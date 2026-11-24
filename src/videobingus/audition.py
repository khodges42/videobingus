import tempfile
import wave
from pathlib import Path

import numpy as np

from .config import load
from .effects.registry import PARAMETERS, validate_params
from .effects.synthesis_specs import MIXERS
from .platform import executable, run
from .render import render
from .timeline import build


def soundtrack(path, duration, rate=16000):
    with wave.open(str(path), "wb") as handle:
        handle.setparams((2, 2, rate, 0, "NONE", "not compressed"))
        for begin in range(0, round(duration * rate), rate):
            t = np.arange(begin, min(begin + rate, round(duration * rate))) / rate
            envelope = 0.15 + 0.65 * np.exp(-(t % 0.5) * 20)
            left = np.sin(2 * np.pi * 80 * t) * envelope * 0.2
            right = np.sin(2 * np.pi * 80 * t + 0.7 * np.sin(t)) * envelope * 0.2
            handle.writeframes((np.column_stack([left, right]) * 32767).astype("<i2").tobytes())


def demo(
    kind,
    input_path=None,
    second_input=None,
    duration=10,
    output=Path("demo.mp4"),
    params=None,
    resolution=(640, 360),
    fps=30,
    seed=420,
    ffmpeg=None,
    ffprobe=None,
    overwrite=False,
    profile=False,
    preset=None,
):
    if not preset and kind not in PARAMETERS:
        raise ValueError(f"Unknown effect: {kind}")
    if not 0.1 <= duration <= 120:
        raise ValueError("Demo duration must lie in [0.1, 120] seconds")
    if output.exists() and not overwrite:
        raise ValueError(f"Output already exists: {output}; use --overwrite")
    if not preset:
        validate_params(kind, params or {})
    output = output.resolve()
    for source in (input_path, second_input):
        if source and source.resolve() == output:
            raise ValueError("Output cannot replace demo source media")
    ffmpeg = executable("ffmpeg", ffmpeg)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="videobingus-demo-", dir=output.parent) as temporary:
        root = Path(temporary)
        audio = root / "stereo.wav"
        soundtrack(audio, duration)
        sources = []
        for index, source in enumerate((input_path, second_input)):
            if source:
                sources.append(source.resolve())
            else:
                target = root / f"pattern-{index}.mp4"
                run(
                    [
                        ffmpeg,
                        "-v",
                        "error",
                        "-f",
                        "lavfi",
                        "-i",
                        "testsrc2=s=640x360:r=30",
                        "-vf",
                        f"hue=h={index * 120}",
                        "-t",
                        str(duration),
                        "-c:v",
                        "libx264",
                        "-preset",
                        "ultrafast",
                        str(target),
                    ]
                )
                sources.append(target)
        configuration = {
            "audio": audio,
            "sources": sources,
            "seed": seed,
            "analysis": True,
            "ffmpeg": ffmpeg,
            "ffprobe": ffprobe,
            "output": {"path": output, "resolution": resolution, "fps": fps, "encoder_preset": "veryfast"},
            "clips": {
                "duration": [duration / 2, duration / 2],
                "random_start": False,
                "short_source": "loop",
            },
        }
        if preset:
            configuration["preset"] = preset
        elif kind in MIXERS:
            transition_duration = min(10, duration / 2)
            configuration["transitions"] = [
                {"type": kind, "duration": [transition_duration, transition_duration], "params": params or {}}
            ]
        else:
            configuration["effects"] = {"global": [{"id": "demo", "type": kind, **(params or {})}]}
        plan = build(load(overrides=configuration))
        # Keep A/B identity independent of shuffle order in comparison demonstrations.
        for index, clip in enumerate(plan["clips"]):
            clip["source"] = next(
                i for i, media in enumerate(plan["media"]) if Path(media["path"]) == sources[index % 2]
            )
        return render(plan, output, overwrite, profile=profile)
