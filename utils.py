"""
utils.py – Shared helpers: logging, text normalisation, TTS, confirmation.
"""

import json
import logging
import queue as _queue
import re
import subprocess
import sys
import threading
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
#
# Architecture: a single daemon worker thread owns the pyttsx3 engine and
# processes utterances from a queue.
#
#   speak(text)       – enqueue and BLOCK until the utterance finishes.
#   speak_async(text) – enqueue and RETURN IMMEDIATELY (fire-and-forget).
#
# This lets Jarvis announce what it is doing *while* the action executes,
# rather than waiting for the TTS to finish before starting the work.
# ---------------------------------------------------------------------------

# Each queue item is (text: str, done_event: threading.Event | None).
# A done_event of None means the caller does not wait (speak_async).
_tts_queue: _queue.Queue = _queue.Queue()


def _tts_worker() -> None:
    """Dedicated TTS worker thread.  Owns the single pyttsx3 engine instance."""
    engine = pyttsx3.init()
    engine.setProperty("rate", 175)
    engine.setProperty("volume", 1.0)
    voices = engine.getProperty("voices")
    for v in voices:
        if "zira" in v.name.lower() or "david" in v.name.lower():
            engine.setProperty("voice", v.id)
            break

    while True:
        item = _tts_queue.get()
        if item is None:          # sentinel: shut down
            _tts_queue.task_done()
            break
        text, done_event = item
        try:
            engine.say(text)
            engine.runAndWait()
        except Exception:         # noqa: BLE001 – never crash the TTS thread
            pass
        finally:
            _tts_queue.task_done()
            if done_event is not None:
                done_event.set()


# Start the worker immediately at import time so the first speak() is fast.
_tts_thread = threading.Thread(target=_tts_worker, name="tts-worker", daemon=True)
_tts_thread.start()


def speak(text: str) -> None:
    """Speak *text* aloud and block until the utterance is fully spoken."""
    logger.info("JARVIS: %s", text)
    done = threading.Event()
    _tts_queue.put((text, done))
    done.wait()


def speak_async(text: str) -> None:
    """Speak *text* in the background and return immediately.

    Use this when the response announcement should play *simultaneously* with
    the action being performed (e.g. say "Opening Brave now" while the app
    is already launching).
    """
    logger.info("JARVIS: %s", text)
    _tts_queue.put((text, None))


# ---------------------------------------------------------------------------
# Animations (screen-edge overlay)
# ---------------------------------------------------------------------------
import tkinter as tk

# ---------------------------------------------------------------------------
# Single-threaded Tkinter root
#
# Tkinter is NOT thread-safe.  Creating a tk.Tk() in a background thread
# causes "Tcl_AsyncDelete: async handler deleted by the wrong thread".
#
# Fix: one invisible tk.Tk root lives permanently in its own dedicated daemon
# thread ("tk-gui").  All overlay windows are tk.Toplevel children of that
# root and are created by scheduling via root.after(), which is the only
# thread-safe Tkinter API.
# ---------------------------------------------------------------------------

_tk_root: "tk.Tk | None" = None
_tk_ready = threading.Event()


def _tk_bootstrap() -> None:
    global _tk_root
    _tk_root = tk.Tk()
    _tk_root.withdraw()           # invisible placeholder – never shown
    _tk_root.overrideredirect(True)
    _tk_ready.set()
    try:
        _tk_root.mainloop()
    except Exception:             # noqa: BLE001
        pass


_tk_gui_thread = threading.Thread(target=_tk_bootstrap, name="tk-gui", daemon=True)
_tk_gui_thread.start()
if not _tk_ready.wait(timeout=5):
    logger.warning("tk-gui thread did not start in time; screen overlays will be disabled.")


def _show_edge_overlay(
    color: str,
    duration: int | None = None,
    stop_event: "threading.Event | None" = None,
) -> None:
    """
    Schedule a glowing border overlay on the tk-gui thread.

    This function is safe to call from *any* thread.  The actual Tk work
    runs inside the tk-gui event loop via after(), which avoids the
    Tcl_AsyncDelete cross-thread error.

    If *duration* (ms) is given the window auto-closes after that many
    milliseconds.  If *stop_event* is given the window stays open until
    the event is set (used for the persistent listening-light).
    """
    if _tk_root is None:
        return

    def _build() -> None:
        top = tk.Toplevel(_tk_root)
        top.overrideredirect(True)
        top.wm_attributes("-topmost", True)

        sw = top.winfo_screenwidth()
        sh = top.winfo_screenheight()
        top.geometry(f"{sw}x{sh}+0+0")

        _TRANSPARENT = "#010101"
        top.configure(bg=_TRANSPARENT)

        try:
            top.wm_attributes("-transparentcolor", _TRANSPARENT)
        except tk.TclError:
            pass

        canvas = tk.Canvas(
            top, width=sw, height=sh,
            bg=_TRANSPARENT, highlightthickness=0,
        )
        canvas.place(x=0, y=0)

        c = color.lstrip("#")
        r0, g0, b0 = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)

        corner_r = 22
        _MIN_CORNER_R = 4
        _MIN_RGB = 2

        def _safe_hex(r: float, g: float, b: float) -> str:
            ri = max(_MIN_RGB, min(255, int(r)))
            gi = max(_MIN_RGB, min(255, int(g)))
            bi = max(_MIN_RGB, min(255, int(b)))
            h = f"#{ri:02x}{gi:02x}{bi:02x}"
            return h if h != _TRANSPARENT else "#020202"

        def _draw_rounded_border(inset: int, width: int, fill: str) -> None:
            x0, y0 = inset, inset
            x1, y1 = sw - inset, sh - inset
            cr = max(_MIN_CORNER_R, corner_r - inset // 2)
            arc_d = cr * 2

            canvas.create_rectangle(
                x0 + cr, y0,         x1 - cr, y0 + width, fill=fill, outline="")  # top
            canvas.create_rectangle(
                x0 + cr, y1 - width, x1 - cr, y1,         fill=fill, outline="")  # bottom
            canvas.create_rectangle(
                x0,      y0 + cr,    x0 + width, y1 - cr, fill=fill, outline="")  # left
            canvas.create_rectangle(
                x1 - width, y0 + cr, x1, y1 - cr,         fill=fill, outline="")  # right

            canvas.create_arc(
                x0, y0, x0 + arc_d, y0 + arc_d,
                start=90, extent=90, outline=fill, width=width, style=tk.ARC)   # top-left
            canvas.create_arc(
                x1 - arc_d, y0, x1, y0 + arc_d,
                start=0, extent=90, outline=fill, width=width, style=tk.ARC)    # top-right
            canvas.create_arc(
                x1 - arc_d, y1 - arc_d, x1, y1,
                start=270, extent=90, outline=fill, width=width, style=tk.ARC)  # bottom-right
            canvas.create_arc(
                x0, y1 - arc_d, x0 + arc_d, y1,
                start=180, extent=90, outline=fill, width=width, style=tk.ARC)  # bottom-left

        _GLOW_LAYERS: list[tuple[int, int, float]] = [
            (18, 7, 0.06),
            (13, 6, 0.14),
            (9,  5, 0.28),
            (6,  4, 0.50),
            (3,  3, 0.75),
            (1,  3, 1.00),
        ]

        for inset, width, alpha in _GLOW_LAYERS:
            fill = _safe_hex(r0 * alpha, g0 * alpha, b0 * alpha)
            _draw_rounded_border(inset, width, fill)

        if duration is not None:
            top.after(duration, top.destroy)
        elif stop_event is not None:
            def _check_stop() -> None:
                if stop_event.is_set():
                    top.destroy()
                    return
                top.after(100, _check_stop)
            top.after(100, _check_stop)

    # Schedule _build to run inside the tk-gui event loop (thread-safe).
    _tk_root.after(0, _build)


def show_listening_animation() -> None:
    """Show a blue edge overlay for a fixed short duration (legacy helper)."""
    _show_edge_overlay(color="#00aaff", duration=2000)


def start_listening_light() -> threading.Event:
    """
    Start a persistent blue edge overlay that stays on until
    :func:`stop_listening_light` is called.

    Returns the :class:`threading.Event` that must be passed to
    :func:`stop_listening_light` to dismiss the overlay.
    """
    stop_event = threading.Event()
    _show_edge_overlay(color="#00aaff", stop_event=stop_event)
    return stop_event


def stop_listening_light(stop_event: threading.Event) -> None:
    """Signal the overlay started by :func:`start_listening_light` to close."""
    stop_event.set()


def show_wake_animation() -> None:
    """Show a green/cyan edge overlay when the wake word is detected."""
    _show_edge_overlay(color="#00ffcc", duration=1500)


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
