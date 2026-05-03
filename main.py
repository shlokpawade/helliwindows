"""
main.py – Jarvis Windows Assistant entry point.

Pipeline:
  wake word  →  STT  →  intent (brain)  →  plan  →  action  →  memory

The wake-word detector runs in a daemon thread.
The main loop blocks until a wake word fires, then runs the full pipeline
synchronously on the main thread to keep TTS/audio sequenced correctly.

Optional features enabled by environment / config:
  KEYBOARD_TRIGGER_MODE=true  – skip Vosk wake word; press Enter to speak
  Tray icon                   – auto-enabled when pystray + Pillow are installed
"""

import signal
import sys
import threading
import types

from actions import build_action_registry
from brain import Brain
from config import KEYBOARD_TRIGGER_MODE, WAKE_WORD
from listener import Listener
from memory import Memory
from planner import Planner
from scheduler import reminder_store
from tray import TrayIcon
from utils import logger, speak, show_wake_animation, start_listening_light, stop_listening_light
from wake import WakeWordDetector


class JarvisAssistant:
    def __init__(self) -> None:
        logger.info("Initialising Jarvis Windows Assistant …")
        self._memory = Memory()

        # Fire any reminders that were set before a previous restart
        reminder_store.fire_overdue()

        self._listener = Listener()
        self._brain = Brain(self._memory)
        self._planner = Planner(self._memory)
        self._planner.register_actions(build_action_registry(self._memory, self._listener))

        self._wake_event = threading.Event()

        if KEYBOARD_TRIGGER_MODE:
            # Keyboard-trigger mode: no Vosk model required
            self._detector = None
            logger.info(
                "Keyboard-trigger mode active. Press Enter in the terminal to speak."
            )
        else:
            self._detector = WakeWordDetector(on_wake=self._wake_event.set)

        # Optional system-tray icon (requires pystray + Pillow)
        self._tray = TrayIcon(on_quit=self.stop)
        self._tray.start()

        self._running = True

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------
    def run(self) -> None:
        if KEYBOARD_TRIGGER_MODE:
            speak("Jarvis is ready. Press Enter to speak a command.")
            self._keyboard_loop()
        else:
            speak(f"Jarvis is ready. Say '{WAKE_WORD}' to start.")
            self._detector.start()
            self._wake_loop()

    def _wake_loop(self) -> None:
        """Main loop: wait for wake-word event then handle one turn."""
        while self._running:
            logger.debug("Waiting for wake word …")
            triggered = self._wake_event.wait(timeout=1.0)
            if not triggered:
                continue
            self._wake_event.clear()
            self._tray.set_status("listening")
            self._handle_turn()
            self._tray.set_status("ready")

    def _keyboard_loop(self) -> None:
        """Keyboard-trigger loop: press Enter in the terminal to listen."""
        while self._running:
            try:
                input()   # blocks until Enter is pressed
            except EOFError:
                break
            self._tray.set_status("listening")
            self._handle_turn()
            self._tray.set_status("ready")

    def _handle_turn(self) -> None:
        """One full listen → understand → act cycle."""
        show_wake_animation()
        speak_async("how can i help you today")
        listening_light = start_listening_light()
        logger.info("listening")
        try:
            text = self._listener.listen()
        finally:
            stop_listening_light(listening_light)
        if not text:
            speak("I didn't catch that. Please try again.")
            return

        intents = self._brain.parse_multi(text)
        logger.info("Parsed %d intent(s) from: '%s'", len(intents), text)
        for intent in intents:
            logger.debug("  Intent: %s  args: %s", intent.name, intent.args)

        success = self._planner.plan_and_run_multi(intents)
        # Record each recognised intent in memory (with args for context)
        for intent in intents:
            self._memory.record_command(text, intent.name, success, args=intent.args)

    # ------------------------------------------------------------------
    # Graceful shutdown
    # ------------------------------------------------------------------
    def stop(self) -> None:
        logger.info("Shutting down Jarvis …")
        self._running = False
        if self._detector is not None:
            self._detector.stop()
        self._tray.stop()


def _handle_signal(sig: int, frame: types.FrameType | None) -> None:
    logger.info("Signal %s received; stopping.", sig)
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    assistant = JarvisAssistant()
    assistant.run()

