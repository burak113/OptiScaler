"""Fixed collaborative visible-total research operator. SOURCE ONLY; root executes.

No truth, frame/region label, seed, frequency, history or native confidence input.
Caller supplies NumPy explicitly; this module imports no runtime/dependencies.
"""

PATCH = 8
GROUP = 8
STRIDE = 4
SEARCH_RADIUS = 32
SIGMA_MULTIPLIER = 3.0
GAUSSIAN_HH_SQUARE_MEDIAN = 0.4549364231195727


def _dct8(np):
    i = np.arange(PATCH, dtype=np.float64)
    k = np.arange(PATCH, dtype=np.float64)[:, None]
    d = np.cos(np.pi * (i[None, :] + 0.5) * k / PATCH)
    d *= (2.0 / PATCH) ** 0.5
    d[0] *= 0.5 ** 0.5
    return d


def apply_frame(np, C, Qspec, Qdiff, R, geometry_valid, *, linear_depth,
                normals, depth_gradient, roughness_codes, material_codes):
    """Return stored HALF candidate RGB promoted to float64, plus scalar telemetry.

    All RGB inputs shape(H,W,3), decoded stored HALF. R is actual composed total.
    Geometry: validity/depth/codes HW, unit normals HW3, depth gradient HW2.
    Domain/geometry fallback is atomic RGB to exact R; valid estimates replace R.
    """
    rgb = [np.asarray(a, dtype=np.float64) for a in (C, Qspec, Qdiff, R)]
    if rgb[0].ndim != 3 or rgb[0].shape[2] != 3:
        raise ValueError('RGB source schema')
    h, w = rgb[0].shape[:2]
    if min(h, w) < PATCH:
        raise ValueError('image too small for fixed patch')
    if any(a.shape != (h, w, 3) for a in rgb):
        raise ValueError('matching RGB extent/schema')
    C, Qspec, Qdiff, R = rgb
    geometry_valid = np.asarray(geometry_valid, dtype=bool)
    z = np.asarray(linear_depth, dtype=np.float64)
    n = np.asarray(normals, dtype=np.float64)
    grad = np.asarray(depth_gradient, dtype=np.float64)
    rough = np.asarray(roughness_codes)
    material = np.asarray(material_codes)
    if (geometry_valid.shape != (h, w) or z.shape != (h, w) or
            n.shape != (h, w, 3) or grad.shape != (h, w, 2) or
            rough.shape != (h, w) or material.shape != (h, w)):
        raise ValueError('geometry extent/schema')
    if (rough.dtype.kind not in 'iu' or material.dtype.kind not in 'iu' or
            np.any(rough > 1023) or np.any(rough < 0) or
            np.any(material > 3) or np.any(material < 0)):
        raise ValueError('stored10-bit roughness/2-bit material codes required')
    if not np.isfinite(R).all() or np.any(R < 0) or np.any(R >= 65504):
        raise ValueError('baseline fallback must have valid consumed RGB')
    if not np.array_equal(R, R.astype('<f2').astype(np.float64)):
        raise ValueError('baseline must be decoded stored HALF')
    valid = geometry_valid & np.isfinite(z) & (z != 0)
    valid &= np.isfinite(n).all(2) & np.isfinite(grad).all(2)
    n = np.where(np.isfinite(n), n, 0)
    norm2 = np.sum(n * n, axis=2)
    normal_domain = np.isfinite(norm2) & (norm2 > 0)
    valid &= normal_domain
    n = n / np.sqrt(np.where(normal_domain, norm2, 1))[..., None]
    for a in (C, Qspec, Qdiff):
        domain = np.isfinite(a) & (a >= 0) & (a < 65504)
        safe = np.where(domain, a, 0)
        typed = safe.astype('<f2').astype(np.float64)
        valid &= (domain & (a == typed)).all(2)
    valid &= ((Qspec <= 1) & (Qdiff <= 1)).all(2)
    M = Qspec + Qdiff
    valid &= np.isfinite(M).all(2) & (M > 0).all(2)
    # Invalid samples are excluded, never clipped/extrapolated into usable evidence.
    safe_C = np.where(valid[..., None], C, 0)
    safe_M = np.where(valid[..., None], M, 1)
    U = safe_C / safe_M
    valid &= np.isfinite(U).all(2)

    def compatible(py, px, yy, xx):
        """Positive guideFlags1 CompositionSurfaceWeight; no albedo-pattern veto.

        Exact stored roughness/material equality is an additional conservative gate.
        bool validity alone is never correspondence.
        """
        if not valid[py, px] or not valid[yy, xx].all():
            return False
        dz = z[py, px]
        if np.any(z[yy, xx] * dz <= 0):
            return False
        prediction = grad[py, px, 0] * (xx - px) + grad[py, px, 1] * (yy - py)
        prediction = np.clip(prediction, -0.25 * abs(dz), 0.25 * abs(dz))
        depth = np.maximum(1 - np.abs(dz + prediction - z[yy, xx]) /
                           max(0.01 * abs(dz), 1e-3), 0) ** 2
        normal = np.maximum((np.sum(n[yy, xx] * n[py, px], axis=-1) - 0.9) * 10, 0)
        normal = np.minimum(normal, 1) ** 2
        return bool(np.all(depth * normal > 0) and
                    np.all(rough[yy, xx] == rough[py, px]) and
                    np.all(material[yy, xx] == material[py, px]))

    # h=(C00-C01-C10+C11)/2 has unit squared norm. Under local IID variance v,
    # Var(h)=v; h^2/v has chi-square1 median0.4549364231195727.
    hh = (safe_C[:-1, :-1] - safe_C[:-1, 1:] -
          safe_C[1:, :-1] + safe_C[1:, 1:]) * 0.5
    V = np.zeros_like(U)
    variance_valid = np.zeros((h, w), dtype=bool)
    for py in range(h):
        for px in range(w):
            y0 = min(max(py - 3, 0), h - PATCH)
            x0 = min(max(px - 3, 0), w - PATCH)
            yy, xx = np.mgrid[y0:y0 + PATCH, x0:x0 + PATCH]
            if not compatible(py, px, yy, xx):
                continue
            energy = hh[y0:y0 + PATCH - 1, x0:x0 + PATCH - 1] ** 2
            vc = np.median(energy, axis=(0, 1)) / GAUSSIAN_HH_SQUARE_MEDIAN
            vi = vc / (M[py, px] ** 2)
            if np.isfinite(vi).all() and np.all(vi >= 0):
                V[py, px] = vi
                variance_valid[py, px] = True

    nodes = []
    for y0 in range(0, h - PATCH + 1, STRIDE):
        for x0 in range(0, w - PATCH + 1, STRIDE):
            yy, xx = np.mgrid[y0:y0 + PATCH, x0:x0 + PATCH]
            if (variance_valid[yy, xx].all() and
                    compatible(y0 + 3, x0 + 3, yy, xx)):
                nodes.append((y0, x0))
    d = _dct8(np)
    d2 = d * d
    patches = {p: U[p[0]:p[0] + PATCH, p[1]:p[1] + PATCH] for p in nodes}
    sums = np.zeros_like(U)
    weights = np.zeros_like(U)
    zero_sums = np.zeros_like(U)
    zero_counts = np.zeros_like(U)
    complete = 0
    insufficient = 0
    rejected_arithmetic = 0
    zero_energy_channels = 0
    for y0, x0 in nodes:
        ref = patches[y0, x0]
        ranked = []
        for y1, x1 in nodes:
            if (y1, x1) == (y0, x0) or max(abs(y1 - y0), abs(x1 - x0)) > SEARCH_RADIUS:
                continue
            yy, xx = np.mgrid[y1:y1 + PATCH, x1:x1 + PATCH]
            if not compatible(y0 + 3, x0 + 3, yy, xx):
                continue
            distance = float(np.mean((patches[y1, x1] - ref) ** 2))
            ranked.append((distance, (y1 - y0) ** 2 + (x1 - x0) ** 2, y1, x1))
        selected = [(y0, x0)]
        for _, _, y1, x1 in sorted(ranked):
            if all(abs(y1 - ya) >= PATCH or abs(x1 - xa) >= PATCH for ya, xa in selected):
                selected.append((y1, x1))
                if len(selected) == GROUP:
                    break
        if len(selected) != GROUP:
            insufficient += 1
            continue
        group = np.stack([patches[p] for p in selected])
        vg = np.stack([V[y:y + PATCH, x:x + PATCH] for y, x in selected])
        spatial = np.einsum('ai,gijc,bj->gabc', d, group, d, optimize=True)
        coeff = np.einsum('kg,gabc->kabc', d, spatial, optimize=True)
        sv = np.einsum('ai,gijc,bj->gabc', d2, vg, d2, optimize=True)
        cv = np.einsum('kg,gabc->kabc', d2, sv, optimize=True)
        if not np.isfinite(coeff).all() or not np.isfinite(cv).all() or np.any(cv < 0):
            rejected_arithmetic += 1
            continue
        keep = (np.abs(coeff) > SIGMA_MULTIPLIER * np.sqrt(cv)) | (cv == 0)
        shrunk = np.where(keep, coeff, 0)
        inverse_group = np.einsum('kg,kabc->gabc', d, shrunk, optimize=True)
        estimate = np.einsum('ai,abc,bj->ijc', d, inverse_group[0], d, optimize=True)
        energy = np.sum(np.where(keep, cv, 0), axis=(0, 1, 2))
        if not np.isfinite(estimate).all() or not np.isfinite(energy).all() or np.any(energy < 0):
            rejected_arithmetic += 1
            continue
        complete += 1
        # Group retained noise-energy trace, not calibrated reference-patch uncertainty.
        # Estimated zero-energy contributors get their own equal-average tier.
        for c in range(3):
            dest = (slice(y0, y0 + PATCH), slice(x0, x0 + PATCH), c)
            if energy[c] == 0:
                zero_energy_channels += 1
                zero_sums[dest] += estimate[..., c]
                zero_counts[dest] += 1
            else:
                weight = 1.0 / energy[c]
                if not np.isfinite(weight):
                    continue
                sums[dest] += weight * estimate[..., c]
                weights[dest] += weight
    covered = (zero_counts > 0) | (weights > 0)
    filtered = np.zeros_like(U)
    np.divide(sums, weights, out=filtered, where=weights > 0)
    np.divide(zero_sums, zero_counts, out=filtered, where=zero_counts > 0)
    total = safe_M * filtered
    use = valid & covered.all(2) & np.isfinite(total).all(2)
    use &= ((total >= 0) & (total < 65504)).all(2)
    stored = np.where(use[..., None], total, R).astype('<f2').astype(np.float64)
    use &= np.isfinite(stored).all(2) & ((stored >= 0) & (stored < 65504)).all(2)
    output = np.where(use[..., None], stored, R)
    return output, dict(
        reference_nodes_possible=((h - PATCH) // STRIDE + 1) * ((w - PATCH) // STRIDE + 1),
        reference_nodes_eligible=len(nodes), groups_complete=complete,
        groups_insufficient_distinct_nonoverlap=insufficient,
        groups_arithmetic_rejected=rejected_arithmetic,
        zero_estimated_energy_reference_channels=zero_energy_channels,
        replaced_pixels=int(np.count_nonzero(use)), fallback_pixels=int(np.count_nonzero(~use)),
        changed_RGB_words=int(np.count_nonzero(output != R)),
        patch_size=PATCH, group_size=GROUP, stride=STRIDE, search_radius=SEARCH_RADIUS,
        sigma_multiplier=SIGMA_MULTIPLIER, no_temporal_history=True,
        valid_estimate_fully_replaces_native=True, no_certified_native_blend_confidence=True)
