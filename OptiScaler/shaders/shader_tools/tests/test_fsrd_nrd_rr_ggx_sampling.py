"""Independent scalar, PDF/BRDF and energy tests of positive-roughness V5 math."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

import fsrd_nrd_rr_ggx_sampling as ggx
import fsrd_nrd_rr_material_quality as sealed


def run(output):
    checks = 0
    def need(value, description):
        nonlocal checks
        checks += 1
        if not bool(value):
            raise AssertionError(description)
    seed = np.random.default_rng(0x15C5001)
    rows = []
    for code in (123, 307):
        roughness, alpha = code / 1023., (code / 1023.) ** 2
        xi = seed.random((400, 2))
        cosine = seed.uniform(.7, 1., 400)
        phi = seed.uniform(0., 2. * np.pi, 400)
        local_v = np.stack((np.sqrt(1. - cosine * cosine) * np.cos(phi),
                            np.sqrt(1. - cosine * cosine) * np.sin(phi), cosine), axis=-1)
        world_v = local_v @ ggx.BASIS
        for routine in (ggx.bounded_vndf, ggx.ndf_reference):
            values = routine(world_v, roughness, xi)
            need(np.max(np.abs(np.linalg.norm(values['direction'], axis=-1) - 1.)) < 5e-16, 'stochastic outgoing vectors normalized')
            need(np.isfinite(values['weight']).all() and np.all(values['weight'] >= 0), 'physical contribution weights finite/nonnegative')
            for i in range(len(xi)):
                nh, nl, nv = float(values['no_h'][i]), float(values['no_l'][i]), float(values['no_v'][i])
                independent_d = 1. / (math.pi * alpha * alpha * ((1. - nh * nh) / (alpha * alpha) + nh * nh) ** 2)
                need(abs(float(ggx.ggx_ndf(nh, alpha)) / independent_d - 1.) < 2e-12, 'independent scalar GGX NDF alpha-squared convention')
                visibility = 0. if nl <= 0 else .5 / (nl * math.sqrt(nv * nv * (1. - alpha * alpha) + alpha * alpha) +
                    nv * math.sqrt(nl * nl * (1. - alpha * alpha) + alpha * alpha))
                target = independent_d * visibility * max(nl, 0.) / float(values['pdf'][i])
                if float(values['vo_h'][i]) <= 0:
                    target = 0.
                need(abs(target - float(values['weight'][i])) < 2e-12, 'physical BRDF*cos/pdf matches independent scalar evaluation')
        # At normal incidence the integrand is azimuth-independent. A midpoint
        # uniform sequence avoids a stochastic tolerance; the independently
        # derived solid-angle quadrature is checked at two orders as well.
        count = 262144
        uniform = np.stack((np.full(count, .375), (np.arange(count) + .5) / count), axis=-1)
        view = np.broadcast_to(ggx.NORMAL, (count, 3))
        bounded = float(np.mean(ggx.bounded_vndf(view, roughness, uniform)['weight']))
        ndf = float(np.mean(ggx.ndf_reference(view, roughness, uniform)['weight']))
        quadrature512 = ggx.normal_incidence_quadrature(roughness, 512)
        quadrature1024 = ggx.normal_incidence_quadrature(roughness, 1024)
        need(abs(quadrature1024 - quadrature512) < 2e-8, 'independent hemisphere quadrature converged')
        need(abs(bounded - quadrature1024) < 2e-5, 'bounded VNDF estimator equals independent constant-environment physical integral')
        need(abs(ndf - quadrature1024) < 2e-5, 'independent NDF estimator equals physical hemisphere integral')
        need(0. < bounded <= 1. and 0. < ndf <= 1., 'single-scatterF1 directional albedo conserves energy')
        correct_peak, demo_peak = float(ggx.ggx_ndf(1., alpha)), float(ggx.sdk_demo_ndf(1., alpha))
        need(abs(correct_peak / demo_peak - 1. / alpha) < 1e-10, 'local demo alpha/PDF mismatch retained as explicit diagnostic')
        rows.append(dict(roughness=roughness, alpha=alpha, bounded_constant_environment=bounded,
            independent_ndf_constant_environment=ndf, hemisphere_quadrature512=quadrature512,
            hemisphere_quadrature1024=quadrature1024, correct_ndf_peak=correct_peak,
            sdk_demo_ndf_peak=demo_peak, sdk_demo_trace_weight='.5/pdf, not the physical D*SmithVisibility*NoL/pdf estimator'))
    for invalid in (0., .08):
        try:
            ggx.bounded_vndf(np.array([0., 0., 1.]), invalid, np.array([.1, .2]))
        except ValueError:
            need(True, 'zero/SDK mirror shortcut excluded from genuine positive-roughness fixture')
        else:
            need(False, 'mirror shortcut must fail closed in this fixture')
    result = dict(schema='fsrd-positive-ggx-sampling-properties-v1', checks=checks,
        rows=rows, gpu_executed=False, compiler_executed=False,
        production_changes=False, reference_uses_different_sampling_algorithm=True)
    sealed.write_json(output, result)
    print(json.dumps(result, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('E:/FSRD/sol_batch/15c-rr/ggx-sampling-properties.json'))
    run(parser.parse_args().output)


if __name__ == '__main__':
    main()
