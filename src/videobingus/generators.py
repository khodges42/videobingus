import cv2
import numpy as np


def validate_generator_params(kind, params):
    from .effects.registry import validate_params
    from .effects.synthesis import SPATIAL_PATTERNS, TEST_PATTERNS

    if kind in SPATIAL_PATTERNS:
        allowed = {
            "frequency",
            "phase",
            "orientation",
            "amplitude",
            "offset",
            "drift",
            "frequency_b",
            "waveform",
            "internal_height",
        }
        if set(params) - allowed:
            raise ValueError(f"Unknown generator parameter: {sorted(set(params) - allowed)}")
        validate_params("spatial_synth", params)
    elif kind in TEST_PATTERNS:
        if params:
            raise ValueError(f"Test pattern {kind} does not accept parameters")
    elif kind in {"oscilloscope_xy", "vectorscope", "waveform_monitor"}:
        validate_params(kind, params)
    elif params:
        raise ValueError(f"Generator {kind} does not accept parameters")


def generate(kind, size, context, params=None, state=None):
    from .effects.engine import State
    from .effects.registry import defaults
    from .effects.synthesis import SPATIAL_PATTERNS, TEST_PATTERNS, spatial

    params = params or {}
    state = state or State()
    width, height = size
    random = context.random
    out = np.zeros((height, width, 3), dtype=np.uint8)
    if kind in SPATIAL_PATTERNS:
        from .effects.recapture import resize_internal

        spec = {**defaults("spatial_synth"), "pattern": kind, "luma_phase": 0, **params}
        signal = spatial(resize_internal(out, spec["internal_height"]).shape, spec, context, state)
        result = np.repeat(np.clip(signal * 255, 0, 255).astype(np.uint8)[..., None], 3, axis=2)
        return cv2.resize(result, (width, height))
    if kind in {"oscilloscope_xy", "vectorscope", "waveform_monitor"}:
        from .effects.synthesis import process

        source = context.raw_frame if context.raw_frame is not None else out
        source = cv2.resize(source, (width, height))
        return process(kind, source, {**defaults(kind), **params}, context, state)
    if kind in TEST_PATTERNS:
        y, x = np.indices((height, width))
        if kind == "grayscale_ramp":
            out[:] = np.rint(x / max(1, width - 1) * 255).astype(np.uint8)[..., None]
        elif kind == "sync_pattern":
            out[:] = 100
            out[:, : max(1, width // 20)] = 0
            out[:: max(1, height // 12)] = 240
            out[: max(1, height // 20)] = 0
        else:
            mask = (x % max(2, width // 12) < 1) | (y % max(2, height // 9) < 1)
            out[mask] = [220, 240, 220]
            if kind == "alignment_grid":
                cv2.circle(out, (width // 2, height // 2), min(width, height) // 3, (200, 200, 200), 1)
        return out
    if kind == "black":
        return out
    if kind == "blue_vcr":
        out[..., 2] = 175
    elif kind in {"television_static", "signal_loss"}:
        noise = random.integers(0, 256, (max(1, height // 2), max(1, width // 2)), dtype=np.uint8)
        noise = cv2.resize(noise, (width, height), interpolation=cv2.INTER_NEAREST)
        out = np.repeat(noise[..., None], 3, axis=2)
        if kind == "signal_loss":
            shift = round(np.sin(context.time * 11) * height / 3)
            out = np.roll(out, shift, axis=0)
            y = int((context.time * 0.4 % 1) * height)
            out[y : y + max(1, height // 5)] //= 5
    elif kind == "color_bars":
        colors = np.array(
            [
                [235, 235, 235],
                [235, 235, 16],
                [16, 235, 235],
                [16, 235, 16],
                [235, 16, 235],
                [235, 16, 16],
                [16, 16, 235],
            ],
            dtype=np.uint8,
        )
        out[:] = colors[np.minimum(6, np.arange(width) * 7 // width)]
    elif kind == "waveform":
        samples = context.audio.get("waveform", [])
        if len(samples):
            samples = np.interp(np.linspace(0, len(samples) - 1, width), np.arange(len(samples)), samples)
            points = np.column_stack([np.arange(width), height / 2 - samples * height * 0.45]).astype(
                np.int32
            )
            cv2.polylines(out, [points], False, (120, 240, 190), max(1, height // 180), cv2.LINE_AA)
    elif kind == "spectrum":
        bins = context.audio.get("spectrum", [])
        if len(bins):
            for i, value in enumerate(bins):
                x0, x1 = i * width // len(bins), (i + 1) * width // len(bins)
                cv2.rectangle(
                    out, (x0, height - 1), (max(x0, x1 - 2), int(height * (1 - value))), (120, 220, 170), -1
                )
    else:
        raise ValueError(f"Unknown generator: {kind}")
    return out
