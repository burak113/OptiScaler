"""Past-only nominal3SE phase pilot with actual weighted-age uncertainty."""
import numpy as np

def make_significant_phase_pilot(raw, controls):
    c = np.asarray(raw, float)
    ctrl = np.asarray(controls, float)
    if c.ndim != 4 or c.shape[-1] != 3 or (not len(c)) or (min(c.shape[1:3]) < 8):
        raise ValueError('N,H,W,RGB >=8 required')
    if not np.isfinite(c).all() or np.any(c < 0) or np.any(c > 65504):
        raise ValueError('Valid source radiance required')
    if ctrl.shape != (len(c), 3) or not np.isfinite(ctrl).all() or (not np.isin(ctrl[:, 0], [0, 1]).all()):
        raise ValueError('reset,jitter controls required')
    nf, h, w, _ = c.shape
    n = h * w
    end = -1 if w % 2 == 0 else None
    boundary = [0] + ([w // 2] if w % 2 == 0 else [])
    out = c.copy()
    active = np.zeros(nf, bool)
    past = []
    sigmas = []
    records = []
    epoch = 0
    for i, frame in enumerate(c):
        reset = bool(ctrl[i, 0])
        jitter = bool(i and (not np.array_equal(ctrl[i, 1:], ctrl[i - 1, 1:])))
        if reset or jitter:
            past.clear()
            sigmas.clear()
            epoch = i
        current = np.fft.rfft2(frame, axes=(0, 1)) / n
        sigma = max(float(np.median(abs(current[:, 1:end, :]))) * np.sqrt(n / np.log(2)), np.finfo(float).eps * max(1.0, float(frame.max())))
        qcurrent = sigma * sigma / n
        m = len(past)
        theta = np.zeros(current.shape[:2])
        used = np.zeros_like(theta, bool)
        qualified = np.zeros_like(theta, bool)
        se_used = np.zeros_like(theta)
        if m >= 8:
            old = np.stack(past)
            a = old[1:]
            b = old[:-1]
            q = np.asarray(sigmas) ** 2 / n
            A = np.mean(np.sum(abs(a) ** 2, -1), 0)
            B = np.mean(np.sum(abs(b) ** 2, -1), 0)
            qa = 3 * np.mean(q[1:])
            qb = 3 * np.mean(q[:-1])
            C = np.sum(np.sum(a * np.conj(b), -1), 0)
            coherence = np.divide(abs(C), (m - 1) * np.sqrt(A * B), out=np.zeros_like(A), where=A * B > 0)
            ratio = np.minimum(np.maximum(A - qa, 0) / qa, np.maximum(B - qb, 0) / qb)
            qualified = (ratio > 16) & (coherence >= 0.8)
            E = np.maximum((A + B - qa - qb) / 2, 0)
            V = E * (q[0] + q[-1]) / 2 + 3 * np.sum(q[1:] * q[:-1]) / 2
            se = np.divide(np.sqrt(V), abs(C), out=np.full_like(A, np.inf), where=abs(C) > 0)
            angle = np.angle(C)
            used = qualified & (abs(angle) > 3 * se)
            theta = np.where(used, angle, 0)
            se_used = np.where(used, se, 0)
            for x in boundary:
                theta[0, x] = 0
                used[0, x] = False
                se_used[0, x] = 0
                for y in range(1, (h + 1) // 2):
                    j = -y % h
                    ok = bool(used[y, x] and used[j, x])
                    used[y, x] = used[j, x] = ok
                    t = theta[y, x] if ok else 0.0
                    s = se_used[y, x] if ok else 0.0
                    theta[y, x] = t
                    theta[j, x] = -t
                    se_used[y, x] = se_used[j, x] = s
                if h % 2 == 0:
                    theta[h // 2, x] = 0
                    used[h // 2, x] = False
                    se_used[h // 2, x] = 0
        theta[0, 0] = 0
        used[0, 0] = False
        se_used[0, 0] = 0
        innovation = np.zeros_like(theta, bool)
        mean_noise = qcurrent
        if m:
            aligned = [f * np.exp(1j * theta * (m - j))[..., None] for j, f in enumerate(past)]
            total = sum(aligned)
            weighted = sum(((m - j) * a for j, a in enumerate(aligned)))
            prior = total / m
            mean = (total + current) / (m + 1)
            prior_noise = sum((s * s for s in sigmas)) / (n * m * m)
            mean_noise = (sum((s * s for s in sigmas)) + sigma * sigma) / (n * (m + 1) ** 2)
            Dprior = 1j * weighted / m
            Dmean = 1j * weighted / (m + 1)
            vprior = (np.sqrt(prior_noise) + abs(Dprior) * se_used[..., None]) ** 2
            vmean = (np.sqrt(mean_noise) + abs(Dmean) * se_used[..., None]) ** 2
            innovation = np.any(abs(current - prior) > 3 * np.sqrt(qcurrent + vprior), -1)
        else:
            mean = current.copy()
            vmean = np.full(current.shape, qcurrent)
            vprior = np.zeros(current.shape)
        innovation[0, 0] = False
        selected = np.where(innovation[..., None], current, mean)
        selected[0, 0] = current[0, 0]
        variance = np.where(innovation[..., None], qcurrent, vmean)
        keep = np.any(abs(selected) > 4 * np.sqrt(variance), -1)
        keep[0, 0] = True
        prediction = np.fft.irfft2(selected * keep[..., None] * n, s=(h, w), axes=(0, 1))
        valid = bool(np.isfinite(prediction).all() and prediction.min() >= 0 and (prediction.max() <= 65504))
        if valid:
            out[i] = prediction
            active[i] = True
        records.append(dict(frame=i, active=valid, epoch_start=epoch, reset=reset, jitter_changed=jitter, preceding_observations=m, total_observations=m + 1, nominal_iid_pixel_sigma=sigma, nominal_mean_coefficient_variance=float(mean_noise), phase_power_coherence_qualified_frequencies=int(qualified.sum()), nominal_3SE_used_phase_frequencies=int(used.sum()), retained_frequencies=int(keep.sum()), retained_used_phase_frequencies=int((keep & used).sum()), retained_innovation_frequencies=int((keep & innovation).sum()), max_used_phase_increment=float(abs(theta[used]).max()) if used.any() else None, max_used_nominal_phase_SE=float(se_used[used].max()) if used.any() else None, max_nominal_prior_variance_inflation=float(np.max(vprior / prior_noise)) if m else None, max_nominal_mean_variance_inflation=float(np.max(vmean / mean_noise)), prediction_min=float(prediction.min()), prediction_max=float(prediction.max()), phase_estimator_uses_current=False, current_DC=True, effective_independent_pixels=None, reason='accepted' if valid else 'invalid_unclamped_prediction_raw_fallback'))
        _readonly_snapshot(i, selected, keep, innovation, used)
        past.append(current)
        sigmas.append(sigma)
        if len(past) >= 64:
            past.pop(0)
            sigmas.pop(0)
    return (out, active, dict(schema='nominal-significant-phase-source-pilot-feasibility-v1', history=64, frames=records, quality_accepted=False, no_clean_truth_input=True, guide_inputs=False, native_measured=False, phase_parameter_uncertainty='Plug-in constant coherent-amplitude circular-IID SE; actual complex weighted-age derivative; first-order Cauchy RMS accounting', exact_confidence_or_nonlinear_bound=False, effective_independent_pixels=None, limitations=['Spatial/temporal and RGB IID/noise scale assumptions not established', 'Random estimated energy/SE/derivative and selection invalidate unconditional bound claims', 'Nominal nonsignificance theta0 can lag true slow motion', 'Acceleration/amplitude drift break coherent lag model', 'Current DC noise, hard support churn and dense/nonperiodic source leakage remain', 'Correlated shared source bias unidentifiable', 'No native response, cost, game or general quality acceptance']))
