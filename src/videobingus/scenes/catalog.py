"""The authoritative scene catalog: parameters, capabilities and suite selection metadata."""

from copy import deepcopy

COMMON = {"speed": (0.35, -3, 3), "palette_phase": (0, -100, 100), "audio_influence": (0.35, 0, 1)}


def entry(
    description,
    category,
    tags,
    parameters,
    *,
    options=None,
    structural=(),
    cost="medium",
    duration=(8, 40),
    profiles=(),
    triggers=(),
):
    parameters = {**COMMON, **parameters}
    if category != "analytical":
        parameters["speed"] = (0.35, 0, 3)
    return {
        "description": description,
        "category": category,
        "tags": tags.split(),
        "parameters": parameters,
        "options": options or {},
        "initialization_only": list(structural),
        "modulatable": [p for p in parameters if p not in structural],
        "triggers": list(dict.fromkeys([*triggers, *(["reset"] if category != "analytical" else [])])),
        "stateful": category != "analytical",
        "cost": cost,
        "backend": "cpu",
        "stages": ["primary", "overlay", "mask", "displacement", "texture"],
        "inputs": "optional video"
        if {"texture_mix", "video_injection", "video_influence"} & parameters.keys()
        else "none",
        "recommended_scene_duration": list(duration),
        "profiles": list(profiles),
    }


CATALOG = {
    "plasma": entry(
        "Warped trigonometric interference with radial oscillators and palette cycling.",
        "analytical",
        "retro demoscene psychedelic geometric",
        {
            "frequency": (3, 0.2, 12),
            "oscillators": (4, 2, 8),
            "warp": (0.4, 0, 2),
            "radial": (0.7, 0, 2),
            "pixel_size": (1, 1, 16),
        },
        profiles=["spectral_color", "slow_breathing"],
        cost="low",
    ),
    "tunnel": entry(
        "Polar-coordinate texture tunnel with depth attenuation and drifting center.",
        "analytical",
        "retro demoscene geometric spatial",
        {
            "depth": (2.5, 0.3, 8),
            "rotation": (0.15, -2, 2),
            "curvature": (0.15, 0, 1),
            "drift": (0.08, 0, 0.3),
            "tiles": (6, 1, 24),
            "texture_mix": (0, 0, 1),
        },
        profiles=["sub_pressure", "spectral_color"],
        cost="low",
    ),
    "rotozoom": entry(
        "Rotating, zooming, mirrored or tiled procedural/video texture.",
        "analytical",
        "retro demoscene geometric",
        {
            "rotation": (0.22, -3, 3),
            "zoom": (1.5, 0.15, 8),
            "zoom_motion": (0.45, 0, 0.9),
            "perspective": (0.2, -0.8, 0.8),
            "tiles": (4, 1, 24),
            "texture_mix": (0, 0, 1),
        },
        options={"tiling": ("mirror", ["mirror", "repeat"])},
        profiles=["sub_pressure"],
        cost="low",
    ),
    "metaballs": entry(
        "Moving inverse-square fields, merging contours and gradient shading.",
        "analytical",
        "organic demoscene psychedelic",
        {
            "count": (6, 2, 16),
            "radius": (0.14, 0.03, 0.4),
            "attraction": (1, 0.3, 2),
            "threshold": (1.2, 0.2, 5),
            "contours": (5, 1, 16),
            "shading": (0.65, 0, 1),
        },
        structural=["count"],
        options={"style": ("smooth", ["smooth", "contours", "threshold"])},
        profiles=["sub_pressure", "transient_injection"],
    ),
    "interference": entry(
        "Rotating grids, concentric wave centers and thresholded moire.",
        "analytical",
        "analog geometric psychedelic minimal",
        {
            "frequency": (12, 1, 48),
            "rotation": (0.05, -0.5, 0.5),
            "phase_modulation": (0.5, 0, 3),
            "threshold": (0.5, 0, 1),
            "sharpness": (0.2, 0.01, 1),
        },
        profiles=["spectral_color"],
    ),
    "floor_cast": entry(
        "Perspective-cast infinite checker/grid planes with horizon and fog.",
        "analytical",
        "retro demoscene industrial geometric spatial",
        {
            "horizon": (0.42, 0.2, 0.65),
            "rotation": (0.1, -1, 1),
            "scale": (4, 1, 20),
            "fog": (0.12, 0.01, 1),
            "texture_mix": (0, 0, 1),
        },
        options={"pattern": ("grid", ["grid", "checker", "landscape"])},
        cost="low",
        profiles=["sub_pressure"],
    ),
    "wireframe": entry(
        "Perspective-projected 3D objects, parametric surfaces and curves.",
        "analytical",
        "retro demoscene geometric industrial vector",
        {
            "rotation": (0.3, -2, 2),
            "deformation": (0.1, 0, 0.6),
            "detail": (20, 6, 48),
            "camera": (4, 2.5, 8),
            "thickness": (1, 1, 3),
        },
        structural=["detail"],
        options={
            "geometry": ("torus", ["torus", "cube", "icosahedron", "sphere", "surface", "lissajous", "mesh"])
        },
        profiles=["sub_pressure", "rhythmic_disturbance"],
    ),
    "fractal": entry(
        "Mandelbrot/Julia exploration with smooth escape coloring and orbit traps.",
        "analytical",
        "mathematical ambient geometric",
        {
            "iterations": (64, 16, 192),
            "zoom_rate": (0.08, -0.3, 0.3),
            "center_x": (-0.72, -2, 2),
            "center_y": (0.17, -1.5, 1.5),
            "julia_real": (-0.745, -1.2, 1.2),
            "julia_imag": (0.186, -1.2, 1.2),
            "orbit_trap": (0.2, 0, 1),
        },
        structural=["iterations"],
        cost="high",
        duration=(20, 120),
        options={"set": ("julia", ["julia", "mandelbrot"])},
        profiles=["spectral_color", "slow_breathing"],
    ),
    "domain_warp": entry(
        "Coherent value-noise fBm with nested domain warping and ridged detail.",
        "analytical",
        "organic mathematical ambient",
        {
            "frequency": (3, 0.2, 10),
            "octaves": (4, 1, 6),
            "warp": (1.2, 0, 4),
            "ridges": (0.3, 0, 1),
            "contours": (0.2, 0, 1),
        },
        structural=["octaves"],
        profiles=["sub_pressure", "slow_breathing"],
    ),
    "voronoi": entry(
        "Moving Worley sites, colored cells and softly outlined distance fields.",
        "analytical",
        "organic geometric psychedelic",
        {"count": (18, 4, 48), "movement": (0.4, 0, 1), "borders": (0.5, 0, 1), "warp": (0.12, 0, 0.4)},
        structural=["count"],
        profiles=["sub_pressure", "spectral_color"],
    ),
    "reaction_diffusion": entry(
        "Gray-Scott chemical simulation with bounded video/audio injection.",
        "simulation",
        "organic artificial_life slow mathematical",
        {
            "diffusion_a": (1, 0.5, 1),
            "diffusion_b": (0.5, 0.1, 0.5),
            "feed": (0.0367, 0.015, 0.065),
            "kill": (0.0649, 0.045, 0.075),
            "iterations": (8, 1, 16),
            "injection_strength": (0.1, 0, 0.5),
            "disturbance_radius": (5, 1, 24),
            "video_injection": (0, 0, 0.2),
            "contours": (0.3, 0, 1),
        },
        structural=["diffusion_a", "diffusion_b", "feed", "kill", "iterations"],
        options={"initialization": ("spots", ["spots", "stripe", "noise"])},
        duration=(20, 180),
        profiles=["transient_injection", "energy_accumulation"],
        triggers=["disturbance", "reset"],
    ),
    "flow_field": entry(
        "Bounded particles advected by coherent curl fields, vortices or image gradients.",
        "simulation",
        "organic artificial_life ambient particle",
        {
            "population": (1800, 100, 12000),
            "vortex": (0.6, 0, 3),
            "frequency": (2, 0.2, 8),
            "trail_decay": (0.8, 0.1, 3),
            "lifetime": (12, 2, 60),
            "video_influence": (0, 0, 2),
            "injection_strength": (0.3, 0, 1),
        },
        structural=["population"],
        duration=(12, 90),
        options={"field": ("curl", ["curl", "vortex", "attractor", "repeller", "image", "oscillator"])},
        profiles=["sub_pressure", "transient_injection"],
        triggers=["disturbance"],
    ),
    "particle_field": entry(
        "Image-driven flow particles colored by source footage or palette.",
        "simulation",
        "particle organic hybrid",
        {
            "population": (1800, 100, 12000),
            "vortex": (0.6, 0, 3),
            "frequency": (2, 0.2, 8),
            "trail_decay": (0.8, 0.1, 3),
            "lifetime": (12, 2, 60),
            "video_influence": (1, 0, 2),
            "injection_strength": (0.3, 0, 1),
        },
        structural=["population"],
        duration=(12, 90),
        options={"field": ("image", ["curl", "vortex", "attractor", "repeller", "image", "oscillator"])},
        profiles=["sub_pressure", "transient_injection"],
        triggers=["disturbance"],
    ),
    "strange_attractor": entry(
        "Incrementally accumulated Clifford, De Jong, Lorenz or Rossler trajectories.",
        "simulation",
        "mathematical ambient vector organic",
        {
            "points_per_step": (700, 100, 3000),
            "persistence": (2, 0.2, 10),
            "drift": (0.03, 0, 0.2),
            "symmetry": (1, 1, 8),
            "disturbance": (0.05, 0, 0.5),
        },
        structural=["points_per_step", "symmetry"],
        options={"system": ("clifford", ["clifford", "de_jong", "lorenz", "rossler"])},
        duration=(20, 120),
        profiles=["rhythmic_disturbance", "slow_breathing"],
        triggers=["disturbance"],
    ),
    "recursive_geometry": entry(
        "Autonomous image recursion seeded by shapes, noise and optional video.",
        "feedback",
        "analog geometric psychedelic ambient",
        {
            "zoom": (1.008, 0.94, 1.06),
            "rotation": (0.3, -2, 2),
            "decay": (0.985, 0.9, 1.04),
            "injection_strength": (0.12, 0.01, 0.5),
            "warp": (0.5, 0, 3),
            "video_injection": (0, 0, 0.3),
        },
        options={"symmetry": ("mirror", ["mirror", "kaleidoscope", "none"])},
        duration=(15, 120),
        profiles=["slow_breathing", "sub_pressure"],
        triggers=["disturbance", "reset"],
    ),
    "cellular_automata": entry(
        "Life, elementary, cyclic or smooth continuous cellular systems with aging.",
        "simulation",
        "digital artificial_life geometric",
        {
            "update_rate": (6, 1, 30),
            "density": (0.3, 0.05, 0.8),
            "states": (12, 3, 24),
            "rule": (110, 0, 255),
            "disturbance": (0.03, 0, 0.3),
            "video_injection": (0, 0, 1),
        },
        structural=["density", "states", "rule"],
        duration=(12, 60),
        options={"system": ("cyclic", ["life", "elementary", "cyclic", "smooth"])},
        profiles=["rhythmic_disturbance", "spectral_color"],
        triggers=["disturbance", "reset"],
    ),
    "starfield": entry(
        "Colored perspective particle populations with coherent hyperspace trails.",
        "simulation",
        "spatial demoscene ambient particle",
        {
            "population": (1400, 100, 10000),
            "rotation": (0.08, -1, 1),
            "drift": (0.15, 0, 0.6),
            "radial_acceleration": (0.1, 0, 2),
            "trail_decay": (2.5, 0.2, 8),
        },
        structural=["population"],
        profiles=["sub_pressure", "energy_accumulation"],
    ),
    "physarum": entry(
        "Chemotactic agents sensing and depositing into a diffusing shared trail field.",
        "simulation",
        "organic artificial_life slow",
        {
            "population": (5000, 500, 20000),
            "sensor_angle": (0.6, 0.1, 1.5),
            "sensor_distance": (6, 2, 24),
            "turn_rate": (2, 0.2, 6),
            "movement": (16, 2, 60),
            "diffusion": (0.7, 0.1, 2),
            "trail_decay": (0.45, 0.05, 2),
            "deposit": (0.15, 0.02, 0.5),
            "disturbance": (0.2, 0, 1),
        },
        structural=["population"],
        options={"initialization": ("uniform", ["uniform", "disk"])},
        cost="high",
        duration=(25, 180),
        profiles=["transient_injection", "energy_accumulation"],
        triggers=["disturbance"],
    ),
    "boids": entry(
        "Grid-partitioned flocking with separation, alignment and cohesion; no all-pairs matrix.",
        "simulation",
        "organic artificial_life particle",
        {
            "population": (700, 100, 4000),
            "separation": (1.2, 0, 3),
            "alignment": (0.7, 0, 3),
            "cohesion": (0.6, 0, 3),
            "neighborhood": (12, 5, 32),
            "trail_decay": (2, 0.1, 6),
            "attraction": (0.2, -1, 1),
        },
        structural=["population", "neighborhood"],
        duration=(15, 90),
        profiles=["sub_pressure", "rhythmic_disturbance"],
    ),
    "fluid_advection": entry(
        "Semi-Lagrangian dye advection through damped vortical velocity fields.",
        "simulation",
        "organic ambient artificial_life",
        {
            "vorticity": (0.8, 0, 3),
            "dissipation": (0.25, 0.02, 2),
            "diffusion": (0.4, 0, 2),
            "injection_strength": (0.25, 0.01, 1),
            "video_injection": (0, 0, 0.5),
        },
        duration=(20, 120),
        profiles=["sub_pressure", "transient_injection"],
        triggers=["disturbance"],
    ),
    "ifs": entry(
        "Weighted affine chaos-game fern or triangular fractals with bounded density accumulation.",
        "simulation",
        "mathematical organic ambient",
        {
            "points_per_step": (800, 100, 3000),
            "symmetry": (1, 1, 8),
            "persistence": (3, 0.2, 10),
            "deformation": (0.02, 0, 0.15),
        },
        structural=["points_per_step", "symmetry"],
        duration=(20, 120),
        options={"system": ("fern", ["fern", "sierpinski"])},
        profiles=["slow_breathing", "spectral_color"],
    ),
}


def defaults(kind):
    spec = CATALOG[kind]
    return {
        **{k: v[0] for k, v in spec["parameters"].items()},
        **{k: v[0] for k, v in spec["options"].items()},
    }


def validate_params(kind, params, modulation=False):
    if kind not in CATALOG:
        raise ValueError(f"Unknown scene generator: {kind}")
    spec = CATALOG[kind]
    for name, value in params.items():
        if name in spec["options"] and not modulation:
            if value not in spec["options"][name][1]:
                raise ValueError(f"{kind}.{name}: choose from {spec['options'][name][1]}")
        elif name in spec["parameters"]:
            if modulation and name not in spec["modulatable"]:
                raise ValueError(f"{kind}.{name} is initialization-only and cannot be modulated")
            low, high = spec["parameters"][name][1:]
            values = value if isinstance(value, (list, tuple)) else [value]
            if len(values) not in (1, 2) or any(
                not isinstance(v, (int, float)) or not low <= v <= high for v in values
            ):
                raise ValueError(f"{kind}.{name} must lie in [{low}, {high}]")
            if len(values) == 2 and values[0] > values[1]:
                raise ValueError(f"{kind}.{name} range must be ordered")
        else:
            raise ValueError(f"Unknown or non-modulatable {kind} parameter: {name}")


def describe(kind):
    return {"type": kind, **deepcopy(CATALOG[kind]), "defaults": defaults(kind)}
