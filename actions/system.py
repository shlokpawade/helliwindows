"""
actions/system.py – System-level actions.

Covers: app launching/closing, volume control, shutdown/restart/sleep/lock,
screenshots, and time/date queries.

Developer-mode actions (run Python files, git, VS Code) live in actions/dev.py.
"""

import os
import subprocess
from datetime import datetime
from pathlib import Path

import psutil
from comtypes import CLSCTX_ALL
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

from config import CONFIRM_DANGEROUS
from utils import confirm_action, logger, run_command, speak

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
            speak(f"Opening {app}.")
        except OSError:
            # Fallback: use subprocess (handles commands on PATH like 'code')
            try:
                subprocess.Popen([executable], shell=False)  # noqa: S603
                self._memory.set_last_app(app)
                speak(f"Opening {app}.")
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
            speak(f"Closed {app}.")
        else:
            speak(f"I couldn't find {app} running.")

    # ------------------------------------------------------------------
    # Volume
    # ------------------------------------------------------------------
    @staticmethod
    def _get_volume_interface():
        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        return interface.QueryInterface(IAudioEndpointVolume)

    def volume_up(self) -> None:
        vol = self._get_volume_interface()
        current = vol.GetMasterVolumeLevelScalar()
        new_val = min(1.0, current + 0.1)
        vol.SetMasterVolumeLevelScalar(new_val, None)
        speak(f"Volume up to {int(new_val * 100)} percent.")

    def volume_down(self) -> None:
        vol = self._get_volume_interface()
        current = vol.GetMasterVolumeLevelScalar()
        new_val = max(0.0, current - 0.1)
        vol.SetMasterVolumeLevelScalar(new_val, None)
        speak(f"Volume down to {int(new_val * 100)} percent.")

    def mute(self) -> None:
        self._get_volume_interface().SetMute(1, None)
        speak("Muted.")

    def unmute(self) -> None:
        self._get_volume_interface().SetMute(0, None)
        speak("Unmuted.")

    def set_volume(self, value: int | None = None, **_) -> None:
        if value is None:
            speak("Please specify a volume level between 0 and 100.")
            return
        clamped = max(0, min(100, int(value)))
        self._get_volume_interface().SetMasterVolumeLevelScalar(clamped / 100, None)
        speak(f"Volume set to {clamped} percent.")

    # ------------------------------------------------------------------
    # Power / session
    # ------------------------------------------------------------------
    def shutdown(self) -> None:
        if not confirm_action("shutdown"):
            speak("Shutdown cancelled.")
            return
        speak("Shutting down Windows.")
        run_command(["shutdown", "/s", "/t", "5"])

    def restart(self) -> None:
        if not confirm_action("restart"):
            speak("Restart cancelled.")
            return
        speak("Restarting Windows.")
        run_command(["shutdown", "/r", "/t", "5"])

    def sleep(self) -> None:
        speak("Going to sleep.")
        run_command(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])

    def lock(self) -> None:
        speak("Locking the screen.")
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
            speak(f"Screenshot saved to {path}.")
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
            speak(f"Sent message to {contact}.")
        except ImportError:
            speak("pyautogui is not installed. Run pip install pyautogui to enable messaging automation.")
        except Exception as e:
            speak(f"Failed to send message: {e}")


