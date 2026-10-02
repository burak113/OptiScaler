"""Fixed empirical current-frame P/native recovery. SOURCE ONLY; root executes.

NumPy is supplied by caller. No truth, labels, history or tuning inputs.
"""

HH_PATCH = 8
HH_SQUARE_GAUSSIAN_MEDIAN = 0.4549364231195727


def apply_frame(np, C, Qspec, Qdiff, P, R, geometry_valid, *, linear_depth,
                normals, depth_gradient, roughness_codes, material_codes):
    """Return modeled stored HALF RGB promoted float64 and scalar diagnostics.

    C/P/R/Q RGB are decoded stored HALF HxWx3. P is observable saved candidate,
    R actual paired full1 visible baseline. Geometry schema matches frozen law.
    """
    arrays = [np.asarray(x, dtype=np.float64) for x in (C, Qspec, Qdiff, P, R)]
    if arrays[0].ndim != 3 or arrays[0].shape[2] != 3:
        raise ValueError('RGB schema')
    h, w = arrays[0].shape[:2]
    if min(h, w) < HH_PATCH or any(x.shape != (h, w, 3) for x in arrays):
        raise ValueError('matching extent at least8')
    C, Qspec, Qdiff, P, R = arrays
    if (not np.isfinite(R).all() or np.any(R < 0) or np.any(R >= 65504) or
            not np.array_equal(R, R.astype('<f2').astype(np.float64))):
        raise ValueError('paired fallback must be nonnegative unsaturated stored HALF')
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
        raise ValueError('stored10-bit roughness/2-bit material required')
    valid &= np.isfinite(z) & (z != 0)
    valid &= np.isfinite(n).all(2) & np.isfinite(grad).all(2)
    n = np.where(np.isfinite(n), n, 0)
    norm2 = np.sum(n * n, axis=2)
    normal_domain = np.isfinite(norm2) & (norm2 > 0)
    valid &= normal_domain
    n = n / np.sqrt(np.where(normal_domain, norm2, 1))[..., None]
    for x in (C, Qspec, Qdiff, P):
        domain = np.isfinite(x) & (x >= 0) & (x < 65504)
        safe = np.where(domain, x, 0)
        valid &= (domain & (x == safe.astype('<f2').astype(np.float64))).all(2)
    valid &= ((Qspec <= 1) & (Qdiff <= 1)).all(2)
    M = Qspec + Qdiff
    valid &= np.isfinite(M).all(2) & (M > 0).all(2)
    safe_M = np.where(valid[..., None], M, 1)
    normalized_C = np.where(valid[..., None], C, 0) / safe_M
    U = np.where(valid[..., None], P, 0) / safe_M
    V = np.where(valid[..., None], R, 0) / safe_M
    valid &= np.isfinite(normalized_C).all(2) & np.isfinite(U).all(2) & np.isfinite(V).all(2)

    def surface_mask(py, px, yy, xx):
        # Frozen collaborative same-surface admission law: positive guideFlags1
        # CompositionSurfaceWeight + exact rough/material codes, no albedo veto.
        if not valid[py, px]:
            return np.zeros(yy.shape, dtype=bool)
        dz = z[py, px]
        prediction = grad[py, px, 0] * (xx - px) + grad[py, px, 1] * (yy - py)
        prediction = np.clip(prediction, -0.25 * abs(dz), 0.25 * abs(dz))
        depth = np.maximum(1 - np.abs(dz + prediction - z[yy, xx]) /
                           max(0.01 * abs(dz), 1e-3), 0) ** 2
        normal = np.maximum((np.sum(n[yy, xx] * n[py, px], axis=-1) - 0.9) * 10, 0)
        normal = np.minimum(normal, 1) ** 2
        return (valid[yy, xx] & (z[yy, xx] * dz > 0) & (depth * normal > 0) &
                (rough[yy, xx] == rough[py, px]) & (material[yy, xx] == material[py, px]))

    def hh_square(image):
        hh = (image[:-1, :-1] - image[:-1, 1:] -
              image[1:, :-1] + image[1:, 1:]) * 0.5
        return hh * hh

    source_hh = hh_square(normalized_C)
    native_hh = hh_square(V)
    estimate = np.zeros_like(U)
    proposed = np.zeros((h, w), dtype=bool)
    insufficient_surface = 0
    arithmetic_rejected = 0
    zero_residual_variance_channels = 0
    zero_noise_allowance_channels = 0
    fully_suppressed_highband_channels = 0
    for py in range(h):
        for px in range(w):
            # Up to nine distinct in-bounds samples; accepted-count normalization.
            sy, sx = np.mgrid[max(py - 1, 0):min(py + 2, h),
                             max(px - 1, 0):min(px + 2, w)]
            accepted = surface_mask(py, px, sy, sx)
            centre = (sy == py) & (sx == px)
            y0 = min(max(py - 3, 0), h - HH_PATCH)
            x0 = min(max(px - 3, 0), w - HH_PATCH)
            yy, xx = np.mgrid[y0:y0 + HH_PATCH, x0:x0 + HH_PATCH]
            if (np.count_nonzero(accepted) < 2 or not accepted[centre].all() or
                    not surface_mask(py, px, yy, xx).all()):
                insufficient_surface += 1
                continue
            up, vp = U[sy[accepted], sx[accepted]], V[sy[accepted], sx[accepted]]
            muP, muR = np.mean(up, axis=0), np.mean(vp, axis=0)
            cp, cr = up - muP, vp - muR
            varP = np.mean(cp * cp, axis=0)
            varR = np.mean(cr * cr, axis=0)
            cov = np.mean(cp * cr, axis=0)
            vD = np.maximum(varP + varR - 2 * cov, 0)
            vC = np.median(source_hh[y0:y0 + 7, x0:x0 + 7], axis=(0, 1)) / HH_SQUARE_GAUSSIAN_MEDIAN
            vRH = np.median(native_hh[y0:y0 + 7, x0:x0 + 7], axis=(0, 1)) / HH_SQUARE_GAUSSIAN_MEDIAN
            nu = (np.sqrt(vC) + np.sqrt(vRH)) ** 2
            if (not np.isfinite(vD).all() or not np.isfinite(nu).all() or
                    np.any(vC < 0) or np.any(vRH < 0)):
                arithmetic_rejected += 1
                continue
            ratio = np.zeros(3, dtype=np.float64)
            np.divide(nu, vD, out=ratio, where=vD > 0)
            if not np.isfinite(ratio).all():
                arithmetic_rejected += 1
                continue
            weight = np.where(vD > 0, np.clip(1 - ratio, 0, 1), 0)
            muD = muP - muR
            delta = U[py, px] - V[py, px]
            total = M[py, px] * (V[py, px] + muD + weight * (delta - muD))
            if not np.isfinite(total).all() or np.any(total < 0) or np.any(total >= 65504):
                arithmetic_rejected += 1
                continue
            stored = total.astype('<f2').astype(np.float64)
            if not np.isfinite(stored).all() or np.any(stored < 0) or np.any(stored >= 65504):
                arithmetic_rejected += 1
                continue
            estimate[py, px] = stored
            proposed[py, px] = True
            zero_residual_variance_channels += int(np.count_nonzero(vD == 0))
            zero_noise_allowance_channels += int(np.count_nonzero(nu == 0))
            fully_suppressed_highband_channels += int(np.count_nonzero(weight == 0))
    output = np.where(proposed[..., None], estimate, R)
    return output, dict(
        recovered_pixels=int(np.count_nonzero(proposed)),
        fallback_pixels=int(np.count_nonzero(~proposed)),
        actually_changed_pixels=int(np.count_nonzero(np.any(output != R, axis=2))),
        changed_RGB_words=int(np.count_nonzero(output != R)),
        unsupported_stencils=insufficient_surface,
        arithmetic_rejected_pixels=arithmetic_rejected,
        zero_residual_variance_channels=zero_residual_variance_channels,
        zero_noise_allowance_channels=zero_noise_allowance_channels,
        fully_suppressed_highband_channels=fully_suppressed_highband_channels,
        mean_residual_transfer_unconditional=True,
        noise_allowance_empirical_not_certified=True,
        no_native_variance_box=True, no_temporal_history=True)
