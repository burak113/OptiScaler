"""Synthetic-domain divide/opaqueA and two-reference paired-analysis tests."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

import fsrd_nrd_rr_ggx_views as views
import fsrd_nrd_rr_ggx_uncertainty as uncertainty
import fsrd_nrd_rr_material_quality as sealed


def run(output):
    checks = 0
    def need(condition, message):
        nonlocal checks
        checks += 1
        if not bool(condition):
            raise AssertionError(message)
    rng = np.random.default_rng(0x15C5D001)
    rgba = rng.uniform(0., 4., (128, 128, 4)).astype('<f2')
    alpha = np.array([0x0000, 0x8000, 0x3c00, 0xbc00, 0x0001, 0x7bff], '<u2').view('<f2')
    rgba[..., 3] = np.resize(alpha, (128, 128))
    original = rgba.copy()
    qs = rng.uniform(.8, 1., (128, 128, 3))
    derived, error = views.divide_physical(rgba, qs)
    need(np.array_equal(rgba.view('<u2'), original.view('<u2')), 'physical input never edited in place')
    need(np.array_equal(np.ascontiguousarray(derived[..., 3]).view('<u2'), np.ascontiguousarray(original[..., 3]).view('<u2')), 'all finite active/inactive/signedzero/subnormal/max alpha words exact')
    expected = (original[..., :3].astype(np.float64) / qs).astype('<f2')
    need(np.array_equal(derived[..., :3], expected), 'exactly one division and nearest-half storage')
    identity, _ = views.divide_physical(rgba, np.ones_like(qs))
    need(np.array_equal(identity.view('<u2'), rgba.view('<u2')), 'unit guide is exact identity')
    try:
        views.divide_physical(rgba, np.zeros_like(qs))
    except AssertionError:
        need(True, 'zero albedo cannot be hidden by epsilon denominator')
    else:
        need(False, 'zero denominator must fail closed')
    reference_a = rng.uniform(0., 1., (128, 128, 3))
    reference_b = reference_a + rng.normal(0., .001, reference_a.shape)
    exact = uncertainty.paired_mse(reference_a, reference_a, reference_a, reference_b)
    need(exact['a']['candidate_minus_baseline_mse'] == exact['b']['candidate_minus_baseline_mse'] == 0., 'identical candidates cannot win below reference uncertainty')
    constant = uncertainty.summarize_paired([exact] * 64)
    need(not constant['supported_by_measured_replicas_and_blocks'], 'zero change not advertised as an improvement')
    winner = uncertainty.paired_mse(reference_a, reference_a + .1, reference_a, reference_b)
    stats = uncertainty.summarize_paired([winner] * 64)
    need(stats['same_lower_mse_winner_both_replicas'] and stats['both_block_intervals_below_zero'], 'strong paired winner survives both references and fixed bootstrap')
    midpoint = (reference_a + reference_b) * .5
    ambiguous = uncertainty.paired_mse(reference_a, reference_b, reference_a, reference_b)
    ambiguous_stats = uncertainty.summarize_paired([ambiguous] * 64)
    need(not ambiguous_stats['supported_by_measured_replicas_and_blocks'], 'opposite-reference winners remain unresolved')
    need(np.all(np.isfinite(midpoint)), 'reference arithmetic finite')
    result = dict(checks=checks, adapter_checks=views.CHECKS, max_abs_quantization_error=error['max_abs_roundtrip_error'],
        gpu_executed=False, compiler_executed=False, production_changes=False)
    sealed.write_json(output, result)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('E:/FSRD/sol_batch/15c-rr/ggx-domain-properties.json'))
    run(parser.parse_args().output)
