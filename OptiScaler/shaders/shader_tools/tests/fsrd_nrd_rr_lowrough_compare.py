"""Strict B46/B80 sensitivity on one positive-r80 physical GGX history.

Reuses the frozen native executable and all unchanged wrapper/Consumer tests.
Default/--analyze-existing are CPU only. --run requires a parent GPU grant and
the shared lead_ops wrapper. No compiler or production change is performed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

import fsrd_nrd_rr_ggx_audit_compare as audit
import fsrd_nrd_rr_ggx_compare as baseline
import fsrd_nrd_rr_ggx_uncertainty as uncertainty
import fsrd_nrd_rr_ggx_views as domain
import fsrd_nrd_rr_lowrough_guides as guides
import fsrd_nrd_rr_material_compare as native_common
import fsrd_nrd_rr_material_quality as sealed


def identity(manifest):
    return 'demod-b' + str(manifest['guide_roughness_code'])


def paired(cases, output):
    completed = json.loads((output / 'comparison.json').read_bytes())
    by_code = {manifest['guide_roughness_code']: (case, manifest) for case, manifest in cases}
    common_case = Path(by_code[80][1]['common_demod_case'])
    domain.need(all(Path(manifest['common_demod_case']) == common_case for _, manifest in cases), 'both candidates use the same once-demodulated parent')
    physical_case = Path(by_code[80][1]['physical_case'])
    physical_manifest = json.loads((physical_case / 'ggx-sequence.json').read_bytes())
    frames, rows = [], {46: [], 80: []}
    for index, frame in enumerate(by_code[80][1]['frames']):
        physical = domain.load_frame(physical_case, physical_manifest, physical_manifest['frames'][index],
            ('reference_spec_a', 'reference_spec_b'))
        data = domain.load_frame(by_code[80][0], by_code[80][1], frame, ('spec_albedo',))
        qs = data['spec_albedo'][..., :3].astype(np.float64) / 255.
        values = {}
        for code in (46, 80):
            key = 'demod-b' + str(code)
            path = output / key / frame['directory'] / 'spec.bin'
            domain.need(sealed.file_sha(path) == completed['native_runs']['runs'][key]['outputs'][str(frame['frame'])]['spec'], 'actual signed output integrity before paired guide scoring')
            values[code] = np.fromfile(path, '<f2').reshape(128, 128, 4)[..., :3].astype(np.float64) * qs
        a, b = physical['reference_spec_a'], physical['reference_spec_b']
        metric = uncertainty.paired_mse(values[80], values[46], a, b, by_code[80][1]['comparison_crop'])
        frames.append(dict(frame=frame['frame'], raw80_minus_mapped46_spec_paired_mse=metric))
        x, y, width, height = by_code[80][1]['comparison_crop']
        crop = np.s_[y:y + height, x:x + width]
        for code in (46, 80):
            rows[code].append(audit.gradients(values[code][crop], a[crop], b[crop]))
    result = dict(schema='fsrd-positive-lowroughness-guide-v6-paired',
        raw80_minus_mapped46_spec_paired_mse=uncertainty.summarize_paired([row['raw80_minus_mapped46_spec_paired_mse'] for row in frames]),
        split_reference_gradients={str(code): audit.summarize(values) for code, values in rows.items()},
        physical_roughness_code=80, supplied_guide_codes=[46, 80], all_other_native_inputs_bit_identical=True,
        original_comparison_sha256=sealed.file_sha(output / 'comparison.json'), frames=frames,
        raw_native_perceptual_semantics_proved=False, zero_roughness_used=False, production_change=False,
        checks=domain.CHECKS, payload_integrity_checks=sealed.CHECKS,
        scope='strictly positive guide mismatch hypothesis, same fixed physicalRGB/A/Qs/reference/noise/history; no native rawA convention or in-game quality claim')
    sealed.write_json(output / 'guide-paired-comparison.json', result)
    print(json.dumps({key: value for key, value in result.items() if key != 'frames'}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared', type=Path, default=native_common.TASK / 'ggx-lowrough-guides-v6')
    parser.add_argument('--output', type=Path, default=native_common.TASK / 'ggx-lowrough-rr-run1')
    parser.add_argument('--native-exe', type=Path)
    parser.add_argument('--native-exe-sha')
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--analyze-existing', action='store_true')
    args = parser.parse_args()
    cases = [(args.prepared / ('guide-b' + str(code)), guides.validate(args.prepared / ('guide-b' + str(code)))) for code in (46, 80)]
    # Explicit research naming adapter only; original baseline source/validation
    # and old r123/r307 results remain unchanged.
    baseline.identity = identity
    if args.run:
        domain.need(args.native_exe is not None, 'explicit prebuilt signed-wrapper fixture, no compiler fallback')
        baseline.execute(cases, args.output, args.native_exe, args.native_exe_sha)
    if args.run or args.analyze_existing:
        baseline.compare(cases, args.output)
        paired(cases, args.output)
    else:
        print(json.dumps(dict(checks=domain.CHECKS, sealed_payload_checks=sealed.CHECKS,
            supplied_positive_codes=[46, 80], physical_code=80, gpu_executed=False, compiler_executed=False), indent=2))
