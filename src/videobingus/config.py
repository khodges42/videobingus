from fractions import Fraction
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .effects.registry import GENERATORS, parameter_names, validate_params
from .effects.synthesis_specs import MIXERS
from .scene_config import Composition, Identity, Performance, Randomization, Scene, Selection
from .scenes.catalog import CATALOG
from .signals import BUILTINS, Signal, validate_signals


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, allow_inf_nan=False)


class Output(Model):
    path: Path = Path("mix.mp4")
    resolution: tuple[int, int] = (1920, 1080)
    fps: str | int | float = 30
    codec: Literal["h264"] = "h264"
    crf: int = Field(20, ge=0, le=51)
    encoder_preset: Literal[
        "ultrafast",
        "superfast",
        "veryfast",
        "faster",
        "fast",
        "medium",
        "slow",
        "slower",
        "veryslow",
        "placebo",
    ] = "medium"
    fit: Literal["fit", "crop", "stretch"] = "fit"

    @property
    def fps_fraction(self):
        return Fraction(str(self.fps))

    @model_validator(mode="after")
    def valid(self):
        if any(v < 2 or v % 2 for v in self.resolution):
            raise ValueError("resolution dimensions must be positive even integers")
        if not 1 <= Fraction(str(self.fps)) <= 120:
            raise ValueError("fps must be between 1 and 120")
        if self.path.suffix.lower() != ".mp4":
            raise ValueError("output must use the .mp4 container")
        return self


def ordered(value, name, minimum=0):
    if value[0] < minimum or value[1] < value[0]:
        raise ValueError(f"{name} must be an ordered range >= {minimum}")


class Clips(Model):
    crossfade: float = Field(0, ge=0, le=2)
    selection: Literal["shuffle", "random"] = "shuffle"
    duration: tuple[float, float] = (3, 15)
    random_start: bool = True
    allow_consecutive_source: bool = False
    speed: tuple[float, float] = (1, 1)
    reverse_probability: float = Field(0, ge=0, le=1)
    freeze_probability: float = Field(0, ge=0, le=1)
    short_source: Literal["shorten", "loop"] = "shorten"

    @model_validator(mode="after")
    def valid(self):
        ordered(self.duration, "clip duration", 0.05)
        ordered(self.speed, "speed", 0.1)
        if self.duration[1] > 120:
            raise ValueError("clips are limited to 120 seconds to bound reverse buffering")
        return self


class Effect(Model):
    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")
    type: str
    intensity: float = Field(1, ge=0, le=1)
    probability: float = Field(1, ge=0, le=1)
    probability_per_second: float = Field(0.02, ge=0, le=1)
    trigger: Literal["random", "bass_onset", "onset", "energy", "track", "clip_boundary", "transition"] = (
        "random"
    )
    duration: tuple[float, float] = (0.2, 1)
    cooldown: float = Field(3, ge=0)
    threshold: float = Field(0.6, ge=0, le=1)
    hysteresis: float = Field(0.1, ge=0, le=1)
    attack: float = Field(0, ge=0)
    release: float = Field(0, ge=0)
    order: int = 0
    layer: str = "composite"
    persist: bool = True
    preserve_state_across_clips: bool | None = None
    inactive: Literal["retain", "clear", "update"] = "retain"
    reset_on: list[Literal["activation", "clip", "track"]] = Field(default_factory=list)
    reset_times: list[float] = Field(default_factory=list)
    input_b: str | None = None
    params: dict = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def parameters(cls, raw):
        raw = dict(raw)
        known = parameter_names(raw.get("type"))
        params = dict(raw.get("params", {}))
        for name in known:
            if name in raw:
                params[name] = raw.pop(name)
        raw["params"] = params
        return raw

    @model_validator(mode="after")
    def valid(self):
        validate_params(self.type, self.params)
        ordered(self.duration, "effect duration", 0.01)
        if any(t < 0 for t in self.reset_times):
            raise ValueError("reset_times must be nonnegative seconds")
        if self.preserve_state_across_clips is not None:
            self.persist = self.preserve_state_across_clips
        return self


class Effects(Model):
    global_: list[Effect] = Field(default_factory=list, alias="global")
    per_clip: list[Effect] = Field(default_factory=list)
    per_track: list[Effect] = Field(default_factory=list)
    events: list[Effect] = Field(default_factory=list)
    transitions: list[Effect] = Field(default_factory=list)

    def all(self):
        return self.global_ + self.per_clip + self.per_track + self.events + self.transitions


class Overlay(Model):
    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")
    source: str
    blend: Literal["normal", "add", "additive", "screen", "multiply", "difference"] = "normal"
    opacity: float | tuple[float, float] = 0.3
    position: Literal["center", "top_left", "top_right", "bottom_left", "bottom_right"] = "center"
    scale: float = Field(1, gt=0, le=1)
    activation: Literal["global", "random"] = "global"
    duration: tuple[float, float] = (4, 12)
    probability_per_second: float = Field(0.015, ge=0, le=1)
    luma_key: float | None = Field(None, ge=0, le=1)
    generator_params: dict = Field(default_factory=dict)
    role: Literal["overlay", "input", "mask", "displacement"] = "overlay"
    displacement: tuple[float, float] = (24, 12)

    @model_validator(mode="after")
    def valid(self):
        ordered(self.duration, "overlay duration", 0.01)
        if any(abs(value) > 200 for value in self.displacement):
            raise ValueError("Overlay displacement must lie within [-200, 200] pixels")
        values = [self.opacity] if isinstance(self.opacity, float) else self.opacity
        if any(not 0 <= v <= 1 for v in values):
            raise ValueError("opacity must lie within [0, 1]")
        if len(values) == 2:
            ordered(values, "opacity")
        if self.source.startswith("generator:") and self.source.split(":", 1)[1] not in GENERATORS:
            raise ValueError("Unknown overlay generator")
        if self.source.startswith("generator:"):
            from .generators import validate_generator_params

            validate_generator_params(self.source.split(":", 1)[1], self.generator_params)
        elif self.generator_params:
            raise ValueError("generator_params requires a generator source")
        return self


class Generator(Model):
    type: str
    probability: float = Field(0.02, ge=0, le=1)
    duration: tuple[float, float] = (0.2, 2)
    params: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid(self):
        if self.type not in GENERATORS:
            raise ValueError(f"Unknown generator: {self.type}")
        ordered(self.duration, "generator duration", 0.01)
        from .generators import validate_generator_params

        validate_generator_params(self.type, self.params)
        return self


class Modulation(Model):
    target: str
    source: str
    output_range: tuple[float, float]
    smoothing: float = Field(0.15, ge=0, le=30)
    combine: Literal["add", "replace", "multiply"] = "add"


class Transition(Model):
    type: str = "analog_crossfade"
    weight: float = Field(1, gt=0)
    duration: tuple[float, float] = (0.5, 1.5)
    intensity: float | tuple[float, float] = 1.0
    params: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid(self):
        if self.type not in MIXERS | {"cut"}:
            raise ValueError(f"Unknown transition mixer: {self.type}")
        ordered(self.duration, "transition duration", 0.01)
        if self.duration[1] > 10:
            raise ValueError("Transition duration is limited to ten seconds")
        values = [self.intensity] if isinstance(self.intensity, float) else self.intensity
        if any(not 0 <= v <= 1 for v in values):
            raise ValueError("Transition intensity must lie in [0, 1]")
        if len(values) == 2:
            ordered(values, "transition intensity")
        if self.type != "cut":
            validate_params(self.type, self.params)
        elif self.params:
            raise ValueError("Cut transitions have no parameters")
        return self


class Titles(Model):
    enabled: bool = False
    style: Literal["lower_third", "vcr"] = "lower_third"
    mix_title: str = ""
    font: Path | None = None
    font_size: int = Field(32, ge=8, le=256)
    color: str = "#ffffff"
    position: Literal["top_left", "top_right", "bottom_left", "bottom_right", "center"] = "bottom_left"
    duration: float = Field(8, gt=0)
    fade_in: float = Field(0.3, ge=0)
    fade_out: float = Field(0.5, ge=0)


class TrackChanges(Model):
    cut_clip: bool = True
    reselect_effects: bool = True


class TrackOverride(Model):
    index: int = Field(ge=1)
    sources: list[Path] | None = None
    clips: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid(self):
        Clips.model_validate(merge(Clips().model_dump(), self.clips))
        return self


class Project(Model):
    seed: int | None = Field(None, ge=0, le=2**63 - 1)
    audio: Path
    sources: list[Path] = Field(default_factory=list)
    preset: str = "clean"
    cue: Path | None = None
    ffmpeg: str | None = None
    ffprobe: str | None = None
    output: Output = Field(default_factory=Output)
    clips: Clips = Field(default_factory=Clips)
    analysis: bool = False
    effects: Effects = Field(default_factory=Effects)
    overlays: list[Overlay] = Field(default_factory=list)
    generators: list[Generator] = Field(default_factory=list)
    modulation: list[Modulation] = Field(default_factory=list)
    titles: Titles = Field(default_factory=Titles)
    track_changes: TrackChanges = Field(default_factory=TrackChanges)
    tracks: list[TrackOverride] = Field(default_factory=list)
    transitions: list[Transition] = Field(default_factory=list)
    signals: dict[str, Signal] = Field(default_factory=dict)
    scenes: list[Scene] = Field(default_factory=list)
    composition: Composition = Field(default_factory=Composition)
    performance: Performance = Field(default_factory=Performance)
    identity: Identity = Field(default_factory=Identity)
    palette: str = "deep_space"
    palettes: dict[str, list] = Field(default_factory=dict)
    palette_space: Literal["rgb", "lab"] = "rgb"
    suite: str | None = None
    audio_profiles: list[str] = Field(default_factory=list)
    randomization: Randomization | None = None
    selection: Selection = Field(default_factory=Selection)
    compiled_from: str | None = None
    master_intensity: float = Field(1, ge=0, le=1)

    @model_validator(mode="after")
    def valid(self):
        effects = {e.id: e for e in self.effects.all()}
        overlays = {o.id: o for o in self.overlays}
        from .palettes import colors
        from .scenes.catalog import validate_params as validate_scene_params

        if not self.sources and not self.scenes and not self.generators:
            raise ValueError("Supply footage sources, scenes, or a suite")
        if self.composition.mode == "footage" and not self.sources:
            raise ValueError("Footage composition mode requires source media")
        if self.composition.dynamics and not self.analysis:
            raise ValueError("Composition dynamics require analysis: true")
        scene_types = {s.id: s.type for s in self.scenes}
        scene_types.update(
            {
                o.id: o.source.split(":", 1)[1]
                for o in self.overlays
                if o.source.startswith("generator:") and o.source.split(":", 1)[1] in CATALOG
            }
        )
        if len({s.id for s in self.scenes}) != len(self.scenes):
            raise ValueError("Scene instance identifiers must be unique")
        colors(self.palette, self.palettes)
        if "identity" not in self.model_fields_set or "palette_family" not in self.identity.model_fields_set:
            self.identity.palette_family = [self.palette]
        for family in self.identity.palette_family:
            colors(family, self.palettes)
        for scene in self.scenes:
            if scene.palette:
                colors(scene.palette, self.palettes)
        from .scenes.profiles import NAMES as profile_names

        if set(self.audio_profiles) - profile_names:
            raise ValueError("Unknown generator audio modulation profile")
        validate_signals(self.signals)
        if len(effects) != len(self.effects.all()) or len(overlays) != len(self.overlays):
            raise ValueError("Effect and overlay identifiers must each be unique")
        for effect in effects.values():
            if effect.layer not in {"primary", "composite", *overlays}:
                raise ValueError(f"Unknown layer: {effect.layer}")
            if effect.input_b:
                if effect.type not in MIXERS:
                    raise ValueError(f"{effect.type} is single-input; input_b is only supported by mixers")
                referenced = effect.input_b.removeprefix("previous:")
                if referenced not in {"primary", "composite", *overlays}:
                    raise ValueError(f"Unknown mixer input: {effect.input_b}")
                if not effect.input_b.startswith("previous:"):
                    order = ["primary", *overlays, "composite"]
                    if order.index(referenced) >= order.index(effect.layer):
                        raise ValueError(
                            "Current inputs must refer to earlier layers; use previous: for feedback"
                        )
            if effect.type in MIXERS and effect.input_b is None:
                raise ValueError(
                    f"Mixer {effect.id} requires input_b; project transitions supply A/B automatically"
                )
        for modulation in self.modulation:
            if modulation.source not in BUILTINS | self.signals.keys():
                raise ValueError(f"Unknown modulation source: {modulation.source}")
            parts = modulation.target.split(".")
            if len(parts) != 3:
                raise ValueError(f"Invalid modulation target: {modulation.target}")
            group, instance, parameter = parts
            low, high = sorted(modulation.output_range)
            if group == "effects" and instance in effects:
                effect = effects[instance]
                if parameter == "intensity":
                    if low < 0 or high > 1:
                        raise ValueError("intensity modulation must lie in [0, 1]")
                else:
                    validate_params(effect.type, {parameter: [low, high]})
            elif group == "overlays" and instance in overlays and parameter == "opacity":
                if low < 0 or high > 1:
                    raise ValueError("opacity modulation must lie in [0, 1]")
            elif group in {"scenes", "generators"} and instance in scene_types:
                validate_scene_params(scene_types[instance], {parameter: [low, high]}, modulation=True)
            else:
                raise ValueError(f"Unknown modulation target: {modulation.target}")
        for overlay in self.overlays:
            if overlay.id in {"primary", "composite"}:
                raise ValueError("Overlay identifiers cannot be primary or composite")
        from PIL import ImageColor

        ImageColor.getrgb(self.titles.color)
        visualizers = {"waveform", "spectrum"}
        needs_analysis = any(g.type in visualizers for g in self.generators) or any(
            o.source in {f"generator:{v}" for v in visualizers} for o in self.overlays
        )
        if needs_analysis and not self.analysis:
            raise ValueError("Waveform and spectrum generators require analysis: true")
        if len({t.index for t in self.tracks}) != len(self.tracks):
            raise ValueError("Duplicate track override index")
        if self.randomization:
            if len(self.effects.global_) > self.randomization.max_global_effects:
                raise ValueError("Global effect count exceeds the configured randomization budget")
            if (
                len(self.effects.per_clip) + len(self.effects.per_track) + len(self.effects.transitions)
                > self.randomization.max_scene_effects
            ):
                raise ValueError("Scene effect count exceeds the configured randomization budget")
        return self


def merge(base: dict, updates: dict) -> dict:
    result = dict(base)
    for key, value in updates.items():
        result[key] = (
            merge(result[key], value)
            if isinstance(value, dict) and isinstance(result.get(key), dict)
            else value
        )
    return result


def load(path: Path | None = None, overrides: dict | None = None) -> Project:
    raw = yaml.safe_load(path.read_text(encoding="utf-8-sig")) if path else {}
    if not isinstance(raw, dict):
        raise ValueError("project configuration must be a YAML mapping")
    raw = merge(raw, overrides or {})
    if raw.get("suite") or (raw.get("selection", {}).get("randomize") and not raw.get("compiled_from")):
        import secrets

        from .suites.compiler import THEMES, compile_suite, load_suite

        selection = Selection.model_validate(raw.get("selection", {}))
        reference = raw.get("suite") or THEMES.get(selection.theme)
        if reference is None:
            raise ValueError("Unknown suite-generation theme")
        chosen_seed = raw.get("seed")
        if chosen_seed is None:
            chosen_seed = secrets.randbits(63)
        compiled = compile_suite(
            load_suite(reference, path.resolve().parent if path else None), chosen_seed, selection
        )
        raw = merge(compiled, raw)
        raw["suite"], raw["seed"] = None, chosen_seed
    from importlib.resources import files

    preset = raw.get("preset", "clean")
    if not isinstance(preset, str) or preset not in {
        p.stem for p in files("videobingus.presets").iterdir() if p.name.endswith(".yaml")
    }:
        raise ValueError(f"Unknown preset: {preset}. Run 'videobingus presets list'.")
    defaults = yaml.safe_load(
        files("videobingus.presets").joinpath(f"{preset}.yaml").read_text(encoding="utf-8")
    )
    if overrides and "quality" in overrides.get("performance", {}):
        raw["performance"] = {
            **raw.get("performance", {}),
            **Performance.model_validate(overrides["performance"]).model_dump(),
        }
    project = Project.model_validate(merge(defaults or {}, raw))
    base = path.resolve().parent if path else Path.cwd()
    project.audio = (base / project.audio).resolve()
    project.sources = [(base / source).resolve() for source in project.sources]
    project.cue = (base / project.cue).resolve() if project.cue else None
    project.output.path = (base / project.output.path).resolve()
    for name in ("ffmpeg", "ffprobe"):
        value = getattr(project, name)
        if value and ("/" in value or "\\" in value):
            setattr(project, name, str((base / value).resolve()))
    if project.titles.font:
        project.titles.font = (base / project.titles.font).resolve()
    for overlay in project.overlays:
        if not overlay.source.startswith("generator:"):
            overlay.source = str((base / overlay.source).resolve())
    for track in project.tracks:
        if track.sources:
            track.sources = [(base / p).resolve() for p in track.sources]
    return project
