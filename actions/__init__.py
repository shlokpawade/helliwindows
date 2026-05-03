"""
actions/__init__.py – Registers and exports all action handlers.

Import this module to get the complete {action_name: handler} mapping
ready to pass to Planner.register_actions().

Plugin auto-discovery
---------------------
Drop a Python module into the ``actions/`` directory and decorate any
callable with ``@register_action("intent_name")``::

    from actions import register_action

    @register_action("my_custom_action")
    def my_handler(**kwargs):
        ...

The decorator registers the function at import time.  Any module placed in
``actions/`` is auto-imported when ``build_action_registry()`` is called,
so no changes to this file are needed for new plugins.
"""

import importlib
import pkgutil
from collections.abc import Callable
from typing import Any

from actions.dev import DevActions
from actions.files import FileActions
from actions.local import LocalActions
from actions.modes import ModeActions
from actions.network import NetworkActions
from actions.news import NewsActions
from actions.system import SystemActions
from actions.web import WebActions

# ---------------------------------------------------------------------------
# Plugin registry – populated by @register_action
# ---------------------------------------------------------------------------

_plugin_registry: dict[str, Callable] = {}


def register_action(name: str) -> Callable:
    """
    Decorator that registers a function as an action handler.

    Usage::

        @register_action("greet_user")
        def greet(name: str = "friend") -> None:
            from utils import speak
            speak(f"Hello, {name}!")
    """
    def _decorator(fn: Callable) -> Callable:
        _plugin_registry[name] = fn
        return fn
    return _decorator


def _auto_discover_plugins() -> None:
    """
    Import every module inside the ``actions`` package so that any
    ``@register_action`` decorators they contain are executed.

    Already-imported modules (dev, files, local, modes, network, news,
    system, web) are skipped gracefully via importlib's cache.
    """
    import actions as _pkg
    for _finder, mod_name, _is_pkg in pkgutil.iter_modules(_pkg.__path__):
        full_name = f"actions.{mod_name}"
        try:
            importlib.import_module(full_name)
        except Exception as exc:  # noqa: BLE001
            import logging
            logging.getLogger("jarvis").warning(
                "Plugin auto-discovery: could not import %s: %s", full_name, exc
            )


def build_action_registry(memory: Any, listener: Any = None) -> dict[str, Callable]:
    """Return a flat dict of {action_name: callable} for all modules."""
    # Auto-discover plugin modules before building the registry so any
    # @register_action decorators in drop-in action files are executed.
    _auto_discover_plugins()

    sys_act  = SystemActions(memory)
    file_act = FileActions(memory)
    web_act  = WebActions(memory)
    dev_act  = DevActions()
    local_act = LocalActions()
    mode_act  = ModeActions(
        listener=listener, sys_act=sys_act,
        web_act=web_act, dev_act=dev_act,
    )
    news_act = NewsActions()
    net_act  = NetworkActions()

    registry: dict[str, Callable] = {
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
        # Process management
        "list_running_apps": sys_act.list_running_apps,
        "kill_process":      sys_act.kill_process,
        # Window snapping
        "snap_window":       sys_act.snap_window,
        # Speech rate
        "speech_rate_up":    sys_act.speech_rate_up,
        "speech_rate_down":  sys_act.speech_rate_down,
        "set_speech_rate":   sys_act.set_speech_rate,

        # Files
        "open_file":         file_act.open_file,
        "delete_file":       file_act.delete_file,
        "list_files":        file_act.list_files,
        "create_folder":     file_act.create_folder,
        "add_app_mapping":   file_act.add_app_mapping,
        "search_files":      file_act.search_files,

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
        "convert_units":     local_act.convert_units,

        # News
        "get_news":          news_act.get_news,

        # Network
        "check_internet":    net_act.check_internet,
        "list_wifi_networks": net_act.list_wifi_networks,
        "connect_wifi":      net_act.connect_wifi,
        "get_ip_address":    net_act.get_ip_address,

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

    # Overlay auto-discovered plugin handlers (plugins can override built-ins)
    registry.update(_plugin_registry)
    return registry


def _help(**_) -> None:
    from utils import speak
    speak(
        "I can open and close apps, search the web, play YouTube videos, "
        "control volume and brightness, manage media playback, "
        "manage files and folders, search for files by name, "
        "run developer commands, check battery and system info, "
        "calculate math, convert units like kilometers to miles or Celsius to Fahrenheit, "
        "set timers and reminders, save and read notes, "
        "read and write the clipboard, get the weather, get news headlines, "
        "check internet connectivity, list Wi-Fi networks, get your IP address, "
        "show the desktop, empty the recycle bin, snap windows left or right, "
        "list running apps, type text and press hotkeys. "
        "Say 'speak faster' or 'speak slower' to adjust my speech speed. "
        "You can chain commands using 'and', for example: "
        "open chrome and play lo-fi music on YouTube. "
        "Say 'press Enter' to speak in keyboard-trigger mode."
    )


def _unknown(**_) -> None:
    from utils import speak
    speak("Sorry, I didn't understand that command.")


def _stop(**_) -> None:
    from utils import speak
    import sys
    speak("Goodbye!")
    sys.exit(0)
