import importlib.util
import platform
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from .config import load
from .platform import executable, run
from .timeline import build, read, save

app = typer.Typer(no_args_is_help=True, help="Procedural visuals for DJ mixes. All rendering is offline.")
console = Console()
effects_app = typer.Typer(help="Implemented effects and validated parameter ranges.")
presets_app = typer.Typer(help="Editable YAML presets shipped with the package.")
app.add_typer(effects_app, name="effects")
app.add_typer(presets_app, name="presets")


@effects_app.command("list")
def effects_list(effect: Annotated[str | None, typer.Argument()] = None):
    from .effects.registry import OPTIONS, PARAMETERS, STRUCTURED

    if effect and effect not in PARAMETERS:
        raise typer.BadParameter(f"Unknown effect: {effect}")

    for name, parameters in PARAMETERS.items():
        if effect and effect != name:
            continue
        console.print(name, style="bold")
        for parameter, (default, minimum, maximum) in parameters.items():
            console.print(f"  {parameter}: {default} [{minimum}, {maximum}]", markup=False)
        for parameter, (default, choices) in OPTIONS.get(name, {}).items():
            console.print(f"  {parameter}: {default}; choices: {', '.join(choices)}", markup=False)
        for parameter, default in STRUCTURED.get(name, {}).items():
            console.print(f"  {parameter}: {default}", markup=False)
    console.print("datamosh simulates frame persistence; it does not modify compressed bitstreams.")


@presets_app.command("list")
def presets_list():
    from importlib.resources import files

    for path in sorted(files("videobingus.presets").iterdir(), key=lambda p: p.name):
        if path.name.endswith(".yaml"):
            console.print(path.stem)


def guarded(function):
    from functools import wraps

    @wraps(function)
    def wrapped(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except KeyboardInterrupt:
            console.print("[yellow]Cancelled.[/yellow]")
            raise typer.Exit(130) from None
        except (ValueError, OSError, KeyError) as error:
            console.print(f"Error: {error}", markup=False)
            raise typer.Exit(1) from None

    return wrapped


def composition(
    config,
    audio=None,
    sources=None,
    preset=None,
    seed=None,
    output=None,
    min_clip=None,
    max_clip=None,
    resolution=None,
    fps=None,
    cue=None,
    crf=None,
    encoder_preset=None,
    ffmpeg=None,
    ffprobe=None,
):
    overrides = {}
    for name, value in (
        ("audio", audio),
        ("sources", sources),
        ("preset", preset),
        ("seed", seed),
        ("cue", cue),
        ("ffmpeg", ffmpeg),
        ("ffprobe", ffprobe),
    ):
        if value is not None and value != []:
            if name == "sources":
                value = [p.resolve() for p in value]
            elif name in {"audio", "cue"}:
                value = value.resolve()
            overrides[name] = value
    settings = {}
    for name, value in (("path", output), ("fps", fps), ("crf", crf), ("encoder_preset", encoder_preset)):
        if value is not None:
            settings[name] = value
    if resolution:
        settings["resolution"] = tuple(int(n) for n in resolution.lower().split("x"))
    if settings:
        if output:
            settings["path"] = output.resolve()
        overrides["output"] = settings
    project = load(config, overrides)
    if sources:
        for track in project.tracks:
            track.sources = None
    if min_clip is not None or max_clip is not None:
        project.clips.duration = (
            min_clip if min_clip is not None else project.clips.duration[0],
            max_clip if max_clip is not None else project.clips.duration[1],
        )
        for track in project.tracks:
            duration = list(track.clips.get("duration", project.clips.duration))
            if min_clip is not None:
                duration[0] = min_clip
            if max_clip is not None:
                duration[1] = max_clip
            track.clips["duration"] = duration
        project = type(project).model_validate(project.model_dump())
    result = build(project)
    console.print(f"Seed: {result['seed']} · {len(result['clips'])} clips")
    return result


@app.command()
@guarded
def render(
    audio: Annotated[Path | None, typer.Argument()] = None,
    sources: Annotated[list[Path] | None, typer.Argument()] = None,
    config: Annotated[Path | None, typer.Option("--config")] = None,
    plan: Annotated[Path | None, typer.Option("--plan")] = None,
    output: Annotated[Path | None, typer.Option("-o", "--output")] = None,
    preset: str | None = None,
    seed: int | None = None,
    cue: Path | None = None,
    min_clip: float | None = None,
    max_clip: float | None = None,
    resolution: str | None = None,
    fps: str | None = None,
    crf: int | None = None,
    encoder_preset: str | None = None,
    media_root: Path | None = None,
    ffmpeg: str | None = None,
    ffprobe: str | None = None,
    overwrite: bool = False,
    profile: bool = False,
):
    """Render an audio recording with one or more footage paths."""
    from .render import render as render_video

    if plan:
        if any(
            v is not None
            for v in (
                config,
                audio,
                sources,
                preset,
                seed,
                cue,
                min_clip,
                max_clip,
                resolution,
                fps,
                crf,
                encoder_preset,
            )
        ):
            raise ValueError("--plan accepts only output, media-root, and overwrite options")
        result = read(plan, media_root, ffmpeg, ffprobe)
    else:
        result = composition(
            config,
            audio,
            sources,
            preset,
            seed,
            output,
            min_clip,
            max_clip,
            resolution,
            fps,
            cue,
            crf,
            encoder_preset,
            ffmpeg,
            ffprobe,
        )
    console.print(str(render_video(result, output, overwrite, profile=profile)))


@app.command()
@guarded
def plan(
    config: Annotated[Path, typer.Option("--config")],
    output: Annotated[Path, typer.Option("-o", "--output")] = Path("plan.json"),
    overwrite: bool = False,
):
    """Export seeded composition decisions to JSON."""
    save(composition(config), output, overwrite)
    console.print(str(output))


def timestamp(value: str) -> float:
    from .cue import seconds

    return seconds(value)


@app.command()
@guarded
def preview(
    config: Path | None = None,
    plan: Path | None = None,
    start: str = "0",
    duration: float = 30,
    output: Annotated[Path, typer.Option("-o", "--output")] = Path("preview.mp4"),
    resolution: str = "640x360",
    overwrite: bool = False,
    media_root: Path | None = None,
    ffmpeg: str | None = None,
    ffprobe: str | None = None,
    exact_history: bool = False,
    warmup: float = 3,
    profile: bool = False,
):
    """Render a low-resolution interval from the same full composition."""
    from .render import render as render_video

    if bool(config) == bool(plan):
        raise ValueError("Supply exactly one of --config or --plan")
    if duration <= 0:
        raise ValueError("duration must be positive")
    size = tuple(int(n) for n in resolution.split("x"))
    result = (
        read(plan, media_root, ffmpeg, ffprobe)
        if plan
        else composition(config, ffmpeg=ffmpeg, ffprobe=ffprobe)
    )
    if warmup < 0:
        raise ValueError("warmup must be nonnegative")
    console.print(
        str(
            render_video(
                result, output, overwrite, timestamp(start), duration, size, exact_history, warmup, profile
            )
        )
    )


@app.command()
@guarded
def validate(config: Path):
    """Validate YAML and inspect the project's source media."""
    composition(config)
    console.print("Project is valid.")


@app.command()
@guarded
def doctor(config: Path | None = None):
    """Report dependencies, FFmpeg versions, and available video encoders."""
    project = load(config) if config else None
    console.print(f"{platform.platform()}\nPython {sys.version.split()[0]}")
    problems = []
    for name in ("numpy", "cv2", "scipy", "typer", "rich", "pydantic", "yaml", "PIL"):
        available = importlib.util.find_spec(name) is not None
        console.print(f"{name}: {'OK' if available else 'MISSING'}")
        if not available:
            problems.append(name)
    for name in ("ffmpeg", "ffprobe"):
        try:
            path = executable(name, getattr(project, name) if project else None)
            console.print(f"{path}\n{run([path, '-version']).splitlines()[0]}")
            if name == "ffmpeg":
                encoders = run([path, "-hide_banner", "-encoders"])
                console.print(
                    "\n".join(line for line in encoders.splitlines() if line.lstrip().startswith("V"))
                )
                if "libx264" not in encoders:
                    problems.append("libx264 encoder")
        except ValueError as error:
            problems.append(str(error))
    if problems:
        raise ValueError("; ".join(problems))


@effects_app.command("demo")
@guarded
def effects_demo(
    effect: Annotated[str, typer.Argument()],
    input_path: Annotated[Path | None, typer.Option("--input")] = None,
    second_input: Path | None = None,
    duration: float = 10,
    output: Annotated[Path, typer.Option("-o", "--output")] = Path("demo.mp4"),
    param: Annotated[list[str] | None, typer.Option("--param")] = None,
    resolution: str = "640x360",
    fps: int = 30,
    seed: int = 420,
    ffmpeg: str | None = None,
    ffprobe: str | None = None,
    overwrite: bool = False,
    profile: bool = False,
):
    """Audition an effect or A/B mixer with footage or synthetic patterns and test stereo audio."""
    import yaml

    from .audition import demo

    parameters = {}
    for item in param or []:
        name, separator, value = item.partition("=")
        if not separator:
            raise ValueError("Use --param name=value")
        parameters[name] = yaml.safe_load(value)
    size = tuple(int(v) for v in resolution.lower().split("x"))
    console.print(
        str(
            demo(
                effect,
                input_path,
                second_input,
                duration,
                output,
                parameters,
                size,
                fps,
                seed,
                ffmpeg,
                ffprobe,
                overwrite,
                profile,
            )
        )
    )


@presets_app.command("demo")
@guarded
def presets_demo(
    preset: Annotated[str, typer.Argument()],
    input_path: Annotated[Path | None, typer.Option("--input")] = None,
    second_input: Path | None = None,
    duration: float = 10,
    output: Annotated[Path, typer.Option("-o", "--output")] = Path("preset-demo.mp4"),
    resolution: str = "640x360",
    fps: int = 30,
    seed: int = 420,
    ffmpeg: str | None = None,
    ffprobe: str | None = None,
    overwrite: bool = False,
    profile: bool = False,
):
    """Audition a preset using two footage sources or standardized moving test patterns."""
    from .audition import demo

    size = tuple(int(v) for v in resolution.lower().split("x"))
    console.print(
        str(
            demo(
                "preset",
                input_path,
                second_input,
                duration,
                output,
                resolution=size,
                fps=fps,
                seed=seed,
                ffmpeg=ffmpeg,
                ffprobe=ffprobe,
                overwrite=overwrite,
                profile=profile,
                preset=preset,
            )
        )
    )


if __name__ == "__main__":
    app()
