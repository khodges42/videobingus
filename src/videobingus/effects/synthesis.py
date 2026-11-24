import cv2
import numpy as np
from scipy.signal import hilbert

from ..signals import wave
from .recapture import coordinates, prepare_state, resize_internal
from .signal_math import fold, luma, threshold, to_ycc

SPATIAL_PATTERNS = {
    "horizontal_ramp",
    "vertical_ramp",
    "radial_ramp",
    "horizontal",
    "vertical",
    "diagonal",
    "rings",
    "grid",
    "checkerboard",
    "spiral",
    "moving_bars",
    "raster_noise",
}
TEST_PATTERNS = {"alignment_grid", "grayscale_ramp", "crosshatch", "sync_pattern"}


def spatial(shape, p, ctx, state, image=None):
    y, x = coordinates(state, shape)
    h, w = shape[:2]
    xx, yy = x / max(1, w - 1), y / max(1, h - 1)
    angle = np.deg2rad(p["orientation"])
    coordinate = xx * np.cos(angle) + yy * np.sin(angle)
    pattern = p["pattern"]
    radius = np.hypot(xx - 0.5, yy - 0.5)
    if pattern == "vertical":
        coordinate = yy
    elif pattern == "diagonal":
        coordinate = (xx + yy) / 2
    elif pattern in {"rings", "radial_ramp"}:
        coordinate = radius
    elif pattern == "spiral":
        coordinate = radius + np.arctan2(yy - 0.5, xx - 0.5) / (2 * np.pi)
    phase = coordinate * p["frequency"] + p["phase"] + ctx.time * p["drift"]
    if image is not None:
        phase += image * p["luma_phase"]
    if pattern == "horizontal_ramp":
        result = (xx + p["phase"] + ctx.time * p["drift"]) % 1
    elif pattern == "vertical_ramp":
        result = (yy + p["phase"] + ctx.time * p["drift"]) % 1
    elif pattern == "radial_ramp":
        result = (radius * p["frequency"] + ctx.time * p["drift"] + p["phase"]) % 1
    elif pattern == "grid":
        result = (
            np.maximum(
                wave(xx * p["frequency"] + ctx.time * p["drift"], "triangle"),
                wave(yy * p["frequency_b"] + p["phase"], "triangle"),
            )
            * 0.5
            + 0.5
        )
    elif pattern == "checkerboard":
        result = (
            (
                np.floor(xx * p["frequency"] + ctx.time * p["drift"])
                + np.floor(yy * p["frequency_b"] + p["phase"])
            )
            % 2
        ).astype(np.float32)
    elif pattern == "moving_bars":
        result = threshold((phase % 1), 0.5, 0.01)
    elif pattern == "raster_noise":
        noise = state.data.get("raster_noise")
        if noise is None or noise.shape != shape[:2]:
            noise = ctx.random.random(shape[:2]).astype(np.float32)
            state.data["raster_noise"] = noise
        result = np.roll(noise, round(ctx.time * p["drift"] * w), axis=1)
    else:
        result = wave(phase, p["waveform"]) * 0.5 + 0.5
    return result * p["amplitude"] + p["offset"]


def colorize(signal, p):
    value = signal * p["folds"]
    if p["mapping"] == "fold":
        value = fold(signal, p["folds"])
    if p["invert"] >= 0.5:
        value = 1 - value
    palette = np.asarray(p["palette"], dtype=np.float32)
    colors = []
    for channel, name in enumerate(("red", "green", "blue")):
        phase = (value + p["phase"] + p[f"{name}_phase"]) % 1
        if p["mapping"] == "channels":
            colors.append(threshold(phase, p[f"{name}_threshold"]))
        else:
            if p["mapping"] == "bands":
                phase = np.floor(phase * p["bands"]) / max(1, p["bands"] - 1)
            position = np.clip(phase, 0, 1) * (len(palette) - 1)
            low = np.floor(position).astype(np.int32)
            high = np.minimum(len(palette) - 1, low + 1)
            alpha = position - low
            colors.append(palette[low, channel] * (1 - alpha) + palette[high, channel] * alpha)
    return np.stack(colors, axis=-1).astype(np.float32)


def scope(kind, frame, p, ctx, state):
    h, w = frame.shape[:2]
    canvas = np.zeros_like(frame, dtype=np.float32)
    if kind == "oscilloscope_xy":
        stereo = np.asarray(ctx.audio.get("stereo", []), dtype=np.float32)
        source = p["source"]
        if source == "oscillator":
            phase = np.linspace(0, 2 * np.pi, round(p["density"]), endpoint=False)
            xx = np.sin(phase * p["frequency"] + ctx.time)
            yy = np.sin(phase * p["frequency"] * p["ratio"] + ctx.time * 0.7)
        elif stereo.size:
            left, right = stereo[:, 0], stereo[:, 1]
            if source == "bands":
                freq = np.fft.rfftfreq(len(left), 1 / 16000)
                spectrum = np.fft.rfft(left)
                xx = np.fft.irfft(spectrum * (freq < 180), n=len(left))
                yy = np.fft.irfft(spectrum * ((freq >= 180) & (freq < 2500)), n=len(left))
            elif source == "phase_shift":
                xx, yy = left, np.imag(hilbert(left))
            else:
                xx, yy = left, right
            stride = max(1, len(xx) // round(p["density"]))
            xx, yy = xx[::stride], yy[::stride]
        else:
            xx = yy = np.zeros(2, dtype=np.float32)
        angle = np.deg2rad(p["rotation"])
        x = (xx * np.cos(angle) - yy * np.sin(angle)) * p["gain"]
        y = (xx * np.sin(angle) + yy * np.cos(angle)) * p["gain"]
        if p["noise"]:
            x += ctx.random.normal(0, p["noise"], len(x))
            y += ctx.random.normal(0, p["noise"], len(y))
        points = np.column_stack([(x * 0.45 + 0.5) * w, (0.5 - y * 0.45) * h]).astype(np.int32)
        cv2.polylines(
            canvas, [points], False, (0.12, p["brightness"], 0.35), round(p["thickness"]), cv2.LINE_AA
        )
    else:
        stride = max(1, round(np.sqrt(h * w / p["density"])))
        sample = frame[::stride, ::stride]
        if kind == "vectorscope":
            cc = to_ycc(sample)[..., 1:]
            x = (cc[..., 0] * p["gain"] + 0.5) * (w - 1)
            y = (0.5 - cc[..., 1] * p["gain"]) * (h - 1)
        else:
            x = np.broadcast_to(
                np.arange(sample.shape[1]) / max(1, sample.shape[1] - 1) * (w - 1), sample.shape[:2]
            )
            y = (1 - np.clip(luma(sample) * p["gain"], 0, 1)) * (h - 1)
        x, y = np.clip(x.astype(int), 0, w - 1), np.clip(y.astype(int), 0, h - 1)
        density = np.zeros((h, w), dtype=np.float32)
        np.add.at(density, (y.ravel(), x.ravel()), 1)
        canvas[..., 1] = np.log1p(density) * p["brightness"]
        canvas[..., 0] = canvas[..., 1] * 0.15
        canvas[..., 2] = canvas[..., 1] * 0.4
    previous = state.data.get("phosphor")
    if previous is not None:
        canvas = np.maximum(canvas, previous * p["decay"])
    canvas = np.clip(canvas, 0, 2)
    state.data["phosphor"] = canvas.copy()
    canvas += cv2.GaussianBlur(canvas, (0, 0), 1.5) * p["bloom"]
    canvas[h // 2, :, 1] += 0.035
    canvas[:, w // 2, 1] += 0.035
    return canvas


def raster(frame, p, ctx, state):
    h, w = frame.shape[:2]
    y, x = coordinates(state, frame.shape)
    brightness = luma(frame)
    oscillation = np.sin(x / w * p["frequency"] * 2 * np.pi + ctx.time) * p["oscillator"]
    amplitude = p["displacement"] * (1 + ctx.audio.get("bass_energy", 0) * p["audio_gain"])
    mx = x + (brightness - 0.5) * p["horizontal"]
    my = y - (brightness - 0.5 + oscillation) * amplitude
    if p["mode"] == "remap":
        return cv2.remap(
            frame,
            mx.astype(np.float32),
            my.astype(np.float32),
            cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REFLECT,
        )
    out = np.zeros_like(frame)
    stride = max(1, w // 512)
    for row in range(0, h, round(p["spacing"])):
        perspective = 1 - p["perspective"] * (1 - row / h)
        xx = (mx[row, ::stride] - w / 2) * perspective + w / 2
        yy = my[row, ::stride]
        points = np.column_stack([xx, yy]).astype(np.int32)
        light = float(np.mean(brightness[row]))
        color = (0.15 + light * 0.5, 0.35 + light * 0.65, 0.25 + light * 0.5)
        if p["colorize"] >= 0.5:
            color = tuple(float(v) for v in (0.5 + 0.5 * np.sin(row / h * 6 + np.arange(3) * 2)))
        cv2.polylines(out, [points], False, color, round(p["thickness"]), cv2.LINE_AA)
    return out


def process(kind, frame, p, ctx, state):
    from .registry import defaults

    original = frame.shape[:2]
    image = resize_internal(frame, p["internal_height"]).astype(np.float32) / 255
    prepare_state(state, image.shape)
    if kind == "spatial_synth":
        brightness = luma(image)
        signal = spatial(image.shape, p, ctx, state, brightness if p["operation"] == "phase" else None)
        secondary = 0.5 + 0.5 * np.sin(brightness * p["frequency_b"] * np.pi * 2)
        operations = {
            "addition": lambda: signal + secondary,
            "multiplication": lambda: signal * secondary,
            "minimum": lambda: np.minimum(signal, secondary),
            "maximum": lambda: np.maximum(signal, secondary),
            "difference": lambda: np.abs(signal - secondary),
            "threshold": lambda: threshold(signal, p["threshold"]),
            "wavefold": lambda: fold(signal + secondary),
        }
        if p["operation"] in operations:
            signal = operations[p["operation"]]()
        if p["output"] == "displace" or p["operation"] == "displace":
            y, x = coordinates(state, image.shape)
            out = cv2.remap(
                image,
                (x + (signal - 0.5) * p["displacement"]).astype(np.float32),
                y,
                cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_REFLECT,
            )
        elif p["output"] == "key":
            mask = threshold(signal, p["threshold"])[..., None]
            out = image * mask
        elif p["output"] == "replace":
            out = np.repeat(np.clip(signal, 0, 1)[..., None], 3, axis=2)
        else:
            out = colorize(signal, defaults("analog_colorizer"))
    elif kind == "analog_colorizer":
        out = colorize(luma(image), p)
    elif kind in {"oscilloscope_xy", "vectorscope", "waveform_monitor"}:
        out = scope(kind, image, p, ctx, state)
    elif kind == "scan_displacement":
        out = raster(image, p, ctx, state)
    else:
        raise ValueError(f"Unknown synthesis processor: {kind}")
    if out.shape[:2] != original:
        out = cv2.resize(out, (original[1], original[0]))
    return np.clip(out * 255, 0, 255).astype(np.uint8)
