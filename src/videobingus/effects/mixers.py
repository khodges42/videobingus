import cv2
import numpy as np

from .recapture import retain
from .signal_math import luma, threshold, to_rgb, to_ycc


def mix(kind, source_a, source_b, p, ctx, state, progress=None):
    if source_b is None:
        raise ValueError(f"{kind} requires a second current or delayed input")
    h, w = source_a.shape[:2]
    if source_b.shape[:2] != (h, w):
        source_b = cv2.resize(source_b, (w, h))
    a = source_a.astype(np.float32) / 255
    b = source_b[..., :3].astype(np.float32) / 255
    amount = float(np.clip(p["mix"] if progress is None else progress, 0, 1))
    strength = np.sin(np.pi * amount)
    if kind in {"analog_crossfade", "dirty_crossfade"}:
        if kind == "dirty_crossfade":
            lines = np.arange(h, dtype=np.float32)
            shifts = np.sin(lines / max(1, h) * 15 + ctx.time * 4) * p["tearing"] * strength
            x = np.broadcast_to(np.arange(w, dtype=np.float32), (h, w)) + shifts[:, None]
            y = np.broadcast_to(lines[:, None], (h, w)) + p["roll"] * h * strength * np.sin(ctx.time * 3)
            b = cv2.remap(
                b, x.astype(np.float32), y.astype(np.float32), cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP
            )
        ycca, yccb = to_ycc(a), to_ycc(b)
        fader = amount ** p["response"]
        if kind == "dirty_crossfade":
            phase = p["chroma_error"] * strength * np.sin(ctx.time * 6 + np.arange(h)[:, None] * 0.09)
            cb, cr = yccb[..., 1].copy(), yccb[..., 2].copy()
            yccb[..., 1] = cb * np.cos(phase) - cr * np.sin(phase)
            yccb[..., 2] = cb * np.sin(phase) + cr * np.cos(phase)
        chroma_fader = np.clip(fader + p["chroma_offset"] * strength, 0, 1)
        weights = np.array([fader, chroma_fader, chroma_fader], dtype=np.float32)
        out = ycca * ((1 - weights) * p["gain_a"] + p["bleed"] * strength)
        out += yccb * (weights * p["gain_b"] + p["bleed"] * strength)
        level = p["clip_level"] * (1 - 0.25 * strength if kind == "dirty_crossfade" else 1)
        out = np.clip(to_rgb(out), 0, max(0.01, level))
    elif kind == "scanline_mixer":
        group = max(1, round(p["group"]))
        rows = np.arange(h) // group
        pattern = p["pattern"]
        phase = ctx.time * p["rate"]
        if pattern == "alternating":
            voltage = (rows % 2) * 0.7 + 0.15
        elif pattern == "random":
            random = np.random.default_rng(
                np.random.SeedSequence([ctx.index // max(1, round(ctx.fps / max(0.01, p["rate"]))), 123])
            )
            voltage = random.random(int(rows.max()) + 1)[rows]
        elif pattern == "bands":
            voltage = (rows % 7) / 7
        elif pattern == "moving":
            voltage = (np.arange(h) / h + phase) % 1
        else:
            voltage = 0.5 + 0.5 * np.sin(rows * 0.8 + phase * 2 * np.pi)
        mask = threshold(amount - voltage, 0, p["softness"])[:, None, None]
        out = a * (1 - mask) + b * mask
    elif kind == "luma_key":
        signal = luma(a)
        if p["mask"] != "source":
            y, x = np.indices((h, w), dtype=np.float32)
            if p["mask"] == "horizontal_ramp":
                signal = x / w
            elif p["mask"] == "vertical_ramp":
                signal = y / h
            else:
                coordinate = np.hypot(x / w - 0.5, y / h - 0.5) if p["mask"] == "rings" else x / w
                signal = 0.5 + 0.5 * np.sin(coordinate * p["frequency"] * 2 * np.pi + ctx.time)
        level = p["threshold"] if progress is None else 1 - amount
        mask = threshold(signal * p["gain"] + p["bias"], level, p["softness"])[..., None]
        if p["invert"] >= 0.5:
            mask = 1 - mask
        out = a * (1 - mask) + b * mask
    elif kind == "chroma_key":
        hsv = np.float32([[[p["key_hue"], p["key_saturation"], 1]]])
        key = to_ycc(cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB))[0, 0, 1:]
        distance = np.linalg.norm(to_ycc(a)[..., 1:] - key, axis=2)
        tolerance = p["tolerance"] if progress is None else amount * 1.5
        mask = 1 - threshold(distance, tolerance, p["softness"])
        cleaned = a * (1 - p["spill"] * mask[..., None])
        out = cleaned * (1 - mask[..., None]) + b * mask[..., None]
    elif kind == "analog_logic":
        aa, bb = (a, b) if p["channels"] == "rgb" else (to_ycc(a), to_ycc(b))
        operation = p["operation"]
        operations = {
            "minimum": np.minimum,
            "maximum": np.maximum,
            "difference": lambda x, y: x - y,
            "absolute_difference": lambda x, y: np.abs(x - y),
            "addition": lambda x, y: x + y,
            "multiplication": lambda x, y: x * y,
            "comparison": lambda x, y: (x >= y).astype(np.float32),
            "rectification": lambda x, y: np.abs(x + y - 1),
        }
        processed = operations[operation](aa, bb) * p["gain"] + p["bias"]
        if p["channels"] == "luma":
            aa[..., 0] = processed[..., 0]
            processed = to_rgb(aa)
        elif p["channels"] == "chroma":
            aa[..., 1:] = processed[..., 1:]
            processed = to_rgb(aa)
        out = a * (1 - amount) + processed * amount
    elif kind == "feedback_transition":
        history = state.data.get("mixer_history")
        old = history[-1] if history else a
        matrix = cv2.getRotationMatrix2D((w / 2, h / 2), p["rotation"], p["zoom"])
        old = cv2.warpAffine(old, matrix, (w, h)) * p["gain"] * p["decay"]
        if p["blur"] > 0.05:
            old = cv2.GaussianBlur(old, (0, 0), p["blur"])
        out = np.clip(old * (1 - amount) + b * amount, 0, 1)
        retain(state, "mixer_history", out, 1)
    elif kind == "glitch_switch":
        group = max(2, round(p["group"]))
        tick = int(ctx.time * p["rate"])
        random = np.random.default_rng(np.random.SeedSequence([tick, 931]))
        if p["pattern"] == "luma":
            voltage = luma(a)
        else:
            gh, gw = (max(1, h // group), 1 if p["pattern"] == "bands" else max(1, w // group))
            voltage = cv2.resize(
                random.random((gh, gw)).astype(np.float32), (w, h), interpolation=cv2.INTER_NEAREST
            )
        mask = (voltage < np.clip(amount + np.sin(ctx.time * 7) * p["instability"] * strength, 0, 1))[
            ..., None
        ]
        out = np.where(mask, b, a)
    else:
        raise ValueError(f"Unknown mixer: {kind}")
    if progress is not None:
        if amount <= 0:
            out = a
        elif amount >= 1:
            out = b
    elif kind in {"luma_key", "chroma_key"}:
        out = a * (1 - amount) + out * amount
    return np.clip(out * 255, 0, 255).astype(np.uint8)
