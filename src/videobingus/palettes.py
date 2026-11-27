FAMILIES = {
    "commodore": ["#101126", "#50459b", "#8b5429", "#a8c9ff", "#e7dac1"],
    "ega": ["#05051b", "#0000aa", "#aa00aa", "#00aaaa", "#ffff55", "#ffffff"],
    "amber": ["#080402", "#462409", "#bd6c12", "#ffca60"],
    "phosphor": ["#010806", "#075337", "#42c675", "#cdffc2"],
    "cyan_magenta": ["#070d24", "#2d3976", "#cb2b95", "#25cddd", "#e7f6e9"],
    "acid": ["#080b15", "#491775", "#b51b92", "#8bd734", "#e7f586"],
    "ultraviolet": ["#060715", "#251359", "#6029b1", "#c246b9", "#eb9adc"],
    "infrared": ["#080718", "#43255d", "#b53055", "#f66a40", "#ffd69a"],
    "thermal": ["#0b0929", "#323cac", "#af2697", "#ed4a3b", "#ffc83d", "#fff4c3"],
    "industrial": ["#080a0c", "#3b4444", "#9a9a75", "#e3b22c", "#f1e8bd"],
    "archival": ["#161b21", "#47535b", "#8b8a78", "#b7a48e", "#ded7bc"],
    "monochrome": ["#07090b", "#354049", "#afbec7", "#eff5f2"],
    "pastel": ["#20263d", "#7f83ab", "#cba4c4", "#e8b6a8", "#bce3d1"],
    "deep_space": ["#030814", "#14234c", "#4e3c7b", "#b35491", "#66cbd6", "#e4eddd"],
}


class ColorStops(list):
    def __init__(self, values, space="rgb"):
        super().__init__(values)
        self.space = space


def colors(value, custom=None):
    from PIL import ImageColor

    if isinstance(value, str):
        value = (custom or {}).get(value, FAMILIES.get(value))
        if value is None:
            raise ValueError("Unknown palette; use a built-in family or define it under palettes")
    if not isinstance(value, (list, tuple)) or not 2 <= len(value) <= 16:
        raise ValueError("A palette requires 2–16 colors")
    result = []
    for color in value:
        if isinstance(color, str):
            rgb = ImageColor.getrgb(color)
            if len(rgb) != 3:
                raise ValueError("Palette colors require RGB without alpha")
            result.append([v / 255 for v in rgb])
        else:
            if len(color) != 3 or any(not 0 <= v <= 1 for v in color):
                raise ValueError("Palette RGB triples must lie in [0, 1]")
            result.append(list(color))
    return result


def map_colors(signal, stops, phase=0, space="rgb", cyclic=True):
    import cv2
    import numpy as np

    space = getattr(stops, "space", space)
    palette = np.asarray(stops, dtype=np.float32)
    if cyclic:
        palette = np.concatenate([palette, palette[:1]], axis=0)
    value = (signal + phase) % 1 if cyclic else np.clip(signal + phase, 0, 1)
    if space == "lab":
        palette = cv2.cvtColor(palette[None, ...], cv2.COLOR_RGB2LAB)[0]
    positions = value * (len(palette) - 1)
    low = np.floor(positions).astype(np.int32)
    high = np.minimum(len(palette) - 1, low + 1)
    alpha = (positions - low)[..., None]
    result = (palette[low] * (1 - alpha) + palette[high] * alpha).astype(np.float32)
    return cv2.cvtColor(result, cv2.COLOR_LAB2RGB) if space == "lab" else result


def generate_palette(seed, scheme="analogous", count=5):
    import colorsys
    import random

    if scheme not in {"analogous", "complementary", "monochrome"} or not 2 <= count <= 16:
        raise ValueError("Choose analogous, complementary or monochrome and 2–16 color stops")
    randomizer = random.Random(seed)
    hue = randomizer.random()
    result = []
    for index in range(count):
        position = index / (count - 1)
        offset = (
            (position - 0.5) * 0.16
            if scheme == "analogous"
            else 0.5 * (index % 2)
            if scheme == "complementary"
            else 0
        )
        rgb = colorsys.hsv_to_rgb((hue + offset) % 1, 0.8 - position * 0.45, 0.05 + position * 0.9)
        result.append("#" + "".join(f"{round(channel * 255):02x}" for channel in rgb))
    return result
