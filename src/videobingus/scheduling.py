import math
from fractions import Fraction
from pathlib import Path

from .audio import events
from .effects.registry import PARAMETERS, defaults
from .media import discover
from .timeline_random import rng


def sample(value, random):
    return random.uniform(*value) if isinstance(value, (tuple, list)) else value


def random_intervals(random, total, fps, probability, duration, cooldown=0):
    if probability <= 0:
        return
    cursor = 0.0
    while cursor < total:
        cursor += random.expovariate(-math.log1p(-min(probability, 1 - 1e-9))) * fps
        begin = round(cursor)
        if begin >= total:
            return
        end = min(total, begin + max(1, round(sample(duration, random) * fps)))
        yield begin, end
        cursor = end + cooldown * fps


def schedule(plan, project):
    fps = float(Fraction(str(project.output.fps)))
    total = plan["frames"]
    schedule_overlays(plan, project, fps, total)
    tracks = plan["tracks"]
    track_intervals = []
    boundaries = sorted({0, *(round(t["time"] * fps) for t in tracks), total})
    for begin, end in zip(boundaries, boundaries[1:]):
        track_intervals.append((begin, end))
    activations = []
    audio_events = {}
    for mode, effects in (
        ("global", project.effects.global_),
        ("per_clip", project.effects.per_clip),
        ("per_track", project.effects.per_track),
        ("events", project.effects.events),
        ("transitions", project.effects.transitions),
    ):
        for effect in effects:
            random = rng(plan["seed"], f"effect:{effect.id}")
            if mode == "global":
                intervals = [(0, total)]
            elif mode == "per_clip":
                clips = (
                    plan["clips"]
                    if effect.layer in {"primary", "composite"}
                    else [o for o in plan["overlays"] if o["id"] == effect.layer]
                )
                intervals = [(c["start"], c["end"]) for c in clips]
            elif mode == "per_track":
                intervals = track_intervals if project.track_changes.reselect_effects else [(0, total)]
            elif mode == "transitions":
                intervals = [(t["start"], t["end"]) for t in plan.get("transitions", [])]
            elif effect.trigger == "random":
                intervals = list(
                    random_intervals(
                        random, total, fps, effect.probability_per_second, effect.duration, effect.cooldown
                    )
                )
            else:
                if effect.trigger == "track":
                    timestamps = [t["time"] for t in tracks]
                elif effect.trigger == "clip_boundary":
                    timestamps = [c["start"] / fps for c in plan["clips"][1:]]
                elif effect.trigger == "transition":
                    timestamps = [t["start"] / fps for t in plan.get("transitions", [])]
                else:
                    timestamps = events(
                        plan["audio_features"], effect.trigger, effect.threshold, effect.hysteresis
                    )
                audio_events[effect.id] = timestamps
                intervals, ready = [], 0
                for time in timestamps:
                    begin = round(time * fps)
                    if begin < ready or begin >= total or random.random() > effect.probability:
                        continue
                    end = min(total, begin + max(1, round(sample(effect.duration, random) * fps)))
                    intervals.append((begin, end))
                    ready = end + round(effect.cooldown * fps)
            for begin, end in intervals:
                if (mode != "events" or effect.trigger == "random") and random.random() > effect.probability:
                    continue
                params = sampled_params(effect.type, effect.params, random)
                activations.append(
                    {
                        "id": effect.id,
                        "type": effect.type,
                        "start": begin,
                        "end": end,
                        "params": params,
                        "intensity": effect.intensity,
                        "order": effect.order,
                        "layer": effect.layer,
                        "attack": effect.attack,
                        "release": effect.release,
                        "persist": effect.persist,
                        "inactive": effect.inactive,
                        "reset_on": effect.reset_on,
                        "reset_times": effect.reset_times,
                        "input_b": effect.input_b,
                    }
                )
    plan["effects"], plan["audio_events"] = activations, audio_events


def sampled_params(kind, params, random):
    result = defaults(kind)
    result.update(params)
    for key in PARAMETERS[kind]:
        result[key] = sample(result[key], random)
    return result


def schedule_transitions(plan, project, reserve=True):
    fps = float(Fraction(str(project.output.fps)))
    random = rng(plan["seed"], "transitions")
    transitions = []
    for index, incoming in enumerate(plan["clips"][1:], 1):
        outgoing = plan["clips"][index - 1]
        if project.transitions:
            selected = random.choices(project.transitions, weights=[t.weight for t in project.transitions])[0]
            if selected.type == "cut":
                continue
            count = max(1, round(sample(selected.duration, random) * fps))
            kind, intensity = selected.type, sample(selected.intensity, random)
            params = sampled_params(kind, selected.params, random)
        else:
            count = round(outgoing.get("crossfade", 0) * fps)
            if not count:
                continue
            kind, intensity, params = "analog_crossfade", 1, defaults("analog_crossfade")
            params["bleed"] = 0
        count = min(count, incoming["end"] - incoming["start"], outgoing["end"] - outgoing["start"])
        if reserve and not outgoing["freeze"]:
            source = plan["media"][outgoing["source"]]
            nominal = (outgoing["end"] - outgoing["start"]) / fps * outgoing["speed"]
            tail = count / fps * outgoing["speed"]
            if source["duration"] >= nominal + tail:
                if outgoing["reverse"]:
                    outgoing["offset"] = max(tail, min(outgoing["offset"], source["duration"] - nominal))
                else:
                    outgoing["offset"] = min(outgoing["offset"], source["duration"] - nominal - tail)
        transitions.append(
            {
                "start": incoming["start"],
                "end": incoming["start"] + count,
                "outgoing": index - 1,
                "incoming": index,
                "type": kind,
                "intensity": intensity,
                "params": params,
            }
        )
    plan["transitions"] = transitions


def schedule_overlays(plan, project, fps, total):
    overlays = []
    for overlay in project.overlays:
        random = rng(plan["seed"], f"overlay:{overlay.id}")
        intervals = (
            [(0, total)]
            if overlay.activation == "global"
            else random_intervals(random, total, fps, overlay.probability_per_second, overlay.duration)
        )
        source = Path(overlay.source)
        if overlay.source.startswith("generator:"):
            assets = [{"path": overlay.source, "duration": 15}]
        elif source.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp"} and source.is_file():
            assets = [{"path": str(source), "duration": 15, "image": True}]
        else:
            assets = discover([source], project.ffprobe)
        for begin, end in intervals:
            opacity = sample(overlay.opacity, random)
            while begin < end:
                asset = random.choice(assets)
                count = min(end - begin, max(1, round(min(15, asset["duration"]) * fps)))
                overlays.append(
                    {
                        **overlay.model_dump(mode="json"),
                        "start": begin,
                        "end": begin + count,
                        "opacity": opacity,
                        "asset": asset,
                        "offset": 0,
                    }
                )
                begin += count
    plan["overlays"] = overlays
