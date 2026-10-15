"""Validate/run/compare the frozen material V2 guide ablation.

--run is ONLY for a lead-granted GPU slot inside lead_ops/run_task_test.py.
It reuses an explicitly hashed real-wrapper executable; no compiler is called.
Default validation and --analyze-existing are CPU-only. All four complete fresh
histories use the same queried SDK defaults and the same prescribed noisy light.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import struct
import sys

import numpy as np
import fsrd_nrd_rr_material_quality as model

DLL = Path('F:/OptiRevelations/OptiScaler-ffxD-alpha/external/FidelityFX-SDK-v2/Kits/FidelityFX/signedbin/amd_fidelityfx_denoiser_dx12.dll')
DLL_SHA = '48f1e5888ba6a0a3d59a98b9751e37c392b0f7b8c223d0082d5c1f40642879d3'
TASK = Path('F:/FSRD/sol_batch/15c-rr')


def validate(prepared):
    manifest = json.loads((prepared/'material-sequence.json').read_bytes())
    model.require(manifest['schema'] == model.SCHEMA and manifest['source_manifest_sha256'] == model.SOURCE_SHA,
                  'sealed controlled material V2 schema/source')
    source = Path(manifest['source_directory'])
    v1 = model.original(source)
    model.require(len(manifest['frames']) == 64 and tuple(manifest['candidates']) == model.CANDIDATES,
                  'all four complete declared guide candidates')
    for index, frame in enumerate(manifest['frames']):
        old = v1['frames'][index]
        model.require(frame['frame'] == old['frame'] and frame['directory'] == old['directory'] and
                      frame['source_payloads'] == old['payloads'], 'V2 never changes reference or source metadata')
        derived = {name:model.load(prepared/'dataset'/frame['directory'], info) for name, info in frame['derived'].items()}
        for name in model.CANDIDATES:
            view = Path(manifest['prepared_views'][name])
            model.require(model.file_sha(view/'native-replay.txt') == v1['native_replay']['sha256'], 'identical complete camera table')
            for key in model.IDENTICAL:
                original_key = 'motion_surface' if key == 'motion' else key
                model.require(model.file_sha(view/frame['directory']/(key+'.bin')) == old['payloads'][original_key]['sha256'],
                              'RGB/hit/depth/normal/surfaceMV identity is exact for every candidate')
            for signal in ('spec', 'diff'):
                enabled = name == 'both' or name == ('specular-only' if signal == 'spec' else 'diffuse-only')
                info = frame['derived']['true_'+signal+'_albedo'] if enabled else old['payloads'][signal+'_albedo']
                model.require(model.file_sha(view/frame['directory']/(signal+'_albedo.bin')) == info['sha256'],
                              'only the declared albedo RGB choice changes')
                data = np.fromfile(view/frame['directory']/(signal+'_albedo.bin'), dtype='u1').reshape(128, 128, 4)
                alpha = model.load(source/old['directory'], old['payloads'][signal+'_albedo'])[..., 3]
                model.require(np.array_equal(data[..., 3], alpha), 'all candidate unused albedo alpha words identical')
        for factor in ('qd', 'qs'):
            model.require(np.isfinite(derived[factor]).all() and np.all(derived[factor] >= 0), 'finite analytic current-material factor')
    return manifest, v1


def native(executable, view, destination, settings=None):
    from test_fsrd_nrd_bridge_rr import bounded_run
    model.require(not destination.exists(), 'fresh native output folder preserves prior failure evidence')
    destination.mkdir(parents=True)
    probe = settings is None
    command = [str(executable), str(view), str(destination), 'dd', 'DEFAULT' if probe else str(settings), '1' if probe else 'ALL']
    text, peak, elapsed, log = bounded_run(command, destination/'native')
    result = json.loads((destination/'native-result.json').read_bytes())
    model.require('PASS world_motion ' in text, 'actual production-wrapper fixture reached all final assertions')
    model.require(result['creates'] == result['destroys'] == 1 and result['dispatches'] == (1 if probe else 64),
                  'each real signed provider history is fresh, complete and retired after GPU completion')
    model.require(result['debug_errors'] == result['debug_warnings'] == 0, 'strict zero D3D12 errors AND warnings')
    model.require(result['route'] == 'dd' and result['signal_flags'] == 0x22 and
                  result['diffuse_descriptor_type'] == 0x50044 and result['specular_descriptor_type'] == 0x50048,
                  'unchanged production DD|IS route and actual ordered public descriptors')
    model.require(result['provider_version_id'] == 4311875584 and not result['native_birth_ready'], 'exact AMD1.2 selection and explicit standalone-adapter boundary')
    model.require([frame['frame'] for frame in result['frames']] == list(range(2, 3 if probe else 66)) and
                  [frame['reset'] for frame in result['frames']] == [True]+[False]*(0 if probe else 63),
                  'whole-history temporal alignment and first-only reset')
    model.require(all(frame['current_gpu_guides_exact'] for frame in result['frames']),
                  'actual GPU readbacks of all seven inputs match uploaded candidate bytes')
    result.update(directory=str(destination), elapsed_seconds=elapsed, peak_resident_bytes=peak, native_log=str(log))
    return result


def execute(prepared, manifest, output, executable, expected_sha):
    model.require(output.resolve().is_relative_to(TASK.resolve()), 'only this task scratch receives native outputs')
    model.require(not output.exists(), 'use a fresh output folder for every scheduled native attempt')
    model.require(expected_sha and model.file_sha(executable) == expected_sha, 'explicitly sealed already-built real-wrapper executable')
    model.require(model.file_sha(DLL) == DLL_SHA, 'exact installed signed AMD1.2 provider DLL')
    output.mkdir(parents=True)
    first = Path(manifest['prepared_views']['white'])
    probe = native(executable, first, output/'defaults-probe')
    words = probe['effective_words']
    numbers = struct.unpack('<8f', struct.pack('<8I', *words))
    settings = output/'common-effective-settings.txt'
    settings.write_text(' '.join(format(float(value), '.9g') for value in numbers)+'\n', encoding='ascii')
    runs = {}
    for name in model.CANDIDATES:
        view = Path(manifest['prepared_views'][name])
        result = native(executable, view, output/name, settings)
        model.require(result['effective_words'] == words, 'every material candidate has bit-identical freshly queried effective settings')
        model.require(result['default_words'] == probe['default_words'], 'provider defaults have not drifted across contexts')
        result['outputs'] = {}
        for frame in manifest['frames']:
            directory = output/name/frame['directory']
            model.require(model.file_sha(directory/'motion.bin') == frame['source_payloads']['motion_surface']['sha256'], 'actual selected surface motion is exact on GPU')
            result['outputs'][str(frame['frame'])] = {}
            for signal, expected_alpha in (('spec', .75), ('diff', 2.)):
                path = directory/(signal+'.bin')
                values = np.fromfile(path, dtype='<f2').reshape(128, 128, 4)
                model.require(np.isfinite(values).all() and np.all(values[..., 3] == np.float16(expected_alpha)), 'actual committed signal finite with exact opaque native destination alpha')
                result['outputs'][str(frame['frame'])][signal] = model.file_sha(path)
        model.write_json(output/name/'native-result.json', result)
        runs[name] = result
    model.write_json(output/'runs.json', dict(executable_sha256=expected_sha, provider_dll_sha256=DLL_SHA,
        prepared_manifest_sha256=model.file_sha(prepared/'material-sequence.json'), probe=probe, runs=runs,
        compiler_executed=False, gpu_executed=True, python_checks=model.CHECKS))
    return runs


def masked_detail(value, reference, material_id, crop):
    x, y, width, height = crop
    out = np.asarray(value, np.float64)[y:y+height, x:x+width, :3]
    ref = np.asarray(reference, np.float64)[y:y+height, x:x+width]
    ids = material_id[y:y+height, x:x+width]
    numerator = denominator = error = 0.
    support = 0
    for axis in (0, 1):
        valid = np.diff(ids.astype(np.int16), axis=axis) == 0
        gradient, truth = np.diff(out, axis=axis)[valid], np.diff(ref, axis=axis)[valid]
        numerator += float(np.sum(gradient*truth))
        denominator += float(np.sum(truth*truth))
        error += float(np.sum((gradient-truth)**2))
        support += int(valid.sum())
    return dict(adjacent_pairs=support, reference_gradient_energy=denominator,
                gradient_projection_ratio=numerator/denominator if denominator else None,
                rgb_gradient_rmse=float(np.sqrt(error/(3*support))) if support else None)


def summarize(rows, keys):
    output = {}
    for key in keys:
        output[key] = {}
        for domain in rows[0]['domains']:
            values = [row['domains'][domain][key] for row in rows]
            summary = {name:float(np.mean([value[name] for value in values])) for name in
                ('rgb_rmse', 'chroma_rmse', 'detail_gradient_rmse', 'gradient_projection_ratio')}
            summary['rgb_rmse_last8_mean'] = float(np.mean([value['rgb_rmse'] for value in values[-8:]]))
            tails = {}
            for age in [str(i) for i in range(9)]+['9..16']:
                selected = [value['reveal_tail'][age] for value in values if age in value['reveal_tail']]
                pixels = sum(value['pixels'] for value in selected)
                if not pixels:
                    continue
                tails[age] = dict(pixels=pixels,
                    rgb_rmse=float(np.sqrt(sum(value['rgb_rmse']**2*value['pixels'] for value in selected)/pixels)),
                    positive_stale_energy=sum(value['positive_stale_energy']*value['pixels'] for value in selected)/pixels,
                    signed_stale_fraction=sum(value['mean_signed_stale_fraction']*value['pixels'] for value in selected)/pixels)
            summary['reveal_tail'] = tails
            output[key][domain] = summary
    return output


def compare(prepared, manifest, v1, output, oracle_source):
    run_info = json.loads((output/'runs.json').read_bytes())
    model.require(run_info['prepared_manifest_sha256'] == model.file_sha(prepared/'material-sequence.json'), 'actual outputs belong to this exact material dataset')
    runs = run_info['runs']
    model.require(tuple(runs) == model.CANDIDATES, 'all prescribed candidates reported, no worse row omitted')
    oracle = model.reference_oracle(oracle_source, v1['generator_sha256'])
    metrics, source = oracle['metrics'], Path(manifest['source_directory'])
    rows = []
    for frame in manifest['frames']:
        folder = source/frame['directory']
        payload = frame['source_payloads']
        age = model.load(folder, payload['reveal_age'])
        material = {name:model.load(prepared/'dataset'/frame['directory'], info) for name, info in frame['derived'].items()}
        qd, qs = material['qd'], material['qs']
        reference = {signal:model.load(folder, payload['reference_'+signal]) for signal in ('spec', 'diff')}
        old = {signal:model.load(folder, payload['ghost_'+signal]) for signal in ('spec', 'diff')}
        lights = {'noisy_input':{signal:model.load(folder, payload[signal])[..., :3] for signal in ('spec', 'diff')}}
        for name, run in runs.items():
            lights[name] = {}
            for signal in ('spec', 'diff'):
                path = output/name/frame['directory']/(signal+'.bin')
                model.require(model.file_sha(path) == run['outputs'][str(frame['frame'])][signal], 'actual signed output length/hash integrity')
                value = np.fromfile(path, dtype='<f2').reshape(128, 128, 4)
                model.require(np.isfinite(value).all(), 'all actual output components finite')
                lights[name][signal] = value[..., :3]
        domain_reference = dict(demod_spec=reference['spec'], demod_diff=reference['diff'],
            remod_spec=reference['spec']*qs, remod_diff=reference['diff']*qd,
            combined=reference['spec']*qs+reference['diff']*qd)
        # RR history stores demodulated light; even stale old light is multiplied
        # by CURRENT material at the late compositor. Do not apply an old
        # material factor and manufacture a different history failure model.
        ghost = dict(demod_spec=old['spec'], demod_diff=old['diff'],
            remod_spec=old['spec']*qs, remod_diff=old['diff']*qd, combined=old['spec']*qs+old['diff']*qd)
        row = dict(frame=frame['frame'], domains={domain:{} for domain in domain_reference}, flat_material_detail={})
        for name, light in lights.items():
            domains = dict(demod_spec=light['spec'], demod_diff=light['diff'],
                remod_spec=light['spec']*qs, remod_diff=light['diff']*qd, combined=light['spec']*qs+light['diff']*qd)
            for domain, value in domains.items():
                row['domains'][domain][name] = metrics(value, domain_reference[domain], age, ghost[domain], v1['comparison_crop'])
            row['flat_material_detail'][name] = {signal:masked_detail(light[signal], reference[signal], material['material_id'], v1['comparison_crop']) for signal in ('spec', 'diff')}
        rows.append(row)
    summaries = summarize(rows, list(lights))
    flat = {name:{signal:dict(mean_gradient_projection=float(np.mean([row['flat_material_detail'][name][signal]['gradient_projection_ratio'] for row in rows])),
        adjacent_pairs=sum(row['flat_material_detail'][name][signal]['adjacent_pairs'] for row in rows)) for signal in ('spec','diff')} for name in lights}
    result = dict(schema='fsrd-material-guide-signed-comparison-v2', source_manifest_sha256=model.SOURCE_SHA,
        prepared_manifest_sha256=model.file_sha(prepared/'material-sequence.json'),
        renderer='current Qd*RRdiff+current Qs*RRspec, unity exposure, pre-Consumer64 units',
        scalar64_conversion='post-Consumer RGB RMSE is64 times reported pre-Consumer RGB RMSE; never input preExposure',
        native_nrd_paired=False, game_fps_measured=False, path_integrated_ground_truth=False,
        source_lighting_and_noise_unchanged=True, no_quality_improvement_assertion=True,
        title_native_lut_identity_claimed=False, all_candidates_reported=True,
        summaries=summaries, flat_material_demod_detail=flat, frames=rows,
        native_runs=run_info, python_checks=model.CHECKS,
        scope='real signed RR on CPU-preconverted synthetic guides; original wrapper/Consumer/alpha/context tests retained; material remodulation is CPU analysis, not native late-compositor execution',
        caveats=['Reference reflectance explicitly uses the AMD analytic GGX approximation, not the unavailable title LUT/CB6.',
                 'Both demodulated and remodulated metrics are required: dark material can hide error without restoring RR lighting detail.',
                 'Material edges can inflate combined gradient agreement; original demod gradients and same-material adjacent pairs are reported separately.',
                 'Original point-sampled/noisy64-frame light is prescribed, not path-integrated or native-NRD temporal truth.'])
    model.write_json(output/'comparison.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared', type=Path, default=TASK/'material-v2')
    parser.add_argument('--output', type=Path, default=TASK/'material-v2-rr')
    parser.add_argument('--oracle-source', type=Path, default=Path('F:/OptiRevelations/OSA-15-nrd-ghosting/OptiScaler/shaders/shader_tools/tests/fsrd_nrd_motion_quality_oracle.py'))
    parser.add_argument('--native-exe', type=Path)
    parser.add_argument('--native-exe-sha')
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--analyze-existing', action='store_true')
    args = parser.parse_args()
    manifest, v1 = validate(args.prepared)
    if args.run:
        model.require(args.native_exe is not None, 'explicit prebuilt native harness required; no compilation fallback')
        execute(args.prepared, manifest, args.output, args.native_exe, args.native_exe_sha)
    if args.run or args.analyze_existing:
        result = compare(args.prepared, manifest, v1, args.output, args.oracle_source)
        print(json.dumps(dict(comparison=str(args.output/'comparison.json'), checks=model.CHECKS,
            summaries=result['summaries'], flat_material_demod_detail=result['flat_material_demod_detail']), indent=2))
    else:
        print(json.dumps(dict(validated_manifest_sha256=model.file_sha(args.prepared/'material-sequence.json'),
            candidates=list(model.CANDIDATES), checks=model.CHECKS, compiler_executed=False, gpu_executed=False), indent=2))


if __name__ == '__main__':
    main()
