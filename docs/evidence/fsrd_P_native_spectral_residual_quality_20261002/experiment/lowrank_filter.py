"""One empirical GD Frobenius shrinker of observable P/native residual.

Injectable NumPy; no imports, IO, truth, history or author execution.
"""

MP_QUADRATURE_ORDER = 128
MP_BISECTION_STEPS = 64


def _mp_median(np, beta, nodes, weights):
    """MP eigenvalue median via a stable angular density transformation.

    lambda(theta)=(1-sqrt(beta))**2+4*sqrt(beta)*sin(theta/2)**2.
    Density*dtheta is proportional to sin(theta)**2/lambda(theta).
    Normalize quadrature by its own full integral; solve half that mass.
    """
    root = float(np.sqrt(beta))

    def integral(end):
        theta = (nodes + 1) * (end / 2)
        if beta == 1:
            density = np.cos(theta / 2) ** 2
        else:
            lam = (1 - root) ** 2 + 4 * root * np.sin(theta / 2) ** 2
            density = np.sin(theta) ** 2 / lam
        return float((end / 2) * np.sum(weights * density))

    mass = integral(float(np.pi))
    if not np.isfinite(mass) or mass <= 0:
        raise ValueError('invalid MP integral')
    lo, hi = 0.0, float(np.pi)
    for _ in range(MP_BISECTION_STEPS):
        mid = (lo + hi) / 2
        if integral(mid) < mass / 2:
            lo = mid
        else:
            hi = mid
    theta = (lo + hi) / 2
    median = (1 - root) ** 2 + 4 * root * float(np.sin(theta / 2) ** 2)
    if not np.isfinite(median) or median <= 0:
        raise ValueError('invalid MP median')
    return median


def _shrink(np, matrix, mu, beta):
    """Unknown-noise Frobenius shrinkage; zero noise-scale limit is identity."""
    u, s, vh = np.linalg.svd(matrix, full_matrices=False)
    if (not np.isfinite(u).all() or not np.isfinite(s).all() or
            not np.isfinite(vh).all() or np.any(s < 0)):
        raise ValueError('nonfinite SVD')
    maximum = float(s[0])
    n = max(matrix.shape)
    if maximum == 0:
        return matrix.copy(), dict(sigma_hat=0.0, bulk_median=0.0,
                                   retained=0, zero_scale_identity=True)
    scaled = s / maximum
    median = float(np.median(scaled))
    tau = median / float(np.sqrt(mu))  # sigma_hat*sqrt(n), divided by s_max
    if not np.isfinite(tau) or tau < 0:
        raise ValueError('invalid bulk scale')
    if tau == 0:
        # No fitted floor or epsilon; exact limit retains the stored residual.
        return matrix.copy(), dict(sigma_hat=0.0, bulk_median=median * maximum,
                                   retained=int(np.count_nonzero(s > 0)),
                                   zero_scale_identity=True)
    root = float(np.sqrt(beta))
    keep = scaled > tau * (1 + root)
    ratio = np.zeros_like(scaled)
    np.divide(tau, scaled, out=ratio, where=keep)
    # Algebraically eta(s)/s. Factorization avoids subtracting close squares.
    product = ((1 - ((1 + root) * ratio) ** 2) *
               (1 - ((1 - root) * ratio) ** 2))
    filtered = np.where(keep, scaled * np.sqrt(np.maximum(product, 0)), 0)
    estimate = ((u * filtered) @ vh) * maximum
    sigma_hat = tau * maximum / float(np.sqrt(n))
    if not np.isfinite(estimate).all() or not np.isfinite(sigma_hat):
        raise ValueError('invalid shrink reconstruction')
    return estimate, dict(sigma_hat=float(sigma_hat), bulk_median=median * maximum,
                          retained=int(np.count_nonzero(filtered > 0)),
                          zero_scale_identity=False)


def apply_frame(np, Qspec, Qdiff, P, R, geometry_valid, *, linear_depth,
                normals, depth_gradient, roughness_codes, material_codes):
    """Return modeled HALF visible-total RGB and scalar-only telemetry.

    H/W are inferred, RGB inputs are exact decoded HALF. Guides normalize only.
    Geometry-only recursive tiling never selects a fixture/colour/frequency axis.
    """
    arrays = [np.asarray(x, dtype=np.float64) for x in (Qspec, Qdiff, P, R)]
    if arrays[0].ndim != 3 or arrays[0].shape[2] != 3:
        raise ValueError('RGB schema')
    h, w = arrays[0].shape[:2]
    if min(h, w) < 2 or any(x.shape != (h, w, 3) for x in arrays):
        raise ValueError('matching extent at least2')
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
    D = U - V
    valid &= np.isfinite(D).all(2)

    def supported(y0, y1, x0, x1):
        patch = (slice(y0, y1), slice(x0, x1))
        if not valid[patch].all():
            return False
        yy, xx = np.mgrid[y0:y1, x0:x1]
        zs, ns, gs = z[patch], n[patch], grad[patch]
        # All central pixels: odd=>one, even=>two per axis. Reciprocal support.
        ys = sorted({(y0 + y1 - 1) // 2, (y0 + y1) // 2})
        xs = sorted({(x0 + x1 - 1) // 2, (x0 + x1) // 2})
        for py in ys:
            for px in xs:
                dz = z[py, px]
                if (np.any(zs * dz <= 0) or
                        np.any(rough[patch] != rough[py, px]) or
                        np.any(material[patch] != material[py, px])):
                    return False
                prediction = grad[py, px, 0] * (xx - px) + grad[py, px, 1] * (yy - py)
                prediction = np.clip(prediction, -0.25 * abs(dz), 0.25 * abs(dz))
                depth = np.maximum(1 - np.abs(dz + prediction - zs) /
                                   max(0.01 * abs(dz), 1e-3), 0) ** 2
                reverse = gs[..., 0] * (px - xx) + gs[..., 1] * (py - yy)
                reverse = np.clip(reverse, -0.25 * np.abs(zs), 0.25 * np.abs(zs))
                back = np.maximum(1 - np.abs(zs + reverse - dz) /
                                  np.maximum(0.01 * np.abs(zs), 1e-3), 0) ** 2
                normal = np.clip((np.sum(ns * n[py, px], axis=2) - 0.9) * 10, 0, 1) ** 2
                if not np.all(depth * back * normal > 0):
                    return False
        return True

    nodes, weights = np.polynomial.legendre.leggauss(MP_QUADRATURE_ORDER)
    medians = {}
    estimate = np.zeros_like(D)
    covered = np.zeros((h, w), dtype=bool)
    tiles = [(0, h, 0, w)]
    accepted = rejected = split = 0
    retained = [0, 0, 0]
    zero_scale = [0, 0, 0]
    sigmas = [[], [], []]
    dimensions = {}
    while tiles:
        y0, y1, x0, x1 = tiles.pop()
        height, width = y1 - y0, x1 - x0
        if min(height, width) < 2:
            rejected += 1
            continue
        if not supported(y0, y1, x0, x1):
            # Geometry/domain only: split both axes, without missing-data fill.
            ym, xm = (y0 + y1) // 2, (x0 + x1) // 2
            tiles.extend((ya, yb, xa, xb) for ya, yb in ((y0, ym), (ym, y1))
                         for xa, xb in ((x0, xm), (xm, x1)))
            split += 1
            continue
        patch = (slice(y0, y1), slice(x0, x1))
        beta = min(height, width) / max(height, width)
        details = []
        candidate = np.zeros((height, width, 3), dtype=np.float64)
        try:
            if beta not in medians:
                medians[beta] = _mp_median(np, beta, nodes, weights)
            for channel in range(3):
                candidate[..., channel], info = _shrink(np, D[patch][..., channel],
                                                        medians[beta], beta)
                details.append(info)
        except (np.linalg.LinAlgError, ValueError, FloatingPointError):
            rejected += 1
            continue
        if not np.isfinite(candidate).all():
            rejected += 1
            continue
        estimate[patch] = candidate
        covered[patch] = True
        accepted += 1
        key = str(min(height, width)) + 'x' + str(max(height, width))
        dimensions[key] = dimensions.get(key, 0) + 1
        for channel, info in enumerate(details):
            retained[channel] += info['retained']
            zero_scale[channel] += int(info['zero_scale_identity'])
            sigmas[channel].append(info['sigma_hat'])
    total = R + safe_M * estimate
    use = valid & covered & np.isfinite(total).all(2)
    use &= ((total >= 0) & (total < 65504)).all(2)
    stored = np.where(use[..., None], total, R).astype('<f2').astype(np.float64)
    use &= np.isfinite(stored).all(2) & ((stored >= 0) & (stored < 65504)).all(2)
    output = np.where(use[..., None], stored, R)
    return output, dict(
        domain_valid_pixels=int(np.count_nonzero(valid)),
        covered_pixels=int(np.count_nonzero(covered)), recovered_pixels=int(np.count_nonzero(use)),
        fallback_pixels=int(np.count_nonzero(~use)),
        actually_changed_pixels=int(np.count_nonzero(np.any(output != R, axis=2))),
        changed_RGB_words=int(np.count_nonzero(output != R)),
        accepted_tiles=accepted, rejected_tiles=rejected, geometry_split_tiles=split,
        tile_dimensions_unordered=dimensions, retained_singular_values_RGB=retained,
        zero_noise_scale_identity_tiles_RGB=zero_scale,
        sigma_hat_min_RGB=[min(x) if x else None for x in sigmas],
        sigma_hat_max_RGB=[max(x) if x else None for x in sigmas],
        mp_quadrature_order=MP_QUADRATURE_ORDER, mp_bisection_steps=MP_BISECTION_STEPS,
        no_temporal_history=True, no_noise_calibration=True, no_native_variance_box=True,
        no_guide_nuisance_projection=True, RGB_independent=True)
