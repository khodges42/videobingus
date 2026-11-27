from .registry import OPTIONS, PARAMETERS, STRUCTURED
from .synthesis_specs import MIXERS, SIGNAL_PROCESSORS

GROUPS = {
    "geometry": {"wave", "mirror", "kaleidoscope", "pixelate", "scan_displacement", "band_displace"},
    "color": {"color", "hue_shift", "negative", "posterize", "analog_colorizer", "rgb_shift", "edges"},
    "feedback": {"feedback", "optical_feedback", "temporal_blend", "frame_hold"},
    "display": {"crt", "display", "camcorder", "virtual_camera", "vhs"},
    "corruption": {"digital_corruption", "simulated_datamosh", "datamosh", "block_glitch", "tracking_error"},
    "scope": {"oscilloscope_xy", "vectorscope", "waveform_monitor"},
    "synthesis": {"spatial_synth"},
}
ORDER = {
    "geometry": 10,
    "synthesis": 15,
    "color": 20,
    "signal": 30,
    "feedback": 40,
    "display": 50,
    "corruption": 60,
    "scope": 70,
    "mixer": 0,
}


def describe(kind):
    if kind not in PARAMETERS:
        raise ValueError(f"Unknown effect: {kind}")
    category = (
        "mixer"
        if kind in MIXERS
        else "signal"
        if kind in SIGNAL_PROCESSORS
        else next((name for name, group in GROUPS.items() if kind in group), "corruption")
    )
    stateful = kind in {
        "optical_feedback",
        "feedback",
        "simulated_datamosh",
        "datamosh",
        "temporal_blend",
        "frame_hold",
        "digital_corruption",
        "signal_delay",
        "display",
        "feedback_transition",
    }
    high = {"optical_feedback", "simulated_datamosh", "camcorder", "virtual_camera"}
    tags = {
        "signal": ["analog", "psychedelic"],
        "feedback": ["analog", "ambient"],
        "display": ["analog", "retro"],
        "corruption": ["digital", "industrial"],
        "geometry": ["geometric", "retro"],
        "color": ["psychedelic"],
        "scope": ["vector", "laboratory"],
        "synthesis": ["analog", "geometric"],
        "mixer": ["transition"],
    }[category]
    return {
        "type": kind,
        "description": kind.replace("_", " "),
        "category": category,
        "tags": tags,
        "stage": ORDER[category],
        "stateful": stateful,
        "cost": "high" if kind in high else "low",
        "typical_intensity": 0.25 if category in {"corruption", "signal"} else 0.4,
        "inputs": 2 if kind in MIXERS else 1,
        "backend": "cpu",
        "stages": ["transition"] if kind in MIXERS else ["primary", "overlay", "composite"],
        "parameters": PARAMETERS[kind],
        "options": OPTIONS.get(kind, {}),
        "structured": STRUCTURED.get(kind, {}),
        "modulatable": list(PARAMETERS[kind]),
        "conflicts": sorted(GROUPS.get(category, set()) - {kind})
        if category in {"color", "feedback", "display"}
        else [],
        "compatible_generators": "all",
    }
