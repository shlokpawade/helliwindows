"""
actions/modes.py – Interactive Study / Code mode routines.

When the user activates study or coding mode, this module conducts a
short multi-turn dialogue to configure the session:

Study flow
----------
1. Ask what topic to study.
2. Offer lofi background music on YouTube.
3. Offer topic-specific study videos on YouTube.
4. Set system brightness and volume to 50 %.

Code flow
---------
1. Ask: new project or existing project?
2. New project  → ask name → create C:\\projects\\<name> → open in VS Code.
3. Existing     → ask name → locate C:\\projects\\<name> → open in VS Code.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from actions.dev import DevActions
    from actions.system import SystemActions
    from actions.web import WebActions
    from listener import Listener

from utils import logger, normalise, speak

# Root folder where all voice-created projects live
PROJECTS_ROOT = Path("C:/projects")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_yes(text: str) -> bool:
    """Return True if *text* looks like an affirmative answer."""
    return bool(re.search(r'\b(yes|yeah|yep|yess|sure|ok|okay|yup)\b', text))


def _set_brightness(level: int) -> None:
    """Set screen brightness via PowerShell WMI (works for built-in displays)."""
    try:
        subprocess.run(
            [
                "powershell", "-NonInteractive", "-Command",
                f"(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods)"
                f".WmiSetBrightness(1,{level})",
            ],
            check=False,
            timeout=10,
            capture_output=True,
        )
        logger.info("Brightness set to %d%%", level)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not set brightness: %s", exc)


def _sanitise_folder_name(name: str) -> str:
    """
    Strip characters that are unsafe in Windows folder names and replace
    spaces with underscores.  Returns an empty string if nothing usable remains.
    """
    # Remove characters that Windows disallows in file/folder names
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', name).strip()
    # Collapse whitespace → underscores
    safe = re.sub(r'\s+', '_', safe)
    return safe


# ---------------------------------------------------------------------------
# ModeActions
# ---------------------------------------------------------------------------

class ModeActions:
    """
    Handles the interactive study-mode and code-mode dialogue flows.

    Requires references to the Listener (for follow-up STT), SystemActions
    (for volume), WebActions (for YouTube), and DevActions (for VS Code).
    """

    def __init__(
        self,
        listener: Listener | None,
        sys_act: SystemActions,
        web_act: WebActions,
        dev_act: DevActions,
    ) -> None:
        self._listener = listener
        self._sys = sys_act
        self._web = web_act
        self._dev = dev_act

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def activate_mode(self, mode: str = "", **_) -> None:
        """Dispatch to study or code flow based on the recognised mode."""
        mode_norm = mode.lower().strip()
        if mode_norm in ("study", "focus"):
            # Directly enter the study flow
            self._study_flow()
        elif mode_norm in ("coding", "code"):
            # Directly enter the code flow
            self._code_flow()
        else:
            # Generic: ask the user which sub-mode they want
            self._ask_study_or_code()

    # ------------------------------------------------------------------
    # Internal: ask/listen helper
    # ------------------------------------------------------------------

    def _ask(self, question: str) -> tuple[str, str]:
        """
        Speak *question*, listen for an answer, and return
        (raw_text, normalised_text).  Both are empty strings on failure.
        """
        speak(question)
        raw = self._listener.listen() or ""
        return raw, normalise(raw)

    # ------------------------------------------------------------------
    # Internal: mode selection
    # ------------------------------------------------------------------

    def _ask_study_or_code(self) -> None:
        _, answer = self._ask("Do you want to study or code?")
        if "study" in answer or "learn" in answer:
            self._study_flow()
        elif "code" in answer or "coding" in answer or "program" in answer:
            self._code_flow()
        else:
            speak("I didn't catch that. Please say study or code.")

    # ------------------------------------------------------------------
    # Study flow
    # ------------------------------------------------------------------

    def _study_flow(self) -> None:
        raw_topic, topic = self._ask("What are you going to study?")
        if not topic:
            speak("I didn't catch the topic. Please try again.")
            return

        speak(f"Alright, let's get you set up to study {raw_topic}.")

        # Background music?
        _, music_answer = self._ask("Do you want background music?")
        if _is_yes(music_answer):
            self._web.youtube_search("lofi beats study music")

        # Topic videos?
        _, video_answer = self._ask(f"Do you want to watch videos about {raw_topic}?")
        if _is_yes(video_answer):
            self._web.youtube_search(raw_topic)

        # Environment settings
        _set_brightness(50)
        self._sys.set_volume(value=50)
        speak(
            "Study mode is ready. Brightness and volume have been set to 50 percent. "
            "Good luck studying!"
        )

    # ------------------------------------------------------------------
    # Code flow
    # ------------------------------------------------------------------

    def _code_flow(self) -> None:
        _, answer = self._ask(
            "Do you want to start a new project or work on an existing project?"
        )

        if "new" in answer:
            self._new_project_flow()
        elif "exist" in answer or "old" in answer or "current" in answer:
            self._existing_project_flow()
        else:
            speak(
                "I didn't understand. Please say new project or existing project."
            )

    def _new_project_flow(self) -> None:
        raw_name, _ = self._ask("What is the project name?")
        if not raw_name:
            speak("I didn't catch the project name. Please try again.")
            return

        folder_name = _sanitise_folder_name(raw_name)
        if not folder_name:
            speak("That project name contains only invalid characters.")
            return

        project_path = PROJECTS_ROOT / folder_name
        try:
            project_path.mkdir(parents=True, exist_ok=True)
            logger.info("Created project folder: %s", project_path)
            speak(f"Created project folder {folder_name}.")
        except OSError as exc:
            logger.error("Could not create project folder %s: %s", project_path, exc)
            speak(f"Sorry, I couldn't create the folder. {exc}")
            return

        self._dev.open_vscode_project(str(project_path))

    def _existing_project_flow(self) -> None:
        raw_name, _ = self._ask("What is the project name?")
        if not raw_name:
            speak("I didn't catch the project name. Please try again.")
            return

        folder_name = _sanitise_folder_name(raw_name)
        if not folder_name:
            speak("That project name contains only invalid characters.")
            return

        project_path = PROJECTS_ROOT / folder_name
        if not project_path.exists():
            speak(
                f"I couldn't find a project named {folder_name} in C:\\projects. "
                "Please check the name and try again."
            )
            return

        self._dev.open_vscode_project(str(project_path))
