"""Validate exported GPU material bytes; no compiler/GPU jobs in this module."""
from pathlib import Path
import hashlib
import numpy as np


def validate(directory, value):
    # Independent FP64 public-SDK rational/UNORM error intervals already tested
    # by the conversion fixture; no production shader arithmetic is imported.
    from test_fsrd_nrd_conversion import material_guide_bounds
    directory = Path(directory)
    trace = value['native_material_guides']
    checks = 0

    def require(condition):
        nonlocal checks
        assert bool(np.all(condition))
        checks += 1

    require(len(trace['frames']) == 7)
    require(trace['same_history_context'] and trace['noisy_rgb_alpha_unchanged'])
    require(trace['borrowed_source_bytes_exact'] and trace['borrowed_title_transitions'] == 0)
    require(trace['pixel_only_no_read'] and trace['later_writer_tombstone'])
    require(value['debug_errors'] == value['debug_warnings'] == 0)
    enabled = trace['enabled']
    require(trace['warm_snapshot_bytes'] > 0 if enabled else trace['warm_snapshot_bytes'] == 0)
    require(trace['coherent_cancel_recovery'] == enabled)
    old_applied = False
    alpha = None
    hashes = {}
    for frame in trace['frames']:
        n = frame['frame']
        prefix = directory / ('frame' + str(n))

        def load(suffix, dtype, shape):
            path = Path(str(prefix) + '-' + suffix + '.bin')
            raw = path.read_bytes()
            hashes[path.name] = hashlib.sha256(raw).hexdigest()
            require(len(raw) == np.prod(shape) * np.dtype(dtype).itemsize)
            return np.frombuffer(raw, dtype=dtype).reshape(shape)

        spec = load('spec-guide', 'u1', (128, 128, 4))
        diff = load('diff-guide', 'u1', (128, 128, 4))
        base = load('base', '<u4', (128, 128))
        params = load('params', 'u1', (128, 128, 4))
        nr = load('normal', '<u4', (128, 128))
        if alpha is None:
            alpha = spec[..., 3].copy()
        require(np.array_equal(spec[..., 3], alpha) and np.all(diff[..., 3] == 0))
        expected_applied = enabled and n in (3, 4, 6, 8)
        require(frame['material_applied'] == expected_applied and frame['snapshot'] == expected_applied)
        require(frame['reset'] == (n == 2 or (enabled and expected_applied != old_applied)))
        require(frame['active'])
        if expected_applied:
            material = load('snapshot', '<f2', (128, 128, 4))
            encoded = np.stack([(base >> shift) & 1023 for shift in (0, 10, 20)], -1).astype(np.float32) / np.float32(1023)
            expected = np.concatenate([(encoded * encoded).astype('<f2'),
                                       (params[..., :1].astype(np.float32) / np.float32(255)).astype('<f2')], -1)
            require(np.array_equal(material.view('<u2'), expected.view('<u2')))
            bounds = material_guide_bounds(dict(material=material, nr=nr), dict(spec_albedo=spec))
            for actual, interval in ((spec[..., :3] / 255, bounds['spec_bounds']),
                                     (diff[..., :3] / 255, bounds['diff_bounds'])):
                known = bounds['known'][..., None]
                require(np.where(known, actual >= interval[0], actual == 1))
                require(np.where(known, actual <= interval[1], actual == 1))
            require(np.any(spec[..., :3] != 255) and np.any(diff[..., :3] != 255))
            require(np.all(spec[..., :3][~bounds['known']] == 255) and np.all(diff[..., :3][~bounds['known']] == 255))
        else:
            require(np.all(spec[..., :3] == 255) and np.all(diff[..., :3] == 255))
        old_applied = expected_applied
    value['material_gpu_readback_sha256'] = hashes
    return checks
