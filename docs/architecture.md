# Architecture and configuration

## Pipeline

`config → media index + audio features + tracks → JSON plan → decoder → layer effects → composite → global effects → titles → encoder`

The planner owns all activation intervals and clip decisions. Integer frame indices define half-open intervals `[start, end)`; `Fraction` represents output frame rate. Source offsets are seconds. Source paths are sorted before selection. Namespace-derived random streams isolate clips, effects, and overlays. Per-frame effect noise is keyed by seed, instance ID, and output frame.

FFmpeg decodes normalized RGB24 into `uint8` NumPy arrays shaped `(height, width, 3)`, in **RGB** order. OpenCV conversions use explicit RGB constants. Images retain a separate alpha channel during layer processing. Encoded output is YUV420p. FFmpeg handles input rotation and variable frame rates.

One encoder remains open throughout a render. Each active video layer owns a segment decoder. Argument arrays, `pathlib`, temporary directories, and context-managed pipes work without a shell. Diagnostics go to temporary files so stderr cannot fill a pipe and deadlock. Failure or cancellation terminates children, closes pipes, waits, and removes temporary output. The final MP4 replaces its destination only after encoding succeeds.

Reverse decoding works in normalized chunks containing at most 64 MiB of RGB frames, traversed backwards. Very large single frames and FFmpeg's internal working buffers add overhead. Transitions use two simultaneous decoders instead of storing outgoing tails. Basic temporal effects keep one prior frame per instance; advanced delay processors enforce a 64 MiB history limit each. CRT maps have a four-entry cache. No frame queues grow with mix duration. Audio feature arrays and plan metadata do grow with duration. See the [synthesis extension](synthesis.md) for multi-input processors and control signals.

Metadata caches use path, size, and modification time in `.cache/videobingus` under the working directory. Audio caches live in `.cache/videobingus` beside the soundtrack. Cache writes are best-effort; originals are never rewritten. Delete caches to force reinspection.

## Generative sources and suite compilation

`scenes/` extends the source timeline with analytical, fixed-timestep simulation, and delayed recursive sources. A planned clip stores either a media index, a scene descriptor, or both for video-textured/injected scenes. Descriptors contain sampled parameters, independent seeds and palette stops. Generated frames enter the same transition, effect, overlay and encoder stages as decoded media. A bounded LRU owns simulation state; simultaneous instances fork state, while recurring motifs can resume it.

The scene catalog supplies validation, discovery, modulation capabilities, structural restrictions and cost metadata. Palette mapping and audio profiles are shared by source scenes and generated overlays. The existing signal bank also targets scene parameters. An optional offline energy controller contributes time-indexed controls and musical-state intervals to the ordinary plan.

Suite YAML compiles before project validation into scene pools, ordered registry effects, transition candidates and overlays. Weighted selection uses independent random streams, category compatibility and explicit density/cost limits. The saved project is usable without the original suite; the saved plan preserves actual timeline choices. Default fit remains aspect-preserving 1080p with bars; explicit stretch is available for footage and generated canvases. See [generative scenes and suites](generative.md) for algorithms, lifecycle, parameter tables and preview limits.

## Clips and transitions

`clips.selection` is `shuffle` or `random`. Shuffle bags avoid repeats until the eligible bag is exhausted. With only one source, repetition is unavoidable. `allow_consecutive_source` defaults to false; `random_start` defaults to true.

`duration` and `speed` accept ordered pairs. `short_source: shorten` limits source consumption to available duration; `loop` repeats a short source. Frame quantization may duplicate an edge frame. `reverse_probability` and `freeze_probability` default to zero. Clip durations are limited to 120 seconds. `crossfade` defaults to zero and accepts up to two seconds. Crossfades extend the outgoing source under the start of the incoming clip without changing timeline duration. They may loop short sources and are shortened to fit both neighboring clip intervals. Primary-layer effects run after the mixer. Weighted project `transitions` take precedence over `clips.crossfade`.

## Effects

Each effect has a unique `id`, a `type`, optional type-specific parameters, and common scheduling controls. Run `videobingus effects list` for every implemented parameter, default, and inclusive limit. A number is fixed; a pair is sampled once per activation. Separate instances can share a type. Processing sorts by `order`, then ID. Layer processing always precedes final composite processing.

```yaml
effects:
  global:
    - id: tape
      type: vhs
      intensity: 0.35
      horizontal_jitter: 2
      layer: primary
      order: 0
  per_clip:
    - id: hue
      type: hue_shift
      probability: 0.2
      degrees: [-90, 90]
  per_track:
    - id: symmetry
      type: kaleidoscope
      probability: 0.25
  events:
    - id: tracking
      type: tracking_error
      trigger: random
      probability_per_second: 0.02
      probability: 1
      duration: [0.2, 1.5]
      cooldown: 5
      attack: 0.1
      release: 0.2
```

Global, per-clip, and per-track `probability` is sampled at interval start. Random events use an exponential waiting time calibrated to `probability_per_second`; event probability can reject a candidate. Cooldown starts at the candidate's end. Envelopes and cooldown use seconds, independent of render speed.

`layer` is `primary`, `composite` (default), or an overlay ID. Per-clip effects on overlays follow that overlay's clips. The frame context contains output frame/time, clip-local time, current track, audio features, and deterministic randomness.

Temporal state persists across cuts and inactive gaps by default. Set `persist: false` to reset it at clip boundaries, or `reset_on: [activation]` to reset it when reactivated. `frame_hold` periodically captures and releases a frame; `temporal_blend` accumulates decaying prior output. `feedback` transforms a prior frame with decay and a convex blend to bound brightness. Legacy `datamosh` simulates displaced prior-frame blocks across cuts. The new `simulated_datamosh` uses within-scene optical flow to warp retained imagery. Neither manipulates codec bitstreams.

VHS combines low-resolution bleeding chroma, separate luma/chroma noise, row jitter, horizontal ghosting, tape dropout, and bottom-edge head noise. CRT adds curved resampling, scanlines, vignette, bloom, and optional refresh interference. Camcorder adds perspective, motion, exposure variation, and sensor noise. These are approximations, with no physically accurate signal model.

## Layers and generators

```yaml
overlays:
  - id: secondary
    source: ./footage/secondary
    activation: random
    probability_per_second: 0.015
    duration: [4, 12]
    opacity: [0.15, 0.5]
    blend: difference
  - id: watermark
    source: ./logo.png
    activation: global
    position: bottom_right
    scale: 0.15
    opacity: 0.8
```

Sources can be a video, directory, still image, transparent PNG, or `generator:<type>`. Layers schedule their own sources in segments of at most 15 seconds. `scale` fits the layer within that fraction of the output canvas, preserving image aspect ratio. Positions: `center`, `top_left`, `top_right`, `bottom_left`, `bottom_right`. Blend modes: `normal`, `add`/`additive`, `screen`, `multiply`, `difference`. `luma_key` optionally removes pixels with mean RGB brightness at or below a normalized threshold.

Generators: `television_static`, `color_bars`, `blue_vcr`, `black`, `signal_loss`, `waveform`, `spectrum`. Primary generator bursts replace the beginning of selected footage clips, with duration capped to that clip:

```yaml
generators:
  - type: television_static
    probability: 0.03
    duration: [0.2, 2]
```

Waveform and spectrum generators require `analysis: true`. They display analyzed waveform samples and 16 linear-frequency spectral bands, rather than synthetic oscillations.

## Tracks and titles

Set `cue: ./mix.cue` or point it at a UTF-8 timestamped text file (`MM:SS Artist - Title`, also `HH:MM:SS`). CUE supports TRACK, TITLE, PERFORMER, INDEX 01, and 75 Hz timestamps. UTF-8 BOM is accepted. Multiple FILE entries are rejected. Track times must strictly increase within the mix.

```yaml
track_changes:
  cut_clip: true
  reselect_effects: true
tracks:
  - index: 3
    sources: [./industrial]
    clips:
      duration: [1, 5]
titles:
  enabled: true
  style: vcr
  mix_title: Friday session
  font_size: 32
  color: '#ffffff'
  position: bottom_left
  duration: 8
  fade_in: 0.3
  fade_out: 0.5
```

Track overrides support source pools and clip settings, taking effect at the next clip when cutting is disabled. Event effects with `trigger: track` fire at listed boundaries. Titles show track number, artist, title, and optional mix title. Styles are `lower_third` and `vcr` (outlined OSD text). Pillow's bundled Aileron is the portable default, with limited glyph coverage. For other Unicode scripts, set `titles.font` to a suitable TTF/OTF file and move it with the project. No system font location is assumed. Font size is in output pixels.

## Audio response

```yaml
analysis: true
effects:
  global:
    - id: tape
      type: vhs
  events:
    - id: corruption
      type: block_glitch
      trigger: bass_onset
      probability: 0.25
      threshold: 0.6
      hysteresis: 0.1
      duration: [0.15, 0.6]
      cooldown: 3
modulation:
  - target: effects.tape.horizontal_jitter
    source: bass_energy
    output_range: [0, 12]
    smoothing: 0.15
```

Analysis streams mono 16 kHz float PCM through 2,048-sample Hann windows, stepping 1,024 samples. Bands are bass 20–180 Hz, mid 180–2,500 Hz, and high 2,500–8,000 Hz. RMS, band energy, and positive spectral flux use Gaussian smoothing and 95th-percentile normalization into `[0, 1]`. Bass candidates use positive bass-energy differences; onset candidates use unsmoothed positive spectral flux. Their times refer to window centers, so timing is approximate to about 64 ms. No constant BPM is assumed. Analysis never changes the muxed soundtrack.

Modulation sources: `rms`, `bass_energy`, `mid_energy`, `high_energy`, `flux`, `bass_onset`, `onset`. Targets are `effects.<id>.<parameter>` (including intensity) or `overlays.<id>.opacity`. Ranges are validated against the registry. `smoothing` is the exponential time constant in seconds; zero disables smoothing. Event triggers are `random`, `bass_onset`, `onset`, `energy` (RMS threshold crossing), and `track`. Threshold crossings rearm below `threshold - hysteresis`; cooldown limits repeated activations. Aggressive flashing has no dedicated effect and is absent from defaults.

## Limits and next work

The initial encoder is software H.264 in MP4. Audio is copied when supported; otherwise AAC is encoded once at 320 kb/s. Preview audio stream copying can include packet-boundary padding. Full-render duration is rounded up to the next video frame; audio codecs and containers may add padding. Source corruption during decoding fails the render safely rather than silently producing gaps. Existing plans validate references and soundtrack duration but do not checksum source video contents; replan after replacing media.

Plans are versioned, UTF-8 JSON. Export strips local executable paths and preserves project-relative media references. References on another Windows drive require reorganizing the project before export. Cached analysis is embedded, making plans self-contained apart from media and optional fonts. Stateless previews share scheduling with a complete render; three seconds of warm-up approximates temporal history.

Next work: benchmark multi-hour renders, improve text wrapping and script-specific font packaging, add hardware encoding, and investigate effect checkpoints and real codec-level datamoshing. A GUI, live VJ controls, beat grids, distributed rendering, and plugin frameworks are outside this release.
