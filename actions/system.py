"""
actions/system.py – System-level actions.

Covers: app launching/closing, volume control, shutdown/restart/sleep/lock,
screenshots, and time/date queries.

Developer-mode actions (run Python files, git, VS Code) live in actions/dev.py.
"""

import os
import subprocess
import urllib.parse
import webbrowser
from datetime import datetime
from pathlib import Path

import psutil
from comtypes import CLSCTX_ALL
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

from config import CONFIRM_DANGEROUS
from utils import confirm_action, logger, run_command, speak, speak_async

# Characters not allowed in application names resolved from memory/voice input
_UNSAFE_CHARS = set(';&|<>`$\'\"\\')


def _safe_executable(name: str) -> str | None:
    """
    Return *name* only if it contains no shell-injection characters.
    Returns None if the name looks unsafe.
    """
    if any(c in _UNSAFE_CHARS for c in name):
        logger.warning("Rejected unsafe executable name: %r", name)
        return None
    return name


class SystemActions:
    def __init__(self, memory) -> None:
        self._memory = memory
        self._volume_iface = None   # cached COM volume interface
        self._brightness = 50       # tracked brightness level (0–100)

    # ------------------------------------------------------------------
    # App control
    # ------------------------------------------------------------------
    def open_app(self, app: str) -> None:
        raw_executable = self._memory.resolve_app(app) or app
        executable = _safe_executable(raw_executable)
        if executable is None:
            speak(f"Unsafe application name rejected: {app}.")
            return
        logger.info("Opening app: %s (%s)", app, executable)
        try:
            os.startfile(executable)
            self._memory.set_last_app(app)
            speak_async(f"Opening {app} now.")
        except OSError:
            # Fallback: use subprocess (handles commands on PATH like 'code')
            try:
                subprocess.Popen([executable], shell=False)  # noqa: S603
                self._memory.set_last_app(app)
                speak_async(f"Opening {app} now.")
            except FileNotFoundError:
                speak(f"I couldn't find {app}. Try teaching me the executable path first.")

    def open_last_app(self) -> None:
        last = self._memory.last_app_opened()
        if last:
            self.open_app(last)
        else:
            speak("I don't remember the last app you opened.")

    def close_app(self, app: str) -> None:
        """Terminate all processes whose name contains *app*."""
        killed = 0
        for proc in psutil.process_iter(["name", "pid"]):
            if app.lower() in proc.info["name"].lower():
                try:
                    proc.terminate()
                    killed += 1
                except psutil.AccessDenied:
                    logger.warning("Access denied closing %s", proc.info["name"])
        if killed:
            speak_async(f"Closed {app}.")
        else:
            speak(f"I couldn't find {app} running.")

    # ------------------------------------------------------------------
    # Volume
    # ------------------------------------------------------------------
    def _get_volume_interface(self):
        """Return a cached IAudioEndpointVolume COM interface."""
        if self._volume_iface is None:
            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            self._volume_iface = interface.QueryInterface(IAudioEndpointVolume)
        return self._volume_iface

    def volume_up(self) -> None:
        vol = self._get_volume_interface()
        current = vol.GetMasterVolumeLevelScalar()
        new_val = min(1.0, current + 0.1)
        vol.SetMasterVolumeLevelScalar(new_val, None)
        speak_async(f"Volume up to {int(new_val * 100)} percent.")

    def volume_down(self) -> None:
        vol = self._get_volume_interface()
        current = vol.GetMasterVolumeLevelScalar()
        new_val = max(0.0, current - 0.1)
        vol.SetMasterVolumeLevelScalar(new_val, None)
        speak_async(f"Volume down to {int(new_val * 100)} percent.")

    def mute(self) -> None:
        self._get_volume_interface().SetMute(1, None)
        speak_async("Muted.")

    def unmute(self) -> None:
        self._get_volume_interface().SetMute(0, None)
        speak_async("Unmuted.")

    def set_volume(self, value: int | None = None, **_) -> None:
        if value is None:
            speak("Please specify a volume level between 0 and 100.")
            return
        clamped = max(0, min(100, int(value)))
        self._get_volume_interface().SetMasterVolumeLevelScalar(clamped / 100, None)
        speak_async(f"Volume set to {clamped} percent.")

    # ------------------------------------------------------------------
    # Power / session
    # ------------------------------------------------------------------
    def shutdown(self) -> None:
        if not confirm_action("shutdown"):
            speak("Shutdown cancelled.")
            return
        speak_async("Shutting down Windows now.")
        run_command(["shutdown", "/s", "/t", "5"])

    def restart(self) -> None:
        if not confirm_action("restart"):
            speak("Restart cancelled.")
            return
        speak_async("Restarting Windows now.")
        run_command(["shutdown", "/r", "/t", "5"])

    def sleep(self) -> None:
        speak_async("Going to sleep.")
        run_command(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])

    def lock(self) -> None:
        speak_async("Locking the screen.")
        run_command(["rundll32.exe", "user32.dll,LockWorkStation"])

    # ------------------------------------------------------------------
    # Screenshot
    # ------------------------------------------------------------------
    def screenshot(self) -> None:
        try:
            import pyautogui  # optional dependency
            from datetime import datetime as _dt
            path = os.path.join(os.path.expanduser("~"), "Pictures",
                                f"screenshot_{_dt.now().strftime('%Y%m%d_%H%M%S')}.png")
            pyautogui.screenshot(path)
            speak_async(f"Screenshot saved to {path}.")
        except ImportError:
            speak("pyautogui is not installed. Run pip install pyautogui to enable screenshots.")

    # ------------------------------------------------------------------
    # Time / date
    # ------------------------------------------------------------------
    def get_time(self) -> None:
        now = datetime.now().strftime("%I:%M %p")
        speak(f"It is {now}.")

    def get_date(self) -> None:
        today = datetime.now().strftime("%A, %B %d, %Y")
        speak(f"Today is {today}.")

    def chat_response(self, message: str) -> None:
        """Speak a general information response from the LLM."""
        speak(message)

    def ask_llm(self, query: str) -> None:
        """Answer a knowledge question using phi3:mini directly, without opening the browser.

        Falls back to a web search only if the local LLM is unavailable.
        """
        from brain import query_llm_direct  # local import – avoids circular dependency

        logger.info("ask_llm: %s", query)
        speak_async("Let me check that for you.")
        answer = query_llm_direct(query)
        if answer:
            speak(answer)
        else:
            # LLM unavailable – open browser as a last resort
            logger.info("ask_llm: LLM unavailable, falling back to web search for '%s'", query)
            encoded = urllib.parse.quote_plus(query)
            webbrowser.open(f"https://www.google.com/search?q={encoded}")
            speak(f"I couldn't answer that directly. Opening a web search for {query}.")

    # ------------------------------------------------------------------
    # Battery / system info
    # ------------------------------------------------------------------
    def get_battery(self) -> None:
        battery = psutil.sensors_battery()
        if battery is None:
            speak("Battery information is not available on this device.")
            return
        pct = int(battery.percent)
        status = "charging" if battery.power_plugged else "not charging"
        speak(f"Battery is at {pct} percent and {status}.")

    def get_system_info(self) -> None:
        cpu = psutil.cpu_percent(interval=0.5)
        ram = psutil.virtual_memory()
        used_gb = round(ram.used / (1024 ** 3), 1)
        total_gb = round(ram.total / (1024 ** 3), 1)
        speak(
            f"CPU usage is {cpu} percent. "
            f"RAM usage is {ram.percent} percent, "
            f"{used_gb} of {total_gb} gigabytes used."
        )

    # ------------------------------------------------------------------
    # Brightness
    # ------------------------------------------------------------------
    @staticmethod
    def _set_brightness_wmi(level: int) -> None:
        """Set display brightness via PowerShell WMI (built-in screens only)."""
        try:
            subprocess.run(
                [
                    "powershell", "-NonInteractive", "-Command",
                    f"(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods)"
                    f".WmiSetBrightness(1,{level})",
                ],
                check=False, timeout=5, capture_output=True,
            )
            logger.info("Brightness set to %d%%", level)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not set brightness: %s", exc)

    def brightness_up(self) -> None:
        self._brightness = min(100, self._brightness + 10)
        self._set_brightness_wmi(self._brightness)
        speak_async(f"Brightness increased to {self._brightness} percent.")

    def brightness_down(self) -> None:
        self._brightness = max(0, self._brightness - 10)
        self._set_brightness_wmi(self._brightness)
        speak_async(f"Brightness decreased to {self._brightness} percent.")

    def set_brightness(self, value: int | None = None, **_) -> None:
        if value is None:
            speak("Please specify a brightness level between 0 and 100.")
            return
        self._brightness = max(0, min(100, int(value)))
        self._set_brightness_wmi(self._brightness)
        speak_async(f"Brightness set to {self._brightness} percent.")

    # ------------------------------------------------------------------
    # Media controls (global media keys via pyautogui)
    # ------------------------------------------------------------------
    def media_pause_play(self) -> None:
        """Toggle play/pause for any active media."""
        try:
            import pyautogui  # optional dependency
            pyautogui.press("playpause")
            speak_async("Toggled media playback.")
        except ImportError:
            speak("pyautogui is not installed. Run pip install pyautogui to enable media keys.")

    def media_next(self) -> None:
        """Skip to the next media track."""
        try:
            import pyautogui
            pyautogui.press("nexttrack")
            speak_async("Next track.")
        except ImportError:
            speak("pyautogui is not installed.")

    def media_previous(self) -> None:
        """Go back to the previous media track."""
        try:
            import pyautogui
            pyautogui.press("prevtrack")
            speak_async("Previous track.")
        except ImportError:
            speak("pyautogui is not installed.")

    # ------------------------------------------------------------------
    # Keyboard / input automation
    # ------------------------------------------------------------------
    def type_text(self, text: str = "") -> None:
        """Type *text* into the currently focused window using copy-paste."""
        if not text:
            speak("What would you like me to type?")
            return
        try:
            import pyautogui
            import pyperclip
            import time
            pyperclip.copy(text)
            time.sleep(0.2)
            pyautogui.hotkey("ctrl", "v")
            logger.info("Typed text (%d chars)", len(text))
            speak_async("Done.")
        except ImportError:
            speak("pyautogui or pyperclip is not installed.")
        except Exception as exc:  # noqa: BLE001
            logger.warning("type_text failed: %s", exc)
            speak("Sorry, I couldn't type that.")

    def press_hotkey(self, keys: str = "") -> None:
        """Press a keyboard shortcut, e.g. 'ctrl v', 'alt tab', 'win d'."""
        if not keys:
            speak("Please specify the keys to press.")
            return
        _KEY_MAP = {
            "control": "ctrl",
            "escape": "esc",
            "windows": "win",
            "delete": "del",
            "return": "enter",
            "page up": "pageup",
            "page down": "pagedown",
        }
        try:
            import pyautogui
            key_list = keys.lower().strip().split()
            mapped = [_KEY_MAP.get(k, k) for k in key_list]
            if len(mapped) == 1:
                pyautogui.press(mapped[0])
            else:
                pyautogui.hotkey(*mapped)
            speak_async(f"Pressed {keys}.")
            logger.info("Pressed hotkey: %s", keys)
        except ImportError:
            speak("pyautogui is not installed.")
        except Exception as exc:  # noqa: BLE001
            logger.warning("press_hotkey '%s' failed: %s", keys, exc)
            speak(f"Couldn't press {keys}.")

    # ------------------------------------------------------------------
    # Desktop management
    # ------------------------------------------------------------------
    def show_desktop(self) -> None:
        """Minimise all windows and show the desktop (Win + D)."""
        try:
            import pyautogui
            pyautogui.hotkey("win", "d")
        except ImportError:
            run_command(
                ["powershell", "-Command",
                 "(New-Object -ComObject Shell.Application).MinimizeAll()"]
            )
        speak_async("Showing desktop.")

    def empty_recycle_bin(self) -> None:
        """Empty the Windows Recycle Bin silently."""
        try:
            subprocess.run(
                [
                    "powershell", "-NonInteractive", "-Command",
                    "Clear-RecycleBin -Confirm:$false -ErrorAction SilentlyContinue",
                ],
                capture_output=True, timeout=15, check=False,
            )
            speak("Recycle bin emptied.")
            logger.info("Recycle bin emptied.")
        except Exception as exc:  # noqa: BLE001
            logger.warning("empty_recycle_bin failed: %s", exc)
            speak("Sorry, I couldn't empty the recycle bin.")

    # ------------------------------------------------------------------
    # Messaging
    # ------------------------------------------------------------------
    def send_whatsapp_message(self, contact: str, message: str) -> None:
        """Send a WhatsApp message using pyautogui automation."""
        try:
            import pyautogui as pg  # optional dependency
            import time
            # Assume WhatsApp is open and focused
            # Search for contact
            pg.hotkey('ctrl', 'f')  # Open search
            time.sleep(0.5)
            pg.write(contact, interval=0.1)
            time.sleep(1)
            pg.press('enter')  # Select contact
            time.sleep(0.5)
            pg.write(message, interval=0.1)
            pg.press('enter')  # Send
            speak_async(f"Sent message to {contact}.")
        except ImportError:
            speak("pyautogui is not installed. Run pip install pyautogui to enable messaging automation.")
        except Exception as e:
            speak(f"Failed to send message: {e}")


