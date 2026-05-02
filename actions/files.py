"""
actions/files.py – File manager actions.

Covers: open file/folder, delete file (with confirmation), list directory,
create folder, and teaching new app mappings to memory.
"""

import os
import shutil
from pathlib import Path

from utils import confirm_action, logger, speak

# Common spoken location shortcuts → actual Path objects
_LOCATION_ALIASES: dict[str, Path] = {
    "desktop":   Path.home() / "Desktop",
    "documents": Path.home() / "Documents",
    "downloads": Path.home() / "Downloads",
    "pictures":  Path.home() / "Pictures",
    "videos":    Path.home() / "Videos",
    "music":     Path.home() / "Music",
    "home":      Path.home(),
    "user":      Path.home(),
}


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
    # Create folder
    # ------------------------------------------------------------------
    def create_folder(self, name: str, location: str = "") -> None:
        """Create a new folder *name* inside *location*.

        *location* can be a known alias (e.g. 'desktop', 'documents') or a
        plain path string.  When omitted the folder is created on the Desktop.
        """
        if not name.strip():
            speak("Please tell me the name for the new folder.")
            return

        # Resolve base directory
        loc_key = location.strip().lower()
        if loc_key in _LOCATION_ALIASES:
            base = _LOCATION_ALIASES[loc_key]
        elif location.strip():
            base = Path(os.path.expandvars(os.path.expanduser(location.strip())))
        else:
            base = _LOCATION_ALIASES["desktop"]

        target = base / name.strip()
        try:
            # Guard against path traversal (e.g. name = "../secret").
            # resolve() follows symlinks; is_relative_to() checks ancestry correctly.
            target = target.resolve()
            base_resolved = base.resolve()
            if not target.is_relative_to(base_resolved):
                speak("That folder name contains an invalid path. Please try again.")
                return
            target.mkdir(parents=True, exist_ok=True)
            logger.info("Created folder: %s", target)
            speak(f"Folder '{name}' created in {base.name}.")
        except PermissionError:
            speak(f"I don't have permission to create a folder in {base}.")
        except OSError as exc:
            logger.error("create_folder failed: %s", exc)
            speak(f"Sorry, I couldn't create the folder. {exc}")

    # ------------------------------------------------------------------
    # App mapping
    # ------------------------------------------------------------------
    def add_app_mapping(self, app: str, executable: str) -> None:
        self._memory.add_app_mapping(app, executable)
        speak(f"Got it. I'll open {app} using {executable} from now on.")
