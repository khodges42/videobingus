import subprocess
from contextlib import closing, contextmanager
from fractions import Fraction
from pathlib import Path

import numpy as np

from .config import Output
from .platform import process


@contextmanager
def decode(ffmpeg: str, path: Path, clip: dict, output: Output, count: int):
    width, height = output.resolution
    fps = Fraction(str(output.fps))
    chunk_limit = max(1, 64 * 1024 * 1024 // (width * height * 3))
    if clip["reverse"] and not clip["freeze"] and count > chunk_limit:

        def reversed_chunks():
            remaining = count
            while remaining:
                size = min(remaining, chunk_limit)
                subclip = dict(clip)
                subclip["offset"] += (remaining - size) / float(fps) * clip["speed"]
                with decode(ffmpeg, path, subclip, output, size) as frames:
                    yield from frames
                remaining -= size

        with closing(reversed_chunks()) as frames:
            yield frames
        return
    if output.fit == "fit":
        sizing = (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
        )
    elif output.fit == "crop":
        sizing = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}"
    else:
        sizing = f"scale={width}:{height}"
    filters = f"scale=iw*sar:ih,setsar=1,{sizing},setpts=(PTS-STARTPTS)/{clip['speed']},fps={fps}"
    if clip["reverse"] and not clip["freeze"]:
        filters += f",trim=end_frame={count},reverse"
    args = [ffmpeg, "-v", "error", "-nostdin", "-threads", "1"]
    args += [
        "-stream_loop",
        "-1",
        "-ss",
        str(clip["offset"] % clip["source_duration"] if clip.get("source_duration") else clip["offset"]),
        "-i",
        str(path),
        "-an",
        "-map",
        "0:v:0",
        "-vf",
        filters,
        "-frames:v",
        str(1 if clip["freeze"] else count),
        "-pix_fmt",
        "rgb24",
        "-f",
        "rawvideo",
        "pipe:1",
    ]
    with process(args, check=False, stdout=subprocess.PIPE) as child:
        consumed = 0

        def frames():
            nonlocal consumed
            cached = None
            for _ in range(count):
                if cached is None or not clip["freeze"]:
                    buffer = bytearray()
                    size = width * height * 3
                    while len(buffer) < size:
                        chunk = child.stdout.read(size - len(buffer))
                        if not chunk:
                            raise ValueError(f"Source decoder ended early: {path}")
                        buffer.extend(chunk)
                    cached = np.frombuffer(buffer, dtype=np.uint8).reshape(height, width, 3)
                consumed += 1
                yield cached.copy()

        try:
            yield frames()
        finally:
            if consumed < count and child.poll() is None:
                child.terminate()
