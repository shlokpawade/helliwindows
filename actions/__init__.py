"""
actions/__init__.py – Registers and exports all action handlers.

Import this module to get the complete {action_name: handler} mapping
ready to pass to Planner.register_actions().
"""

from actions.files import FileActions
from actions.system import SystemActions
from actions.web import WebActions


def build_action_registry(memory) -> dict:
    """Return a flat dict of {action_name: callable} for all modules."""
    sys_act = SystemActions(memory)
    file_act = FileActions(memory)
    web_act = WebActions()

    return {
        # System
        "open_app":          sys_act.open_app,
        "close_app":         sys_act.close_app,
        "open_last_app":     sys_act.open_last_app,
        "volume_up":         sys_act.volume_up,
        "volume_down":       sys_act.volume_down,
        "mute":              sys_act.mute,
        "unmute":            sys_act.unmute,
        "set_volume":        sys_act.set_volume,
        "shutdown":          sys_act.shutdown,
        "restart":           sys_act.restart,
        "sleep":             sys_act.sleep,
        "lock":              sys_act.lock,
        "screenshot":        sys_act.screenshot,
        "get_time":          sys_act.get_time,
        "get_date":          sys_act.get_date,
        "run_python_file":   sys_act.run_python_file,
        "git_command":       sys_act.git_command,
        "open_vscode_project": sys_act.open_vscode_project,

        # Files
        "open_file":         file_act.open_file,
        "delete_file":       file_act.delete_file,
        "list_files":        file_act.list_files,
        "add_app_mapping":   file_act.add_app_mapping,

        # Web
        "web_search":        web_act.web_search,
        "youtube_search":    web_act.youtube_search,
        "open_url":          web_act.open_url,

        # Meta
        "help":              _help,
        "unknown":           _unknown,
        "stop":              _stop,
    }


def _help(**_) -> None:
    from utils import speak
    speak(
        "I can open apps, search the web, control volume, manage files, "
        "run routines, and more. Just tell me what you need."
    )


def _unknown(**_) -> None:
    from utils import speak
    speak("Sorry, I didn't understand that command.")


def _stop(**_) -> None:
    from utils import speak
    import sys
    speak("Goodbye!")
    sys.exit(0)
