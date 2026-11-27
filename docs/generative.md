# Generative scenes and suites

Scenes use the ordinary integer-frame timeline and FFmpeg renderer. An analytical scene calculates images from time; a simulation evolves bounded fields or particles at a fixed update rate; a feedback scene transforms its previous image. All implementations run on the CPU using NumPy and OpenCV. Audio is optional for auditions and required for a complete mix.

## Rendering

```sh
videobingus render mix.flac --suite artificial_life --intensity 0.8 --seed random -o mix.mp4
videobingus render mix.flac footage/ --suite acid_television --seed 420 -o hybrid.mp4
videobingus render mix.flac --generators plasma,tunnel,reaction_diffusion --effects optical_feedback,composite_video --randomize --seed 420 -o mix.mp4
videobingus render mix.flac footage/ --suite digital_decay --include-effect optical_feedback --exclude-effect rgb_shift --intensity 0.6 -o mix.mp4
```

`--seed random` chooses and records a new seed. A numeric seed reproduces choices. `--include-effect` adds a candidate to a constrained pool; it does not force every candidate into the performance. `--effects` restricts the pool when using a suite or `--randomize`; without either, it enables an explicit global chain. Two-input effects in that list become transition candidates. `--generators` restricts or replaces the suite's generator pool. `--min-clip` and `--max-clip` override scene durations, including suite minimums.

Default output is 1920×1080, 30 FPS, preserving aspect ratio with black bars. Choose `--fit fit`, `--fit crop`, or `--fit stretch`. Internal generator resolution has its own aspect ratio: retro's 320×200 canvas also gets bars unless cropped or stretched.

## Audition and discovery

```sh
videobingus generators list
videobingus generators info reaction_diffusion --json
videobingus effects info optical_feedback --json
videobingus generators demo strange_attractor --duration 30 --palette thermal --seed 123 -o attractor.mp4
videobingus generators demo plasma --randomize --param frequency=4 --quality retro -o plasma.mp4
videobingus generators demo particle_field --audio mix.flac --start 12:30 --duration 30 --input footage.mp4 --param video_influence=0.8 -o particles.mp4
videobingus suites list
videobingus suites info demoscene
videobingus suites demo demoscene --duration 60 --resolution 1280x720 --seed 42 --showcase --contact-sheet preview.png -o showcase.mp4
```

Generator demos use silence without `--audio`. Suite demos use a synthetic stereo test soundtrack; they also accept `--audio`, `--start`, and `--input`. `--showcase` shortens scenes and cycles the compiled motifs; ordinary suite demos preserve the suite's duration choices. Contact sheets sample six points across the rendered video. Auditions are bounded to ten minutes. Use `--overwrite` explicitly to replace an existing output.

`info --json` exposes the authoritative catalog: numeric defaults and bounds, enum options, initialization-only parameters, modulation targets, triggers, input requirements, cost, state, and recommended duration. Spatial test patterns and scopes remain available through the existing effect and overlay mechanisms.

## Editable project

```yaml
audio: ./mix.flac
seed: 420
sources: []
palette: acid
composition:
  mode: generative                 # auto, footage, generative, hybrid
  scene_duration: [20, 60]
  motif_recurrence: 0.35
performance:
  quality: balanced
scenes:
  - id: organisms
    type: reaction_diffusion
    retain_state: true
    params:
      feed: 0.0367
      kill: 0.0649
      injection_strength: 0.2
    triggers:
      - source: bass_onset
        action: disturbance
        threshold: 0.6
        probability: 0.2
        cooldown: 4
  - id: waves
    type: plasma
    weight: 2
    params:
      frequency: [2, 5]
audio_profiles: [sub_pressure, transient_injection, spectral_color]
signals:
  breathing:
    type: lfo
    waveform: sine
    frequency: 0.035
modulation:
  - target: scenes.waves.warp
    source: breathing
    output_range: [0.1, 0.7]
output:
  path: ./mix.mp4
  resolution: [1920, 1080]
  fit: fit
```

Numeric parameter pairs sample once per motif, then persist into the render plan. Scene identifiers must be unique. Structural parameters, enum options, population sizes, and Gray–Scott feed/kill rates are initialization-only where marked in the catalog. Invalid modulation targets fail validation. Scene triggers use `bass_onset`, `onset`, `energy`, or `track`, with `threshold`, `hysteresis`, `probability`, and `cooldown`; supported actions are catalog-specific. Built-in audio disturbance behavior also respects a short refractory period.

Hybrid mode chooses footage or a scene using `footage_weight` and `generated_weight`. Optional texture or injection controls connect a generated scene to decoded footage when sources are available. Ordinary footage-only projects continue through the original clip planner.

Generated overlays use `source: generator:plasma` and `generator_params`. The ordinary `opacity`, placement, scale, luma key, blend, activation, and per-layer effects apply. An overlay's `role` can be `overlay`, `input` (available to downstream mixers without compositing), `mask` (luminance attenuates the current composite), or `displacement` (red/green control horizontal/vertical resampling). Displacement uses `displacement: [24, 12]` pixels, bounded to ±200. Mask and displacement roles operate across the whole canvas. Use an input layer with a downstream luma/chroma key mixer to combine generated patterns with independently decoded footage; see the [signal-processing guide](synthesis.md) for layer input ordering.

## Suites

A suite is an editable YAML recipe defining a constrained space of performances. Its compiler produces an ordinary validated project; there is no second rendering engine or expression language. Built-in recipes live in [src/videobingus/suites](../src/videobingus/suites).

| Suite | Vocabulary |
| --- | --- |
| demoscene | Plasma, tunnels, tiled textures, metaballs, wireframes, perspective planes; retro palette and raster processing |
| acid_television | Interference, plasma, cells and recursion; saturated palettes, analog signal damage and dirty mixing |
| artificial_life | Chemical fields, chemotactic agents, flow, flocking, cellular systems and dye; long organic scenes |
| digital_decay | Cellular patterns and geometry; retained blocks, motion-driven corruption and digital processing |
| deep_space | Attractors, fractals, stars and flow; dark palettes and slow accumulation |
| phosphor_lab | Curves, wireframes, particles and attractors; phosphor palettes and raster deformation |
| warehouse | Geometry, perspective planes and contours; restrained monochrome processing |
| bass_mutations | Fields, metaballs and tunnels; bass-driven deformation and occasional corruption |
| corporate_signal | Footage, obsolete computer graphics, picture-in-picture and broadcast processing |
| mathematical_maximalism | Fractals, affine accumulation, attractors and recursive geometry |
| ambient_feedback | Chemical growth, dye, coherent fields and recursion; slow scene evolution |

The compiler chooses up to four recurring motifs, a palette family, and ordered processing stages. It limits duplicate categories, conflicting color/feedback/display processors, expensive processors, global effects, scene effects, overlays, and simultaneous events. It reserves cost for expensive scene algorithms and avoids crossfading two expensive scenes beyond the budget. Cost is an ordinal estimate, not a runtime deadline or memory limit.

Identity traits influence generator weights, motion, detail, overlay density, feedback/corruption strength, and analog/digital effect weights. Palettes are inherited per mix, track, or musical section. `background` sets the low palette stop. A recurring stateful motif can retain its simulation while absent; global optical feedback remains independent and can span all scene changes.

```sh
videobingus suites generate --theme analog --generators plasma,metaballs,reaction_diffusion --effects optical_feedback,dirty_crossfade,analog_colorizer --audio-reactive --intensity 0.7 --seed 42 -o my-suite.yaml
videobingus render mix.flac --suite ./my-suite.yaml -o mix.mp4
videobingus suites generate --theme organic --variants 5 --palette-scheme analogous --output-dir ./suites/
videobingus suites compile ./my-suite.yaml mix.flac --source footage/ --seed 42 -o project.yaml
videobingus plan --config project.yaml -o plan.json
videobingus render --plan plan.json
```

Themes: `analog`, `digital`, `organic`, `geometric`, `retro`, `psychedelic`, `industrial`, `minimal`, `maximal`, `ambient`. Selection is local weighted sampling. No external AI service is used. Generated recipes preserve the aesthetic while allowing rerolls; `compile` exports the concrete project. `generate --audio mix.flac` exports a concrete project directly. Audio and media must exist when building a plan, but not when exporting the recipe.

Suite fields:

| Field | Purpose |
| --- | --- |
| `composition` | Mode, footage/generated weights, scene duration, motif recurrence, scene-rate cap |
| `identity` | Palette families/scope, background, analog/geometric bias, motion, density, complexity, feedback, corruption; traits 0–1 |
| `generators` | Ordinary scene definitions plus weighted selection |
| `effects.persistent`, `effects.per_scene` | `choose: [minimum, maximum]` and candidate `pool`; numeric effect params may be flat or under `params` |
| `effects.events` | `max_active` and candidates with trigger, probability, duration, cooldown, release |
| `transitions` | Ordinary weighted two-source transition definitions |
| `overlays` | Ordinary overlay definitions with optional selection weight |
| `audio_response` | Enabled flag, profiles, scene/effect sensitivity and quiet-section preservation |
| `randomization` | Global/scene/event/overlay/expensive limits, intensity 0–1, preserve_palette |
| `performance`, `palettes` | Ordinary quality settings and custom palettes |

Included effects become eligible candidates, subject to budgets and compatibility; constraints may produce fewer effects than the requested pool count. This is intentional. Saved plans contain the actual motifs, seeds, sampled parameters, palettes, audio analysis, state intervals, clips, transitions and scheduled effects.

## Audio and palettes

Profiles use normalized audio features and clamp to catalog bounds. `auto` applies each generator's recommended profiles. They alter the equations or simulation updates rather than only post-processing brightness.

| Profile | Behavior |
| --- | --- |
| sub_pressure | Bass changes vortex strength, attraction, warping, deformation or speed |
| transient_injection | Onsets drive injection/disturbance where supported |
| spectral_color | Spectral balance moves the shared palette |
| energy_accumulation | Sustained energy increases movement gradually |
| rhythmic_disturbance | Onsets perturb supported simulation controls |
| slow_breathing | Independent slow procedural evolution |
| track_evolution | Track-local palette progression |

Explicit `scenes.ID.parameter` (or `generators.ID.parameter` for generated overlays) modulation uses the existing virtual signal system. Profiles apply after explicit parameter modulation; profile names execute in configured order. See [synthesis.md](synthesis.md) for control-source ranges, slew, quantization and combination rules.

Optional composition dynamics derive immediate/sustained energy, energy trend, onset density, bass activity, relative contrast and track progress. Calm/building/active/peak/recovery states have minimum durations and distinct entry/exit thresholds; transitions are smoothed. They influence scene duration/selection, event density, effect strength and transition intensity. This is a lightweight energy controller, not song-structure recognition or beat-grid detection. Conservative scene-rate caps and intensity defaults reduce abrupt changes; they do not guarantee photosensitivity safety.

Built-in palette names: `commodore`, `ega`, `amber`, `phosphor`, `cyan_magenta`, `acid`, `ultraviolet`, `infrared`, `thermal`, `industrial`, `archival`, `monochrome`, `pastel`, `deep_space`. Project `palettes: {my_palette: ["#07121f", "#18b5b0", "#fff1b8"]}` adds 2–16 explicit stops. `palette_space: lab` enables perceptual interpolation; RGB is default. Generators cycle through a closed gradient. Use a monochrome family for limited color. Generated analogous/complementary/monochrome families keep related hues instead of sampling unrelated RGB values. Color bands and posterization remain available in the analog colorizer.

## Simulation, previews and performance

| Quality | Analytical canvas | Simulation canvas | Simulation Hz | Upscale |
| --- | --- | --- | --- | --- |
| draft | 320×180 | 160×90 | 15 | linear |
| retro | 320×200 | 160×100 | 30 | nearest |
| balanced | 640×360 | 320×180 | 30 | linear |
| high | 960×540 | 480×270 | 30 | linear |

Override `performance.generator_resolution`, `simulation_resolution`, `simulation_hz`, `upscale`, and `state_cache` independently. Quality also scales unspecified populations, attractor point batches, fractal iterations and mesh detail. Explicit values override quality scaling. Internal dimensions are bounded to 16–1920 with at most 1920×1080 pixels. Simulations use fixed timesteps of `1/simulation_hz`; reaction-diffusion performs its configured substeps within each tick. Output FPS changes do not change an unmodulated simulation's stepping. Different simulation Hz or resolution can change its numerical trajectory and aesthetic.

State is initialized once, stepped while active, and disposed on eviction or renderer shutdown. `retain_state: true` resumes a motif after interruptions; absence pauses that simulation. The bounded LRU cache holds 2–8 scene instances (default four). Evicted motifs restart from their seed. Overlapping occurrences fork independent state so a transition never reads/writes the same simulation recursively. Generated overlay state stays bounded per configured overlay ID. Frame buffers, particles and density fields do not grow with mix duration. Spatial maps are cached within runtime instances.

Analytical frames support direct time access. Stateful scenes reconstruct local steps when a preview begins mid-scene. Audio features are sampled at simulation ticks; source-video injection and explicit control values are held from the current output frame while catching up. Approximate previews therefore cannot recreate missing prior video/feedback history. Use `preview --exact-history` for preceding composition history at the preview's resolution. Resolution changes, OpenCV implementations and floating-point differences can alter pixels across machines; deterministic planning is stronger than cross-platform pixel identity.

Use `--profile` for measured per-effect and per-generator frame costs. Draft auditions are useful for artistic tuning; 1080p output with optical flow or many simulations can be slower than real time. There is no multi-hour throughput guarantee. Local automated media tests and demo renders run on Windows; Windows/Ubuntu CI is configured, but Linux rendering has not been locally validated.

## Algorithms and limits

Plasma, tunnels, rotozoom, implicit metaballs, moiré, value-noise fBm, Voronoi distance fields, escape-time fractals and 3D wireframe projection are mathematical image generators. Gray–Scott uses coupled reaction/diffusion fields, following the equations described by [Karl Sims](https://www.karlsims.com/rd.html). Flow fields move bounded particles through gradients/vortices; agent trail sensing follows the principles in [Jeff Jones's particle model](https://arxiv.org/abs/1511.05774). Flocking approximates local neighbors through grid aggregates rather than exact all-pairs interactions, consistent with the scalability concerns in [Reynolds's boids work](https://www.red3d.com/cwr/boids/). Dye advection is semi-Lagrangian transport with prescribed vortices and damping, without a pressure projection; it is not a complete incompressible fluid solver.

Attractors use actual Clifford/De Jong maps or numerically integrated Lorenz/Rössler systems. IFS uses weighted affine chaos-game transforms. Cellular options implement Life, elementary rules, cyclic systems, and a continuous approximation. Recursive geometry feeds its previous transformed image into the next tick. These are original CPU implementations; analog display, composite, camcorder and codec damage remain explicitly described simulations in the synthesis guide.

Optional GLSL/raymarching remains deferred. [ModernGL supports standalone contexts](https://moderngl.readthedocs.io/en/stable/topics/context.html), but this pass does not establish reliable Windows and headless Linux context creation. There are no placeholder GPU generators, copied third-party shaders, deep-zoom precision promises, or genuine codec-datamoshing claims.

## Parameter reference

The tables below reflect the catalog. Numeric pairs in scene configuration select a fixed value from that range. Unless marked initialization-only, numeric parameters accept modulation. Enum options are initialization-only. `speed` controls time/movement; `palette_phase` is measured in palette cycles; `audio_influence` scales built-in audio response from 0 to 1. Distances and particle fields use internal-canvas pixels; angles in oscillators/sensors are radians, wireframe rotation uses radians, and recursive rotation is degrees per nominal 30 Hz step. Decay and persistence units follow the individual algorithm (per-second trail loss, seconds of accumulation, or recursive per-step gain).

### plasma

Warped trigonometric interference with radial oscillators and palette cycling.

Analytical; low relative cost. Recommended scene: 8–40 seconds. Inputs: none.

| Parameter | Default | Bounds | Initialization only |
| --- | --- | --- | --- |
| `speed` | 0.35 | -3…3 |  |
| `palette_phase` | 0 | -100…100 |  |
| `audio_influence` | 0.35 | 0…1 |  |
| `frequency` | 3 | 0.2…12 |  |
| `oscillators` | 4 | 2…8 |  |
| `warp` | 0.4 | 0…2 |  |
| `radial` | 0.7 | 0…2 |  |
| `pixel_size` | 1 | 1…16 |  |

### tunnel

Polar-coordinate texture tunnel with depth attenuation and drifting center.

Analytical; low relative cost. Recommended scene: 8–40 seconds. Inputs: optional video.

| Parameter | Default | Bounds | Initialization only |
| --- | --- | --- | --- |
| `speed` | 0.35 | -3…3 |  |
| `palette_phase` | 0 | -100…100 |  |
| `audio_influence` | 0.35 | 0…1 |  |
| `depth` | 2.5 | 0.3…8 |  |
| `rotation` | 0.15 | -2…2 |  |
| `curvature` | 0.15 | 0…1 |  |
| `drift` | 0.08 | 0…0.3 |  |
| `tiles` | 6 | 1…24 |  |
| `texture_mix` | 0 | 0…1 |  |

### rotozoom

Rotating, zooming, mirrored or tiled procedural/video texture.

Analytical; low relative cost. Recommended scene: 8–40 seconds. Inputs: optional video.

| Parameter | Default | Bounds | Initialization only |
| --- | --- | --- | --- |
| `speed` | 0.35 | -3…3 |  |
| `palette_phase` | 0 | -100…100 |  |
| `audio_influence` | 0.35 | 0…1 |  |
| `rotation` | 0.22 | -3…3 |  |
| `zoom` | 1.5 | 0.15…8 |  |
| `zoom_motion` | 0.45 | 0…0.9 |  |
| `perspective` | 0.2 | -0.8…0.8 |  |
| `tiles` | 4 | 1…24 |  |
| `texture_mix` | 0 | 0…1 |  |
| `tiling` | mirror | mirror, repeat | yes |

### metaballs

Moving inverse-square fields, merging contours and gradient shading.

Analytical; medium relative cost. Recommended scene: 8–40 seconds. Inputs: none.

| Parameter | Default | Bounds | Initialization only |
| --- | --- | --- | --- |
| `speed` | 0.35 | -3…3 |  |
| `palette_phase` | 0 | -100…100 |  |
| `audio_influence` | 0.35 | 0…1 |  |
| `count` | 6 | 2…16 | yes |
| `radius` | 0.14 | 0.03…0.4 |  |
| `attraction` | 1 | 0.3…2 |  |
| `threshold` | 1.2 | 0.2…5 |  |
| `contours` | 5 | 1…16 |  |
| `shading` | 0.65 | 0…1 |  |
| `style` | smooth | smooth, contours, threshold | yes |

### interference

Rotating grids, concentric wave centers and thresholded moire.

Analytical; medium relative cost. Recommended scene: 8–40 seconds. Inputs: none.

| Parameter | Default | Bounds | Initialization only |
| --- | --- | --- | --- |
| `speed` | 0.35 | -3…3 |  |
| `palette_phase` | 0 | -100…100 |  |
| `audio_influence` | 0.35 | 0…1 |  |
| `frequency` | 12 | 1…48 |  |
| `rotation` | 0.05 | -0.5…0.5 |  |
| `phase_modulation` | 0.5 | 0…3 |  |
| `threshold` | 0.5 | 0…1 |  |
| `sharpness` | 0.2 | 0.01…1 |  |

### floor_cast

Perspective-cast infinite checker/grid planes with horizon and fog.

Analytical; low relative cost. Recommended scene: 8–40 seconds. Inputs: optional video.

| Parameter | Default | Bounds | Initialization only |
| --- | --- | --- | --- |
| `speed` | 0.35 | -3…3 |  |
| `palette_phase` | 0 | -100…100 |  |
| `audio_influence` | 0.35 | 0…1 |  |
| `horizon` | 0.42 | 0.2…0.65 |  |
| `rotation` | 0.1 | -1…1 |  |
| `scale` | 4 | 1…20 |  |
| `fog` | 0.12 | 0.01…1 |  |
| `texture_mix` | 0 | 0…1 |  |
| `pattern` | grid | grid, checker, landscape | yes |

### wireframe

Perspective-projected 3D objects, parametric surfaces and curves.

Analytical; medium relative cost. Recommended scene: 8–40 seconds. Inputs: none.

| Parameter | Default | Bounds | Initialization only |
| --- | --- | --- | --- |
| `speed` | 0.35 | -3…3 |  |
| `palette_phase` | 0 | -100…100 |  |
| `audio_influence` | 0.35 | 0…1 |  |
| `rotation` | 0.3 | -2…2 |  |
| `deformation` | 0.1 | 0…0.6 |  |
| `detail` | 20 | 6…48 | yes |
| `camera` | 4 | 2.5…8 |  |
| `thickness` | 1 | 1…3 |  |
| `geometry` | torus | torus, cube, icosahedron, sphere, surface, lissajous, mesh | yes |

### fractal

Mandelbrot/Julia exploration with smooth escape coloring and orbit traps.

Analytical; high relative cost. Recommended scene: 20–120 seconds. Inputs: none.

| Parameter | Default | Bounds | Initialization only |
| --- | --- | --- | --- |
| `speed` | 0.35 | -3…3 |  |
| `palette_phase` | 0 | -100…100 |  |
| `audio_influence` | 0.35 | 0…1 |  |
| `iterations` | 64 | 16…192 | yes |
| `zoom_rate` | 0.08 | -0.3…0.3 |  |
| `center_x` | -0.72 | -2…2 |  |
| `center_y` | 0.17 | -1.5…1.5 |  |
| `julia_real` | -0.745 | -1.2…1.2 |  |
| `julia_imag` | 0.186 | -1.2…1.2 |  |
| `orbit_trap` | 0.2 | 0…1 |  |
| `set` | julia | julia, mandelbrot | yes |

### domain_warp

Coherent value-noise fBm with nested domain warping and ridged detail.

Analytical; medium relative cost. Recommended scene: 8–40 seconds. Inputs: none.

| Parameter | Default | Bounds | Initialization only |
| --- | --- | --- | --- |
| `speed` | 0.35 | -3…3 |  |
| `palette_phase` | 0 | -100…100 |  |
| `audio_influence` | 0.35 | 0…1 |  |
| `frequency` | 3 | 0.2…10 |  |
| `octaves` | 4 | 1…6 | yes |
| `warp` | 1.2 | 0…4 |  |
| `ridges` | 0.3 | 0…1 |  |
| `contours` | 0.2 | 0…1 |  |

### voronoi

Moving Worley sites, colored cells and softly outlined distance fields.

Analytical; medium relative cost. Recommended scene: 8–40 seconds. Inputs: none.

| Parameter | Default | Bounds | Initialization only |
| --- | --- | --- | --- |
| `speed` | 0.35 | -3…3 |  |
| `palette_phase` | 0 | -100…100 |  |
| `audio_influence` | 0.35 | 0…1 |  |
| `count` | 18 | 4…48 | yes |
| `movement` | 0.4 | 0…1 |  |
| `borders` | 0.5 | 0…1 |  |
| `warp` | 0.12 | 0…0.4 |  |

### reaction_diffusion

Gray-Scott chemical simulation with bounded video/audio injection.

Simulation; medium relative cost. Recommended scene: 20–180 seconds. Inputs: optional video.

| Parameter | Default | Bounds | Initialization only |
| --- | --- | --- | --- |
| `speed` | 0.35 | 0…3 |  |
| `palette_phase` | 0 | -100…100 |  |
| `audio_influence` | 0.35 | 0…1 |  |
| `diffusion_a` | 1 | 0.5…1 | yes |
| `diffusion_b` | 0.5 | 0.1…0.5 | yes |
| `feed` | 0.0367 | 0.015…0.065 | yes |
| `kill` | 0.0649 | 0.045…0.075 | yes |
| `iterations` | 8 | 1…16 | yes |
| `injection_strength` | 0.1 | 0…0.5 |  |
| `disturbance_radius` | 5 | 1…24 |  |
| `video_injection` | 0 | 0…0.2 |  |
| `contours` | 0.3 | 0…1 |  |
| `initialization` | spots | spots, stripe, noise | yes |

### flow_field

Bounded particles advected by coherent curl fields, vortices or image gradients.

Simulation; medium relative cost. Recommended scene: 12–90 seconds. Inputs: optional video.

| Parameter | Default | Bounds | Initialization only |
| --- | --- | --- | --- |
| `speed` | 0.35 | 0…3 |  |
| `palette_phase` | 0 | -100…100 |  |
| `audio_influence` | 0.35 | 0…1 |  |
| `population` | 1800 | 100…12000 | yes |
| `vortex` | 0.6 | 0…3 |  |
| `frequency` | 2 | 0.2…8 |  |
| `trail_decay` | 0.8 | 0.1…3 |  |
| `lifetime` | 12 | 2…60 |  |
| `video_influence` | 0 | 0…2 |  |
| `injection_strength` | 0.3 | 0…1 |  |
| `field` | curl | curl, vortex, attractor, repeller, image, oscillator | yes |

### particle_field

Image-driven flow particles colored by source footage or palette.

Simulation; medium relative cost. Recommended scene: 12–90 seconds. Inputs: optional video.

| Parameter | Default | Bounds | Initialization only |
| --- | --- | --- | --- |
| `speed` | 0.35 | 0…3 |  |
| `palette_phase` | 0 | -100…100 |  |
| `audio_influence` | 0.35 | 0…1 |  |
| `population` | 1800 | 100…12000 | yes |
| `vortex` | 0.6 | 0…3 |  |
| `frequency` | 2 | 0.2…8 |  |
| `trail_decay` | 0.8 | 0.1…3 |  |
| `lifetime` | 12 | 2…60 |  |
| `video_influence` | 1 | 0…2 |  |
| `injection_strength` | 0.3 | 0…1 |  |
| `field` | image | curl, vortex, attractor, repeller, image, oscillator | yes |

### strange_attractor

Incrementally accumulated Clifford, De Jong, Lorenz or Rossler trajectories.

Simulation; medium relative cost. Recommended scene: 20–120 seconds. Inputs: none.

| Parameter | Default | Bounds | Initialization only |
| --- | --- | --- | --- |
| `speed` | 0.35 | 0…3 |  |
| `palette_phase` | 0 | -100…100 |  |
| `audio_influence` | 0.35 | 0…1 |  |
| `points_per_step` | 700 | 100…3000 | yes |
| `persistence` | 2 | 0.2…10 |  |
| `drift` | 0.03 | 0…0.2 |  |
| `symmetry` | 1 | 1…8 | yes |
| `disturbance` | 0.05 | 0…0.5 |  |
| `system` | clifford | clifford, de_jong, lorenz, rossler | yes |

### recursive_geometry

Autonomous image recursion seeded by shapes, noise and optional video.

Feedback; medium relative cost. Recommended scene: 15–120 seconds. Inputs: optional video.

| Parameter | Default | Bounds | Initialization only |
| --- | --- | --- | --- |
| `speed` | 0.35 | 0…3 |  |
| `palette_phase` | 0 | -100…100 |  |
| `audio_influence` | 0.35 | 0…1 |  |
| `zoom` | 1.008 | 0.94…1.06 |  |
| `rotation` | 0.3 | -2…2 |  |
| `decay` | 0.985 | 0.9…1.04 |  |
| `injection_strength` | 0.12 | 0.01…0.5 |  |
| `warp` | 0.5 | 0…3 |  |
| `video_injection` | 0 | 0…0.3 |  |
| `symmetry` | mirror | mirror, kaleidoscope, none | yes |

### cellular_automata

Life, elementary, cyclic or smooth continuous cellular systems with aging.

Simulation; medium relative cost. Recommended scene: 12–60 seconds. Inputs: optional video.

| Parameter | Default | Bounds | Initialization only |
| --- | --- | --- | --- |
| `speed` | 0.35 | 0…3 |  |
| `palette_phase` | 0 | -100…100 |  |
| `audio_influence` | 0.35 | 0…1 |  |
| `update_rate` | 6 | 1…30 |  |
| `density` | 0.3 | 0.05…0.8 | yes |
| `states` | 12 | 3…24 | yes |
| `rule` | 110 | 0…255 | yes |
| `disturbance` | 0.03 | 0…0.3 |  |
| `video_injection` | 0 | 0…1 |  |
| `system` | cyclic | life, elementary, cyclic, smooth | yes |

### starfield

Colored perspective particle populations with coherent hyperspace trails.

Simulation; medium relative cost. Recommended scene: 8–40 seconds. Inputs: none.

| Parameter | Default | Bounds | Initialization only |
| --- | --- | --- | --- |
| `speed` | 0.35 | 0…3 |  |
| `palette_phase` | 0 | -100…100 |  |
| `audio_influence` | 0.35 | 0…1 |  |
| `population` | 1400 | 100…10000 | yes |
| `rotation` | 0.08 | -1…1 |  |
| `drift` | 0.15 | 0…0.6 |  |
| `radial_acceleration` | 0.1 | 0…2 |  |
| `trail_decay` | 2.5 | 0.2…8 |  |

### physarum

Chemotactic agents sensing and depositing into a diffusing shared trail field.

Simulation; high relative cost. Recommended scene: 25–180 seconds. Inputs: none.

| Parameter | Default | Bounds | Initialization only |
| --- | --- | --- | --- |
| `speed` | 0.35 | 0…3 |  |
| `palette_phase` | 0 | -100…100 |  |
| `audio_influence` | 0.35 | 0…1 |  |
| `population` | 5000 | 500…20000 | yes |
| `sensor_angle` | 0.6 | 0.1…1.5 |  |
| `sensor_distance` | 6 | 2…24 |  |
| `turn_rate` | 2 | 0.2…6 |  |
| `movement` | 16 | 2…60 |  |
| `diffusion` | 0.7 | 0.1…2 |  |
| `trail_decay` | 0.45 | 0.05…2 |  |
| `deposit` | 0.15 | 0.02…0.5 |  |
| `disturbance` | 0.2 | 0…1 |  |
| `initialization` | uniform | uniform, disk | yes |

### boids

Grid-partitioned flocking with separation, alignment and cohesion; no all-pairs matrix.

Simulation; medium relative cost. Recommended scene: 15–90 seconds. Inputs: none.

| Parameter | Default | Bounds | Initialization only |
| --- | --- | --- | --- |
| `speed` | 0.35 | 0…3 |  |
| `palette_phase` | 0 | -100…100 |  |
| `audio_influence` | 0.35 | 0…1 |  |
| `population` | 700 | 100…4000 | yes |
| `separation` | 1.2 | 0…3 |  |
| `alignment` | 0.7 | 0…3 |  |
| `cohesion` | 0.6 | 0…3 |  |
| `neighborhood` | 12 | 5…32 | yes |
| `trail_decay` | 2 | 0.1…6 |  |
| `attraction` | 0.2 | -1…1 |  |

### fluid_advection

Semi-Lagrangian dye advection through damped vortical velocity fields.

Simulation; medium relative cost. Recommended scene: 20–120 seconds. Inputs: optional video.

| Parameter | Default | Bounds | Initialization only |
| --- | --- | --- | --- |
| `speed` | 0.35 | 0…3 |  |
| `palette_phase` | 0 | -100…100 |  |
| `audio_influence` | 0.35 | 0…1 |  |
| `vorticity` | 0.8 | 0…3 |  |
| `dissipation` | 0.25 | 0.02…2 |  |
| `diffusion` | 0.4 | 0…2 |  |
| `injection_strength` | 0.25 | 0.01…1 |  |
| `video_injection` | 0 | 0…0.5 |  |

### ifs

Weighted affine chaos-game fern or triangular fractals with bounded density accumulation.

Simulation; medium relative cost. Recommended scene: 20–120 seconds. Inputs: none.

| Parameter | Default | Bounds | Initialization only |
| --- | --- | --- | --- |
| `speed` | 0.35 | 0…3 |  |
| `palette_phase` | 0 | -100…100 |  |
| `audio_influence` | 0.35 | 0…1 |  |
| `points_per_step` | 800 | 100…3000 | yes |
| `symmetry` | 1 | 1…8 | yes |
| `persistence` | 3 | 0.2…10 |  |
| `deformation` | 0.02 | 0…0.15 |  |
| `system` | fern | fern, sierpinski | yes |
