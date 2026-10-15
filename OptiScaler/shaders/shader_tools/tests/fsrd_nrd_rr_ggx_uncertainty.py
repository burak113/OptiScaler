"""Paired two-reference MSE sensitivity and fixed temporal block bootstrap.

Analysis only: reference/age/truth never drives a denoising/recovery gate.
Two replicas plus finite spatial audit remain evidence, not exact ground truth.
"""
from __future__ import annotations

import numpy as np


def paired_mse(candidate, baseline, reference_a, reference_b, crop=(16, 16, 96, 96)):
    x, y, width, height = crop
    sl = np.s_[y:y + height, x:x + width, :3]
    a = np.asarray(candidate, np.float64)[sl]
    b = np.asarray(baseline, np.float64)[sl]
    refs = [np.asarray(reference, np.float64)[sl] for reference in (reference_a, reference_b)]
    result = {}
    for index, reference in enumerate(refs):
        mse_candidate = float(np.mean((a - reference) ** 2))
        mse_baseline = float(np.mean((b - reference) ** 2))
        # The shared reference-squared term cancels, retaining paired evidence.
        delta = float(np.mean((a - b) * (a + b - 2. * reference)))
        result['ab'[index]] = dict(candidate_mse=mse_candidate, baseline_mse=mse_baseline,
                                 candidate_minus_baseline_mse=delta)
    result['replica_pair_delta_difference'] = abs(result['a']['candidate_minus_baseline_mse'] - result['b']['candidate_minus_baseline_mse'])
    result['reference_split_rgb_rmse'] = float(np.sqrt(np.mean((refs[0] - refs[1]) ** 2)))
    return result


def summarize_paired(frames, block_length=8, repeats=2000, seed=0x15C5B007):
    if len(frames) != 64 or block_length != 8 or repeats != 2000:
        raise ValueError('fixed prespecified64-frame/8-frame circular-block/2000draws analysis')
    deltas = np.array([[frame[name]['candidate_minus_baseline_mse'] for name in ('a', 'b')] for frame in frames])
    starts = np.random.default_rng(seed).integers(0, len(frames), (repeats, len(frames) // block_length))
    indices = ((starts[..., None] + np.arange(block_length)) % len(frames)).reshape(repeats, len(frames))
    draws = np.mean(deltas[indices], axis=1)
    rows = {}
    for index, name in enumerate(('a', 'b')):
        rows[name] = dict(mean_paired_mse_delta=float(np.mean(deltas[:, index])),
            circular_block95_percentile_interval=np.quantile(draws[:, index], [.025, .975]).tolist())
    same_winner = all(rows[name]['mean_paired_mse_delta'] < 0. for name in ('a', 'b'))
    both_ci = all(rows[name]['circular_block95_percentile_interval'][1] < 0. for name in ('a', 'b'))
    return dict(replicas=rows, shared_bootstrap_indices=True, block_length=block_length, repeats=repeats, seed=seed,
        negative_delta_means_lower_mse=True, same_lower_mse_winner_both_replicas=same_winner,
        both_block_intervals_below_zero=both_ci,
        absolute_mean_replica_sensitivity=float(abs(np.mean(deltas[:, 0] - deltas[:, 1]))),
        mean_frame_reference_split_rmse=float(np.mean([frame['reference_split_rgb_rmse'] for frame in frames])),
        supported_by_measured_replicas_and_blocks=bool(same_winner and both_ci),
        interpretation='two independently randomized finite references and fixed frame-block uncertainty; not a guarantee against unmeasured Monte Carlo or scene bias')
