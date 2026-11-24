"""Create a ten-second synthetic soundtrack and CUE sheet for the example project."""

import wave
from pathlib import Path

import numpy as np

destination = Path(__file__).resolve().parents[1] / ".output" / "demo"
destination.mkdir(parents=True, exist_ok=True)
rate = 48000
time = np.arange(rate * 10) / rate
signal = np.zeros_like(time)
for onset in np.arange(0.5, 10, 0.5):
    elapsed = np.maximum(0, time - onset)
    signal += (
        np.sin(2 * np.pi * (60 * elapsed + 40 * (1 - np.exp(-elapsed * 15))))
        * np.exp(-elapsed * 15)
        * (time >= onset)
    )
samples = (np.clip(signal, -1, 1) * 12000).astype("<i2")
with wave.open(str(destination / "mix.wav"), "wb") as handle:
    handle.setparams((1, 2, rate, 0, "NONE", "not compressed"))
    handle.writeframes(samples.tobytes())
(destination / "mix.cue").write_text(
    'FILE "mix.wav" WAVE\nPERFORMER "videobingus"\n'
    'TRACK 01 AUDIO\nTITLE "Test signal A"\nINDEX 01 00:00:00\n'
    'TRACK 02 AUDIO\nTITLE "Test signal B"\nINDEX 01 00:05:00\n',
    encoding="utf-8",
)
print(destination)
