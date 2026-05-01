"""
memory.py – Persistent memory store backed by memory.json.

Responsibilities:
- Load / save structured JSON memory.
- Record command history.
- Provide app-mapping lookups and routine storage.
"""

import json
import threading
from pathlib import Path
from typing import Any

from config import MEMORY_FILE, MAX_MEMORY_ENTRIES
from utils import logger, now_iso


class Memory:
    """Thread-safe in-memory dict that syncs to disk."""

    def __init__(self, path: Path = MEMORY_FILE) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._data: dict[str, Any] = {}
        self._load()

    # ------------------------------------------------------------------
    # Internal I/O
    # ------------------------------------------------------------------
    def _load(self) -> None:
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                self._data = json.load(f)
            logger.debug("Memory loaded from %s", self._path)
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            logger.warning("Could not load memory (%s). Starting fresh.", exc)
            self._data = {
                "app_mappings": {},
                "routines": {},
                "history": [],
                "last_action": None,
                "last_app_opened": None,
            }

    def _save(self) -> None:
        try:
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
        except OSError as exc:
            logger.error("Failed to save memory: %s", exc)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._data[key] = value
            self._save()

    def record_command(self, text: str, intent: str, success: bool) -> None:
        """Append a command to history, capping at MAX_MEMORY_ENTRIES."""
        entry = {
            "ts": now_iso(),
            "text": text,
            "intent": intent,
            "success": success,
        }
        with self._lock:
            history: list = self._data.setdefault("history", [])
            history.append(entry)
            if len(history) > MAX_MEMORY_ENTRIES:
                self._data["history"] = history[-MAX_MEMORY_ENTRIES:]
            self._data["last_action"] = intent
            self._save()

    def resolve_app(self, name: str) -> str | None:
        """Return the executable for *name* from app_mappings, or None."""
        mappings: dict = self._data.get("app_mappings", {})
        return mappings.get(name.lower())

    def add_app_mapping(self, name: str, executable: str) -> None:
        with self._lock:
            self._data.setdefault("app_mappings", {})[name.lower()] = executable
            self._save()

    def get_routine(self, name: str) -> list[dict] | None:
        routines: dict = self._data.get("routines", {})
        return routines.get(name.lower())

    def save_routine(self, name: str, steps: list[dict]) -> None:
        with self._lock:
            self._data.setdefault("routines", {})[name.lower()] = steps
            self._save()

    def last_app_opened(self) -> str | None:
        return self._data.get("last_app_opened")

    def set_last_app(self, app: str) -> None:
        with self._lock:
            self._data["last_app_opened"] = app
            self._save()
