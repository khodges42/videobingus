from dataclasses import dataclass

import cv2
import numpy as np


def to_ycc(rgb):
    rgb = np.asarray(rgb, dtype=np.float32)
    red, green, blue = np.moveaxis(rgb, -1, 0)
    y = 0.299 * red + 0.587 * green + 0.114 * blue
    return np.stack([y, (blue - y) / 1.772, (red - y) / 1.402], axis=-1)


def to_rgb(ycc):
    y, cb, cr = np.moveaxis(ycc, -1, 0)
    return np.stack([y + 1.402 * cr, y - 0.344136 * cb - 0.714136 * cr, y + 1.772 * cb], axis=-1)


def luma(rgb):
    return np.einsum("...c,c->...", rgb, np.array([0.299, 0.587, 0.114], dtype=np.float32))


def chroma(rgb):
    return to_ycc(rgb)[..., 1:]


def attenuate_chroma(signal, amount):
    result = signal.copy()
    result[..., 1:] *= amount
    return result


def gain_offset(signal, gain=1, offset=0):
    return signal * gain + offset


def limit(signal, low=0, high=1, soft=False):
    high = max(low + 0.001, high)
    if soft:
        midpoint, radius = (low + high) / 2, (high - low) / 2
        return midpoint + radius * np.tanh((signal - midpoint) / radius)
    return np.clip(signal, low, high)


def invert(signal):
    return 1 - signal


def rectify(signal):
    return np.abs(signal)


def fold(signal, gain=1):
    return 1 - np.abs((signal * gain % 2) - 1)


def threshold(signal, level=0.5, softness=0):
    if softness <= 0:
        return (signal >= level).astype(np.float32)
    amount = np.clip((signal - level) / (2 * softness) + 0.5, 0, 1)
    return amount * amount * (3 - 2 * amount)


def lowpass(signal, width):
    width = max(1, round(width))
    return cv2.blur(signal, (width, 1), borderType=cv2.BORDER_REFLECT)


def differentiate(signal):
    return (np.roll(signal, -1, axis=1) - np.roll(signal, 1, axis=1)) * 0.5


def delayed_mix(signal, delayed, gain=0.3, x=0, y=0):
    return signal + np.roll(delayed, (round(y), round(x)), axis=(0, 1)) * gain


@dataclass
class SignalFrame:
    values: np.ndarray
    original_size: tuple[int, int]

    @classmethod
    def from_rgb(cls, frame, height):
        from .recapture import resize_internal

        return cls(to_ycc(resize_internal(frame, height).astype(np.float32) / 255), frame.shape[:2])

    def rgb(self):
        result = to_rgb(self.values)
        if result.shape[:2] != self.original_size:
            result = cv2.resize(result, (self.original_size[1], self.original_size[0]))
        return np.clip(result * 255, 0, 255).astype(np.uint8)
