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

def _reminder_arg(m: re.Match) -> dict:
    """Extract {minutes, seconds, task} from a reminder regex match."""
    val = int(m.group("value"))
    unit = m.group("unit")
    task = m.group("task").strip() if "task" in m.groupdict() else ""
    if unit.startswith(("hour", "hr")):
        return {"minutes": val * 60, "seconds": 0, "task": task}
    if unit.startswith(("minute", "min")):
        return {"minutes": val, "seconds": 0, "task": task}
    return {"minutes": 0, "seconds": val, "task": task}

def _folder_with_location_arg(m: re.Match) -> dict:
    return {"name": m.group("name").strip(), "location": m.group("location").strip()}

def _folder_name_arg(m: re.Match) -> dict:
    return {"name": m.group("name").strip(), "location": ""}


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

    # ---- Brightness ----
    (re.compile(r"\bbrightness\s+up\b|\bincrease\s+brightness\b"), "brightness_up", None),
    (re.compile(r"\bbrightness\s+down\b|\bdecrease\s+brightness\b|\bdim\s+(?:the\s+)?screen\b"), "brightness_down", None),
    (re.compile(r"\bset\s+brightness\s+to\s+(?P<value>\d+)\b"), "set_brightness",
     lambda m: {"value": int(m.group("value"))}),

    # ---- System ----
    (re.compile(r"\bshutdown\b"), "shutdown", None),
    (re.compile(r"\brestart\b"), "restart", None),
    (re.compile(r"\bsleep\b"), "sleep", None),
    (re.compile(r"\block\b"), "lock", None),
    (re.compile(r"\bscreenshot\b"), "screenshot", None),

    # ---- Desktop / window management ----
    (re.compile(r"\bshow\s+desktop\b|\bminimize\s+all\b|\bminimise\s+all\b"), "show_desktop", None),

    # ---- Window snapping ----
    (re.compile(
        r"\b(?:snap|move|pin)\s+(?:(?:the\s+)?window\s+)?(?:to\s+)?(?P<direction>left|right|up|down|maximize|maximize|minimize)\b"
    ), "snap_window", lambda m: {"direction": m.group("direction").strip()}),

    # ---- Recycle bin ----
    (re.compile(r"\bempty\s+(?:the\s+)?(?:recycle\s+bin|trash|recycling)\b"), "empty_recycle_bin", None),

    # ---- Speech rate ----
    (re.compile(r"\bspeak\s+(?:faster|quicker|fast|quick)\b"), "speech_rate_up", None),
    (re.compile(r"\bspeak\s+(?:slower|slow|more\s+slowly)\b"), "speech_rate_down", None),
    (re.compile(r"\bset\s+speech\s+(?:rate|speed)\s+to\s+(?P<rate>\d+)\b"),
     "set_speech_rate", lambda m: {"rate": int(m.group("rate"))}),

    # ---- Media controls ----
    # "pause" at start of utterance, or "pause music/media" anywhere
    (re.compile(r"^pause\b|\bpause\s+(?:music|media|track|song|audio)\b"), "media_pause_play", None),
    (re.compile(r"\bresume\s+(?:music|media|track|song|audio)\b"), "media_pause_play", None),
    (re.compile(r"\b(?:next|skip)\s+(?:track|song|music|media)\b"), "media_next", None),
    (re.compile(r"\b(?:previous|prev)\s+(?:track|song|music|media)\b"), "media_previous", None),

    # ---- Type text ----
    # Anchored to start so "what type is…" doesn't trigger this rule
    (re.compile(r"^type\s+(?:out\s+)?(?P<text>.+)"),
     "type_text", lambda m: {"text": m.group("text").strip()}),

    # ---- Press hotkey ----
    (re.compile(r"^press\s+(?P<keys>.+)"),
     "press_hotkey", lambda m: {"keys": m.group("keys").strip()}),

    # ---- Files ----
    # create_folder must precede delete/list so "create folder" isn't swallowed.
    (re.compile(
        r"\b(?:create|make)\s+(?:a\s+)?(?:new\s+)?folder\s+"
        r"(?:named?\s+|called\s+)?(?P<name>.+?)"
        r"\s+(?:in|at|on|inside)\s+(?P<location>.+)"
    ), "create_folder", _folder_with_location_arg),
    (re.compile(
        r"\b(?:create|make)\s+(?:a\s+)?(?:new\s+)?folder\s+"
        r"(?:named?\s+|called\s+)?(?P<name>.+)"
    ), "create_folder", _folder_name_arg),
    (re.compile(r"\bdelete\s+(?:file\s+)?(?P<path>.+)"), "delete_file", _file_arg),
    # ---- Running processes (must come before list_files to avoid misparse) ----
    (re.compile(r"\blist\s+(?:running\s+)?(?:apps?|applications?|processes?|tasks?)\b"),
     "list_running_apps", None),
    (re.compile(r"\bkill\s+(?:process\s+)?(?P<app>.+)"),
     "kill_process", lambda m: {"app": m.group("app").strip()}),
    # ---- File search ----
    (re.compile(
        r"\bfind\s+(?:files?\s+)?(?P<query>.+?)\s+in\s+(?P<location>\S.*)$"
    ), "search_files",
     lambda m: {"query": m.group("query").strip(), "location": m.group("location").strip()}),
    (re.compile(r"\bfind\s+(?:files?\s+)?(?P<query>.+)"),
     "search_files", lambda m: {"query": m.group("query").strip(), "location": ""}),
    (re.compile(r"\blist\s+(?:files?\s+in\s+)?(?P<path>.+)"), "list_files", _file_arg),

    # ---- Web / browser ----
    # Price/rate/cost queries → web search (fast, no LLM needed)
    (re.compile(r"\b(?:what\s+(?:is|s)\s+)?(?:the\s+)?(?P<query>.+?)\s+(?:price|rate|cost|price\s+today)\b"), "web_search", _query_arg),
    (re.compile(r"\bsearch\s+(?:for\s+)?(?P<query>.+)"), "web_search", _query_arg),
    (re.compile(r"\b(?:search\s+for\s+)?(?P<query>.+?)\s+on\s+youtube\b"), "youtube_search", _query_arg),
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
    (re.compile(r"\bwhat\s+(is\s+|s\s+)?the\s+time\b"), "get_time", None),
    (re.compile(r"\bwhat\s+(is\s+|s\s+)?the\s+date\b"), "get_date", None),
    (re.compile(r"\bremember\s+that\s+(?P<app>.+)\s+is\s+(?P<path>.+)"), "add_app_mapping",
     lambda m: {"app": m.group("app").strip(), "executable": m.group("path").strip()}),

    # ---- Battery / system ----
    (re.compile(r"\bbattery\b"), "get_battery", None),
    (re.compile(r"\b(?:system\s+info|cpu\s+usage|ram\s+usage|memory\s+usage|system\s+status)\b"),
     "get_system_info", None),

    # ---- Calculator ----
    # "calculate 5 plus 3", "compute 10 divided by 2"
    (re.compile(r"\b(?:calculate|compute)\s+(?P<expr>.+)"),
     "calculate", lambda m: {"expression": m.group("expr").strip()}),
    # "what is 5 times 6" — only if the expression starts with a digit
    (re.compile(r"\bwhat\s+(?:is|s)\s+(?P<expr>[0-9].+)"),
     "calculate", lambda m: {"expression": m.group("expr").strip()}),

    # ---- Unit conversion ----
    # "convert 100 km to miles", "convert 5 kg to pounds"
    (re.compile(
        r"\bconvert\s+(?P<value>\d+)\s+(?P<from_unit>[a-z]+(?:\s+[a-z]+)?)"
        r"\s+(?:to|into?)\s+(?P<to_unit>[a-z]+(?:\s+[a-z]+)?)\b"
    ), "convert_units",
     lambda m: {
         "value": int(m.group("value")),
         "from_unit": m.group("from_unit").strip(),
         "to_unit":   m.group("to_unit").strip(),
     }),
    # "how many miles is 10 km"
    (re.compile(
        r"\bhow\s+many\s+(?P<to_unit>[a-z]+(?:\s+[a-z]+)?)"
        r"\s+(?:is|are|in)\s+(?P<value>\d+)\s+(?P<from_unit>[a-z]+(?:\s+[a-z]+)?)\b"
    ), "convert_units",
     lambda m: {
         "value":     int(m.group("value")),
         "from_unit": m.group("from_unit").strip(),
         "to_unit":   m.group("to_unit").strip(),
     }),

    # ---- News headlines ----
    # Specific source queries must come before the generic "news" rule.
    (re.compile(r"\bnews\s+(?:from|about|on|in)\s+(?P<source>.+)"),
     "get_news", lambda m: {"source": m.group("source").strip()}),
    (re.compile(r"\b(?:get|read|show)\s+(?:the\s+)?(?:latest\s+)?news\b"),
     "get_news", lambda m: {"source": "", "count": 5}),
    # "what is the news" / "what's the news" (normalised: "what s the news")
    (re.compile(r"\bwhat\s+(?:is|are|s)\s+(?:the\s+)?(?:latest\s+)?news\b"),
     "get_news", lambda m: {"source": "", "count": 5}),

    # ---- Network / Wi-Fi ----
    (re.compile(r"\bwhat\s+(?:is\s+)?(?:my\s+)?(?:ip|ip\s+address)\b"),
     "get_ip_address", None),
    (re.compile(r"\b(?:check|test)\s+(?:my\s+)?(?:internet|connection|network)\b"),
     "check_internet", None),
    # "list wifi", "show wireless networks"
    (re.compile(r"\blist\s+(?:available\s+)?(?:wifi|wi\s*fi|wireless)\s*(?:networks?)?\b"),
     "list_wifi_networks", None),
    (re.compile(r"\bconnect\s+(?:to\s+)?(?:wifi|wi\s*fi|wireless)\s+(?P<ssid>.+)"),
     "connect_wifi", lambda m: {"ssid": m.group("ssid").strip()}),

    # ---- Knowledge queries → answered directly by LLM (phi3:mini) ----
    # These rules MUST appear after the specific "what is the time/date" and
    # "what is [digit]" (calculate) rules above so those take priority.
    # Rule ordering guarantees: the calculate rule at line 152 requires the
    # expression to start with a digit, so "what is 2 plus 2" → calculate,
    # while "what is Python" (no leading digit) falls through to this rule.
    # Each segment reaching _parse_rules has already been split on "and"/"," by
    # parse_multi, so the greedy `(.+)` captures the full remaining query text.
    (re.compile(r"\bwho\s+(?:is|was|are|were)\s+(?P<query>.+)"), "ask_llm", _query_arg),
    (re.compile(r"\bwhat\s+(?:is|are|was|were)\s+(?P<query>.+)"), "ask_llm", _query_arg),
    (re.compile(r"\bhow\s+(?:do|does|did|can|to)\s+(?P<query>.+)"), "ask_llm", _query_arg),
    (re.compile(r"\btell\s+me\s+about\s+(?P<query>.+)"), "ask_llm", _query_arg),
    (re.compile(r"\bexplain\s+(?P<query>.+)"), "ask_llm", _query_arg),
    (re.compile(r"\bdefine\s+(?P<query>.+)"), "ask_llm", _query_arg),
    (re.compile(r"\bwhen\s+(?:is|was|did|are|were)\s+(?P<query>.+)"), "ask_llm", _query_arg),
    (re.compile(r"\bwhere\s+(?:is|are|was|were)\s+(?P<query>.+)"), "ask_llm", _query_arg),
    (re.compile(r"\bwhy\s+(?:is|are|was|were|does|do|did)\s+(?P<query>.+)"), "ask_llm", _query_arg),

    # ---- Timer ----
    (re.compile(
        r"\bset\s+(?:a\s+)?(?P<value>\d+)\s*(?P<unit>minute|min|second|sec)s?\s+timer\b"
    ), "set_timer",
     lambda m: {"minutes": int(m.group("value")) if m.group("unit").startswith("m") else 0,
                "seconds": int(m.group("value")) if m.group("unit").startswith("s") else 0}),
    (re.compile(
        r"\bset\s+(?:a\s+)?timer\s+(?:for\s+)?(?P<value>\d+)\s*(?P<unit>minute|min|second|sec)s?\b"
    ), "set_timer",
     lambda m: {"minutes": int(m.group("value")) if m.group("unit").startswith("m") else 0,
                "seconds": int(m.group("value")) if m.group("unit").startswith("s") else 0}),

    # ---- Notes ----
    (re.compile(r"\btake\s+(?:a\s+)?note\s+(?:that\s+)?(?P<note>.+)"), "take_note",
     lambda m: {"note": m.group("note").strip()}),
    (re.compile(r"\bread\s+(?:my\s+)?notes?\b"), "read_notes", None),
    (re.compile(r"\bclear\s+(?:my\s+)?notes?\b"), "clear_notes", None),

    # ---- Reminders ----
    # "remind me in 10 minutes for / to / about <task>"
    (re.compile(
        r"\bremind\s+(?:me\s+)?in\s+(?P<value>\d+)\s*(?P<unit>hour|hr|minute|min|second|sec)s?"
        r"\s+(?:for\s+|to\s+|about\s+)?(?P<task>.+)"
    ), "set_reminder", _reminder_arg),
    # "remind me <task> in 10 minutes" (task-first order)
    (re.compile(
        r"\bremind\s+(?:me\s+)?(?:to\s+|about\s+)?(?P<task>.+?)"
        r"\s+in\s+(?P<value>\d+)\s*(?P<unit>hour|hr|minute|min|second|sec)s?\b"
    ), "set_reminder", _reminder_arg),
    # "set a reminder for / in 10 minutes <task>"
    (re.compile(
        r"\b(?:set\s+(?:a\s+)?)?reminder\s+(?:for\s+|in\s+)?(?P<value>\d+)\s*(?P<unit>hour|hr|minute|min|second|sec)s?"
        r"\s+(?:for\s+|to\s+|about\s+)?(?P<task>.+)"
    ), "set_reminder", _reminder_arg),
    # "list / show reminders"
    (re.compile(r"\b(?:list|show)\s+(?:my\s+)?reminders?\b"), "list_reminders", None),
    # "cancel reminder for <task>"
    (re.compile(r"\bcancel\s+(?:my\s+)?reminder(?:\s+(?:for|about)\s+)?(?P<task>.+)"),
     "cancel_reminder", lambda m: {"task": m.group("task").strip()}),

    # ---- Clipboard ----
    (re.compile(r"\b(?:read|what(?:'s|\s+is)\s+in)\s+(?:my\s+)?clipboard\b"),
     "read_clipboard", None),
    (re.compile(r"\b(?:write|copy|put)\s+(?P<text>.+?)\s+(?:to|in(?:to)?)\s+(?:my\s+)?clipboard\b"),
     "write_clipboard", lambda m: {"text": m.group("text").strip()}),

    # ---- Weather ----
    (re.compile(r"\bweather\s+(?:in\s+|at\s+|for\s+)?(?P<query>\S.+)"), "get_weather",
     lambda m: {"location": m.group("query").strip()}),
    (re.compile(r"\bweather\b"), "get_weather", lambda m: {"location": ""}),

    # ---- Meta ----
    (re.compile(r"\bhelp\b"), "help", None),
    (re.compile(r"\bstop\b|\bbye\b|\bexit\b|\bquit\b"), "stop", None),
]


# ---------------------------------------------------------------------------
# LLM fallback
# ---------------------------------------------------------------------------

_LLM_SYSTEM_PROMPT = (
    "You are Jarvis, a Windows voice assistant. "
    "Parse the user command into a JSON array of intents only. "
    "Do not include any text, markdown, or explanation outside the JSON. "
    "Use snake_case for intent names. Keep args minimal. "
    "\n\nValid intents:\n"
    "- open_app: [{\"intent\": \"open_app\", \"args\": {\"app\": \"chrome\"}}]\n"
    "- web_search: [{\"intent\": \"web_search\", \"args\": {\"query\": \"python tutorials\"}}]\n"
    "- youtube_search: [{\"intent\": \"youtube_search\", \"args\": {\"query\": \"music\"}}]\n"
    "- volume_up: [{\"intent\": \"volume_up\", \"args\": {}}]\n"
    "- volume_down: [{\"intent\": \"volume_down\", \"args\": {}}]\n"
    "- set_volume: [{\"intent\": \"set_volume\", \"args\": {\"value\": 50}}]\n"
    "- mute: [{\"intent\": \"mute\", \"args\": {}}]\n"
    "- brightness_up: [{\"intent\": \"brightness_up\", \"args\": {}}]\n"
    "- brightness_down: [{\"intent\": \"brightness_down\", \"args\": {}}]\n"
    "- set_brightness: [{\"intent\": \"set_brightness\", \"args\": {\"value\": 70}}]\n"
    "- get_time: [{\"intent\": \"get_time\", \"args\": {}}]\n"
    "- get_date: [{\"intent\": \"get_date\", \"args\": {}}]\n"
    "- screenshot: [{\"intent\": \"screenshot\", \"args\": {}}]\n"
    "- show_desktop: [{\"intent\": \"show_desktop\", \"args\": {}}]\n"
    "- empty_recycle_bin: [{\"intent\": \"empty_recycle_bin\", \"args\": {}}]\n"
    "- media_pause_play: [{\"intent\": \"media_pause_play\", \"args\": {}}]\n"
    "- media_next: [{\"intent\": \"media_next\", \"args\": {}}]\n"
    "- media_previous: [{\"intent\": \"media_previous\", \"args\": {}}]\n"
    "- type_text: [{\"intent\": \"type_text\", \"args\": {\"text\": \"hello world\"}}]\n"
    "- press_hotkey: [{\"intent\": \"press_hotkey\", \"args\": {\"keys\": \"ctrl c\"}}]\n"
    "- shutdown: [{\"intent\": \"shutdown\", \"args\": {}}]\n"
    "- create_folder: [{\"intent\": \"create_folder\", \"args\": {\"name\": \"Photos\", \"location\": \"desktop\"}}]\n"
    "- set_reminder: [{\"intent\": \"set_reminder\", \"args\": {\"minutes\": 10, \"seconds\": 0, \"task\": \"meeting\"}}]\n"
    "- list_reminders: [{\"intent\": \"list_reminders\", \"args\": {}}]\n"
    "- cancel_reminder: [{\"intent\": \"cancel_reminder\", \"args\": {\"task\": \"meeting\"}}]\n"
    "- read_clipboard: [{\"intent\": \"read_clipboard\", \"args\": {}}]\n"
    "- write_clipboard: [{\"intent\": \"write_clipboard\", \"args\": {\"text\": \"some text\"}}]\n"
    "- send_whatsapp_message: [{\"intent\": \"send_whatsapp_message\", \"args\": {\"contact\": \"mummy\", \"message\": \"hey\"}}]\n"
    "- ask_llm: [{\"intent\": \"ask_llm\", \"args\": {\"query\": \"who is Elon Musk\"}}]\n"
    "- chat_response: [{\"intent\": \"chat_response\", \"args\": {\"message\": \"Elon Musk is ...\"}}]\n"
    "- help: [{\"intent\": \"help\", \"args\": {}}]\n"
    "- stop: [{\"intent\": \"stop\", \"args\": {}}]\n"
    "\nFor reminders, always include minutes (int), seconds (int), and task (string). "
    "If the user says 'in 2 hours', set minutes=120. "
    "If the user asks who/what/where/when/why/how about a person, place, or concept, return ask_llm. "
    "If the user wants to create or make a new folder, return create_folder. "
    "If the user wants to pause, play, next, or previous track, return the matching media intent. "
    "If you cannot map to a known command, return [{\"intent\": \"unknown\", \"args\": {}}]."
)



def _query_llm(text: str) -> list[Intent] | None:
    if not USE_LOCAL_LLM:
        return None

    endpoint = OLLAMA_URL.rstrip("/")
    if endpoint.endswith("/api/generate") or endpoint.endswith("/v1/generate"):
        request_style = "prompt"
    elif endpoint.endswith("/chat/completions") or endpoint.endswith("/completions"):
        request_style = "openai"
    else:
        endpoint = f"{endpoint}/v1/chat/completions"
        request_style = "openai"

    logger.debug("LLM request: %s model=%s style=%s text='%s'", endpoint, OLLAMA_MODEL, request_style, text)

    if request_style == "openai":
        payload = {
            "model": OLLAMA_MODEL,
            "messages": [
                {"role": "system", "content": _LLM_SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            "temperature": 0.0,
            "max_tokens": 80,
        }
    else:
        payload = {
            "model": OLLAMA_MODEL,
            "prompt": f"{_LLM_SYSTEM_PROMPT}\n\nCommand: {text}\n",
            "stream": False,
            "temperature": 0.0,
            "max_tokens": 80,
        }

    try:
        resp = requests.post(endpoint, json=payload, timeout=OLLAMA_TIMEOUT)
        resp.raise_for_status()
        response_data = resp.json()
        logger.debug("LLM raw response: %s", response_data)
        raw_response = ""

        if isinstance(response_data, dict):
            if "response" in response_data and isinstance(response_data["response"], str):
                raw_response = response_data["response"].strip()
            elif "choices" in response_data and response_data["choices"]:
                first_choice = response_data["choices"][0]
                if isinstance(first_choice, dict):
                    if "message" in first_choice and isinstance(first_choice["message"], dict):
                        raw_response = first_choice["message"].get("content", "").strip()
                    elif "text" in first_choice:
                        raw_response = first_choice.get("text", "").strip()
            elif "result" in response_data and isinstance(response_data["result"], str):
                raw_response = response_data["result"].strip()
        elif isinstance(response_data, str):
            raw_response = response_data.strip()

        import json as _json  # local import to avoid name clash
        data = None
        if raw_response:
            raw_text = raw_response
            logger.debug("LLM parsing response: %s", raw_text)
            for attempt in range(2):
                try:
                    data = _json.loads(raw_text)
                    logger.debug("LLM JSON parsed successfully: %s", data)
                    break
                except ValueError:
                    start = raw_text.find("[")
                    end = raw_text.rfind("]")
                    if start != -1 and end != -1 and end > start:
                        raw_text = raw_text[start:end + 1]
                    else:
                        start = raw_text.find("{")
                        end = raw_text.rfind("}")
                        if start != -1 and end != -1 and end > start:
                            raw_text = raw_text[start:end + 1]
                        else:
                            data = None
                            break

        if isinstance(data, list):
            logger.info("LLM returned list of intents: %d intents", len(data))
            return [Intent(
                name=item.get("intent", "unknown"),
                args=item.get("args", {}) if isinstance(item, dict) else {},
                raw=text,
                confidence=0.8,
            ) for item in data]

        if isinstance(data, dict):
            if "intent" in data:
                logger.info("LLM returned single intent: %s", data.get("intent"))
                return [Intent(
                    name=data.get("intent", "unknown"),
                    args=data.get("args", {}),
                    raw=text,
                    confidence=0.8,
                )]
            if "response" in data and isinstance(data["response"], str):
                logger.info("LLM returned response: %s", data["response"][:50])
                return [Intent(
                    name="chat_response",
                    args={"message": data["response"]},
                    raw=text,
                    confidence=0.6,
                )]

        if raw_response:
            logger.info("LLM returning raw response: %s", raw_response[:50])
            return [Intent(
                name="chat_response",
                args={"message": raw_response},
                raw=text,
                confidence=0.5,
            )]

        logger.warning("LLM returned empty response for: %s", text)
        return None
    except requests.Timeout:
        logger.error("LLM timeout (>%d sec) for: %s", OLLAMA_TIMEOUT, text)
        return None
    except requests.ConnectionError as e:
        logger.error("LLM connection error: %s (is Ollama running on %s?)", e, OLLAMA_URL)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.error("LLM fallback failed: %s", exc, exc_info=True)
        return None


_LLM_ANSWER_PROMPT = (
    "You are Jarvis, a helpful voice assistant. "
    "Answer the user's question concisely in 2-3 sentences. "
    "Do not use markdown, bullet points, headers, or special characters. "
    "Respond in plain English suitable for text-to-speech."
)


def query_llm_direct(question: str) -> str | None:
    """
    Ask phi3:mini (or the configured Ollama model) for a plain-text answer.

    Returns the answer string, or None if the LLM is unavailable or fails.
    This function is intentionally separate from _query_llm which is only
    used for structured intent parsing.
    """
    if not USE_LOCAL_LLM:
        return None

    endpoint = OLLAMA_URL.rstrip("/")
    # Always use the chat/completions endpoint for conversational queries.
    if not endpoint.endswith("/chat/completions"):
        for suffix in ("/api/generate", "/v1/completions", "/completions", "/generate"):
            if endpoint.endswith(suffix):
                endpoint = endpoint[: -len(suffix)]
                break
        endpoint = f"{endpoint}/v1/chat/completions"

    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": _LLM_ANSWER_PROMPT},
            {"role": "user", "content": question},
        ],
        "temperature": 0.3,
        "max_tokens": 200,
    }

    logger.debug("query_llm_direct: %s (model=%s)", question[:60], OLLAMA_MODEL)
    try:
        resp = requests.post(endpoint, json=payload, timeout=OLLAMA_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict) and "choices" in data and data["choices"]:
            msg = data["choices"][0].get("message", {})
            answer = msg.get("content", "").strip()
            if answer:
                logger.info("LLM direct answer (%d chars)", len(answer))
                return answer
        if isinstance(data, dict) and "response" in data:
            answer = data["response"].strip()
            if answer:
                return answer
        logger.warning("query_llm_direct: empty response from LLM")
        return None
    except requests.Timeout:
        logger.error("query_llm_direct timeout for: %s", question[:60])
        return None
    except requests.ConnectionError as exc:
        logger.error("query_llm_direct connection error: %s", exc)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.error("query_llm_direct failed: %s", exc, exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Brain
# ---------------------------------------------------------------------------

class Brain:
    def __init__(self, memory: Memory) -> None:
        self._memory = memory

    # ------------------------------------------------------------------
    # Internal: rule-based only (no LLM)
    # ------------------------------------------------------------------
    def _parse_rules(self, text: str) -> list[Intent]:
        """Run only rule-based matching.  Returns [Intent("unknown")] on miss."""
        norm = normalise(text)

        # ------------------------------------------------------------------
        # Context resolution: short follow-up commands resolved from memory
        # ------------------------------------------------------------------
        # "open it / launch it / start it" → re-open last app
        if norm in ("open it", "launch it", "start it"):
            last = self._memory.last_app_opened()
            if last:
                return [Intent("open_app", {"app": last}, raw=text)]

        # "close it" → close the last opened app
        if norm in ("close it", "stop it", "quit it"):
            last = self._memory.last_app_opened()
            if last:
                return [Intent("close_app", {"app": last}, raw=text)]

        # "search that again" / "search again" → repeat last web search
        if re.search(r"\bsearch\s+(?:that|it)\s+again\b|\bsearch\s+again\b", norm):
            q = self._memory.get_context("last_search_query")
            if q:
                return [Intent("web_search", {"query": q}, raw=text)]

        # "play that again" / "play it again" → repeat last media query
        if re.search(r"\bplay\s+(?:that|it)\s+again\b|\bplay\s+again\b", norm):
            q = self._memory.get_context("last_media_query")
            if q:
                return [Intent("play_media", {"query": q}, raw=text)]

        # ------------------------------------------------------------------
        # Standard rule matching
        # ------------------------------------------------------------------
        for pattern, intent_name, extractor in _RULES:
            m = pattern.search(norm)
            if m:
                args = extractor(m) if extractor else {}
                logger.debug("Rule match: %s → %s %s", pattern.pattern, intent_name, args)
                return [Intent(intent_name, args, raw=text)]

        return [Intent("unknown", {}, raw=text, confidence=0.0)]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def parse(self, text: str) -> list[Intent]:
        """Return a list of best Intent(s) for the given raw *text*."""
        logger.debug("Brain parsing: '%s'", normalise(text))

        # 1. Rule matching (fast, offline)
        intents = self._parse_rules(text)
        if intents[0].name != "unknown":
            return intents

        # 2. LLM fallback (only for unrecognised commands)
        llm_intents = _query_llm(text)
        if llm_intents:
            return llm_intents

        # 3. Smart fallback: treat any multi-word utterance as a web search so
        #    the user always gets a useful response even without an LLM.
        norm_text = normalise(text)
        if len(norm_text.split()) >= 2:
            logger.info("Unknown intent - falling back to web search for: '%s'", text)
            return [Intent("web_search", {"query": text}, raw=text, confidence=0.3)]

        logger.info("Intent unknown for: '%s'", text)
        return [Intent("unknown", {}, raw=text, confidence=0.0)]

    def parse_multi(self, text: str) -> list[Intent]:
        """
        Parse compound commands split on 'and' / ','.

        Fast path: split → rule-match each segment.  If every segment is
        recognised by rules, return immediately without touching the LLM.
        Slow path (LLM): only invoked when at least one segment is unknown,
        in case the LLM can resolve the ambiguity as a multi-step command.
        """
        norm = normalise(text)
        segments = re.split(r"\s+and\s+|,\s*", norm)
        segments = [s.strip() for s in segments if s.strip()]

        if len(segments) <= 1:
            return self.parse(text)

        # --- Fast path: rule-based matching for each segment ---
        rule_intents: list[Intent] = []
        for seg in segments:
            seg_intents = self._parse_rules(seg)
            rule_intents.extend(seg_intents)
            logger.debug("parse_multi segment '%s' → %s", seg, seg_intents[0].name)

        if all(i.name != "unknown" for i in rule_intents):
            logger.info("parse_multi (rules) produced %d intents from: '%s'",
                        len(rule_intents), norm)
            return rule_intents

        # --- Slow path: ask LLM about the full compound command ---
        llm_intents = _query_llm(text)
        if llm_intents and len(llm_intents) > 1:
            logger.debug("LLM parsed multi-step: %d intents", len(llm_intents))
            return llm_intents

        # --- Fallback: per-segment parse (includes per-segment LLM if needed) ---
        intents: list[Intent] = []
        for seg in segments:
            seg_intents = self.parse(seg)
            intents.extend(seg_intents)
            logger.debug("parse_multi(fallback) segment '%s' → %d intent(s)",
                         seg, len(seg_intents))

        logger.info("parse_multi produced %d intents from: '%s'", len(intents), norm)
        return intents
