import json
import tempfile
import wave
from pathlib import Path
from typing import Annotated

import typer
import yaml
from rich.console import Console

from .scenes.catalog import CATALOG, describe, validate_params


def parameters(values):
    result = {}
    for item in values or []:
        name, equal, value = item.partition("=")
        if not equal:
            raise ValueError("Use --param name=value")
        result[name] = yaml.safe_load(value)
    return result


def demo_generator(
    kind,
    output,
    duration=10,
    resolution=(640, 360),
    seed=420,
    palette="deep_space",
    params=None,
    audio=None,
    start=0,
    source=None,
    quality="balanced",
    ffmpeg=None,
    ffprobe=None,
    overwrite=False,
    profile=False,
):
    from .config import load
    from .platform import executable, run
    from .render import render
    from .timeline import build

    validate_params(kind, params or {})
    if not 0.1 <= duration <= 600:
        raise ValueError("Demo duration must lie in [0.1, 600] seconds")
    if output.exists() and not overwrite:
        raise ValueError(f"Output already exists: {output}; use --overwrite")
    if any(path and path.resolve() == output.resolve() for path in (audio, source)):
        raise ValueError("Output cannot replace demo input")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="videobingus-scene-", dir=output.resolve().parent) as temporary:
        soundtrack = Path(temporary) / "excerpt.wav"
        if audio:
            run(
                [
                    executable("ffmpeg", ffmpeg),
                    "-v",
                    "error",
                    "-nostdin",
                    "-ss",
                    str(start),
                    "-i",
                    str(audio),
                    "-t",
                    str(duration),
                    "-vn",
                    "-c:a",
                    "pcm_s16le",
                    str(soundtrack),
                ]
            )
        else:
            with wave.open(str(soundtrack), "wb") as handle:
                handle.setparams((2, 2, 16000, 0, "NONE", "not compressed"))
                remaining = round(duration * 16000)
                while remaining:
                    count = min(remaining, 16000)
                    handle.writeframes(bytes(count * 4))
                    remaining -= count
        project = load(
            overrides={
                "audio": soundtrack,
                "sources": [source] if source else [],
                "seed": seed,
                "scenes": [{"id": "demo", "type": kind, "params": params or {}}],
                "palette": palette,
                "analysis": bool(audio),
                "composition": {"mode": "generative", "scene_duration": [duration, duration]},
                "performance": {"quality": quality},
                "ffmpeg": ffmpeg,
                "ffprobe": ffprobe,
                "output": {"path": output.resolve(), "resolution": resolution, "encoder_preset": "veryfast"},
            }
        )
        return render(build(project), output, overwrite, profile=profile)


def register_generators(app, guarded):
    group = typer.Typer(help="Procedural artwork: analytical scenes, simulations and autonomous feedback.")
    app.add_typer(group, name="generators")
    console = Console()

    @group.command("list")
    def list_generators(json_output: Annotated[bool, typer.Option("--json")] = False):
        if json_output:
            typer.echo(json.dumps([describe(kind) for kind in CATALOG], indent=2))
        else:
            for name, spec in CATALOG.items():
                console.print(f"{name} ({spec['category']}, {spec['cost']})\n  {spec['description']}")

    @group.command("info")
    @guarded
    def info(kind: str, json_output: Annotated[bool, typer.Option("--json")] = False):
        if kind not in CATALOG:
            raise ValueError(f"Unknown scene generator: {kind}")
        typer.echo(
            json.dumps(describe(kind), indent=2)
            if json_output
            else yaml.safe_dump(describe(kind), sort_keys=False)
        )

    @group.command("demo")
    @guarded
    def demo(
        kind: str,
        duration: float = 10,
        seed: int = 420,
        palette: str = "deep_space",
        resolution: str = "640x360",
        quality: str = "balanced",
        audio: Path | None = None,
        start: str = "0",
        source: Annotated[Path | None, typer.Option("--input")] = None,
        param: Annotated[list[str] | None, typer.Option("--param")] = None,
        output: Annotated[Path, typer.Option("-o", "--output")] = Path("generator-demo.mp4"),
        ffmpeg: str | None = None,
        ffprobe: str | None = None,
        overwrite: bool = False,
        profile: bool = False,
        randomize: bool = False,
    ):
        from .cue import seconds

        size = tuple(int(v) for v in resolution.lower().split("x"))
        chosen = parameters(param)
        if randomize:
            import numpy as np

            if kind not in CATALOG:
                raise ValueError(f"Unknown scene generator: {kind}")
            random = np.random.default_rng(seed)
            for name in CATALOG[kind]["modulatable"]:
                default, low, high = CATALOG[kind]["parameters"][name]
                spread = min((high - low) * 0.08, max(abs(default) * 0.2, 0.02))
                chosen.setdefault(name, float(np.clip(default + random.uniform(-spread, spread), low, high)))
        console.print(
            str(
                demo_generator(
                    kind,
                    output,
                    duration,
                    size,
                    seed,
                    palette,
                    chosen,
                    audio,
                    seconds(start),
                    source,
                    quality,
                    ffmpeg,
                    ffprobe,
                    overwrite,
                    profile,
                )
            )
        )
