"""
listener.py – Command Speech-to-Text using Whisper.

Captures a single utterance from the microphone after the wake word fires,
then transcribes it with OpenAI Whisper (runs fully offline / on-device).
Vosk is intentionally NOT used here; it is reserved for wake-word detection.
"""

import queue

import numpy as np
import sounddevice as sd
import whisper

from config import (
    AUDIO_BLOCK_SIZE,
    AUDIO_SAMPLE_RATE,
    MIC_DEVICE_INDEX,
    STT_AUDIO_GAIN,
    STT_SILENCE_THRESHOLD,
    WHISPER_LANGUAGE,
    WHISPER_MODEL_SIZE,
)
from utils import logger, speak

# Seconds of continuous silence after speech before the utterance is complete
_SILENCE_TIMEOUT = 3.0
# Hard upper limit so the listener never blocks forever
_MAX_LISTEN_DURATION = 15.0


class Listener:
    """Record one utterance and return the transcribed text (via Whisper)."""

    def __init__(self) -> None:
        logger.info("Loading Whisper model '%s' for command STT …", WHISPER_MODEL_SIZE)
        self._model = whisper.load_model(WHISPER_MODEL_SIZE)
        logger.info("Whisper STT listener ready.")

    def listen(self) -> str:
        """
        Open the microphone, record until silence, transcribe with Whisper,
        and return the recognised text.  Returns an empty string on failure.
        """
        speak("Listening …")
        audio_q: queue.Queue[bytes] = queue.Queue()

        def _callback(indata, frames, time, status):  # noqa: ANN001
            if status:
                logger.warning("STT audio status: %s", status)
            audio_q.put(bytes(indata))

        all_chunks: list[np.ndarray] = []
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
                samples = np.frombuffer(data, dtype=np.int16).astype(np.float32)
                rms = float(np.sqrt(np.mean(samples ** 2))) if samples.size else 0.0

                # Apply gain for quiet microphones
                if STT_AUDIO_GAIN != 1.0:
                    samples = np.clip(samples * STT_AUDIO_GAIN, -32768, 32767)

                all_chunks.append(samples)

                # Energy-based silence detection
                if rms < STT_SILENCE_THRESHOLD:
                    if started_speaking:
                        silence_chunks += 1
                else:
                    started_speaking = True
                    silence_chunks = 0

                if started_speaking and silence_chunks >= max_silence:
                    break

        if not all_chunks:
            logger.warning("No audio captured.")
            return ""

        # Concatenate all PCM int16 samples and normalise to [-1.0, 1.0] float32
        audio_np = np.concatenate(all_chunks) / 32768.0

        # --- Audio pre-processing for better Whisper accuracy ---
        # 1. Remove DC offset (constant bias from the microphone)
        audio_np = audio_np - np.mean(audio_np)
        # 2. Normalise amplitude so quiet utterances are boosted to full scale
        peak = np.max(np.abs(audio_np))
        if peak > 1e-6:
            audio_np = audio_np / peak
        # 3. Pre-emphasis filter: boost high-frequency components (consonants)
        #    which Whisper benefits from for clarity.
        pre_emphasis = 0.97
        audio_np = np.concatenate(
            ([audio_np[0]], audio_np[1:] - pre_emphasis * audio_np[:-1])
        ).astype(np.float32)

        logger.info("Transcribing %d samples with Whisper …", len(audio_np))
        result = self._model.transcribe(
            audio_np,
            language=WHISPER_LANGUAGE,
            fp16=False,
            beam_size=5,
            best_of=5,
            temperature=0.0,
            condition_on_previous_text=False,
            no_speech_threshold=0.6,
            compression_ratio_threshold=2.4,
            initial_prompt=(
                "Jarvis, hey windows, open, search, play, volume, reminder, "
                "timer, note, weather, screenshot, shutdown, restart, lock"
            ),
        )
        text = result.get("text", "").strip()

        logger.info("STT result: '%s'", text)
        return text

