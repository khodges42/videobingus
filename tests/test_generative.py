import numpy as np
import pytest

from videobingus.scenes.runtime import SceneContext, SceneRuntime


@pytest.mark.parametrize("kind", ["plasma", "tunnel", "rotozoom", "metaballs", "interference"])
def test_analytical_generators_are_deterministic_and_animated(kind):
    a, b = SceneRuntime(kind, seed=42), SceneRuntime(kind, seed=42)
    first = a.frame(SceneContext(0, 0, 0, 30), (160, 90))
    second = a.frame(SceneContext(2, 2, 60, 30), (160, 90))
    assert np.array_equal(second, b.frame(SceneContext(2, 2, 60, 30), (160, 90)))
    assert first.dtype == np.uint8 and first.shape == (90, 160, 3)
    assert np.mean(np.abs(first.astype(float) - second.astype(float))) > 2
    a.close()
    assert not a.data


def test_render_without_footage(project, tmp_path):
    from videobingus.config import load
    from videobingus.media import probe
    from videobingus.render import render
    from videobingus.timeline import build, read, save

    configured = load(
        overrides={
            "audio": project.audio,
            "sources": [],
            "seed": 42,
            "scenes": [{"type": "plasma"}, {"type": "tunnel"}],
            "ffmpeg": project.ffmpeg,
            "ffprobe": project.ffprobe,
            "output": {
                "path": tmp_path / "generated.mp4",
                "resolution": [160, 90],
                "fps": 12,
                "encoder_preset": "ultrafast",
            },
        }
    )
    plan = build(configured)
    assert plan["media"] == [] and all(c["source"] is None for c in plan["clips"])
    target = render(plan)
    assert abs(float(probe(target, project.ffprobe)["format"]["duration"]) - 2) < 0.1
    path = tmp_path / "plan.json"
    save(plan, path)
    assert read(path, ffmpeg=project.ffmpeg, ffprobe=project.ffprobe) == plan


def test_fit_defaults_to_bars_and_can_stretch():
    from videobingus.config import Output
    from videobingus.scenes.runtime import fit_frame

    assert Output().resolution == (1920, 1080) and Output().fit == "fit"
    square = np.full((100, 100, 3), 255, dtype=np.uint8)
    fitted = fit_frame(square, (160, 90))
    assert fitted[:, 0].max() == 0 and fitted[:, 80].min() == 255
    assert fit_frame(square, (160, 90), "stretch").min() == 255


@pytest.mark.parametrize(
    "kind",
    [
        "reaction_diffusion",
        "flow_field",
        "particle_field",
        "strange_attractor",
        "recursive_geometry",
        "cellular_automata",
        "physarum",
        "boids",
        "fluid_advection",
        "ifs",
        "starfield",
        "fractal",
        "domain_warp",
        "voronoi",
        "floor_cast",
        "wireframe",
    ],
)
def test_scene_algorithms_have_finite_bounded_state(kind):
    runtime = SceneRuntime(kind, seed=13, performance={"quality": "draft"})
    runtime.frame(SceneContext(0, 0, 0, 30), (128, 72))
    frame = runtime.frame(SceneContext(0.3, 0.3, 9, 30), (128, 72))
    assert frame.shape == (72, 128, 3) and frame.dtype == np.uint8
    assert np.std(frame) > 1
    for value in runtime.data.values():
        if isinstance(value, np.ndarray):
            assert np.isfinite(value).all()


def test_simulation_clock_is_independent_of_output_fps():
    a, b = SceneRuntime("reaction_diffusion", seed=1), SceneRuntime("reaction_diffusion", seed=1)
    for frame in range(16):
        a.frame(SceneContext(frame / 15, frame / 15, frame, 15), (96, 54))
    for frame in range(31):
        b.frame(SceneContext(frame / 30, frame / 30, frame, 30), (96, 54))
    assert a.tick == b.tick == 30
    assert np.array_equal(a.data["a"], b.data["a"])
    assert np.array_equal(a.data["b"], b.data["b"])


def test_structural_parameters_cannot_be_modulated():
    from videobingus.config import Project

    with pytest.raises(ValueError, match="initialization-only"):
        Project(
            audio="mix.wav",
            scenes=[{"id": "life", "type": "reaction_diffusion"}],
            modulation=[{"target": "scenes.life.feed", "source": "rms", "output_range": [0.02, 0.05]}],
        )
