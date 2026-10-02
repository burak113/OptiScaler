"""Saved-output attribution only; no candidate evaluation, IO or runtime imports."""


def observable_mean_component(np, C, Qspec, Qdiff, P, R, geometry_valid, *,
                              linear_depth, normals, depth_gradient,
                              roughness_codes, material_codes):
    """B=M*muD and eligible support, with the frozen recovery mean schedule.

    Truth and saved T are deliberately absent from this function.
    """
    arrays = [np.asarray(x, dtype=np.float64) for x in (C, Qspec, Qdiff, P, R)]
    if arrays[0].ndim != 3 or arrays[0].shape[2] != 3:
        raise ValueError('RGB schema')
    h, w = arrays[0].shape[:2]
    if min(h, w) < 8 or any(x.shape != (h, w, 3) for x in arrays):
        raise ValueError('matching extent at least8')
    C, Qspec, Qdiff, P, R = arrays
    if (not np.isfinite(R).all() or np.any(R < 0) or np.any(R >= 65504) or
            not np.array_equal(R, R.astype('<f2').astype(np.float64))):
        raise ValueError('paired R stored HALF')
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
        raise ValueError('stored rough/material codes')
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

    B = np.zeros_like(U)
    eligible = np.zeros((h, w), dtype=bool)
    for py in range(h):
        for px in range(w):
            sy, sx = np.mgrid[max(py - 1, 0):min(py + 2, h),
                             max(px - 1, 0):min(px + 2, w)]
            accepted = surface_mask(py, px, sy, sx)
            centre = (sy == py) & (sx == px)
            y0, x0 = min(max(py - 3, 0), h - 8), min(max(px - 3, 0), w - 8)
            yy, xx = np.mgrid[y0:y0 + 8, x0:x0 + 8]
            if (np.count_nonzero(accepted) < 2 or not accepted[centre].all() or
                    not surface_mask(py, px, yy, xx).all()):
                continue
            up, vp = U[sy[accepted], sx[accepted]], V[sy[accepted], sx[accepted]]
            muP, muR = np.mean(up, axis=0), np.mean(vp, axis=0)
            B[py, px] = M[py, px] * (muP - muR)
            eligible[py, px] = np.isfinite(B[py, px]).all()
    return B, eligible


def _gram(np, arrays):
    names = ('BASE_ERROR', 'MEAN', 'REMAINDER')
    gram = [[float(np.mean(a * b)) for b in arrays] for a in arrays]
    gram_rgb = [[np.mean(a * b, axis=(0, 1)).tolist() for b in arrays] for a in arrays]
    expanded = sum(gram[i][i] for i in range(3)) + 2 * sum(
        gram[i][j] for i in range(3) for j in range(i + 1, 3))
    return dict(order=list(names), dot=gram, dot_RGB=gram_rgb,
                RMS=[float(np.sqrt(gram[i][i])) for i in range(3)],
                expanded_MSE=expanded)


def attribute_frame(np, C, Qspec, Qdiff, P, R, T, truth, geometry_valid, *,
                    linear_depth, normals, depth_gradient, roughness_codes,
                    material_codes, regions, closed_fallback_pixels):
    """Analyze fixed saved T; truth is used only after observable means.

    Caller must pin actual CLOSED zero-fallback telemetry for this cohort.
    regions maps names to declared (x_begin,x_end), never enters mean computation.
    """
    if closed_fallback_pixels != 0:
        raise ValueError('arithmetic/fallback mask unsaved; zero-fallback cohort required')
    B, eligible = observable_mean_component(np, C, Qspec, Qdiff, P, R, geometry_valid,
        linear_depth=linear_depth, normals=normals, depth_gradient=depth_gradient,
        roughness_codes=roughness_codes, material_codes=material_codes)
    if not eligible.all():
        raise ValueError('mean support differs from closed fully-supported cohort')
    R, T, truth = [np.asarray(x, dtype=np.float64) for x in (R, T, truth)]
    if T.shape != R.shape or truth.shape != R.shape or not np.isfinite(truth).all():
        raise ValueError('truth/T RGB schema')
    if (not np.isfinite(T).all() or np.any(T < 0) or np.any(T >= 65504) or
            not np.array_equal(T, T.astype('<f2').astype(np.float64))):
        raise ValueError('saved T must be valid stored HALF')
    H = T - R - B
    E_R, E_T = R - truth, T - truth
    rows = {}
    for name, (lo, hi) in regions.items():
        if not (0 <= lo < hi <= R.shape[1]):
            raise ValueError('fixed region extent')
        components = [x[:, lo:hi] for x in (E_R, B, H)]
        actual_error = E_T[:, lo:hi]
        pixel_gram = _gram(np, components)
        pixel_MSE = float(np.mean(actual_error * actual_error))
        # EXACT same material-profile operator: mean over Y, remove mean over X.
        profiles = []
        for x in components:
            profile = x.mean(axis=0)
            profiles.append(profile - profile.mean(axis=0, keepdims=True))
        tprofile = actual_error.mean(axis=0)
        tprofile -= tprofile.mean(axis=0, keepdims=True)
        # Shape(1,X,3) keeps Gram RGB reduction axes consistent.
        profile_gram = _gram(np, [x[None] for x in profiles])
        profile_MSE = float(np.mean(tprofile * tprofile))
        carriers = {}
        for kind, axis, frequency, idx in (
                ('material', 0, 1 / 8, np.arange(lo, hi)),
                ('illumination', 1, 1 / 16, np.arange(R.shape[0]))):
            carrier = np.exp(-2j * np.pi * frequency * idx)
            reference = truth[:, lo:hi].mean(axis=axis)
            denominator = np.einsum('ic,i->c', reference - reference.mean(axis=0), carrier)
            numerator = {}
            ratios = {}
            for label, x in (('BASE', R), ('MEAN', B), ('REMAINDER', H), ('T', T)):
                profile = x[:, lo:hi].mean(axis=axis)
                operand = np.einsum('ic,i->c', profile - profile.mean(axis=0), carrier)
                numerator[label] = operand
                ratios[label] = [None if abs(denominator[c]) < 1e-12 else
                                 dict(Re=float((operand[c] / denominator[c]).real),
                                      Im=float((operand[c] / denominator[c]).imag)) for c in range(3)]
            closure = numerator['T'] - numerator['BASE'] - numerator['MEAN'] - numerator['REMAINDER']
            carriers[kind] = dict(contributions=ratios,
                numerator_closure_Re_RGB=closure.real.tolist(),
                numerator_closure_Im_RGB=closure.imag.tolist(),
                reference_zero_RGB=(np.abs(denominator) < 1e-12).tolist())
        rows[name] = dict(pixel_error_gram=pixel_gram, actual_T_MSE=pixel_MSE,
            pixel_MSE_closure_residual=pixel_MSE - pixel_gram['expanded_MSE'],
            material_profile_gram=profile_gram, actual_T_material_error_squared=profile_MSE,
            material_MSE_closure_residual=profile_MSE - profile_gram['expanded_MSE'],
            pointwise_identity_max_abs=float(np.max(np.abs(actual_error - sum(components)))),
            carriers=carriers)
    return dict(status='SAVED_COMPONENT_ATTRIBUTION_ONLY_NO_ACCEPTANCE', rows=rows,
                remainder_includes_HALF_rounding=True, source_truth_used_only_for_scores=True,
                mean_supported_pixels=int(np.count_nonzero(eligible)),
                actual_candidate_rejection_unchanged=True,
                no_counterfactual_quality_acceptance=True)
