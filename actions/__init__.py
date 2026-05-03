"""
actions/__init__.py – Registers and exports all action handlers.

Import this module to get the complete {action_name: handler} mapping
ready to pass to Planner.register_actions().
"""

from actions.dev import DevActions
from actions.files import FileActions
from actions.local import LocalActions
from actions.modes import ModeActions
from actions.system import SystemActions
from actions.web import WebActions


def build_action_registry(memory, listener=None) -> dict:
    """Return a flat dict of {action_name: callable} for all modules."""
    sys_act = SystemActions(memory)
    file_act = FileActions(memory)
    web_act = WebActions()
    dev_act = DevActions()
    local_act = LocalActions()
    mode_act = ModeActions(listener=listener, sys_act=sys_act,
                           web_act=web_act, dev_act=dev_act)

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
        "brightness_up":     sys_act.brightness_up,
        "brightness_down":   sys_act.brightness_down,
        "set_brightness":    sys_act.set_brightness,
        "shutdown":          sys_act.shutdown,
        "restart":           sys_act.restart,
        "sleep":             sys_act.sleep,
        "lock":              sys_act.lock,
        "screenshot":        sys_act.screenshot,
        "get_time":          sys_act.get_time,
        "get_date":          sys_act.get_date,
        "get_battery":       sys_act.get_battery,
        "get_system_info":   sys_act.get_system_info,
        "send_whatsapp_message": sys_act.send_whatsapp_message,
        "chat_response":     sys_act.chat_response,
        "ask_llm":           sys_act.ask_llm,
        "show_desktop":      sys_act.show_desktop,
        "empty_recycle_bin": sys_act.empty_recycle_bin,
        "media_pause_play":  sys_act.media_pause_play,
        "media_next":        sys_act.media_next,
        "media_previous":    sys_act.media_previous,
        "type_text":         sys_act.type_text,
        "press_hotkey":      sys_act.press_hotkey,

        # Files
        "open_file":         file_act.open_file,
        "delete_file":       file_act.delete_file,
        "list_files":        file_act.list_files,
        "create_folder":     file_act.create_folder,
        "add_app_mapping":   file_act.add_app_mapping,

        # Web
        "web_search":        web_act.web_search,
        "youtube_search":    web_act.youtube_search,
        "play_media":        web_act.play_media,
        "open_url":          web_act.open_url,

        # Local utilities
        "calculate":         local_act.calculate,
        "set_timer":         local_act.set_timer,
        "set_reminder":      local_act.set_reminder,
        "list_reminders":    local_act.list_reminders,
        "cancel_reminder":   local_act.cancel_reminder,
        "take_note":         local_act.take_note,
        "read_notes":        local_act.read_notes,
        "clear_notes":       local_act.clear_notes,
        "get_weather":       local_act.get_weather,
        "read_clipboard":    local_act.read_clipboard,
        "write_clipboard":   local_act.write_clipboard,

        # Developer (gated by DEVELOPER_MODE flag)
        "run_python_file":   dev_act.run_python_file,
        "git_command":       dev_act.git_command,
        "open_vscode_project": dev_act.open_vscode_project,

        # Meta
        "activate_mode":     mode_act.activate_mode,
        "run_routine":       mode_act.activate_mode,
        "help":              _help,
        "unknown":           _unknown,
        "stop":              _stop,
    }


def _help(**_) -> None:
    from utils import speak
    speak(
        "I can open and close apps, search the web, play YouTube videos, "
        "control volume and brightness, manage media playback, "
        "manage files and folders, run developer commands, "
        "check battery and system info, calculate math, "
        "set timers and reminders, save and read notes, "
        "read and write the clipboard, get the weather, "
        "show the desktop, empty the recycle bin, "
        "type text and press hotkeys, and more. "
        "For knowledge questions say 'who is Elon Musk', 'what is Python', "
        "or 'explain quantum computing' and I'll answer using AI. "
        "You can chain commands using 'and', for example: "
        "open chrome and play lo-fi music on YouTube. "
        "Say 'brightness up', 'brightness down', or 'set brightness to 70'. "
        "Say 'pause music', 'next track', or 'previous track' for media control. "
        "Say 'show desktop' to minimise all windows. "
        "Say 'type hello world' to type into the active window. "
        "Say 'press ctrl c' to press keyboard shortcuts."
    )


def _unknown(**_) -> None:
    from utils import speak
    speak("Sorry, I didn't understand that command.")


def _stop(**_) -> None:
    from utils import speak
    import sys
    speak("Goodbye!")
    sys.exit(0)
