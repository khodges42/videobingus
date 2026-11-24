import math

import cv2
import numpy as np

from .recapture import coordinates, prepare_state, resize_internal, retain
from .signal_math import luma, to_rgb, to_ycc


def motion_field(image, p, ctx, state):
    gray = cv2.cvtColor(np.clip(image * 255, 0, 255).astype(np.uint8), cv2.COLOR_RGB2GRAY)
    previous = state.data.get("motion_gray")
    same_scene = state.data.get("motion_clip") == ctx.clip_id
    if previous is None or previous.shape != gray.shape or not same_scene:
        flow = np.zeros((*gray.shape, 2), dtype=np.float32)
    else:
        flow = cv2.calcOpticalFlowFarneback(previous, gray, None, 0.5, 3, 15, 3, 5, 1.2, 0)
    state.data["motion_gray"], state.data["motion_clip"] = gray, ctx.clip_id
    h, w = gray.shape
    block = max(4, round(p["block_size"]))
    bw, bh = max(1, math.ceil(w / block)), max(1, math.ceil(h / block))
    field = cv2.resize(flow, (bw, bh), interpolation=cv2.INTER_AREA)
    field = np.round(field / p["quantization"]) * p["quantization"]
    if p["corruption"]:
        random = np.random.default_rng(
            np.random.SeedSequence(
                [state.data.setdefault("motion_seed", int(ctx.random.integers(2**31))), ctx.index // 4]
            )
        )
        errors = random.random((bh, bw)) < p["corruption"]
        field[errors] += random.uniform(-p["max_displacement"], p["max_displacement"], (int(errors.sum()), 2))
    field = cv2.resize(field, (w, h), interpolation=cv2.INTER_NEAREST) * p["motion_amplification"]
    return np.clip(field, -p["max_displacement"], p["max_displacement"])


def datamosh(frame, p, ctx, state):
    h, w = frame.shape[:2]
    motion_source = (
        ctx.raw_frame if ctx.raw_frame is not None else np.clip(frame * 255, 0, 255).astype(np.uint8)
    )
    motion_source = cv2.resize(motion_source, (w, h)).astype(np.float32) / 255
    flow = motion_field(motion_source, p, ctx, state)
    reference = state.data.get("mosh_reference")
    if reference is None:
        seed = ctx.previous_inputs.get(ctx.layer)
        reference = cv2.resize(seed, (w, h)).astype(np.float32) / 255 if seed is not None else frame.copy()
        state.data["frozen_reference"] = reference.copy()
    if p["mode"] == "frozen":
        reference = state.data["frozen_reference"]
    elif p["mode"] == "accumulate":
        flow = np.clip(
            flow + state.data.get("last_flow", 0) * 0.7, -p["max_displacement"], p["max_displacement"]
        )
    state.data["last_flow"] = flow.copy()
    y, x = coordinates(state, frame.shape)
    warped = cv2.remap(
        reference,
        (x - flow[..., 0]).astype(np.float32),
        (y - flow[..., 1]).astype(np.float32),
        cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REFLECT,
    )
    block = max(4, round(p["block_size"]))
    gh, gw = max(1, math.ceil(h / block)), max(1, math.ceil(w / block))
    refresh_probability = p["refresh_probability"]
    if p["mode"] == "frozen":
        refresh_probability = 0
    refresh = (ctx.random.random((gh, gw)) < refresh_probability).astype(np.uint8)
    size = max(1, round(p["refresh_size"]))
    if size > 1:
        refresh = cv2.dilate(refresh, np.ones((size, size), dtype=np.uint8))
    refresh = cv2.resize(refresh, (w, h), interpolation=cv2.INTER_NEAREST)[..., None]
    out = warped * p["persistence"] + frame * (1 - p["persistence"])
    out = np.where(refresh > 0, frame, out)
    if p["color_retention"] < 1:
        signal = to_ycc(out)
        signal[..., 1:] = signal[..., 1:] * p["color_retention"] + to_ycc(frame)[..., 1:] * (
            1 - p["color_retention"]
        )
        out = to_rgb(signal)
    recovery = p["recovery"]
    if p["mode"] == "recovery" and ctx.activation_end > ctx.activation_time:
        progress = (ctx.time - ctx.activation_time) / (ctx.activation_end - ctx.activation_time)
        recovery = max(recovery, float(np.clip((progress - 0.6) / 0.4, 0, 1)))
    out = out * (1 - recovery) + frame * recovery
    state.data["mosh_reference"] = np.clip(out, 0, 1).copy()
    return out


def corruption(frame, p, ctx, state):
    h, w = frame.shape[:2]
    mode, amount = p["mode"], p["amount"]
    block = max(2, round(p["block_size"]))
    gh, gw = max(1, math.ceil(h / block)), max(1, math.ceil(w / block))
    mask = cv2.resize(
        (ctx.random.random((gh, gw)) < amount).astype(np.float32), (w, h), interpolation=cv2.INTER_NEAREST
    )[..., None]
    history = state.data.get("digital_history")
    previous = history[-1] if history else frame
    delay = max(1, round(p["delay"]))
    out = frame.copy()
    if mode == "macroblock":
        dx = ctx.random.uniform(-p["displacement"], p["displacement"], (gh, gw)).astype(np.float32)
        dy = ctx.random.uniform(-p["displacement"], p["displacement"], (gh, gw)).astype(np.float32)
        y, x = coordinates(state, frame.shape)
        shifted = cv2.remap(
            frame,
            x + cv2.resize(dx, (w, h), interpolation=cv2.INTER_NEAREST),
            y + cv2.resize(dy, (w, h), interpolation=cv2.INTER_NEAREST),
            cv2.INTER_NEAREST,
            borderMode=cv2.BORDER_WRAP,
        )
        out = np.where(mask > 0, shifted, frame)
    elif mode == "motion_field":
        from .registry import defaults

        params = defaults("simulated_datamosh")
        params.update(block_size=p["block_size"], corruption=amount, max_displacement=p["displacement"])
        flow = motion_field(frame, params, ctx, state)
        y, x = coordinates(state, frame.shape)
        out = cv2.remap(
            frame, x - flow[..., 0], y - flow[..., 1], cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT
        )
    elif mode in {"block_persist", "partial_replace"}:
        out = np.where(mask > 0, previous, frame)
    elif mode == "pixel_sort":
        brightness = luma(frame)
        order = np.argsort(brightness, axis=1, kind="stable")
        sorted_pixels = np.take_along_axis(frame, order[..., None], axis=1)
        out = np.where((brightness >= p["threshold"])[..., None] * mask > 0, sorted_pixels, frame)
    elif mode == "horizontal_streak":
        streak = np.repeat(frame[:, w // 2 : w // 2 + 1], w, axis=1)
        out = frame * (1 - mask) + streak * mask
    elif mode == "vertical_streak":
        streak = np.repeat(frame[h // 2 : h // 2 + 1], h, axis=0)
        out = frame * (1 - mask) + streak * mask
    elif mode == "bit_plane":
        values = np.clip(frame * 255, 0, 255).astype(np.uint8)
        bit = 1 << (round(p["bits"]) - 1)
        flipped = np.bitwise_xor(values, np.uint8(bit)).astype(np.float32) / 255
        out = np.where(mask > 0, flipped, frame)
    elif mode in {"bit_depth", "quantization"}:
        levels = 2 ** round(p["bits"]) - 1
        values = frame
        if mode == "quantization":
            values = values + ctx.random.uniform(-1, 1, (gh, gw, 3)).repeat(block, 0).repeat(block, 1)[
                :h, :w
            ] / max(1, levels)
        quantized = np.round(values * levels) / max(1, levels)
        out = frame * (1 - amount) + quantized * amount
    elif mode == "frame_repeat":
        if ctx.index % delay == 0 or "repeated" not in state.data:
            state.data["repeated"] = frame.copy()
        out = frame * (1 - amount) + state.data["repeated"] * amount
    elif mode in {"scanline_buffer", "delayed_regions"}:
        if history:
            if mode == "delayed_regions":
                out = np.where(mask > 0, history[0], frame)
            else:
                out = frame.copy()
                for lag in range(min(delay, len(history))):
                    rows = (np.arange(h) // block) % delay == lag
                    out[rows] = out[rows] * (1 - amount) + history[-lag - 1][rows] * amount
    elif mode == "slit_scan":
        out = state.data.get("slit_canvas", frame).copy()
        column = (ctx.index * max(1, round(p["displacement"]))) % w
        out[:, column : min(w, column + block)] = frame[:, column : min(w, column + block)]
        state.data["slit_canvas"] = out.copy()
        out = out * amount + frame * (1 - amount)
    retain(state, "digital_history", out if mode == "block_persist" else frame, delay)
    return out


def process(kind, frame, p, ctx, state):
    original = frame.shape[:2]
    image = resize_internal(frame, p["internal_height"]).astype(np.float32) / 255
    prepare_state(state, image.shape)
    out = datamosh(image, p, ctx, state) if kind == "simulated_datamosh" else corruption(image, p, ctx, state)
    if out.shape[:2] != original:
        out = cv2.resize(out, (original[1], original[0]))
    return np.clip(out * 255, 0, 255).astype(np.uint8)
