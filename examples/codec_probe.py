"""Bounded codec experiments; deliberately not a render backend."""

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

from videobingus.platform import executable, run


def probe(ffmpeg=None, ffprobe=None):
    ffmpeg, ffprobe = executable("ffmpeg", ffmpeg), executable("ffprobe", ffprobe)
    reports = []
    with tempfile.TemporaryDirectory(prefix="videobingus-codec-probe-") as temporary:
        root = Path(temporary)
        original = root / "original.avi"
        run(
            [
                ffmpeg,
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "testsrc2=s=160x120:r=12:d=1",
                "-f",
                "lavfi",
                "-i",
                "testsrc2=s=160x120:r=12:d=1,hue=h=120",
                "-filter_complex",
                "[0:v][1:v]concat=n=2:v=1:a=0",
                "-c:v",
                "mpeg4",
                "-bf",
                "0",
                "-g",
                "12",
                "-sc_threshold",
                "0",
                "-q:v",
                "4",
                str(original),
            ]
        )
        suppressed = root / "suppressed.avi"
        run(
            [
                ffmpeg,
                "-v",
                "error",
                "-i",
                str(original),
                "-c:v",
                "copy",
                "-bsf:v",
                r"noise=drop=gt(n\,0)*key",
                str(suppressed),
            ]
        )
        raw = root / "original.m4v"
        run([ffmpeg, "-v", "error", "-i", str(original), "-c:v", "copy", "-f", "m4v", str(raw)])
        data = raw.read_bytes()
        start_code = b"\x00\x00\x01\xb6"
        offsets, cursor = [], 0
        while (found := data.find(start_code, cursor)) >= 0:
            offsets.append(found)
            cursor = found + 4
        offsets.append(len(data))
        repeated = root / "p-repeat.m4v"
        retained = bytearray(data[: offsets[0]])
        for number, (begin, end) in enumerate(zip(offsets, offsets[1:])):
            packet = data[begin:end]
            kind = packet[4] >> 6
            if kind == 0 and number > 0:
                continue
            retained.extend(packet)
            if kind == 1 and number % 5 == 0:
                retained.extend(packet)
        repeated.write_bytes(retained)
        for name, path in (
            ("baseline", original),
            ("keyframe_suppression", suppressed),
            ("p_repeat", repeated),
        ):
            result = subprocess.run(
                [ffmpeg, "-v", "error", "-i", str(path), "-f", "null", "-"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            info = json.loads(
                run([ffprobe, "-v", "error", "-count_frames", "-show_streams", "-of", "json", str(path)])
            )
            reports.append(
                {
                    "experiment": name,
                    "decode_exit": result.returncode,
                    "decoded_frames": info["streams"][0].get("nb_read_frames"),
                    "reported_duration": info["streams"][0].get("duration"),
                    "decoder_messages": result.stderr[-1000:],
                }
            )
    return reports


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ffmpeg")
    parser.add_argument("--ffprobe")
    args = parser.parse_args()
    print(json.dumps(probe(args.ffmpeg, args.ffprobe), indent=2))
