import math

from .catalog import CATALOG

NAMES = {
    "sub_pressure",
    "transient_injection",
    "spectral_color",
    "energy_accumulation",
    "rhythmic_disturbance",
    "slow_breathing",
    "track_evolution",
    "auto",
}


def apply(kind, parameters, context, profiles):
    result = dict(parameters)
    profiles = list(CATALOG[kind]["profiles"]) if "auto" in profiles else profiles
    safe = CATALOG[kind]["modulatable"]
    amount = result["audio_influence"]
    audio = context.audio

    def influence(names, factor):
        target = next((name for name in names if name in safe), None)
        if target:
            result[target] *= factor

    for profile in profiles:
        if profile == "sub_pressure":
            influence(
                ["vortex", "vorticity", "attraction", "warp", "deformation", "speed"],
                1 + audio.get("bass_energy", 0) * amount,
            )
        elif profile == "transient_injection":
            influence(
                ["injection_strength", "disturbance", "deformation"],
                1 + audio.get("bass_onset", 0) * amount * 2,
            )
        elif profile == "spectral_color":
            result["palette_phase"] += audio.get("high_energy", 0) * amount * 0.25
        elif profile == "energy_accumulation":
            influence(["speed", "vortex"], 0.7 + audio.get("sustained_energy", audio.get("rms", 0)) * amount)
        elif profile == "rhythmic_disturbance":
            influence(["disturbance", "deformation", "warp"], 1 + audio.get("onset", 0) * amount)
        elif profile == "slow_breathing":
            influence(["speed", "warp"], 1 + 0.15 * math.sin(context.time * 0.15))
        elif profile == "track_evolution":
            result["palette_phase"] += audio.get("track_progress", 0) * 0.25
    if "visual_intensity" in audio:
        influence(["speed"], 0.6 + 0.5 * audio["visual_intensity"])
    for name in safe:
        low, high = CATALOG[kind]["parameters"][name][1:]
        result[name] = min(high, max(low, result[name]))
    return result
