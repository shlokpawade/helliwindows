"""
listener.py – Offline Speech-to-Text using Vosk.

Captures a single utterance from the microphone after the wake word fires
and returns the recognised text.
"""

import json
import queue

import numpy as np
import sounddevice as sd
from vosk import KaldiRecognizer, Model

from config import (
    AUDIO_BLOCK_SIZE,
    AUDIO_SAMPLE_RATE,
    MIC_DEVICE_INDEX,
    STT_AUDIO_GAIN,
    STT_SILENCE_THRESHOLD,
    VOSK_MODEL_PATH,
)
from utils import logger, speak

# Seconds of continuous silence after speech before the utterance is complete
_SILENCE_TIMEOUT = 3.0
# Hard upper limit so the listener never blocks forever
_MAX_LISTEN_DURATION = 15.0


def _process_chunk(data: bytes, gain: float) -> tuple[bytes, float]:
    """
    Apply gain to PCM int16 audio and compute its RMS energy in one pass.

    Returns (boosted_bytes, rms).  RMS is measured on the *original* signal so
    that silence detection reflects the true microphone level.
    """
    samples = np.frombuffer(data, dtype=np.int16).astype(np.float32)
    rms = float(np.sqrt(np.mean(samples ** 2))) if samples.size else 0.0
    if gain != 1.0:
        samples = np.clip(samples * gain, -32768, 32767)
        return samples.astype(np.int16).tobytes(), rms
    return data, rms


class Listener:
    """Record one utterance and return the transcribed text."""

    def __init__(self) -> None:
        logger.info("Loading Vosk STT model from: %s", VOSK_MODEL_PATH)
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
        rec.SetWords(True)  # include per-word timestamps in results

        def _callback(indata, frames, time, status):  # noqa: ANN001
            if status:
                logger.warning("STT audio status: %s", status)
            audio_q.put(bytes(indata))

        text = ""
        best_partial = ""
        silence_chunks = 0
        started_speaking = False
        max_silence = int(_SILENCE_TIMEOUT * AUDIO_SAMPLE_RATE / AUDIO_BLOCK_SIZE)
        max_chunks = int(_MAX_LISTEN_DURATION * AUDIO_SAMPLE_RATE / AUDIO_BLOCK_SIZE)
        total_chunks = 0

        with sd.InputStream(
            samplerate=AUDIO_SAMPLE_RATE,
            blocksize=AUDIO_BLOCK_SIZE,
            device=MIC_DEVICE_INDEX,
            dtype="int16",
            channels=1,
            callback=_callback,
        ):
            while total_chunks < max_chunks:
                try:
                    data = audio_q.get(timeout=_SILENCE_TIMEOUT + 1)
                except queue.Empty:
                    break

                total_chunks += 1
                data, rms = _process_chunk(data, STT_AUDIO_GAIN)

                # Energy-based silence detection (independent of Vosk output)
                if rms < STT_SILENCE_THRESHOLD:
                    if started_speaking:
                        silence_chunks += 1
                else:
                    started_speaking = True
                    silence_chunks = 0

                if rec.AcceptWaveform(data):
                    chunk = json.loads(rec.Result()).get("text", "").strip()
                    if chunk:
                        text += (" " + chunk) if text else chunk
                else:
                    partial = json.loads(rec.PartialResult()).get("partial", "")
                    if partial and len(partial) > len(best_partial):
                        best_partial = partial

                if started_speaking and silence_chunks >= max_silence:
                    break

        # Flush any remaining audio
        final = json.loads(rec.FinalResult()).get("text", "").strip()
        if final and final not in text:
            text += (" " + final) if text else final

        if not text and best_partial:
            logger.info("STT partial fallback: '%s'", best_partial)
            text = best_partial

        logger.info("STT result: '%s'", text)
        return text.strip()
