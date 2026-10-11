"""Numpy reference of the Recovery v2 lobe recovery (FSRDRecoveryLobeAccumulate/Down/Band.hlsl).

Mirrors the shaders' arithmetic, including the FP16 storage of every texture they write. The accumulate pass
rounds its reference values and gradients stochastically; the reference returns them unrounded in FP32, so callers
compare those with a one-unit FP16 tolerance and feed the GPU's stored history back into both."""
import numpy as np

LEVELS = 6
HISTORY_VALID, EXTRA_DIFFUSE, NO_SPECULAR, COARSEST, FINAL = 1, 2, 4, 8, 16
LUMA = np.array([0.2126, 0.7152, 0.0722], np.float32)


def f16(x):
    return np.asarray(x, np.float32).astype(np.float16).astype(np.float32)


def smoothstep(a, b, x):
    t = np.clip((np.asarray(x, np.float32) - a) / (b - a), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def octahedral_decode(uv):
    e = 2.0 * (uv - 0.5)
    n = np.stack([e[..., 0], e[..., 1], 1.0 - np.abs(e[..., 0]) - np.abs(e[..., 1])], -1)
    t = np.maximum(-n[..., 2], 0.0)
    n[..., 0] += np.where(n[..., 0] >= 0.0, -t, t)
    n[..., 1] += np.where(n[..., 1] >= 0.0, -t, t)
    return n / np.maximum(np.linalg.norm(n, axis=-1, keepdims=True), 1e-20)


def weight_squares(age, response):
    """sum of squared weights: a running mean until its weight reaches response, then an exponential average."""
    start = 1.0 / max(response, 1e-6)
    age = np.maximum(age, 1.0)
    limit = response / (2.0 - response)
    decay = (1.0 - response) ** 2
    late = limit + (1.0 / start - limit) * np.power(decay, np.maximum(age - start, 0.0))
    return np.where(age <= start, 1.0 / age, late)


def level_sizes(width, height):
    sizes = [(width, height)]
    for _ in range(LEVELS):
        sizes.append(((sizes[-1][0] + 1) // 2, (sizes[-1][1] + 1) // 2))
    return sizes


def load_bilinear(texture, x, y):
    """texture (h, w, c); x, y level coordinates (pixel centres at integers), clamped like LoadBilinear."""
    h, w = texture.shape[:2]
    x = np.clip(x, 0.0, w - 1.0); y = np.clip(y, 0.0, h - 1.0)
    x0 = np.floor(x).astype(np.int64); y0 = np.floor(y).astype(np.int64)
    x1 = np.minimum(x0 + 1, w - 1); y1 = np.minimum(y0 + 1, h - 1)
    fx = (x - x0)[..., None]; fy = (y - y0)[..., None]
    top = texture[y0, x0] * (1 - fx) + texture[y0, x1] * fx
    bottom = texture[y1, x0] * (1 - fx) + texture[y1, x1] * fx
    return top * (1 - fy) + bottom * fy


def gradient_colour(v):
    c = np.maximum(v, 0.0)
    return c / np.maximum(c @ LUMA, 1e-4)[..., None]


def shifted(img, dy, dx):
    """img[clamp(y + dy), clamp(x + dx)]"""
    H, W = img.shape[:2]
    ys = np.clip(np.arange(H) + dy, 0, H - 1); xs = np.clip(np.arange(W) + dx, 0, W - 1)
    return img[ys][:, xs]


def spatial_flat_reference(raw, rr, depth, flat, current):
    y = rr @ LUMA
    mean = sum(shifted(y,dy,dx) for dy in (-1,0,1) for dx in (-1,0,1)) / 9.0
    square = sum(shifted(y*y,dy,dx) for dy in (-1,0,1) for dx in (-1,0,1)) / 9.0
    variance = np.maximum(square-mean*mean,0.0) + 1e-4*mean*mean + 1e-8
    total = np.zeros_like(raw); weights = np.zeros_like(y)
    for dy in (-1,0,1):
        for dx in (-1,0,1):
            delta = shifted(y,dy,dx)-y
            compatible = ((np.abs(shifted(depth,dy,dx)-depth) <= .03*np.maximum(np.abs(depth),1e-3)) &
                          (shifted(flat,dy,dx)==flat) & ~shifted(current,dy,dx))
            w = ((2 if dy==0 else 1)*(2 if dx==0 else 1))/(1.0+delta*delta/variance)*compatible
            total += w[...,None]*shifted(raw,dy,dx); weights += w
    return total / np.maximum(weights[...,None],1e-6)


def accumulate(c, U, V, RRs, RRd, RRd2, Qs, Qd, depth, normals_unorm, motion, skip, prevS, prevD, prevGeo, prevGrad):
    """returns (specular value, diffuse value, geometry, level A, level B, level C, gradient); values and gradient in
    FP32 (the shader rounds them stochastically), the rest as stored."""
    H, W = depth.shape
    flags = c["Flags"]
    octa = normals_unorm[..., :2]
    normal = octahedral_decode(octa)
    current = skip[..., 3] == -1.0
    geometry = np.isfinite(depth) & (np.abs(depth) > 1e-5)
    y, x = np.mgrid[:H, :W].astype(np.float32)
    expected = depth + motion[..., 2]
    try_history = bool(flags & HISTORY_VALID) & (motion[..., 3] >= 0.5) & geometry & ~current

    slope = np.zeros((H, W), np.float32); closest = np.ones((H, W), np.float32)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            closest = np.minimum(closest, (shifted(normal, dy, dx) * normal).sum(-1))
            if dx == 0 or dy == 0:
                z = shifted(depth, dy, dx)
                slope = np.maximum(slope, np.where(np.isfinite(z), np.abs(z - depth), 0.0))
    ztol = 0.03 * np.maximum(np.abs(expected), 1e-3) + slope
    nthr = np.minimum(0.95, closest) - 0.05

    px = x + motion[..., 0] * W; py = y + motion[..., 1] * H
    bx = np.floor(px).astype(np.int64); by = np.floor(py).astype(np.int64)
    fx = px - bx; fy = py - by
    hs = np.zeros((H, W, 3), np.float32); hd = np.zeros_like(hs); hg = np.zeros((H, W, 4), np.float32)
    hage = np.zeros((H, W), np.float32); weight = np.zeros((H, W), np.float32)
    for t in range(4):
        ox, oy = t & 1, t >> 1
        qx = bx + ox; qy = by + oy
        inb = (qx >= 0) & (qy >= 0) & (qx < W) & (qy < H)
        qxc = np.clip(qx, 0, W - 1); qyc = np.clip(qy, 0, H - 1)
        pg = prevGeo[qyc, qxc]
        ok = try_history & inb & (np.abs(pg[..., 0] - expected) <= ztol)
        ok &= (octahedral_decode(pg[..., 1:3]) * normal).sum(-1) > nthr
        w = np.where(ok, (fx if ox else 1 - fx) * (fy if oy else 1 - fy), 0.0).astype(np.float32)
        sx = px - qx; sy = py - qy
        s = prevS[qyc, qxc, :3]; d = prevD[qyc, qxc, :3]; g = prevGrad[qyc, qxc]
        hs += w[..., None] * (s + (g[..., 0] * sx + g[..., 1] * sy)[..., None] * gradient_colour(s))
        hd += w[..., None] * (d + (g[..., 2] * sx + g[..., 3] * sy)[..., None] * gradient_colour(d))
        hg += w[..., None] * g
        hage += w * pg[..., 3]; weight += w
    valid = weight >= 0.5
    safe = np.where(weight > 0.0, weight, 1.0)
    hs /= safe[..., None]; hd /= safe[..., None]; hg /= safe[..., None]; hage /= safe

    jx, jy = -c["Jitter"][0], -c["Jitter"][1]
    xs = U[..., :3]; xd = V[..., :3] * (2.0 if flags & EXTRA_DIFFUSE else 1.0)
    a = np.maximum(1.0 / (hage + 1.0), c["Response"])
    b = np.where(hage >= c["GradientAge"], a, 0.0)

    def update(sample, value, gx, gy):
        predicted = value + (gx * jx + gy * jy)[..., None] * gradient_colour(value)
        e = sample - predicted
        inn = e @ LUMA
        value = value + a[..., None] * e
        gx = gx + 12.0 * b * inn * jx; gy = gy + 12.0 * b * inn * jy
        return value, gx, gy, inn, value + (gx * jx + gy * jy)[..., None] * gradient_colour(value)

    vs, gsx, gsy, inns, refs = update(xs, hs, hg[..., 0], hg[..., 1])
    vd, gdx, gdy, innd, refd = update(xd, hd, hg[..., 2], hg[..., 3])
    v3 = valid[..., None]
    vs = np.where(v3, vs, xs); vd = np.where(v3, vd, xd)
    refs = np.where(v3, refs, xs); refd = np.where(v3, refd, xd)
    grad = np.where(v3, np.stack([gsx, gsy, gdx, gdy], -1), 0.0)
    inns = np.where(valid, inns, 0.0); innd = np.where(valid, innd, 0.0)
    age = np.where(valid, np.minimum(hage + 1.0, 1024.0), 1.0)

    c3 = current[..., None]
    rs = np.where(c3, 0.0, np.maximum(refs, 0.0)); rd = np.where(c3, 0.0, np.maximum(refd, 0.0))
    sage = np.where(current, 0.0, age)
    spatial_flat = (np.abs(normals_unorm[...,3]-1.0/3.0)<0.1) & (c['Strength'][3]>0) & geometry
    if c['Strength'][3]>0:
        sf=spatial_flat_reference(xs,RRs[...,:3],depth,spatial_flat,current)
        df=spatial_flat_reference(xd,RRd[...,:3]+(RRd2[...,:3] if flags & EXTRA_DIFFUSE else 0.0),depth,spatial_flat,current)
        active=spatial_flat & ~current
        rs=np.where(active[...,None],sf,rs); rd=np.where(active[...,None],df,rd)
        inns=np.where(active,(xs-sf)@LUMA,inns); innd=np.where(active,(xd-df)@LUMA,innd)
    # within the range of the eight neighbours that have a reference (edge pixels repeat, as the shader's clamp)
    lo_s = np.full((H, W, 3), 65504.0, np.float32); hi_s = -lo_s.copy(); lo_d = lo_s.copy(); hi_d = -lo_s.copy()
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            use = (shifted(sage, dy, dx) != 0.0)[..., None]
            ns = shifted(rs, dy, dx); nd = shifted(rd, dy, dx)
            lo_s = np.where(use, np.minimum(lo_s, ns), lo_s); hi_s = np.where(use, np.maximum(hi_s, ns), hi_s)
            lo_d = np.where(use, np.minimum(lo_d, nd), lo_d); hi_d = np.where(use, np.maximum(hi_d, nd), hi_d)
    some = np.all(lo_s <= hi_s, -1)[..., None]
    rs = np.where(some, np.clip(rs, lo_s, hi_s), rs); rd = np.where(some, np.clip(rd, lo_d, hi_d), rd)

    ys = RRs[..., :3]; yd = RRd[..., :3] + (RRd2[..., :3] if flags & EXTRA_DIFFUSE else 0.0)
    geo = np.concatenate([np.where(geometry & ~current, depth, 0.0)[..., None], octa, age[..., None]], -1)
    maturity = np.where(current, 0.0, smoothstep(0.5 * c["MatureAge"], c["MatureAge"], sage))
    flat = (np.abs(normals_unorm[..., 3] - 1.0 / 3.0) < 0.1).astype(np.float32)
    A = np.concatenate([np.where(c3, 0.0, rs - ys), np.clip(inns, -65504, 65504)[..., None]], -1)
    B = np.concatenate([np.where(c3, 0.0, rd - yd), np.clip(innd, -65504, 65504)[..., None]], -1)
    C = np.stack([flat, flat, maturity, weight_squares(np.maximum(sage, 1.0), c["Response"])], -1)
    C[...,2]=np.where(spatial_flat & ~current,1.0,C[...,2])
    C[...,3]=np.where(spatial_flat,.15,C[...,3])
    return vs, vd, f16(geo), f16(A), f16(B), f16(C), grad


def down(level, out_size):
    w, h = out_size
    H, W = level.shape[:2]
    y, x = np.mgrid[:h, :w]
    acc = 0
    for oy in (0, 1):
        for ox in (0, 1):
            acc = acc + level[np.minimum(2 * y + oy, H - 1), np.minimum(2 * x + ox, W - 1)]
    return f16(0.25 * acc)


def anchor_lobe(correction, rr, anchor, noise_variance):
    """per pixel: anchor (h, w), noise_variance (h, w); rr the lobe's RR output (h, w, 3)."""
    mean = 0; square = 0
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            v = shifted(rr, dy, dx); mean = mean + v; square = square + v * v
    mean = mean / 9.0
    variance = np.maximum(square / 9.0 - mean * mean, 0.0)
    chroma = np.maximum(rr, 1e-6) / np.maximum(np.maximum(rr, 0.0) @ LUMA, 1e-6)[..., None]
    deviation = anchor[..., None] * np.sqrt(variance + 1e-4 * mean * mean)
    limited = np.clip(rr + correction, np.minimum(mean - deviation, rr), np.maximum(mean + deviation, rr)) - rr
    return np.where((anchor > 0.0)[..., None], limited, correction)


def band(c, level, A, B, C, coarseA, coarseB, coarseS, coarseD, prevNoise, motion, composed=None, Qs=None, Qd=None,
         skip=None, RRs=None, RRd=None, RRd2=None):
    """one band pass at `level`; returns (specular, diffuse, noise, colour or None) as the shader stores them."""
    h, w = A.shape[:2]
    flags = c["Flags"]; scale = float(1 << level)
    y, x = np.mgrid[:h, :w].astype(np.float32)
    cx = (x + 0.5) * 0.5 - 0.5; cy = (y + 0.5) * 0.5 - 0.5
    # the shader keeps the bands and the weighted bands as FP16 in group memory
    bandA = f16(np.clip(A - load_bilinear(coarseA, cx, cy), -65504, 65504))
    bandB = f16(np.clip(B - load_bilinear(coarseB, cx, cy), -65504, 65504))

    def box3(v):
        p = np.pad(v, 1, mode="edge"); s = 0
        for dy in range(3):
            for dx in range(3):
                s = s + p[dy:dy + h, dx:dx + w]
        return s / 9.0
    energy = np.stack([box3((bandA[..., :3] @ LUMA) ** 2), box3((bandB[..., :3] @ LUMA) ** 2)], -1)
    variance = np.stack([bandA[..., 3] ** 2, bandB[..., 3] ** 2], -1)
    Hf, Wf = motion.shape[:2]
    centre_x = (x + 0.5) * scale; centre_y = (y + 0.5) * scale
    mv = motion[np.minimum(centre_y.astype(np.int64), Hf - 1), np.minimum(centre_x.astype(np.int64), Wf - 1)]
    reuse = bool(flags & HISTORY_VALID) & (C[..., 2] > 0.0) & (mv[..., 3] >= 0.5)
    hx = (centre_x + mv[..., 0] * Wf) / scale - 0.5
    hy = (centre_y + mv[..., 1] * Hf) / scale - 0.5
    hist = load_bilinear(prevNoise, hx, hy)
    squared = np.concatenate([prevNoise[..., :2] ** 2, prevNoise[..., 2:]], -1)
    pv = load_bilinear(squared, hx, hy)[..., :2]  # variances are interpolated, not standard deviations
    rate = np.maximum(1.0 / (hist[..., 2] + 1.0), 1.0 / 16.0)[..., None]
    variance = np.where(reuse[..., None], pv + rate * (variance - pv), variance)
    age = np.where(reuse, np.minimum(hist[..., 2] + 1.0, 1024.0), 1.0)
    q = C[..., 3][..., None]
    noise_variance = np.maximum(variance * q / (1.0 + q), 1e-20)
    motion_gate=smoothstep(4.,20.,np.linalg.norm(mv[...,:2]*[Wf,Hf],axis=-1))
    margin=np.maximum(motion_gate,C[...,0]) if level>=2 else np.zeros_like(motion_gate)
    k=c['Threshold']*(1.+.5*level*level*margin)
    wiener = np.clip((energy - k[...,None] * noise_variance) / np.maximum(energy, 1e-30), 0.0, 1.0)
    maturity = C[..., 2:3] * smoothstep(2.0, 4.0, age)[..., None]
    st = np.asarray(c["Strength"], np.float32); blend = np.asarray(c["Blend"], np.float32)
    ordinary = st[:2] * (wiener + blend[0] * (1.0 - wiener))
    flat_albedo = st[3] * (wiener + blend[2] * (1.0 - wiener))
    flat = np.clip(C[..., :2], 0.0, 1.0)
    weight = (ordinary + (flat_albedo - ordinary) * flat) * maturity
    weight=np.where((flat>=0.99) & (C[...,2:3]>=0.99),flat_albedo,weight)
    if flags & NO_SPECULAR:
        weight[..., 0] = 0.0
    corrS = f16(np.clip(bandA[..., :3] * weight[..., 0:1], -65504, 65504))
    corrD = f16(np.clip(bandB[..., :3] * weight[..., 1:2], -65504, 65504))
    cw, ch = (w + 1) // 2, (h + 1) // 2

    def mean2(v):
        yy, xx = np.mgrid[:ch, :cw]
        acc = 0
        for oy in (0, 1):
            for ox in (0, 1):
                acc = acc + v[np.minimum(2 * yy + oy, h - 1), np.minimum(2 * xx + ox, w - 1)]
        return 0.25 * acc
    specular = corrS - load_bilinear(mean2(corrS), cx, cy)
    diffuse = corrD - load_bilinear(mean2(corrD), cx, cy)
    if not flags & COARSEST:
        specular = specular + load_bilinear(coarseS, cx, cy)[..., :3]
        diffuse = diffuse + load_bilinear(coarseD, cx, cy)[..., :3]
    noise = f16(np.concatenate([np.minimum(np.sqrt(variance), 65504.0), age[..., None], np.zeros((h, w, 1), np.float32)], -1))
    if not flags & FINAL:
        return f16(np.clip(specular, -65504, 65504)), f16(np.clip(diffuse, -65504, 65504)), noise, None
    flat0 = np.clip(C[..., :2], 0.0, 1.0)
    noise_variance = f16(np.minimum(np.sqrt(noise_variance), 65504.0)) ** 2  # stored as an FP16 standard deviation
    rrd = f16(RRd[..., :3] + (RRd2[..., :3] if flags & EXTRA_DIFFUSE else 0.0))  # kept as FP16 in group memory
    if not flags & NO_SPECULAR:
        specular = anchor_lobe(specular, f16(RRs[..., :3]), blend[1] + (blend[3] - blend[1]) * flat0[..., 0], noise_variance[..., 0])
    diffuse = anchor_lobe(diffuse, rrd, blend[1] + (blend[3] - blend[1]) * flat0[..., 1], noise_variance[..., 1])
    specular=np.maximum(specular,-.25*np.maximum(f16(RRs[...,:3]),0.))
    diffuse=np.maximum(diffuse,-.25*np.maximum(rrd,0.))
    mod = c["Modulation"]
    correction = specular * (1.0 + np.clip(mod[0], 0, 1) * (Qs[..., :3] - 1.0)) + diffuse * (1.0 + np.clip(mod[1], 0, 1) * (Qd[..., :3] - 1.0))
    base = composed[..., :3]
    limit = np.ones((h, w), np.float32)
    for ch_ in range(3):
        bad = (base[..., ch_] + correction[..., ch_] < 0) & (correction[..., ch_] < 0)
        limit = np.where(bad, np.minimum(limit, np.maximum(base[..., ch_], 0.0) / np.where(bad, -correction[..., ch_], 1.0)), limit)
    correction = correction * np.clip(limit, 0, 1)[..., None]
    correction = np.where(np.all(np.isfinite(correction), -1, keepdims=True), correction, 0.0)
    correction = np.where((skip[..., 3] == -1.0)[..., None], 0.0, correction)
    color = np.concatenate([base + correction, composed[..., 3:4]], -1)
    return None, None, noise, f16(np.clip(color, -65504, 65504))
