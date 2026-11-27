import math
from fractions import Fraction

from ..palettes import colors
from ..timeline_random import rng
from .runtime import sampled_params, stable_seed


def plan_scenes(
    project,
    media,
    duration,
    tracks,
    seed,
    features=None,
    dynamics=None,
    track_sources=None,
    primary_pool=None,
):
    from ..director import state_at

    fps = float(Fraction(str(project.output.fps)))
    total = math.ceil(Fraction(str(duration)) * Fraction(str(project.output.fps)))
    random = rng(seed, "scene-selection")
    choices = project.scenes
    mode = project.composition.mode
    motifs = {}
    for choice in choices:
        motif_seed = stable_seed(seed, choice.id)
        motifs[choice.id] = {
            "id": choice.id,
            "type": choice.type,
            "seed": motif_seed,
            "params": sampled_params(choice.type, choice.params, motif_seed, project.performance.quality),
            "palette": colors(choice.palette or project.palette, project.palettes),
            "retain_state": choice.retain_state,
            "triggers": [t.model_dump() for t in choice.triggers],
        }
    clips = []
    cursor, previous = 0, None
    history = []
    while cursor < total:
        generated = (
            not media
            or mode == "generative"
            or (
                mode != "footage"
                and random.random()
                < project.composition.generated_weight
                / (project.composition.generated_weight + project.composition.footage_weight)
            )
        )
        if not choices:
            generated = False
        state = state_at(dynamics or [], cursor / fps)
        from .catalog import CATALOG

        weights = [
            s.weight
            * (
                1.7
                if state["state"] in {"calm", "recovery"}
                and {"organic", "slow", "ambient"} & set(CATALOG[s.type]["tags"])
                else 1
            )
            for s in choices
        ]
        choice = random.choices(choices, weights=weights)[0] if generated else None
        if choice and len(history) > 1 and random.random() < project.composition.motif_recurrence:
            earlier = [s for s in choices if s.id in history[:-1] and s.id != history[-1]]
            if earlier:
                choice = random.choice(earlier)
        minimum, maximum = project.composition.scene_duration
        if choice:
            minimum = max(minimum, choice.minimum_scene_duration)
            maximum = max(maximum, minimum)
        length = random.uniform(minimum, maximum)
        if project.composition.dynamics:
            length *= (
                1.3 if state["state"] in {"calm", "recovery"} else 0.8 if state["state"] == "peak" else 1
            )
            length = min(maximum, max(minimum, length))
        current_track = next((t for t in reversed(tracks) if t["time"] <= cursor / fps), None)
        for override in project.tracks:
            if current_track and override.index == current_track["index"] and "duration" in override.clips:
                length = random.uniform(*override.clips["duration"])
        length = max(length, 60 / project.composition.max_scene_changes_per_minute)
        count = min(total - cursor, max(1, round(length * fps)))
        if project.track_changes.cut_clip:
            next_track = next(
                (round(t["time"] * fps) for t in tracks if round(t["time"] * fps) > cursor), total
            )
            count = min(count, next_track - cursor)
        source = None
        if not generated or (
            media
            and choice
            and any(
                motifs[choice.id]["params"].get(p, 0) > 0
                for p in ("texture_mix", "video_injection", "video_influence")
            )
        ):
            candidates = list(
                (track_sources or {}).get(
                    current_track["index"] if current_track else None,
                    primary_pool if primary_pool is not None else range(len(media)),
                )
            )
            if len(candidates) > 1 and previous in candidates:
                candidates.remove(previous)
            source = random.choice(candidates)
            previous = source
        clip = {
            "start": cursor,
            "end": cursor + count,
            "source": source,
            "offset": 0,
            "speed": 1,
            "reverse": False,
            "freeze": False,
            "crossfade": project.clips.crossfade,
        }
        if source is not None and project.clips.random_start:
            clip["offset"] = random.uniform(0, max(0, media[source]["duration"] - count / fps))
        if generated:
            clip["scene"] = dict(motifs[choice.id])
            if not choice.palette:
                scope = (
                    f"track:{current_track['index'] if current_track else 0}"
                    if project.identity.palette_scope == "track"
                    else f"section:{state['time']}"
                    if project.identity.palette_scope == "section"
                    else "mix"
                )
                family = rng(seed, "palette:" + scope).choice(project.identity.palette_family)
                clip["scene"]["palette"] = colors(family, project.palettes)
                clip["scene"]["palette_name"] = family
            if "background" in project.identity.model_fields_set:
                background = colors([project.identity.background, "#ffffff"])[0]
                clip["scene"]["palette"] = [background, *clip["scene"]["palette"][1:]]
            history.append(choice.id)
        clip["visual_state"] = state["state"]
        clips.append(clip)
        cursor += count
    return clips
