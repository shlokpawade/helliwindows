import json
import sounddevice as sd
from vosk import KaldiRecognizer, Model

MODEL_PATH = "models/vosk-model-small-en-us-0.15"
SAMPLE_RATE = 16000

print("Loading model...")
model = Model(MODEL_PATH)
grammar = json.dumps(["hey windows"])
rec = KaldiRecognizer(model, SAMPLE_RATE, grammar)

print("Recording for 5 seconds...")
audio = sd.rec(int(5 * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1, dtype='int16')
sd.wait()

print("Recognizing...")
rec.AcceptWaveform(audio.tobytes())
result = json.loads(rec.Result())
print("Result:", result)