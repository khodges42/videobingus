import importlib.util
import platform
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from .config import load
from .platform import executable, run
from .scene_cli import register_generators
from .suite_cli import register_suites
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


@effects_app.command("info")
def effects_info(effect: str, json_output: Annotated[bool, typer.Option("--json")] = False):
    import json

    import yaml

    from .effects.catalog import describe
    from .effects.registry import PARAMETERS

    if effect not in PARAMETERS:
        raise typer.BadParameter(f"Unknown effect: {effect}")
    metadata = describe(effect)
    typer.echo(json.dumps(metadata, indent=2) if json_output else yaml.safe_dump(metadata, sort_keys=False))


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
    fit=None,
    generators=None,
    quality=None,
    suite=None,
    effects=None,
    randomize=False,
    include_effect=None,
    exclude_effect=None,
    intensity=None,
):
    overrides = {}
    import yaml

    configured = yaml.safe_load(config.read_text(encoding="utf-8-sig")) if config else {}
    configured_suite = isinstance(configured, dict) and bool(configured.get("suite"))
    suite_mode = bool(suite or randomize or configured_suite)
    random_seed = seed is not None and str(seed).lower() == "random"
    if seed is not None:
        seed = None if str(seed).lower() == "random" else int(seed)
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
    if random_seed:
        overrides["seed"] = None
    if suite:
        candidate = Path(suite)
        overrides["suite"] = str(candidate.resolve()) if candidate.is_file() else suite
    if suite_mode:
        overrides["selection"] = {
            "randomize": randomize,
            "generators": [s.strip() for s in (generators or "").split(",") if s.strip()],
            "effects": [s.strip() for s in (effects or "").split(",") if s.strip()],
            "include_effect": include_effect or [],
            "exclude_effect": exclude_effect or [],
            "intensity": intensity,
        }
    elif generators:
        overrides["scenes"] = [{"type": name.strip()} for name in generators.split(",") if name.strip()]
    if effects and not suite_mode:
        from .effects.synthesis_specs import MIXERS

        chosen = [s.strip() for s in effects.split(",") if s.strip()]
        overrides["effects"] = {
            "global": [{"id": f"manual_{name}", "type": name} for name in chosen if name not in MIXERS]
        }
        overrides["transitions"] = [{"type": name} for name in chosen if name in MIXERS]
    if intensity is not None and not suite_mode:
        overrides["master_intensity"] = intensity
    if quality:
        overrides["performance"] = {"quality": quality}
    if fit:
        settings["fit"] = fit
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
    if not suite_mode and (include_effect or exclude_effect):
        from .config import Effect, Transition
        from .effects.registry import PARAMETERS
        from .effects.synthesis_specs import MIXERS

        excluded = set(exclude_effect or [])
        unknown = set(include_effect or []) | excluded
        if unknown - PARAMETERS.keys():
            raise ValueError(f"Unknown effects: {sorted(unknown - PARAMETERS.keys())}")
        for group in (
            project.effects.global_,
            project.effects.per_clip,
            project.effects.per_track,
            project.effects.events,
            project.effects.transitions,
        ):
            group[:] = [e for e in group if e.type not in excluded]
        project.transitions[:] = [t for t in project.transitions if t.type not in excluded]
        for name in include_effect or []:
            if name not in excluded:
                if name in MIXERS:
                    project.transitions.append(Transition(type=name))
                else:
                    project.effects.global_.append(Effect(id=f"included_{name}", type=name))
        project = type(project).model_validate(project.model_dump(by_alias=True))
    if sources:
        for track in project.tracks:
            track.sources = None
    if min_clip is not None or max_clip is not None:
        if project.scenes:
            low = min_clip if min_clip is not None else min(project.composition.scene_duration[0], max_clip)
            high = max_clip if max_clip is not None else max(project.composition.scene_duration[1], min_clip)
            project.composition.scene_duration = (low, high)
            project.composition.max_scene_changes_per_minute = min(
                120, max(project.composition.max_scene_changes_per_minute, 60 / max(0.1, low))
            )
            for scene in project.scenes:
                scene.minimum_scene_duration = min(scene.minimum_scene_duration, high)
            for track in project.tracks:
                track.clips.pop("duration", None)
        else:
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
        project = type(project).model_validate(project.model_dump(by_alias=True))
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
    seed: str | None = None,
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
    fit: str | None = None,
    generators: str | None = None,
    quality: str | None = None,
    suite: str | None = None,
    effects: str | None = None,
    randomize: bool = False,
    include_effect: Annotated[list[str] | None, typer.Option("--include-effect")] = None,
    exclude_effect: Annotated[list[str] | None, typer.Option("--exclude-effect")] = None,
    intensity: float | None = None,
):
    """Render an audio recording with footage, generative scenes, or a suite."""
    from .render import render as render_video

    if plan:
        if randomize or include_effect or exclude_effect or intensity is not None:
            raise ValueError("Suite and selection overrides require a new composition, not --plan")
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
                fit,
                generators,
                quality,
                suite,
                effects,
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
            fit,
            generators,
            quality,
            suite,
            effects,
            randomize,
            include_effect,
            exclude_effect,
            intensity,
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


register_generators(app, guarded)
register_suites(app, guarded)

if __name__ == "__main__":
    app()
