import cv2
import numpy as np

from ..palettes import map_colors


def grid(data, size):
    if data.get("grid_size") != size:
        w, h = size
        y, x = np.indices((h, w), dtype=np.float32)
        nx, ny = (x / max(1, w - 1) * 2 - 1) * w / h, y / max(1, h - 1) * 2 - 1
        data.update(grid_size=size, grid=(nx, ny, np.hypot(nx, ny), np.arctan2(ny, nx)))
    return data["grid"]


def noise(x, y, z, seed):
    ix, iy, iz = np.floor(x).astype(np.int32), np.floor(y).astype(np.int32), int(np.floor(z))
    fx, fy, fz = x - ix, y - iy, z % 1
    fx, fy, fz = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy), fz * fz * (3 - 2 * fz)

    def hashed(a, b, c):
        value = (
            a.astype(np.uint32) * np.uint32(374761393)
            + b.astype(np.uint32) * np.uint32(668265263)
            + np.uint32((c * 1442695041 + seed) & 0xFFFFFFFF)
        )
        value = (value ^ (value >> 13)) * np.uint32(1274126177)
        return ((value ^ (value >> 16)) & np.uint32(0xFFFFFF)).astype(np.float32) / 16777215

    levels = []
    for dz in (0, 1):
        a = hashed(ix, iy, iz + dz) * (1 - fx) + hashed(ix + 1, iy, iz + dz) * fx
        b = hashed(ix, iy + 1, iz + dz) * (1 - fx) + hashed(ix + 1, iy + 1, iz + dz) * fx
        levels.append(a * (1 - fy) + b * fy)
    return levels[0] * (1 - fz) + levels[1] * fz


def fbm(x, y, t, octaves, seed):
    result = np.zeros_like(x)
    amplitude, total = 0.5, 0
    for octave in range(round(octaves)):
        result += noise(x, y, t, seed + octave * 101) * amplitude
        total += amplitude
        x, y, t, amplitude = x * 2.03, y * 2.03, t * 1.7, amplitude * 0.5
    return result / total


def texture(u, v, p, ctx, palette):
    uu, vv = u % 1, v % 1
    if p.get("tiling") == "mirror":
        uu, vv = 1 - np.abs(u % 2 - 1), 1 - np.abs(v % 2 - 1)
    pattern = 0.5 + 0.25 * np.sin(uu * np.pi * 8) + 0.25 * np.cos(vv * np.pi * 8 + uu * 3)
    result = map_colors(pattern, palette, p["palette_phase"] + ctx.local_time * 0.025)
    if ctx.video is not None and p.get("texture_mix", 0):
        h, w = ctx.video.shape[:2]
        image = (
            cv2.remap(
                ctx.video,
                (uu * (w - 1)).astype(np.float32),
                (vv * (h - 1)).astype(np.float32),
                cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_WRAP,
            ).astype(np.float32)
            / 255
        )
        result = result * (1 - p["texture_mix"]) + image * p["texture_mix"]
    return result


def render(kind, size, p, ctx, data, palette, seed):
    x, y, radius, angle = grid(data, size)
    t = ctx.local_time
    bass, mid = ctx.audio.get("bass_energy", 0), ctx.audio.get("mid_energy", 0)
    drive = p["audio_influence"]
    motion = t * p["speed"]
    phase = p["palette_phase"] + motion * 0.04
    if kind == "plasma":
        f = p["frequency"] * (1 + mid * drive * 0.4)
        warp = p["warp"] * (1 + drive * bass)
        xx, yy = x + np.sin(y * f + motion) * warp * 0.3, y + np.cos(x * f - motion * 0.7) * warp * 0.3
        signal = np.zeros_like(x)
        for index in range(round(p["oscillators"])):
            a = index * 2.39996
            signal += np.sin((xx * np.cos(a) + yy * np.sin(a)) * f + motion * (1 + index * 0.13))
        signal += np.sin(radius * f * 2 - motion) * p["radial"]
        signal = 0.5 + signal / (2 * (p["oscillators"] + p["radial"]))
        result = map_colors(signal, palette, phase)
        pixel = round(p["pixel_size"])
        if pixel > 1:
            result = cv2.resize(
                cv2.resize(result, (max(1, size[0] // pixel), max(1, size[1] // pixel))),
                size,
                interpolation=cv2.INTER_NEAREST,
            )
        return result
    if kind == "tunnel":
        xx = x - np.sin(t * 0.21) * p["drift"]
        yy = y - np.cos(t * 0.17) * p["drift"]
        r = np.maximum(0.025, np.hypot(xx, yy))
        a = np.arctan2(yy, xx)
        depth = p["depth"] / r
        u = a / (2 * np.pi) * p["tiles"] + t * p["rotation"] + np.sin(depth * 0.1 + motion) * p["curvature"]
        v = depth * 0.13 + motion * (1 + bass * drive * 1.5)
        return texture(u, v, p, ctx, palette) * (0.2 + 0.8 * np.clip(r, 0, 1))[..., None]
    if kind == "rotozoom":
        a = t * p["rotation"] * (1 + drive * bass)
        scale = p["zoom"] * np.exp(np.sin(t * 0.23) * p["zoom_motion"])
        perspective = np.maximum(0.2, 1 + y * p["perspective"])
        u = (x * np.cos(a) - y * np.sin(a)) / (scale * perspective) * p["tiles"] + motion * 0.1
        v = (x * np.sin(a) + y * np.cos(a)) / (scale * perspective) * p["tiles"]
        return texture(u, v, p, ctx, palette)
    if kind == "metaballs":
        phases = data.setdefault("ball_phases", np.random.default_rng(seed).uniform(0, 2 * np.pi, (20, 3)))
        field = np.zeros_like(x)
        count = min(20, round(p["count"]) + int(ctx.audio.get("onset", 0) * drive * 4))
        strength = p["radius"] ** 2 * p["attraction"] * (1 + drive * bass)
        for a, b, c in phases[:count]:
            bx = np.sin(motion * 0.65 + a) * size[0] / size[1] * 0.6
            by = np.cos(motion * 0.83 + b) * 0.65
            field += strength / ((x - bx) ** 2 + (y - by) ** 2 + 0.002 + 0.001 * np.sin(c))
        value = field / p["threshold"]
        if p["style"] == "threshold":
            value = (value >= 1).astype(np.float32)
        elif p["style"] == "contours":
            value = (np.sin(value * p["contours"] * np.pi) + 1) / 2
        else:
            value = np.clip(value, 0, 2) / 2
        gy, gx = np.gradient(np.minimum(field, 5))
        lighting = 0.35 + 0.65 / np.sqrt(1 + (gx * 10) ** 2 + (gy * 10) ** 2)
        return map_colors(value, palette, phase) * (1 - p["shading"] + lighting[..., None] * p["shading"])
    if kind == "interference":
        a = t * p["rotation"]
        xx, yy = x * np.cos(a) - y * np.sin(a), x * np.sin(a) + y * np.cos(a)
        f = p["frequency"] * (1 + mid * drive * 0.15)
        field = np.sin(xx * f + motion) + np.sin(np.hypot(xx - 0.4, yy + 0.2) * f - motion)
        field += np.cos(yy * f * 0.97 + np.sin(xx * 2 + motion) * p["phase_modulation"])
        value = 0.5 + field / 6
        value = np.clip((value - p["threshold"]) / p["sharpness"] + 0.5, 0, 1)
        return map_colors(value, palette, phase)
    if kind == "floor_cast":
        vertical = (y + 1) / 2 - p["horizon"]
        depth = 1 / np.maximum(0.015, vertical)
        a = t * p["rotation"]
        xx, zz = x * depth, depth + motion * 3
        u = (xx * np.cos(a) - zz * np.sin(a)) * p["scale"] * 0.15
        v = (xx * np.sin(a) + zz * np.cos(a)) * p["scale"] * 0.15
        if p["pattern"] == "checker":
            value = (np.floor(u) + np.floor(v)) % 2
        elif p["pattern"] == "landscape":
            value = fbm(u * 0.2, v * 0.2, motion * 0.05, 3, seed)
        else:
            value = ((u % 1 < 0.08) | (v % 1 < 0.08)).astype(np.float32) * 0.8
        result = map_colors(value * 0.8, palette, phase)
        if p["texture_mix"]:
            tex = texture(u, v, p, ctx, palette)
            result = result * (1 - p["texture_mix"]) + tex * p["texture_mix"]
        sky = map_colors(np.clip((y + 1) * 0.1, 0, 0.3), palette, 0, cyclic=False)
        fog = np.exp(-depth * p["fog"])[..., None]
        result = result * fog + sky * (1 - fog)
        return np.where((vertical > 0)[..., None], result, sky)
    if kind == "domain_warp":
        f = p["frequency"]
        q = fbm(x * f, y * f, motion * 0.15, p["octaves"], seed)
        r = fbm(x * f + 3.7, y * f - 1.4, motion * 0.12, p["octaves"], seed + 17)
        value = fbm(
            x * f + q * p["warp"] * 3, y * f + r * p["warp"] * 3, motion * 0.1, p["octaves"], seed + 43
        )
        value = value * (1 - p["ridges"]) + (1 - np.abs(value * 2 - 1)) * p["ridges"]
        contours = 0.5 + 0.5 * np.sin(value * 24 * np.pi)
        return map_colors(value * (1 - p["contours"]) + contours * p["contours"], palette, phase)
    if kind == "voronoi":
        phases = data.setdefault("sites", np.random.default_rng(seed).uniform(0, 2 * np.pi, (48, 3)))
        nearest, second = np.full_like(x, 1e6), np.full_like(x, 1e6)
        color = np.zeros_like(x)
        for index, (a, b, c) in enumerate(phases[: round(p["count"])]):
            sx = np.sin(a + motion * p["movement"] * 0.3) * size[0] / size[1]
            sy = np.sin(b + motion * p["movement"] * 0.4)
            distance = (x + np.sin(y * 4 + motion) * p["warp"] - sx) ** 2 + (y - sy) ** 2
            closer = distance < nearest
            second = np.where(closer, nearest, np.minimum(second, distance))
            color = np.where(closer, (index * 0.618034) % 1, color)
            nearest = np.minimum(nearest, distance)
        edge = np.clip((np.sqrt(second) - np.sqrt(nearest)) * 12, 0, 1)
        result = map_colors(color * 0.7 + np.sqrt(nearest) * 0.3, palette, phase)
        return result * (1 - p["borders"] + edge[..., None] * p["borders"])
    if kind == "fractal":
        zoom = np.exp(np.clip(t * abs(p["zoom_rate"]), 0, 7))
        zoom = zoom if p["zoom_rate"] >= 0 else 1 / max(0.1, zoom)
        plane = (x + 1j * y) * 1.5 / zoom + complex(p["center_x"], p["center_y"])
        if p["set"] == "mandelbrot":
            z, c = np.zeros_like(plane), plane
        else:
            z = plane.copy()
            c = complex(
                p["julia_real"] + np.sin(motion * 0.1) * 0.025,
                p["julia_imag"] + np.cos(motion * 0.09) * 0.015,
            )
        alive = np.ones(x.shape, dtype=bool)
        escaped = np.zeros_like(x)
        trap = np.ones_like(x) * 100
        for iteration in range(round(p["iterations"])):
            z[alive] = z[alive] ** 2 + (c[alive] if isinstance(c, np.ndarray) else c)
            absolute = np.abs(z)
            trap = np.minimum(trap, np.abs(absolute - 0.5))
            leaving = alive & (absolute > 4)
            escaped[leaving] = iteration + 1 - np.log2(np.maximum(0.01, np.log2(absolute[leaving])))
            alive[leaving] = False
            if not alive.any():
                break
        value = escaped / max(1, p["iterations"]) * 3 + np.exp(-trap * 6) * p["orbit_trap"]
        result = map_colors(value, palette, phase)
        result[alive] *= 0.15
        return result
    if kind == "wireframe":
        return wireframe(size, p, ctx, data, palette)
    raise ValueError(f"Unimplemented analytical scene: {kind}")


def geometry(kind, detail):
    if kind == "cube":
        points = np.array([[a, b, c] for a in (-1, 1) for b in (-1, 1) for c in (-1, 1)], dtype=np.float32)
        edges = [
            (a, b) for a in range(8) for b in range(a + 1, 8) if np.count_nonzero(points[a] != points[b]) == 1
        ]
    elif kind == "icosahedron":
        phi = (1 + np.sqrt(5)) / 2
        points = (
            np.array(
                [(0, a, b * phi) for a in (-1, 1) for b in (-1, 1)]
                + [(a, b * phi, 0) for a in (-1, 1) for b in (-1, 1)]
                + [(b * phi, 0, a) for a in (-1, 1) for b in (-1, 1)],
                dtype=np.float32,
            )
            / 1.5
        )
        edges = [
            (a, b) for a in range(12) for b in range(a + 1, 12) if np.linalg.norm(points[a] - points[b]) < 1.5
        ]
    elif kind == "lissajous":
        t = np.linspace(0, 2 * np.pi, detail * 12)
        points = np.column_stack([np.sin(t * 3), np.sin(t * 4 + 0.5), np.sin(t * 5)]).astype(np.float32)
        edges = [(a, a + 1) for a in range(len(points) - 1)]
    else:
        n, m = detail, max(6, detail // 2)
        u, v = np.meshgrid(
            np.linspace(0, 2 * np.pi, n, endpoint=False), np.linspace(0, 2 * np.pi, m, endpoint=False)
        )
        if kind == "torus":
            points = np.stack(
                [(1 + 0.35 * np.cos(v)) * np.cos(u), (1 + 0.35 * np.cos(v)) * np.sin(u), 0.35 * np.sin(v)], -1
            )
        elif kind == "sphere":
            points = np.stack([np.cos(u) * np.sin(v), np.sin(u) * np.sin(v), np.cos(v)], -1)
        else:
            xx, yy = (u / np.pi - 1), (v / np.pi - 1)
            zz = np.sin(xx * 4) * np.cos(yy * 3) * 0.4
            points = np.stack([xx, yy, zz], -1)
        points = points.reshape(-1, 3).astype(np.float32)
        edges = [(j * n + i, j * n + (i + 1) % n) for j in range(m) for i in range(n)]
        edges += [(j * n + i, ((j + 1) % m) * n + i) for j in range(m) for i in range(n)]
    return points, np.array(edges, dtype=np.int32)


def wireframe(size, p, ctx, data, palette):
    w, h = size
    key = (p["geometry"], round(p["detail"]))
    if data.get("geometry_key") != key:
        data["geometry_key"], data["geometry"] = key, geometry(*key)
    points, edges = data["geometry"]
    points = points.copy()
    t = ctx.local_time * p["speed"]
    points += (
        np.sin(points * 5 + t)
        * p["deformation"]
        * (1 + ctx.audio.get("bass_energy", 0) * p["audio_influence"])
    )
    a, b = t * p["rotation"], t * p["rotation"] * 0.71
    rx = np.float32([[1, 0, 0], [0, np.cos(a), -np.sin(a)], [0, np.sin(a), np.cos(a)]])
    ry = np.float32([[np.cos(b), 0, np.sin(b)], [0, 1, 0], [-np.sin(b), 0, np.cos(b)]])
    points = points @ rx.T @ ry.T
    depth = np.maximum(0.3, p["camera"] + points[:, 2])
    projected = np.column_stack(
        [w / 2 + points[:, 0] / depth * h * 0.9, h / 2 + points[:, 1] / depth * h * 0.9]
    ).astype(np.int32)
    colors = map_colors(np.clip((points[:, 2] + 2) / 4, 0, 1)[None, :], palette, p["palette_phase"])[0]
    canvas = np.zeros((h, w, 3), dtype=np.float32)
    for first, second in edges:
        color = tuple(float(c) for c in colors[first])
        cv2.line(
            canvas,
            tuple(projected[first]),
            tuple(projected[second]),
            color,
            round(p["thickness"]),
            cv2.LINE_AA,
        )
    return canvas
