"""Safe CPU alternative: same-surface spatial bands and per-surface DC.

Each axis window replicates the nearest boundary of its same-surface segment.
Temporal signed moments are unchanged; current material/certificate eligibility
can only remove a contributor, never introduce raw or Skip color as a witness.
"""
from dataclasses import dataclass
import numpy as np
from fsrd_recovery_detail_reference import PairedBandMoments, identity_taps


def segments(same, extent, axis):
    shape = list(same.shape)
    shape[axis] += 1
    index = np.broadcast_to(np.arange(extent).reshape((1, extent) if axis == 1 else (extent, 1)), shape)
    left_break = np.concatenate((np.ones((shape[0], 1), bool), ~same), 1) if axis == 1 else \
                 np.concatenate((np.ones((1, shape[1]), bool), ~same), 0)
    right_break = np.concatenate((~same, np.ones((shape[0], 1), bool)), 1) if axis == 1 else \
                  np.concatenate((~same, np.ones((1, shape[1]), bool)), 0)
    start = np.maximum.accumulate(np.where(left_break, index, 0), axis=axis)
    reverse = (slice(None), slice(None, None, -1)) if axis == 1 else (slice(None, None, -1), slice(None))
    end = np.minimum.accumulate(np.where(right_break, index, extent-1)[reverse], axis=axis)[reverse]
    return start, end


def axis_box(values, radius, bounds, axis):
    if radius == 0:
        return np.asarray(values, np.float32)
    values = np.asarray(values, np.float64)
    start, end = bounds
    h, w = start.shape
    y, x = np.indices((h, w))
    index = x if axis == 1 else y
    low = np.maximum(index-radius, start)
    high = np.minimum(index+radius, end)
    padding = [(0, 0)]*values.ndim
    padding[axis] = (1, 0)
    prefix = np.pad(values.cumsum(axis), padding)
    low_sum = prefix[y, low] if axis == 1 else prefix[low, x]
    high_sum = prefix[y, high+1] if axis == 1 else prefix[high+1, x]
    first = values[y, start] if axis == 1 else values[start, x]
    last = values[y, end] if axis == 1 else values[end, x]
    tail = (None,)*(values.ndim-2)
    missing_low = np.maximum(radius-index+start, 0)[(...,)+tail]
    missing_high = np.maximum(index+radius-end, 0)[(...,)+tail]
    return ((high_sum-low_sum+missing_low*first+missing_high*last)/(2*radius+1)).astype(np.float32)


class GeometryObservations:
    def __init__(self, depth, normal):
        depth = np.asarray(depth, np.float32)
        normal = np.asarray(normal, np.float32)
        h, w = depth.shape
        self.valid = np.isfinite(depth) & (abs(depth) > 1e-5) & np.all(np.isfinite(normal), -1)
        def same(a, b):
            return self.valid[a] & self.valid[b] & \
                (abs(depth[a]-depth[b]) <= .03*np.maximum(np.minimum(abs(depth[a]), abs(depth[b])), .001)) & \
                ((normal[a]*normal[b]).sum(-1) > .95)
        horizontal = same((slice(None), slice(None, -1)), (slice(None), slice(1, None)))
        vertical = same((slice(None, -1), slice(None)), (slice(1, None), slice(None)))
        self.x_bounds = segments(horizontal, w, 1)
        self.y_bounds = segments(vertical, h, 0)
        # Exact connected surfaces in the reference, not arbitrary rectangular
        # tiles. The production GPU labeling/neutralization cost is still pending.
        from scipy.sparse import coo_matrix
        from scipy.sparse.csgraph import connected_components
        ids = np.arange(h*w, dtype=np.int32).reshape(h, w)
        rows = np.concatenate((ids[:, :-1][horizontal], ids[:-1][vertical]))
        cols = np.concatenate((ids[:, 1:][horizontal], ids[1:][vertical]))
        graph = coo_matrix((np.ones(rows.size, np.uint8), (rows, cols)), shape=(h*w, h*w))
        self.count, labels = connected_components(graph, directed=False, return_labels=True)
        self.labels = labels.reshape(h, w)

    def box(self, values, radius):
        return axis_box(axis_box(values, radius, self.x_bounds, 1), radius, self.y_bounds, 0)

    def band(self, values, small, large):
        return self.box(values, small)-self.box(values, large)

    def neutral(self, raw, mask, base):
        mask = np.asarray(mask, bool) & np.isfinite(raw) & np.isfinite(base) & (base > 0)
        value = np.where(mask, raw, 0).astype(np.float32)
        labels = self.labels.ravel()
        for channel in range(3):
            count = np.bincount(labels, weights=mask[..., channel].ravel(), minlength=self.count)
            total = np.bincount(labels, weights=value[..., channel].ravel(), minlength=self.count)
            offset = (total/np.maximum(count, 1))[self.labels]
            value[..., channel] -= mask[..., channel]*offset
            value[..., channel] = np.where(count[self.labels] >= 4, value[..., channel], 0)
        negative = value < 0
        scale = min(1., float(np.min(base[negative]/-value[negative]))) if negative.any() else 1.
        value *= max(0., scale)
        return value, scale


class GeometryState:
    """Static-identity safety adapter; real capture replay uses original mapping."""
    def __init__(self, gate, width, height):
        self.gate, self.shape = gate, (height, width)
        self.states = [PairedBandMoments(self.shape, 1, .1) for _ in range(2)]
        self.previous_available = [np.zeros((*self.shape, 3), bool) for _ in range(2)]
        self.valid = False
        self.old_depth = np.zeros(self.shape, np.float32)
        self.old_normal = np.zeros((*self.shape, 3), np.float32)

    def step(self, signals, denoised, albedo, base, depth, normal, motion,
             strengths=(1., 1.), reset=False, eligibility=None, **unused):
        from fsrd_recovery_detail_gpu import stored
        h, w = self.shape
        base = np.asarray(base[:h, :w], np.float16).astype(np.float32)
        depth = np.asarray(depth[:h, :w], np.float32)
        normal = self.gate.decode_normals(stored(normal[:h, :w], 24)).astype(np.float32)
        geometry = GeometryObservations(depth, normal)
        reuse = (self.valid and not reset) & geometry.valid & np.isfinite(self.old_depth) & \
            (abs(depth-self.old_depth) <= .03*np.maximum(abs(depth), .001)) & \
            ((normal*self.old_normal).sum(-1) > .95)
        correction = np.zeros((*self.shape, 3), np.float32)
        for index in range(2):
            guide = np.asarray(albedo[index][:h, :w, :3], np.float32)
            guide = guide/255. if albedo[index].dtype == np.uint8 else \
                    np.rint(np.clip(guide, 0, 1)*255).astype(np.float32)/255.
            available = np.isfinite(guide) & (guide > 0)
            if eligibility is not None:
                veto = np.asarray(eligibility[index], bool)[:h, :w]
                available &= veto[..., None] if veto.ndim == 2 else veto
            changed = np.any(available != self.previous_available[index], -1)
            lobe_reuse = reuse & ~changed
            signal = np.asarray(signals[index][:h, :w, :3], np.float16).astype(np.float32)
            rr = np.asarray(denoised[index][:h, :w, :3], np.float16).astype(np.float32)
            observed = geometry.band(np.where(available, (signal-rr)*guide, 0), 3, 40)[None]
            state = self.states[index]
            _, noise = state.update(observed, identity_taps(h, w), lobe_reuse)
            raw = strengths[index]*state.correction(noise, lobe_reuse, 2., "soft", 8.)[0]
            value, _ = geometry.neutral(raw, available, base[..., :3])
            correction += value
            self.previous_available[index] = available
        negative = correction < 0
        scale = min(1., float(np.min(base[..., :3][negative]/-correction[negative]))) if negative.any() else 1.
        correction *= max(0., scale)
        output = base.copy(); output[..., :3] += correction
        self.valid = True
        self.old_depth, self.old_normal = depth.copy(), normal.copy()
        return output.astype(np.float16).astype(np.float32)
