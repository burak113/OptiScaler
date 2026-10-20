"""Job 02 v1: paired-log diagnostics with unconditional causal abstention.

This operates on already recalled native D+S cell observations. It changes no
transport, key selection, native units, or production policy. ``gain`` is always
identity: these observations cannot distinguish real light from input excess.
``provisional_gain`` is a deliberately non-deployable, one-sided diagnostic used
to measure conditional estimator trade-offs, including its real-light failures.

The interval is a deterministic FP16 rounding + local dispersion envelope, NOT a
confidence interval, effective sample count, or probability of an excess cause.
The same coherent error can move all taps together, leaving zero local MAD.
"""
from dataclasses import asdict, dataclass
from enum import IntFlag
import importlib.util
from pathlib import Path
import math

import numpy as np


VERSION = "anchor-diagnostic-v1"


@dataclass(frozen=True)
class Config:
    # Frozen before validation/holdout; no scene-specific tuning.
    min_pairs: int = 5
    tap_step: int = 3
    dispersion_multiplier: float = 1.0
    gain_low: float = 0.80
    band_a: float = 0.18
    tau: float = 10.0
    cap_extra: float = 0.05
    cap_hard: float = 0.30
    reject_mult: float = 1.8
    reject_abs: float = 0.30
    frame_min_coverage: float = 0.15
    physical_cap: float = 16.0
    atomic_scale: int = 65536


DEFAULT_CONFIG = Config()


class Reason(IntFlag):
    OFF = 1
    RESET = 2
    CENTER_UNSUPPORTED = 4
    SPARSE_SUPPORT = 8
    INVALID_INPUT = 16
    DARK_OR_UNBOUNDED = 32
    CAP_DOMAIN = 64
    FRAME_GUARD_AMBIGUOUS = 128
    FRAME_CHANGE_REJECTED = 256
    LOCAL_GUARD_AMBIGUOUS = 512
    LOCAL_CHANGE_REJECTED = 1024
    NO_POSITIVE_LOWER_BOUND = 2048
    MISSING_INDEPENDENT_CAUSE = 4096


def _validate_config(config):
    fields = asdict(config)
    if any(not math.isfinite(float(v)) for v in fields.values()):
        raise ValueError("configuration values must be finite")
    if (not isinstance(config.min_pairs, int) or config.min_pairs not in range(1, 10) or
            not isinstance(config.tap_step, int) or config.tap_step < 1 or
            config.dispersion_multiplier < 0. or config.tau <= 0. or
            not 0. <= config.gain_low <= 1. or not 0. <= config.frame_min_coverage <= 1. or
            min(config.band_a, config.cap_extra, config.cap_hard,
                config.reject_mult, config.reject_abs) < 0. or
            max(config.cap_hard, config.reject_abs) >= 1. or
            config.physical_cap != 16. or config.atomic_scale != 65536):
        raise ValueError("invalid diagnostic configuration or altered native units")


def _validate(stats, recalled):
    s, r = np.asarray(stats, np.float32), np.asarray(recalled, np.float32)
    if s.shape != r.shape or s.ndim != 3 or s.shape[-1] != 4 or min(s.shape[:2]) < 1:
        raise ValueError("expected matching nonempty H x W x 4 stored cell grids")
    return s, r


def support_mask(stats, recalled):
    """Observation support, separate from positive-level numerical usability."""
    s, r = _validate(stats, recalled)
    return ((s[..., 2] > .5) & (r[..., 1] > .5) & (r[..., 3] > .5) &
            np.isfinite(s).all(axis=-1) & np.isfinite(r).all(axis=-1) &
            (s[..., 0] >= 0) & (r[..., 0] >= 0))


def half_interval(values):
    """Conservative union of nonnegative finite FP16 RTNE and RTZ preimages.

    Native fields are stored half values. An arbitrary float32 input is first
    represented by the adjacent half value for this modeled storage stage.
    Lower midpoint includes ties; upper next-half includes the RTZ supremum.
    No guessed rounding mode narrows this interval. Maximum finite half has an
    unbounded upper endpoint and is marked unusable. NaN/negative are invalid.
    """
    v = np.asarray(values, np.float64)
    with np.errstate(over="ignore", invalid="ignore"):
        h = v.astype(np.float16)
        prev = np.nextafter(h, np.float16(-np.inf)).astype(np.float64)
        nex = np.nextafter(h, np.float16(np.inf)).astype(np.float64)
    q = h.astype(np.float64)
    valid = np.isfinite(v) & (v >= 0) & np.isfinite(q) & (q >= 0) & np.isfinite(nex)
    lo = np.maximum((prev + q) * .5, 0.)
    hi = nex
    return np.where(valid, lo, 0.), np.where(valid, hi, 0.), valid


def _qsum(values, config):
    # Native physical cap16 and floor-to-16.16, never a radiance scale change.
    q = np.floor(np.clip(np.asarray(values, np.float64), 0., config.physical_cap) *
                 config.atomic_scale)
    return int(q.astype(np.uint64).sum(dtype=np.uint64))


def frame_interval(stats, recalled, config=DEFAULT_CONFIG):
    """Bound the unseen native atomic ratio from rounded fields.

    JSON-safe metadata: ``upper: None`` denotes an undefined/unbounded ratio,
    never a fabricated finite denominator. Interval includes conservative FP32
    integer conversion/division slack; it is not an exact native atomic result.
    Invalid supported observations fail closed instead of disappearing from the
    frame denominator. Mask provenance is still the original observation flags.
    """
    _validate_config(config)
    s, r = _validate(stats, recalled)
    flag = (s[..., 2] > .5) & (r[..., 1] > .5) & (r[..., 3] > .5)
    x, y = s[..., 0][flag], r[..., 0][flag]
    xlo, xhi, xv = half_interval(x)
    ylo, yhi, yv = half_interval(y)
    invalid = bool(not (xv.all() and yv.all()) or
                   not np.isfinite(s[flag]).all() or not np.isfinite(r[flag]).all())
    count = int(flag.sum())
    base = {"provenance": "FP16 RTNE/RTZ union; native cap16/16.16 bounded estimate",
            "exact": False, "count": count, "coverage": count / flag.size,
            "invalid": invalid}
    if invalid or count == 0:
        return dict(base, central=None, lower=0., upper=None,
                    current_sum_bounds=[0, 0], recalled_sum_bounds=[0, 0])
    dx0, dx1 = _qsum(xlo, config), _qsum(xhi, config)
    ry0, ry1 = _qsum(ylo, config), _qsum(yhi, config)
    dmid = _qsum(x, config)
    central = _qsum(y, config) / dmid if dmid else None
    # Eight float32 epsilons cover split-word integer conversion, addition and
    # division in the native shader; round the interval outward.
    eps = 8. * float(np.finfo(np.float32).eps)
    lower = max(0., ry0 / dx1 * (1. - eps)) if dx1 else 0.
    upper = ry1 / dx0 * (1. + eps) if dx0 else None
    return dict(base, central=central, lower=lower, upper=upper,
                current_sum_bounds=[dx0, dx1], recalled_sum_bounds=[ry0, ry1])


def _lower_median(stack, valid):
    """Lower order median, not an even-sample interpolation; finite at n=0."""
    count = valid.sum(axis=0)
    index = np.maximum((count - 1) // 2, 0)
    sorted_values = np.sort(np.where(valid, stack, np.inf), axis=0)
    result = np.take_along_axis(sorted_values, index[None, ...], axis=0)[0]
    return np.where(count > 0, result, 0.)


def estimate(stats, recalled, k, *, strength=1.0, active=True, reset=False,
             frame_ratio_bounds=None, config=DEFAULT_CONFIG):
    """Return production identity and distinctly labeled diagnostic fields.

    ``frame_ratio_bounds`` optionally supplies (lower, upper), or a metadata
    dict containing these keys plus coverage. None endpoints fail closed.
    Use exact native atomics only when they really exist; packaged native fields
    need ``frame_interval``. All synthetic/captured results are conditional on
    recalled observations. No history is inferred and no reset state is hidden.
    """
    s, r = _validate(stats, recalled)
    _validate_config(config)
    if not math.isfinite(float(k)) or not math.isfinite(float(strength)):
        raise ValueError("k and strength must be finite")
    h, w = s.shape[:2]
    one = np.ones((h, w), np.float32)
    reason = np.full((h, w), int(Reason.MISSING_INDEPENDENT_CAUSE), np.uint32)
    support = support_mask(s, r)
    xlo, xhi, xv = half_interval(s[..., 0])
    ylo, yhi, yv = half_interval(r[..., 0])
    positive = support & xv & yv & (xlo > 0.) & (ylo > 0.)
    center = positive.copy()
    reason[~support] |= int(Reason.CENTER_UNSUPPORTED)
    reason[support & ~positive] |= int(Reason.DARK_OR_UNBOUNDED)
    invalid = (~np.isfinite(s).all(axis=-1) | ~np.isfinite(r).all(axis=-1) |
               (s[..., 0] < 0.) | (r[..., 0] < 0.))
    reason[invalid] |= int(Reason.INVALID_INPUT)
    log = np.zeros((h, w), np.float64)
    low = log.copy()
    high = log.copy()
    log[positive] = np.log(s[..., 0][positive].astype(np.float64) /
                           r[..., 0][positive].astype(np.float64))
    low[positive] = np.log(xlo[positive] / yhi[positive])
    high[positive] = np.log(xhi[positive] / ylo[positive])

    logs, lows, highs, valids, levels, cap_flags = [], [], [], [], [], []
    previous_ids = []
    # Clamp matches the old observation footprint, but repeated coordinates do
    # not manufacture new support. Distinct coordinates still need not be iid.
    for dy in (-config.tap_step, 0, config.tap_step):
        for dx in (-config.tap_step, 0, config.tap_step):
            yy = np.clip(np.arange(h) + dy, 0, h - 1)
            xx = np.clip(np.arange(w) + dx, 0, w - 1)
            index = np.ix_(yy, xx)
            ids = yy[:, None] * w + xx[None, :]
            unique = np.ones((h, w), bool)
            for old in previous_ids:
                unique &= ids != old
            previous_ids.append(ids)
            valid = positive[index] & unique
            logs.append(log[index]); lows.append(low[index]); highs.append(high[index])
            valids.append(valid)
            levels.append(np.where(valid, s[..., 0][index], 0.))
            cap_flags.append(valid & ((xhi[index] >= config.physical_cap) |
                                      (yhi[index] >= config.physical_cap)))
    valid = np.stack(valids)
    values = np.stack(logs)
    n = valid.sum(axis=0).astype(np.uint8)
    median = _lower_median(values, valid)
    mad = _lower_median(np.abs(values - median), valid)
    low = _lower_median(np.stack(lows), valid) - config.dispersion_multiplier * mad
    high = _lower_median(np.stack(highs), valid) + config.dispersion_multiplier * mad
    amount = np.stack(levels).astype(np.float64)
    total = amount.sum(axis=0)
    squares = (amount * amount).sum(axis=0)
    effective = np.divide(total * total, squares, out=np.zeros_like(total), where=squares > 0.)
    tails = np.divide(amount.max(axis=0), total, out=np.zeros_like(total), where=total > 0.)
    cap_domain = np.any(np.stack(cap_flags), axis=0)
    reason[n < config.min_pairs] |= int(Reason.SPARSE_SUPPORT)
    reason[cap_domain] |= int(Reason.CAP_DOMAIN)
    eligible = center & (n >= config.min_pairs) & ~cap_domain
    if not active:
        reason[:] |= int(Reason.OFF)
        eligible[:] = False
    if reset:
        reason[:] |= int(Reason.RESET)
        eligible[:] = False

    fi = frame_interval(s, r, config)
    if frame_ratio_bounds is not None:
        if isinstance(frame_ratio_bounds, dict):
            allowed = {"lower", "upper", "coverage", "central", "exact", "provenance"}
            if set(frame_ratio_bounds) - allowed:
                raise ValueError("unsupported frame interval metadata override")
            fi = dict(fi, **frame_ratio_bounds)
        else:
            lo, hi = frame_ratio_bounds
            fi = dict(fi, lower=lo, upper=hi, provenance="explicit caller interval")
    model = config.band_a * math.exp(-max(float(k), 0.) / config.tau)
    threshold = max(config.reject_mult * model, config.reject_abs)
    flo, fhi = fi["lower"], fi["upper"]
    if (fi.get("invalid", False) or flo is None or fhi is None or
            not math.isfinite(float(flo)) or not math.isfinite(float(fhi)) or
            float(flo) < 0. or float(fhi) < float(flo) or
            not math.isfinite(float(fi["coverage"])) or not 0. <= float(fi["coverage"]) <= 1.):
        reason[:] |= int(Reason.DARK_OR_UNBOUNDED)
        eligible[:] = False
        fi["invalid_interval"] = True
    elif fi["coverage"] >= config.frame_min_coverage:
        reject_at_low = 1. - float(flo) > threshold
        reject_at_high = 1. - float(fhi) > threshold
        if reject_at_low != reject_at_high:
            reason[:] |= int(Reason.FRAME_GUARD_AMBIGUOUS)
            eligible[:] = False
        elif reject_at_low:
            reason[:] |= int(Reason.FRAME_CHANGE_REJECTED)
            eligible[:] = False

    # Evaluate the strict guard over the entire interval, never just its centre.
    reject_local_low = 1. - np.exp(-low) > threshold
    reject_local_high = 1. - np.exp(-high) > threshold
    ambiguous = reject_local_low != reject_local_high
    reason[ambiguous] |= int(Reason.LOCAL_GUARD_AMBIGUOUS)
    reason[reject_local_low & reject_local_high] |= int(Reason.LOCAL_CHANGE_REJECTED)
    reason[low <= 0.] |= int(Reason.NO_POSITIVE_LOWER_BOUND)
    eligible &= ~ambiguous & ~reject_local_low & (low > 0.)
    cap = min(model + config.cap_extra, config.cap_hard)
    raw = np.maximum(np.clip(np.exp(-np.maximum(low, 0.)), config.gain_low, 1.), 1. - cap)
    raw = 1. + float(np.clip(strength, 0., 1.)) * (raw - 1.)
    provisional = np.where(eligible, raw, 1.).astype(np.float16).astype(np.float32)
    for name in ("lower", "upper", "coverage", "central"):
        if fi.get(name) is not None:
            fi[name] = float(fi[name]) if math.isfinite(float(fi[name])) else None
    return {"gain": one, "provisional_gain": provisional,
            "eligible": eligible, "abstain": np.ones((h, w), bool),
            "reason": reason, "support": support, "unique_pairs": n,
            "median_log_ratio": median, "log_lower": low, "log_upper": high,
            "mad_log": mad, "effective_energy_support": effective,
            "tail_share": tails, "frame_ratio": fi,
            "version": VERSION, "config": asdict(config)}


def bilinear_gain(gain, height, width):
    """Ideal CPU clamp/bilinear Apply model; NOT exact D3D sampler parity."""
    g = np.asarray(gain, np.float32)
    if g.ndim != 2 or min(g.shape) < 1 or min(height, width) < 1:
        raise ValueError("expected nonempty gain and positive output extent")
    xx = (np.arange(width, dtype=np.float64) + .5) * g.shape[1] / width - .5
    yy = (np.arange(height, dtype=np.float64) + .5) * g.shape[0] / height - .5
    x0, y0 = np.floor(xx).astype(int), np.floor(yy).astype(int)
    fx, fy = (xx - x0)[None, :], (yy - y0)[:, None]
    x1, y1 = np.clip(x0 + 1, 0, g.shape[1] - 1), np.clip(y0 + 1, 0, g.shape[0] - 1)
    x0, y0 = np.clip(x0, 0, g.shape[1] - 1), np.clip(y0, 0, g.shape[0] - 1)
    return np.clip((1. - fy) * ((1. - fx) * g[np.ix_(y0, x0)] + fx * g[np.ix_(y0, x1)]) +
                   fy * ((1. - fx) * g[np.ix_(y1, x0)] + fx * g[np.ix_(y1, x1)]), 0., 1.).astype(np.float32)


def apply_reference(diffuse, specular, gain):
    """Model shared native D/S RGB Apply, preserving every alpha storage bit.

    RGB uses production SanitizeRadiance (finite, clamp0..65500) then the input
    storage dtype. Alpha is copied without a numeric conversion, including half
    NaN payloads and signed zero. This model is not new full-resolution transport.
    """
    d, s = np.asarray(diffuse), np.asarray(specular)
    if d.shape != s.shape or d.ndim != 3 or d.shape[-1] != 4:
        raise ValueError("expected equal H x W x 4 native lobe inputs")
    if d.dtype not in (np.dtype("float16"), np.dtype("float32")) or s.dtype != d.dtype:
        raise ValueError("native lobes must have matching float16/float32 storage")
    factor = bilinear_gain(gain, d.shape[0], d.shape[1])
    outputs = []
    for a in (d, s):
        out = a.copy()
        rgb = a[..., :3].astype(np.float32) * factor[..., None]
        out[..., :3] = np.where(np.isfinite(rgb), np.clip(rgb, 0., 65500.), 0.).astype(a.dtype)
        outputs.append(out)
    return outputs[0], outputs[1]


def frozen_predict(*args, **kwargs):
    """Load the unchanged, versioned package estimator for comparative controls."""
    source = Path(__file__).resolve().parents[2] / "portable/anchor/anchor_reference.py"
    spec = importlib.util.spec_from_file_location("job02_frozen_anchor_reference", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.predict(*args, **kwargs)
