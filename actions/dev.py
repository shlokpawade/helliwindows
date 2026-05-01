"""
actions/dev.py – Developer-mode actions.

Covers: run Python files, execute git commands, open VS Code projects.
All actions are gated by the DEVELOPER_MODE config flag.
"""

import os
import subprocess
import sys
from pathlib import Path

from config import DEVELOPER_MODE, VSCODE_PATH
from utils import logger, run_command, speak

# Characters that must not appear in paths or git sub-commands
_UNSAFE_CHARS = set(';&|<>`$\'"\\')


def _safe_path(path: str) -> str | None:
    """Return *path* only if it contains no shell-injection characters."""
    if any(c in _UNSAFE_CHARS for c in path):
        logger.warning("Rejected unsafe path: %r", path)
        return None
    return path


class DevActions:
    """Developer-mode actions: Python runner, git helper, VS Code launcher."""

    # ------------------------------------------------------------------
    # Python runner
    # ------------------------------------------------------------------
    def run_python_file(self, path: str) -> None:
        """Run a Python file with the current interpreter."""
        if not DEVELOPER_MODE:
            speak("Developer mode is disabled. Set DEVELOPER_MODE=true in .env to enable it.")
            return

        resolved = Path(os.path.expandvars(os.path.expanduser(path))).resolve()
        if not resolved.exists() or resolved.suffix != ".py":
            speak(f"I couldn't find a Python file at {path}.")
            return
        if _safe_path(str(resolved)) is None:
            speak("That file path contains unsafe characters.")
            return

        speak(f"Running {resolved.name}.")
        logger.info("Running Python file: %s", resolved)
        run_command([sys.executable, str(resolved)])

    # ------------------------------------------------------------------
    # Git helper
    # ------------------------------------------------------------------
    def git_command(self, command: str) -> None:
        """Execute a basic git sub-command and speak the output."""
        if not DEVELOPER_MODE:
            speak("Developer mode is disabled.")
            return

        # Allow only safe git sub-commands (no pipes, redirects, etc.)
        allowed_prefixes = ("status", "log", "pull", "push", "add", "commit", "diff", "branch")
        first_word = command.split()[0] if command.split() else ""
        if first_word not in allowed_prefixes:
            speak(f"Git sub-command '{first_word}' is not allowed.")
            return

        parts = ["git"] + command.split()
        logger.info("git command: %s", parts)
        result = run_command(parts, capture=True)
        output = (result.stdout or result.stderr or "Done.").strip()
        speak(output[:200] if len(output) > 200 else output)

    # ------------------------------------------------------------------
    # VS Code launcher
    # ------------------------------------------------------------------
    def open_vscode_project(self, path: str) -> None:
        """Open a folder/project in VS Code."""
        if not DEVELOPER_MODE:
            speak("Developer mode is disabled.")
            return

        speak(f"Opening {path} in VS Code.")
        logger.info("Opening VS Code project: %s", path)
        try:
            subprocess.Popen([VSCODE_PATH, path], shell=False)  # noqa: S603
        except FileNotFoundError:
            speak("VS Code was not found. Make sure it is installed and on your PATH.")
