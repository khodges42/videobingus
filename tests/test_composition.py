from fractions import Fraction

import numpy as np
import pytest
from PIL import Image
from typer.testing import CliRunner

from videobingus.audio import analyze, at, events
from videobingus.cli import app
from videobingus.compositing import blend
from videobingus.config import Project, load
from videobingus.cue import parse, seconds
from videobingus.effects.engine import Context, EffectEngine, State, apply
from videobingus.effects.registry import PARAMETERS, defaults
from videobingus.media import discover, probe
from videobingus.render import render
from videobingus.timeline import build, read, save


def changed(project, updates):
    from videobingus.config import merge

    return Project.model_validate(merge(project.model_dump(by_alias=True), updates))


def test_all_presets_validate(project):
    from importlib.resources import files

    for path in files("videobingus.presets").iterdir():
        if path.name.endswith(".yaml"):
            configured = load(
                overrides={"preset": path.stem, "audio": project.audio, "sources": project.sources}
            )
            assert configured.preset == path.stem
    runner = CliRunner()
    assert "bass_reactive" in runner.invoke(app, ["presets", "list"]).output
    assert "horizontal_jitter" in runner.invoke(app, ["effects", "list"]).output


def test_effect_schema(project):
    for effect in [
        {"id": "tape", "type": "vhs", "nooise": 4},
        {"id": "tape", "type": "vhs", "noise": 999},
        {"id": "tape", "type": "fake"},
    ]:
        with pytest.raises(ValueError):
            changed(project, {"effects": {"global": [effect]}})
    with pytest.raises(ValueError, match="Unknown modulation"):
        changed(
            project,
            {"modulation": [{"target": "effects.missing.noise", "source": "rms", "output_range": [0, 1]}]},
        )


@pytest.mark.parametrize("kind", PARAMETERS)
def test_effect_pixels_and_state(kind):
    random = np.random.default_rng(5)
    frame = random.integers(0, 256, (48, 64, 3), dtype=np.uint8)
    context = Context(0, 30, 0, None, {}, random)
    params = defaults(kind)
    context.source_b = np.roll(frame, 3, axis=1)
    state = State()
    first = apply(kind, frame, params, context, state)
    context.index = 1
    second = apply(kind, frame, params, context, state)
    assert first.shape == second.shape == frame.shape
    assert first.dtype == second.dtype == np.uint8
    assert not np.shares_memory(first, frame) or kind in {"temporal_blend"}


def test_temporal_persistence():
    params = {"decay": 0.5}
    state = State()
    context = Context(0, 30, 0, None, {}, np.random.default_rng(1))
    white = np.full((10, 10, 3), 200, dtype=np.uint8)
    black = np.zeros_like(white)
    apply("temporal_blend", white, params, context, state)
    assert np.all(apply("temporal_blend", black, params, context, state) == 100)


def test_alpha_and_blend_modes():
    base = np.full((4, 4, 3), 100, dtype=np.uint8)
    layer = np.full((4, 4, 4), 200, dtype=np.uint8)
    layer[..., 3] = 0
    assert np.array_equal(blend(base, layer, "normal", 1), base)
    layer[..., 3] = 255
    assert np.all(blend(base, layer, "normal", 0.5) == 150)
    assert np.all(blend(base, layer, "difference", 1) == 100)
    assert np.all(blend(base, layer, "add", 1) == 255)
    assert np.all(blend(base, layer, "multiply", 1) < base)


def test_cue_and_plain_tracklists(tmp_path):
    assert seconds("01:02:74", cue=True) == pytest.approx(62 + 74 / 75)
    path = tmp_path / "mix.cue"
    path.write_text(
        '\ufeffFILE "mix.wav" WAVE\nPERFORMER "Artíst"\nTRACK 01 AUDIO\n'
        'TITLE "One"\nINDEX 01 00:00:00\nTRACK 02 AUDIO\nTITLE "Two"\nINDEX 01 00:01:00',
        encoding="utf-8",
    )
    tracks = parse(path, 2)
    assert tracks[1]["time"] == 1
    assert tracks[0]["artist"] == "Artíst"
    path.write_text(path.read_text(encoding="utf-8") + '\nFILE "another.wav" WAVE', encoding="utf-8")
    with pytest.raises(ValueError, match="Multi-file"):
        parse(path, 2)
    path = tmp_path / "tracks.txt"
    path.write_text("00:00 Artist - One\n00:01 Artist - Two", encoding="utf-8")
    assert parse(path, 2)[1]["title"] == "Two"
    with pytest.raises(ValueError):
        parse(path, 0.5)


def test_schedules_tracks_independent_randomness(project, tmp_path):
    cue = tmp_path / "tracks.txt"
    cue.write_text("00:00 Artist - One\n00:01 Artist - Two", encoding="utf-8")
    configured = changed(
        project,
        {
            "cue": cue,
            "clips": {"duration": [0.8, 1.5]},
            "effects": {
                "per_track": [{"id": "color", "type": "hue_shift"}],
                "events": [
                    {
                        "id": "tracking",
                        "type": "tracking_error",
                        "probability_per_second": 1,
                        "duration": [0.1, 0.1],
                        "cooldown": 0.3,
                    }
                ],
            },
        },
    )
    plan = build(configured)
    assert 12 in [c["start"] for c in plan["clips"]]
    per_track = [e for e in plan["effects"] if e["id"] == "color"]
    assert [(e["start"], e["end"]) for e in per_track] == [(0, 12), (12, 24)]
    activations = [e for e in plan["effects"] if e["id"] == "tracking"]
    for previous, current in zip(activations, activations[1:]):
        assert current["start"] >= previous["end"] + round(0.3 * 12) - 1
    no_effects = build(changed(configured, {"effects": {"per_track": [], "events": []}}))
    assert no_effects["clips"] == plan["clips"]


def test_audio_analysis(project, tmp_path):
    features = analyze(project.audio, project.ffmpeg, tmp_path / "cache")
    assert len(features["times"]) > 10
    assert max(features["bass_energy"]) == pytest.approx(1)
    assert at(features, 0.5)["rms"] > 0.8
    assert analyze(project.audio, project.ffmpeg, tmp_path / "cache") == features
    synthetic = {"times": [0, 0.5, 1, 1.5, 2], "bass_onset": [0, 1, 0, 1, 0]}
    assert events(synthetic, "bass_onset", 0.5, 0.1) == [0.5, 1.5]


def test_layered_reactive_render_and_plan(project, tmp_path):
    image = tmp_path / "logo α.png"
    Image.new("RGBA", (20, 20), (255, 0, 0, 128)).save(image)
    configured = changed(
        project,
        {
            "analysis": True,
            "effects": {
                "global": [
                    {"id": "tape", "type": "vhs", "intensity": 0.3},
                    {"id": "crt", "type": "crt", "order": 1},
                ],
                "per_clip": [
                    {"id": "negative", "type": "negative", "layer": "secondary", "probability": 0.5}
                ],
            },
            "overlays": [
                {"id": "logo", "source": str(image), "scale": 0.2, "position": "bottom_right"},
                {"id": "secondary", "source": str(project.sources[0]), "blend": "screen", "opacity": 0.2},
            ],
            "modulation": [
                {"target": "effects.tape.horizontal_jitter", "source": "rms", "output_range": [0, 4]}
            ],
        },
    )
    plan = build(configured)
    path = tmp_path / "plan.json"
    save(plan, path)
    restored = read(path, ffmpeg=project.ffmpeg, ffprobe=project.ffprobe)
    assert restored == plan
    output = render(restored)
    assert len(probe(output, project.ffprobe)["streams"]) == 2
    preview = render(restored, output.with_name("layered-preview.mp4"), start=0.25, duration=0.25)
    assert preview.is_file()


def test_generators_and_freeze_reverse(project):
    from videobingus.effects.registry import GENERATORS
    from videobingus.generators import generate

    context = Context(
        0, 12, 0, None, {"waveform": [0, 1, -1], "spectrum": [0.1, 0.5, 0.9]}, np.random.default_rng(1)
    )
    for kind in GENERATORS:
        assert generate(kind, (64, 48), context).shape == (48, 64, 3)
    configured = changed(
        project, {"clips": {"reverse_probability": 1, "short_source": "loop", "duration": [0.8, 1.2]}}
    )
    render(build(configured))
    configured.clips.freeze_probability = 1
    render(build(configured), overwrite=True)


def test_invalid_media_skipped(project):
    bad = project.sources[0] / "invalid.mp4"
    bad.write_bytes(b"not video")
    with pytest.warns(UserWarning):
        assert len(discover(project.sources, project.ffprobe)) == 2


def test_rational_fps_and_track_override(project, tmp_path):
    cue = tmp_path / "tracks.txt"
    cue.write_text("00:00 One\n00:01 Two", encoding="utf-8")
    configured = changed(
        project,
        {
            "cue": cue,
            "output": {"fps": "30000/1001"},
            "tracks": [
                {
                    "index": 2,
                    "sources": [project.sources[0] / "clip 0.mp4"],
                    "clips": {"duration": [0.1, 0.2]},
                }
            ],
        },
    )
    plan = build(configured)
    for clip in plan["clips"]:
        if clip["start"] >= round(Fraction(30000, 1001)):
            assert plan["media"][clip["source"]]["path"].endswith("clip 0.mp4")
            assert clip["end"] - clip["start"] <= 6


def test_preview_pixels_equal_without_temporal_history(project):

    plan = build(changed(project, {"effects": {"global": [{"id": "tape", "type": "vhs"}]}}))
    target = render(plan)
    short = render(plan, target.with_name("preview.mp4"), start=0.5, duration=0.5)
    # Lossy encoding changes pixels, but the first frames should remain close.
    import subprocess

    def frame(path, time):
        raw = subprocess.check_output(
            [
                project.ffmpeg,
                "-v",
                "error",
                "-ss",
                str(time),
                "-i",
                str(path),
                "-frames:v",
                "1",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "pipe:1",
            ]
        )
        return np.frombuffer(raw, dtype=np.uint8).astype(float)

    assert np.mean(np.abs(frame(target, 0.5) - frame(short, 0))) < 15


def test_cancel_process_cleans_child():
    import subprocess
    import sys

    from videobingus.platform import process

    child = None
    with pytest.raises(KeyboardInterrupt):
        with process([sys.executable, "-c", "import time; time.sleep(60)"], stdout=subprocess.PIPE) as child:
            raise KeyboardInterrupt
    assert child.poll() is not None


def test_transients_and_mux_sync(project, tmp_path):
    import subprocess
    import wave

    rate = 16000
    times = np.arange(rate * 2) / rate
    signal = np.zeros_like(times)
    for onset in (0.5, 1.5):
        relative = np.maximum(0, times - onset)
        signal += np.sin(2 * np.pi * 80 * relative) * np.exp(-relative * 25) * (times >= onset) * 0.7
    with wave.open(str(project.audio), "wb") as handle:
        handle.setparams((1, 2, rate, 0, "NONE", ""))
        handle.writeframes((signal * 32767).astype("<i2").tobytes())
    features = analyze(project.audio, project.ffmpeg, tmp_path / "cache")
    transients = events(features, "bass_onset", 0.5, 0.1)
    for expected in (0.5, 1.5):
        assert min(abs(t - expected) for t in transients) < 0.1
    configured = changed(
        project,
        {
            "analysis": True,
            "effects": {
                "events": [
                    {
                        "id": "bass",
                        "type": "block_glitch",
                        "trigger": "bass_onset",
                        "threshold": 0.5,
                        "duration": [0.1, 0.1],
                        "cooldown": 0.3,
                    }
                ]
            },
        },
    )
    plan = build(configured)
    assert len(plan["effects"]) == 2
    output = render(plan)
    decoded = np.frombuffer(
        subprocess.check_output(
            [
                project.ffmpeg,
                "-v",
                "error",
                "-i",
                str(output),
                "-vn",
                "-ac",
                "1",
                "-ar",
                str(rate),
                "-f",
                "f32le",
                "pipe:1",
            ]
        ),
        dtype="<f4",
    )
    count = min(len(signal), len(decoded))
    assert np.sqrt(np.mean((signal[:count] - decoded[:count]) ** 2)) < 0.02


def test_portable_media_root(project, tmp_path):
    import shutil

    plan = build(project)
    path = tmp_path / "plan.json"
    save(plan, path)
    moved = tmp_path / "moved"
    moved.mkdir()
    shutil.copy2(project.audio, moved / project.audio.name)
    shutil.copytree(project.sources[0], moved / project.sources[0].name)
    restored = read(path, moved, project.ffmpeg, project.ffprobe)
    assert restored["clips"] == plan["clips"]
    assert str(moved) in restored["config"]["audio"]
    assert render(restored).parent == moved


def test_crossfades_and_corrupt_plan(project):
    configured = changed(project, {"clips": {"crossfade": 0.25}})
    plan = build(configured)
    output = render(plan)
    assert abs(float(probe(output, project.ffprobe)["format"]["duration"]) - 2) < 0.1
    plan["clips"][1]["start"] += 1
    with pytest.raises(ValueError, match="gap"):
        render(plan, overwrite=True)


def test_cli_saved_plan_and_explicit_tools(project, tmp_path):
    path = tmp_path / "plan.json"
    save(build(project), path)
    result = CliRunner().invoke(
        app, ["render", "--plan", str(path), "--ffmpeg", project.ffmpeg, "--ffprobe", project.ffprobe]
    )
    assert result.exit_code == 0, result.output


def test_persistent_false_resets_at_clip_boundary():
    effect = {
        "id": "history",
        "type": "temporal_blend",
        "start": 0,
        "end": 10,
        "order": 0,
        "layer": "composite",
        "persist": False,
        "params": {"decay": 0.5},
        "intensity": 1,
        "attack": 0,
        "release": 0,
    }
    engine = EffectEngine([effect], 30, 420)
    frame = np.full((10, 10, 3), 200, dtype=np.uint8)
    context = Context(0, 30, 0, None, {}, np.random.default_rng(1))
    engine.process(frame, context)
    context.index = 1
    assert np.all(engine.process(np.zeros_like(frame), context) == 0)


def test_overlay_per_clip_schedule(project):
    configured = changed(
        project,
        {
            "effects": {"per_clip": [{"id": "hue", "type": "hue_shift", "layer": "secondary"}]},
            "overlays": [{"id": "secondary", "source": str(project.sources[0])}],
        },
    )
    plan = build(configured)
    assert [(e["start"], e["end"]) for e in plan["effects"]] == [
        (o["start"], o["end"]) for o in plan["overlays"]
    ]


def test_executable_discovery(monkeypatch, tmp_path):
    import sys

    from videobingus.platform import executable

    assert executable("python", sys.executable) == sys.executable
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(ValueError, match="was not found"):
        executable("not-ffmpeg")


def test_non_square_pixels_preserve_display_aspect(project, tmp_path):
    import subprocess

    from videobingus.decoder import decode

    path = tmp_path / "anamorphic.mp4"
    subprocess.run(
        [
            project.ffmpeg,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=white:s=96x72:r=12",
            "-vf",
            "setsar=2",
            "-t",
            "0.5",
            "-c:v",
            "libx264",
            str(path),
        ],
        check=True,
    )
    clip = {"offset": 0, "speed": 1, "reverse": False, "freeze": False}
    with decode(project.ffmpeg, path, clip, project.output, 1) as frames:
        frame = next(frames)
    assert frame[0].max() < 5
    assert frame[32].min() > 240
    assert frame[10].max() < 5


def test_audio_copy_and_fractional_duration(project, tmp_path):
    import subprocess

    audio = tmp_path / "mix.m4a"
    subprocess.run(
        [project.ffmpeg, "-v", "error", "-i", str(project.audio), "-t", "1.713", "-c:a", "aac", str(audio)],
        check=True,
    )
    configured = changed(project, {"audio": audio})
    plan = build(configured)
    target = render(plan)
    input_info, output_info = probe(audio, project.ffprobe), probe(target, project.ffprobe)
    stream = next(s for s in output_info["streams"] if s["codec_type"] == "audio")
    assert stream["codec_name"] == "aac"
    assert abs(float(output_info["format"]["duration"]) - float(input_info["format"]["duration"])) < 1 / 12
