import numpy as np
import pytest
from typer.testing import CliRunner

from videobingus.config import Project, load
from videobingus.effects.catalog import describe
from videobingus.scene_config import Selection
from videobingus.scenes.catalog import CATALOG
from videobingus.suites.compiler import compile_suite, export_project, load_suite, names


@pytest.mark.parametrize("name", names())
def test_builtin_suites_compile_to_ordinary_reproducible_projects(name):
    suite = load_suite(name)
    raw = compile_suite(suite, 42)
    assert raw == compile_suite(suite, 42)
    assert raw != compile_suite(suite, 43)
    project = Project(audio="mix.wav", **raw)
    assert project.suite is None and project.compiled_from == name
    budget = project.randomization
    assert len(project.effects.global_) <= budget.max_global_effects
    assert len(project.effects.per_clip) <= budget.max_scene_effects
    assert len(project.overlays) <= budget.max_overlays
    primary_cost = int(any(CATALOG[s.type]["cost"] == "high" for s in project.scenes))
    effects_cost = sum(describe(e.type)["cost"] == "high" for e in project.effects.all())
    overlays_cost = sum(
        CATALOG[o.source.split(":", 1)[1]]["cost"] == "high"
        for o in project.overlays
        if o.source.startswith("generator:") and o.source.split(":", 1)[1] in CATALOG
    )
    assert primary_cost + effects_cost + overlays_cost <= budget.max_expensive_processors


def test_suite_selection_palette_and_portable_export(tmp_path):
    suite = load_suite("acid_television")
    raw = compile_suite(
        suite,
        55,
        Selection(
            generators=["plasma", "metaballs"],
            effects=["optical_feedback", "analog_colorizer"],
            exclude_effect=["optical_feedback"],
            intensity=0.3,
        ),
    )
    project = Project(audio=tmp_path / "mix.wav", **raw)
    assert {s.type for s in project.scenes} == {"plasma", "metaballs"}
    assert {e.type for e in project.effects.all()} <= {"analog_colorizer"}
    output = tmp_path / "export" / "project.yaml"
    export_project(project, output)
    restored = load(output)
    assert restored.scenes == project.scenes
    assert restored.audio.resolve() == project.audio.resolve()
    assert restored.compiled_from == "acid_television"


def test_explicit_palette_is_not_replaced_by_identity_defaults():
    project = Project(audio="mix.wav", scenes=[{"type": "plasma"}], palette="acid")
    assert project.identity.palette_family == ["acid"]


def test_scene_trigger_preserves_simulation_bounds():
    from videobingus.scenes.runtime import SceneContext, SceneRuntime

    runtime = SceneRuntime("reaction_diffusion", seed=42, performance={"quality": "draft"})
    runtime.triggers = [
        {
            "source": "bass_onset",
            "action": "disturbance",
            "threshold": 0.5,
            "hysteresis": 0.1,
            "probability": 1,
            "cooldown": 0.1,
        }
    ]
    for frame in range(30):
        runtime.frame(
            SceneContext(frame / 30, frame / 30, frame, 30, audio={"bass_onset": frame % 10 == 0}), (96, 54)
        )
    assert any(s["time"] >= 0 for s in runtime.event_state.values())
    assert 0 <= runtime.data["b"].min() <= runtime.data["b"].max() <= 1


def test_audio_changes_simulation_instead_of_only_output_color():
    from videobingus.scenes.runtime import SceneContext, SceneRuntime

    silent, active = [SceneRuntime("flow_field", seed=42) for _ in range(2)]
    for frame in range(31):
        for runtime, energy in ((silent, 0), (active, 1)):
            runtime.frame(
                SceneContext(frame / 30, frame / 30, frame, 30, audio={"bass_energy": energy}),
                (96, 54),
                profiles=["sub_pressure"],
            )
    assert not np.array_equal(silent.data["positions"], active.data["positions"])


def test_custom_suite_generation_and_catalog_commands(tmp_path):
    from videobingus.cli import app

    runner = CliRunner()
    target = tmp_path / "suites"
    result = runner.invoke(
        app,
        [
            "suites",
            "generate",
            "--theme",
            "organic",
            "--variants",
            "2",
            "--palette-scheme",
            "analogous",
            "--output-dir",
            str(target),
        ],
    )
    assert result.exit_code == 0, result.output
    suite = load_suite(str(target / "organic-01.yaml"))
    assert len(suite.palettes) == 1
    assert Project(audio="mix.wav", **compile_suite(suite, 42)).scenes
    for command in (
        ["generators", "info", "reaction_diffusion", "--json"],
        ["effects", "info", "optical_feedback", "--json"],
        ["suites", "list"],
    ):
        result = runner.invoke(app, command)
        assert result.exit_code == 0, result.output


def test_hybrid_timeline_and_simultaneous_sources(project):
    from videobingus.render import render
    from videobingus.timeline import build

    configured = project.model_copy(deep=True)
    configured.scenes = Project(
        audio="mix.wav", scenes=[{"type": "tunnel", "params": {"texture_mix": 0.7}}]
    ).scenes
    configured.composition.scene_duration = (0.5, 0.5)
    configured.composition.max_scene_changes_per_minute = 120
    configured.composition.mode = "generative"
    plan = build(configured)
    assert all(c["scene"]["type"] == "tunnel" and c["source"] is not None for c in plan["clips"])
    assert render(plan).is_file()


@pytest.mark.parametrize("role", ["input", "mask", "displacement"])
def test_generated_layers_can_supply_inputs_masks_and_displacement(role):
    from videobingus.compositing import Layers
    from videobingus.config import Output
    from videobingus.effects.engine import Context, EffectEngine

    overlay = {
        "id": "field",
        "asset": {"path": "generator:plasma"},
        "start": 0,
        "end": 30,
        "opacity": 1,
        "role": role,
        "generator_params": {},
        "offset": 0,
    }
    grid = np.indices((54, 96)).sum(axis=0) % 7 * 35
    frame = np.repeat(grid[..., None], 3, axis=2).astype(np.uint8)
    context = Context(0, 30, 0, None, {}, np.random.default_rng(42))
    context.raw_frame = frame
    with Layers([overlay], None, Output(resolution=(96, 54)), EffectEngine([], 30, 42)) as layers:
        result = layers.composite(frame, context, {}, {})
    assert "field" in context.inputs and context.inputs["field"].shape == frame.shape
    assert np.array_equal(result, frame) == (role == "input")


def test_runtime_fork_keeps_overlapping_scene_states_independent():
    from videobingus.scenes.runtime import SceneContext, SceneRuntime

    outgoing = SceneRuntime("reaction_diffusion", seed=5)
    outgoing.frame(SceneContext(1, 1, 30, 30), (96, 54))
    incoming = outgoing.fork()
    retained = outgoing.data["b"].copy()
    incoming.frame(SceneContext(2, 2, 60, 30), (96, 54))
    assert np.array_equal(outgoing.data["b"], retained)
    assert not np.array_equal(incoming.data["b"], retained)


def test_suite_selection_overrides_also_apply_to_yaml_suite_references(project, tmp_path):
    from videobingus.cli import composition

    config = tmp_path / "suite-project.yaml"
    config.write_text("suite: artificial_life\n", encoding="utf-8")
    plan = composition(
        config=config,
        audio=project.audio,
        seed="42",
        generators="plasma",
        effects="analog_colorizer",
        exclude_effect=["optical_feedback"],
        ffmpeg=project.ffmpeg,
        ffprobe=project.ffprobe,
        resolution="96x64",
    )
    assert {s["type"] for s in plan["config"]["scenes"]} == {"plasma"}
    assert all(e["type"] != "optical_feedback" for e in plan["effects"])


def test_simulation_palette_profile_is_applied_to_rendering():
    from videobingus.scenes.runtime import SceneContext, SceneRuntime

    plain, colored = [SceneRuntime("reaction_diffusion", seed=42) for _ in range(2)]
    context = SceneContext(0, 0, 0, 30, audio={"high_energy": 1})
    a = plain.frame(context, (96, 54))
    b = colored.frame(context, (96, 54), profiles=["spectral_color"])
    assert not np.array_equal(a, b)
    assert np.array_equal(plain.data["b"], colored.data["b"])
