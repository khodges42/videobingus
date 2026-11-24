import subprocess
from contextlib import ExitStack
from fractions import Fraction
from pathlib import Path

import numpy as np
from scipy.ndimage import gaussian_filter1d

from .media import identity
from .platform import executable, process

RATE, WINDOW, HOP = 16000, 2048, 1024
BANDS = {"bass_energy": (20, 180), "mid_energy": (180, 2500), "high_energy": (2500, 8000)}
FEATURES = ("rms", "bass_energy", "mid_energy", "high_energy", "flux", "bass_onset", "onset")


def normalize(values):
    values = np.asarray(values, dtype=np.float32)
    scale = np.percentile(values, 95) if values.size else 0
    return np.clip(values / max(float(scale), 1e-8), 0, 1)


def analyze(path: Path, ffmpeg: str | None = None, cache: Path | None = None) -> dict:
    cache = cache or path.parent / ".cache" / "videobingus"
    key = identity(path) + "-audio-v2.npz"
    location = cache / key
    if location.is_file():
        try:
            with np.load(location, allow_pickle=False) as data:
                return {key: data[key].tolist() for key in data.files}
        except (ValueError, OSError):
            pass
    collected = {name: [] for name in ("rms", "bass_energy", "mid_energy", "high_energy", "flux")}
    waveforms, spectra = [], []
    frequencies = np.fft.rfftfreq(WINDOW, 1 / RATE)
    masks = {name: (frequencies >= lo) & (frequencies < hi) for name, (lo, hi) in BANDS.items()}
    previous = np.zeros(WINDOW // 2 + 1)
    tail = np.empty(0, dtype=np.float32)
    args = [
        executable("ffmpeg", ffmpeg),
        "-v",
        "error",
        "-nostdin",
        "-i",
        str(path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(RATE),
        "-f",
        "f32le",
        "pipe:1",
    ]
    with process(args, stdout=subprocess.PIPE) as child:
        while chunk := child.stdout.read(HOP * 4 * 128):
            tail = np.concatenate([tail, np.frombuffer(chunk, dtype="<f4")])
            while tail.size >= WINDOW:
                window = tail[:WINDOW]
                spectrum = np.abs(np.fft.rfft(window * np.hanning(WINDOW)))
                power = spectrum**2
                collected["rms"].append(float(np.sqrt(np.mean(window**2))))
                for name, mask in masks.items():
                    collected[name].append(float(np.sqrt(np.mean(power[mask]))))
                collected["flux"].append(float(np.mean(np.maximum(0, spectrum - previous))))
                waveforms.append(window[::64].tolist())
                bands = np.array_split(power, 16)
                spectra.append([float(np.sqrt(np.mean(band))) for band in bands])
                previous = spectrum
                tail = tail[HOP:]
    if not collected["rms"]:
        collected = {name: [0.0] for name in collected}
    raw_bass = np.asarray(collected["bass_energy"])
    result = {
        name: normalize(gaussian_filter1d(np.asarray(values, dtype=float), 1.0))
        for name, values in collected.items()
    }
    result["bass_onset"] = normalize(np.maximum(0, np.diff(raw_bass, prepend=raw_bass[0])))
    result["onset"] = normalize(collected["flux"])
    result["times"] = np.arange(len(raw_bass)) * HOP / RATE + WINDOW / RATE / 2
    result["waveform"] = np.asarray(waveforms or [[0] * 32], dtype=np.float32)
    result["spectrum"] = normalize(np.asarray(spectra or [[0] * 16], dtype=np.float32))
    temporary = None
    try:
        cache.mkdir(parents=True, exist_ok=True)
        import tempfile

        with tempfile.NamedTemporaryFile(dir=cache, suffix=".npz", delete=False) as handle:
            temporary = Path(handle.name)
            np.savez_compressed(handle, **result)
        temporary.replace(location)
    except OSError:
        pass
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {key: value.tolist() for key, value in result.items()}


def at(features: dict, time: float) -> dict:
    if not features:
        return {name: 0.0 for name in FEATURES}
    times = features["times"]
    result = {name: float(np.interp(time, times, features[name])) for name in FEATURES}
    index = min(len(times) - 1, int(np.searchsorted(times, time)))
    for key in ("waveform", "spectrum"):
        result[key] = features[key][index] if key in features else []
    return result


def events(features: dict, kind: str, threshold: float, hysteresis: float) -> list[float]:
    source = "rms" if kind == "energy" else kind
    if not features:
        return []
    result, armed = [], True
    for time, value in zip(features["times"], features[source]):
        if armed and value >= threshold:
            result.append(time)
            armed = False
        elif value < max(0.001, threshold - hysteresis):
            armed = True
    return result


class Modulator:
    def __init__(self, modulation, fps, signals=None):
        self.modulation, self.fps = modulation, fps
        self.values = {}
        self.signals = signals or {}

    def values_at(self, features):
        effects, overlays = {}, {}
        for ordinal, item in enumerate(self.modulation):
            low, high = item.output_range
            signal = features[item.source]
            if item.source in self.signals and self.signals[item.source].bipolar:
                signal = (signal + 1) / 2
            value = low + (high - low) * signal
            alpha = 1 - np.exp(-1 / (self.fps * item.smoothing)) if item.smoothing else 1
            value = self.values.get(ordinal, value) * (1 - alpha) + value * alpha
            self.values[ordinal] = value
            group, identity, parameter = item.target.split(".")
            if group == "effects":
                destination = effects.setdefault(identity, {})
                previous = destination.get(parameter)
                destination[parameter] = (
                    value
                    if previous is None or item.combine == "replace"
                    else previous * value
                    if item.combine == "multiply"
                    else previous + value
                )
            else:
                previous = overlays.get(identity)
                overlays[identity] = (
                    value
                    if previous is None or item.combine == "replace"
                    else previous * value
                    if item.combine == "multiply"
                    else previous + value
                )
        return effects, overlays


class StereoReader:
    """Bounded paired audio samples for XY displays; the muxed soundtrack is unchanged."""

    def __init__(self, path, ffmpeg, fps, first=0, enabled=True):
        self.path, self.ffmpeg, self.fps, self.first = path, ffmpeg, Fraction(str(fps)), first
        self.enabled = enabled
        self.samples = np.empty((0, 2), dtype=np.float32)
        self.read_samples = 0
        self.stack = ExitStack()

    def __enter__(self):
        if self.enabled:
            args = [
                self.ffmpeg,
                "-v",
                "error",
                "-nostdin",
                "-ss",
                str(float(self.first / self.fps)),
                "-i",
                str(self.path),
                "-vn",
                "-ac",
                "2",
                "-ar",
                "16000",
                "-f",
                "f32le",
                "pipe:1",
            ]
            self.child = self.stack.enter_context(process(args, check=False, stdout=subprocess.PIPE))
        return self

    def at(self, index):
        if not self.enabled:
            return np.empty((0, 2), dtype=np.float32)
        target = int((index - self.first + 1) * RATE / self.fps)
        count = target - self.read_samples
        buffer = bytearray()
        while len(buffer) < count * 8:
            chunk = self.child.stdout.read(count * 8 - len(buffer))
            if not chunk:
                break
            buffer.extend(chunk)
        decoded = np.frombuffer(buffer, dtype="<f4").reshape(-1, 2)
        self.samples = np.concatenate([self.samples, decoded])[-2048:]
        self.read_samples = target
        return self.samples

    def __exit__(self, *error):
        if self.enabled and self.child.poll() is None:
            self.child.terminate()
        return self.stack.__exit__(*error)
