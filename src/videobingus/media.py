import hashlib
import json
import warnings
from pathlib import Path

from .platform import executable, run

EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".mpeg", ".mpg", ".webm", ".m4v"}


def probe(path: Path, ffprobe: str | None = None) -> dict:
    if not path.is_file():
        raise ValueError(f"Media does not exist: {path}")
    return json.loads(
        run(
            [
                executable("ffprobe", ffprobe),
                "-v",
                "error",
                "-show_format",
                "-show_streams",
                "-of",
                "json",
                str(path),
            ]
        )
    )


def inspect(path: Path, ffprobe: str | None = None) -> dict:
    executable("ffprobe", ffprobe)
    cache = Path.cwd() / ".cache" / "videobingus" / f"{identity(path)}-media-v1.json"
    if cache.is_file():
        try:
            return json.loads(cache.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            pass
    info = probe(path, ffprobe)
    stream = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    if not stream:
        raise ValueError(f"No video stream: {path}")
    duration = float(stream.get("duration") or info["format"].get("duration", 0))
    if duration <= 0:
        raise ValueError(f"No finite video duration: {path}")
    metadata = {
        "path": str(path),
        "duration": duration,
        "width": stream["width"],
        "height": stream["height"],
        "fps": stream["avg_frame_rate"],
        "aspect": stream.get("display_aspect_ratio"),
        "rotation": next(
            (s.get("rotation", 0) for s in stream.get("side_data_list", []) if "rotation" in s), 0
        ),
    }
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(metadata), encoding="utf-8")
    except OSError:
        pass
    return metadata


def discover(sources: list[Path], ffprobe: str | None = None) -> list[dict]:
    paths = set()
    for source in sources:
        if not source.exists():
            raise ValueError(f"Source does not exist: {source}")
        paths.update(
            p.resolve()
            for p in (source.rglob("*") if source.is_dir() else [source])
            if p.is_file() and p.suffix.lower() in EXTENSIONS
        )
    result = []
    for path in sorted(paths, key=lambda p: p.as_posix()):
        try:
            result.append(inspect(path, ffprobe))
        except ValueError as error:
            warnings.warn(str(error), stacklevel=2)
    if not result:
        raise ValueError("No usable video found in the source paths")
    return result


def identity(path: Path) -> str:
    stat = path.stat()
    return hashlib.sha256(f"{path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}".encode()).hexdigest()
