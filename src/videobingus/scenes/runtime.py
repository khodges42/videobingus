import hashlib
import time
from collections import OrderedDict
from dataclasses import dataclass, field, replace

import cv2
import numpy as np

from ..palettes import ColorStops, colors
from ..scene_config import Performance
from .catalog import CATALOG, defaults, validate_params


@dataclass
class SceneContext:
    time: float
    local_time: float
    index: int
    fps: float
    audio: dict = field(default_factory=dict)
    video: np.ndarray | None = None
    track: dict | None = None
    signals: dict = field(default_factory=dict)
    activation: int = 0
    actions: tuple = ()


def sampled_params(kind, params, seed, quality="balanced"):
    validate_params(kind, params)
    random = np.random.default_rng(seed)
    result = defaults(kind)
    for name, value in params.items():
        result[name] = float(random.uniform(*value)) if isinstance(value, (tuple, list)) else value
    factor = {"draft": 0.45, "retro": 0.65, "balanced": 1, "high": 1.3}[quality]
    for name in ("population", "points_per_step", "iterations", "detail"):
        if name in result and name not in params:
            low, high = CATALOG[kind]["parameters"][name][1:]
            result[name] = round(
                np.clip(result[name] * (factor**2 if name == "population" else factor), low, high)
            )
    return result


def fit_frame(frame, resolution, fit="fit", upscale="linear"):
    width, height = resolution
    mode = {"linear": cv2.INTER_LINEAR, "nearest": cv2.INTER_NEAREST, "cubic": cv2.INTER_CUBIC}[upscale]
    if fit == "stretch":
        return cv2.resize(frame, (width, height), interpolation=mode)
    h, w = frame.shape[:2]
    scale = min(width / w, height / h) if fit == "fit" else max(width / w, height / h)
    resized = cv2.resize(frame, (max(1, round(w * scale)), max(1, round(h * scale))), interpolation=mode)
    rh, rw = resized.shape[:2]
    if fit == "crop":
        x, y = max(0, (rw - width) // 2), max(0, (rh - height) // 2)
        return resized[y : y + height, x : x + width]
    out = np.zeros((height, width, 3), dtype=np.uint8)
    x, y = (width - rw) // 2, (height - rh) // 2
    out[y : y + rh, x : x + rw] = resized
    return out


class SceneRuntime:
    def __init__(
        self,
        kind,
        params=None,
        seed=420,
        performance=None,
        palette="deep_space",
        palette_space="rgb",
        triggers=None,
    ):
        if kind not in CATALOG:
            raise ValueError(f"Unknown scene generator: {kind}")
        self.kind, self.seed = kind, seed
        self.performance = (
            performance
            if isinstance(performance, Performance)
            else Performance.model_validate(performance or {})
        )
        self.params = sampled_params(kind, params or {}, seed, self.performance.quality)
        self.palette = colors(palette) if isinstance(palette, str) else palette
        self.palette_space = palette_space
        self.random = np.random.default_rng(seed)
        self.data = {}
        self.tick, self.origin_tick, self.activation = 0, 0, None
        self.initialized = False
        self.seconds, self.calls = 0.0, 0
        self.triggers, self.event_state = triggers or [], {}

    def reset(self):
        self.data.clear()
        self.random = np.random.default_rng(self.seed)
        self.tick, self.origin_tick, self.activation, self.initialized = 0, 0, None, False
        self.event_state.clear()

    def close(self):
        self.data.clear()
        self.initialized = False

    def fork(self):
        from copy import deepcopy

        result = SceneRuntime(
            self.kind, self.params, self.seed, self.performance, self.palette, self.palette_space
        )
        result.data = deepcopy(self.data)
        result.tick = self.tick
        result.initialized = self.initialized
        result.random.bit_generator.state = deepcopy(self.random.bit_generator.state)
        result.triggers, result.event_state = deepcopy(self.triggers), deepcopy(self.event_state)
        return result

    def frame(
        self, context, resolution, fit="fit", palette=None, modulation=None, feature_at=None, profiles=()
    ):
        started = time.perf_counter()
        parameters = dict(self.params)
        for name, value in (modulation or {}).items():
            if name in CATALOG[self.kind]["modulatable"]:
                _, low, high = CATALOG[self.kind]["parameters"][name]
                parameters[name] = float(np.clip(value, low, high))
        spec = CATALOG[self.kind]
        base = (
            self.performance.generator_resolution
            if spec["category"] == "analytical"
            else self.performance.simulation_resolution
        )
        scale = min(1, resolution[0] / base[0], resolution[1] / base[1])
        size = (max(16, round(base[0] * scale)), max(16, round(base[1] * scale)))
        if self.data.get("size", size) != size:
            self.reset()
        self.data["size"] = size
        palette = ColorStops(palette or self.palette, self.palette_space)
        if spec["category"] == "analytical":
            from .analytical import render
            from .profiles import apply

            image = render(
                self.kind,
                size,
                apply(self.kind, parameters, context, profiles),
                context,
                self.data,
                palette,
                self.seed,
            )
        else:
            from .simulation import initialize, render, step

            if not self.initialized:
                initialize(self.kind, size, parameters, self.data, self.random)
                self.initialized = True
            if self.activation != context.activation:
                self.origin_tick, self.activation = self.tick, context.activation
            target = self.origin_tick + int(
                np.floor(context.local_time * self.performance.simulation_hz + 1e-7)
            )
            if target < self.tick:
                raise ValueError("Simulation time moved backwards; reset or reconstruct the scene")
            while self.tick < target:
                step_time = (self.tick - self.origin_tick + 1) / self.performance.simulation_hz
                absolute = context.time - context.local_time + step_time
                audio = feature_at(absolute) if feature_at else context.audio
                simulated = replace(context, time=absolute, local_time=step_time, audio=audio)
                actions = []
                for ordinal, trigger in enumerate(self.triggers):
                    state = self.event_state.setdefault(ordinal, {"armed": True, "time": -1e9, "track": None})
                    if trigger["source"] == "track":
                        track = context.track.get("index") if context.track else None
                        crossing = state["track"] != track
                        state["track"] = track
                    else:
                        value = audio.get("rms" if trigger["source"] == "energy" else trigger["source"], 0)
                        crossing = state["armed"] and value >= trigger["threshold"]
                        if value < trigger["threshold"] - trigger["hysteresis"]:
                            state["armed"] = True
                        elif crossing:
                            state["armed"] = False
                    if (
                        crossing
                        and absolute - state["time"] >= trigger["cooldown"]
                        and self.random.random() < trigger["probability"]
                    ):
                        actions.append(trigger["action"])
                        state["time"] = absolute
                if "reset" in actions:
                    initialize(self.kind, size, parameters, self.data, self.random)
                simulated = replace(simulated, actions=tuple(actions))
                from .profiles import apply

                step(
                    self.kind,
                    size,
                    apply(self.kind, parameters, simulated, profiles),
                    simulated,
                    self.data,
                    self.random,
                    1 / self.performance.simulation_hz,
                    palette,
                )
                self.tick += 1
            from .profiles import apply

            image = render(
                self.kind, size, apply(self.kind, parameters, context, profiles), context, self.data, palette
            )
        frame = np.clip(np.nan_to_num(image) * 255, 0, 255).astype(np.uint8)
        result = fit_frame(frame, resolution, fit, self.performance.upscale)
        self.seconds += time.perf_counter() - started
        self.calls += 1
        return result


class SceneStore:
    def __init__(self, config, output, features=None):
        self.performance = Performance.model_validate(config.get("performance", {}))
        self.output, self.features = output, features or {}
        self.profiles = config.get("audio_profiles", [])
        self.space = config.get("palette_space", "rgb")
        self.cache = OrderedDict()
        self.timings = {}

    def close(self):
        for runtime in self.cache.values():
            runtime.close()
        self.cache.clear()

    def frame(self, clip, index, context, video=None):
        from ..audio import at

        scene = clip["scene"]
        key = f"{scene['id']}:{clip['start']}"
        if key not in self.cache:
            previous = (
                next(
                    (
                        runtime
                        for name, runtime in reversed(self.cache.items())
                        if name.startswith(scene["id"] + ":")
                    ),
                    None,
                )
                if scene.get("retain_state")
                else None
            )
            runtime = (
                previous.fork()
                if previous is not None
                else SceneRuntime(
                    scene["type"],
                    scene["params"],
                    scene["seed"],
                    self.performance,
                    scene["palette"],
                    self.space,
                )
            )
            while len(self.cache) >= self.performance.state_cache:
                _, old = self.cache.popitem(last=False)
                old.close()
            runtime.triggers = scene.get("triggers", [])
            self.cache[key] = runtime
        runtime = self.cache[key]
        self.cache.move_to_end(key)
        ctx = SceneContext(
            index / context.fps,
            (index - clip["start"]) / context.fps,
            index,
            context.fps,
            context.audio,
            video,
            context.track,
            getattr(context, "signals", {}),
            clip["start"],
        )
        before = runtime.seconds
        result = runtime.frame(
            ctx,
            self.output.resolution,
            self.output.fit,
            scene["palette"],
            getattr(context, "scene_modulation", {}).get(scene["id"], {}),
            feature_at=lambda t: at(self.features, t),
            profiles=self.profiles,
        )
        seconds, calls = self.timings.get(scene["type"], (0, 0))
        self.timings[scene["type"]] = seconds + runtime.seconds - before, calls + 1
        return result


def stable_seed(seed, name):
    return int.from_bytes(hashlib.sha256(f"{seed}:scene:{name}".encode()).digest()[:8], "big") & (2**63 - 1)
