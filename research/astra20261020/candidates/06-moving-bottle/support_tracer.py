"""Read-only temporal support diagnostics. No RR emulation or production filter.

Coordinates use the handoff/job04 contract: previous minus current, full-render
UV, current and previous crop origins, no second jitter delta. The sampling
implementation is the packaged CPU reference, not an asserted D3D sampler.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import importlib.util
import numpy as np

_CLIP_PATH = Path(__file__).resolve().parents[2] / "fixtures/clips/clip_loader.py"
_spec = importlib.util.spec_from_file_location("job06_frozen_clip_loader", _CLIP_PATH)
_clip = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_clip)


@dataclass(frozen=True)
class CoordinateConvention:
    units: str = "full_render_uv"
    direction: str = "previous_minus_current"
    jitter: str = "already_encoded_no_extra_delta"
    pixel_centres: str = "integer_index_centres"

    def validate(self):
        if self != CoordinateConvention():
            raise ValueError("Unsupported convention; explicitly convert at the adapter boundary")


def previous_coordinates(motion_uv, current_origin, previous_origin, render_extent,
                         previous_shape=None, convention=CoordinateConvention()):
    """Delegate arithmetic to the immutable clip_loader; invalid history stays invalid."""
    convention.validate()
    mv = np.asarray(motion_uv)
    if mv.ndim != 3 or mv.shape[-1] < 2:
        raise ValueError("Motion must be H x W x >=2 with RG full-render UV")
    if np.asarray(render_extent).shape != (2,) or np.any(np.asarray(render_extent) <= 0) or not np.all(np.asarray(render_extent) == np.floor(render_extent)):
        raise ValueError("Positive render width,height required")
    if np.asarray(current_origin).shape != (2,) or np.asarray(previous_origin).shape != (2,):
        raise ValueError("Origins must be x,y pairs")
    if not np.isfinite(np.r_[current_origin, previous_origin, render_extent]).all():
        raise ValueError("Coordinate metadata must be finite")
    if np.any(np.asarray(render_extent) != np.floor(render_extent)):
        raise ValueError("Render extents are integer pixel counts, not fractional scales")
    arrays = {"input_motion": np.stack([np.zeros_like(mv), mv]),
              "crop_origin_render": np.stack([previous_origin, current_origin]),
              "render_extent": np.asarray(render_extent)}
    qx, qy, valid = _clip.previous_coordinates(arrays, 1)
    h, w = previous_shape[:2] if previous_shape is not None else mv.shape[:2]
    # The packaged helper assumes equal extents. The explicit check also supports
    # a different previous extent without changing the coordinate convention.
    valid = np.isfinite(qx) & np.isfinite(qy) & (qx >= 0) & (qy >= 0) & (qx < w-1) & (qy < h-1)
    return qx, qy, valid


def sample_previous(image, qx, qy):
    image, qx, qy = np.asarray(image), np.asarray(qx), np.asarray(qy)
    if image.ndim not in (2, 3) or qx.shape != qy.shape:
        raise ValueError("Image must be HxW[xC] and coordinate arrays must match")
    return _clip.sample_previous(image, qx, qy)


def luminance(image):
    image = np.asarray(image)
    if image.ndim >= 3 and image.shape[-1] in (3, 4):
        return np.sum(image[..., :3].astype(np.float32) * np.array([.2126, .7152, .0722], np.float32), axis=-1)
    return image.astype(np.float32)


def support(image, threshold):
    """A brightness-support proxy, never a physical silhouette or absence oracle."""
    if not np.isfinite(threshold) or threshold < 0:
        raise ValueError("Use a nonnegative threshold fixed before candidate evaluation")
    value = luminance(image)
    valid = np.isfinite(value)
    return valid & (value > threshold), valid


def trace_stages(stages, motion_uv, crop_origins, render_extent, frame_indices,
                 thresholds, convention=CoordinateConvention(), comparison_breaks=None):
    """Yield synchronized named-stage support and transported previous support.

    Stage data are never modified. First frame and nonconsecutive frame gaps
    have no history. Thresholds come from BASE/analytic truth, not a candidate.
    The caller owns uncertainty interpretation at sparse/zero-valued pixels.
    comparison_breaks[t] explicitly invalidates the prior observation at reset,
    convention/extent change or discarded capture; it NEVER resets the provider.
    A fixed render extent describes each segment; split DRS segments explicitly.
    """
    convention.validate()
    if not stages or set(thresholds) != set(stages):
        raise ValueError("A fixed threshold is required for every named stage")
    n = len(frame_indices)
    if len(motion_uv) != n or np.asarray(crop_origins).shape != (n, 2):
        raise ValueError("Mismatched chronology/crop metadata")
    indices = np.asarray(frame_indices)
    if indices.ndim != 1 or not np.isfinite(indices).all() or not np.all(indices == np.floor(indices)) or np.any(np.diff(indices) <= 0):
        raise ValueError("Chronology must be strictly increasing and unlooped")
    breaks = np.zeros(n, dtype=bool) if comparison_breaks is None else np.asarray(comparison_breaks)
    if breaks.shape != (n,) or breaks.dtype.kind != "b":
        raise ValueError("comparison_breaks must be an explicit boolean vector per frame")
    shape = np.asarray(motion_uv).shape[1:3]
    for name, stage in stages.items():
        if len(stage) != n or np.asarray(stage).shape[1:3] != shape:
            raise ValueError("Stage extent mismatch: " + name)
    for t, index in enumerate(indices):
        has_previous = t > 0 and index == indices[t-1]+1 and not breaks[t]
        if has_previous:
            qx, qy, coordinate_valid = previous_coordinates(motion_uv[t], crop_origins[t], crop_origins[t-1], render_extent, shape, convention)
        else:
            qx = qy = np.full(shape, np.nan)
            coordinate_valid = np.zeros(shape, dtype=bool)
        row = {"frame_index": int(index), "has_previous": bool(has_previous),
               "comparison_break": bool(breaks[t]),
               "previous_x": qx, "previous_y": qy, "coordinate_valid": coordinate_valid,
               "stages": {}}
        for name, values in stages.items():
            current, current_valid = support(values[t], thresholds[name])
            if has_previous:
                previous, previous_finite = support(values[t-1], thresholds[name])
                transported, inside = sample_previous(previous.astype(float), qx, qy)
                finite_coverage, _ = sample_previous(previous_finite.astype(float), qx, qy)
                usable = inside & (finite_coverage >= 1-1e-12)
                transported[~usable] = np.nan
            else:
                transported = np.full(shape, np.nan)
                usable = np.zeros(shape, dtype=bool)
            row["stages"][name] = {"current_support": current, "current_finite": current_valid,
                                     "transported_previous_support": transported, "history_valid": usable}
        yield row


def abstain_identity(selected):
    """Conservative candidate: no pixel changes, no retained history, zero-frame temporal latency.

    Missing metadata never causes a reset, clamp, gain or motion edit. Returning
    a copy protects ownership while preserving every dtype bit including alpha,
    signed zero and NaN payloads. Diagnostics cannot certify a production fix.
    """
    return np.asarray(selected).copy(order="K")


def diagnose(observation):
    """Conservative evidence classifier for explicitly independent witnesses.

    These fixed thresholds are synthetic discriminators, not game thresholds.
    A true silhouette and an independently validated geometry witness are
    unavailable in the supplied game clip; that route must abstain.
    """
    if observation.get("evidence_domain") != "analytic_synthetic":
        return {"diagnosis": "non_identifiable", "production_action": "identity",
                "reason": "This classifier is validated only on analytic witnesses; real capture flags cannot establish oracle provenance"}
    if not observation.get("independent_geometry", False) or not observation.get("known_support", False):
        return {"diagnosis": "non_identifiable", "production_action": "identity",
                "reason": "Independent current support and geometry correspondence are required"}
    if observation.get("guide_authority") is not True:
        return {"diagnosis": "non_identifiable", "production_action": "identity",
                "reason": "Guide correctness cannot be separated from motion correctness"}
    geometry = observation.get("geometry_error_px")
    if geometry is None or not np.isfinite(geometry):
        return {"diagnosis": "non_identifiable", "production_action": "identity", "reason": "No overlap witness"}
    required = ("raw_offsupport_fraction", "rr_offsupport_fraction", "selected_offsupport_fraction", "raw_support_fraction")
    if any(observation.get(key) is None or not np.isfinite(observation[key]) for key in required):
        return {"diagnosis": "non_identifiable", "production_action": "identity", "reason": "Incomplete or nonfinite support evidence"}
    if geometry < 0 or any(not 0 <= observation[key] <= 1 for key in required):
        return {"diagnosis": "non_identifiable", "production_action": "identity", "reason": "Out-of-range evidence"}
    virtual = observation.get("virtual_error_px")
    if virtual is not None and (not np.isfinite(virtual) or virtual < 0):
        return {"diagnosis": "non_identifiable", "production_action": "identity", "reason": "Invalid virtual witness"}
    if geometry > .45:
        label = "transport_error"
    elif observation.get("raw_offsupport_fraction", 0) > .12:
        label = "source_support_error"
    elif observation.get("virtual_error_px") is not None and observation["virtual_error_px"] > .45:
        label = "virtual_correspondence_error"
    elif observation.get("rr_offsupport_fraction", 0) > observation.get("raw_offsupport_fraction", 0)+.08:
        label = "provider_stage_tail"
    elif observation.get("selected_offsupport_fraction", 0) > observation.get("rr_offsupport_fraction", 0)+.08:
        label = "selected_stage_tail"
    elif observation.get("raw_support_fraction", 1) < .65:
        label = "sparse_source_no_motion_blame"
    else:
        label = "no_detected_support_error"
    return {"diagnosis": label, "production_action": "identity",
            "reason": "Synthetic conditional diagnosis; output remains unchanged",
            "virtual_correspondence_observable": observation.get("virtual_error_px") is not None,
            "ambiguities": (["MV bias versus jitter requires independent convention metadata"] if label == "transport_error" else []) + (["Virtual correspondence is unobservable; no positive hit-distance authority or reflected-feature witness"] if observation.get("virtual_error_px") is None else [])}


def _mean_or_none(values):
    values = np.asarray(values, float)
    return float(np.mean(values)) if values.size else None


def metric_sequence(values, truth, true_mask, centres, velocity, threshold=.25,
                    universe=None, detail_mask=None, disocclusion_mask=None):
    """Fixed-universe analytic metrics, with level and geometry reported separately.

    Input values/truth are nonnegative background-subtracted scalar signals.
    Error statistics use a truth-frozen denominator. IoU's union is intrinsic to
    IoU, never used to select evaluation pixels. Disocclusion requires an
    explicit BASE/oracle mask in current coordinates using background/world
    correspondence; comparing consecutive local crops would be incorrect.
    Without that witness the disocclusion statistic is null. No converged
    truth is inferred.
    """
    values, truth = np.asarray(values, float), np.asarray(truth, float)
    true_mask = np.asarray(true_mask, bool)
    if values.ndim != 3 or any(size == 0 for size in values.shape):
        raise ValueError("A nonempty T x H x W sequence is required")
    if values.shape != truth.shape or truth.shape != true_mask.shape:
        raise ValueError("values/truth/mask extents differ")
    if universe is None:
        universe = np.ones_like(true_mask)
    universe = np.asarray(universe, bool)
    if universe.shape != values.shape or not universe.any() or not np.isfinite(values[universe]).all() or not np.isfinite(truth[universe]).all():
        raise ValueError("Fixed evaluation universe and finite samples required")
    n, h, w = values.shape
    if np.asarray(centres).shape != (n,2) or np.asarray(velocity).shape != (n,2) or not np.isfinite(np.r_[centres,velocity]).all():
        raise ValueError("Finite T x 2 trajectories are required")
    if disocclusion_mask is not None:
        disocclusion_mask=np.asarray(disocclusion_mask,bool)
        if disocclusion_mask.shape != values.shape:
            raise ValueError("Disocclusion mask must have the fixed sequence extent")
    yy, xx = np.mgrid[:h, :w]
    rows=[]
    normalized = np.zeros_like(values)
    for t in range(n):
        region=universe[t]; target=true_mask[t] & region
        truth_energy=float(truth[t][region].sum())
        denom=max(truth_energy,float(np.sum(truth[universe])/n),1e-12)
        total=max(float(values[t][region].sum()),1e-12)
        normalized[t]=values[t]*truth_energy/total
        predicted=(values[t]>threshold)&region
        norm_pred=(normalized[t]>threshold)&region
        union=np.count_nonzero(target|predicted)
        norm_union=np.count_nonzero(target|norm_pred)
        vx,vy=np.asarray(velocity[t],float); speed=np.hypot(vx,vy)
        direction=np.array([vx,vy])/speed if speed>1e-12 else np.array([0.,0.])
        signed=(xx-centres[t,0])*direction[0]+(yy-centres[t,1])*direction[1]
        outside=region & ~true_mask[t]
        ahead=outside & (signed>0); behind=outside & (signed<0)
        if predicted.any() and target.any() and speed>1e-12:
            pc=np.array([xx[predicted].mean(),yy[predicted].mean()])
            tc=np.array([xx[target].mean(),yy[target].mean()])
            lag=float(np.dot(tc-pc,direction))
        else: lag=None
        if norm_pred.any() and target.any() and speed>1e-12:
            pc=np.array([xx[norm_pred].mean(),yy[norm_pred].mean()])
            tc=np.array([xx[target].mean(),yy[target].mean()])
            matched_lag=float(np.dot(tc-pc,direction))
        else: matched_lag=None
        rows.append({"frame":t,"evaluation_pixels":int(region.sum()),"truth_support_pixels":int(target.sum()),
            "shape_iou":float(np.count_nonzero(target&predicted)/union) if union else None,
            "level_matched_shape_iou":float(np.count_nonzero(target&norm_pred)/norm_union) if norm_union else None,
            "occupancy_lag_px":lag,
            "level_matched_occupancy_lag_px":matched_lag,
            "level_ratio":float(values[t][region].sum()/truth_energy) if truth_energy>0 else None,
            "tail_behind_energy":float(values[t][behind].sum()/denom),
            "tail_ahead_energy":float(values[t][ahead].sum()/denom),
            "signed_tail_energy":float((values[t][behind].sum()-values[t][ahead].sum())/denom),
            "offsupport_energy":float(values[t][outside].sum()/denom),
            "disocclusion_leakage":float(values[t][region & disocclusion_mask[t]].sum()/denom) if t and disocclusion_mask is not None else None})
    residual=values-truth
    fixed=universe&true_mask
    gradient=(np.abs(residual[:,:,1:]-residual[:,:,:-1]))
    gradient_mask=fixed[:,:,1:]&fixed[:,:,:-1]
    temporal=residual[1:]-residual[:-1]
    temporal_mask=universe[1:]&universe[:-1]
    metrics={key:_mean_or_none([row[key] for row in rows if row[key] is not None]) for key in rows[0] if key not in ("frame","evaluation_pixels","truth_support_pixels")}
    metrics.update({"grain_gradient_error":_mean_or_none(gradient[gradient_mask]),
                    "sparkle_p99_absolute_error":float(np.quantile(np.abs(residual[universe]),.99)),
                    "temporal_flicker_residual_rms":float(np.sqrt(np.mean(temporal[temporal_mask]**2))) if temporal_mask.any() else None,
                    "fixed_evaluation_pixels":int(universe.sum()),
                    "fixed_support_pixels":int(fixed.sum())})
    if detail_mask is not None:
        mask=np.asarray(detail_mask,bool)
        if mask.shape != values.shape:
            raise ValueError("Detail mask extent mismatch")
        dx=values[:,:,1:]-values[:,:,:-1]; target_dx=truth[:,:,1:]-truth[:,:,:-1]
        edge=mask[:,:,1:]&mask[:,:,:-1]
        reference=float(np.abs(target_dx[edge]).sum())
        metrics["retained_detail_ratio"]=float(np.abs(dx[edge]).sum()/reference) if reference>0 else None
        metrics["detail_error_mae"]=_mean_or_none(np.abs((values-truth)[mask]))
    return {"summary":metrics,"frames":rows}


def confidence_interval(samples, seed=717, draws=2000):
    """Percentile bootstrap across independent seeds, never across correlated pixels."""
    a=np.asarray(samples,float)
    if a.size<2 or not np.isfinite(a).all():
        return {"mean":float(a[0]) if a.size==1 else None,"ci95":None,"independent_seeds":int(a.size)}
    rng=np.random.default_rng(seed)
    means=a[rng.integers(0,len(a),size=(draws,len(a)))].mean(axis=1)
    return {"mean":float(a.mean()),"ci95":[float(x) for x in np.quantile(means,[.025,.975])],"independent_seeds":int(a.size)}
