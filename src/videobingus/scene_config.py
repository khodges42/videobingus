from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .scenes.catalog import validate_params


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class SceneTrigger(Model):
    source: Literal["bass_onset", "onset", "energy", "track"] = "bass_onset"
    action: Literal["disturbance", "reset"] = "disturbance"
    threshold: float = Field(0.6, ge=0, le=1)
    hysteresis: float = Field(0.1, ge=0, le=1)
    probability: float = Field(1, ge=0, le=1)
    cooldown: float = Field(3, ge=0)


class Scene(Model):
    id: str | None = Field(None, pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")
    type: str
    weight: float = Field(1, gt=0)
    params: dict = Field(default_factory=dict)
    palette: str | None = None
    minimum_scene_duration: float = Field(0, ge=0, le=600)
    retain_state: bool = False
    triggers: list[SceneTrigger] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid(self):
        validate_params(self.type, self.params)
        from .scenes.catalog import CATALOG

        for trigger in self.triggers:
            if trigger.action not in CATALOG[self.type]["triggers"]:
                raise ValueError(f"{self.type} does not support the {trigger.action} action")
        if self.id is None:
            self.id = self.type
        return self


class Performance(Model):
    quality: Literal["draft", "retro", "balanced", "high"] = "balanced"
    generator_resolution: tuple[int, int] = (640, 360)
    simulation_resolution: tuple[int, int] = (320, 180)
    simulation_hz: int = Field(30, ge=1, le=60)
    upscale: Literal["linear", "nearest", "cubic"] = "linear"
    state_cache: int = Field(4, ge=2, le=8)

    @model_validator(mode="before")
    @classmethod
    def quality_defaults(cls, raw):
        raw = dict(raw)
        profiles = {
            "draft": ((320, 180), (160, 90), 15, "linear"),
            "retro": ((320, 200), (160, 100), 30, "nearest"),
            "balanced": ((640, 360), (320, 180), 30, "linear"),
            "high": ((960, 540), (480, 270), 30, "linear"),
        }
        values = profiles.get(raw.get("quality", "balanced"), profiles["balanced"])
        for key, value in zip(
            ("generator_resolution", "simulation_resolution", "simulation_hz", "upscale"), values
        ):
            raw.setdefault(key, value)
        return raw

    @model_validator(mode="after")
    def valid(self):
        for resolution in (self.generator_resolution, self.simulation_resolution):
            if any(v < 16 or v > 1920 for v in resolution) or resolution[0] * resolution[1] > 1920 * 1080:
                raise ValueError(
                    "Internal resolutions require dimensions 16–1920 and at most 1920x1080 pixels"
                )
        return self


class Composition(Model):
    mode: Literal["auto", "footage", "generative", "hybrid"] = "auto"
    footage_weight: float = Field(0.4, ge=0)
    generated_weight: float = Field(0.6, ge=0)
    scene_duration: tuple[float, float] = (8, 35)
    motif_recurrence: float = Field(0.3, ge=0, le=1)
    dynamics: bool = False
    minimum_state_duration: float = Field(8, ge=1, le=120)
    scene_change_sensitivity: float = Field(0.4, ge=0, le=1)
    effect_density_sensitivity: float = Field(0.5, ge=0, le=1)
    max_scene_changes_per_minute: float = Field(20, gt=0, le=120)

    @model_validator(mode="after")
    def valid(self):
        if not 0.1 <= self.scene_duration[0] <= self.scene_duration[1] <= 600:
            raise ValueError("scene_duration must be an ordered range in [0.1, 600] seconds")
        if self.footage_weight + self.generated_weight <= 0:
            raise ValueError("At least one composition weight must be positive")
        return self


class Identity(Model):
    palette_family: list[str] = Field(default_factory=lambda: ["deep_space"], min_length=1)
    palette_scope: Literal["mix", "track", "section"] = "track"
    background: str = "#030814"
    analog_bias: float = Field(0.5, ge=0, le=1)
    geometric_bias: float = Field(0.5, ge=0, le=1)
    motion: float = Field(0.5, ge=0, le=1)
    density: float = Field(0.5, ge=0, le=1)
    complexity: float = Field(0.5, ge=0, le=1)
    feedback: float = Field(0.3, ge=0, le=1)
    corruption: float = Field(0.2, ge=0, le=1)

    @model_validator(mode="after")
    def valid(self):
        from .palettes import colors

        colors([self.background, "#ffffff"])
        return self


class Randomization(Model):
    max_global_effects: int = Field(3, ge=0, le=8)
    max_scene_effects: int = Field(3, ge=0, le=8)
    max_simultaneous_events: int = Field(2, ge=0, le=4)
    max_overlays: int = Field(2, ge=0, le=4)
    max_expensive_processors: int = Field(1, ge=0, le=3)
    preserve_palette: bool = True
    intensity: float = Field(0.6, ge=0, le=1)


class Selection(Model):
    generators: list[str] = Field(default_factory=list)
    effects: list[str] = Field(default_factory=list)
    include_effect: list[str] = Field(default_factory=list)
    exclude_effect: list[str] = Field(default_factory=list)
    randomize: bool = False
    intensity: float | None = Field(None, ge=0, le=1)
    theme: str = "analog"
