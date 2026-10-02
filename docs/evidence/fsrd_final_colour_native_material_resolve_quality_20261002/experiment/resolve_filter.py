"""One final-colour native material-span resolve; parent executes.

Pure injectable NumPy. No imports, IO, truth, histories or author execution.
J is saved final-colour output of the CLOSED nuisance projector, not its P.
"""


def apply_frame(np, Qspec, Qdiff, J, R, geometry_valid, *, linear_depth,
                normals, depth_gradient, roughness_codes, material_codes):
    """Return modeled HALF visible RGB promoted float64 and scalar telemetry."""
    arrays = [np.asarray(a, dtype=np.float64) for a in (Qspec, Qdiff, J, R)]
    if arrays[0].ndim != 3 or arrays[0].shape[2] != 3:
        raise ValueError('RGB schema')
    h, w = arrays[0].shape[:2]
    if min(h, w) < 1 or any(a.shape != (h, w, 3) for a in arrays):
        raise ValueError('matching nonempty RGB extent')
    Qspec, Qdiff, J, R = arrays
    if (not np.isfinite(R).all() or np.any(R < 0) or np.any(R >= 65504) or
            not np.array_equal(R, R.astype('<f2').astype(np.float64))):
        raise ValueError('paired fallback must be valid stored HALF')
    z = np.asarray(linear_depth, dtype=np.float64)
    n = np.asarray(normals, dtype=np.float64)
    grad = np.asarray(depth_gradient, dtype=np.float64)
    rough = np.asarray(roughness_codes)
    material = np.asarray(material_codes)
    valid = np.asarray(geometry_valid, dtype=bool).copy()
    if (valid.shape != (h, w) or z.shape != (h, w) or n.shape != (h, w, 3) or
            grad.shape != (h, w, 2) or rough.shape != (h, w) or
            material.shape != (h, w)):
        raise ValueError('geometry schema')
    if (rough.dtype.kind not in 'iu' or material.dtype.kind not in 'iu' or
            np.any(rough < 0) or np.any(rough > 1023) or
            np.any(material < 0) or np.any(material > 3)):
        raise ValueError('stored10bit roughness/2bit material required')
    valid &= np.isfinite(z) & (z != 0)
    valid &= np.isfinite(n).all(2) & np.isfinite(grad).all(2)
    n = np.where(np.isfinite(n), n, 0)
    with np.errstate(over='ignore', invalid='ignore'):
        norm2 = np.sum(n * n, axis=2)
    normal_domain = np.isfinite(norm2) & (norm2 > 0)
    valid &= normal_domain
    n = n / np.sqrt(np.where(normal_domain, norm2, 1))[..., None]
    for a in (Qspec, Qdiff, J):
        domain = np.isfinite(a) & (a >= 0) & (a < 65504)
        safe = np.where(domain, a, 0)
        valid &= (domain & (a == safe.astype('<f2').astype(np.float64))).all(2)
    valid &= ((Qspec <= 1) & (Qdiff <= 1)).all(2)
    valid &= ((Qspec + Qdiff) > 0).all(2)

    def links(py, px, qy, qx):
        zp, zq = z[py, px], z[qy, qx]
        with np.errstate(over='ignore', invalid='ignore', divide='ignore'):
            pred = grad[py, px, 0] * (qx - px) + grad[py, px, 1] * (qy - py)
            back = grad[qy, qx, 0] * (px - qx) + grad[qy, qx, 1] * (py - qy)
            finite_prediction = np.isfinite(pred) & np.isfinite(back)
            pred = np.clip(pred, -0.25 * np.abs(zp), 0.25 * np.abs(zp))
            back = np.clip(back, -0.25 * np.abs(zq), 0.25 * np.abs(zq))
            dp = np.maximum(1 - np.abs(zp + pred - zq) /
                            np.maximum(0.01 * np.abs(zp), 1e-3), 0) ** 2
            dq = np.maximum(1 - np.abs(zq + back - zp) /
                            np.maximum(0.01 * np.abs(zq), 1e-3), 0) ** 2
            normal = np.clip((np.sum(n[py, px] * n[qy, qx], axis=2) - 0.9) * 10, 0, 1) ** 2
        return (valid[py, px] & valid[qy, qx] & finite_prediction &
                ((zp > 0) == (zq > 0)) & np.isfinite(dp) & np.isfinite(dq) &
                np.isfinite(normal) & (dp > 0) & (dq > 0) & (normal > 0) &
                (rough[py, px] == rough[qy, qx]) &
                (material[py, px] == material[qy, qx]))

    yy, xx = np.mgrid[0:h, 0:max(w - 1, 0)]
    right = links(yy, xx, yy, xx + 1)
    yy, xx = np.mgrid[0:max(h - 1, 0), 0:w]
    down = links(yy, xx, yy + 1, xx)
    flat_valid = valid.reshape(-1)
    seen = np.zeros(h * w, dtype=bool)
    use = np.zeros(h * w, dtype=bool)
    flat_J, flat_R = J.reshape(-1, 3), R.reshape(-1, 3)
    flat_S, flat_D = Qspec.reshape(-1, 3), Qdiff.reshape(-1, 3)
    output = flat_R.copy()
    rank_hist = [[0, 0, 0] for _ in range(3)]
    components = resolved = single = arithmetic_failed = final_failed = 0
    pre_drift, post_drift = [[], [], []], [[], [], []]
    for start in range(h * w):
        if seen[start] or not flat_valid[start]:
            continue
        stack, members = [start], []
        seen[start] = True
        while stack:
            index = stack.pop()
            members.append(index)
            y, x = divmod(index, w)
            adjacent = []
            if x and right[y, x - 1]:
                adjacent.append(index - 1)
            if x + 1 < w and right[y, x]:
                adjacent.append(index + 1)
            if y and down[y - 1, x]:
                adjacent.append(index - w)
            if y + 1 < h and down[y, x]:
                adjacent.append(index + w)
            for q in adjacent:
                if not seen[q]:
                    seen[q] = True
                    stack.append(q)
        components += 1
        if len(members) < 2:
            single += 1
            continue
        # Canonical row-major ordering, no invented 2D filling/interpolation.
        indices = np.asarray(sorted(members), dtype=np.int64)
        proposed = flat_J[indices].copy()
        bases, ranks = [], []
        try:
            for channel in range(3):
                G = np.stack((flat_S[indices, channel], flat_D[indices, channel]), axis=1)
                G = G - G.mean(axis=0, keepdims=True)
                lengths = np.sqrt(np.sum(G * G, axis=0))
                normalized = np.zeros_like(G)
                np.divide(G, lengths, out=normalized, where=lengths > 0)
                u, s, vh = np.linalg.svd(normalized, full_matrices=False)
                if not np.isfinite(u).all() or not np.isfinite(s).all() or not np.isfinite(vh).all():
                    raise ValueError('invalid material SVD')
                retained = s > max(normalized.shape) * np.finfo(np.float64).eps * s[0]
                basis = u[:, retained]
                delta = flat_J[indices, channel] - flat_R[indices, channel]
                proposed[:, channel] -= basis @ (basis.T @ delta)
                bases.append(basis)
                ranks.append(int(np.count_nonzero(retained)))
        except (np.linalg.LinAlgError, ValueError, FloatingPointError):
            arithmetic_failed += 1
            continue
        if (not np.isfinite(proposed).all() or np.any(proposed < 0) or
                np.any(proposed >= 65504)):
            final_failed += 1
            continue
        stored = proposed.astype('<f2').astype(np.float64)
        if not np.isfinite(stored).all() or np.any(stored < 0) or np.any(stored >= 65504):
            final_failed += 1
            continue
        # Whole component is accepted or falls back across ALL three RGB.
        component_pre, component_post = [], []
        for channel, basis in enumerate(bases):
            p = basis.T @ (proposed[:, channel] - flat_R[indices, channel])
            q = basis.T @ (stored[:, channel] - flat_R[indices, channel])
            component_pre.append(float(np.sqrt(np.sum(p * p) / len(indices))))
            component_post.append(float(np.sqrt(np.sum(q * q) / len(indices))))
        if not np.isfinite(component_pre).all() or not np.isfinite(component_post).all():
            arithmetic_failed += 1
            continue
        output[indices] = stored
        use[indices] = True
        resolved += 1
        for channel in range(3):
            rank_hist[channel][ranks[channel]] += 1
            pre_drift[channel].append(component_pre[channel])
            post_drift[channel].append(component_post[channel])
    return output.reshape(h, w, 3), dict(
        domain_valid_pixels=int(np.count_nonzero(valid)), geometry_components=components,
        resolved_components=resolved, single_pixel_fallback_components=single,
        arithmetic_fallback_components=arithmetic_failed, final_store_fallback_components=final_failed,
        resolved_pixels=int(np.count_nonzero(use)), fallback_pixels=int(np.count_nonzero(~use)),
        actually_changed_pixels=int(np.count_nonzero(np.any(output != flat_R, axis=1))),
        changed_RGB_words=int(np.count_nonzero(output != flat_R)),
        resolve_changed_vs_J_pixels=int(np.count_nonzero(np.any(output != flat_J, axis=1))),
        resolve_changed_vs_J_RGB_words=int(np.count_nonzero(output != flat_J)),
        material_rank_histogram_RGB=rank_hist,
        max_pre_store_projected_delta_RMS_RGB=[max(x) if x else None for x in pre_drift],
        max_post_store_projected_delta_RMS_RGB=[max(x) if x else None for x in post_drift],
        component_DC_unconstrained=True, post_HALF_exact_constraint_claim=False,
        material_span='perRGB demeaned original Qspec_c,Qdiff_c; nonzero column L2 normalized',
        numerical_rank='max(G.shape)*eps_float64*smax; strict greater',
        no_later_remod_gather=True, no_history=True, no_noise_confidence=True)
