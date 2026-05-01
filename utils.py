"""
utils.py – Shared helpers: logging, text normalisation, TTS, confirmation.
"""

import json
import logging
import re
import subprocess
import sys
from datetime import datetime

import pyttsx3

from config import LOG_FILE, LOGS_FILE, CONFIRM_DANGEROUS, DANGEROUS_ACTIONS

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
def setup_logger(name: str = "jarvis") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    # Console handler (INFO+)
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)

    # File handler (DEBUG+)
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    logger.addHandler(ch)
    logger.addHandler(fh)
    return logger


logger = setup_logger()

# ---------------------------------------------------------------------------
# Text-to-Speech (offline via pyttsx3)
# ---------------------------------------------------------------------------
_tts_engine = None


def _get_tts():
    global _tts_engine
    if _tts_engine is None:
        _tts_engine = pyttsx3.init()
        _tts_engine.setProperty("rate", 175)
        _tts_engine.setProperty("volume", 1.0)
        # prefer a Windows SAPI voice if available
        voices = _tts_engine.getProperty("voices")
        for v in voices:
            if "zira" in v.name.lower() or "david" in v.name.lower():
                _tts_engine.setProperty("voice", v.id)
                break
    return _tts_engine


def speak(text: str) -> None:
    """Speak *text* aloud and print it."""
    logger.info("JARVIS: %s", text)
    engine = _get_tts()
    engine.say(text)
    engine.runAndWait()


# ---------------------------------------------------------------------------
# Animations (screen-edge overlay)
# ---------------------------------------------------------------------------
import threading
import tkinter as tk


def _show_edge_overlay(color: str, duration: int) -> None:
    """
    Display a colourful border around the entire screen for *duration* ms.

    The window is borderless and fullscreen; only the thin coloured edges are
    visible – the centre is made transparent so the desktop stays usable.
    Works on Windows via the '-transparentcolor' attribute.
    """
    root = tk.Tk()
    root.overrideredirect(True)          # no title-bar / decorations
    root.wm_attributes("-topmost", True) # always on top

    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    root.geometry(f"{sw}x{sh}+0+0")

    # Background colour that will be made fully transparent (centre hole)
    _TRANSPARENT = "#010101"
    root.configure(bg=_TRANSPARENT)

    try:
        root.wm_attributes("-transparentcolor", _TRANSPARENT)
    except tk.TclError:
        # Non-Windows platforms may not support this; fall back gracefully.
        pass

    border = 10  # edge thickness in pixels

    canvas = tk.Canvas(
        root, width=sw, height=sh,
        bg=_TRANSPARENT, highlightthickness=0,
    )
    canvas.place(x=0, y=0)

    # Draw four edge rectangles in the chosen colour
    canvas.create_rectangle(0,          0,          sw, border,    fill=color, outline="")
    canvas.create_rectangle(0,          sh - border, sw, sh,        fill=color, outline="")
    canvas.create_rectangle(0,          0,          border, sh,     fill=color, outline="")
    canvas.create_rectangle(sw - border, 0,          sw, sh,        fill=color, outline="")

    root.after(duration, root.destroy)
    root.mainloop()


def show_listening_animation() -> None:
    """Show a blue edge overlay while Jarvis is listening."""
    threading.Thread(
        target=_show_edge_overlay,
        args=("#00aaff", 2000),
        daemon=True,
    ).start()


def show_wake_animation() -> None:
    """Show a green/cyan edge overlay when the wake word is detected."""
    threading.Thread(
        target=_show_edge_overlay,
        args=("#00ffcc", 1500),
        daemon=True,
    ).start()


# ---------------------------------------------------------------------------
# Text normalisation
# ---------------------------------------------------------------------------
def normalise(text: str) -> str:
    """Lower-case, strip punctuation, collapse whitespace."""
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Safety confirmation
# ---------------------------------------------------------------------------
def confirm_action(action_name: str) -> bool:
    """
    For dangerous actions: ask for verbal/text confirmation.
    Returns True if confirmed.
    """
    if not CONFIRM_DANGEROUS or action_name not in DANGEROUS_ACTIONS:
        return True
    speak(f"This will {action_name.replace('_', ' ')}. Are you sure? Say yes to confirm.")
    answer = input("[confirm] Type 'yes' to proceed: ").strip().lower()
    return answer in ("yes", "y")


# ---------------------------------------------------------------------------
# Subprocess helper
# ---------------------------------------------------------------------------
def run_command(cmd: list[str], capture: bool = False) -> subprocess.CompletedProcess:
    """Run a shell command safely, logging errors."""
    logger.debug("run_command: %s", cmd)
    try:
        return subprocess.run(
            cmd,
            capture_output=capture,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        logger.error("Command not found: %s – %s", cmd[0], exc)
        raise


# ---------------------------------------------------------------------------
# Timestamp
# ---------------------------------------------------------------------------
def now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


# ---------------------------------------------------------------------------
# JSON structured event log (logs.json)
# ---------------------------------------------------------------------------
def log_event(event_type: str, data: dict) -> None:
    """
    Append a structured JSON event to logs.json.

    Each entry is written as a single line (NDJSON) to avoid loading the
    entire file into memory on every write.
    """
    entry = {"ts": now_iso(), "event": event_type, **data}
    try:
        with open(LOGS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError as exc:
        logger.warning("Could not write to logs.json: %s", exc)
