"""Compare frozen V4 mirror guides through the prebuilt real signed-RR fixture.

Default and --analyze-existing are CPU only. --run requires an explicit lead
GPU slot and lead_ops/run_task_test.py, and never invokes any compiler.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import struct

import numpy as np

import fsrd_nrd_rr_material_compare as common
import fsrd_nrd_rr_material_quality as sealed
import fsrd_nrd_rr_mirror_oracle as mirror
import test_fsrd_nrd_rr_mirror_oracle as tests


def execute(prepared, manifest, output, executable, expected_sha):
    mirror.need(output.resolve().is_relative_to(mirror.BASE.resolve()) and not output.exists(),
                'fresh native output folder belongs to this task; keep every prior attempt')
    mirror.need(expected_sha and sealed.file_sha(executable) == expected_sha, 'explicit hash of already-built real-wrapper executable')
    mirror.need(sealed.file_sha(common.DLL) == common.DLL_SHA, 'exact installed signed AMD1.2 provider')
    output.mkdir(parents=True)
    probe = common.native(executable, Path(manifest['views']['mirror-r0']), output / 'defaults-probe')
    words = probe['effective_words']
    values = struct.unpack('<8f', struct.pack('<8I', *words))
    settings = output / 'common-effective-settings.txt'
    settings.write_text(' '.join(format(float(value), '.9g') for value in values) + '\n', encoding='ascii')
    runs = {}
    for candidate in mirror.CANDIDATES:
        view = Path(manifest['views'][candidate])
        native = common.native(executable, view, output / candidate, settings)
        mirror.need(native['effective_words'] == words and native['default_words'] == probe['default_words'],
                    'physically fresh contexts use exact same queried settings')
        native['outputs'] = {}
        for frame in manifest['frames']:
            native['outputs'][str(frame['frame'])] = {}
            folder = output / candidate / frame['directory']
            mirror.need(sealed.file_sha(folder / 'motion.bin') == sealed.file_sha(view / frame['directory'] / 'motion.bin'),
                        'actual selected primary/diagnostic motion words are exact GPU inputs')
            for signal, alpha in (('spec', .75), ('diff', 2.)):
                path = folder / (signal + '.bin')
                result = np.fromfile(path, '<f2').reshape(128, 128, 4)
                mirror.need(np.isfinite(result).all(), 'finite signed-RR committed RGBA')
                mirror.need(np.all(result[..., 3] == np.float16(alpha)), 'native destination alpha remains exact and opaque')
                native['outputs'][str(frame['frame'])][signal] = sealed.file_sha(path)
        sealed.write_json(output / candidate / 'native-result.json', native)
        runs[candidate] = native
    metadata = dict(schema='fsrd-mirror-control-signed-runs-v4',
        prepared_manifest_sha256=sealed.file_sha(prepared / 'mirror-sequence.json'),
        executable_sha256=expected_sha, provider_dll_sha256=common.DLL_SHA,
        probe=probe, runs=runs, checks=mirror.CHECKS, common_native_checks=sealed.CHECKS,
        compiler_executed=False, gpu_executed=True)
    sealed.write_json(output / 'runs.json', metadata)
    return metadata


def compare(prepared, manifest, completed, camera_source):
    run_info = json.loads((completed / 'runs.json').read_bytes())
    mirror.need(run_info['schema'] == 'fsrd-mirror-control-signed-runs-v4' and
                run_info['prepared_manifest_sha256'] == sealed.file_sha(prepared / 'mirror-sequence.json'),
                'completed real outputs belong to these exact V4 payloads')
    mirror.need(tuple(run_info['runs']) == mirror.CANDIDATES, 'both roughness rows and nonproduction diagnostic retained')
    original = sealed.original(Path('F:/FSRD/sol_batch/15e-quality/inputs'))
    oracle = sealed.reference_oracle(camera_source, original['generator_sha256'])
    rows = []
    for frame in manifest['frames']:
        folder = prepared / 'dataset' / frame['directory']
        data = {name: sealed.load(folder, record) for name, record in frame['payloads'].items()}
        reference = {signal: data['reference_' + signal] for signal in ('spec', 'diff')}
        ghost = {signal: data['ghost_' + signal] for signal in ('spec', 'diff')}
        lights = dict(noisy_input={signal: data[signal][..., :3] for signal in ('spec', 'diff')})
        for candidate, native in run_info['runs'].items():
            lights[candidate] = {}
            for signal in ('spec', 'diff'):
                path = completed / candidate / frame['directory'] / (signal + '.bin')
                mirror.need(sealed.file_sha(path) == native['outputs'][str(frame['frame'])][signal], 'signed-RR output SHA remains exact')
                rgba = np.fromfile(path, '<f2').reshape(128, 128, 4)
                mirror.need(np.isfinite(rgba).all(), 'all measured output pixels finite')
                lights[candidate][signal] = rgba[..., :3]
        row = dict(frame=frame['frame'], domains=dict(spec={}, diff={}), flat_surface_detail={})
        for candidate, signals in lights.items():
            for signal in ('spec', 'diff'):
                row['domains'][signal][candidate] = oracle['metrics'](signals[signal], reference[signal],
                    data['reveal_age'], ghost[signal], manifest['comparison_crop'])
            # Real emitting-surface boundaries are excluded from adjacent-pair
            # spec detail; a material edge is not recovered fine mirror texture.
            spec_id = data['object'].astype(np.int16) * 3 + data['secondary_object']
            row['flat_surface_detail'][candidate] = {
                signal: common.masked_detail(signals[signal], reference[signal],
                    spec_id if signal == 'spec' else data['object'], manifest['comparison_crop'])
                for signal in ('spec', 'diff')}
        rows.append(row)
    names = ['noisy_input', *mirror.CANDIDATES]
    summaries = common.summarize(rows, names)
    phases = dict(first_reset=rows[:1], jittered_static=rows[1:16], camera_and_object=rows[16:48],
                  camera_only=rows[48:56], settled_tail=rows[56:])
    flat = {candidate: {signal: dict(mean_gradient_projection=float(np.mean([
        row['flat_surface_detail'][candidate][signal]['gradient_projection_ratio'] for row in rows])),
        adjacent_pairs=sum(row['flat_surface_detail'][candidate][signal]['adjacent_pairs'] for row in rows))
        for signal in ('spec', 'diff')} for candidate in names}
    result = dict(schema='fsrd-mirror-control-signed-comparison-v4',
        prepared_manifest_sha256=run_info['prepared_manifest_sha256'],
        geometry_and_reference=manifest['geometry'], model=manifest['radiance'],
        candidates=manifest['candidates'], source_v1_manifest_sha256=sealed.SOURCE_SHA,
        source_v1_or_v2_changed=False, native_nrd_paired=False, game_fps_measured=False,
        rough_ggx_integrated_truth=False, sdk_private_virtual_hit_formula_known=False,
        all_noisy_lighting_through_signed_rr=True, no_quality_improvement_assertion=True,
        summaries=summaries, phases={phase: common.summarize(selected, names) for phase, selected in phases.items()},
        flat_surface_detail=flat, frames=rows, native_runs=run_info, checks=mirror.CHECKS,
        sealed_payload_checks=sealed.CHECKS,
        timing_scope='128x128 actual signed RR + normal production RGB commit, including first reset; no game FPS or conversion/material-capture cost',
        caveats=[
            'mirror-r0 is a coherent ideal-mirror point-sample reference, not a finite-area pixel-filtered rendering.',
            'negative-r012 changes only B and intentionally mismatches the ideal-mirror radiance; it is not a rough-GGX ground truth.',
            'diagnostic-reflected-mv intentionally violates SDK primary-material motion semantics and cannot authorize a production motion replacement.',
            'Diffuse is a separately declared analytic point-light lobe; unit-lobe addition is not an energy-conserving material claim.',
            'One-bounce emitted specular radiance uses nearest full-scene secondary visibility; primary selfhit is excluded.',
            'Neutral white albedos and queried provider defaults are held fixed; no native guide or SDK setting was tuned.'])
    sealed.write_json(completed / 'comparison.json', result)
    print(json.dumps({key: value for key, value in result.items() if key not in ('frames', 'native_runs', 'phases')}, indent=2))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared', type=Path, default=mirror.BASE / 'mirror-v4')
    parser.add_argument('--output', type=Path, default=mirror.BASE / 'mirror-v4-rr')
    # Frozen v1 generator source; the sealed manifest pins these bytes.
    parser.add_argument('--camera-source', type=Path, default=Path(__file__).resolve().parent / 'fsrd_nrd_motion_quality_oracle_v1_frozen.py')
    parser.add_argument('--native-exe', type=Path)
    parser.add_argument('--native-exe-sha')
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--analyze-existing', action='store_true')
    args = parser.parse_args()
    validation = tests.validate(args.prepared, args.camera_source)
    manifest = json.loads((args.prepared / 'mirror-sequence.json').read_bytes())
    if args.run:
        mirror.need(args.native_exe is not None, 'explicit prebuilt real signed-RR harness required; no compiler fallback')
        execute(args.prepared, manifest, args.output, args.native_exe, args.native_exe_sha)
    if args.run or args.analyze_existing:
        compare(args.prepared, manifest, args.output, args.camera_source)
    else:
        print(json.dumps(validation, indent=2))


if __name__ == '__main__':
    main()
