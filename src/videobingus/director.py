import numpy as np
from scipy.ndimage import gaussian_filter1d

CONTROL_NAMES = (
    "immediate_energy",
    "sustained_energy",
    "energy_trend",
    "onset_density",
    "low_activity",
    "relative_contrast",
    "track_progress",
    "visual_intensity",
)
LEVELS = {"calm": 0.4, "building": 0.65, "active": 0.8, "peak": 1, "recovery": 0.5}


def derive(features, tracks, settings, duration):
    if not features:
        return []
    times = np.asarray(features["times"])
    step = float(np.median(np.diff(times))) if len(times) > 1 else 0.064
    rms = np.asarray(features["rms"], dtype=float)
    sustained = gaussian_filter1d(rms, max(1, 5 / step))
    recent = gaussian_filter1d(rms, max(1, 20 / step))
    trend = np.clip((sustained - np.roll(sustained, max(1, round(5 / step)))) * 3 + 0.5, 0, 1)
    trend[: max(1, round(5 / step))] = 0.5
    density = gaussian_filter1d((np.asarray(features["onset"]) > 0.55).astype(float), max(1, 3 / step))
    density = np.clip(density * 5, 0, 1)
    contrast = np.clip((rms - recent) * 2 + 0.5, 0, 1)
    features.update(
        immediate_energy=rms.tolist(),
        sustained_energy=sustained.tolist(),
        energy_trend=trend.tolist(),
        onset_density=density.tolist(),
        low_activity=features["bass_energy"],
        relative_contrast=contrast.tolist(),
    )
    progress = np.zeros(len(times))
    boundaries = [0, *[t["time"] for t in tracks if t["time"] > 0], duration]
    for start, end in zip(boundaries, boundaries[1:]):
        mask = (times >= start) & (times < end)
        progress[mask] = (times[mask] - start) / max(0.1, end - start)
    features["track_progress"] = progress.tolist()
    state, since = "calm", 0.0
    intervals = [{"time": 0.0, "state": state, "intensity": LEVELS[state]}]
    visual = []
    for i, time in enumerate(times):
        target = state
        if sustained[i] < 0.27:
            target = "recovery" if state in {"active", "peak"} else "calm"
        elif trend[i] > 0.62:
            target = "building"
        elif sustained[i] > 0.8 and (density[i] > 0.3 or contrast[i] > 0.65):
            target = "peak"
        elif sustained[i] > 0.48:
            target = "active"
        elif state in {"peak", "active"} and trend[i] < 0.4:
            target = "recovery"
        if time - since >= settings.minimum_state_duration and target != state:
            state, since = target, float(time)
            intervals.append({"time": float(time), "state": state, "intensity": LEVELS[state]})
        visual.append(LEVELS[state])
    features["visual_intensity"] = gaussian_filter1d(np.asarray(visual), max(1, 1 / step)).tolist()
    return intervals


def state_at(intervals, time):
    return next(
        (s for s in reversed(intervals) if s["time"] <= time),
        {"time": 0, "state": "active", "intensity": 0.8},
    )


def cap_intervals(intervals, maximum):
    accepted, active = [], []
    for item in sorted(intervals, key=lambda e: (e["start"], e.get("order", 0), e["id"])):
        active = [end for end in active if end > item["start"]]
        if len(active) < maximum:
            accepted.append(item)
            active.append(item["end"])
    return accepted
