import numpy as np
import pytest

from videobingus.config import Project
from videobingus.effects.engine import Context, EffectEngine, State, apply
from videobingus.effects.registry import defaults
from videobingus.signals import Signal, SignalBank


def context(index=0, frame=None, clip=0):
    return Context(
        index, 30, index / 30, None, {}, np.random.default_rng(index), clip_id=clip, raw_frame=frame
    )


@pytest.mark.parametrize("kind", ["optical_feedback", "display", "virtual_camera"])
def test_recapture_processors(kind):
    frame = np.zeros((72, 96, 3), dtype=np.uint8)
    frame[20:40, 30:60] = [220, 100, 30]
    state = State()
    params = defaults(kind)
    for index in range(6):
        result = apply(kind, frame, params, context(index), state)
        assert result.shape == frame.shape and result.dtype == np.uint8
    if kind == "optical_feedback":
        assert len(state.data["optical_history"]) == 1
        assert result.max() > 0


def test_feedback_above_unity_is_not_normalized():
    frame = np.full((48, 64, 3), 80, dtype=np.uint8)
    params = defaults("optical_feedback")
    params.update(
        gain=1.2,
        injection=0,
        clipping="hard",
        zoom=1,
        rotation=0,
        curvature=0,
        perspective=0,
        drift=0,
        persistence=0,
        saturation=1,
        hue=0,
    )
    state = State()
    first = apply("optical_feedback", frame, params, context(), state)
    result = first
    for index in range(1, 15):
        result = apply("optical_feedback", np.zeros_like(frame), params, context(index), state)
    assert result[24, 32].mean() > first[24, 32].mean()
    assert result.max() <= 255


def test_signal_determinism_and_dependency_validation():
    specs = {
        "lfo": Signal(type="lfo", frequency=1, waveform="triangle"),
        "hold": Signal(type="sample_hold", rate=3, smoothing=0.08),
        "walk": Signal(type="random_walk"),
        "envelope": Signal(type="envelope", source="lfo"),
    }
    first, second = SignalBank(specs, 420, 30), SignalBank(specs, 420, 30)
    for index in range(90):
        assert first.evaluate(index) == second.evaluate(index)
    with pytest.raises(ValueError, match="cycle"):
        Project(
            audio="mix.wav",
            sources=["footage"],
            signals={"a": {"type": "envelope", "source": "b"}, "b": {"type": "envelope", "source": "a"}},
        )


def test_procedural_modulation_does_not_require_audio_analysis():
    project = Project(
        audio="mix.wav",
        sources=["footage"],
        signals={"drift": {"type": "lfo"}},
        effects={"global": [{"id": "loop", "type": "optical_feedback"}]},
        modulation=[{"target": "effects.loop.rotation", "source": "drift", "output_range": [-2, 2]}],
    )
    assert not project.analysis


def test_inactive_state_lifecycle():
    effect = {
        "id": "loop",
        "type": "optical_feedback",
        "start": 0,
        "end": 2,
        "params": defaults("optical_feedback"),
        "order": 0,
        "layer": "composite",
        "persist": True,
        "attack": 0,
        "release": 0,
        "intensity": 1,
        "inactive": "clear",
    }
    engine = EffectEngine([effect], 30, 420)
    frame = np.full((48, 64, 3), 100, dtype=np.uint8)
    engine.process(frame, context(0))
    assert "loop" in engine.states
    engine.process(frame, context(2))
    assert "loop" not in engine.states


@pytest.mark.parametrize(
    "kind",
    [
        "analog_crossfade",
        "dirty_crossfade",
        "scanline_mixer",
        "luma_key",
        "chroma_key",
        "analog_logic",
        "feedback_transition",
        "glitch_switch",
    ],
)
def test_mixers_have_two_inputs_and_exact_transition_endpoints(kind):
    from videobingus.effects.mixers import mix

    a = np.full((48, 64, 3), [180, 30, 50], dtype=np.uint8)
    b = np.full((48, 64, 3), [20, 160, 200], dtype=np.uint8)
    p = defaults(kind)
    state = State()
    assert np.array_equal(mix(kind, a, b, p, context(), state, 0), a)
    midpoint = mix(kind, a, b, p, context(), state, 0.5)
    assert midpoint.shape == a.shape
    assert np.array_equal(mix(kind, a, b, p, context(), state, 1), b)


def test_two_decoder_transitions_and_exact_preview(project):
    from videobingus.media import probe
    from videobingus.render import render
    from videobingus.timeline import build

    project = Project.model_validate(
        {
            **project.model_dump(by_alias=True),
            "transitions": [{"type": "dirty_crossfade", "duration": [0.2, 0.3]}],
        }
    )
    plan = build(project)
    assert plan["transitions"]
    for transition in plan["transitions"]:
        assert transition["start"] == plan["clips"][transition["incoming"]]["start"]
        assert transition["end"] <= plan["clips"][transition["incoming"]]["end"]
    target = render(plan)
    assert abs(float(probe(target, project.ffprobe)["format"]["duration"]) - 2) < 0.1
    render(plan, target.with_name("exact.mp4"), start=0.5, duration=0.5, exact_history=True)


@pytest.mark.parametrize(
    "kind",
    [
        "sync_corruption",
        "dirty_enhancer",
        "chroma_corruption",
        "signal_overload",
        "signal_delay",
        "composite_video",
    ],
)
def test_signal_processors_are_finite_and_deterministic(kind):
    random = np.random.default_rng(8)
    frame = random.integers(0, 256, (72, 96, 3), dtype=np.uint8)
    p = defaults(kind)
    one, two = State(), State()
    for index in range(3):
        first = apply(kind, frame, p, context(index), one)
        second = apply(kind, frame, p, context(index), two)
        assert np.array_equal(first, second)
        assert first.shape == frame.shape and first.dtype == np.uint8


def test_signal_math_roundtrip_and_wavefold():
    from videobingus.effects.signal_math import fold, to_rgb, to_ycc

    rgb = np.random.default_rng(1).random((20, 30, 3)).astype(np.float32)
    assert np.max(np.abs(to_rgb(to_ycc(rgb)) - rgb)) < 1e-5
    assert np.allclose(fold(np.array([0, 0.5, 1, 1.5, 2])), [0, 0.5, 1, 0.5, 0])


def test_composite_carrier_is_not_rgb_separation():
    frame = np.repeat(((np.indices((48, 64))[1] % 3) * 100).astype(np.uint8)[..., None], 3, axis=2)
    p = defaults("composite_video")
    p["quality"] = "carrier"
    out = apply("composite_video", frame, p, context(), State())
    assert np.any(np.max(out, axis=2) != np.min(out, axis=2))


@pytest.mark.parametrize(
    "kind",
    [
        "spatial_synth",
        "analog_colorizer",
        "oscilloscope_xy",
        "vectorscope",
        "waveform_monitor",
        "scan_displacement",
    ],
)
def test_synthesis_processors(kind):
    frame = np.random.default_rng(1).integers(0, 256, (72, 96, 3), dtype=np.uint8)
    ctx = context(frame=frame)
    time = np.arange(1024) / 16000
    ctx.audio["stereo"] = np.column_stack([np.sin(time * 500), np.cos(time * 500)])
    state = State()
    first = apply(kind, frame, defaults(kind), ctx, state)
    assert first.shape == frame.shape and first.dtype == np.uint8
    assert np.any(first)


def test_spatial_patterns_and_test_generators():
    from videobingus.effects.synthesis import SPATIAL_PATTERNS, TEST_PATTERNS
    from videobingus.generators import generate

    for kind in SPATIAL_PATTERNS | TEST_PATTERNS:
        first = generate(kind, (96, 72), context())
        assert first.shape == (72, 96, 3)
        assert np.any(first)


def test_xy_uses_paired_samples():
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    ctx = context()
    left = np.linspace(-0.8, 0.8, 200)
    ctx.audio["stereo"] = np.column_stack([left, left])
    first = apply("oscilloscope_xy", frame, defaults("oscilloscope_xy"), ctx, State())
    ctx.audio["stereo"] = np.column_stack([left, -left])
    second = apply("oscilloscope_xy", frame, defaults("oscilloscope_xy"), ctx, State())
    assert np.mean(np.abs(first.astype(float) - second.astype(float))) > 1


def test_datamosh_motion_stays_within_incoming_scene():
    random = np.random.default_rng(42)
    outgoing = np.zeros((72, 96, 3), dtype=np.uint8)
    outgoing[..., 0] = random.integers(20, 250, (72, 96), dtype=np.uint8)
    incoming = np.zeros_like(outgoing)
    incoming[..., 1] = random.integers(0, 255, (72, 96), dtype=np.uint8)
    params = defaults("simulated_datamosh")
    params.update(
        corruption=0,
        persistence=1,
        recovery=0,
        refresh_probability=0,
        color_retention=1,
        motion_amplification=1,
        quantization=0.1,
        block_size=4,
    )
    state = State()
    apply("simulated_datamosh", outgoing, params, context(0, outgoing, 0), state)
    first = apply("simulated_datamosh", incoming, params, context(1, incoming, 1), state)
    assert np.all(state.data["last_flow"] == 0)
    assert first[..., 0].mean() > 50
    shifted = np.roll(incoming, 3, axis=1)
    second = apply("simulated_datamosh", shifted, params, context(2, shifted, 1), state)
    assert np.median(state.data["last_flow"][15:-15, 15:-15, 0]) > 1
    assert second[..., 0].mean() > 50


@pytest.mark.parametrize(
    "mode",
    [
        "macroblock",
        "motion_field",
        "block_persist",
        "partial_replace",
        "pixel_sort",
        "horizontal_streak",
        "vertical_streak",
        "bit_plane",
        "bit_depth",
        "quantization",
        "frame_repeat",
        "scanline_buffer",
        "delayed_regions",
        "slit_scan",
    ],
)
def test_digital_modes(mode):
    frame = np.random.default_rng(5).integers(0, 256, (72, 96, 3), dtype=np.uint8)
    p = {**defaults("digital_corruption"), "mode": mode}
    state = State()
    for index in range(3):
        source = np.roll(frame, index, axis=1)
        result = apply("digital_corruption", source, p, context(index, source), state)
        assert result.shape == frame.shape and result.dtype == np.uint8
    assert len(state.data["digital_history"]) <= p["delay"]


def test_multiple_modulators_have_independent_smoothing():
    from videobingus.audio import Modulator
    from videobingus.config import Modulation

    bindings = [
        Modulation(target="effects.loop.rotation", source="rms", output_range=(0, 2), smoothing=0),
        Modulation(target="effects.loop.rotation", source="bass_energy", output_range=(0, 3), smoothing=0),
    ]
    effects, _ = Modulator(bindings, 30).values_at({"rms": 1, "bass_energy": 1})
    assert effects["loop"]["rotation"] == 5
    bindings[1].combine = "multiply"
    effects, _ = Modulator(bindings, 30).values_at({"rms": 1, "bass_energy": 1})
    assert effects["loop"]["rotation"] == 6
    bindings[1].combine = "replace"
    effects, _ = Modulator(bindings, 30).values_at({"rms": 1, "bass_energy": 1})
    assert effects["loop"]["rotation"] == 3


def test_sample_hold_trigger_and_slew():
    bank = SignalBank(
        {
            "held": Signal(type="sample_hold", trigger="bass_onset", smoothing=0),
            "slewed": Signal(type="lfo", waveform="square", frequency=2, slew=0.5),
        },
        420,
        30,
    )
    previous = None
    held_values = []
    for index in range(60):
        values = bank.evaluate(index, {"bass_onset": 1 if index in {10, 30} else 0})
        held_values.append(values["held"])
        if previous is not None:
            assert abs(values["slewed"] - previous) <= 0.5 / 30 + 1e-7
        previous = values["slewed"]
    assert len(set(held_values[:10])) == 1
    assert held_values[10] != held_values[9]
    assert len(set(held_values[10:30])) == 1


def test_internal_resolution_change_resets_incompatible_history():
    image = np.full((120, 160, 3), 100, dtype=np.uint8)
    state = State()
    p = defaults("optical_feedback")
    p["internal_height"] = 64
    apply("optical_feedback", image, p, context(), state)
    p["internal_height"] = 48
    result = apply("optical_feedback", image, p, context(1), state)
    assert result.shape == image.shape
    assert state.data["optical_history"][-1].shape[0] == 48


def test_explicit_delayed_input_and_current_cycle_rejection():
    with pytest.raises(ValueError, match="earlier layers"):
        Project(
            audio="mix.wav",
            sources=["footage"],
            effects={"global": [{"id": "key", "type": "luma_key", "input_b": "composite"}]},
        )
    project = Project(
        audio="mix.wav",
        sources=["footage"],
        effects={"global": [{"id": "key", "type": "luma_key", "input_b": "previous:composite"}]},
    )
    assert project.effects.global_[0].input_b == "previous:composite"


def test_phase_one_demo_cli(project, tmp_path):
    from typer.testing import CliRunner

    from videobingus.cli import app

    target = tmp_path / "demo.mp4"
    result = CliRunner().invoke(
        app,
        [
            "effects",
            "demo",
            "optical_feedback",
            "--duration",
            ".5",
            "--resolution",
            "96x64",
            "--fps",
            "12",
            "--param",
            "gain=1.02",
            "--ffmpeg",
            project.ffmpeg,
            "--ffprobe",
            project.ffprobe,
            "--output",
            str(target),
            "--profile",
        ],
    )
    assert result.exit_code == 0, result.output
    assert target.is_file()
    assert "ms/frame" in result.output


def test_continuous_update_and_scheduled_reset():
    frame = np.full((48, 64, 3), 100, dtype=np.uint8)
    base = {
        "id": "hold",
        "type": "temporal_blend",
        "start": 0,
        "end": 1,
        "params": defaults("temporal_blend"),
        "order": 0,
        "layer": "composite",
        "persist": True,
        "attack": 0,
        "release": 0,
        "intensity": 1,
        "inactive": "update",
        "reset_times": [2 / 30],
    }
    engine = EffectEngine([base], 30, 420)
    engine.process(frame, context(0))
    black = np.zeros_like(frame)
    assert np.array_equal(engine.process(black, context(1)), black)
    assert engine.states["hold"].previous.mean() > 0
    engine.process(black, context(2))
    assert engine.states["hold"].previous.mean() == 0


def test_current_layer_inputs_follow_configuration_order(project):
    from videobingus.compositing import Layers
    from videobingus.timeline import build

    configured = Project.model_validate(
        {
            **project.model_dump(by_alias=True),
            "overlays": [
                {"id": "z", "source": "generator:blue_vcr"},
                {"id": "a", "source": "generator:black"},
            ],
            "effects": {
                "global": [
                    {
                        "id": "logic",
                        "type": "analog_logic",
                        "layer": "a",
                        "input_b": "z",
                        "operation": "maximum",
                        "channels": "rgb",
                        "mix": 1,
                    }
                ]
            },
        }
    )
    plan = build(configured)
    frame = np.zeros((64, 96, 3), dtype=np.uint8)
    ctx = context(frame=frame)
    ctx.inputs["primary"] = frame
    engine = EffectEngine(plan["effects"], 12, 420)
    with Layers(plan["overlays"], project.ffmpeg, project.output, engine, ["z", "a"]) as layers:
        layers.composite(frame, ctx, {}, {})
    assert ctx.inputs["a"][..., 2].mean() > 100


def test_history_memory_budget_is_enforced():
    from videobingus.effects.recapture import retain

    image = np.zeros((720, 1280, 3), dtype=np.float32)
    with pytest.raises(ValueError, match="64 MiB"):
        retain(State(), "history", image, 8)


def test_feedback_exact_history_preview(project):
    import subprocess

    from videobingus.render import render
    from videobingus.timeline import build

    configured = Project.model_validate(
        {
            **project.model_dump(by_alias=True),
            "effects": {"global": [{"id": "loop", "type": "optical_feedback"}]},
            "signals": {"drift": {"type": "random_walk", "rate": 2}},
            "modulation": [{"target": "effects.loop.rotation", "source": "drift", "output_range": [-2, 2]}],
        }
    )
    plan = build(configured)
    full = render(plan)
    short = render(plan, full.with_name("exact-feedback.mp4"), start=1, duration=0.5, exact_history=True)

    def first(path, start):
        raw = subprocess.check_output(
            [
                project.ffmpeg,
                "-v",
                "error",
                "-ss",
                str(start),
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

    assert np.mean(np.abs(first(full, 1) - first(short, 0))) < 12
