"""Frozen physical/demod positive-GGX cases through actual signed RRWrapper.

Default validation/--analyze-existing are CPU only. --run needs the parent's
exclusive GPU grant and lead_ops wrapper; this script never invokes a compiler.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import struct

import numpy as np

import fsrd_nrd_rr_material_compare as native_common
import fsrd_nrd_rr_material_quality as sealed
import fsrd_nrd_rr_ggx_oracle as oracle
import fsrd_nrd_rr_ggx_views as domain
import fsrd_nrd_rr_ggx_uncertainty as uncertainty
import fsrd_nrd_rr_mirror_oracle as scene


def identity(manifest):
    return ('demod' if manifest['schema'] == domain.DEMOD_SCHEMA else 'physical') + '-r' + str(manifest['code'])


def validate(case):
    manifest = json.loads((case / 'ggx-sequence.json').read_bytes())
    domain.need(manifest['schema'] in (oracle.SCHEMA, domain.DEMOD_SCHEMA), 'explicit physical or one-time guide-demod V5 domain')
    domain.need(not manifest['zero_roughness_used'] and manifest['code'] in oracle.ROUGHNESS_CODES and manifest['roughness'] >= .1,
                'all measured V5 cases avoid zero and the SDK demo mirror approximation')
    domain.need(manifest['submitted_frames'] == len(manifest['frames']) == 64 and len(manifest['views']) == 1, 'one complete immutable64-frame native view per physical scenario')
    for source, expected in manifest['source_files'].items():
        domain.need(sealed.file_sha(Path(source)) == expected, 'frozen math/camera/official source provenance')
    if manifest['schema'] == domain.DEMOD_SCHEMA:
        physical = Path(manifest['physical_case'])
        domain.need(sealed.file_sha(physical / 'ggx-sequence.json') == manifest['physical_manifest_sha256'], 'derived view retains the original physical reference manifest')
        domain.need(sealed.file_sha(Path(domain.__file__)) == manifest['derived_source_sha256'], 'exact sealed one-time signal-domain adapter source')
    view = Path(next(iter(manifest['views'].values())))
    domain.need(sealed.file_sha(view / 'native-replay.txt') == manifest['native_replay']['sha256'], 'sealed complete native camera table')
    for index, frame in enumerate(manifest['frames']):
        domain.need(frame['frame'] == index + 2, 'continuous samples and first-only reset order')
        data = domain.load_frame(case, manifest, frame, ('spec', 'diff', 'depth', 'motion', 'normals', 'spec_albedo', 'diff_albedo',
            'reference_spec_a', 'reference_spec_b', 'reference_diff'))
        for name in ('spec', 'diff', 'depth', 'motion', 'normals', 'spec_albedo', 'diff_albedo'):
            domain.need(sealed.file_sha(view / frame['directory'] / (name + '.bin')) == frame['payloads'][name]['sha256'], 'exact seven declared native inputs for this signal domain')
        domain.need(all(np.isfinite(value).all() for value in data.values()), 'all actual inputs and independent references finite')
        domain.need(np.all(data['spec'][..., 3] > 0.) and np.all(data['diff'][..., 3] > 0.), 'active path hits/misses preserve positive real metrics')
        domain.need(np.all(((data['normals'] >> 20) & 1023) == manifest['code']), 'actual packed strictly positive perceptual roughness')
    return manifest


def execute(cases, output, executable, expected_exe_sha):
    domain.need(output.resolve().is_relative_to(scene.BASE.resolve()) and not output.exists(), 'fresh task-scoped signed output folder, preserving all prior attempts')
    domain.need(expected_exe_sha and sealed.file_sha(executable) == expected_exe_sha, 'explicit existing real-wrapper executable hash; no compilation fallback')
    domain.need(sealed.file_sha(native_common.DLL) == native_common.DLL_SHA, 'exact installed signed AMD1.2 provider')
    output.mkdir(parents=True)
    first_manifest = cases[0][1]
    probe = native_common.native(executable, Path(next(iter(first_manifest['views'].values()))), output / 'defaults-probe')
    values = struct.unpack('<8f', struct.pack('<8I', *probe['effective_words']))
    settings = output / 'common-effective-settings.txt'
    settings.write_text(' '.join(format(float(value), '.9g') for value in values) + '\n', encoding='ascii')
    runs = {}
    for case, manifest in cases:
        key = identity(manifest)
        domain.need(key not in runs, 'every physical/domain candidate has a distinct complete history')
        view_name, view = next(iter(manifest['views'].items()))
        native = native_common.native(executable, Path(view), output / key, settings)
        domain.need(native['effective_words'] == probe['effective_words'] and native['default_words'] == probe['default_words'], 'identical eight settings words and actual queried defaults across fresh signed histories')
        native.update(input_case=str(case), input_manifest_sha256=sealed.file_sha(case / 'ggx-sequence.json'),
            signal_domain='guide-defined-demodulated' if manifest['schema'] == domain.DEMOD_SCHEMA else 'physical-outgoing-GGX',
            roughness=manifest['roughness'], outputs={})
        for frame in manifest['frames']:
            folder = output / key / frame['directory']
            domain.need(sealed.file_sha(folder / 'motion.bin') == frame['payloads']['motion']['sha256'], 'actual current primary motion exact on GPU')
            native['outputs'][str(frame['frame'])] = {}
            for signal, alpha in (('spec', .75), ('diff', 2.)):
                path = folder / (signal + '.bin')
                rgba = np.fromfile(path, '<f2').reshape(128, 128, 4)
                domain.need(np.isfinite(rgba).all() and np.all(rgba[..., 3] == np.float16(alpha)), 'all committed RGB finite and original destination alpha exact')
                native['outputs'][str(frame['frame'])][signal] = sealed.file_sha(path)
        sealed.write_json(output / key / 'native-result.json', native)
        # One-case V4-shaped map lets recovery consume the exact raw baseline
        # without depending on how other unit domains are scheduled.
        sealed.write_json(output / key / 'runs.json', dict(schema=oracle.SCHEMA + '-one-case-signed-runs',
            prepared_manifest_sha256=native['input_manifest_sha256'], input_case=str(case),
            signal_domain=native['signal_domain'], runs={view_name: native}))
        runs[key] = native
    result = dict(schema=oracle.SCHEMA + '-signed-runs', executable_sha256=expected_exe_sha,
        provider_dll_sha256=native_common.DLL_SHA, probe=probe, runs=runs,
        checks=domain.CHECKS, sealed_payload_checks=sealed.CHECKS, gpu_executed=True, compiler_executed=False)
    sealed.write_json(output / 'runs.json', result)
    return result


def compare(cases, completed):
    run_info = json.loads((completed / 'runs.json').read_bytes())
    camera = oracle.camera_api()
    rows, case_summaries = {}, {}
    for case, manifest in cases:
        key = identity(manifest)
        native = run_info['runs'][key]
        domain.need(native['input_manifest_sha256'] == sealed.file_sha(case / 'ggx-sequence.json'), 'signed outputs retain exact reference/input provenance')
        is_demod = manifest['schema'] == domain.DEMOD_SCHEMA
        physical_case = Path(manifest['physical_case']) if is_demod else case
        physical_manifest = json.loads((physical_case / 'ggx-sequence.json').read_bytes())
        frames, paired = [], []
        for index, frame in enumerate(manifest['frames']):
            data = domain.load_frame(case, manifest, frame)
            physical_frame = physical_manifest['frames'][index]
            domain.need(physical_frame['frame'] == frame['frame'], 'unit scenarios retain the same physical sample order')
            physical = domain.load_frame(physical_case, physical_manifest, physical_frame,
                ('reference_spec', 'reference_spec_a', 'reference_spec_b', 'reference_diff'))
            lights = {}
            for signal in ('spec', 'diff'):
                path = completed / key / frame['directory'] / (signal + '.bin')
                domain.need(sealed.file_sha(path) == native['outputs'][str(frame['frame'])][signal], 'actual signed output integrity before quality analysis')
                lights[signal] = np.fromfile(path, '<f2').reshape(128, 128, 4)[..., :3].astype(np.float64)
            qs = data['spec_albedo'][..., :3].astype(np.float64) / 255. if is_demod else np.ones((128, 128, 3))
            metrics = dict(spec={}, diff={})
            for name, signals in (('noisy_input', {s: data[s][..., :3] for s in ('spec', 'diff')}), ('signed_rr', lights)):
                for signal in ('spec', 'diff'):
                    factor = qs if signal == 'spec' else 1.
                    value = signals[signal] * factor
                    # Score both unit domains against the untouched physical
                    # replicas, avoiding a divide/store/multiply reference bias.
                    reference = physical['reference_' + signal].astype(np.float64)
                    ghost = data['ghost_' + signal].astype(np.float64) * factor
                    metrics[signal][name] = camera['metrics'](value, reference, data['reveal_age'], ghost, manifest['comparison_crop'])
            refs = [physical['reference_spec_' + suffix].astype(np.float64) for suffix in ('a', 'b')]
            paired_row = uncertainty.paired_mse(lights['spec'] * qs, data['spec'][..., :3] * qs, refs[0], refs[1], manifest['comparison_crop'])
            paired.append(paired_row)
            frames.append(dict(frame=frame['frame'], domains=metrics, spec_paired_mse=paired_row))
        summary = native_common.summarize(frames, ['noisy_input', 'signed_rr'])
        case_summaries[key] = dict(input_case=str(case), signal_domain=native['signal_domain'], roughness=manifest['roughness'],
            report_domain='physical outgoing radiance after defined currentQs remodulation' if is_demod else 'physical outgoing radiance directly',
            summaries=summary, spec_paired_mse=uncertainty.summarize_paired(paired))
        rows[key] = frames
    result = dict(schema=oracle.SCHEMA + '-signed-comparison', cases=case_summaries, frames=rows,
        native_runs=run_info, checks=domain.CHECKS, sealed_payload_checks=sealed.CHECKS,
        native_nrd_paired=False, game_fps_measured=False, native_recon_unit_parity_claimed=False,
        zero_roughness_quality_claimed=False, no_production_change=True, all_noisy_lighting_through_rr=True,
        reference_uncertainty='two independent256spp physical NDF replicas; same paired winner and circular8-frame block intervals required; fixed spatial32768spp audit remains separate',
        consumer_scope='actual native fixture verifies RGBcodec/alpha/scale64; chosen synthetic Qs remodulation above is CPU analysis, not title-LUT execution',
        caveat='physical and guide-defined-demod scenarios are explicit unit experiments; no actual native Recon signal is divided or altered')
    sealed.write_json(completed / 'comparison.json', result)
    print(json.dumps({key: value for key, value in result.items() if key not in ('frames', 'native_runs')}, indent=2))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', type=Path, action='append', required=True)
    parser.add_argument('--output', type=Path, default=scene.BASE / 'ggx-v5-rr-run1')
    parser.add_argument('--native-exe', type=Path)
    parser.add_argument('--native-exe-sha')
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--analyze-existing', action='store_true')
    args = parser.parse_args()
    cases = [(case, validate(case)) for case in args.case]
    if args.run:
        domain.need(args.native_exe is not None, 'explicit hashed prebuilt native harness required')
        execute(cases, args.output, args.native_exe, args.native_exe_sha)
    if args.run or args.analyze_existing:
        compare(cases, args.output)
    else:
        print(json.dumps(dict(validated_cases=[identity(m) for _, m in cases], checks=domain.CHECKS,
            sealed_payload_checks=sealed.CHECKS, gpu_executed=False, compiler_executed=False), indent=2))


if __name__ == '__main__':
    main()
