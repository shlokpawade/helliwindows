"""
listener.py – Offline Speech-to-Text using Vosk.

Captures a single utterance from the microphone after the wake word fires
and returns the recognised text.
"""

import json
import queue

import sounddevice as sd
from vosk import KaldiRecognizer, Model

from config import (
    AUDIO_BLOCK_SIZE,
    AUDIO_SAMPLE_RATE,
    MIC_DEVICE_INDEX,
    VOSK_MODEL_PATH,
)
from utils import logger, speak

# Maximum silence (in seconds) before considering the utterance complete
_SILENCE_TIMEOUT = 2.0


class Listener:
    """Record one utterance and return the transcribed text."""

    def __init__(self) -> None:
        logger.info("Loading Vosk STT model …")
        model = Model(VOSK_MODEL_PATH)
        self._model = model
        logger.info("STT listener ready.")

    def listen(self) -> str:
        """
        Open the microphone, record until silence, and return the transcription.
        Returns an empty string on failure.
        """
        speak("Listening …")
        audio_q: queue.Queue[bytes] = queue.Queue()
        rec = KaldiRecognizer(self._model, AUDIO_SAMPLE_RATE)

        def _callback(indata, frames, time, status):  # noqa: ANN001
            if status:
                logger.warning("STT audio status: %s", status)
            audio_q.put(bytes(indata))

        text = ""
        silence_chunks = 0
        max_silence = int(_SILENCE_TIMEOUT * AUDIO_SAMPLE_RATE / AUDIO_BLOCK_SIZE)

        with sd.RawInputStream(
            samplerate=AUDIO_SAMPLE_RATE,
            blocksize=AUDIO_BLOCK_SIZE,
            device=MIC_DEVICE_INDEX,
            dtype="int16",
            channels=1,
            callback=_callback,
        ):
            while True:
                try:
                    data = audio_q.get(timeout=_SILENCE_TIMEOUT + 1)
                except queue.Empty:
                    break

                if rec.AcceptWaveform(data):
                    result = json.loads(rec.Result())
                    chunk = result.get("text", "").strip()
                    if chunk:
                        text += (" " + chunk) if text else chunk
                        silence_chunks = 0
                    else:
                        silence_chunks += 1
                else:
                    partial = json.loads(rec.PartialResult()).get("partial", "")
                    if not partial:
                        silence_chunks += 1
                    else:
                        silence_chunks = 0

                if silence_chunks >= max_silence:
                    break

        # Flush any remaining audio
        final = json.loads(rec.FinalResult()).get("text", "").strip()
        if final and final not in text:
            text += (" " + final) if text else final

        logger.info("STT result: '%s'", text)
        return text.strip()
