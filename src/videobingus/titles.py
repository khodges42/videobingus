import numpy as np
from PIL import Image, ImageColor, ImageDraw, ImageFont

from .compositing import position


class TitleRenderer:
    def __init__(self, settings, resolution):
        self.settings, self.resolution = settings, resolution
        self.font = (
            ImageFont.truetype(str(settings.font), settings.font_size)
            if settings.font
            else ImageFont.load_default(size=settings.font_size)
        )
        self.color = ImageColor.getrgb(settings.color)
        self.cached = None
        self.last_text = None

    def apply(self, frame, time, track):
        settings = self.settings
        if not settings.enabled:
            return frame
        start = track["time"] if track else 0
        elapsed = time - start
        if elapsed < 0 or elapsed >= settings.duration:
            return frame
        lines = [settings.mix_title] if settings.mix_title else []
        if track:
            lines.append(
                f"{track['index']:02d}  " + " - ".join(s for s in [track["artist"], track["title"]] if s)
            )
        if not lines:
            return frame
        text = "\n".join(lines)
        if text != self.last_text:
            width, height = self.resolution
            image = Image.new("RGBA", (width, height))
            draw = ImageDraw.Draw(image)
            box = draw.multiline_textbbox((0, 0), text, font=self.font, spacing=6)
            tw, th = box[2] - box[0], box[3] - box[1]
            x, y = position(settings.position, self.resolution, (tw, th), max(8, width // 30))
            if settings.style == "lower_third":
                draw.rectangle(
                    (max(0, x - 10), max(0, y - 10), min(width, x + tw + 10), min(height, y + th + 10)),
                    fill=(0, 0, 0, 160),
                )
            draw.multiline_text(
                (x, y - box[1]),
                text,
                font=self.font,
                fill=(*self.color, 255),
                spacing=6,
                stroke_width=1 if settings.style == "vcr" else 0,
                stroke_fill=(0, 0, 0, 220),
            )
            self.cached, self.last_text = np.array(image), text
        opacity = 1
        if settings.fade_in:
            opacity *= min(1, elapsed / settings.fade_in)
        if settings.fade_out:
            opacity *= min(1, (settings.duration - elapsed) / settings.fade_out)
        alpha = self.cached[..., 3:4].astype(np.float32) / 255 * opacity
        return np.clip(frame * (1 - alpha) + self.cached[..., :3] * alpha, 0, 255).astype(np.uint8)
