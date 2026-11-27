from pydantic import Field, model_validator

from .config import Overlay, Transition
from .effects.registry import parameter_names, validate_params
from .effects.synthesis_specs import MIXERS
from .scene_config import Composition, Identity, Model, Performance, Randomization, Scene


class Candidate(Model):
    type: str
    weight: float = Field(1, gt=0)
    intensity: float | tuple[float, float] = (0.2, 0.45)
    probability: float = Field(0.4, ge=0, le=1)
    trigger: str = "random"
    probability_per_second: float = Field(0.025, ge=0, le=1)
    duration: tuple[float, float] = (0.3, 1.5)
    cooldown: float = Field(5, ge=0)
    release: float = Field(0.4, ge=0)
    params: dict = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def parameters(cls, raw):
        raw = dict(raw)
        params = dict(raw.get("params", {}))
        for name in parameter_names(raw.get("type")):
            if name in raw:
                params[name] = raw.pop(name)
        raw["params"] = params
        return raw

    @model_validator(mode="after")
    def valid(self):
        validate_params(self.type, self.params)
        if self.type in MIXERS:
            raise ValueError("Two-input mixers belong under suite transitions")
        values = [self.intensity] if isinstance(self.intensity, (float, int)) else self.intensity
        if any(not 0 <= value <= 1 for value in values) or (len(values) == 2 and values[0] > values[1]):
            raise ValueError("Candidate intensity must be an ordered range within [0, 1]")
        if not 0.01 <= self.duration[0] <= self.duration[1] <= 120:
            raise ValueError("Invalid candidate event duration")
        from .config import Effect

        Effect(id="validate", type=self.type, trigger=self.trigger)
        return self


class Pool(Model):
    choose: tuple[int, int] = (0, 2)
    pool: list[Candidate] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid(self):
        if not 0 <= self.choose[0] <= self.choose[1] <= 8:
            raise ValueError("Pool choose must be an ordered integer range in [0, 8]")
        return self


class Events(Model):
    max_active: int = Field(2, ge=0, le=4)
    pool: list[Candidate] = Field(default_factory=list)


class Pools(Model):
    persistent: Pool = Field(default_factory=Pool)
    per_scene: Pool = Field(default_factory=Pool)
    events: Events = Field(default_factory=Events)


class AudioResponse(Model):
    enabled: bool = True
    profiles: list[str] = Field(default_factory=lambda: ["sub_pressure", "spectral_color"])
    scene_change_sensitivity: float = Field(0.4, ge=0, le=1)
    effect_density_sensitivity: float = Field(0.5, ge=0, le=1)
    preserve_quiet_sections: bool = True


class SuiteOverlay(Overlay):
    weight: float = Field(1, gt=0)


class Suite(Model):
    name: str = "custom"
    description: str = "Constrained procedural visual performance."
    composition: Composition = Field(default_factory=Composition)
    identity: Identity = Field(default_factory=Identity)
    generators: list[Scene] = Field(min_length=1)
    effects: Pools = Field(default_factory=Pools)
    transitions: list[Transition] = Field(default_factory=lambda: [Transition(type="analog_crossfade")])
    overlays: list[SuiteOverlay] = Field(default_factory=list)
    audio_response: AudioResponse = Field(default_factory=AudioResponse)
    randomization: Randomization = Field(default_factory=Randomization)
    performance: Performance = Field(default_factory=Performance)
    palettes: dict[str, list] = Field(default_factory=dict)
