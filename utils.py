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
    Display a glowing border around the entire screen for *duration* ms.

    The window is borderless and fullscreen; only the thin coloured edges are
    visible – the centre is made transparent so the desktop stays usable.
    Works on Windows via the '-transparentcolor' attribute.

    Visual improvements over a plain solid border:
    - Rounded corners drawn with arcs.
    - Inner glow: multiple concentric bands that fade as they move into the
      screen, simulating a soft light emission from the edge.
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

    canvas = tk.Canvas(
        root, width=sw, height=sh,
        bg=_TRANSPARENT, highlightthickness=0,
    )
    canvas.place(x=0, y=0)

    # Parse the base colour into RGB components.
    c = color.lstrip("#")
    r0, g0, b0 = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)

    corner_r = 22  # radius for rounded corners (pixels)

    def _safe_hex(r: float, g: float, b: float) -> str:
        """Clamp and format an RGB triple as a hex colour string.

        Avoids the reserved transparent background colour.
        """
        ri = max(2, min(255, int(r)))
        gi = max(2, min(255, int(g)))
        bi = max(2, min(255, int(b)))
        h = f"#{ri:02x}{gi:02x}{bi:02x}"
        return h if h != _TRANSPARENT else "#020202"

    def _draw_rounded_border(inset: int, width: int, fill: str) -> None:
        """Draw one rounded-rectangle border band at *inset* pixels from the
        screen edge, using *width* as the band thickness and *fill* as colour.

        The border is composed of four straight segments (top/bottom/left/right)
        connected by quarter-circle arcs at each corner.
        """
        x0, y0 = inset, inset
        x1, y1 = sw - inset, sh - inset
        cr = max(corner_r - inset // 2, 4)   # corner radius shrinks as inset grows
        arc_d = cr * 2

        # Straight segments (skip the corner areas so arcs can close them)
        canvas.create_rectangle(
            x0 + cr, y0,         x1 - cr, y0 + width, fill=fill, outline="")  # top
        canvas.create_rectangle(
            x0 + cr, y1 - width, x1 - cr, y1,         fill=fill, outline="")  # bottom
        canvas.create_rectangle(
            x0,      y0 + cr,    x0 + width, y1 - cr, fill=fill, outline="")  # left
        canvas.create_rectangle(
            x1 - width, y0 + cr, x1, y1 - cr,         fill=fill, outline="")  # right

        # Quarter-circle arcs at each corner (ARC style = outline only)
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

    # Glow layers drawn from the faintest (most inward) to the brightest (at
    # the screen edge).  Each entry: (inset_px, band_width_px, colour_alpha).
    # Later draws sit on top of earlier ones, so the core line is always on top.
    _GLOW_LAYERS: list[tuple[int, int, float]] = [
        (18, 7, 0.06),   # outermost glow – very faint, wide band
        (13, 6, 0.14),
        (9,  5, 0.28),
        (6,  4, 0.50),
        (3,  3, 0.75),
        (1,  3, 1.00),   # core bright line at the screen edge
    ]

    for inset, width, alpha in _GLOW_LAYERS:
        fill = _safe_hex(r0 * alpha, g0 * alpha, b0 * alpha)
        _draw_rounded_border(inset, width, fill)

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
