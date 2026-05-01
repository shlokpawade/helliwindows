"""
main.py – Jarvis Windows Assistant entry point.

Pipeline:
  wake word  →  STT  →  intent (brain)  →  plan  →  action  →  memory

The wake-word detector runs in a daemon thread.
The main loop blocks until a wake word fires, then runs the full pipeline
synchronously on the main thread to keep TTS/audio sequenced correctly.
"""

import signal
import sys
import threading
import types

from actions import build_action_registry
from brain import Brain
from config import WAKE_WORD
from listener import Listener
from memory import Memory
from planner import Planner
from utils import logger, speak, show_wake_animation, show_listening_animation
from wake import WakeWordDetector


class JarvisAssistant:
    def __init__(self) -> None:
        logger.info("Initialising Jarvis Windows Assistant …")
        self._memory = Memory()
        self._listener = Listener()
        self._brain = Brain(self._memory)
        self._planner = Planner(self._memory)
        self._planner.register_actions(build_action_registry(self._memory, self._listener))

        self._wake_event = threading.Event()
        self._detector = WakeWordDetector(on_wake=self._wake_event.set)

        self._running = True

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------
    def run(self) -> None:
        speak(f"Jarvis is ready. Say '{WAKE_WORD}' to start.")
        self._detector.start()

        while self._running:
            logger.debug("Waiting for wake word …")
            triggered = self._wake_event.wait(timeout=1.0)
            if not triggered:
                continue
            self._wake_event.clear()
            self._handle_turn()

    def _handle_turn(self) -> None:
        """One full listen → understand → act cycle."""
        show_wake_animation()
        speak("how can i help you today")
        show_listening_animation()
        logger.info("listening")
        text = self._listener.listen()
        if not text:
            speak("I didn't catch that. Please try again.")
            return

        intents = self._brain.parse_multi(text)
        logger.info("Parsed %d intent(s) from: '%s'", len(intents), text)
        for intent in intents:
            logger.debug("  Intent: %s  args: %s", intent.name, intent.args)

        success = self._planner.plan_and_run_multi(intents)
        # Record each recognised intent in memory
        for intent in intents:
            self._memory.record_command(text, intent.name, success)

    # ------------------------------------------------------------------
    # Graceful shutdown
    # ------------------------------------------------------------------
    def stop(self) -> None:
        logger.info("Shutting down Jarvis …")
        self._running = False
        self._detector.stop()


def _handle_signal(sig: int, frame: types.FrameType | None) -> None:
    logger.info("Signal %s received; stopping.", sig)
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    assistant = JarvisAssistant()
    assistant.run()
