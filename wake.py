"""
wake.py – Wake-word detection using Vosk keyword spotting.

Listens on the microphone in a background thread and calls *on_wake()*
when "hey windows" is detected with sufficient confidence.
"""

import json
import queue
import threading
from collections.abc import Callable

import sounddevice as sd
from vosk import KaldiRecognizer, Model

from config import (
    AUDIO_BLOCK_SIZE,
    AUDIO_SAMPLE_RATE,
    MIC_DEVICE_INDEX,
    VOSK_MODEL_PATH,
    WAKE_SENSITIVITY,
    WAKE_WORD,
)
from utils import logger


class WakeWordDetector:
    """Runs Vosk in a thread; fires *on_wake* when wake word is heard."""

    def __init__(self, on_wake: Callable[[], None]) -> None:
        self._on_wake = on_wake
        self._stop_event = threading.Event()
        self._audio_queue: queue.Queue[bytes] = queue.Queue()
        self._thread: threading.Thread | None = None

        logger.info("Loading Vosk model for wake-word detection …")
        model = Model(VOSK_MODEL_PATH)
        # Keyword list format for Vosk grammar
        grammar = json.dumps(["hey windows"])
        self._rec = KaldiRecognizer(model, AUDIO_SAMPLE_RATE, grammar)
        # Enable per-word confidence scores in Result() JSON
        self._rec.SetWords(True)
        logger.info("Wake-word detector ready. Listening for '%s' …", WAKE_WORD)

    # ------------------------------------------------------------------
    # Streaming callback
    # ------------------------------------------------------------------
    def _audio_callback(
        self,
        indata: "np.ndarray",   # noqa: F821
        frames: int,
        time,                   # noqa: ANN001
        status,                 # noqa: ANN001
    ) -> None:
        if status:
            logger.warning("Audio status: %s", status)
        self._audio_queue.put(bytes(indata))

    # ------------------------------------------------------------------
    # Detection loop
    # ------------------------------------------------------------------
    def _detect_loop(self) -> None:
        with sd.InputStream(
            samplerate=AUDIO_SAMPLE_RATE,
            blocksize=AUDIO_BLOCK_SIZE,
            device=MIC_DEVICE_INDEX,
            dtype="int16",
            channels=1,
            callback=self._audio_callback,
        ):
            while not self._stop_event.is_set():
                try:
                    data = self._audio_queue.get(timeout=0.5)
                except queue.Empty:
                    continue

                if self._rec.AcceptWaveform(data):
                    result = json.loads(self._rec.Result())
                    text: str = result.get("text", "").strip()
                    logger.debug("Wake recogniser result: '%s'", text)

                    # Only trigger on an exact, full match of the wake word.
                    if text == WAKE_WORD:
                        # Use the minimum per-word confidence so every syllable
                        # must be confident; fall back to 0.0 when words are absent.
                        words = result.get("result", [])
                        conf: float = (
                            min((w.get("conf", 0.0) for w in words), default=0.0)
                            if words
                            else result.get("confidence", 0.0)
                        )
                        logger.debug("Wake word match conf=%.2f (threshold=%.2f)", conf, WAKE_SENSITIVITY)
                        if conf >= WAKE_SENSITIVITY:
                            logger.info("Wake word detected! (conf=%.2f)", conf)
                            self._on_wake()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._detect_loop, name="wake-detector", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3)
