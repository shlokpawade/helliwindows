import json
import sounddevice as sd
from vosk import KaldiRecognizer, Model

from config import AUDIO_SAMPLE_RATE, VOSK_MODEL_PATH

print(f"Loading model from: {VOSK_MODEL_PATH}")
model = Model(VOSK_MODEL_PATH)
grammar = json.dumps(["hey windows"])
rec = KaldiRecognizer(model, AUDIO_SAMPLE_RATE, grammar)

print("Recording for 5 seconds...")
audio = sd.rec(int(5 * AUDIO_SAMPLE_RATE), samplerate=AUDIO_SAMPLE_RATE, channels=1, dtype='int16')
sd.wait()

print("Recognizing...")
rec.AcceptWaveform(audio.tobytes())
result = json.loads(rec.Result())
print("Result:", result)