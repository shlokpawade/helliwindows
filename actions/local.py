"""
actions/local.py – Fully offline local utility actions.

Provides: calculator, countdown timer, reminders, notes (take/read/clear),
clipboard read, and weather lookup via the public wttr.in service (requires
internet but no API key).
"""

import ast
import operator
import re
import subprocess
import threading
import time
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

import requests

from config import BASE_DIR
from utils import logger, speak, speak_async

NOTES_FILE = BASE_DIR / "notes.txt"
MAX_RECENT_NOTES = 5  # number of most-recent notes spoken by read_notes()

# ---------------------------------------------------------------------------
# Reminder store (in-memory; thread-safe via lock)
# ---------------------------------------------------------------------------

class _Reminder(NamedTuple):
    id: int
    task: str
    fire_at: float     # monotonic clock value (time.monotonic())
    label: str         # human-readable duration string


class _ReminderStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._reminders: list[_Reminder] = []
        self._next_id = 1

    def add(self, task: str, total_seconds: int, duration_label: str) -> _Reminder:
        with self._lock:
            rid = self._next_id
            self._next_id += 1
            r = _Reminder(
                id=rid,
                task=task,
                fire_at=time.monotonic() + total_seconds,
                label=duration_label,
            )
            self._reminders.append(r)
        return r

    def remove(self, rid: int) -> bool:
        with self._lock:
            before = len(self._reminders)
            self._reminders = [r for r in self._reminders if r.id != rid]
            return len(self._reminders) < before

    def list_all(self) -> list[_Reminder]:
        with self._lock:
            return list(self._reminders)

    def cancel_by_task(self, fragment: str) -> int:
        """Cancel all reminders whose task contains *fragment*; returns count."""
        with self._lock:
            before = len(self._reminders)
            self._reminders = [
                r for r in self._reminders
                if fragment.lower() not in r.task.lower()
            ]
            return before - len(self._reminders)


_reminder_store = _ReminderStore()


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

        speak_async(f"Timer set for {duration_str}.")
        logger.info("Timer started: %d seconds", total)

        def _alarm():
            time.sleep(total)
            speak(f"Your {duration_str} timer is done!")

        threading.Thread(target=_alarm, daemon=True).start()

    # ------------------------------------------------------------------
    # Reminders
    # ------------------------------------------------------------------
    @staticmethod
    def _build_duration_str(minutes: int, seconds: int) -> str:
        parts = []
        if minutes:
            parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
        if seconds:
            parts.append(f"{seconds} second{'s' if seconds != 1 else ''}")
        return " and ".join(parts) if parts else "0 seconds"

    def set_reminder(self, minutes: int = 0, seconds: int = 0, task: str = "") -> None:
        """Set a reminder to fire after *minutes*/*seconds* for *task*."""
        total = int(minutes) * 60 + int(seconds)
        if total <= 0:
            speak("Please specify when I should remind you.")
            return

        task_str = task.strip() or "your reminder"
        duration_str = self._build_duration_str(int(minutes), int(seconds))

        reminder = _reminder_store.add(task_str, total, duration_str)
        speak_async(f"Got it! I'll remind you about '{task_str}' in {duration_str}.")
        logger.info("Reminder #%d set: '%s' in %d seconds", reminder.id, task_str, total)

        def _fire(rid: int) -> None:
            time.sleep(total)
            # Remove from store before speaking (in case it was cancelled)
            if _reminder_store.remove(rid):
                speak(f"Reminder! {task_str}.")
                logger.info("Reminder #%d fired: '%s'", rid, task_str)

        threading.Thread(target=_fire, args=(reminder.id,), daemon=True).start()

    def list_reminders(self) -> None:
        """Read out all pending reminders."""
        reminders = _reminder_store.list_all()
        if not reminders:
            speak("You have no pending reminders.")
            return
        lines = []
        for r in reminders:
            remaining = max(0, r.fire_at - time.monotonic())
            mins, secs = divmod(int(remaining), 60)
            if mins:
                time_left = f"{mins} minute{'s' if mins != 1 else ''}"
                if secs:
                    time_left += f" and {secs} second{'s' if secs != 1 else ''}"
            else:
                time_left = f"{secs} second{'s' if secs != 1 else ''}"
            lines.append(f"Reminder {r.id}: '{r.task}' in {time_left}")
        speak(f"You have {len(reminders)} pending reminder{'s' if len(reminders) != 1 else ''}. " +
              ". ".join(lines) + ".")

    def cancel_reminder(self, task: str = "") -> None:
        """Cancel reminders matching *task*."""
        if not task.strip():
            speak("Please tell me which reminder to cancel.")
            return
        count = _reminder_store.cancel_by_task(task.strip())
        if count:
            speak(f"Cancelled {count} reminder{'s' if count != 1 else ''} about '{task}'.")
        else:
            speak(f"I couldn't find any reminders about '{task}'.")

    # ------------------------------------------------------------------
    # Clipboard
    # ------------------------------------------------------------------
    def read_clipboard(self) -> None:
        """Read the current clipboard contents aloud."""
        try:
            result = subprocess.run(
                ["powershell", "-Command", "Get-Clipboard"],
                capture_output=True, text=True, check=False,
            )
            text = result.stdout.strip()
            if text:
                # Truncate very long clipboard contents
                preview = text if len(text) <= 200 else text[:200] + "…"
                speak(f"Clipboard contains: {preview}")
                logger.info("Read clipboard: %d chars", len(text))
            else:
                speak("The clipboard is empty.")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Clipboard read failed: %s", exc)
            speak("Sorry, I couldn't read the clipboard.")

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
    # Clipboard (write)
    # ------------------------------------------------------------------
    def write_clipboard(self, text: str = "") -> None:
        """Copy *text* to the system clipboard."""
        if not text:
            speak("What would you like me to copy to the clipboard?")
            return
        try:
            proc = subprocess.Popen(
                ["powershell", "-NonInteractive", "-Command", "$input | Set-Clipboard"],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            proc.communicate(input=text, timeout=5)
            preview = text if len(text) <= 60 else text[:60] + "…"
            logger.info("Wrote to clipboard: %d chars", len(text))
            speak_async(f"Copied to clipboard: {preview}.")
        except Exception as exc:  # noqa: BLE001
            logger.warning("write_clipboard failed: %s", exc)
            speak("Sorry, I couldn't write to the clipboard.")

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
