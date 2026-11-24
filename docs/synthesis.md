# Video synthesis extension

## Design

The existing registry and ordered frame pipeline remain authoritative. Processors have four roles: single-frame processors, explicit two-input mixers, delayed stateful processors, and spatial sources. Transitions keep two independent segment decoders alive over planned, integer-frame overlaps. Output duration and soundtrack timing do not change. No frame-tail queue is needed.

Current-frame layer inputs and `previous:<layer>` inputs are separate. Recursive processors read their bounded history before writing this frame. Feedback therefore always has at least one frame of delay. Layer references follow processing order; unavailable current inputs are errors, never implicit recursive evaluation.

Control signals are deterministic, frame-indexed scalar values. Spatial signals are normalized image arrays, sampled in raster coordinates. Named controls do not constitute a patch graph or expression language. Signal dependencies must be acyclic. Effects retain their existing scheduling modes, with clip-boundary and transition scheduling added.

Analog chains use floating-point, full-range BT.601-derived Y/Cb/Cr: Y = .299R + .587G + .114B, Cb = (B-Y)/1.772, Cr = (R-Y)/1.402; RGB and Y nominally span 0–1, chroma −.5–.5. These are gamma-encoded signal values, not linear-light radiometry. Over-range values remain meaningful until an explicit limiter or RGB output clips them. Adjacent compatible processors share this representation. Composite-carrier processing is a simplified scanline experiment, not a television encoder.

## Research and aesthetic references

| Reference | Principle and implementation direction |
| --- | --- |
| [LZX learning material](https://lzxindustries.net/docs/getting-started/learn), [signal standard](https://lzxindustries.net/docs/guides/standards) | Normalized voltage-like ramps, oscillators, comparators and image-controlled modulation. Scalar controls and spatial oscillators remain distinct here. |
| [BPMC](https://bpmcglitch.com/), [Fluxus Duo strategy demonstration](https://vimeo.com/338183598) | Circuit-bent processing and unstable mixing inspire coherent sync disagreement, enhancement overload and chroma failures. Internal proprietary circuits are not reproduced. |
| [Tachyons+ equipment](https://tachyonsplus.com/gear), [Dreamweapon demonstration](https://www.youtube.com/watch?v=lpk-4QHtB2E) | Unstable color boundaries, bleed, damaged enhancement and recapture are aesthetic references. |
| [Roland/Edirol V-4 manual](https://static.roland.com/assets/media/pdf/v4_manual_e1.pdf), [Panasonic WJ-MX50](https://partner.connect.panasonic.com/jp-ja/products-services/lineup/WJ-MX50) | Independent buses, fader mixing, luminance/chroma keys and digital effects motivate explicit A/B processors. Dirty sync is an added failure simulation, not a claim about normal mixer behavior. |
| [Dave Jones Design](https://www.djdesign.com/), [Jones's design history](https://www.videohistoryproject.org/dave-jones-design-dave-jones-1998) | Luminance colorizing, independent channel thresholds, polarity, clipping and diode-style min/max mixing. |
| [Sandin and Rutt/Etra archive](https://www.vasulka.org/archive/LinzONE/catalogue/AE043.pdf) | Sandin's patched image processors motivate composable signal operations; Rutt/Etra's raster deflection motivates luminance-elevated scanlines. The implementation is 2D raster drawing, not a 3D beam simulation. |
| [Wobbulator operation and construction](https://www.videohistoryproject.org/raster-manipulation-unit-operation-and-construction) | External signals alter raster deflection. Here spatial oscillators and luminance deform sampling coordinates or drawn scanlines. No hardware construction is involved. |
| [Tektronix video measurement reference](https://download.tek.com/document/25W_7247_1_rfs.pdf), [XY chroma measurement](https://www.tek.com/en/support/faqs/why-do-i-get-flat-line-signal-vectorscope-display-mode-when-i-apply-75-or-100-color-bar) | Waveform monitors measure position versus signal level; vectorscopes plot color differences. XY audio traces must use paired stereo samples or explicitly selected synthesized signals. These displays are visualization tools, not calibrated instruments. |
| [Video feedback systems study](https://files.eric.ed.gov/fulltext/ED067855.pdf), [Exploratorium feedback exhibit](https://annex.exploratorium.edu/complexity/exhibit/feedback.html) | Display-camera recursion, transformed on each pass, with saturation, delay and incoming injection. This differs from a convex frame echo. |
| [BAVC time-base error reference](https://github.com/bavc/avaa/blob/master/_artifacts/time_base_error.md) | Timing errors cause flagging, skew and tearing. Correlated line offsets and recoverable loss approximate these artifacts without corrupting actual output sync. |
| [OpenCV optical flow](https://docs.opencv.org/4.x/d4/dee/tutorial_optical_flow.html) | Estimate motion within the incoming scene, then warp retained older imagery. Never estimate the primary motion field across an unrelated cut. |
| [FFmpeg bitstream filters](https://ffmpeg.org/ffmpeg-bitstream-filters.html) | Packet dropping and packed B-frame handling are not reliable datamoshing by themselves. A codec experiment must validate decoding and frame counts on bounded segments before becoming a feature. |
| [VideoLAN effect sources](https://github.com/videolan/vlc/tree/master/modules/video_filter), [VideoLAN demonstration script](https://github.com/videolan/vlc/blob/master/doc/demo.sh) | Psychedelic color cycling, gradients, waves and motion processing provide compositional references; VLC is not a dependency. |

## Configuration

All existing projects, presets, command names and version-1 plans remain supported. The old `feedback` and `datamosh` algorithms keep their behavior; use `optical_feedback` and `simulated_datamosh` for the new implementations. Weighted project `transitions` override `clips.crossfade`. Transition duration is capped to the two neighboring clip intervals; outgoing source regions extend and may loop, but the output timeline never extends. A single-frame transition selects the incoming source.

```yaml
seed: 420
audio: ./mix.flac
sources: [./footage]
transitions:
  - type: cut
    weight: 5
  - type: dirty_crossfade
    weight: 3
    duration: [0.5, 2]
    intensity: [0.2, 0.8]
    params:
      tearing: 30
  - type: luma_key
    weight: 1
    duration: [0.5, 2]
signals:
  camera_drift:
    type: lfo
    waveform: triangle
    frequency: 0.07
  unstable_voltage:
    type: sample_hold
    rate: 3.5
    smoothing: 0.08
effects:
  global:
    - id: feedback
      type: optical_feedback
      gain: 1.02
      zoom: 1.025
      mode: normal
      injection: 0.18
      preserve_state_across_clips: true
  transitions:
    - id: sync
      type: sync_corruption
      loss: 0.6
      recovery: 0.5
      release: 0.3
  events:
    - id: mosh
      type: simulated_datamosh
      trigger: clip_boundary
      probability: 0.18
      duration: [1, 5]
      release: 0.5
      refresh_probability: 0.08
modulation:
  - target: effects.feedback.rotation
    source: camera_drift
    output_range: [-1.2, 1.2]
  - target: effects.sync.horizontal_phase
    source: unstable_voltage
    output_range: [-16, 16]
```

Common effect controls retain their existing meanings: intensity and probability 0–1; activation `duration` is an ordered pair in seconds; cooldown, attack and release are seconds; explicit integer `order` sorts each chain. `effects.transitions` activates ordinary processors for each planned A/B overlap. Events additionally accept `trigger: clip_boundary` and `trigger: transition`, alongside random, track, bass, onset and energy triggers. A cut is a clip boundary but has no transition interval. A/B mixers can be used as normal effects with `input_b: <earlier-layer-id>` or `input_b: previous:<layer-id>`. Their normal input A is the image entering that point in the chain.

Current layers are evaluated primary → overlays in configured order → composite. Current input references must point to an earlier layer. Delayed references read the last completed output of that layer, with black initialization when no previous image exists. Inactive overlays supply black. Layer input references use RGB images before placement, blend opacity and alpha compositing. The composite cannot reference itself in the current frame. This keeps recursive relationships explicit and delayed.

Generator examples:

```yaml
generators:
  - type: rings
    probability: 0.1
    duration: [1, 3]
    params:
      frequency: 8
      waveform: triangle
overlays:
  - id: scope
    source: generator:oscilloscope_xy
    generator_params:
      gain: 2
      decay: 0.9
    blend: screen
    opacity: 0.4
    scale: 0.35
    position: bottom_right
```

Spatial sources accept frequency, phase, orientation, amplitude, offset, drift, frequency_b, waveform and internal_height from `spatial_synth`. Static test patterns have no parameters. Their generator name determines the pattern; generators do not expose an unrestricted composition graph. `spatial_synth` as an effect combines footage with spatial signals using its `operation` and `output`. Use `luma_key.mask` for generator-driven keying, `output: displace` for distortion maps, and `output: colorize` for signal-driven colorization. Generator scope sources use the current raw footage for video measurement; normal scope effects measure their actual chain input. `color_bars`, `alignment_grid`, `grayscale_ramp`, `crosshatch`, and `sync_pattern` are test images, not calibrated broadcast timing signals.

## Virtual control signals

Controls are evaluated once per output frame in dependency order. Random values use stable names, seed and sample index. Controls are evaluated from frame zero even for an approximate video preview, so sample-and-hold, envelope, random-walk, smoothing and slew histories remain reproducible. Control signal rates above half the output frame rate alias and are intended only for deliberate experiments. They do not create video-rate spatial oscillators.

| Field | Default / allowed values | Meaning |
| --- | --- | --- |
| `type` | `lfo`; `smooth_random`, `sample_hold`, `random_walk`, `envelope`, `audio`, `track_time`, `transition_progress` | Scalar source algorithm. |
| `waveform` | `sine`; `triangle`, `sawtooth`, `square` | LFO waveform. |
| `frequency` | 0.1; 0–120 Hz | LFO cycles per second. |
| `phase` | 0; finite number | LFO phase in cycles. |
| `amplitude`, `offset` | 1 (0–100), 0 (finite) | Scale and bias. |
| `bipolar` | false | Base 0–1 becomes −1–1 before amplitude/offset. |
| `attenuation` | 1; −10–10 | Additional signed gain. |
| `smoothing` | 0; 0–30 s | Exponential time constant. |
| `slew` | 0; 0–100 units/s | Maximum output change per second; zero disables limiting. |
| `quantization` | 0; integer 0–256 | Number of steps across one unit; 0/1 disables. |
| `rate` | 1; >0–120 Hz | Random knot / sample-and-hold clock rate. |
| `trigger` | null; built-in or named control | Rising threshold crossing samples a new held voltage, replacing the clock. |
| `source` | `rms`; built-in or named control | Audio follower or envelope input. |
| `threshold` | 0.5; 0–1 | Envelope gate / sample-and-hold trigger level. |
| `attack`, `release` | 0.05, 0.5; >0–30 s | Envelope rise/fall time constants. |
| `step` | 0.15; >0–1 | Maximum bounded random-walk step. |

`smooth_random` interpolates hashed random knots using a smoothstep curve. Random walks take bounded signed steps at their clock rate and clamp to 0–1. Envelopes are attack/release followers of a threshold gate. Named dependencies are checked for missing references and cycles. Unused controls are still validated and evaluated.

Built-ins are `rms`/`amplitude`, `bass_energy`, `mid_energy`, `high_energy`, `flux`, `bass_onset`, `onset`, `track_time`, and `transition_progress`. Audio sources require `analysis: true`; procedural-only projects do not. Track-local time is in seconds (use amplitude/attenuation to scale it). Transition progress is 0–1 during an overlap and zero otherwise. These do not require audio analysis.

Modulation maps a control into `output_range`. Bipolar named controls are first remapped from −1–1 to 0–1. Amplitude/offset can deliberately extrapolate beyond that range; the final parameter is clamped to its registry bounds. `smoothing` on a modulation binding is a separate time constant in seconds. Multiple bindings for a target are evaluated in list order: the first establishes the value, then `combine: add` (default), `replace`, or `multiply` combines subsequent mapped values. Each binding has independent smoothing. Numeric parameters and intensity are modulatable; categorical options, palettes and tap lists are not. Overlay opacity has the same combination rules.

## Lifecycle and memory

Initialization creates empty state; activation starts an envelope and samples parameter ranges. Per-frame processing reads delayed buffers before appending current output. Clip and track boundaries are delivered through frame context. Deactivation stops output contribution, subject to the release envelope. Disposal clears instance state and closes all input processes.

`inactive: retain` (default) freezes state while inactive. `clear` discards it at deactivation. `update` keeps processing the current layer without contributing to the output, after the first activation. Set `reset_on: [activation, clip, track]` to choose reset boundaries, or `reset_times: [30, 90]` for explicit timeline seconds. `persist: false` resets at clip boundaries; `preserve_state_across_clips` is an alias for `persist`. Retaining state across clips is the default. `release` blends every processor back into its underlying video; it does not reduce internal feedback gain or overwrite retained state.

| Processor | Retained state / behavior |
| --- | --- |
| `optical_feedback` | 1–30 delayed float RGB recaptures plus one display-persistence frame. Delay is always at least one frame. Gain may exceed one; explicit hard or tanh limiting bounds the loop. |
| `display` | One phosphor-persistence frame; current content blends with prior display. |
| `virtual_camera` | Coordinate grid only; coherent drift is time-indexed. |
| `sync_corruption` | Stable phases; neighboring lines share smooth timing errors. Loss has an activation recovery envelope and slow recurring excursions. |
| `dirty_enhancer`, `chroma_corruption`, `signal_overload`, `composite_video` | Coordinate maps; no temporal image history. Adjacent equal-resolution signal processors share float Y/Cb/Cr. |
| `signal_delay` | Up to 30 prior Y/Cb/Cr frames, selected before adding this frame. Spatial-only taps use current signal and need no history. |
| `feedback_transition` | One transformed old-image frame, reset for each transition. Other mixers are stateless or use deterministic time-indexed switching patterns. |
| `spatial_synth` | Coordinate maps and an optional fixed raster-noise field. |
| `analog_colorizer`, `scan_displacement` | Coordinate maps, no temporal image history. |
| Scope processors | One phosphor frame; use maximum of this trace and decaying prior trace. |
| `simulated_datamosh` | Retained image, frozen reference, previous source gray image, last motion field. Scene changes reset motion estimation, never the retained image unless requested. |
| `digital_corruption` | Bounded delay queue plus mode-specific held image or slit canvas. `block_persist` stores its processed result; partial replacement stores source history. |

Histories reject configurations exceeding 64 MiB per queue, with instructions to reduce `internal_height` or delay. They never silently reduce the requested delay. Coordinate caches retain only the current size. Changing internal resolution clears image history. `internal_height` is capped to the current input height and preserves aspect ratio; spatial pixel controls use those internal pixels. Integer-like controls (delay, block size, scan spacing, density, bits) round to the nearest integer.

Approximate previews process a three-second warm-up by default. `--warmup SECONDS` changes it; `--exact-history` processes from frame zero at preview resolution and encodes only the selected interval. Exact-history here means exact pipeline history at that resolution, not pixel equivalence to a differently sized or differently encoded full render. Stereo XY uses a bounded, trailing 2,048-sample window decoded separately from the untouched soundtrack; approximate previews rebuild that short audio history.

## Techniques and limitations

`analog_crossfade` crossfades luma and chroma separately with gain, bleed and nonlinear fader response. `dirty_crossfade` adds midpoint-weighted raster and chroma disagreement. Scanline patterns switch coherent groups rather than unrelated pixels. Luma keys use actual luminance or selected spatial masks; chroma keys measure Cb/Cr distance from a hue/saturation target and attenuate spill. Analog logic applies mathematical operations in RGB or selected Y/Cb/Cr channels. Transition endpoints are exactly A and B; standalone keyers/mixers use their explicit `mix` parameter.

`optical_feedback` injects incoming video into delayed imagery, then applies display treatment and virtual-camera geometry, focus and exposure. The recapture enters the delay buffer. Additive gain above unity can intentionally become saturated; use normal/difference modes, lower injection, or soft clipping for more detail. Black borders and camera geometry supply structure around bright interiors. Soft clipping is tanh, not automatic normalization. Chroma-key feedback gates by saturation rather than selecting an arbitrary hue; use the two-input `chroma_key` processor for targeted chroma keying.

Signal overload combines gain/bias with true absolute-value rectification and triangular wavefolding, not ordinary contrast. Dirty enhancement differentiates and delays luminance while smearing chroma. Composite `quality: carrier` modulates Cb/Cr onto a spatial carrier, low-passes luma, and demodulates the residual with intentional phase and bandwidth errors. `fast` approximates leakage from luma detail and chroma. Both model artifacts in scanline space, omit blanking/color-burst standards, and are not NTSC/PAL encoders. Sync corruption only deforms frames; output synchronization remains valid.

The colorizer maps luminance through RGB ramps, independent channel thresholds and phase offsets, optional hard bands or wavefolding. Spatial synthesis uses ramps/oscillators and luma-controlled phase; combination modes use a second luminance-derived oscillator. Wireframe scan displacement draws 2D scanlines elevated by luminance and spatial/audio modulation; it is not a 3D beam model.

XY defaults to actual paired stereo samples. `bands` compares FFT-filtered bass and midrange from the left input; `phase_shift` uses its Hilbert quadrature; `oscillator` explicitly selects a procedural Lissajous source. Input amplitude is not automatically normalized: use `gain`. Vectorscopes plot source Cb/Cr density, waveform monitors plot horizontal position against luminance. They are uncalibrated artistic monitors. Scope sources or overlays without source imagery show only a baseline until imagery is available.

`simulated_datamosh` estimates Farneback optical flow at internal resolution, resamples to macroblocks, quantizes and optionally corrupts the field, warps retained imagery, and selectively refreshes regions. The first frame of a new scene has a zero motion estimate before optional field corruption; subsequent flow comes only from consecutive frames of that scene. `frozen` warps a fixed reference each frame; `accumulate` retains part of the prior motion field; `refresh` emphasizes selective refresh with the supplied probability; `recovery` progressively returns to the current image. `motion_transfer` is the default accumulation of image history under live motion. Flat textures, occlusions, cuts inside a source asset, and aperture ambiguities limit optical-flow accuracy. Timeline clip boundaries are known; internal edits inside a video file are not automatically classified.

Digital modes remain separate from analog processing: block motion/displacement, persistent blocks, partial prior-frame replacement, threshold-masked horizontal pixel sorting, streaks, XOR bit planes, bit-depth reduction, noisy quantization, held frames, scanline delays, delayed regions and temporal slit scanning. Sorting is row-wise luminance ordering; the threshold/mask selects where sorted pixels replace the source. `slit_scan` captures moving vertical strips into a retained canvas. These are decoded-frame operations, not compressed-bitstream errors.

## Auditioning and verification

```text
uv run videobingus effects demo optical_feedback --input footage.mp4 --param gain=1.02 --param zoom=1.03 --duration 15 -o feedback.mp4
uv run videobingus effects demo dirty_crossfade --input a.mp4 --second-input b.mp4 --duration 10 -o mixer.mp4
uv run videobingus effects demo oscilloscope_xy --param gain=3 --duration 10 -o scope.mp4
uv run videobingus presets demo raster_bender --duration 10 -o raster.mp4
uv run videobingus effects list optical_feedback
```

Demos synthesize bounded stereo audio, use moving test patterns for omitted video inputs, and force one cut between the two audition sources. They accept seed, resolution, fps, explicit FFmpeg/FFprobe paths, overwrite protection and `--profile`. `--param name=value` accepts YAML scalars and structured values. Original media are read-only. Preset auditions deliberately shorten clip durations; ordinary rendering preserves preset/project durations.

Tests cover original workflows, signal determinism, dependencies, envelope/lifecycle behavior, exact transition endpoints, overlap planning, color-space math, finite bounded outputs, real stereo relationships and within-scene motion transfer. Windows renders are inspected through representative decoded frames. Ubuntu remains a configured CI target, not a locally verified platform. Optical flow and raster drawing are the expensive stages; begin at 320×180 or 640×360 and use 240/360-line internal stages. Per-effect `--profile` reports CPU wall time and calls, excluding decoding, scalar controls, generators and final encoding. No multi-hour performance claim is made.

## Codec experiment: deferred backend

`examples/codec_probe.py` makes a bounded, synthetic two-scene MPEG-4 Part 2 segment with no B-frames and a fixed GOP, then tries keyframe suppression and P-VOP repetition. It never reads or modifies user footage and deletes all intermediates. Run it with FFmpeg/FFprobe on PATH or explicit executable arguments.

On the Windows FFmpeg build used for local verification, the baseline decoded 24 frames in two seconds. Suppressing later keyframes decoded 23 frames while still reporting two seconds. Repeating selected P-VOPs decoded 27 frames, lost a trustworthy stream duration, and produced non-monotonic timestamp diagnostics despite a zero process exit code. This is insufficient evidence for a robust timeline-preserving backend. Merely checking decoder exit status would have accepted an unsuitable result.

Genuine codec datamoshing is therefore not registered or enabled. The supported alternative is `simulated_datamosh`. A future bounded preprocessing backend needs codec-aware VOP/GOP and timestamp handling, explicit frame-count validation and normalization, recovery tests across FFmpeg versions/platforms, and automatic fallback before it can feed the main renderer. Packed-B-frame unpacking is not motion-vector reuse; blind packet deletion is not treated as a successful implementation.

## Parameter reference

The following defaults and inclusive ranges apply to synthesis effects. All numeric entries accept fixed values or ordered ranges sampled on activation, and support modulation. Discrete and structured entries are fixed configuration. Common scheduling and lifecycle fields are described above. `effects list NAME` reports the live registry used by validation.

### `optical_feedback`

| Parameter | Default | Inclusive range / choices | Meaning |
| --- | --- | --- | --- |
| `gain` | 0.98 | 0–1.5 | Signal/loop gain; values above unity intentionally overdrive. |
| `zoom` | 1.025 | 0.5–1.5 | Camera scale; below one recedes, above one magnifies. |
| `rotation` | 0.5 | -45–45 | Degrees per recapture iteration (or fixed camera/trace angle). |
| `x` | 0 | -500–500 | Horizontal camera displacement in internal pixels. |
| `y` | 0 | -500–500 | Vertical camera displacement in internal pixels. |
| `perspective` | 0.02 | -0.3–0.3 | Fractional perspective distortion; raster mode compresses distant scanlines. |
| `angle` | 0 | -45–45 | Camera tilt in degrees. |
| `delay` | 1 | 1–30 | Delay in frames, rounded, at least one. |
| `injection` | 0.18 | 0–1 | Incoming source contribution to the loop. |
| `threshold` | 0.1 | 0–1 | Normalized comparison/key level. |
| `hue` | 0.3 | -180–180 | Degrees of hue rotation per iteration. |
| `saturation` | 1.01 | 0–3 | Chroma/saturation multiplier. |
| `blur` | 0.3 | 0–8 | Per-iteration Gaussian blur radius in pixels. |
| `exposure` | 0.02 | 0–1 | Coherent exposure oscillation amplitude. |
| `curvature` | 0.025 | 0–0.4 | Radial screen warp coefficient. |
| `persistence` | 0.1 | 0–0.99 | Retained-image weight; algorithm-specific behavior described above. |
| `decay` | 0.995 | 0–1 | History/phosphor retention per processed frame. |
| `drift` | 0.3 | 0–20 | Camera wander in internal pixels. |
| `clip_level` | 1 | 0.1–2 | Explicit normalized signal ceiling / soft-limiter scale. |
| `internal_height` | 360 | 32–1080 | Internal processing height in pixels, capped to the input height. |
| `mode` | `additive` | `normal`, `additive`, `difference`, `multiply`, `luma_key`, `chroma_key`, `maximum`, `minimum` | Fixed algorithm / routing choice; not modulatable. |
| `clipping` | `soft` | `soft`, `hard` | Fixed algorithm / routing choice; not modulatable. |

### `display`

| Parameter | Default | Inclusive range / choices | Meaning |
| --- | --- | --- | --- |
| `curvature` | 0.07 | 0–0.4 | Radial screen warp coefficient. |
| `scanlines` | 0.18 | 0–1 | Attenuation on alternating display rows. |
| `mask` | 0.12 | 0–1 | Phosphor triad attenuation. |
| `bloom` | 0.12 | 0–1 | Narrow Gaussian light spread gain. |
| `halation` | 0.05 | 0–1 | Wider, red-weighted light spread gain. |
| `persistence` | 0.12 | 0–0.99 | Retained-image weight; algorithm-specific behavior described above. |
| `border` | 0.02 | 0–0.25 | Black border as a fraction of the smaller image dimension. |
| `overscan` | 1.02 | 1–1.3 | Screen magnification before recapture. |
| `black_level` | 0 | -0.2–0.2 | Normalized display pedestal offset. |
| `refresh` | 0 | 0–1 | Moving refresh-band contrast. |
| `internal_height` | 360 | 32–1080 | Internal processing height in pixels, capped to the input height. |

### `virtual_camera`

| Parameter | Default | Inclusive range / choices | Meaning |
| --- | --- | --- | --- |
| `zoom` | 1 | 0.5–1.5 | Camera scale; below one recedes, above one magnifies. |
| `rotation` | 0 | -45–45 | Degrees per recapture iteration (or fixed camera/trace angle). |
| `x` | 0 | -500–500 | Horizontal camera displacement in internal pixels. |
| `y` | 0 | -500–500 | Vertical camera displacement in internal pixels. |
| `perspective` | 0.03 | -0.3–0.3 | Fractional perspective distortion; raster mode compresses distant scanlines. |
| `angle` | 0 | -45–45 | Camera tilt in degrees. |
| `lens` | 0.03 | -0.4–0.4 | Radial virtual-lens distortion coefficient. |
| `movement` | 1 | 0–20 | Camera position drift in internal pixels; small correlated rotation also follows it. |
| `focus` | 0.4 | 0–8 | Maximum autofocus blur radius in pixels. |
| `exposure` | 0.04 | 0–1 | Coherent exposure oscillation amplitude. |
| `white_balance` | 0.04 | 0–1 | Opposed red/blue gain drift. |
| `rolling_shutter` | 1 | 0–40 | Row-dependent camera displacement in pixels. |
| `noise` | 0.005 | 0–0.2 | Normalized Gaussian sensor / trace noise amplitude. |
| `moire` | 0.025 | 0–0.5 | Fine-pattern interference amplitude. |
| `refresh` | 0.03 | 0–1 | Moving refresh-band contrast. |
| `internal_height` | 360 | 32–1080 | Internal processing height in pixels, capped to the input height. |

### `analog_crossfade`

| Parameter | Default | Inclusive range / choices | Meaning |
| --- | --- | --- | --- |
| `mix` | 0.5 | 0–1 | Standalone B/fader amount; transitions instead supply their planned progress. |
| `response` | 1 | 0.2–5 | Fader curve exponent. |
| `gain_a` | 1 | 0–2 | Outgoing/input A signal gain. |
| `gain_b` | 1 | 0–2 | Incoming/input B signal gain. |
| `bleed` | 0.02 | 0–0.3 | Source leakage strongest near midpoint. |
| `chroma_offset` | 0 | -1–1 | Chroma-versus-luma fader offset, weighted toward midpoint. |
| `clip_level` | 1 | 0.1–2 | Explicit normalized signal ceiling / soft-limiter scale. |

### `dirty_crossfade`

| Parameter | Default | Inclusive range / choices | Meaning |
| --- | --- | --- | --- |
| `mix` | 0.5 | 0–1 | Standalone B/fader amount; transitions instead supply their planned progress. |
| `response` | 1 | 0.2–5 | Fader curve exponent. |
| `gain_a` | 1 | 0–2 | Outgoing/input A signal gain. |
| `gain_b` | 1 | 0–2 | Incoming/input B signal gain. |
| `bleed` | 0.02 | 0–0.3 | Source leakage strongest near midpoint. |
| `chroma_offset` | 0 | -1–1 | Chroma-versus-luma fader offset, weighted toward midpoint. |
| `clip_level` | 1 | 0.1–2 | Explicit normalized signal ceiling / soft-limiter scale. |
| `tearing` | 24 | 0–200 | Horizontal line disturbance in internal pixels. |
| `roll` | 0.1 | 0–1 | Vertical source disagreement as image-height fraction. |
| `chroma_error` | 0.5 | 0–3 | Transition chroma-phase error in radians. |

### `scanline_mixer`

| Parameter | Default | Inclusive range / choices | Meaning |
| --- | --- | --- | --- |
| `mix` | 0.5 | 0–1 | Standalone B/fader amount; transitions instead supply their planned progress. |
| `group` | 6 | 1–128 | Switching group size in rows (bands) or pixels (blocks). |
| `rate` | 0.5 | 0–30 | Switching / drift rate in cycles or updates per second. |
| `softness` | 0 | 0–0.5 | Half-width of a smooth threshold ramp. |
| `pattern` | `alternating` | `alternating`, `bands`, `random`, `moving`, `oscillator` | Fixed algorithm / routing choice; not modulatable. |

### `luma_key`

| Parameter | Default | Inclusive range / choices | Meaning |
| --- | --- | --- | --- |
| `mix` | 0.5 | 0–1 | Standalone B/fader amount; transitions instead supply their planned progress. |
| `threshold` | 0.5 | 0–1 | Normalized comparison/key level. |
| `softness` | 0.04 | 0–0.5 | Half-width of a smooth threshold ramp. |
| `invert` | 0 | 0–1 | Values >=0.5 invert the signal or mask. |
| `gain` | 1 | 0–4 | Signal/loop gain; values above unity intentionally overdrive. |
| `bias` | 0 | -1–1 | Normalized signal offset before comparison or overload. |
| `frequency` | 4 | 0.1–64 | Spatial oscillator cycles across its normalized coordinate. |
| `mask` | `source` | `source`, `horizontal_ramp`, `vertical_ramp`, `rings`, `oscillator` | Fixed algorithm / routing choice; not modulatable. |

### `chroma_key`

| Parameter | Default | Inclusive range / choices | Meaning |
| --- | --- | --- | --- |
| `mix` | 0.5 | 0–1 | Standalone B/fader amount; transitions instead supply their planned progress. |
| `key_hue` | 120 | 0–360 | Target key hue in degrees. |
| `tolerance` | 0.2 | 0–1 | Cb/Cr key-distance radius. |
| `softness` | 0.05 | 0–0.5 | Half-width of a smooth threshold ramp. |
| `spill` | 0.3 | 0–1 | Keyed source attenuation near the extracted color. |
| `key_saturation` | 1 | 0–1 | Target key saturation. |

### `analog_logic`

| Parameter | Default | Inclusive range / choices | Meaning |
| --- | --- | --- | --- |
| `mix` | 0.5 | 0–1 | Standalone B/fader amount; transitions instead supply their planned progress. |
| `gain` | 1 | 0–4 | Signal/loop gain; values above unity intentionally overdrive. |
| `bias` | 0 | -1–1 | Normalized signal offset before comparison or overload. |
| `operation` | `maximum` | `minimum`, `maximum`, `difference`, `absolute_difference`, `addition`, `multiplication`, `comparison`, `rectification` | Fixed algorithm / routing choice; not modulatable. |
| `channels` | `luma` | `luma`, `chroma`, `rgb` | Fixed algorithm / routing choice; not modulatable. |

### `feedback_transition`

| Parameter | Default | Inclusive range / choices | Meaning |
| --- | --- | --- | --- |
| `mix` | 0.5 | 0–1 | Standalone B/fader amount; transitions instead supply their planned progress. |
| `gain` | 0.98 | 0–1.5 | Signal/loop gain; values above unity intentionally overdrive. |
| `zoom` | 1.035 | 0.8–1.2 | Camera scale; below one recedes, above one magnifies. |
| `rotation` | 0.8 | -15–15 | Degrees per recapture iteration (or fixed camera/trace angle). |
| `decay` | 0.98 | 0–1 | History/phosphor retention per processed frame. |
| `blur` | 0.3 | 0–8 | Per-iteration Gaussian blur radius in pixels. |

### `glitch_switch`

| Parameter | Default | Inclusive range / choices | Meaning |
| --- | --- | --- | --- |
| `mix` | 0.5 | 0–1 | Standalone B/fader amount; transitions instead supply their planned progress. |
| `group` | 24 | 2–256 | Switching group size in rows (bands) or pixels (blocks). |
| `rate` | 3 | 0.1–12 | Switching / drift rate in cycles or updates per second. |
| `instability` | 0.2 | 0–1 | Coherent gain / switching-threshold excursion. |
| `pattern` | `bands` | `bands`, `blocks`, `luma` | Fixed algorithm / routing choice; not modulatable. |

### `sync_corruption`

| Parameter | Default | Inclusive range / choices | Meaning |
| --- | --- | --- | --- |
| `horizontal_phase` | 0 | -500–500 | Horizontal raster offset in internal pixels. |
| `vertical_phase` | 0 | -500–500 | Vertical raster offset in internal pixels. |
| `jitter` | 4 | 0–100 | Correlated per-line offset amplitude in pixels. |
| `tearing` | 12 | 0–300 | Horizontal line disturbance in internal pixels. |
| `rolling` | 0 | -2–2 | Vertical drift in image heights per second. |
| `loss` | 0.2 | 0–1 | Localized sync-loss amplitude. |
| `recovery` | 1.5 | 0.05–20 | Recovery time in seconds. |
| `drift_rate` | 0.15 | 0–10 | Sync excursion rate in Hz. |
| `correlation` | 0.9 | 0–1 | Proportion of smooth versus fine scanline jitter. |
| `internal_height` | 360 | 32–1080 | Internal processing height in pixels, capped to the input height. |
| `edges` | `wrap` | `wrap`, `blank` | Fixed algorithm / routing choice; not modulatable. |

### `dirty_enhancer`

| Parameter | Default | Inclusive range / choices | Meaning |
| --- | --- | --- | --- |
| `enhancement` | 2 | 0–12 | High-pass edge overdrive. |
| `ringing` | 0.35 | 0–3 | Second-derivative luma overshoot/undershoot gain. |
| `ghost` | 0.25 | -1–1 | Signed delayed-luma gain. |
| `delay` | 5 | -100–100 | Horizontal luma ghost displacement in internal pixels. |
| `chroma_bleed` | 5 | 0–50 | Horizontal chroma box-filter width in pixels. |
| `saturation` | 1.2 | 0–4 | Chroma/saturation multiplier. |
| `instability` | 0.15 | 0–2 | Coherent gain / switching-threshold excursion. |
| `threshold` | 0.45 | 0–1 | Normalized comparison/key level. |
| `inversion` | 0 | 0–1 | Blend toward inverted luminance or opposite chroma polarity. |
| `clip_level` | 1 | 0.1–2 | Explicit normalized signal ceiling / soft-limiter scale. |
| `internal_height` | 360 | 32–1080 | Internal processing height in pixels, capped to the input height. |

### `chroma_corruption`

| Parameter | Default | Inclusive range / choices | Meaning |
| --- | --- | --- | --- |
| `phase` | 15 | -360–360 | Chroma phase rotation in degrees. |
| `drift` | 15 | 0–180 | Slow hue-drift amplitude in degrees. |
| `rate` | 0.1 | 0–10 | Switching / drift rate in cycles or updates per second. |
| `delay` | 4 | -100–100 | Horizontal chroma displacement in internal pixels. |
| `bleed` | 5 | 0–50 | Horizontal chroma low-pass width in pixels. |
| `saturation` | 1 | 0–4 | Chroma/saturation multiplier. |
| `inversion` | 0 | 0–1 | Blend toward inverted luminance or opposite chroma polarity. |
| `dropout` | 0.1 | 0–1 | Slow, scanline-dependent color attenuation depth. |
| `line_error` | 0.2 | 0–3 | Scanline chroma-phase excursion in radians. |
| `luma_to_chroma` | 0.12 | 0–2 | Fine luminance detail leaking into chroma. |
| `chroma_to_luma` | 0.08 | 0–2 | Chroma carrier leaking into luminance. |
| `internal_height` | 360 | 32–1080 | Internal processing height in pixels, capped to the input height. |

### `signal_overload`

| Parameter | Default | Inclusive range / choices | Meaning |
| --- | --- | --- | --- |
| `gain` | 1.8 | 0–8 | Signal/loop gain; values above unity intentionally overdrive. |
| `bias` | -0.2 | -2–2 | Normalized signal offset before comparison or overload. |
| `low` | 0 | -2–1 | Lower normalized luma clipping threshold. |
| `high` | 1 | 0.01–3 | Upper normalized luma clipping threshold; must exceed low. |
| `folds` | 2 | 0.1–12 | Triangular wavefold / color contour count multiplier. |
| `rectify` | 0 | 0–1 | Blend toward absolute-value rectification. |
| `chroma_gain` | 1.3 | 0–8 | Chroma overdrive before channel-dependent soft limiting. |
| `smear` | 3 | 0–60 | Highlight-smearing horizontal filter width in pixels. |
| `internal_height` | 360 | 32–1080 | Internal processing height in pixels, capped to the input height. |
| `mode` | `fold` | `fold`, `soft`, `hard` | Fixed algorithm / routing choice; not modulatable. |

### `signal_delay`

| Parameter | Default | Inclusive range / choices | Meaning |
| --- | --- | --- | --- |
| `internal_height` | 240 | 32–1080 | Internal processing height in pixels, capped to the input height. |
| `taps` | `[{"x": 5, "y": 0, "frames": 0, "gain": 0.3, "polarity": 1, "channels": "luma"}]` | Structured list | 1–8 taps with x/y (±500 px), frames (0–30), gain (±2), polarity (±1), channels (luma/chroma/all). Missing values default to 0 px, 0 frames, gain 0.3, polarity 1, luma. |

### `composite_video`

| Parameter | Default | Inclusive range / choices | Meaning |
| --- | --- | --- | --- |
| `carrier` | 0.25 | 0.08–0.45 | Simulated chroma carrier cycles per internal pixel. |
| `bandwidth` | 5 | 1–31 | Horizontal reconstruction filter width in pixels. |
| `phase` | 0 | -180–180 | Chroma phase rotation in degrees. |
| `phase_drift` | 0.2 | 0–3 | Slow chroma-phase error in radians. |
| `cross_color` | 0.3 | 0–2 | Luma-to-color reconstruction leakage gain. |
| `cross_luma` | 0.2 | 0–2 | Chroma-to-luma reconstruction leakage gain. |
| `dot_crawl` | 0.15 | 0–1 | Carrier-pattern luma interference amplitude. |
| `burst_instability` | 0.1 | 0–2 | Scanline-dependent carrier phase excursion in radians. |
| `internal_height` | 360 | 32–1080 | Internal processing height in pixels, capped to the input height. |
| `quality` | `fast` | `fast`, `carrier` | Fixed algorithm / routing choice; not modulatable. |

### `spatial_synth`

| Parameter | Default | Inclusive range / choices | Meaning |
| --- | --- | --- | --- |
| `frequency` | 5 | 0.1–100 | Spatial oscillator cycles across its normalized coordinate. |
| `phase` | 0 | -100–100 | Spatial oscillator phase in cycles. |
| `orientation` | 0 | -360–360 | Spatial oscillator orientation in degrees. |
| `amplitude` | 1 | 0–4 | Spatial signal gain. |
| `offset` | 0 | -2–2 | Spatial signal bias. |
| `drift` | 0.1 | -10–10 | Temporal phase drift in cycles per second. |
| `luma_phase` | 1 | -10–10 | Footage luminance phase-modulation depth in cycles. |
| `displacement` | 20 | -300–300 | Sampling/block displacement in internal pixels. |
| `threshold` | 0.5 | 0–1 | Normalized comparison/key level. |
| `frequency_b` | 7 | 0.1–100 | Secondary oscillator frequency in cycles. |
| `internal_height` | 360 | 32–1080 | Internal processing height in pixels, capped to the input height. |
| `pattern` | `rings` | `horizontal_ramp`, `vertical_ramp`, `radial_ramp`, `horizontal`, `vertical`, `diagonal`, `rings`, `grid`, `checkerboard`, `spiral`, `moving_bars`, `raster_noise` | Fixed algorithm / routing choice; not modulatable. |
| `waveform` | `sine` | `sine`, `triangle`, `sawtooth`, `square` | Fixed algorithm / routing choice; not modulatable. |
| `operation` | `phase` | `phase`, `addition`, `multiplication`, `minimum`, `maximum`, `difference`, `threshold`, `wavefold`, `displace` | Fixed algorithm / routing choice; not modulatable. |
| `output` | `colorize` | `colorize`, `replace`, `key`, `displace` | Fixed algorithm / routing choice; not modulatable. |

### `analog_colorizer`

| Parameter | Default | Inclusive range / choices | Meaning |
| --- | --- | --- | --- |
| `phase` | 0 | -10–10 | Shared palette movement in cycles. |
| `red_phase` | 0 | -10–10 | Red mapping offset in cycles. |
| `green_phase` | 0.333 | -10–10 | Green mapping offset in cycles. |
| `blue_phase` | 0.667 | -10–10 | Blue mapping offset in cycles. |
| `red_threshold` | 0.5 | 0–1 | Red-channel comparator threshold. |
| `green_threshold` | 0.5 | 0–1 | Green-channel comparator threshold. |
| `blue_threshold` | 0.5 | 0–1 | Blue-channel comparator threshold. |
| `bands` | 5 | 2–32 | Number of hard color bands. |
| `folds` | 1 | 0.1–12 | Triangular wavefold / color contour count multiplier. |
| `invert` | 0 | 0–1 | Values >=0.5 invert the signal or mask. |
| `internal_height` | 360 | 32–1080 | Internal processing height in pixels, capped to the input height. |
| `mapping` | `smooth` | `smooth`, `bands`, `channels`, `fold` | Fixed algorithm / routing choice; not modulatable. |
| `palette` | `[[0.05, 0.02, 0.2], [0.9, 0.05, 0.3], [0.05, 0.9, 0.8], [1, 0.9, 0.1]]` | Structured list | 2–16 RGB triples in normalized 0–1; fixed palette, not modulatable. |

### `oscilloscope_xy`

| Parameter | Default | Inclusive range / choices | Meaning |
| --- | --- | --- | --- |
| `gain` | 0.8 | 0–4 | Signal/loop gain; values above unity intentionally overdrive. |
| `rotation` | 0 | -180–180 | Degrees per recapture iteration (or fixed camera/trace angle). |
| `brightness` | 0.8 | 0–3 | Trace/density light gain. |
| `thickness` | 1 | 1–8 | Trace or scanline thickness in internal pixels. |
| `density` | 256 | 16–2048 | Maximum trace samples / density sampling budget. |
| `decay` | 0.85 | 0–0.999 | History/phosphor retention per processed frame. |
| `bloom` | 0.3 | 0–2 | Narrow Gaussian light spread gain. |
| `noise` | 0 | 0–0.1 | Normalized Gaussian sensor / trace noise amplitude. |
| `frequency` | 3 | 0.1–30 | Number of procedural oscillations across the trace window. |
| `ratio` | 1.5 | 0.1–10 | Procedural XY oscillator frequency ratio. |
| `internal_height` | 360 | 32–1080 | Internal processing height in pixels, capped to the input height. |
| `source` | `stereo` | `stereo`, `bands`, `oscillator`, `phase_shift` | Fixed algorithm / routing choice; not modulatable. |

### `vectorscope`

| Parameter | Default | Inclusive range / choices | Meaning |
| --- | --- | --- | --- |
| `gain` | 0.85 | 0–3 | Signal/loop gain; values above unity intentionally overdrive. |
| `brightness` | 0.35 | 0–3 | Trace/density light gain. |
| `decay` | 0.8 | 0–0.999 | History/phosphor retention per processed frame. |
| `density` | 12000 | 256–65536 | Maximum trace samples / density sampling budget. |
| `bloom` | 0.2 | 0–2 | Narrow Gaussian light spread gain. |
| `internal_height` | 360 | 32–1080 | Internal processing height in pixels, capped to the input height. |

### `waveform_monitor`

| Parameter | Default | Inclusive range / choices | Meaning |
| --- | --- | --- | --- |
| `gain` | 1 | 0–3 | Signal/loop gain; values above unity intentionally overdrive. |
| `brightness` | 0.3 | 0–3 | Trace/density light gain. |
| `decay` | 0.7 | 0–0.999 | History/phosphor retention per processed frame. |
| `density` | 12000 | 256–65536 | Maximum trace samples / density sampling budget. |
| `bloom` | 0.15 | 0–2 | Narrow Gaussian light spread gain. |
| `internal_height` | 360 | 32–1080 | Internal processing height in pixels, capped to the input height. |

### `scan_displacement`

| Parameter | Default | Inclusive range / choices | Meaning |
| --- | --- | --- | --- |
| `displacement` | 35 | -300–300 | Sampling/block displacement in internal pixels. |
| `horizontal` | 5 | -300–300 | Luminance-controlled horizontal shift in pixels. |
| `frequency` | 3 | 0–64 | Spatial oscillator cycles across its normalized coordinate. |
| `oscillator` | 0.2 | 0–2 | Spatial bending depth added to luminance. |
| `audio_gain` | 0 | 0–3 | Bass-energy multiplier of raster elevation. |
| `spacing` | 5 | 2–32 | Spacing between rendered scanlines in internal pixels. |
| `thickness` | 1 | 1–8 | Trace or scanline thickness in internal pixels. |
| `perspective` | 0.2 | -0.8–0.8 | Fractional perspective distortion; raster mode compresses distant scanlines. |
| `colorize` | 0 | 0–1 | Values >=0.5 use row-dependent false color. |
| `internal_height` | 360 | 32–1080 | Internal processing height in pixels, capped to the input height. |
| `mode` | `wireframe` | `wireframe`, `remap` | Fixed algorithm / routing choice; not modulatable. |

### `simulated_datamosh`

| Parameter | Default | Inclusive range / choices | Meaning |
| --- | --- | --- | --- |
| `motion_amplification` | 1.8 | -8–8 | Signed optical-flow multiplier. |
| `block_size` | 16 | 4–64 | Macroblock side length in internal pixels. |
| `persistence` | 0.98 | 0–1 | Retained-image weight; algorithm-specific behavior described above. |
| `refresh_probability` | 0.03 | 0–1 | Probability per macroblock per frame of source-image refresh. |
| `refresh_size` | 1 | 1–8 | Refresh-mask dilation size in macroblocks. |
| `max_displacement` | 40 | 0–200 | Maximum motion vector component in internal pixels. |
| `quantization` | 1 | 0.1–16 | Motion vector step in internal pixels. |
| `corruption` | 0.05 | 0–1 | Fraction of motion macroblocks receiving coherent noise. |
| `color_retention` | 0.95 | 0–1 | Retained chroma weight; zero adopts current-source chroma. |
| `recovery` | 0.03 | 0–1 | Per-frame blend back toward the current source; recovery mode ramps this up near release. |
| `internal_height` | 240 | 32–720 | Internal processing height in pixels, capped to the input height. |
| `mode` | `motion_transfer` | `motion_transfer`, `frozen`, `accumulate`, `refresh`, `recovery` | Fixed algorithm / routing choice; not modulatable. |

### `digital_corruption`

| Parameter | Default | Inclusive range / choices | Meaning |
| --- | --- | --- | --- |
| `amount` | 0.3 | 0–1 | Digital corruption coverage / blend. |
| `block_size` | 16 | 2–128 | Macroblock side length in internal pixels. |
| `displacement` | 24 | 0–300 | Sampling/block displacement in internal pixels. |
| `delay` | 4 | 1–30 | Delay in frames, rounded, at least one. |
| `bits` | 4 | 1–8 | Retained bit depth or selected XOR bit plane (1=least significant). |
| `threshold` | 0.5 | 0–1 | Normalized comparison/key level. |
| `internal_height` | 240 | 32–1080 | Internal processing height in pixels, capped to the input height. |
| `mode` | `block_persist` | `macroblock`, `motion_field`, `block_persist`, `partial_replace`, `pixel_sort`, `horizontal_streak`, `vertical_streak`, `bit_plane`, `bit_depth`, `quantization`, `frame_repeat`, `scanline_buffer`, `delayed_regions`, `slit_scan` | Fixed algorithm / routing choice; not modulatable. |
