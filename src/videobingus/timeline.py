import json
import math
import os
import secrets
from fractions import Fraction
from pathlib import Path

from .config import Project
from .media import discover, probe
from .timeline_random import rng


def build(project: Project) -> dict:
    info = probe(project.audio, project.ffprobe)
    if not any(s["codec_type"] == "audio" for s in info["streams"]):
        raise ValueError("The soundtrack contains no audio stream")
    duration = float(info["format"]["duration"])
    media = discover(project.sources, project.ffprobe)
    primary_pool = list(range(len(media)))
    seed = project.seed if project.seed is not None else secrets.randbits(63)
    project = project.model_copy(deep=True)
    project.seed = seed
    fps = Fraction(str(project.output.fps))
    total = math.ceil(Fraction(str(duration)) * fps)
    from .audio import analyze
    from .cue import parse

    tracks = parse(project.cue, duration) if project.cue else []
    features = analyze(project.audio, project.ffmpeg) if project.analysis else {}
    from .signals import needs_audio

    if not project.analysis and (
        needs_audio(project.signals, [m.source for m in project.modulation] + list(project.signals))
        or any(e.trigger in {"bass_onset", "onset", "energy"} for e in project.effects.events)
    ):
        raise ValueError("Audio modulation and audio triggers require analysis: true")
    track_sources = {}
    from .config import Clips, merge

    for override in project.tracks:
        if override.index not in {t["index"] for t in tracks}:
            raise ValueError(f"Track override refers to absent track {override.index}")
        if override.sources:
            found = discover(override.sources, project.ffprobe)
            indices = []
            for item in found:
                if item not in media:
                    media.append(item)
                indices.append(media.index(item))
            track_sources[override.index] = indices
    boundary_frames = sorted({round(t["time"] * fps) for t in tracks if t["time"] > 0})
    randomizer = rng(seed, "clips")
    clips, bag = [], []
    cursor, previous = 0, None
    while cursor < total:
        current_track = next((t for t in reversed(tracks) if round(t["time"] * fps) <= cursor), None)
        track_index = current_track["index"] if current_track else None
        settings = project.clips
        for override in project.tracks:
            if override.index == track_index:
                settings = Clips.model_validate(merge(settings.model_dump(), override.clips))
        candidates = track_sources.get(track_index, primary_pool)[:]
        if len(candidates) > 1 and not settings.allow_consecutive_source and previous in candidates:
            candidates.remove(previous)
        if settings.selection == "shuffle":
            available = [i for i in bag if i in candidates]
            if not available:
                bag = candidates[:]
                randomizer.shuffle(bag)
                available = bag
            index = available[-1]
            bag.remove(index)
        else:
            index = randomizer.choice(candidates)
        source = media[index]
        speed = randomizer.uniform(*settings.speed)
        count = max(1, round(randomizer.uniform(*settings.duration) * fps))
        freeze = randomizer.random() < settings.freeze_probability
        if settings.short_source == "shorten" and not freeze:
            count = min(count, max(1, math.floor(source["duration"] / speed * fps)))
        count = min(count, total - cursor)
        if project.track_changes.cut_clip:
            next_boundary = next((b for b in boundary_frames if b > cursor), total)
            count = min(count, next_boundary - cursor)
        needed = count / float(fps) * speed if not freeze else 1 / float(fps)
        start = randomizer.uniform(0, max(0, source["duration"] - needed)) if settings.random_start else 0
        clips.append(
            {
                "start": cursor,
                "end": cursor + count,
                "source": index,
                "offset": start,
                "speed": speed,
                "reverse": randomizer.random() < settings.reverse_probability,
                "freeze": freeze,
                "crossfade": settings.crossfade,
            }
        )
        previous, cursor = index, cursor + count
    generator_random = rng(seed, "generators")
    for clip in clips:
        for generator in project.generators:
            if generator_random.random() < generator.probability:
                from .scheduling import sample

                clip["generator"] = generator.type
                clip["generator_params"] = generator.params
                length = max(1, round(sample(generator.duration, generator_random) * fps))
                clip["generator_end"] = min(clip["end"], clip["start"] + length)
                break
    result = {
        "schema_version": 1,
        "seed": seed,
        "config": project.model_dump(mode="json", by_alias=True),
        "media": media,
        "duration": duration,
        "frames": total,
        "clips": clips,
        "tracks": tracks,
        "effects": [],
        "overlays": [],
        "audio_features": features,
    }
    from .scheduling import schedule, schedule_transitions

    schedule_transitions(result, project)
    schedule(result, project)
    return result


def save(plan: dict, path: Path, overwrite=False):
    data = json.loads(json.dumps(plan))
    base = path.resolve().parent

    def relative(value):
        try:
            return Path(os.path.relpath(value, base)).as_posix()
        except ValueError:
            raise ValueError(
                "Plan media and destination must be on the same drive for portable paths"
            ) from None

    config = data["config"]
    config["audio"] = relative(config["audio"])
    config["sources"] = [relative(p) for p in config["sources"]]
    config["output"]["path"] = relative(config["output"]["path"])
    if config["cue"]:
        config["cue"] = relative(config["cue"])
    if config["titles"]["font"]:
        config["titles"]["font"] = relative(config["titles"]["font"])
    config["ffmpeg"] = None
    config["ffprobe"] = None
    for track in config["tracks"]:
        if track["sources"]:
            track["sources"] = [relative(p) for p in track["sources"]]
    for overlay in config["overlays"]:
        if not overlay["source"].startswith("generator:"):
            overlay["source"] = relative(overlay["source"])
    for overlay in data["overlays"]:
        if not overlay["source"].startswith("generator:"):
            overlay["source"] = relative(overlay["source"])
            overlay["asset"]["path"] = relative(overlay["asset"]["path"])
    for item in data["media"]:
        item["path"] = relative(item["path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w" if overwrite else "x", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)


def read(path: Path, media_root: Path | None = None, ffmpeg=None, ffprobe=None) -> dict:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if data.get("schema_version") != 1:
        raise ValueError("Unsupported render-plan schema")
    base = (media_root or path.resolve().parent).resolve()

    def absolute(value):
        return str((base / Path(value.replace("\\", "/"))).resolve())

    config = data["config"]
    if ffmpeg:
        config["ffmpeg"] = ffmpeg
    if ffprobe:
        config["ffprobe"] = ffprobe
    config["audio"] = absolute(config["audio"])
    config["sources"] = [absolute(p) for p in config["sources"]]
    config["output"]["path"] = absolute(config["output"]["path"])
    if config["cue"]:
        config["cue"] = absolute(config["cue"])
    if config["titles"]["font"]:
        config["titles"]["font"] = absolute(config["titles"]["font"])
    for track in config["tracks"]:
        if track["sources"]:
            track["sources"] = [absolute(p) for p in track["sources"]]
    for overlay in config["overlays"]:
        if not overlay["source"].startswith("generator:"):
            overlay["source"] = absolute(overlay["source"])
    for overlay in data["overlays"]:
        if not overlay["source"].startswith("generator:"):
            overlay["source"] = absolute(overlay["source"])
            overlay["asset"]["path"] = absolute(overlay["asset"]["path"])
    for item in data["media"]:
        item["path"] = absolute(item["path"])
    Project.model_validate(config)
    return data
