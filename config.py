"""
config.py – Central configuration for Jarvis Windows Assistant.
All tuneable constants, paths, and flags live here.
"""

import os
from pathlib import Path

# Load .env file if present (python-dotenv is a required dependency;
# the ImportError catch is kept for graceful degradation in stripped installs)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # fall back to environment variables already set in the shell

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).parent.resolve()
MEMORY_FILE = BASE_DIR / "memory.json"
LOG_FILE    = BASE_DIR / "jarvis.log"
LOGS_FILE   = BASE_DIR / "logs.json"  # structured JSON event log

# Vosk model directory (download from https://alphacephei.com/vosk/models)
# e.g. BASE_DIR / "models" / "vosk-model-small-en-us-0.15"

def _find_best_vosk_model() -> str:
    env_path = os.getenv("VOSK_MODEL_PATH")
    if env_path:
        return env_path

    models_dir = BASE_DIR / "models"
    if models_dir.exists():
        candidates = [p for p in models_dir.iterdir() if p.is_dir()]
        if candidates:
            # Prefer full-size models over small/tiny ones; break ties by name.
            def _model_key(p: Path) -> tuple:  # noqa: F821
                name = p.name.lower()
                is_full = int("small" not in name and "tiny" not in name)
                return (is_full, name)

            candidates.sort(key=_model_key)
            return str(candidates[-1])

    return str(BASE_DIR / "models" / "vosk-model-en-us-0.22")

VOSK_MODEL_PATH = _find_best_vosk_model()

# ---------------------------------------------------------------------------
# Audio
# ---------------------------------------------------------------------------
AUDIO_SAMPLE_RATE = 16000          # Hz – required by Vosk
AUDIO_BLOCK_SIZE  = 4000           # smaller blocks improve STT responsiveness
MIC_DEVICE_INDEX  = 1             # None → system default

# ---------------------------------------------------------------------------
# Wake word
# ---------------------------------------------------------------------------
WAKE_WORD         = "hey windows"
WAKE_SENSITIVITY  = 0.0            # Vosk keyword threshold (0–1)

# ---------------------------------------------------------------------------
# Brain / Intent
# ---------------------------------------------------------------------------
USE_LOCAL_LLM     = os.getenv("USE_LOCAL_LLM", "true").lower() == "true"
OLLAMA_MODEL      = os.getenv("OLLAMA_MODEL", "phi3:mini")
OLLAMA_URL        = os.getenv("OLLAMA_URL", "http://localhost:11434/v1/chat/completions")
OLLAMA_TIMEOUT    = 30             # seconds; reduced for snappier responses

# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------
DANGEROUS_ACTIONS = {"shutdown", "restart", "delete_file", "format_drive"}
CONFIRM_DANGEROUS = True           # ask user before executing

# ---------------------------------------------------------------------------
# Developer mode
# ---------------------------------------------------------------------------
DEVELOPER_MODE    = os.getenv("DEVELOPER_MODE", "false").lower() == "true"
VSCODE_PATH       = os.getenv("VSCODE_PATH", "code")  # must be on PATH

# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------
MAX_MEMORY_ENTRIES = 200           # cap history list length

# ---------------------------------------------------------------------------
# STT tuning
# ---------------------------------------------------------------------------
# Multiply the raw microphone signal before feeding it to Vosk.
# Increase if your mic is too quiet (try 2.0–4.0); set to 1.0 to disable.
STT_AUDIO_GAIN        = float(os.getenv("STT_AUDIO_GAIN", "2.0"))
# RMS energy below this level is treated as silence.
# Lower the value if the detector cuts off too early; raise it in noisy rooms.
STT_SILENCE_THRESHOLD = int(os.getenv("STT_SILENCE_THRESHOLD", "300"))

# ---------------------------------------------------------------------------
# Whisper (command STT)
# ---------------------------------------------------------------------------
# Size of the Whisper model used for command recognition.
# Options (smallest→largest): "tiny.en", "base.en", "small.en", "medium.en"
# "base.en" gives a good speed/accuracy trade-off on CPU.
WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "base.en")
# BCP-47 language code passed to Whisper. Use "en" for English (fastest).
# Set to None to let Whisper auto-detect the language.
WHISPER_LANGUAGE   = os.getenv("WHISPER_LANGUAGE", "en") or None
