import re
import shlex
from pathlib import Path


def seconds(value: str, cue=False) -> float:
    parts = value.split(":")
    if cue:
        if len(parts) != 3:
            raise ValueError(f"Invalid CUE timestamp: {value}")
        minutes, secs, frames = map(int, parts)
        if minutes < 0 or not 0 <= secs < 60 or not 0 <= frames < 75:
            raise ValueError(f"Invalid CUE timestamp: {value}")
        return minutes * 60 + secs + frames / 75
    if not 1 <= len(parts) <= 3:
        raise ValueError(f"Invalid timestamp: {value}")
    numbers = list(map(float, parts))
    if any(n < 0 for n in numbers) or any(n >= 60 for n in numbers[1:]):
        raise ValueError(f"Invalid timestamp: {value}")
    result = 0
    for number in numbers:
        result = result * 60 + number
    return result


def parse(path: Path, duration: float) -> list[dict]:
    text = path.read_text(encoding="utf-8-sig")
    tracks = []
    if path.suffix.lower() == ".cue":
        files = 0
        current, performer = None, ""
        for line in text.splitlines():
            tokens = shlex.split(line, posix=True)
            if not tokens:
                continue
            command, *args = tokens
            command = command.upper()
            if command == "FILE":
                files += 1
                if files > 1:
                    raise ValueError(
                        "Multi-file CUE sheets are unsupported. Export a single-file CUE for the mix."
                    )
            elif command == "TRACK":
                if len(args) != 2 or args[1].upper() != "AUDIO":
                    raise ValueError("Only AUDIO tracks are supported in CUE sheets")
                if current and "time" not in current:
                    raise ValueError("Each CUE track requires INDEX 01")
                current = {"index": int(args[0]), "artist": performer, "title": ""}
                tracks.append(current)
            elif command in {"TITLE", "PERFORMER"}:
                value = " ".join(args)
                if current is not None:
                    current["title" if command == "TITLE" else "artist"] = value
                elif command == "PERFORMER":
                    performer = value
            elif command == "INDEX" and args and args[0] == "01":
                if current is None or len(args) != 2:
                    raise ValueError("INDEX 01 must follow TRACK")
                current["time"] = seconds(args[1], cue=True)
    else:
        for line in text.splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            match = re.fullmatch(r"\s*(\d+(?::\d{2}){1,2}(?:\.\d+)?)\s+(.+?)\s*", line)
            if not match:
                raise ValueError(f"Expected 'MM:SS Artist - Title': {line}")
            artist, separator, title = match[2].partition(" - ")
            tracks.append(
                {
                    "index": len(tracks) + 1,
                    "time": seconds(match[1]),
                    "artist": artist if separator else "",
                    "title": title if separator else artist,
                }
            )
    if not tracks:
        raise ValueError("Tracklist contains no tracks")
    previous = -1
    indices = set()
    for track in tracks:
        time = track.get("time", -1)
        if time < 0 or time >= duration or time <= previous:
            raise ValueError("Track timestamps must increase strictly and lie within the soundtrack")
        if track["index"] < 1 or track["index"] in indices:
            raise ValueError("Track numbers must be positive and unique")
        indices.add(track["index"])
        previous = time
    return tracks
