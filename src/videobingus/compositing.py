import hashlib
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from .decoder import decode
from .effects.engine import State, pixels
from .generators import generate


def position(name, canvas, size, margin=0):
    width, height = canvas
    w, h = size
    x = margin if "left" in name else width - w - margin if "right" in name else (width - w) // 2
    y = margin if "top" in name else height - h - margin if "bottom" in name else (height - h) // 2
    return max(0, x), max(0, y)


def blend(background, foreground, mode, opacity, location="center", scale=1, luma_key=None):
    h, w = background.shape[:2]
    target = (max(1, round(w * scale)), max(1, round(h * scale)))
    ratio = min(target[0] / foreground.shape[1], target[1] / foreground.shape[0])
    target = (max(1, round(foreground.shape[1] * ratio)), max(1, round(foreground.shape[0] * ratio)))
    if foreground.shape[:2] != (target[1], target[0]):
        foreground = cv2.resize(foreground, target, interpolation=cv2.INTER_AREA)
    x, y = position(location, (w, h), target)
    source = foreground[..., :3].astype(np.float32) / 255
    alpha = np.full((*source.shape[:2], 1), opacity, dtype=np.float32)
    if foreground.shape[2] == 4:
        alpha *= foreground[..., 3:4].astype(np.float32) / 255
    if luma_key is not None:
        alpha *= np.mean(source, axis=2, keepdims=True) > luma_key
    base = background[y : y + target[1], x : x + target[0]].astype(np.float32) / 255
    if mode in {"add", "additive"}:
        mixed = np.minimum(1, base + source)
    elif mode == "screen":
        mixed = 1 - (1 - base) * (1 - source)
    elif mode == "multiply":
        mixed = base * source
    elif mode == "difference":
        mixed = np.abs(base - source)
    else:
        mixed = source
    out = background.copy()
    out[y : y + target[1], x : x + target[0]] = pixels((base * (1 - alpha) + mixed * alpha) * 255)
    return out


class Layers:
    def __init__(self, overlays, ffmpeg, output, effects, layer_order=None):
        self.layer_ids = layer_order or list(dict.fromkeys(o["id"] for o in overlays))
        rank = {identity: index for index, identity in enumerate(self.layer_ids)}
        self.pending = iter(sorted(overlays, key=lambda o: (o["start"], rank[o["id"]])))
        self.next = next(self.pending, None)
        self.active = []
        self.ffmpeg, self.output, self.effects = ffmpeg, output, effects
        self.generator_states = {}
        self.coordinates = None

    def __enter__(self):
        return self

    def __exit__(self, *error):
        cleanup = ExitStack()
        for _, stack, _ in self.active:
            cleanup.push(stack)
        return cleanup.__exit__(*error)

    def composite(self, frame, context, modulated_effects, opacity):
        blank = np.zeros_like(frame)
        for identity in self.layer_ids:
            context.inputs.setdefault(identity, blank)
        alive = []
        for entry in self.active:
            overlay, stack, _ = entry
            if overlay["end"] <= context.index:
                stack.close()
            else:
                alive.append(entry)
        self.active = alive
        while self.next and self.next["start"] <= context.index:
            overlay = self.next
            self.next = next(self.pending, None)
            if overlay["end"] <= context.index:
                continue
            stack = ExitStack()
            asset = overlay["asset"]
            try:
                if asset["path"].startswith("generator:"):
                    source = None
                elif asset.get("image"):
                    with Image.open(asset["path"]) as image:
                        source = np.array(image.convert("RGBA"))
                else:
                    clip = {"offset": overlay["offset"], "speed": 1, "reverse": False, "freeze": False}
                    source = stack.enter_context(
                        decode(
                            self.ffmpeg,
                            Path(asset["path"]),
                            clip,
                            self.output,
                            overlay["end"] - overlay["start"],
                        )
                    )
                    for _ in range(context.index - overlay["start"]):
                        next(source)
                self.active.append((overlay, stack, source))
            except BaseException:
                stack.close()
                raise
        by_identity = {overlay["id"]: (overlay, stack, source) for overlay, stack, source in self.active}
        for identity in self.layer_ids:
            if identity not in by_identity:
                silent = replace(context, clip_id=-1, clip_time=1 / context.fps)
                self.effects.process(blank, silent, identity, modulated_effects)
                continue
            overlay, _, source = by_identity[identity]
            stream = int.from_bytes(hashlib.sha256(overlay["id"].encode()).digest()[:8], "big")
            local = replace(
                context,
                clip_id=overlay["start"],
                generator_id=overlay["id"],
                clip_time=(context.index - overlay["start"]) / context.fps,
                random=np.random.default_rng(
                    np.random.SeedSequence([self.effects.seed, stream, context.index])
                ),
            )
            if source is None:
                foreground = generate(
                    overlay["asset"]["path"].split(":", 1)[1],
                    self.output.resolution,
                    local,
                    overlay.get("generator_params", {}),
                    self.generator_states.setdefault(overlay["id"], State()),
                )
            elif isinstance(source, np.ndarray):
                foreground = source.copy()
            else:
                foreground = next(source)
            alpha = foreground[..., 3:4] if foreground.shape[2] == 4 else None
            foreground = self.effects.process(foreground[..., :3], local, overlay["id"], modulated_effects)
            if alpha is not None:
                foreground = np.concatenate([foreground, alpha], axis=2)
            context.inputs[overlay["id"]] = foreground[..., :3]
            amount = opacity.get(overlay["id"], overlay["opacity"])
            role = overlay.get("role", "overlay")
            if role == "input":
                continue
            if role in {"mask", "displacement"}:
                field = (
                    cv2.resize(foreground[..., :3], (frame.shape[1], frame.shape[0])).astype(np.float32) / 255
                )
                if role == "mask":
                    luminance = field @ np.float32([0.299, 0.587, 0.114])
                    frame = pixels(frame.astype(np.float32) * (1 - amount + luminance[..., None] * amount))
                else:
                    if self.coordinates is None:
                        self.coordinates = np.meshgrid(
                            np.arange(frame.shape[1], dtype=np.float32),
                            np.arange(frame.shape[0], dtype=np.float32),
                        )
                    dx, dy = overlay.get("displacement", (24, 12))
                    displaced = cv2.remap(
                        frame,
                        self.coordinates[0] + (field[..., 0] * 2 - 1) * dx,
                        self.coordinates[1] + (field[..., 1] * 2 - 1) * dy,
                        cv2.INTER_LINEAR,
                        borderMode=cv2.BORDER_REFLECT,
                    )
                    frame = pixels(
                        frame.astype(np.float32) * (1 - amount) + displaced.astype(np.float32) * amount
                    )
                continue
            frame = blend(
                frame,
                foreground,
                overlay["blend"],
                amount,
                overlay["position"],
                overlay["scale"],
                overlay["luma_key"],
            )
        return frame
