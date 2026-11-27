import cv2
import numpy as np

from ..palettes import map_colors


def initialize(kind, size, p, data, random):
    w, h = size
    data["clock"] = 0.0
    data["last_event"] = -100.0
    data["canvas"] = np.zeros((h, w, 3), dtype=np.float32)
    data["density"] = np.zeros((h, w), dtype=np.float32)
    y, x = np.indices((h, w), dtype=np.float32)
    data["coordinates"] = (x, y)
    if kind == "reaction_diffusion":
        a, b = np.ones((h, w), dtype=np.float32), np.zeros((h, w), dtype=np.float32)
        if p["initialization"] == "stripe":
            b[h // 2 - 3 : h // 2 + 3] = 0.8
        elif p["initialization"] == "noise":
            b[:] = random.random((h, w)) * 0.25
        else:
            for cx, cy in random.uniform(0.1, 0.9, (18, 2)):
                cv2.circle(b, (round(cx * w), round(cy * h)), max(2, h // 25), 0.85, -1)
        a -= b * 0.5
        data["a"], data["b"] = a, b
        for _ in range(80):
            chemical_step(data, p, 0.7)
    elif kind in {"flow_field", "particle_field", "boids", "physarum", "starfield"}:
        population = round(p["population"])
        data["positions"] = random.random((population, 2)).astype(np.float32) * [w, h]
        data["velocity"] = random.normal(0, 1, (population, 2)).astype(np.float32)
        data["age"] = random.random(population).astype(np.float32) * p.get("lifetime", 10)
        data["heading"] = random.uniform(0, 2 * np.pi, population).astype(np.float32)
        if kind == "starfield":
            data["stars"] = random.uniform(-1, 1, (population, 3)).astype(np.float32)
            data["stars"][:, 2] = random.uniform(0.08, 1, population)
        if kind == "physarum" and p["initialization"] == "disk":
            angle = random.uniform(0, 2 * np.pi, population)
            radius = random.uniform(0.1, 0.4, population) * min(w, h)
            data["positions"][:] = np.column_stack(
                [w / 2 + np.cos(angle) * radius, h / 2 + np.sin(angle) * radius]
            )
    elif kind == "cellular_automata":
        if p["system"] == "cyclic":
            cells = random.integers(0, round(p["states"]), (max(2, h // 10), max(2, w // 10))).astype(
                np.float32
            )
            data["cells"] = cv2.resize(cells, (w, h), interpolation=cv2.INTER_NEAREST)
        else:
            data["cells"] = (random.random((h, w)) < p["density"]).astype(np.float32)
        data["cell_age"] = np.zeros((h, w), dtype=np.float32)
        data["ca_accumulator"] = 0.0
    elif kind in {"strange_attractor", "ifs"}:
        data["points"] = random.uniform(-0.5, 0.5, (min(256, round(p["points_per_step"])), 3)).astype(
            np.float64
        )
        if kind == "strange_attractor" and p["system"] in {"lorenz", "rossler"}:
            data["points"] += [1, 1, 1]
    elif kind == "recursive_geometry":
        data["canvas"] += random.random((h, w, 3)).astype(np.float32) * 0.015
        cv2.circle(data["canvas"], (w // 2, h // 2), h // 6, (0.05, 0.15, 0.12), 2)
    elif kind == "fluid_advection":
        data["velocity_field"] = np.zeros((h, w, 2), dtype=np.float32)
    else:
        raise ValueError(f"Unimplemented simulation: {kind}")


def chemical_step(data, p, dt):
    kernel = np.float32([[0.05, 0.2, 0.05], [0.2, -1, 0.2], [0.05, 0.2, 0.05]])
    a, b = data["a"], data["b"]
    reaction = a * b * b
    da = (
        p["diffusion_a"] * cv2.filter2D(a, -1, kernel, borderType=cv2.BORDER_REFLECT)
        - reaction
        + p["feed"] * (1 - a)
    )
    db = (
        p["diffusion_b"] * cv2.filter2D(b, -1, kernel, borderType=cv2.BORDER_REFLECT)
        + reaction
        - (p["kill"] + p["feed"]) * b
    )
    data["a"] = np.clip(a + da * dt, 0, 1)
    data["b"] = np.clip(b + db * dt, 0, 1)


def source_image(ctx, size):
    return cv2.resize(ctx.video, size).astype(np.float32) / 255 if ctx.video is not None else None


def deposit(canvas, positions, color, amount=1):
    h, w = canvas.shape[:2]
    ix, iy = positions[:, 0].astype(int), positions[:, 1].astype(int)
    valid = (ix >= 0) & (ix < w) & (iy >= 0) & (iy < h)
    if canvas.ndim == 2:
        np.add.at(canvas, (iy[valid], ix[valid]), amount)
    else:
        np.add.at(canvas, (iy[valid], ix[valid]), color[valid] * amount)


def step(kind, size, p, ctx, data, random, dt, palette):
    w, h = size
    data["clock"] += dt
    t = data["clock"]
    bass = ctx.audio.get("bass_energy", 0)
    drive = p["audio_influence"]
    event = ("disturbance" in ctx.actions or ctx.audio.get("bass_onset", 0) > 0.6) and ctx.time - data[
        "last_event"
    ] > 0.4
    if event:
        data["last_event"] = ctx.time
    image = source_image(ctx, size)
    if kind == "reaction_diffusion":
        if event:
            center = tuple(int(v) for v in random.uniform([0, 0], [w, h]))
            injection = np.zeros_like(data["b"])
            cv2.circle(
                injection, center, round(p["disturbance_radius"]), p["injection_strength"] * (0.5 + drive), -1
            )
            data["b"] = np.clip(data["b"] + injection, 0, 1)
        if image is not None and p["video_injection"]:
            signal = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
            data["b"] += signal * p["video_injection"] * dt
        data["b"][h // 2 - 1 : h // 2 + 1, w // 2 - 1 : w // 2 + 1] += p["injection_strength"] * dt * 0.1
        for _ in range(round(p["iterations"])):
            chemical_step(data, p, min(1, abs(p["speed"]) * 2 * dt * 30))
    elif kind in {"flow_field", "particle_field", "boids"}:
        positions, velocity = data["positions"], data["velocity"]
        xn, yn = positions[:, 0] / w * 2 * np.pi, positions[:, 1] / h * 2 * np.pi
        speed = abs(p["speed"]) * min(w, h) * 0.25 * (1 + bass * drive)
        if kind == "boids":
            velocity = flock(positions, velocity, size, p, dt)
            attraction = np.column_stack([w / 2 - positions[:, 0], h / 2 - positions[:, 1]])
            velocity += attraction / max(w, h) * p["attraction"] * dt
        else:
            f = p["frequency"]
            # Curl of a smooth time-varying potential, rather than independent random headings.
            field = np.column_stack(
                [
                    -np.sin(xn * f + t * 0.17) * np.sin(yn * f - t * 0.13),
                    -np.cos(xn * f + t * 0.17) * np.cos(yn * f - t * 0.13),
                ]
            )
            center = positions - np.float32([w / 2, h / 2])
            r = np.linalg.norm(center, axis=1, keepdims=True) + 8
            vortex = np.column_stack([-center[:, 1], center[:, 0]]) / r
            if p["field"] in {"attractor", "repeller"}:
                field = center / r * (-1 if p["field"] == "attractor" else 1)
            elif p["field"] == "vortex":
                field = vortex
            elif p["field"] == "oscillator":
                field = np.column_stack([np.sin(yn * f + t), np.cos(xn * f - t)])
            field += vortex * p["vortex"] * (0.3 + bass * drive)
            if image is not None and p["video_influence"]:
                gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
                gy, gx = np.gradient(gray)
                xx, yy = positions[:, 0].astype(int) % w, positions[:, 1].astype(int) % h
                field += np.column_stack([-gy[yy, xx], gx[yy, xx]]) * p["video_influence"] * 8
            velocity = velocity * np.exp(-dt * 3) + field * (1 - np.exp(-dt * 3))
        norm = np.linalg.norm(velocity, axis=1, keepdims=True) + 1e-6
        velocity = velocity / norm
        positions[:] = (positions + velocity * speed * dt) % [w, h]
        data["velocity"] = velocity
        data["age"] += dt
        lifetime = p.get("lifetime", 30)
        expired = data["age"] > lifetime
        if event and kind != "boids":
            expired |= random.random(len(positions)) < p["injection_strength"] * drive * 0.1
        count = int(expired.sum())
        if count:
            positions[expired] = random.uniform([0, 0], [w, h], (count, 2))
            if image is not None and p.get("video_influence", 0):
                gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
                weights = gray.ravel().astype(float) + 0.001
                selected = random.choice(w * h, count, p=weights / weights.sum())
                positions[expired] = np.column_stack([selected % w, selected // w])
            data["age"][expired] = 0
        canvas = data["canvas"]
        canvas *= np.exp(-p["trail_decay"] * dt)
        color = map_colors(
            ((data["age"] / lifetime + np.arange(len(positions)) % 3 * 0.2) % 1)[None, :],
            palette,
            p["palette_phase"],
        )[0]
        if image is not None and kind == "particle_field":
            color = image[positions[:, 1].astype(int) % h, positions[:, 0].astype(int) % w]
        deposit(canvas, positions, color, 0.09 * dt * 30)
        data["canvas"] = np.clip(cv2.GaussianBlur(canvas, (0, 0), 0.35), 0, 3)
    elif kind == "physarum":
        positions, headings, trail = data["positions"], data["heading"], data["density"]

        def sense(angle):
            sample = positions + np.column_stack([np.cos(angle), np.sin(angle)]) * p["sensor_distance"]
            return trail[sample[:, 1].astype(int) % h, sample[:, 0].astype(int) % w]

        front, left, right = (
            sense(headings),
            sense(headings - p["sensor_angle"]),
            sense(headings + p["sensor_angle"]),
        )
        turn = np.where(left > right, -1, 1).astype(np.float32)
        turn = np.where((front > left) & (front > right), 0, turn)
        ambiguous = ((front < left) & (front < right)) | ((front == left) & (front == right))
        turn[ambiguous] = random.choice([-1, 1], int(ambiguous.sum()))
        headings += turn * p["turn_rate"] * dt
        if event:
            headings += random.uniform(-1, 1, len(headings)) * p["disturbance"] * drive
        movement = p["movement"] * (0.6 + abs(p["speed"])) * (1 + bass * drive * 0.5)
        positions[:] = (positions + np.column_stack([np.cos(headings), np.sin(headings)]) * movement * dt) % [
            w,
            h,
        ]
        deposit(trail, positions, None, p["deposit"] * dt * 30)
        data["density"] = np.clip(
            cv2.GaussianBlur(trail, (0, 0), p["diffusion"] * np.sqrt(dt * 30))
            * np.exp(-p["trail_decay"] * dt),
            0,
            8,
        )
    elif kind == "cellular_automata":
        data["ca_accumulator"] += dt * p["update_rate"] * abs(p["speed"]) / 0.35
        while data["ca_accumulator"] >= 1:
            data["ca_accumulator"] -= 1
            cells = data["cells"]
            if p["system"] == "life":
                neighbors = sum(
                    np.roll(cells, (dy, dx), (0, 1))
                    for dy, dx in [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
                )
                cells = ((neighbors == 3) | ((cells > 0.5) & (neighbors == 2))).astype(np.float32)
            elif p["system"] == "elementary":
                row = cells[0].astype(np.uint8)
                code = np.roll(row, 1) * 4 + row * 2 + np.roll(row, -1)
                cells = np.roll(cells, 1, axis=0)
                cells[0] = (round(p["rule"]) >> code) & 1
            elif p["system"] == "cyclic":
                target = (cells + 1) % round(p["states"])
                neighbors = sum(
                    np.roll(cells, (dy, dx), (0, 1)) == target
                    for dy, dx in [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
                )
                cells = np.where(neighbors >= 2, target, cells)
            else:
                inner = cv2.GaussianBlur(cells, (0, 0), 1)
                outer = cv2.GaussianBlur(cells, (0, 0), 3)
                growth = np.exp(-(((outer - 0.3) / 0.13) ** 2))
                cells = np.clip(cells + 0.25 * (growth - 0.7 * inner), 0, 1)
            if image is not None and p["video_injection"]:
                mask = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY) > 0.65
                cells = np.where(mask & (random.random((h, w)) < p["video_injection"]), 1, cells)
            if event:
                mask = random.random((h, w)) < p["disturbance"] * drive
                cells[mask] = 1
            data["cell_age"] = np.where(
                cells > 0, np.minimum(100, data["cell_age"] + 1), data["cell_age"] * 0.9
            )
            data["cells"] = cells
    elif kind in {"strange_attractor", "ifs"}:
        attractor_step(kind, size, p, ctx, data, random, dt)
    elif kind == "starfield":
        stars = data["stars"]
        stars[:, 2] -= (
            dt
            * abs(p["speed"])
            * (0.25 + p["radial_acceleration"] / np.maximum(0.05, stars[:, 2]))
            * (1 + bass * drive)
        )
        expired = stars[:, 2] <= 0.03
        stars[expired, :2] = random.uniform(-1, 1, (int(expired.sum()), 2))
        stars[expired, 2] = 1
        a = t * p["rotation"]
        xx = (stars[:, 0] * np.cos(a) - stars[:, 1] * np.sin(a)) / stars[:, 2]
        yy = (stars[:, 0] * np.sin(a) + stars[:, 1] * np.cos(a)) / stars[:, 2]
        positions = np.column_stack(
            [w / 2 + xx * h * 0.3 + np.sin(t * 0.2) * w * p["drift"], h / 2 + yy * h * 0.3]
        )
        color = map_colors(
            (stars[:, 2] * 0.6 + np.arange(len(stars)) % 3 * 0.1)[None, :], palette, p["palette_phase"]
        )[0]
        color *= (0.2 + 0.8 * (1 - stars[:, 2]))[:, None]
        data["canvas"] *= np.exp(-p["trail_decay"] * dt)
        deposit(data["canvas"], positions, color, 0.5 * dt * 30)
        data["canvas"] = np.clip(data["canvas"], 0, 3)
    elif kind == "recursive_geometry":
        canvas = data["canvas"]
        rate = dt * 30 * abs(p["speed"]) / 0.35
        matrix = cv2.getRotationMatrix2D((w / 2, h / 2), p["rotation"] * rate, p["zoom"] ** rate)
        out = cv2.warpAffine(canvas, matrix, (w, h), borderMode=cv2.BORDER_REFLECT)
        x, y = data["coordinates"]
        brightness = out.mean(axis=2)
        out = cv2.remap(
            out,
            (x + np.sin(brightness * 6 + t) * p["warp"] * dt * 30).astype(np.float32),
            (y + np.cos(brightness * 6 - t) * p["warp"] * dt * 30).astype(np.float32),
            cv2.INTER_LINEAR,
        )
        if p["symmetry"] != "none":
            out[:, w // 2 :] = out[:, : w - w // 2][:, ::-1]
        if p["symmetry"] == "kaleidoscope":
            out[h // 2 :] = out[: h - h // 2][::-1]
        out *= p["decay"] ** (dt * 30)
        color = map_colors(np.float32([[(0.35 + t * 0.05) % 1]]), palette, p["palette_phase"])[0, 0]
        center = (round(w * (0.5 + 0.25 * np.sin(t * 0.3))), round(h * (0.5 + 0.2 * np.cos(t * 0.4))))
        seed = np.zeros_like(out)
        cv2.circle(seed, center, max(2, h // 9), tuple(float(c) for c in color), 1)
        seed += seed[:, ::-1] * 0.8
        cv2.line(seed, (w // 4, h // 3), (w * 3 // 4, h * 2 // 3), tuple(float(c * 0.3) for c in color), 1)
        out += seed * p["injection_strength"] * dt * 30 * (1 + event * drive * 2)
        if image is not None:
            out += image * p["video_injection"] * dt * 30
        data["canvas"] = np.clip(cv2.GaussianBlur(out, (0, 0), 0.25), 0, 1)
    elif kind == "fluid_advection":
        x, y = data["coordinates"]
        velocity = data["velocity_field"]
        mx = (x - velocity[..., 0] * dt * abs(p["speed"]) / 0.35).astype(np.float32)
        my = (y - velocity[..., 1] * dt * abs(p["speed"]) / 0.35).astype(np.float32)
        velocity = cv2.remap(velocity, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP)
        force = np.zeros_like(velocity)
        for number in range(3):
            cx = w * (0.5 + 0.3 * np.sin(t * 0.19 + number * 2))
            cy = h * (0.5 + 0.3 * np.cos(t * 0.17 + number * 2))
            dx, dy = (x - cx) / w, (y - cy) / h
            falloff = np.exp(-(dx * dx + dy * dy) * 12) * (1 if number % 2 else -1)
            force[..., 0] += -dy * falloff * min(w, h)
            force[..., 1] += dx * falloff * min(w, h)
        velocity = np.clip(
            velocity * np.exp(-dt * 0.2) + force * p["vorticity"] * (1 + bass * drive) * dt, -80, 80
        )
        data["velocity_field"] = velocity.astype(np.float32)
        out = cv2.remap(data["canvas"], mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP)
        out = cv2.GaussianBlur(out, (0, 0), max(0.05, p["diffusion"] * np.sqrt(dt * 30))) * np.exp(
            -p["dissipation"] * dt
        )
        color = map_colors(np.float32([[(0.35 + t * 0.06) % 1]]), palette, p["palette_phase"])[0, 0]
        seed = np.zeros_like(out)
        cv2.circle(
            seed,
            (round(w * (0.5 + 0.3 * np.sin(t))), round(h * (0.5 + 0.25 * np.cos(t * 0.8)))),
            max(2, h // 14),
            tuple(float(c) for c in color),
            -1,
        )
        out += seed * p["injection_strength"] * dt * 4 * (1 + event * drive * 4)
        if image is not None:
            out += image * p["video_injection"] * dt
        data["canvas"] = np.clip(out, 0, 2)


def flock(positions, velocity, size, p, dt):
    w, h = size
    cell = p["neighborhood"]
    nx, ny = max(2, int(w / cell)), max(2, int(h / cell))
    ix, iy = (positions[:, 0] / w * nx).astype(int) % nx, (positions[:, 1] / h * ny).astype(int) % ny
    ids = iy * nx + ix
    count = np.bincount(ids, minlength=nx * ny).reshape(ny, nx).astype(np.float32)
    sums = [
        np.bincount(ids, weights=value, minlength=nx * ny).reshape(ny, nx)
        for value in (positions[:, 0], positions[:, 1], velocity[:, 0], velocity[:, 1])
    ]
    total = np.zeros(len(positions))
    gathered = np.zeros((len(positions), 4))
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            xx, yy = (ix + dx) % nx, (iy + dy) % ny
            total += count[yy, xx]
            for channel in range(4):
                gathered[:, channel] += sums[channel][yy, xx]
    averages = gathered / np.maximum(1, total[:, None])
    displacement = averages[:, :2] - positions
    separation = -displacement / (np.sum(displacement**2, axis=1, keepdims=True) + 1)
    alignment = averages[:, 2:] - velocity
    cohesion = displacement / max(1, cell)
    return (
        velocity
        + (separation * p["separation"] * 8 + alignment * p["alignment"] + cohesion * p["cohesion"] * 0.2)
        * dt
        * 3
    )


def attractor_step(kind, size, p, ctx, data, random, dt):
    w, h = size
    points = data["points"]
    budget = data.get("point_budget", 0) + p["points_per_step"] * dt * 30 * abs(p["speed"]) / 0.35
    iterations = min(64, int(budget / len(points)))
    data["point_budget"] = budget - iterations * len(points)
    density = data["density"]
    density *= np.exp(-dt / p["persistence"])
    for _ in range(iterations):
        x, y, z = points.T.copy()
        if kind == "ifs":
            if p["system"] == "fern":
                transforms = np.array(
                    [
                        [[0, 0], [0, 0.16]],
                        [[0.85, 0.04], [-0.04, 0.85]],
                        [[0.2, -0.26], [0.23, 0.22]],
                        [[-0.15, 0.28], [0.26, 0.24]],
                    ]
                )
                shifts = np.array([[0, 0], [0, 1.6], [0, 1.6], [0, 0.44]])
                selected = random.choice(4, len(points), p=[0.01, 0.85, 0.07, 0.07])
                points[:, :2] = (
                    np.einsum("nij,nj->ni", transforms[selected], points[:, :2]) + shifts[selected]
                )
                px, py = points[:, 0] / 5.6 + 0.5, 1 - points[:, 1] / 11
            else:
                corners = np.array([[-1, -1], [1, -1], [0, 1]])
                points[:, :2] = points[:, :2] * 0.5 + corners[random.integers(0, 3, len(points))] * 0.5
                px, py = points[:, 0] / 2.3 + 0.5, points[:, 1] / 2.3 + 0.5
            px += np.sin(py * 6 + ctx.time * 0.1) * p["deformation"]
        elif p["system"] in {"clifford", "de_jong"}:
            drift = (
                p["drift"] * np.sin(ctx.time * 0.13)
                + ctx.audio.get("onset", 0) * p["disturbance"] * p["audio_influence"] * 0.05
            )
            if p["system"] == "clifford":
                points[:, 0] = np.sin((-1.4 + drift) * y) + np.cos((-1.4 + drift) * x)
                points[:, 1] = np.sin((1.6 + drift) * x) + 0.7 * np.cos((1.6 + drift) * y)
            else:
                points[:, 0] = np.sin((1.4 + drift) * y) - np.cos(-2.3 * x)
                points[:, 1] = np.sin(2.4 * x) - np.cos((-2.1 + drift) * y)
            px, py = points[:, 0] / 5 + 0.5, points[:, 1] / 4.5 + 0.5
        else:
            delta = min(0.02, dt * max(0.1, abs(p["speed"])) * 1.5)
            if p["system"] == "lorenz":
                points[:, 0] += 10 * (y - x) * delta
                points[:, 1] += (x * (28 - z) - y) * delta
                points[:, 2] += (x * y - 8 / 3 * z) * delta
                px, py = points[:, 0] / 50 + 0.5, 1 - points[:, 2] / 60
            else:
                points[:, 0] += (-y - z) * delta
                points[:, 1] += (x + 0.2 * y) * delta
                points[:, 2] += (0.2 + z * (x - 5.7)) * delta
                px, py = points[:, 0] / 30 + 0.5, points[:, 1] / 30 + 0.5
            points[:] = np.clip(points, -100, 100)
        for index in range(round(p.get("symmetry", 1))):
            a = index * 2 * np.pi / p.get("symmetry", 1)
            xx = ((px - 0.5) * np.cos(a) - (py - 0.5) * np.sin(a) + 0.5) * w
            yy = ((px - 0.5) * np.sin(a) + (py - 0.5) * np.cos(a) + 0.5) * h
            deposit(density, np.column_stack([xx, yy]), None, 0.12)
    data["density"] = np.clip(density, 0, 100)


def render(kind, size, p, ctx, data, palette):
    phase = p["palette_phase"] + ctx.local_time * 0.008
    if kind == "reaction_diffusion":
        value = np.clip(data["b"] * 2.5, 0, 1)
        contour = 0.5 + 0.5 * np.sin(value * np.pi * 10)
        return map_colors(value * (1 - p["contours"]) + contour * p["contours"], palette, phase)
    if kind in {
        "flow_field",
        "particle_field",
        "boids",
        "starfield",
        "recursive_geometry",
        "fluid_advection",
    }:
        canvas = data["canvas"]
        gain = 2 if kind in {"boids", "recursive_geometry", "fluid_advection"} else 1.2
        return np.clip((canvas + cv2.GaussianBlur(canvas, (0, 0), 1) * 0.25) * gain, 0, 1)
    if kind == "cellular_automata":
        value = (
            data["cells"] / max(1, p["states"] - 1)
            if p["system"] == "cyclic"
            else data["cells"] * 0.6 + np.clip(data["cell_age"] / 25, 0, 0.4)
        )
        return map_colors(value * 0.9, palette, phase)
    value = np.log1p(data["density"])
    scale = 2.2 if kind == "physarum" else 1.6
    value = np.clip(value / scale, 0, 1)
    return map_colors(value * 0.9, palette, phase) * np.clip(value * 2.5, 0, 1)[..., None]
