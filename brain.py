"""
brain.py – Hybrid intent engine.

Intent resolution order:
1. Rule-based pattern matching (fast, offline, always available).
2. Optional local LLM via Ollama (richer NLU when USE_LOCAL_LLM=true).

Returns a structured Intent object consumed by planner.py.
"""

import re
from dataclasses import dataclass, field
from typing import Any

import requests

from config import OLLAMA_MODEL, OLLAMA_TIMEOUT, OLLAMA_URL, USE_LOCAL_LLM
from memory import Memory
from utils import logger, normalise

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Intent:
    name: str
    args: dict[str, Any] = field(default_factory=dict)
    raw: str = ""
    confidence: float = 1.0


# ---------------------------------------------------------------------------
# Rule table
# ---------------------------------------------------------------------------
# Each rule: (compiled_regex, intent_name, arg_extractor_fn | None)

def _app_arg(m: re.Match) -> dict:
    return {"app": m.group("app").strip()}

def _query_arg(m: re.Match) -> dict:
    return {"query": m.group("query").strip()}

def _file_arg(m: re.Match) -> dict:
    return {"path": m.group("path").strip()}

def _vol_arg(m: re.Match) -> dict:
    val = m.group("value")
    return {"value": int(val) if val else None, "direction": m.group(0).split()[0]}

def _mode_arg(m: re.Match) -> dict:
    return {"mode": m.group("mode").strip()}

def _git_arg(m: re.Match) -> dict:
    return {"command": m.group("cmd").strip()}


_RULES: list[tuple[re.Pattern, str, Any]] = [
    # App control
    (re.compile(r"\bopen\s+(?P<app>.+)"), "open_app", _app_arg),
    (re.compile(r"\blaunch\s+(?P<app>.+)"), "open_app", _app_arg),
    (re.compile(r"\bstart\s+(?P<app>.+)"), "open_app", _app_arg),
    (re.compile(r"\bclose\s+(?P<app>.+)"), "close_app", _app_arg),
    (re.compile(r"\bopen\s+it\b"), "open_last_app", None),

    # Volume
    (re.compile(r"\b(volume|vol)\s+up\b"), "volume_up", None),
    (re.compile(r"\b(volume|vol)\s+down\b"), "volume_down", None),
    (re.compile(r"\bmute\b"), "mute", None),
    (re.compile(r"\bunmute\b"), "unmute", None),
    (re.compile(r"\bset\s+(volume|vol)\s+to\s+(?P<value>\d+)\b"), "set_volume",
     lambda m: {"value": int(m.group("value"))}),

    # System
    (re.compile(r"\bshutdown\b"), "shutdown", None),
    (re.compile(r"\brestart\b"), "restart", None),
    (re.compile(r"\bsleep\b"), "sleep", None),
    (re.compile(r"\block\b"), "lock", None),
    (re.compile(r"\bscreenshot\b"), "screenshot", None),

    # Files
    (re.compile(r"\bopen\s+(?:file|folder)\s+(?P<path>.+)"), "open_file", _file_arg),
    (re.compile(r"\bdelete\s+(?:file\s+)?(?P<path>.+)"), "delete_file", _file_arg),
    (re.compile(r"\blist\s+(?:files?\s+in\s+)?(?P<path>.+)"), "list_files", _file_arg),

    # Web / browser
    (re.compile(r"\bsearch\s+(?:for\s+)?(?P<query>.+)"), "web_search", _query_arg),
    (re.compile(r"\byoutube\s+(?P<query>.+)"), "youtube_search", _query_arg),
    (re.compile(r"\bplay\s+(?P<query>.+)\s+on\s+youtube\b"), "youtube_search", _query_arg),
    (re.compile(r"\bopen\s+(?P<query>https?://.+)"), "open_url", _query_arg),

    # Modes / routines
    (re.compile(r"\b(?:activate\s+)?(?P<mode>study|coding|focus)\s+mode\b"), "activate_mode", _mode_arg),
    (re.compile(r"\brun\s+routine\s+(?P<mode>.+)"), "run_routine", _mode_arg),

    # Developer
    (re.compile(r"\brun\s+(?:file\s+)?(?P<path>.+\.py)\b"), "run_python_file", _file_arg),
    (re.compile(r"\bgit\s+(?P<cmd>status|log|pull|push|commit.*)"), "git_command", _git_arg),
    (re.compile(r"\bopen\s+project\s+(?P<path>.+)"), "open_vscode_project", _file_arg),

    # Memory / info
    (re.compile(r"\bwhat\s+(is\s+)?the\s+time\b"), "get_time", None),
    (re.compile(r"\bwhat\s+(is\s+)?the\s+date\b"), "get_date", None),
    (re.compile(r"\bremember\s+that\s+(?P<app>.+)\s+is\s+(?P<path>.+)"), "add_app_mapping",
     lambda m: {"app": m.group("app").strip(), "executable": m.group("path").strip()}),

    # Meta
    (re.compile(r"\bhelp\b"), "help", None),
    (re.compile(r"\bstop\b|\bbye\b|\bexit\b|\bquit\b"), "stop", None),
]


# ---------------------------------------------------------------------------
# LLM fallback
# ---------------------------------------------------------------------------

_LLM_SYSTEM_PROMPT = (
    "You are an intent parser for a Windows voice assistant. "
    "Given a user command, respond with ONLY a JSON object like: "
    '{"intent": "intent_name", "args": {"key": "value"}}. '
    "Use snake_case for intent names. Keep args minimal."
)


def _query_llm(text: str) -> Intent | None:
    if not USE_LOCAL_LLM:
        return None
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": f"Command: {text}\n",
        "system": _LLM_SYSTEM_PROMPT,
        "stream": False,
    }
    try:
        resp = requests.post(OLLAMA_URL, json=payload, timeout=OLLAMA_TIMEOUT)
        resp.raise_for_status()
        raw_json = resp.json().get("response", "")
        import json as _json  # local import to avoid name clash
        data = _json.loads(raw_json)
        return Intent(
            name=data.get("intent", "unknown"),
            args=data.get("args", {}),
            raw=text,
            confidence=0.8,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM fallback failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Brain
# ---------------------------------------------------------------------------

class Brain:
    def __init__(self, memory: Memory) -> None:
        self._memory = memory

    def parse(self, text: str) -> Intent:
        """Return the best Intent for the given raw *text*."""
        norm = normalise(text)
        logger.debug("Brain parsing: '%s'", norm)

        # 1. Context resolution: "open it" → last opened app
        if norm in ("open it", "launch it", "start it"):
            last = self._memory.last_app_opened()
            if last:
                return Intent("open_app", {"app": last}, raw=text)

        # 2. Rule matching
        for pattern, intent_name, extractor in _RULES:
            m = pattern.search(norm)
            if m:
                args = extractor(m) if extractor else {}
                logger.debug("Rule match: %s → %s %s", pattern.pattern, intent_name, args)
                return Intent(intent_name, args, raw=text)

        # 3. LLM fallback
        llm_intent = _query_llm(text)
        if llm_intent:
            return llm_intent

        logger.info("Intent unknown for: '%s'", text)
        return Intent("unknown", {}, raw=text, confidence=0.0)
