import hashlib
import time
from dataclasses import dataclass, field

import cv2
import numpy as np


def pixels(frame):
    return np.clip(frame, 0, 255).astype(np.uint8)


@dataclass
class Context:
    index: int
    fps: float
    clip_time: float
    track: dict | None
    audio: dict
    random: np.random.Generator
    clip_id: int = 0
    track_time: float = 0
    transition_progress: float = 0
    inputs: dict = field(default_factory=dict)
    previous_inputs: dict = field(default_factory=dict)
    raw_frame: np.ndarray | None = None
    source_b: np.ndarray | None = None
    activation_time: float = 0
    activation_end: float = 0
    layer: str = "composite"
    seed: int = 420
    performance: dict | None = None
    palette: str | list = "deep_space"
    signals: dict = field(default_factory=dict)
    scene_modulation: dict = field(default_factory=dict)
    generator_id: str = ""
    visual_intensity: float = 1
    preserve_palette: bool = False

    @property
    def time(self):
        return self.index / self.fps


@dataclass
class State:
    previous: np.ndarray | None = None
    held: np.ndarray | None = None
    held_at: int = -1
    maps: dict = field(default_factory=dict)
    data: dict = field(default_factory=dict)


def crt(frame, params, context, state):
    h, w = frame.shape[:2]
    key = (h, w, params["curvature"], params["vignette"])
    if key not in state.maps:
        y, x = np.mgrid[-1 : 1 : complex(h), -1 : 1 : complex(w)].astype(np.float32)
        radius = x * x + y * y
        factor = 1 + params["curvature"] * radius
        state.maps[key] = (
            (x * factor + 1) * (w - 1) / 2,
            (y * factor + 1) * (h - 1) / 2,
            np.clip(1 - params["vignette"] * radius / 2, 0, 1)[..., None],
        )
        if len(state.maps) > 4:
            state.maps = {key: state.maps[key]}
    mx, my, vignette = state.maps[key]
    out = cv2.remap(frame, mx, my, cv2.INTER_LINEAR).astype(np.float32)
    out[1::2] *= 1 - params["scanlines"]
    out *= vignette
    out += cv2.GaussianBlur(out, (0, 0), 2) * params["bloom"]
    out[..., 1] *= 1.025
    if params["refresh"]:
        band = np.sin(np.arange(h) * 0.02 - context.time * 8) * params["refresh"] * 0.15
        out *= (1 + band)[:, None, None]
    return pixels(out)


def apply(kind, frame, p, ctx, state):
    from .synthesis_specs import MIXERS, SIGNAL_PROCESSORS

    if kind in {"simulated_datamosh", "digital_corruption"}:
        from .digital import process

        return process(kind, frame, p, ctx, state)

    if kind in {
        "spatial_synth",
        "analog_colorizer",
        "oscilloscope_xy",
        "vectorscope",
        "waveform_monitor",
        "scan_displacement",
    }:
        from .synthesis import process

        return process(kind, frame, p, ctx, state)

    if kind in SIGNAL_PROCESSORS:
        from .analog_signal import process

        return process(kind, frame, p, ctx, state)

    if kind in MIXERS:
        from .mixers import mix

        return mix(kind, frame, ctx.source_b, p, ctx, state)
    if kind in {"optical_feedback", "display", "virtual_camera"}:
        from .recapture import process

        return process(kind, frame, p, ctx, state)
    h, w = frame.shape[:2]
    random = ctx.random
    if kind == "hue_shift":
        hsv = cv2.cvtColor(frame, cv2.COLOR_RGB2HSV)
        hsv[..., 0] = (hsv[..., 0].astype(float) + p["degrees"] / 2) % 180
        return cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB)
    if kind == "color":
        gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)[..., None]
        return pixels(((frame.astype(float) - gray) * p["saturation"] + gray - 127.5) * p["contrast"] + 127.5)
    if kind == "negative":
        return 255 - frame
    if kind == "posterize":
        levels = max(2, round(p["levels"]))
        return pixels(np.round(frame.astype(float) / 255 * (levels - 1)) * 255 / (levels - 1))
    if kind == "edges":
        edges = cv2.Canny(frame, p["threshold"], min(255, p["threshold"] * 2))
        return np.repeat(edges[..., None], 3, axis=2)
    if kind == "rgb_shift":
        out = frame.copy()
        out[..., 0] = np.roll(frame[..., 0], round(p["pixels"]), axis=1)
        out[..., 2] = np.roll(frame[..., 2], -round(p["pixels"]), axis=1)
        return out
    if kind == "pixelate":
        size = max(1, round(p["size"]))
        return cv2.resize(
            cv2.resize(frame, (max(1, w // size), max(1, h // size))), (w, h), interpolation=cv2.INTER_NEAREST
        )
    if kind == "mirror":
        return np.ascontiguousarray(frame[:, ::-1])
    if kind == "kaleidoscope":
        out = frame.copy()
        half = w // 2
        out[:, w - half :] = out[:, :half][:, ::-1]
        half = h // 2
        out[h - half :] = out[:half][::-1]
        return out
    if kind == "wave":
        y, x = np.indices((h, w), dtype=np.float32)
        x += np.sin(y / h * np.pi * 2 * p["frequency"] + ctx.time * p["speed"]) * p["amplitude"]
        return cv2.remap(frame, x, y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    if kind in {"band_displace", "tracking_error"}:
        out = frame.copy()
        for _ in range(round(p["bands"])):
            y = int(random.integers(h))
            height = int(random.integers(1, max(2, h // 12)))
            out[y : y + height] = np.roll(
                out[y : y + height], round(random.uniform(-p["pixels"], p["pixels"])), axis=1
            )
        if kind == "tracking_error":
            y = int((ctx.time * 0.3 % 1) * h)
            out[y : y + max(1, h // 20)] = random.integers(
                0, 256, out[y : y + max(1, h // 20)].shape, dtype=np.uint8
            )
        return out
    if kind == "vhs":
        ycc = cv2.cvtColor(frame, cv2.COLOR_RGB2YCrCb).astype(np.float32)
        chroma = cv2.resize(ycc[..., 1:], (max(1, w // 6), max(1, h // 2)))
        chroma = cv2.resize(chroma, (w, h))
        bleed = max(1, round(p["chroma_bleed"]) * 2 + 1)
        ycc[..., 1:] = np.roll(cv2.blur(chroma, (bleed, 1)), round(p["chroma_bleed"]), axis=1)
        ycc[..., 0] += random.normal(0, p["noise"], (h, w))
        ycc[..., 1:] += random.normal(0, p["noise"] * 0.5, (h, w, 2))
        out = cv2.cvtColor(pixels(ycc), cv2.COLOR_YCrCb2RGB)
        shifts = np.rint(random.normal(0, p["horizontal_jitter"], h)).astype(int)
        out = out[np.arange(h)[:, None], (np.arange(w)[None, :] - shifts[:, None]) % w]
        out = pixels(out * (1 - p["ghosting"]) + np.roll(out, max(1, w // 80), axis=1) * p["ghosting"])
        if random.random() < p["dropout"]:
            y = int(random.integers(h))
            out[y : y + max(1, h // 100)] = random.integers(100, 256, dtype=np.uint8)
        bottom = round(h * p["head_noise"])
        if bottom:
            out[-bottom:] = pixels(out[-bottom:] * 0.6 + random.uniform(0, 100, (bottom, w, 1)))
        return out
    if kind == "crt":
        return crt(frame, p, ctx, state)
    if kind == "camcorder":
        out = crt(
            frame,
            {"scanlines": 0.16, "curvature": 0.08, "vignette": 0.3, "bloom": 0.1, "refresh": 0.8},
            ctx,
            state,
        )
        shift = p["perspective"] * min(w, h)
        source = np.float32([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]])
        destination = source + np.float32([[shift, 0], [-shift, shift], [0, -shift], [shift, 0]])
        destination += np.float32([np.sin(ctx.time * 1.3), np.cos(ctx.time * 0.9)]) * p["movement"]
        out = cv2.warpPerspective(out, cv2.getPerspectiveTransform(source, destination), (w, h))
        return pixels(
            out.astype(float) * (1 + 0.04 * np.sin(ctx.time * 2)) + random.normal(0, p["noise"], out.shape)
        )
    if kind in {"block_glitch", "datamosh"}:
        out = frame.copy()
        source = state.previous if kind == "datamosh" and state.previous is not None else frame
        count = round(p["blocks"])
        amount = p["displacement"]
        for _ in range(count):
            y, x = int(random.integers(h)), int(random.integers(w))
            bh, bw = max(1, h // 8), max(1, w // 6)
            block = source[y : y + bh, x : x + bw]
            shifted = np.roll(block, round(random.uniform(-amount, amount)), axis=1)
            if kind == "datamosh":
                shifted = pixels(block * p["persistence"] + shifted * (1 - p["persistence"]))
            elif random.random() < p["smear"]:
                shifted = np.repeat(shifted[:, :1], shifted.shape[1], axis=1)
            out[y : y + bh, x : x + bw] = shifted
        if kind == "block_glitch":
            out[..., 0] = np.roll(out[..., 0], max(1, round(amount / 8)), axis=1)
        else:
            state.previous = out.copy()
        return out
    if kind == "frame_hold":
        interval = max(1, round(p["seconds"] * ctx.fps))
        if state.held is None or ctx.index - state.held_at >= interval:
            state.held, state.held_at = frame.copy(), ctx.index
        return state.held.copy()
    if kind == "temporal_blend":
        out = (
            frame
            if state.previous is None
            else pixels(frame * (1 - p["decay"]) + state.previous * p["decay"])
        )
        state.previous = out.copy()
        return out
    if kind == "feedback":
        if state.previous is None:
            out = frame.copy()
        else:
            transform = cv2.getRotationMatrix2D((w / 2, h / 2), p["rotation"], p["scale"])
            transform[:, 2] += [p["x"], p["y"]]
            history = cv2.warpAffine(state.previous, transform, (w, h))
            out = pixels(frame * (1 - p["opacity"]) + history * p["opacity"] * p["decay"])
        state.previous = out.copy()
        return out
    raise ValueError(f"Unimplemented effect: {kind}")


class EffectEngine:
    def __init__(self, activations: list[dict], fps: float, seed: int, profile=False):
        self.pending = iter(sorted(activations, key=lambda e: (e["start"], e["order"], e["id"])))
        self.next = next(self.pending, None)
        self.active = []
        self.index = -1
        self.streams = {
            e["id"]: int.from_bytes(hashlib.sha256(e["id"].encode()).digest()[:8], "big") for e in activations
        }
        self.states: dict[str, State] = {}
        self.fps, self.seed = fps, seed
        self.seen = {}
        self.boundaries = {}
        self.activations = {}
        self.profile, self.timings = profile, {}

    def __enter__(self):
        return self

    def __exit__(self, *error):
        self.states.clear()

    def advance(self, index):
        if self.index == index:
            return
        for effect in self.active:
            if effect["end"] <= index and effect.get("inactive") == "clear":
                self.states.pop(effect["id"], None)
        self.active = [e for e in self.active if e["end"] > index]
        while self.next and self.next["start"] <= index:
            if self.next["end"] > index:
                self.active.append(self.next)
            self.next = next(self.pending, None)
        self.active.sort(key=lambda e: (e["order"], e["id"]))
        self.index = index

    def process(self, frame, context, layer="composite", modulation=None):
        from .analog_signal import process_signal
        from .signal_math import SignalFrame
        from .synthesis_specs import SIGNAL_PROCESSORS

        modulation = modulation or {}
        packet = None
        packet_height = None
        self.advance(context.index)
        live = {e["id"] for e in self.active}
        chain = self.active + [
            e for identity, e in self.seen.items() if identity not in live and e.get("inactive") == "update"
        ]
        for effect in sorted(chain, key=lambda e: (e["order"], e["id"])):
            if effect["layer"] != layer:
                continue
            identity = effect["id"]
            self.seen[identity] = effect
            track = context.track.get("index") if context.track else None
            previous_clip, previous_track, previous_index = self.boundaries.get(identity, (None, None, -1))
            reset_on = effect.get("reset_on", [])
            activation = self.activations.get(identity) != effect["start"]
            reset = (
                (not effect["persist"] and context.clip_time == 0)
                or ("activation" in reset_on and activation)
                or ("clip" in reset_on and context.clip_id != previous_clip)
                or ("track" in reset_on and track != previous_track)
                or any(
                    previous_index < round(t * self.fps) <= context.index
                    for t in effect.get("reset_times", [])
                )
            )
            if identity not in self.states or reset:
                self.states[identity] = State()
            self.activations[identity] = effect["start"]
            self.boundaries[identity] = context.clip_id, track, context.index
            parameters = dict(effect["params"])
            parameters.update(modulation.get(identity, {}))
            if (
                effect["type"] == "analog_colorizer"
                and context.preserve_palette
                and isinstance(context.palette, list)
            ):
                parameters["palette"] = context.palette
            from .registry import PARAMETERS

            for name, (_, low, high) in PARAMETERS[effect["type"]].items():
                parameters[name] = float(np.clip(parameters[name], low, high))
            intensity = float(np.clip(parameters.pop("intensity", effect["intensity"]), 0, 1))
            intensity *= context.visual_intensity
            if identity not in live:
                intensity = 0
            elapsed = (context.index - effect["start"]) / self.fps
            remaining = (effect["end"] - context.index) / self.fps
            if effect["attack"]:
                intensity *= min(1, elapsed / effect["attack"])
            if effect["release"]:
                intensity *= min(1, remaining / effect["release"])
            context.random = np.random.default_rng(
                np.random.SeedSequence([self.seed, self.streams[identity], context.index])
            )
            context.activation_time = effect["start"] / self.fps
            context.activation_end = effect["end"] / self.fps
            context.layer = layer
            reference = effect.get("input_b")
            context.source_b = None
            if reference:
                inputs = context.previous_inputs if reference.startswith("previous:") else context.inputs
                name = reference.removeprefix("previous:")
                if name not in inputs:
                    if reference.startswith("previous:"):
                        context.source_b = np.zeros_like(frame)
                    else:
                        raise ValueError(f"Unavailable input {reference!r} for effect {identity}")
                else:
                    context.source_b = inputs[name]
            started = time.perf_counter() if self.profile else 0
            if effect["type"] in SIGNAL_PROCESSORS:
                height = parameters["internal_height"]
                if packet is None or packet_height != height:
                    if packet is not None:
                        frame = packet.rgb()
                    packet = SignalFrame.from_rgb(frame, height)
                    packet_height = height
                result = process_signal(
                    effect["type"], packet.values, parameters, context, self.states[identity]
                )
                packet.values = packet.values * (1 - intensity) + result * intensity
            else:
                if packet is not None:
                    frame, packet = packet.rgb(), None
                result = apply(effect["type"], frame, parameters, context, self.states[identity])
                frame = pixels(
                    frame.astype(np.float32) * (1 - intensity) + result.astype(np.float32) * intensity
                )
            if self.profile:
                seconds, calls = self.timings.get(identity, (0, 0))
                self.timings[identity] = seconds + time.perf_counter() - started, calls + 1
        return packet.rgb() if packet is not None else frame
