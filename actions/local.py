"""
actions/local.py – Fully offline local utility actions.

Provides: calculator, countdown timer, notes (take/read/clear), and
weather lookup via the public wttr.in service (requires internet but
no API key).
"""

import ast
import operator
import re
import threading
import time
import urllib.parse
from datetime import datetime
from pathlib import Path

import requests

from config import BASE_DIR
from utils import logger, speak

NOTES_FILE = BASE_DIR / "notes.txt"
MAX_RECENT_NOTES = 5  # number of most-recent notes spoken by read_notes()

# ---------------------------------------------------------------------------
# Safe math evaluator (no eval(), uses ast)
# ---------------------------------------------------------------------------
_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
}


def _safe_eval(expr: str) -> float:
    """Evaluate a simple arithmetic expression safely using ast."""
    # Translate spoken words to symbols before parsing
    expr = expr.lower()
    expr = re.sub(r"\bplus\b", "+", expr)
    expr = re.sub(r"\bminus\b", "-", expr)
    expr = re.sub(r"\btimes\b|\bmultiplied\s+by\b", "*", expr)
    expr = re.sub(r"\bdivided\s+by\b|\bover\b", "/", expr)
    expr = re.sub(r"\bto\s+the\s+power\s+of\b|\bpower\b", "**", expr)
    expr = re.sub(r"\bsquared\b", "**2", expr)
    expr = re.sub(r"\bcubed\b", "**3", expr)
    # Keep only characters valid in arithmetic expressions
    expr = re.sub(r"[^0-9+\-*/().\s]", "", expr).strip()

    def _eval(node: ast.expr) -> float:
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.BinOp) and type(node.op) in _OPERATORS:
            return _OPERATORS[type(node.op)](_eval(node.left), _eval(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPERATORS:
            return _OPERATORS[type(node.op)](_eval(node.operand))
        raise ValueError(f"Unsupported expression node: {ast.dump(node)}")

    tree = ast.parse(expr, mode="eval")
    return _eval(tree.body)


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

class LocalActions:
    # ------------------------------------------------------------------
    # Calculator
    # ------------------------------------------------------------------
    def calculate(self, expression: str = "") -> None:
        if not expression:
            speak("Please provide a math expression to calculate.")
            return
        try:
            result = _safe_eval(expression)
            # Format nicely: drop unnecessary decimals
            if result == int(result):
                answer = str(int(result))
            else:
                answer = f"{result:.4f}".rstrip("0").rstrip(".")
            logger.info("Calculate '%s' = %s", expression, answer)
            speak(f"The answer is {answer}.")
        except Exception as exc:
            logger.warning("Calculate failed for '%s': %s", expression, exc)
            speak("Sorry, I couldn't calculate that expression.")

    # ------------------------------------------------------------------
    # Timer
    # ------------------------------------------------------------------
    def set_timer(self, minutes: int = 0, seconds: int = 0) -> None:
        total = int(minutes) * 60 + int(seconds)
        if total <= 0:
            speak("Please specify a valid timer duration.")
            return

        parts = []
        if minutes:
            parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
        if seconds:
            parts.append(f"{seconds} second{'s' if seconds != 1 else ''}")
        duration_str = " and ".join(parts)

        speak(f"Timer set for {duration_str}.")
        logger.info("Timer started: %d seconds", total)

        def _alarm():
            time.sleep(total)
            speak(f"Your {duration_str} timer is done!")

        threading.Thread(target=_alarm, daemon=True).start()

    # ------------------------------------------------------------------
    # Notes
    # ------------------------------------------------------------------
    def take_note(self, note: str = "") -> None:
        if not note:
            speak("What would you like me to note?")
            return
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        entry = f"[{ts}] {note}\n"
        with open(NOTES_FILE, "a", encoding="utf-8") as f:
            f.write(entry)
        logger.info("Note saved: %s", note)
        speak("Note saved.")

    def read_notes(self) -> None:
        if not NOTES_FILE.exists() or NOTES_FILE.stat().st_size == 0:
            speak("You have no notes yet.")
            return
        with open(NOTES_FILE, "r", encoding="utf-8") as f:
            lines = [l.rstrip() for l in f if l.strip()]
        if not lines:
            speak("You have no notes yet.")
            return
        recent = lines[-MAX_RECENT_NOTES:]  # Read up to the last MAX_RECENT_NOTES notes
        speak(f"Your recent notes: {'. '.join(recent)}.")

    def clear_notes(self) -> None:
        if NOTES_FILE.exists():
            NOTES_FILE.write_text("", encoding="utf-8")
        speak("All notes cleared.")

    # ------------------------------------------------------------------
    # Weather  (via public wttr.in, no API key needed)
    # ------------------------------------------------------------------
    def get_weather(self, location: str = "") -> None:
        loc = location.strip() or ""
        path = urllib.parse.quote(loc) if loc else ""
        url = f"https://wttr.in/{path}?format=%C,+%t,+humidity+%h"
        try:
            resp = requests.get(
                url,
                headers={"Accept": "text/plain", "User-Agent": "curl/7.0"},
                timeout=8,
            )
            resp.raise_for_status()
            weather = resp.text.strip()
            where = f" in {location}" if location else ""
            speak(f"Weather{where}: {weather}.")
            logger.info("Weather%s: %s", where, weather)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Weather lookup failed: %s", exc)
            speak("Sorry, I couldn't retrieve the weather right now.")
