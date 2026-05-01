"""
actions/files.py – File manager actions.

Covers: open file/folder, delete file (with confirmation), list directory,
and teaching new app mappings to memory.
"""

import os
import shutil
from pathlib import Path

from utils import confirm_action, logger, speak


class FileActions:
    def __init__(self, memory) -> None:
        self._memory = memory

    # ------------------------------------------------------------------
    # Open
    # ------------------------------------------------------------------
    def open_file(self, path: str) -> None:
        expanded = os.path.expandvars(os.path.expanduser(path))
        if not os.path.exists(expanded):
            speak(f"I couldn't find {path}.")
            return
        logger.info("Opening: %s", expanded)
        os.startfile(expanded)
        speak(f"Opening {path}.")

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------
    def delete_file(self, path: str) -> None:
        if not confirm_action("delete_file"):
            speak("Deletion cancelled.")
            return
        expanded = os.path.expandvars(os.path.expanduser(path))
        target = Path(expanded)
        if not target.exists():
            speak(f"I couldn't find {path}.")
            return
        try:
            if target.is_dir():
                shutil.rmtree(target)
                speak(f"Deleted folder {path}.")
            else:
                target.unlink()
                speak(f"Deleted {path}.")
        except PermissionError:
            speak(f"I don't have permission to delete {path}.")

    # ------------------------------------------------------------------
    # List
    # ------------------------------------------------------------------
    def list_files(self, path: str) -> None:
        expanded = os.path.expandvars(os.path.expanduser(path))
        target = Path(expanded)
        if not target.is_dir():
            speak(f"{path} is not a valid folder.")
            return
        entries = list(target.iterdir())
        if not entries:
            speak(f"{path} is empty.")
            return
        names = [e.name for e in entries[:10]]
        listing = ", ".join(names)
        suffix = f" and {len(entries) - 10} more" if len(entries) > 10 else ""
        speak(f"In {path}: {listing}{suffix}.")

    # ------------------------------------------------------------------
    # App mapping
    # ------------------------------------------------------------------
    def add_app_mapping(self, app: str, executable: str) -> None:
        self._memory.add_app_mapping(app, executable)
        speak(f"Got it. I'll open {app} using {executable} from now on.")
