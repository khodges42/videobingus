import cv2
import numpy as np

from .recapture import coordinates, prepare_state, retain
from .signal_math import delayed_mix, differentiate, fold, limit, lowpass, rectify, threshold


def process_signal(kind, signal, p, ctx, state):
    prepare_state(state, signal.shape)
    out = signal.copy()
    h, w = signal.shape[:2]
    y, x = coordinates(state, signal.shape)
    t = ctx.time
    if kind == "sync_corruption":
        phases = state.data.setdefault("sync_phases", ctx.random.uniform(0, 2 * np.pi, 3))
        line = np.arange(h, dtype=np.float32) / max(1, h)
        rate = p["drift_rate"]
        correlated = np.sin(line * 6 + t * rate * 2 * np.pi + phases[0])
        correlated += 0.4 * np.sin(line * 19 - t * rate * 3 + phases[1])
        fine = np.sin(line * h * 0.8 + t * 3 + phases[2])
        jitter = p["jitter"] * (p["correlation"] * correlated + (1 - p["correlation"]) * fine)
        elapsed = max(0, t - ctx.activation_time)
        recovery = np.exp(-elapsed / p["recovery"])
        pulse = max(0, np.sin(t * rate * 2 + phases[0])) ** 12
        loss = p["loss"] * max(recovery, pulse)
        center = (t * rate * 0.3) % 1
        local = np.exp(-(((line - center) / 0.12) ** 2))
        shifts = p["horizontal_phase"] + jitter + p["tearing"] * local * (0.2 + loss)
        mx = x + shifts[:, None]
        my = y + p["vertical_phase"] + p["rolling"] * h * elapsed * (0.1 + loss)
        border = cv2.BORDER_WRAP if p["edges"] == "wrap" else cv2.BORDER_CONSTANT
        return cv2.remap(
            out, mx.astype(np.float32), my.astype(np.float32), cv2.INTER_LINEAR, borderMode=border
        )
    if kind == "dirty_enhancer":
        original = signal[..., 0]
        edge = original - lowpass(original, 5)
        ringing = differentiate(differentiate(original))
        overload = 1 + threshold(original, p["threshold"], 0.03) * p["enhancement"]
        out[..., 0] = original + edge * p["enhancement"] * overload + ringing * p["ringing"]
        out[..., 0] = delayed_mix(out[..., 0], original, p["ghost"], p["delay"])
        out[..., 0] = limit(out[..., 0], 0, p["clip_level"])
        out[..., 0] = out[..., 0] * (1 - p["inversion"]) + (1 - out[..., 0]) * p["inversion"]
        out[..., 1:] = lowpass(out[..., 1:], p["chroma_bleed"]) * p["saturation"]
        out[..., 1:] *= 1 + p["instability"] * np.sin(t * 1.7 + y[..., None] * 0.03)
        return out
    if kind == "chroma_corruption":
        phase = np.deg2rad(p["phase"] + p["drift"] * np.sin(t * p["rate"] * 2 * np.pi))
        phase = phase + p["line_error"] * np.sin(y * 0.07 + t * 0.9)
        color = lowpass(np.roll(out[..., 1:], round(p["delay"]), axis=1), p["bleed"])
        cb, cr = color[..., 0], color[..., 1]
        out[..., 1] = cb * np.cos(phase) - cr * np.sin(phase)
        out[..., 2] = cb * np.sin(phase) + cr * np.cos(phase)
        dropout = np.clip(1 - p["dropout"] * (1 + np.sin(t * 2.3 + y * 0.025)), 0, 1)
        out[..., 1:] *= (p["saturation"] * (1 - 2 * p["inversion"]) * dropout)[..., None]
        detail = differentiate(out[..., 0])
        carrier = x * np.pi / 2 + y * np.pi + t * 2
        out[..., 1] += detail * np.cos(carrier) * p["luma_to_chroma"]
        out[..., 2] += detail * np.sin(carrier) * p["luma_to_chroma"]
        out[..., 0] += (cb * np.cos(carrier) + cr * np.sin(carrier)) * p["chroma_to_luma"]
        return out
    if kind == "signal_overload":
        overloaded = out[..., 0] * p["gain"] + p["bias"]
        overloaded = overloaded * (1 - p["rectify"]) + rectify(overloaded) * p["rectify"]
        if p["mode"] == "fold":
            out[..., 0] = fold(overloaded, p["folds"])
        else:
            out[..., 0] = limit(overloaded, p["low"], p["high"], p["mode"] == "soft")
        out[..., 1] = np.tanh(out[..., 1] * p["chroma_gain"] * 2) / 2
        out[..., 2] = np.tanh(out[..., 2] * p["chroma_gain"] * 2.3) / 2
        highlights = threshold(signal[..., 0], 0.7, 0.1)
        smear = lowpass(out[..., 0] * highlights, p["smear"])
        out[..., 0] += smear * 0.25
        return out
    if kind == "signal_delay":
        max_delay = max(tap.get("frames", 0) for tap in p["taps"])
        history = state.data.get("signal_history")
        for tap in p["taps"]:
            delay = tap.get("frames", 0)
            source = (
                history[-delay]
                if delay and history and len(history) >= delay
                else (np.zeros_like(signal) if delay else signal)
            )
            channels = tap.get("channels", "luma")
            selection = (
                slice(0, 1) if channels == "luma" else slice(1, 3) if channels == "chroma" else slice(0, 3)
            )
            out[..., selection] = delayed_mix(
                out[..., selection],
                source[..., selection],
                tap.get("gain", 0.3) * tap.get("polarity", 1),
                tap.get("x", 0),
                tap.get("y", 0),
            )
        if max_delay:
            retain(state, "signal_history", signal, max_delay)
        return out
    if kind == "composite_video":
        carrier = x * (2 * np.pi * p["carrier"]) + y * np.pi + (ctx.index % 4) * np.pi / 2
        phase_error = np.deg2rad(p["phase"]) + p["phase_drift"] * np.sin(t * 0.8)
        phase_error += p["burst_instability"] * np.sin(y * 0.11 + t * 1.2)
        color = lowpass(out[..., 1:], p["bandwidth"])
        if p["quality"] == "carrier":
            encoded = signal[..., 0] + color[..., 0] * np.cos(carrier) + color[..., 1] * np.sin(carrier)
            # A short luma low-pass and synchronous demodulator intentionally leak crosstalk.
            reconstructed_y = lowpass(encoded, max(3, p["bandwidth"]))
            residual = encoded - reconstructed_y
            cb = lowpass(2 * residual * np.cos(carrier + phase_error), p["bandwidth"])
            cr = lowpass(2 * residual * np.sin(carrier + phase_error), p["bandwidth"])
            out[..., 0] = signal[..., 0] * (1 - p["cross_luma"]) + reconstructed_y * p["cross_luma"]
            out[..., 1] = color[..., 0] * (1 - min(1, p["cross_color"])) + cb * p["cross_color"]
            out[..., 2] = color[..., 1] * (1 - min(1, p["cross_color"])) + cr * p["cross_color"]
        else:
            detail = signal[..., 0] - lowpass(signal[..., 0], 3)
            cb, cr = color[..., 0], color[..., 1]
            out[..., 1] = cb * np.cos(phase_error) - cr * np.sin(phase_error)
            out[..., 2] = cb * np.sin(phase_error) + cr * np.cos(phase_error)
            out[..., 1] += detail * np.cos(carrier) * p["cross_color"]
            out[..., 2] += detail * np.sin(carrier) * p["cross_color"]
            out[..., 0] += (cb * np.cos(carrier) + cr * np.sin(carrier)) * p["cross_luma"]
        out[..., 0] += np.hypot(color[..., 0], color[..., 1]) * np.cos(carrier) * p["dot_crawl"]
        return out
    raise ValueError(f"Unknown signal processor: {kind}")


def process(kind, frame, p, ctx, state):
    from .signal_math import SignalFrame

    packet = SignalFrame.from_rgb(frame, p["internal_height"])
    packet.values = process_signal(kind, packet.values, p, ctx, state)
    return packet.rgb()
