import os
import shutil
import subprocess
import wave

import numpy as np
import pytest

from videobingus.config import load


@pytest.fixture
def project(tmp_path):
    ffmpeg = os.environ.get("VIDEOBINGUS_TEST_FFMPEG") or shutil.which("ffmpeg")
    ffprobe = os.environ.get("VIDEOBINGUS_TEST_FFPROBE") or shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("FFmpeg and FFprobe required for media tests")
    audio = tmp_path / "mix café.wav"
    rate = 16000
    time = np.arange(rate * 2) / rate
    samples = (np.sin(2 * np.pi * 80 * time) * 12000).astype("<i2")
    with wave.open(str(audio), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(samples.tobytes())
    footage = tmp_path / "vidéo assets"
    footage.mkdir()
    for index, size, fps in [(0, "96x72", "12"), (1, "64x96", "15")]:
        subprocess.run(
            [
                ffmpeg,
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                f"testsrc2=s={size}:r={fps}",
                "-t",
                "0.8",
                "-c:v",
                "libx264",
                str(footage / f"clip {index}.mp4"),
            ],
            check=True,
        )
    return load(
        overrides={
            "audio": audio,
            "sources": [footage],
            "seed": 420,
            "ffmpeg": ffmpeg,
            "ffprobe": ffprobe,
            "output": {
                "path": tmp_path / "output.mp4",
                "resolution": [96, 64],
                "fps": 12,
                "encoder_preset": "ultrafast",
            },
            "clips": {"duration": [0.3, 0.5]},
        }
    )
