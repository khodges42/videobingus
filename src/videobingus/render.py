import math
import subprocess
import tempfile
import time
from fractions import Fraction
from pathlib import Path

import numpy as np
from rich.progress import (
    BarColumn,
    Progress,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)

from .audio import Modulator, StereoReader, at
from .compositing import Layers
from .config import Project
from .effects.engine import Context, EffectEngine, State, pixels
from .effects.mixers import mix
from .effects.registry import PARAMETERS, validate_params
from .effects.synthesis_specs import MIXERS
from .media import inspect, probe
from .platform import executable, process
from .signals import SignalBank
from .sources import SourceTimeline
from .titles import TitleRenderer


def render(
    plan: dict,
    output: Path | None = None,
    overwrite=False,
    start=0.0,
    duration=None,
    resolution=None,
    exact_history=False,
    warmup_seconds=3,
    profile=False,
):
    project = Project.model_validate(plan["config"])
    if "transitions" not in plan:
        from .scheduling import schedule_transitions

        plan = dict(plan)
        schedule_transitions(plan, project, reserve=False)
    if resolution:
        project.output = type(project.output).model_validate(
            {**project.output.model_dump(), "resolution": resolution}
        )
    target = (output or project.output.path).resolve()
    if target.suffix.lower() != ".mp4":
        raise ValueError("Output must use the .mp4 container")
    if target.exists() and not overwrite:
        raise ValueError(f"Output already exists: {target}. Use --overwrite to replace it.")
    paths = [project.audio, *(Path(m["path"]) for m in plan["media"])]
    paths.extend(
        Path(o["asset"]["path"]) for o in plan["overlays"] if not o["asset"]["path"].startswith("generator:")
    )
    for path in paths:
        if not path.is_file():
            raise ValueError(f"Plan source missing: {path}. Use --media-root to remap relative references.")
        if path.resolve() == target:
            raise ValueError("Output cannot replace source media")
    fps = Fraction(str(project.output.fps))
    cursor = 0
    for clip in plan["clips"]:
        if clip["start"] != cursor or clip["end"] <= cursor:
            raise ValueError("Render plan has a gap, overlap, or invalid clip interval")
        if clip["source"] is None and "scene" not in clip:
            raise ValueError("A clip without footage requires a scene")
        if clip["source"] is not None and not 0 <= clip["source"] < len(plan["media"]):
            raise ValueError("Render plan has an invalid media reference")
        if clip["offset"] < 0 or clip["speed"] <= 0:
            raise ValueError("Render plan has invalid source timing")
        cursor = clip["end"]
    if cursor != plan["frames"]:
        raise ValueError("Render plan clips do not cover the output timeline")
    previous_end = 0
    for transition in plan["transitions"]:
        incoming = transition["incoming"]
        if (
            not isinstance(incoming, int)
            or not 1 <= incoming < len(plan["clips"])
            or transition["outgoing"] != incoming - 1
        ):
            raise ValueError("Render plan has an invalid transition source reference")
        clip = plan["clips"][incoming]
        if (
            transition["start"] != clip["start"]
            or transition["start"] < previous_end
            or not transition["start"] < transition["end"] <= clip["end"]
        ):
            raise ValueError("Render plan has an invalid or overlapping transition interval")
        if transition["type"] not in MIXERS or not 0 <= transition["intensity"] <= 1:
            raise ValueError("Render plan has an invalid transition mixer or intensity")
        validate_params(transition["type"], transition["params"])
        previous_end = transition["end"]
    for effect in plan["effects"]:
        if not 0 <= effect["start"] < effect["end"] <= plan["frames"]:
            raise ValueError("Render plan has an invalid effect interval")
        validate_params(effect["type"], effect["params"])
        if any(isinstance(effect["params"].get(key), (list, tuple)) for key in PARAMETERS[effect["type"]]):
            raise ValueError("Render-plan effect parameters must already be sampled numbers")
    for media in plan["media"]:
        inspect(Path(media["path"]), project.ffprobe)
    begin = round(start * fps)
    end = min(plan["frames"], begin + math.ceil(duration * fps)) if duration else plan["frames"]
    if begin < 0 or begin >= end:
        raise ValueError("Preview interval lies outside the composition")
    ffmpeg = executable("ffmpeg", project.ffmpeg)
    info = probe(project.audio, project.ffprobe)
    if abs(float(info["format"]["duration"]) - plan["duration"]) > 1 / float(fps):
        raise ValueError("Soundtrack duration changed since planning; create a new plan")
    audio_codec = next(s["codec_name"] for s in info["streams"] if s["codec_type"] == "audio")
    width, height = project.output.resolution
    effects = EffectEngine(plan["effects"], float(fps), plan["seed"], profile)
    modulation = Modulator(project.modulation, float(fps), project.signals)
    bank = SignalBank(project.signals, plan["seed"], float(fps))
    titles = TitleRenderer(project.titles, project.output.resolution)
    features = {
        key: np.asarray(value, dtype=np.float64 if key == "times" else np.float32)
        for key, value in plan.get("audio_features", {}).items()
    }
    warmup = 0 if exact_history else max(0, begin - round(warmup_seconds * fps))
    transition_cursor = 0
    transition_intervals = plan.get("transitions", [])

    def controls(index):
        nonlocal transition_cursor
        audio = at(features, float(index / fps))
        track = next((t for t in reversed(plan["tracks"]) if round(t["time"] * fps) <= index), None)
        track_time = float(index / fps) - (track["time"] if track else 0)
        next_track = next((t["time"] for t in plan["tracks"] if t["time"] > index / fps), plan["duration"])
        audio["track_progress"] = float(
            np.clip(track_time / max(0.1, next_track - (track["time"] if track else 0)), 0, 1)
        )
        while (
            transition_cursor < len(transition_intervals)
            and transition_intervals[transition_cursor]["end"] <= index
        ):
            transition_cursor += 1
        transition = (
            transition_intervals[transition_cursor] if transition_cursor < len(transition_intervals) else None
        )
        if transition and index < transition["start"]:
            transition = None
        progress = (
            (
                1
                if transition["end"] - transition["start"] == 1
                else (index - transition["start"]) / (transition["end"] - transition["start"] - 1)
            )
            if transition
            else 0
        )
        signals = bank.evaluate(index, audio, track_time, progress)
        return audio, track, track_time, progress, modulation.values_at(signals), signals

    for index in range(warmup):
        controls(index)
    previous_inputs = {}
    stereo_required = (
        any(e.type == "oscilloscope_xy" for e in project.effects.all())
        or any(g.type == "oscilloscope_xy" for g in project.generators)
        or any(o.source == "generator:oscilloscope_xy" for o in project.overlays)
    )
    transition_state, transition_start = State(), None
    started = time.monotonic()
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="videobingus-", dir=target.parent) as temporary:
        staging = Path(temporary) / "render.mp4"
        args = [
            ffmpeg,
            "-v",
            "error",
            "-nostdin",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            f"{width}x{height}",
            "-r",
            str(fps),
            "-i",
            "pipe:0",
            "-ss",
            str(float(begin / fps)),
            "-i",
            str(project.audio),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "libx264",
            "-preset",
            project.output.encoder_preset,
            "-crf",
            str(project.output.crf),
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "copy" if audio_codec in {"aac", "mp3", "alac"} else "aac",
        ]
        if audio_codec not in {"aac", "mp3", "alac"}:
            args += ["-b:a", "320k"]
        args += [
            "-t",
            str(min(float((end - begin) / fps), plan["duration"] - float(begin / fps))),
            "-movflags",
            "+faststart",
            str(staging),
        ]
        with Progress(
            TextColumn("{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
        ) as progress:
            task = progress.add_task("Rendering", total=end - begin)
            with (
                process(args, stdin=subprocess.PIPE) as encoder,
                Layers(
                    plan["overlays"],
                    ffmpeg,
                    project.output,
                    effects,
                    layer_order=[o.id for o in project.overlays],
                ) as layers,
                effects,
                SourceTimeline(plan, ffmpeg, project.output, features) as sources,
                StereoReader(project.audio, ffmpeg, fps, warmup, stereo_required) as stereo,
            ):
                for index in range(warmup, end):
                    audio, track, track_time, transition_progress, values, signals = controls(index)
                    audio["stereo"] = stereo.at(index)
                    random = np.random.default_rng(np.random.SeedSequence([plan["seed"], index]))
                    context = Context(index, float(fps), 0, track, audio, random)
                    context.seed = plan["seed"]
                    context.performance = project.performance.model_dump()
                    context.palette = project.palette
                    context.signals = signals
                    context.audio_profiles = project.audio_profiles
                    context.scene_modulation = modulation.scene_values
                    context.visual_intensity = project.master_intensity * (
                        audio.get("visual_intensity", 1) if project.composition.dynamics else 1
                    )
                    context.preserve_palette = bool(
                        project.randomization and project.randomization.preserve_palette
                    )
                    clip, frame, outgoing, transition = sources.at(index, context)
                    context.clip_time = (index - clip["start"]) / float(fps)
                    context.clip_id = clip["start"]
                    if "scene" in clip:
                        context.palette = clip["scene"]["palette"]
                    context.track_time = track_time
                    context.transition_progress = transition_progress
                    context.previous_inputs = previous_inputs
                    context.raw_frame = frame
                    context.inputs["primary"] = frame
                    if transition:
                        if transition["start"] != transition_start:
                            transition_state, transition_start = State(), transition["start"]
                        mixed = mix(
                            transition["type"],
                            outgoing,
                            frame,
                            transition["params"],
                            context,
                            transition_state,
                            transition_progress,
                        )
                        linear = outgoing * (1 - transition_progress) + frame * transition_progress
                        strength = transition["intensity"]
                        frame = pixels(linear * (1 - strength) + mixed.astype(np.float32) * strength)
                    effect_values, opacity = values
                    frame = effects.process(frame, context, "primary", effect_values)
                    context.inputs["primary"] = frame
                    frame = layers.composite(frame, context, effect_values, opacity)
                    frame = effects.process(frame, context, "composite", effect_values)
                    context.inputs["composite"] = frame
                    previous_inputs = {name: image.copy() for name, image in context.inputs.items()}
                    frame = titles.apply(frame, float(index / fps), track)
                    if index >= begin:
                        encoder.stdin.write(frame.tobytes())
                        elapsed = max(0.001, time.monotonic() - started)
                        speed = (index - begin + 1) / elapsed
                        progress.update(
                            task, advance=1, description=f"{float(index / fps):.1f}s · {speed:.1f} fps"
                        )
        if target.exists() and not overwrite:
            raise ValueError(f"Output was created during rendering: {target}")
        staging.replace(target)
    if profile:
        from rich.console import Console

        console = Console()
        for identity, (seconds, calls) in sorted(effects.timings.items(), key=lambda item: -item[1][0]):
            console.print(
                f"{identity}: {seconds:.3f}s, {calls} frames, {seconds * 1000 / max(1, calls):.2f} ms/frame"
            )
        for kind, (seconds, calls) in sources.scene_store.timings.items():
            console.print(
                f"generator {kind}: {seconds:.3f}s, {calls} frames, "
                f"{seconds * 1000 / max(1, calls):.2f} ms/frame"
            )
    return target
