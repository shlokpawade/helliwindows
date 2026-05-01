"""
config.py – Central configuration for Jarvis Windows Assistant.
All tuneable constants, paths, and flags live here.
"""

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).parent.resolve()
MEMORY_FILE = BASE_DIR / "memory.json"
LOG_FILE = BASE_DIR / "jarvis.log"

# Vosk model directory (download from https://alphacephei.com/vosk/models)
# e.g. BASE_DIR / "models" / "vosk-model-small-en-us-0.15"
VOSK_MODEL_PATH = os.getenv("VOSK_MODEL_PATH", str(BASE_DIR / "models" / "vosk-model-small-en-us-0.15"))

# ---------------------------------------------------------------------------
# Audio
# ---------------------------------------------------------------------------
AUDIO_SAMPLE_RATE = 16000          # Hz – required by Vosk
AUDIO_BLOCK_SIZE  = 8000           # frames per read block
MIC_DEVICE_INDEX  = None           # None → system default

# ---------------------------------------------------------------------------
# Wake word
# ---------------------------------------------------------------------------
WAKE_WORD         = "hey windows"
WAKE_SENSITIVITY  = 0.6            # Vosk keyword threshold (0–1)

# ---------------------------------------------------------------------------
# Brain / Intent
# ---------------------------------------------------------------------------
USE_LOCAL_LLM     = os.getenv("USE_LOCAL_LLM", "false").lower() == "true"
OLLAMA_MODEL      = os.getenv("OLLAMA_MODEL", "mistral")
OLLAMA_URL        = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
OLLAMA_TIMEOUT    = 30             # seconds

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
