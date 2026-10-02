"""Fixed material-constrained normalized residual projector; root executes.

Pure injectable NumPy interface. No runtime imports, IO, truth or history.
"""

PATCH = 8
STRIDE = 4


def _anchors(length):
    last = length - PATCH
    anchors = list(range(0, last + 1, STRIDE))
    if anchors[-1] != last:
        anchors.append(last)
    return anchors


def _pinv(np, matrix):
    u, s, vh = np.linalg.svd(matrix, full_matrices=False)
    if not np.isfinite(s).all():
        raise ValueError('nonfinite SVD')
    cutoff = max(matrix.shape) * np.finfo(np.float64).eps * s[0]
    retained = s > cutoff
    inverse = np.zeros_like(s)
    np.divide(1, s, out=inverse, where=retained)
    return (vh.T * inverse) @ u.T, int(np.count_nonzero(retained))


def apply_frame(np, Qspec, Qdiff, P, R, geometry_valid, *, linear_depth,
                normals, depth_gradient, roughness_codes, material_codes):
    """Return modeled HALF total RGB promoted float64 and scalar telemetry.

    P is observable detailed saved output; R is paired actual visible baseline.
    RGB input schema(H,W,3), exact decoded HALF. Geometry matches frozen law.
    """
    arrays = [np.asarray(x, dtype=np.float64) for x in (Qspec, Qdiff, P, R)]
    if arrays[0].ndim != 3 or arrays[0].shape[2] != 3:
        raise ValueError('RGB schema')
    h, w = arrays[0].shape[:2]
    if min(h, w) < PATCH or any(x.shape != (h, w, 3) for x in arrays):
        raise ValueError('matching extent at least8')
    Qspec, Qdiff, P, R = arrays
    if (not np.isfinite(R).all() or np.any(R < 0) or np.any(R >= 65504) or
            not np.array_equal(R, R.astype('<f2').astype(np.float64))):
        raise ValueError('paired fallback must be valid stored HALF')
    z = np.asarray(linear_depth, dtype=np.float64)
    n = np.asarray(normals, dtype=np.float64)
    grad = np.asarray(depth_gradient, dtype=np.float64)
    rough = np.asarray(roughness_codes)
    material = np.asarray(material_codes)
    valid = np.asarray(geometry_valid, dtype=bool).copy()
    if (valid.shape != (h, w) or z.shape != (h, w) or
            n.shape != (h, w, 3) or grad.shape != (h, w, 2) or
            rough.shape != (h, w) or material.shape != (h, w)):
        raise ValueError('geometry schema')
    if (rough.dtype.kind not in 'iu' or material.dtype.kind not in 'iu' or
            np.any(rough < 0) or np.any(rough > 1023) or
            np.any(material < 0) or np.any(material > 3)):
        raise ValueError('stored10bit roughness/2bit material required')
    valid &= np.isfinite(z) & (z != 0)
    valid &= np.isfinite(n).all(2) & np.isfinite(grad).all(2)
    n = np.where(np.isfinite(n), n, 0)
    norm2 = np.sum(n * n, axis=2)
    normal_domain = np.isfinite(norm2) & (norm2 > 0)
    valid &= normal_domain
    n = n / np.sqrt(np.where(normal_domain, norm2, 1))[..., None]
    for x in (Qspec, Qdiff, P):
        domain = np.isfinite(x) & (x >= 0) & (x < 65504)
        safe = np.where(domain, x, 0)
        valid &= (domain & (x == safe.astype('<f2').astype(np.float64))).all(2)
    valid &= ((Qspec <= 1) & (Qdiff <= 1)).all(2)
    M = Qspec + Qdiff
    valid &= np.isfinite(M).all(2) & (M > 0).all(2)
    safe_M = np.where(valid[..., None], M, 1)
    U = np.where(valid[..., None], P, 0) / safe_M
    V = np.where(valid[..., None], R, 0) / safe_M
    valid &= np.isfinite(U).all(2) & np.isfinite(V).all(2)
    D = U - V

    def compatible(py, px, yy, xx):
        # Frozen same-surface admission, not albedo-pattern veto.
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

    gy, gx = np.mgrid[0:PATCH, 0:PATCH]
    x, y = (gx.reshape(-1) - 3.5) / 3.5, (gy.reshape(-1) - 3.5) / 3.5
    X = np.stack((np.ones(PATCH * PATCH), x, y, x * x, x * y, y * y), axis=1)
    identity = np.eye(PATCH * PATCH, dtype=np.float64)
    sums = np.zeros_like(D)
    counts = np.zeros((h, w), dtype=np.int64)
    rankZ = [0] * 7
    rankA = [0] * 7
    eligible_patches = 0
    successful_patches = 0
    arithmetic_rejected = 0
    ys, xs = _anchors(h), _anchors(w)
    for y0 in ys:
        for x0 in xs:
            yy, xx = np.mgrid[y0:y0 + PATCH, x0:x0 + PATCH]
            if not compatible(y0 + 3, x0 + 3, yy, xx):
                continue
            eligible_patches += 1
            patch = (slice(y0, y0 + PATCH), slice(x0, x0 + PATCH))
            Z = np.concatenate((Qspec[patch].reshape(-1, 3), Qdiff[patch].reshape(-1, 3)), axis=1)
            Z = Z - Z.mean(axis=0, keepdims=True)
            lengths = np.sqrt(np.sum(Z * Z, axis=0))
            normalized = np.zeros_like(Z)
            np.divide(Z, lengths, out=normalized, where=lengths > 0)
            try:
                inverseZ, rz = _pinv(np, normalized)
                N = identity - normalized @ inverseZ
                A = N @ X
                inverseA, ra = _pinv(np, A)
                estimate = A @ (inverseA @ D[patch].reshape(-1, 3))
            except (np.linalg.LinAlgError, ValueError):
                arithmetic_rejected += 1
                continue
            if not np.isfinite(estimate).all():
                arithmetic_rejected += 1
                continue
            rankZ[rz] += 1
            rankA[ra] += 1
            sums[patch] += estimate.reshape(PATCH, PATCH, 3)
            counts[patch] += 1
            successful_patches += 1
    mean = np.zeros_like(D)
    np.divide(sums, counts[..., None], out=mean, where=counts[..., None] > 0)
    total = R + safe_M * mean
    use = valid & (counts > 0) & np.isfinite(total).all(2)
    use &= ((total >= 0) & (total < 65504)).all(2)
    stored = np.where(use[..., None], total, R).astype('<f2').astype(np.float64)
    use &= np.isfinite(stored).all(2) & ((stored >= 0) & (stored < 65504)).all(2)
    output = np.where(use[..., None], stored, R)
    return output, dict(
        patch_size=PATCH, stride=STRIDE, final_edge_origin_included=True,
        patches_possible=len(ys) * len(xs), patches_eligible=eligible_patches,
        patches_succeeded=successful_patches, patches_arithmetic_rejected=arithmetic_rejected,
        nuisance_rank_histogram=rankZ, projected_spatial_rank_histogram=rankA,
        covered_pixels=int(np.count_nonzero(counts > 0)),
        projected_pixels=int(np.count_nonzero(use)), fallback_pixels=int(np.count_nonzero(~use)),
        actually_changed_pixels=int(np.count_nonzero(np.any(output != R, axis=2))),
        changed_RGB_words=int(np.count_nonzero(output != R)),
        min_positive_overlap_count=int(np.min(counts[counts > 0])) if np.any(counts > 0) else 0,
        max_overlap_count=int(np.max(counts)), no_temporal_history=True,
        no_noise_confidence=True, no_native_variance_box=True,
        numeric_rank_cutoff='max(matrix.shape)*eps_float64*s_max')
