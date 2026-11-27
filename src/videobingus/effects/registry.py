"""Parameter defaults and inclusive limits; ranges are sampled on activation."""

from ..scenes.catalog import CATALOG
from .synthesis_specs import OPTIONS, STRUCTURED
from .synthesis_specs import PARAMETERS as SYNTHESIS

# name: (default, minimum, maximum)
PARAMETERS = {
    "hue_shift": {"degrees": (45, -360, 360)},
    "color": {"saturation": (1.2, 0, 4), "contrast": (1.1, 0, 4)},
    "negative": {},
    "posterize": {"levels": (5, 2, 32)},
    "edges": {"threshold": (80, 0, 255)},
    "rgb_shift": {"pixels": (6, -100, 100)},
    "pixelate": {"size": (12, 1, 256)},
    "mirror": {},
    "kaleidoscope": {},
    "wave": {"amplitude": (8, 0, 100), "frequency": (3, 0, 30), "speed": (1, 0, 20)},
    "band_displace": {"pixels": (20, 0, 200), "bands": (5, 1, 64)},
    "vhs": {
        "chroma_bleed": (5, 0, 30),
        "noise": (7, 0, 60),
        "horizontal_jitter": (2, 0, 40),
        "ghosting": (0.12, 0, 0.8),
        "dropout": (0.015, 0, 0.5),
        "head_noise": (0.04, 0, 0.3),
    },
    "tracking_error": {"pixels": (45, 0, 300), "bands": (8, 1, 64)},
    "crt": {
        "scanlines": (0.2, 0, 1),
        "curvature": (0.08, 0, 0.4),
        "vignette": (0.35, 0, 1),
        "bloom": (0.12, 0, 1),
        "refresh": (0, 0, 1),
    },
    "camcorder": {"movement": (3, 0, 30), "perspective": (0.02, 0, 0.2), "noise": (3, 0, 40)},
    "block_glitch": {"blocks": (8, 1, 64), "displacement": (40, 0, 300), "smear": (0.3, 0, 1)},
    "frame_hold": {"seconds": (0.2, 0.02, 5)},
    "temporal_blend": {"decay": (0.6, 0, 0.98)},
    "datamosh": {"persistence": (0.8, 0, 0.98), "displacement": (12, 0, 100), "blocks": (12, 1, 64)},
    "feedback": {
        "decay": (0.85, 0, 0.99),
        "scale": (1.01, 0.8, 1.2),
        "rotation": (0.5, -15, 15),
        "x": (0, -100, 100),
        "y": (0, -100, 100),
        "opacity": (0.5, 0, 1),
    },
}
PARAMETERS.update(SYNTHESIS)

GENERATORS = {"television_static", "color_bars", "blue_vcr", "black", "signal_loss", "waveform", "spectrum"}
GENERATORS.update(
    {
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
        "alignment_grid",
        "grayscale_ramp",
        "crosshatch",
        "sync_pattern",
        "oscilloscope_xy",
        "vectorscope",
        "waveform_monitor",
    }
)
GENERATORS.update(CATALOG)


def defaults(kind):
    return {
        **{k: v[0] for k, v in PARAMETERS[kind].items()},
        **{k: v[0] for k, v in OPTIONS.get(kind, {}).items()},
        **STRUCTURED.get(kind, {}),
    }


def parameter_names(kind):
    return set(PARAMETERS.get(kind, {})) | set(OPTIONS.get(kind, {})) | set(STRUCTURED.get(kind, {}))


def validate_params(kind: str, params: dict) -> dict:
    if kind not in PARAMETERS:
        raise ValueError(f"Unknown effect {kind!r}. Run 'videobingus effects list'.")
    for key, value in params.items():
        if key in OPTIONS.get(kind, {}):
            if value not in OPTIONS[kind][key][1]:
                raise ValueError(f"{kind}.{key} must be one of {OPTIONS[kind][key][1]}")
            continue
        if key in STRUCTURED.get(kind, {}):
            validate_structure(key, value)
            continue
        if key not in PARAMETERS[kind]:
            raise ValueError(f"Unknown {kind} parameter: {key}")
        _, low, high = PARAMETERS[kind][key]
        values = value if isinstance(value, (list, tuple)) else [value]
        if len(values) not in (1, 2) or any(
            not isinstance(v, (int, float)) or not low <= v <= high for v in values
        ):
            raise ValueError(f"{kind}.{key} must be a number or range within [{low}, {high}]")
        if len(values) == 2 and values[0] > values[1]:
            raise ValueError(f"{kind}.{key} range must be ordered")
    if kind == "signal_overload":
        low = params.get("low", PARAMETERS[kind]["low"][0])
        high = params.get("high", PARAMETERS[kind]["high"][0])
        low_max = max(low) if isinstance(low, (list, tuple)) else low
        high_min = min(high) if isinstance(high, (list, tuple)) else high
        if low_max >= high_min:
            raise ValueError("signal_overload low must remain below high throughout their ranges")
    return params


def validate_structure(key, value):
    import math

    if key == "palette":
        if not isinstance(value, list) or not 2 <= len(value) <= 16:
            raise ValueError("palette requires 2–16 RGB triples in [0, 1]")
        if any(
            not isinstance(c, (list, tuple))
            or len(c) != 3
            or any(not isinstance(v, (int, float)) or not 0 <= v <= 1 for v in c)
            for c in value
        ):
            raise ValueError("palette requires RGB triples in [0, 1]")
    elif key == "taps":
        if not isinstance(value, list) or not 1 <= len(value) <= 8:
            raise ValueError("signal_delay requires 1–8 taps")
        for tap in value:
            if not isinstance(tap, dict) or set(tap) - {"x", "y", "frames", "gain", "polarity", "channels"}:
                raise ValueError("Unknown delay tap field")
            for name, limit in (("x", 500), ("y", 500), ("gain", 2), ("polarity", 1)):
                v = tap.get(name, 1 if name in {"gain", "polarity"} else 0)
                if not isinstance(v, (float, int)) or not math.isfinite(v) or abs(v) > limit:
                    raise ValueError(f"Invalid tap {name}")
            if not isinstance(tap.get("frames", 0), int) or not 0 <= tap.get("frames", 0) <= 30:
                raise ValueError("Tap frame delay must be an integer in [0, 30]")
            if tap.get("channels", "luma") not in {"luma", "chroma", "all"}:
                raise ValueError("Tap channels must be luma, chroma or all")
