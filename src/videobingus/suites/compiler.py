import os
from importlib.resources import files
from pathlib import Path

import yaml

from ..effects.catalog import describe as effect_info
from ..effects.registry import PARAMETERS
from ..effects.synthesis_specs import MIXERS
from ..palettes import colors
from ..scene_config import Scene, Selection
from ..scenes.catalog import CATALOG, defaults
from ..suite_config import Candidate, Suite
from ..timeline_random import rng

THEMES = {
    "analog": "acid_television",
    "digital": "digital_decay",
    "organic": "artificial_life",
    "geometric": "demoscene",
    "retro": "demoscene",
    "psychedelic": "acid_television",
    "industrial": "warehouse",
    "minimal": "ambient_feedback",
    "maximal": "mathematical_maximalism",
    "ambient": "ambient_feedback",
}


def names():
    return sorted(p.name[:-5] for p in files("videobingus.suites").iterdir() if p.name.endswith(".yaml"))


def load_suite(reference, base=None):
    path = (base or Path.cwd()) / reference
    if path.is_file():
        raw = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
        suite = Suite.model_validate(raw)
        for overlay in suite.overlays:
            if not overlay.source.startswith("generator:"):
                overlay.source = str((path.resolve().parent / overlay.source).resolve())
        return suite
    if reference not in names():
        raise ValueError(f"Unknown suite {reference!r}; run 'videobingus suites list'")
    return Suite.model_validate(
        yaml.safe_load(files("videobingus.suites").joinpath(reference + ".yaml").read_text(encoding="utf-8"))
    )


def weighted_subset(values, count, random):
    pool, result = list(values), []
    for _ in range(min(count, len(pool))):
        item = random.choices(pool, weights=[p.weight for p in pool])[0]
        result.append(item)
        pool.remove(item)
    return result


def restrict(suite, selection):
    suite = suite.model_copy(deep=True)
    if selection.generators:
        unknown = set(selection.generators) - CATALOG.keys()
        if unknown:
            raise ValueError(f"Unknown scene generators: {sorted(unknown)}")
        suite.generators = [
            next((g for g in suite.generators if g.type == kind), Scene(type=kind))
            for kind in dict.fromkeys(selection.generators)
        ]
    allowed = set(selection.effects) if selection.effects else None
    denied = set(selection.exclude_effect)
    requested = set(selection.effects + selection.include_effect + selection.exclude_effect)
    if requested - PARAMETERS.keys():
        raise ValueError(f"Unknown effects: {sorted(requested - PARAMETERS.keys())}")
    for pool in (suite.effects.persistent.pool, suite.effects.per_scene.pool, suite.effects.events.pool):
        pool[:] = [c for c in pool if c.type not in denied and (allowed is None or c.type in allowed)]
    known = {
        c.type
        for pool in (suite.effects.persistent.pool, suite.effects.per_scene.pool, suite.effects.events.pool)
        for c in pool
    }
    for kind in sorted((set(selection.include_effect) | (allowed or set())) - known - denied):
        if kind in MIXERS:
            from ..config import Transition

            suite.transitions.append(Transition(type=kind))
        else:
            target = (
                suite.effects.events.pool
                if effect_info(kind)["category"] == "corruption"
                else suite.effects.per_scene.pool
            )
            target.append(Candidate(type=kind))
    suite.transitions = [
        t
        for t in suite.transitions
        if t.type not in denied and (allowed is None or t.type in allowed or t.type == "cut")
    ]
    if selection.intensity is not None:
        suite.randomization.intensity = selection.intensity
    return suite


def compile_suite(suite, seed, selection=None):
    suite = restrict(suite, selection or Selection())
    settings = suite.randomization
    generator_random, effect_random = rng(seed, "suite-generators"), rng(seed, "suite-effects")
    identity_random = rng(seed, "suite-identity")
    palette = identity_random.choice(suite.identity.palette_family)
    generator_pool = [
        g for g in suite.generators if settings.max_expensive_processors or CATALOG[g.type]["cost"] != "high"
    ]
    if not generator_pool:
        raise ValueError("The expensive-processor budget excludes every selected generator")
    for generator in generator_pool:
        tags = CATALOG[generator.type]["tags"]
        if "geometric" in tags:
            generator.weight *= 0.5 + suite.identity.geometric_bias
        if "organic" in tags:
            generator.weight *= 1.5 - suite.identity.geometric_bias
    for pool in (suite.effects.persistent.pool, suite.effects.per_scene.pool, suite.effects.events.pool):
        for candidate in pool:
            tags = effect_info(candidate.type)["tags"]
            candidate.weight *= 0.5 + (
                suite.identity.analog_bias if "analog" in tags else 1 - suite.identity.analog_bias
            )
    chosen = weighted_subset(generator_pool, min(4, len(generator_pool)), generator_random)
    scenes = []
    for generator in chosen:
        scene = generator.model_dump(mode="json")
        scene["id"] = generator.id or generator.type
        scene["retain_state"] = CATALOG[generator.type]["stateful"]
        params = dict(generator.params)
        params.setdefault(
            "speed",
            defaults(generator.type)["speed"]
            * (0.5 + suite.identity.motion)
            * generator_random.uniform(0.85, 1.15),
        )
        params.setdefault("palette_phase", generator_random.random() * 0.3)
        for parameter in ("count", "particles", "agents", "iterations", "octaves", "detail"):
            if parameter in CATALOG[generator.type]["parameters"] and parameter not in params:
                default, low, high = CATALOG[generator.type]["parameters"][parameter]
                trait = (
                    suite.identity.density
                    if parameter in {"particles", "agents"}
                    else suite.identity.complexity
                )
                params[parameter] = min(high, max(low, round(default * (0.5 + trait))))
        params.setdefault(
            "audio_influence", 0.2 + 0.4 * settings.intensity if suite.audio_response.enabled else 0
        )
        scene["params"] = params
        scenes.append(scene)
    high_cost = int(any(CATALOG[g.type]["cost"] == "high" for g in chosen))
    used, counts = set(), {}
    effects = {"global": [], "per_clip": [], "events": []}

    def compatible(candidate):
        info = effect_info(candidate.type)
        if candidate.type in used or (
            info["cost"] == "high" and high_cost >= settings.max_expensive_processors
        ):
            return False
        if settings.preserve_palette and candidate.type in {"negative", "hue_shift", "rgb_shift"}:
            return False
        limit = 2 if info["category"] == "signal" and settings.intensity > 0.7 else 1
        return counts.get(info["category"], 0) < limit

    for mode, pool, maximum in (
        ("global", suite.effects.persistent, settings.max_global_effects),
        ("per_clip", suite.effects.per_scene, settings.max_scene_effects),
    ):
        count = min(maximum, effect_random.randint(*pool.choose))
        selected = 0
        for candidate in weighted_subset(pool.pool, len(pool.pool), effect_random):
            if selected >= count:
                break
            if not compatible(candidate):
                continue
            info = effect_info(candidate.type)
            low, high = (
                candidate.intensity if isinstance(candidate.intensity, tuple) else (candidate.intensity,) * 2
            )
            params = dict(candidate.params)
            if candidate.type == "analog_colorizer" and settings.preserve_palette:
                params.update(
                    palette=colors(palette, suite.palettes), red_phase=0, green_phase=0, blue_phase=0
                )
            effects[mode].append(
                {
                    "id": f"suite_{candidate.type}",
                    "type": candidate.type,
                    "intensity": effect_random.uniform(low, high)
                    * settings.intensity
                    * (
                        0.5 + suite.identity.feedback
                        if info["category"] == "feedback"
                        else 0.5 + suite.identity.corruption
                        if info["category"] == "corruption"
                        else 1
                    )
                    / (1.5 if info["category"] in {"feedback", "corruption"} else 1),
                    "probability": 1 if mode == "global" else candidate.probability,
                    "order": info["stage"],
                    "params": params,
                }
            )
            used.add(candidate.type)
            counts[info["category"]] = counts.get(info["category"], 0) + 1
            high_cost += info["cost"] == "high"
            selected += 1
    for candidate in suite.effects.events.pool:
        if not suite.audio_response.enabled and candidate.trigger in {"bass_onset", "onset", "energy"}:
            continue
        info = effect_info(candidate.type)
        if candidate.type in used or (
            info["cost"] == "high" and high_cost >= settings.max_expensive_processors
        ):
            continue
        low, high = (
            candidate.intensity if isinstance(candidate.intensity, tuple) else (candidate.intensity,) * 2
        )
        effects["events"].append(
            {
                "id": f"suite_{candidate.type}",
                "type": candidate.type,
                "intensity": effect_random.uniform(low, high) * settings.intensity,
                "trigger": candidate.trigger,
                "probability": candidate.probability,
                "probability_per_second": candidate.probability_per_second,
                "duration": candidate.duration,
                "cooldown": candidate.cooldown,
                "release": candidate.release,
                "params": candidate.params,
                "order": info["stage"],
            }
        )
        used.add(candidate.type)
        high_cost += info["cost"] == "high"
    overlay_count = (
        min(settings.max_overlays, max(1, round(settings.max_overlays * suite.identity.density)))
        if suite.overlays
        else 0
    )
    overlays = []
    for overlay in weighted_subset(suite.overlays, len(suite.overlays), rng(seed, "suite-overlays")):
        if len(overlays) >= overlay_count:
            break
        kind = overlay.source.removeprefix("generator:")
        cost = int(kind in CATALOG and CATALOG[kind]["cost"] == "high")
        if high_cost + cost <= settings.max_expensive_processors:
            overlays.append(overlay)
            high_cost += cost
    composition = suite.composition.model_dump()
    composition.update(
        dynamics=suite.audio_response.enabled and suite.audio_response.preserve_quiet_sections,
        scene_change_sensitivity=suite.audio_response.scene_change_sensitivity,
        effect_density_sensitivity=suite.audio_response.effect_density_sensitivity,
    )
    randomization = settings.model_dump()
    randomization["max_simultaneous_events"] = min(
        settings.max_simultaneous_events, suite.effects.events.max_active
    )
    return {
        "seed": seed,
        "suite": None,
        "compiled_from": suite.name,
        "scenes": scenes,
        "effects": effects,
        "transitions": [t.model_dump(mode="json") for t in suite.transitions],
        "palette": palette,
        "palettes": suite.palettes,
        "identity": suite.identity.model_dump(),
        "composition": composition,
        "clips": {"crossfade": 0},
        "randomization": randomization,
        "analysis": suite.audio_response.enabled,
        "audio_profiles": suite.audio_response.profiles if suite.audio_response.enabled else [],
        "overlays": [o.model_dump(mode="json", exclude={"weight"}) for o in overlays],
        "performance": suite.performance.model_dump(),
    }


def export_project(project, path, overwrite=False):
    raw = project.model_dump(mode="json", by_alias=True)

    def relative(value):
        return Path(os.path.relpath(value, path.resolve().parent)).as_posix()

    raw["audio"] = relative(raw["audio"])
    raw["sources"] = [relative(p) for p in raw["sources"]]
    raw["output"]["path"] = relative(raw["output"]["path"])
    if raw["cue"]:
        raw["cue"] = relative(raw["cue"])
    if raw["titles"]["font"]:
        raw["titles"]["font"] = relative(raw["titles"]["font"])
    for overlay in raw["overlays"]:
        if not overlay["source"].startswith("generator:"):
            overlay["source"] = relative(overlay["source"])
    for track in raw["tracks"]:
        if track["sources"]:
            track["sources"] = [relative(p) for p in track["sources"]]
    raw["ffmpeg"], raw["ffprobe"] = None, None
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w" if overwrite else "x", encoding="utf-8") as handle:
        yaml.safe_dump(raw, handle, sort_keys=False, allow_unicode=True)
