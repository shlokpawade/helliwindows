"""
actions/__init__.py – Registers and exports all action handlers.

Import this module to get the complete {action_name: handler} mapping
ready to pass to Planner.register_actions().
"""

from actions.dev import DevActions
from actions.files import FileActions
from actions.system import SystemActions
from actions.web import WebActions


def build_action_registry(memory) -> dict:
    """Return a flat dict of {action_name: callable} for all modules."""
    sys_act = SystemActions(memory)
    file_act = FileActions(memory)
    web_act = WebActions()
    dev_act = DevActions()

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
        "send_whatsapp_message": sys_act.send_whatsapp_message,
        "chat_response":     sys_act.chat_response,

        # Files
        "open_file":         file_act.open_file,
        "delete_file":       file_act.delete_file,
        "list_files":        file_act.list_files,
        "add_app_mapping":   file_act.add_app_mapping,

        # Web
        "web_search":        web_act.web_search,
        "youtube_search":    web_act.youtube_search,
        "play_media":        web_act.play_media,
        "open_url":          web_act.open_url,

        # Developer (gated by DEVELOPER_MODE flag)
        "run_python_file":   dev_act.run_python_file,
        "git_command":       dev_act.git_command,
        "open_vscode_project": dev_act.open_vscode_project,

        # Meta
        "activate_mode":     _activate_mode,
        "run_routine":       _activate_mode,
        "help":              _help,
        "unknown":           _unknown,
        "stop":              _stop,
    }


def _activate_mode(mode: str = "", **_) -> None:
    """Spoken feedback when a mode/routine has no defined steps."""
    from utils import speak
    speak(f"No routine defined for {mode} mode yet. Add steps to memory.json.")


def _help(**_) -> None:
    from utils import speak
    speak(
        "I can open apps, search the web, control volume, manage files, "
        "run developer commands, activate modes, and more. "
        "You can also chain commands using 'and', for example: "
        "open chrome and search for python tutorials."
    )


def _unknown(**_) -> None:
    from utils import speak
    speak("Sorry, I didn't understand that command.")


def _stop(**_) -> None:
    from utils import speak
    import sys
    speak("Goodbye!")
    sys.exit(0)
