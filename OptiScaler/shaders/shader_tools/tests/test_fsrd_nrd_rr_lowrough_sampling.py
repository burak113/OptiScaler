"""CPU-only independent positive-r80 calibration before expensive references."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

import fsrd_nrd_rr_ggx_sampling as frozen
import fsrd_nrd_rr_lowrough_sampling as low
import fsrd_nrd_rr_material_quality as sealed


def run(output):
    checks = 0
    rng = np.random.default_rng(0x15C680)
    xi = rng.random((1024, 2))
    view = np.broadcast_to(low.BASIS[2], (1024, 3))
    for roughness in (123 / 1023., 307 / 1023.):
        for name in ('bounded_vndf', 'ndf_reference'):
            first = getattr(frozen, name)(view, roughness, xi)
            second = getattr(low, name)(view, roughness, xi)
            for key in first:
                assert np.array_equal(first[key], second[key]), 'new positive-domain fork must retain every existing sampler result exactly'
                checks += 1
    for name in ('bounded_vndf', 'ndf_reference'):
        for roughness in (0., -.01, 1.01):
            try:
                getattr(low, name)(view, roughness, xi)
            except ValueError:
                checks += 1
            else:
                raise AssertionError('no zero/negative/mirror validation escape')
        try:
            getattr(frozen, name)(view, 80 / 1023., xi)
        except ValueError:
            checks += 1
        else:
            raise AssertionError('frozen V5 lower bound was changed')
    roughness = 80 / 1023.
    q2048 = low.normal_incidence_quadrature(roughness, 2048)
    q4096 = low.normal_incidence_quadrature(roughness, 4096)
    assert abs(q2048 - q4096) < 5e-6, 'independent hemisphere quadrature converges at this positive roughness'
    checks += 1
    points = np.stack((frozen.radical_inverse(np.arange(1, 262145), 2), frozen.radical_inverse(np.arange(1, 262145), 3)), axis=-1)
    means = {}
    for name in ('bounded_vndf', 'ndf_reference'):
        sample = getattr(low, name)(np.broadcast_to(low.BASIS[2], (len(points), 3)), roughness, points)
        assert all(np.isfinite(value).all() for value in sample.values()), 'all low-positive physical estimator fields finite'
        assert np.all(sample['weight'] >= 0.) and np.all(sample['weight'][sample['no_l'] <= 0.] == 0.), 'below-hemisphere probability retains zero BRDF contribution'
        assert np.max(np.abs(np.linalg.norm(sample['direction'], axis=-1) - 1.)) < 1e-12, 'actual path distance uses unit ray direction'
        value = float(np.mean(sample['weight']))
        assert abs(value - q4096) < 2e-5, 'different inverse maps agree with independent physical hemisphere integral'
        means[name] = value
        checks += 4
    result = dict(checks=checks, roughness=roughness, quadrature2048=q2048, quadrature4096=q4096,
        constant_environment_f1_means=means, frozen_sampler_sha256=sealed.file_sha(Path(frozen.__file__)),
        new_sampler_sha256=sealed.file_sha(Path(low.__file__)), gpu_executed=False, compiler_executed=False,
        zero_roughness_used=False, physical_raw_perceptual_hypothesis_only=True)
    sealed.write_json(output, result)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    run(Path('E:/FSRD/sol_batch/15c-rr/ggx-lowrough-sampling-properties-1.json'))
