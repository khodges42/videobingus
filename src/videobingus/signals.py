import hashlib
import math

from pydantic import BaseModel, ConfigDict, Field, model_validator

AUDIO_SIGNALS = {
    "rms",
    "amplitude",
    "bass_energy",
    "mid_energy",
    "high_energy",
    "flux",
    "bass_onset",
    "onset",
}
BUILTINS = AUDIO_SIGNALS | {"track_time", "transition_progress"}
AUDIO_SIGNALS.update(
    {
        "immediate_energy",
        "sustained_energy",
        "energy_trend",
        "onset_density",
        "low_activity",
        "relative_contrast",
        "visual_intensity",
    }
)
BUILTINS.update(AUDIO_SIGNALS | {"track_progress"})


class Signal(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    type: str = "lfo"
    waveform: str = "sine"
    frequency: float = Field(0.1, ge=0, le=120)
    phase: float = 0
    amplitude: float = Field(1, ge=0, le=100)
    offset: float = 0
    bipolar: bool = False
    attenuation: float = Field(1, ge=-10, le=10)
    smoothing: float = Field(0, ge=0, le=30)
    slew: float = Field(0, ge=0, le=100)
    quantization: int = Field(0, ge=0, le=256)
    rate: float = Field(1, gt=0, le=120)
    source: str = "rms"
    trigger: str | None = None
    threshold: float = Field(0.5, ge=0, le=1)
    attack: float = Field(0.05, gt=0, le=30)
    release: float = Field(0.5, gt=0, le=30)
    step: float = Field(0.15, gt=0, le=1)

    @model_validator(mode="after")
    def valid(self):
        if self.type not in {
            "lfo",
            "smooth_random",
            "sample_hold",
            "random_walk",
            "envelope",
            "audio",
            "track_time",
            "transition_progress",
        }:
            raise ValueError(f"Unknown signal type: {self.type}")
        if self.waveform not in {"sine", "triangle", "sawtooth", "square"}:
            raise ValueError("Unknown LFO waveform")
        return self


def wave(phase, waveform="sine"):
    import numpy as np

    phase = np.asarray(phase)
    if waveform == "sine":
        return np.sin(phase * 2 * np.pi)
    if waveform == "triangle":
        return 1 - 4 * np.abs((phase % 1) - 0.5)
    if waveform == "sawtooth":
        return 2 * (phase % 1) - 1
    return np.where((phase % 1) < 0.5, 1, -1)


def validate_signals(signals):
    def dependencies(name, visiting):
        if name in BUILTINS:
            return
        if name not in signals:
            raise ValueError(f"Unknown control signal: {name}")
        if name in visiting:
            raise ValueError("Control signal dependency cycle")
        signal = signals[name]
        if signal.type in {"audio", "envelope"}:
            dependencies(signal.source, visiting | {name})
        if signal.trigger:
            dependencies(signal.trigger, visiting | {name})

    for name in signals:
        if name in BUILTINS or "." in name:
            raise ValueError(f"Reserved or invalid signal name: {name}")
        dependencies(name, set())


def needs_audio(signals, names):
    def uses(name):
        if name in AUDIO_SIGNALS:
            return True
        signal = signals.get(name)
        if signal is None:
            return False
        return (signal.type in {"audio", "envelope"} and uses(signal.source)) or (
            signal.trigger is not None and uses(signal.trigger)
        )

    return any(uses(name) for name in names)


class SignalBank:
    def __init__(self, definitions, seed, fps):
        self.definitions, self.seed, self.fps = definitions, seed, fps
        self.state = {}
        self.ids = {
            name: int.from_bytes(hashlib.sha256(name.encode()).digest()[:8], "big") for name in definitions
        }
        self.last = -1

    def noise(self, name, tick):
        import numpy as np

        return float(
            np.random.default_rng(np.random.SeedSequence([self.seed, self.ids[name], max(0, tick)])).random()
        )

    def evaluate(self, index, audio=None, track_time=0, transition_progress=0):
        import numpy as np

        if index != self.last + 1:
            raise ValueError(
                "Control signals require contiguous frame evaluation; prime signals from frame zero"
            )
        self.last = index
        values = {**(audio or {}), "track_time": track_time, "transition_progress": transition_progress}
        values["amplitude"] = values.get("rms", 0)
        for name in BUILTINS:
            values.setdefault(name, 0)

        def evaluate(name):
            if name in values:
                return values[name]
            spec = self.definitions[name]
            state = self.state.setdefault(name, {})
            time = index / self.fps
            tick = math.floor(time * spec.rate)
            if spec.type == "lfo":
                value = float(wave(time * spec.frequency + spec.phase, spec.waveform)) * 0.5 + 0.5
            elif spec.type == "smooth_random":
                phase = time * spec.rate % 1
                phase = phase * phase * (3 - 2 * phase)
                value = self.noise(name, tick) * (1 - phase) + self.noise(name, tick + 1) * phase
            elif spec.type == "sample_hold":
                if spec.trigger:
                    gate = evaluate(spec.trigger) >= spec.threshold
                    if gate and not state.get("gate", False):
                        state["sample"] = self.noise(name, index)
                    state["gate"] = gate
                    value = state.get("sample", 0.5)
                else:
                    value = self.noise(name, tick)
            elif spec.type == "random_walk":
                value = state.get("walk", 0.5)
                for step in range(state.get("tick", -1) + 1, tick + 1):
                    value = float(np.clip(value + (self.noise(name, step) * 2 - 1) * spec.step, 0, 1))
                state["walk"], state["tick"] = value, tick
            elif spec.type == "envelope":
                gate = float(evaluate(spec.source) >= spec.threshold)
                previous = state.get("envelope", 0)
                tau = spec.attack if gate > previous else spec.release
                value = previous + (gate - previous) * (1 - math.exp(-1 / (self.fps * tau)))
                state["envelope"] = value
            elif spec.type == "audio":
                value = evaluate(spec.source)
            else:
                value = values[spec.type]
            if spec.bipolar:
                value = value * 2 - 1
            value = value * spec.amplitude * spec.attenuation + spec.offset
            if spec.quantization > 1:
                value = round(value * (spec.quantization - 1)) / (spec.quantization - 1)
            previous = state.get("output", value)
            if spec.smoothing:
                value = previous + (value - previous) * (1 - math.exp(-1 / (self.fps * spec.smoothing)))
            if spec.slew:
                value = previous + float(
                    np.clip(value - previous, -spec.slew / self.fps, spec.slew / self.fps)
                )
            state["output"] = values[name] = value
            return value

        for name in self.definitions:
            evaluate(name)
        return values
