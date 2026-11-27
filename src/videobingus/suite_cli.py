import json
import tempfile
from pathlib import Path
from typing import Annotated

import typer
import yaml
from rich.console import Console

from .scene_config import Selection
from .suites.compiler import (
    THEMES,
    compile_suite,
    export_project,
    load_suite,
    names,
    restrict,
)
from .timeline_random import rng


def contact_sheet(video, output, duration, ffmpeg=None, overwrite=False):
    from .platform import executable, run

    if output.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
        raise ValueError("Contact sheet must be PNG or JPEG")
    if output.exists() and not overwrite:
        raise ValueError(f"Contact sheet already exists: {output}; use --overwrite")
    output.parent.mkdir(parents=True, exist_ok=True)
    filter_graph = (
        f"fps={6 / duration},scale=320:180:force_original_aspect_ratio=decrease,"
        "pad=320:180:(ow-iw)/2:(oh-ih)/2,tile=3x2:nb_frames=6"
    )
    run(
        [
            executable("ffmpeg", ffmpeg),
            "-v",
            "error",
            "-nostdin",
            "-y" if overwrite else "-n",
            "-i",
            str(video),
            "-vf",
            filter_graph,
            "-frames:v",
            "1",
            str(output),
        ]
    )


def demo_suite(
    reference,
    output,
    duration=30,
    resolution=(640, 360),
    seed=420,
    audio=None,
    start=0,
    source=None,
    quality="draft",
    ffmpeg=None,
    ffprobe=None,
    overwrite=False,
    profile=False,
    sheet=None,
    showcase=False,
):
    from .audition import soundtrack
    from .config import load
    from .platform import executable, run
    from .render import render
    from .timeline import build

    if not 0.1 <= duration <= 600:
        raise ValueError("Suite demo duration must lie in [0.1, 600] seconds")
    if output.exists() and not overwrite:
        raise ValueError(f"Output already exists: {output}; use --overwrite")
    if any(p and p.resolve() == output.resolve() for p in (audio, source)):
        raise ValueError("Output cannot replace demo input")
    if sheet and sheet.exists() and not overwrite:
        raise ValueError(f"Contact sheet already exists: {sheet}; use --overwrite")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="videobingus-suite-", dir=output.resolve().parent) as temporary:
        track = Path(temporary) / "audio.wav"
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
                    str(track),
                ]
            )
        else:
            soundtrack(track, duration)
        project = load(
            overrides={
                "suite": reference,
                "audio": track,
                "sources": [source] if source else [],
                "seed": seed,
                "performance": {"quality": quality},
                "ffmpeg": ffmpeg,
                "ffprobe": ffprobe,
                "output": {"path": output.resolve(), "resolution": resolution, "encoder_preset": "veryfast"},
            }
        )
        if showcase:
            interval = max(0.5, duration / min(4, len(project.scenes)))
            project.composition.scene_duration = (interval, interval)
            project.composition.max_scene_changes_per_minute = min(120, 60 / interval)
            for scene in project.scenes:
                scene.minimum_scene_duration = 0
        plan = build(project)
        if showcase:
            # Cycle through compiled motifs while keeping each motif's sampled parameters and palette.
            scene_clips = [clip for clip in plan["clips"] if "scene" in clip]
            from .palettes import colors
            from .scenes.runtime import sampled_params, stable_seed

            for index, clip in enumerate(scene_clips):
                scene = project.scenes[index % len(project.scenes)]
                chosen_seed = stable_seed(seed, scene.id)
                clip["scene"] = {
                    "id": scene.id,
                    "type": scene.type,
                    "seed": chosen_seed,
                    "params": sampled_params(scene.type, scene.params, chosen_seed, quality),
                    "palette": colors(project.palette, project.palettes),
                    "retain_state": scene.retain_state,
                    "triggers": [trigger.model_dump() for trigger in scene.triggers],
                }
            from .scheduling import schedule_transitions

            schedule_transitions(plan, project)
        result = render(plan, output, overwrite, profile=profile)
        if sheet:
            contact_sheet(result, sheet, plan["duration"], ffmpeg, overwrite)
        return result


def register_suites(app, guarded):
    group = typer.Typer(help="Themed, constrained generators, processing chains and musical response.")
    app.add_typer(group, name="suites")
    console = Console()

    @group.command("list")
    def list_suites():
        for name in names():
            suite = load_suite(name)
            console.print(f"{name}\n  {suite.description}")

    @group.command("info")
    @guarded
    def info(name: str, json_output: Annotated[bool, typer.Option("--json")] = False):
        raw = load_suite(name).model_dump(mode="json")
        typer.echo(json.dumps(raw, indent=2) if json_output else yaml.safe_dump(raw, sort_keys=False))

    @group.command("demo")
    @guarded
    def demo(
        name: str,
        duration: float = 30,
        resolution: str = "640x360",
        seed: int = 420,
        audio: Path | None = None,
        start: str = "0",
        source: Annotated[Path | None, typer.Option("--input")] = None,
        quality: str = "draft",
        output: Annotated[Path, typer.Option("-o", "--output")] = Path("suite-demo.mp4"),
        contact_sheet: Path | None = None,
        showcase: bool = False,
        ffmpeg: str | None = None,
        ffprobe: str | None = None,
        overwrite: bool = False,
        profile: bool = False,
    ):
        from .cue import seconds

        size = tuple(int(v) for v in resolution.lower().split("x"))
        console.print(
            str(
                demo_suite(
                    name,
                    output,
                    duration,
                    size,
                    seed,
                    audio,
                    seconds(start),
                    source,
                    quality,
                    ffmpeg,
                    ffprobe,
                    overwrite,
                    profile,
                    contact_sheet,
                    showcase,
                )
            )
        )

    @group.command("compile")
    @guarded
    def compile_project(
        name: str,
        audio: Path,
        seed: int = 420,
        sources: Annotated[list[Path] | None, typer.Option("--source")] = None,
        output: Annotated[Path, typer.Option("-o", "--output")] = Path("project.yaml"),
        overwrite: bool = False,
    ):
        from .config import load

        project = load(
            overrides={
                "suite": name,
                "audio": audio.resolve(),
                "sources": [p.resolve() for p in sources or []],
                "seed": seed,
            }
        )
        export_project(project, output, overwrite)
        console.print(str(output))

    @group.command("generate")
    @guarded
    def generate(
        theme: str = "analog",
        generators: str | None = None,
        effects: str | None = None,
        audio_reactive: bool = False,
        palette_scheme: str | None = None,
        intensity: float = 0.6,
        seed: int = 42,
        variants: int = 1,
        output: Annotated[Path, typer.Option("-o", "--output")] = Path("my-suite.yaml"),
        output_dir: Path | None = None,
        audio: Path | None = None,
        overwrite: bool = False,
    ):
        if theme not in THEMES or not 1 <= variants <= 20:
            raise ValueError(f"Choose a theme from {list(THEMES)} and 1–20 variants")
        if variants > 1 and output_dir is None:
            raise ValueError("Multiple variants require --output-dir")
        selection = Selection(
            generators=[s.strip() for s in (generators or "").split(",") if s.strip()],
            effects=[s.strip() for s in (effects or "").split(",") if s.strip()],
            intensity=intensity,
        )
        destinations = [
            output_dir / f"{theme}-{index + 1:02d}.yaml" if output_dir else output
            for index in range(variants)
        ]
        if not overwrite and any(path.exists() for path in destinations):
            raise ValueError("A generated suite destination already exists; use --overwrite")
        for index, path in enumerate(destinations):
            random = rng(seed + index, "suite-recipe")
            suite = restrict(load_suite(THEMES[theme]), selection)
            suite.name = f"{theme}_{seed + index}"
            suite.audio_response.enabled = audio_reactive
            suite.identity.palette_family = [random.choice(suite.identity.palette_family)]
            if palette_scheme:
                from .palettes import generate_palette

                palette_name = f"generated_{seed + index}"
                suite.palettes[palette_name] = generate_palette(seed + index, palette_scheme)
                suite.identity.palette_family = [palette_name]
            for scene in suite.generators:
                scene.weight *= random.uniform(0.65, 1.35)
            if audio:
                from .config import load

                raw = compile_suite(suite, seed + index)
                raw["audio"] = audio.resolve()
                export_project(load(overrides=raw), path, overwrite)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("w" if overwrite else "x", encoding="utf-8") as handle:
                    yaml.safe_dump(suite.model_dump(mode="json"), handle, sort_keys=False, allow_unicode=True)
            console.print(str(path))
