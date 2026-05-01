"""
brain.py – Hybrid intent engine.

Intent resolution order:
1. Rule-based pattern matching (fast, offline, always available).
2. Optional local LLM via Ollama (richer NLU when USE_LOCAL_LLM=true).

Returns a structured Intent object consumed by planner.py.

For compound commands ("open chrome and play lo-fi"), use parse_multi()
which splits on "and" / "," and parses each segment independently.
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

def _mode_arg(m: re.Match) -> dict:
    return {"mode": m.group("mode").strip()}

def _git_arg(m: re.Match) -> dict:
    return {"command": m.group("cmd").strip()}


# ---------------------------------------------------------------------------
# NOTE: Rule ordering matters — more specific patterns MUST precede general
# ones.  In particular, every specific "open <X>" variant must appear BEFORE
# the catch-all "open_app" rule at the end of the open-app block.
# ---------------------------------------------------------------------------
_RULES: list[tuple[re.Pattern, str, Any]] = [
    # ---- App control (specific variants first, generic last) ----
    # "open it" / "launch it" / "start it" → reopen the last used app.
    # These rules are also covered by an exact-string pre-check inside
    # Brain.parse() (which runs before rule matching), but the rules below
    # serve as a fallback for any normalised variant the pre-check misses.
    (re.compile(r"\bopen\s+it\b"), "open_last_app", None),
    (re.compile(r"\blaunch\s+it\b"), "open_last_app", None),
    (re.compile(r"\bstart\s+it\b"), "open_last_app", None),
    # URL must be checked before generic open_app.
    # Use .+ so the full URL (including query string) is captured; the
    # segment has already been split on " and " / "," by parse_multi, so
    # there are no other tokens after the URL in a typical voice command.
    (re.compile(r"\bopen\s+(?P<query>https?://.+)"), "open_url", _query_arg),
    # File / folder must be checked before generic open_app
    (re.compile(r"\bopen\s+(?:file|folder)\s+(?P<path>.+)"), "open_file", _file_arg),
    # VS Code project must be checked before generic open_app
    (re.compile(r"\bopen\s+project\s+(?P<path>.+)"), "open_vscode_project", _file_arg),
    # Generic app launcher (catch-all, must be last in this group).
    # Negative lookaheads for "it" prevent shadowing the open_last_app rules
    # above — an additional safeguard since the specific rules are ordered first.
    (re.compile(r"\bopen\s+(?!it\b)(?P<app>.+)"), "open_app", _app_arg),
    (re.compile(r"\blaunch\s+(?!it\b)(?P<app>.+)"), "open_app", _app_arg),
    (re.compile(r"\bstart\s+(?!it\b)(?P<app>.+)"), "open_app", _app_arg),
    (re.compile(r"\bclose\s+(?P<app>.+)"), "close_app", _app_arg),

    # ---- Volume ----
    (re.compile(r"\b(volume|vol)\s+up\b"), "volume_up", None),
    (re.compile(r"\b(volume|vol)\s+down\b"), "volume_down", None),
    (re.compile(r"\bmute\b"), "mute", None),
    (re.compile(r"\bunmute\b"), "unmute", None),
    (re.compile(r"\bset\s+(volume|vol)\s+to\s+(?P<value>\d+)\b"), "set_volume",
     lambda m: {"value": int(m.group("value"))}),

    # ---- System ----
    (re.compile(r"\bshutdown\b"), "shutdown", None),
    (re.compile(r"\brestart\b"), "restart", None),
    (re.compile(r"\bsleep\b"), "sleep", None),
    (re.compile(r"\block\b"), "lock", None),
    (re.compile(r"\bscreenshot\b"), "screenshot", None),

    # ---- Files ----
    (re.compile(r"\bdelete\s+(?:file\s+)?(?P<path>.+)"), "delete_file", _file_arg),
    (re.compile(r"\blist\s+(?:files?\s+in\s+)?(?P<path>.+)"), "list_files", _file_arg),

    # ---- Web / browser ----
    (re.compile(r"\bsearch\s+(?:for\s+)?(?P<query>.+)"), "web_search", _query_arg),
    (re.compile(r"\byoutube\s+(?P<query>.+)"), "youtube_search", _query_arg),
    # "play X on youtube" must come before the generic "play X"
    (re.compile(r"\bplay\s+(?P<query>.+)\s+on\s+youtube\b"), "youtube_search", _query_arg),
    (re.compile(r"\bplay\s+(?P<query>.+)"), "play_media", _query_arg),

    # ---- Modes / routines ----
    (re.compile(r"\b(?:activate\s+)?(?P<mode>study|coding|focus)\s+mode\b"), "activate_mode", _mode_arg),
    (re.compile(r"\brun\s+routine\s+(?P<mode>.+)"), "run_routine", _mode_arg),

    # ---- Developer ----
    (re.compile(r"\brun\s+(?:file\s+)?(?P<path>.+\.py)\b"), "run_python_file", _file_arg),
    (re.compile(r"\bgit\s+(?P<cmd>status|log|pull|push|commit.*)"), "git_command", _git_arg),

    # ---- Memory / info ----
    (re.compile(r"\bwhat\s+(is\s+)?the\s+time\b"), "get_time", None),
    (re.compile(r"\bwhat\s+(is\s+)?the\s+date\b"), "get_date", None),
    (re.compile(r"\bremember\s+that\s+(?P<app>.+)\s+is\s+(?P<path>.+)"), "add_app_mapping",
     lambda m: {"app": m.group("app").strip(), "executable": m.group("path").strip()}),

    # ---- Meta ----
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

    def parse_multi(self, text: str) -> list[Intent]:
        """
        Split a compound command on "and" / "," and parse each segment.

        Example:
            "open chrome and play lo-fi"
            → [Intent("open_app", {"app": "chrome"}),
               Intent("play_media", {"query": "lo-fi"})]

        Single-segment inputs fall through to parse() unchanged so callers
        can always use this method instead of parse().
        """
        norm = normalise(text)
        # Split on literal " and " or a comma followed by optional whitespace.
        # Use a non-greedy approach to avoid over-splitting queries like
        # "search for python and ruby" – each segment is still validated.
        segments = re.split(r"\s+and\s+|,\s*", norm)
        segments = [s.strip() for s in segments if s.strip()]

        if len(segments) <= 1:
            return [self.parse(text)]

        intents: list[Intent] = []
        for seg in segments:
            intent = self.parse(seg)
            intents.append(intent)
            logger.debug("parse_multi segment '%s' → %s %s", seg, intent.name, intent.args)

        logger.info("parse_multi produced %d intents from: '%s'", len(intents), norm)
        return intents
