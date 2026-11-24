import pytest
from typer.testing import CliRunner

from videobingus.cli import app
from videobingus.config import load
from videobingus.media import probe
from videobingus.render import render
from videobingus.timeline import build, read, save


def test_config_paths_and_unknown_fields(tmp_path):
    path = tmp_path / "project.yaml"
    path.write_text("audio: mix.wav\nsources: [footage]\n", encoding="utf-8")
    assert load(path).audio == tmp_path / "mix.wav"
    with pytest.raises(ValueError):
        load(path, {"typo": 1})
    with pytest.raises(ValueError):
        load(path, {"clips": {"duration": [5, 1]}})


def test_seeded_timeline_and_portability(project, tmp_path):
    first, second = build(project), build(project)
    assert first == second
    assert first["clips"][0]["start"] == 0
    assert first["clips"][-1]["end"] == first["frames"]
    for previous, current in zip(first["clips"], first["clips"][1:]):
        assert previous["end"] == current["start"]
        assert previous["source"] != current["source"]
    path = tmp_path / "plan.json"
    save(first, path)
    assert str(tmp_path).replace("\\", "\\\\") not in path.read_text(encoding="utf-8")
    assert read(path, ffmpeg=project.ffmpeg, ffprobe=project.ffprobe) == first


def test_render_smoke(project):
    plan = build(project)
    target = render(plan)
    info = probe(target, project.ffprobe)
    assert {s["codec_type"] for s in info["streams"]} == {"video", "audio"}
    assert abs(float(info["format"]["duration"]) - 2) < 1 / 12 + 0.03
    with pytest.raises(ValueError, match="already exists"):
        render(plan)
    preview = render(plan, target.with_name("preview.mp4"), start=0.5, duration=0.5)
    assert abs(float(probe(preview, project.ffprobe)["format"]["duration"]) - 0.5) < 0.1


def test_cli_help_and_errors():
    runner = CliRunner()
    assert runner.invoke(app, ["--help"]).exit_code == 0
    result = runner.invoke(app, ["render", "missing.wav", "missing-footage"])
    assert result.exit_code == 1
    assert "Error" in result.output


def test_platform_independent_decision_snapshot(monkeypatch):
    import videobingus.timeline as timeline
    from videobingus.config import Project

    monkeypatch.setattr(
        timeline, "probe", lambda *args: {"streams": [{"codec_type": "audio"}], "format": {"duration": "2"}}
    )
    monkeypatch.setattr(
        timeline,
        "discover",
        lambda *args: [{"path": "a.mp4", "duration": 3.2}, {"path": "b.mp4", "duration": 4.1}],
    )
    plan = build(
        Project(
            audio="mix.wav",
            sources=["footage"],
            seed=420,
            output={"resolution": [64, 48], "fps": 10},
            clips={"duration": [0.2, 0.5], "speed": [0.9, 1.1]},
        )
    )
    decisions = [
        (c["source"], c["start"], c["end"], round(c["offset"], 6), round(c["speed"], 6))
        for c in plan["clips"]
    ]
    assert decisions == [
        (1, 0, 2, 1.978202, 0.949231),
        (0, 2, 4, 2.508396, 1.005688),
        (1, 4, 6, 2.503329, 1.047124),
        (0, 6, 9, 1.58516, 0.969289),
        (1, 9, 14, 0.73214, 0.986752),
        (0, 14, 17, 1.583869, 0.928632),
        (1, 17, 20, 3.022751, 0.931779),
    ]
