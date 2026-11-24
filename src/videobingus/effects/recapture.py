from collections import deque

import cv2
import numpy as np


def prepare_state(state, shape):
    size = tuple(shape[:2])
    if state.data.get("processing_shape", size) != size:
        state.data.clear()
        state.maps.clear()
        state.previous = state.held = None
    state.data["processing_shape"] = size


def coordinates(state, shape):
    key = (shape[0], shape[1])
    if state.data.get("coordinate_shape") != key:
        state.data["coordinate_shape"] = key
        state.data["coordinates"] = np.indices(key, dtype=np.float32)
    return state.data["coordinates"]


def retain(state, key, frame, length):
    length = max(1, round(length))
    if frame.nbytes * length > 64 * 1024 * 1024:
        raise ValueError("Effect history exceeds 64 MiB; reduce internal_height or frame delay")
    history = state.data.get(key)
    if history is None or history.maxlen != length:
        history = deque(list(history or [])[-length:], maxlen=length)
        state.data[key] = history
    history.append(frame.copy())
    return history


def resize_internal(frame, height):
    h, w = frame.shape[:2]
    target = min(h, max(2, round(height)))
    return (
        cv2.resize(frame, (max(2, round(w * target / h)), target), interpolation=cv2.INTER_AREA)
        if target < h
        else frame
    )


def display(frame, p, ctx, state):
    h, w = frame.shape[:2]
    y, x = coordinates(state, frame.shape)
    nx, ny = (x / max(1, w - 1) * 2 - 1), (y / max(1, h - 1) * 2 - 1)
    factor = (1 + p["curvature"] * (nx * nx + ny * ny)) / p["overscan"]
    out = cv2.remap(frame, (nx * factor + 1) * (w - 1) / 2, (ny * factor + 1) * (h - 1) / 2, cv2.INTER_LINEAR)
    out[1::2] *= 1 - p["scanlines"]
    mask = np.eye(3, dtype=np.float32)[np.arange(w) % 3]
    out *= 1 - p["mask"] * (1 - mask[None, ...])
    out += cv2.GaussianBlur(out, (0, 0), 1.2) * p["bloom"]
    glow = cv2.GaussianBlur(out, (0, 0), 5) * p["halation"]
    glow[..., 0] *= 1.3
    out += glow + p["black_level"]
    out *= (1 - p["refresh"] * (0.5 + 0.5 * np.sin(y * 0.025 - ctx.time * 7)))[..., None]
    if state.data.get("display_previous") is not None:
        out = out * (1 - p["persistence"]) + state.data["display_previous"] * p["persistence"]
    border = round(min(h, w) * p["border"])
    if border:
        out[:border] = out[-border:] = 0
        out[:, :border] = out[:, -border:] = 0
    out = np.clip(out, 0, 2)
    state.data["display_previous"] = out.copy()
    return out


def camera(frame, p, ctx, state):
    h, w = frame.shape[:2]
    t = ctx.time
    movement = p["movement"]
    transform = cv2.getRotationMatrix2D(
        (w / 2, h / 2), p["rotation"] + movement * np.sin(t * 0.19) * 0.1, p["zoom"]
    )
    transform[:, 2] += [p["x"] + movement * np.sin(t * 0.31), p["y"] + movement * np.sin(t * 0.23 + 1)]
    out = cv2.warpAffine(frame, transform, (w, h))
    source = np.float32([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]])
    shift = p["perspective"] * w
    tilt = np.sin(np.deg2rad(p["angle"])) * h * 0.25
    destination = source + np.float32([[shift, tilt], [-shift, -tilt], [0, tilt], [0, -tilt]])
    out = cv2.warpPerspective(out, cv2.getPerspectiveTransform(source, destination), (w, h))
    y, x = coordinates(state, frame.shape)
    nx, ny = x / max(1, w - 1) * 2 - 1, y / max(1, h - 1) * 2 - 1
    factor = 1 + p["lens"] * (nx * nx + ny * ny)
    mx = (nx * factor + 1) * (w - 1) / 2 + np.sin(y / h * 9 + t * 4) * p["rolling_shutter"]
    my = (ny * factor + 1) * (h - 1) / 2
    out = cv2.remap(out, mx.astype(np.float32), my.astype(np.float32), cv2.INTER_LINEAR)
    sigma = p["focus"] * (0.5 + 0.5 * np.sin(t * 0.37))
    if sigma > 0.05:
        out = cv2.GaussianBlur(out, (0, 0), sigma)
    out *= 1 + p["exposure"] * np.sin(t * 0.71)
    out[..., 0] *= 1 + p["white_balance"] * np.sin(t * 0.13)
    out[..., 2] *= 1 - p["white_balance"] * np.sin(t * 0.13)
    interference = p["moire"] * np.sin(x * 2.2 + y * 0.4 + t) * np.sin(y * 2.1 - t * 0.3)
    out += interference[..., None]
    out *= (1 + p["refresh"] * np.sin(y / h * 2 * np.pi - t * 8))[..., None]
    if p["noise"]:
        out += ctx.random.normal(0, p["noise"], out.shape).astype(np.float32)
    return np.clip(out, 0, 2)


def feedback(frame, p, ctx, state):
    from .registry import defaults

    delay = max(1, round(p["delay"]))
    history = state.data.get("optical_history")
    delayed = history[-delay].copy() if history and len(history) >= delay else frame.copy()
    hsv = cv2.cvtColor(np.clip(delayed, 0, 1), cv2.COLOR_RGB2HSV)
    hsv[..., 0] = (hsv[..., 0] + p["hue"]) % 360
    hsv[..., 1] = np.clip(hsv[..., 1] * p["saturation"], 0, 1)
    delayed = cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB) * p["gain"] * p["decay"]
    incoming = frame * p["injection"]
    mode = p["mode"]
    if mode == "normal":
        mixed = incoming + delayed * (1 - p["injection"])
    elif mode == "additive":
        mixed = incoming + delayed
    elif mode == "difference":
        mixed = np.abs(delayed - incoming)
    elif mode == "multiply":
        mixed = delayed * (1 - p["injection"] + incoming)
    elif mode == "maximum":
        mixed = np.maximum(delayed, incoming)
    elif mode == "minimum":
        mixed = np.minimum(delayed, frame * (1 - p["injection"]) + incoming)
    else:
        if mode == "luma_key":
            mask = np.mean(delayed, axis=2, keepdims=True) >= p["threshold"]
        else:
            mask = cv2.cvtColor(np.clip(delayed, 0, 1), cv2.COLOR_RGB2HSV)[..., 1:2] >= p["threshold"]
        mixed = np.where(mask, delayed, incoming)
    screen = defaults("display")
    screen.update(curvature=p["curvature"], persistence=p["persistence"], bloom=0.05, mask=0.03)
    mixed = display(mixed.astype(np.float32), screen, ctx, state)
    cam = defaults("virtual_camera")
    cam.update(
        zoom=p["zoom"],
        rotation=p["rotation"],
        x=p["x"],
        y=p["y"],
        perspective=p["perspective"],
        angle=p["angle"],
        movement=p["drift"],
        focus=p["blur"],
        exposure=p["exposure"],
        noise=0,
        moire=0,
        white_balance=0,
        lens=0,
        rolling_shutter=0,
        refresh=0,
    )
    captured = camera(mixed, cam, ctx, state)
    level = p["clip_level"]
    captured = level * np.tanh(captured / level) if p["clipping"] == "soft" else np.clip(captured, 0, level)
    retain(state, "optical_history", captured, delay)
    return captured


def process(kind, frame, p, ctx, state):
    original = frame.shape[:2]
    frame = resize_internal(frame, p["internal_height"]).astype(np.float32) / 255
    prepare_state(state, frame.shape)
    operation = {"display": display, "virtual_camera": camera, "optical_feedback": feedback}[kind]
    result = operation(frame, p, ctx, state)
    if result.shape[:2] != original:
        result = cv2.resize(result, (original[1], original[0]))
    return np.clip(result * 255, 0, 255).astype(np.uint8)
