"""CPU-only split-reference gradient and prespecified high-spp V5 audit.

These additional estimators retain the original comparison unchanged. The
cross-replica denominator estimates signal energy without the positive gradient
noise term of a finite-spp mean reference. Finite-sample uncertainty remains.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

import fsrd_nrd_rr_ggx_compare as replay
import fsrd_nrd_rr_ggx_oracle as oracle
import fsrd_nrd_rr_ggx_views as domain
import fsrd_nrd_rr_material_quality as sealed


def gradients(candidate, first, second, mask=None):
    totals = dict(pairs=0, cross_reference_energy=0., mean_reference_energy=0.,
                  split_reference_noise_energy=0., candidate_projection_numerator=0.)
    for axis in (0, 1):
        gc, ga, gb = [np.diff(np.asarray(value, np.float64), axis=axis)
                      for value in (candidate, first, second)]
        valid = np.ones(ga.shape[:-1], bool) if mask is None else np.diff(mask.astype(np.int16), axis=axis) == 0
        gc, ga, gb = gc[valid], ga[valid], gb[valid]
        mean = (ga + gb) * .5
        totals['pairs'] += int(valid.sum())
        totals['cross_reference_energy'] += float(np.sum(ga * gb))
        totals['mean_reference_energy'] += float(np.sum(mean * mean))
        totals['split_reference_noise_energy'] += float(np.sum((ga - gb) ** 2) * .25)
        totals['candidate_projection_numerator'] += float(np.sum(gc * mean))
    return totals


def summarize(rows):
    totals = {name: sum(row[name] for row in rows) for name in rows[0]}
    energy = totals['cross_reference_energy']
    totals['cross_reference_projection_ratio'] = totals['candidate_projection_numerator'] / energy if energy > 0. else None
    totals['mean_reference_projection_ratio'] = totals['candidate_projection_numerator'] / totals['mean_reference_energy']
    totals['finite_reference_gradient_noise_fraction'] = totals['split_reference_noise_energy'] / totals['mean_reference_energy']
    if len(rows) < 16:
        totals['all_bootstrap_cross_energies_positive'] = None
        totals['cross_reference_projection_block95_interval'] = None
        totals['block_uncertainty_unavailable'] = 'fixed4-frame high-spp audit has fewer than two8-frame blocks; no artificial degenerate confidence interval'
        return totals
    # Prespecified shared circular blocks; report ratios only when denominator
    # remains positive in every resample, rather than clipping noisy energies.
    rng = np.random.default_rng(0x15C5B007)
    starts = rng.integers(0, len(rows), size=(2000, (len(rows) + 7) // 8))
    indices = ((starts[..., None] + np.arange(8)) % len(rows)).reshape(2000, -1)[:, :len(rows)]
    denominator = np.sum(np.asarray([row['cross_reference_energy'] for row in rows])[indices], axis=1)
    numerator = np.sum(np.asarray([row['candidate_projection_numerator'] for row in rows])[indices], axis=1)
    totals['all_bootstrap_cross_energies_positive'] = bool(np.all(denominator > 0.))
    totals['cross_reference_projection_block95_interval'] = np.percentile(numerator / denominator, [2.5, 97.5]).tolist() if np.all(denominator > 0.) else None
    return totals


def source_independence():
    input_seeds = {oracle.INPUT_SEED + index for index in range(64)}
    reference_seeds = [{seed + index for index in range(64)} for seed in oracle.REFERENCE_SEEDS]
    ghost_seeds = [{seed + 0x100000 + index for index in range(64)} for seed in oracle.REFERENCE_SEEDS]
    sets = [input_seeds] + reference_seeds + ghost_seeds
    domain.need(all(not first.intersection(second) for index, first in enumerate(sets) for second in sets[index + 1:]),
                'all noisy/current-reference/historical-reference PRNG seed ranges are disjoint')
    return dict(input_seed=oracle.INPUT_SEED, reference_seeds=list(oracle.REFERENCE_SEEDS),
        input_map='independent default_rng(seed+frameIndex) random128x128x2, boundedVNDF transform',
        reference_map='different seed ranges default_rng(seed+frameIndex) per-pixel shifts of deterministic2/3radical-inverse points, independent NDF transform',
        common_samples_copied=False, disjoint_seed_ranges=True,
        limitation='different seeded pseudorandom streams and different maps; not a mathematical proof of infinite-stream statistical independence')


def evaluate(cases, completed, audit_root, output):
    runs = json.loads((completed / 'runs.json').read_bytes())
    audit = json.loads((audit_root / 'audit.json').read_bytes())
    audit_cases = {Path(row['case']).name: row for row in audit['rows']}
    coordinates = audit['fixed_pixel_coordinates']
    ys, xs = np.meshgrid(coordinates, coordinates, indexing='ij')
    summaries, all_frames = {}, {}
    for case in cases:
        manifest = replay.validate(case)
        key = replay.identity(manifest)
        native = runs['runs'][key]
        domain.need(sealed.file_sha(case / 'ggx-sequence.json') == native['input_manifest_sha256'], 'signed immutable case identity')
        physical_case = Path(manifest.get('physical_case', case))
        physical_manifest = json.loads((physical_case / 'ggx-sequence.json').read_bytes())
        high_case = audit_cases[physical_case.name]
        domain.need(sealed.file_sha(physical_case / 'ggx-sequence.json') == high_case['manifest_sha256'], 'high-spp audit belongs to the same frozen physical scene')
        high_frames = {row['frame']: row for row in high_case['frames']}
        rows, high_rows = [], []
        for index, frame in enumerate(manifest['frames']):
            physical = domain.load_frame(physical_case, physical_manifest, physical_manifest['frames'][index],
                ('reference_spec_a', 'reference_spec_b', 'object'))
            data = domain.load_frame(case, manifest, frame, ('spec', 'spec_albedo'))
            path = completed / key / frame['directory'] / 'spec.bin'
            domain.need(sealed.file_sha(path) == native['outputs'][str(frame['frame'])]['spec'], 'signed output SHA before additional CPU audit')
            output_rgb = np.fromfile(path, '<f2').reshape(128, 128, 4)[..., :3].astype(np.float64)
            factor = data['spec_albedo'][..., :3].astype(np.float64) / 255. if manifest['schema'] == domain.DEMOD_SCHEMA else 1.
            values = dict(noisy_input=data['spec'][..., :3] * factor, signed_rr=output_rgb * factor)
            a, b = physical['reference_spec_a'], physical['reference_spec_b']
            x, y, width, height = manifest['comparison_crop']
            crop = np.s_[y:y + height, x:x + width]
            frame_stats = {}
            for name, value in values.items():
                frame_stats[name] = {region: gradients(value[crop], a[crop], b[crop], mask)
                    for region, mask in (('original_crop', None), ('same_primary_surface', physical['object'][crop]))}
            rows.append(dict(frame=frame['frame'], gradients=frame_stats,
                reference_split_rgb_rmse=float(np.sqrt(np.mean((a[crop].astype(np.float64) - b[crop]) ** 2))),
                rr_to_mean_reference_rgb_rmse=float(np.sqrt(np.mean((values['signed_rr'][crop] - (a[crop].astype(np.float64) + b[crop]) * .5) ** 2)))))
            if frame['frame'] in high_frames:
                high = [sealed.load(audit_root, info['payload']).astype(np.float64) for info in high_frames[frame['frame']]['high_reference_replicas']]
                per_method = {}
                for name, value in values.items():
                    v = value[ys, xs]
                    per_method[name] = dict(rgb_rmse_against_a=float(np.sqrt(np.mean((v - high[0]) ** 2))),
                        rgb_rmse_against_b=float(np.sqrt(np.mean((v - high[1]) ** 2))),
                        rgb_rmse_against_mean=float(np.sqrt(np.mean((v - (high[0] + high[1]) * .5) ** 2))),
                        gradients=gradients(v, high[0], high[1]))
                high_rows.append(dict(frame=frame['frame'], methods=per_method,
                    high_split_rgb_rmse=high_frames[frame['frame']]['high_split_rgb_rmse'],
                    low_minus_high_rmse=high_frames[frame['frame']]['low_mean_minus_high_mean_rgb_rmse']))
        summary = {name: {region: summarize([row['gradients'][name][region] for row in rows])
            for region in ('original_crop', 'same_primary_surface')} for name in ('noisy_input', 'signed_rr')}
        summaries[key] = dict(full_crop_gradients=summary, high_spp_fixed_spatial_rows=high_rows,
            high_spp_coarse_gradients={name: summarize([row['methods'][name]['gradients'] for row in high_rows]) for name in ('noisy_input', 'signed_rr')},
            mean_frame_split_reference_rgb_rmse=float(np.mean([row['reference_split_rgb_rmse'] for row in rows])),
            mean_frame_rr_to_mean_reference_rgb_rmse=float(np.mean([row['rr_to_mean_reference_rgb_rmse'] for row in rows])))
        all_frames[key] = rows
    result = dict(schema=oracle.SCHEMA + '-additional-reference-audit', source_sha256=sealed.file_sha(Path(__file__)),
        signed_runs_sha256=sealed.file_sha(completed / 'runs.json'), audit_sha256=sealed.file_sha(audit_root / 'audit.json'),
        source_independence=source_independence(), cases=summaries, frames=all_frames,
        checks=domain.CHECKS, payload_integrity_checks=sealed.CHECKS, gpu_executed=False,
        original_metrics_changed=False, zero_roughness_used=False,
        scope='analysis-only split-reference signal-energy estimate and prespecified64points×4frames32768spp audit; no local98percent-detail-loss inference or native-title quality verdict')
    sealed.write_json(output, result)
    print(json.dumps(dict(output=str(output), checks=result['checks'], payload_integrity_checks=result['payload_integrity_checks'],
        cases={key: value['full_crop_gradients']['signed_rr']['original_crop'] for key, value in summaries.items()}), indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', type=Path, action='append', required=True)
    parser.add_argument('--completed', type=Path, default=Path('F:/FSRD/sol_batch/15c-rr/ggx-v5-rr-run1'))
    parser.add_argument('--audit', type=Path, default=Path('E:/FSRD/sol_batch/15c-rr/ggx-reference-audit-1'))
    parser.add_argument('--output', type=Path, default=Path('E:/FSRD/sol_batch/15c-rr/ggx-v5-reference-output-audit.json'))
    args = parser.parse_args()
    evaluate(args.case, args.completed, args.audit, args.output)
