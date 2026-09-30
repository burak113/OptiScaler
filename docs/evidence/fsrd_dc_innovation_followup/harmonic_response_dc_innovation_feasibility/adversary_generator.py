import numpy as np
def adversaries():
    f, h, w = (64, 64, 96)
    y, x = np.indices((h, w))
    rng = np.random.default_rng(83729)
    noise = rng.normal(0, 0.012, (f, h, w, 3))
    ctrl = np.zeros((f, 3))
    ctrl[0, 0] = 1
    phi = 2 * np.pi * (5.23 * x / w + 3.17 * y / h)
    psi = 2 * np.pi * (8.43 * x / w - 2.31 * y / h)
    static = np.broadcast_to(0.2 + 0.008 * np.cos(phi)[None, ..., None], noise.shape).copy()
    out = []

    def add(name, truth, observed=None, controls=None, exposure=None, supported=True, **extra):
        observed = truth + noise if observed is None else observed
        out.append(dict(family=name, raw=observed.astype('f4'), truth=truth.astype('f4'), controls=ctrl if controls is None else controls, exposure=exposure))
    add('offgrid_stationary_one_wave', static)
    two = np.broadcast_to(0.2 + 0.006 * np.cos(phi)[None, ..., None] + 0.004 * np.cos(psi)[None, ..., None], noise.shape).copy()
    add('two_offgrid_waves', two)
    dense = np.full_like(noise, 0.2)
    for fx, fy in ((1.2, 2.37), (4.53, -1.41), (7.17, 5.81), (12.19, -3.44), (15.21, 6.13), (9.6, 10.2)):
        dense += 0.004 * np.cos(2 * np.pi * (fx * x / w + fy * y / h))[None, ..., None]
    add('dense_more_than_two_components', dense)
    close = np.broadcast_to(0.2 + 0.008 * (np.cos(phi) + np.cos(2 * np.pi * (5.26 * x / w + 3.2 * y / h)))[None, ..., None], noise.shape).copy()
    add('close_frequency_illconditioning', close)
    weak = np.broadcast_to(0.2 + 0.0008 * ((-1.0) ** x)[None, ..., None], noise.shape).copy()
    add('weak_Nyquist_startup', weak)
    late = np.full_like(noise, 0.2)
    late[32:] = weak[32:]
    add('late_weak_appearance', late)
    for name, angle in (('slow_moving_phase', 0.02 * np.arange(f)), ('phase_acceleration', 0.0015 * np.arange(f) ** 2)):
        truth = np.broadcast_to(0.2 + 0.008 * np.cos(phi[None] + angle[:, None, None])[..., None], noise.shape).copy()
        add(name, truth)
    drift = np.stack([0.2 + 0.008 * np.cos(2 * np.pi * ((5.23 + 0.015 * i) * x / w + 3.17 * y / h)) for i in range(f)])
    add('frequency_drift', np.repeat(drift[..., None], 3, -1))
    light = static.copy()
    light[32:] *= 1.7
    add('multiplicative_illumination_step', light)
    light = static.copy()
    light[32:] += 0.08
    add('additive_DC_illumination_step', light)
    disco = static.copy()
    disco[32:] = 0.2 + 0.008 * np.cos(psi)[None, ..., None]
    add('disocclusion', disco)
    controls = ctrl.copy()
    controls[20, 0] = 1
    controls[40:, 1:] = [0.25, 0.125]
    ex = np.ones(f)
    ex[56:] = 2
    exposed = static.copy()
    exposed[56:] *= 2
    add('reset_jitter_exposure_metadata', exposed, controls=controls, exposure=ex)
    add('colored_RGB_noise', static, static + noise * np.array([0.5, 1, 2]), nominal_RGB_scale_false=True)
    add('current_RGB_correlated_noise', static, static + np.repeat(noise[..., :1], 3, -1), nominal_RGB_independence_false=True)
    ar = noise.copy()
    for i in range(1, f):
        ar[i] = 0.8 * ar[i - 1] + 0.6 * noise[i]
    add('temporal_AR_noise', static, static + ar, nominal_time_independence_false=True)
    clean = np.full_like(noise, 0.2)
    bias = 0.008 * np.cos(phi)[None, ..., None] * np.array([1, 0.8, 0.6])
    add('persistent_shared_bias', clean, clean + bias + noise, unidentifiable_clean_or_true_texture=True)
    checker = np.broadcast_to(0.2 + 0.02 * ((-1.0) ** x)[None, ..., None], noise.shape).copy()
    add('Nyquist_real_checker', checker)
    signed = static + noise
    signed[32, 1, 1, 0] = -0.001
    add('signed_source_fallback', static, signed, supported=False)
    near = static + noise
    near[32, ..., 0] = 1e-05
    near_truth = static.copy()
    near_truth[32, ..., 0] = 1e-05
    add('nearzero_channel_fallback', near_truth, near)
    overflow = static + noise
    overflow[32, 1, 1, 0] = 65505
    add('overflow_source_fallback', static, overflow, supported=False)
    high = np.zeros_like(noise)
    high[:, :, w // 2:] = 65504
    add('residual_carrier_or_Gibbs_fallback', high, high)
    return out
