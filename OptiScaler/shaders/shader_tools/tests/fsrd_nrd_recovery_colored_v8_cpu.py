"""Unchanged FP32 causal recovery on corrected colored V8 actual signed RR.

CPU only: no compiler, GPU runner, provider invocation or production mutation.
Oracle truth defines scoring cohorts only and is never passed to Recovery.step.
"""
from pathlib import Path
from dataclasses import asdict
import hashlib
import json
import os
import sys
import time

sys.dont_write_bytecode = True  # Main checkout is read-only, including caches.
HERE = Path(__file__).resolve().parent
MAIN = Path('F:/OptiRevelations/OSA-15-nrd-ghosting/OptiScaler/shaders/shader_tools/tests')
sys.path[:0] = [str(MAIN), str(MAIN.parent)]
import numpy as np
import fsrd_nrd_lobe_reference_prototype as cpu
import fsrd_nrd_recovery_replay as recovery_metrics
import fsrd_nrd_rr_albedo_pair_compare as corrected


CASE = Path('F:/FSRD/sol_batch/15c-rr/ggx-colored-native-v8-four-way-r2/g31-b124')
RUN_ROOT = Path('F:/FSRD/sol_batch/15c-rr/albedo-v7-v8-rr-run1')
OUT = Path(os.environ.get('FSRD_GPU_TEST_OUTPUT', 'F:/FSRD/sol_batch/15b-inputs/tests/recovery-colored-v8-cpu-r1'))
VARIANTS = {'spec1-diff0': (1., 0.), 'spec0-diff1': (0., 1.), 'spec1-diff1': (1., 1.), 'zero': (0., 0.)}
CHECKS = 0
ALGORITHM_CANONICAL_SHA = {
    'fsrd_nrd_lobe_reference_prototype.py': 'bbe9ae7b8f8cbef7725334e411d72533ec2d37f0e5a6dac983df15ad779f804a',
    'fsrd_nrd_recovery_prototype.py': 'b9b6347c0b274127ceb6e9d91ca8c70bc88dfbf69ca54fb745ddef099369b309',
    'fsrd_nrd_recovery_local_bounds.py': '196ebc9b8a87f5a1d410bed37473a96b5ca0644ad89b01911ddbdc0ad85fae8e',
}


def need(condition, message):
    global CHECKS
    CHECKS += 1
    if not bool(condition):
        raise AssertionError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_sha(path):
    # Git working trees may expose LF versus CRLF. Pin every other source byte.
    return hashlib.sha256(Path(path).read_bytes().replace(b'\r\n', b'\n')).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def sealed_run(candidate, manifest_sha):
    directory = RUN_ROOT/('colored-v8-g31-b124-'+candidate)
    wrapper = json.loads((directory/'runs.json').read_bytes())
    run = wrapper['runs'][candidate]
    need(wrapper['prepared_manifest_sha256'] == run['input_manifest_sha256'] == manifest_sha,
         'actual signed history belongs to exact corrected colored manifest')
    need(run['debug_errors'] == run['debug_warnings'] == 0, 'actual signed baseline debug clean')
    need(Path(run['directory']).resolve() == directory.resolve(), 'exact sealed output directory')
    return directory, run


def summarize_cohorts(rows, names):
    output = {}
    for name in names:
        output[name] = {}
        for signal in ('spec', 'diff', 'combined'):
            values = [row['cohorts'][signal][name] for row in rows]
            cohorts = {}
            for cohort in sorted(set().union(*values)):
                selected = [v[cohort] for v in values if cohort in v]
                pixels = sum(v['pixels'] for v in selected)
                cohorts[cohort] = dict(pixels=pixels,
                    rgb_rmse=float(np.sqrt(sum(v['rgb_rmse']**2*v['pixels'] for v in selected)/pixels)),
                    chroma_rmse=float(np.sqrt(sum(v['chroma_rmse']**2*v['pixels'] for v in selected)/pixels)),
                    absolute_rgb_p99_frame_mean=float(np.mean([v['absolute_rgb_p99'] for v in selected])),
                    absolute_chroma_p99_frame_mean=float(np.mean([v['absolute_chroma_p99'] for v in selected])),
                    rgb_energy_ratio=sum(v['rgb_energy'] for v in selected)/max(sum(v['reference_rgb_energy'] for v in selected), 1e-30))
            output[name][signal] = cohorts
    return output


def crop_sheet(path, lighting, refs, crop):
    from PIL import Image, ImageDraw
    x, y, width, height = crop
    keys = ['rr-white', 'rr-both', 'spec1-diff0', 'spec0-diff1', 'spec1-diff1', 'reference']
    sheet = Image.new('RGB', (180+3*width, len(keys)*(height+22)), (24, 24, 24))
    draw = ImageDraw.Draw(sheet)
    for row, key in enumerate(keys):
        draw.text((3, row*(height+22)+3), key, fill=(255, 255, 255))
        for column, signal in enumerate(('spec', 'diff', 'combined')):
            image = refs[signal] if key == 'reference' else lighting[key][signal]
            image = np.asarray(image[y:y+height, x:x+width], np.float32)
            # Fixed Consumer-style64 display factor, same exposure/gamma everywhere.
            pixels = np.rint(np.clip(image*64, 0, 1)**(1/2.2)*255).astype(np.uint8)
            sheet.paste(Image.fromarray(pixels), (180+column*width, row*(height+22)+22))
    sheet.save(path)
    return dict(path=str(path), sha256=sha(path), gain=64, gamma=2.2, crop=list(crop),
                columns=['physical spec', 'physical diff', 'physical sum'])


def main():
    started = time.perf_counter()
    need(OUT.resolve().is_relative_to(Path('F:/FSRD/sol_batch/15b-inputs').resolve()) and not OUT.exists(),
         'fresh bounded own-task output; retain earlier evidence')
    OUT.mkdir(parents=True)
    name, manifest = corrected.validate(CASE)
    manifest_sha = sha(CASE/name)
    need(manifest_sha == '269aad83f74718d6085dfe76fc13121b82f500ecdd00f6d066eed9efbc9ecfb5',
         'prespecified corrected colored V8 manifest')
    need(len(manifest['frames']) == 64 and manifest['rr_normal_r10_code'] == 124,
         'all64 prescribed strictly-positive-roughness frames')
    histories = {variant: {signal: cpu.LobeReferenceRecovery(cpu.ReferenceSettings(
        strength=strength, bound_projection='local_anchor', texture_storage='fp32'))
        for signal, strength in zip(('spec', 'diff'), strengths)} for variant, strengths in VARIANTS.items()}
    algorithm_names = ('fsrd_nrd_lobe_reference_prototype.py', 'fsrd_nrd_recovery_prototype.py',
                       'fsrd_nrd_recovery_local_bounds.py')
    for filename in algorithm_names:
        need(source_sha(HERE/filename) == source_sha(MAIN/filename) == ALGORITHM_CANONICAL_SHA[filename],
             'unchanged tested canonicalLF FP32 algorithm: '+filename)
    runs = {candidate: sealed_run(candidate, manifest_sha) for candidate in ('both', 'white')}
    need(runs['both'][1]['effective_words'] == runs['white'][1]['effective_words'], 'same eight actual SDK settings')
    rows = (Path(manifest['views']['both'])/'native-replay.txt').read_text().splitlines()[1:]
    jitters = [np.asarray([float(v) for v in row.split()[-2:]], np.float32) for row in rows]
    need(len(jitters) == 64, 'full unchanged jitter chronology')
    camera = corrected.transport.camera_api()
    names = ['rr-both', 'rr-white', 'off']+list(VARIANTS)
    frames = []; pairs = {v: {s: [] for s in ('spec', 'diff', 'combined')} for v in VARIANTS if v != 'zero'}
    gradients = {v: {d: [] for d in ('physical', 'demod_same_material')} for v in names if v not in ('zero', 'off')}
    previous_diff = previous_age = None
    fixed_crops = {}; outputs = {}; peak = 0
    for index, frame in enumerate(manifest['frames']):
        data = corrected.load(CASE, manifest, frame)
        rr = {}
        for candidate, (directory, run) in runs.items():
            rr[candidate] = {}
            for signal in ('spec', 'diff'):
                path = directory/frame['directory']/(signal+'.bin')
                need(sha(path) == run['outputs'][str(frame['frame'])][signal], 'sealed actual RR '+candidate+' '+signal)
                rr[candidate][signal] = np.fromfile(path, '<f2').reshape(128, 128, 4)
        decoded = {key: {s: rr['both'][s].copy() for s in ('spec', 'diff')} for key in ('off',)}
        decoded['rr-both'], decoded['rr-white'] = rr['both'], rr['white']
        stats = {}; outputs[str(frame['frame'])] = {}
        for variant, models in histories.items():
            decoded[variant] = {}; stats[variant] = {}
            for signal, model in models.items():
                # Exact production CPU oracle inputs ONLY. No truth, Q factors,
                # material IDs, secondary UV, reveal or uncertainty enters here.
                result = model.step(data[signal], rr['both'][signal], data['depth'], data['normals'],
                    data['motion'], frame['frame'], reset=index == 0, jitter=jitters[index])
                need(result.dtype == np.dtype('<f2') and np.isfinite(result).all(), 'finite half output')
                need(np.array_equal(result[..., 3].copy().view('<u2'), rr['both'][signal][..., 3].copy().view('<u2')),
                     'exact opaque signed-provider alpha')
                strength = VARIANTS[variant][0 if signal == 'spec' else 1]
                if strength == 0 or index < 7:
                    need(np.array_equal(result.view('<u2'), rr['both'][signal].view('<u2')), 'zero/cold byte-exact RR')
                decoded[variant][signal] = result; stats[variant][signal] = dict(model.last_stats)
                if variant != 'zero':
                    directory = OUT/variant/frame['directory']; directory.mkdir(parents=True, exist_ok=True)
                    path = directory/(signal+'.bin'); path.write_bytes(result.tobytes())
                    outputs[str(frame['frame'])][variant+'/'+signal] = sha(path)
        for signal, variant in (('spec', 'spec1-diff0'), ('diff', 'spec0-diff1')):
            need(np.array_equal(decoded[variant][signal].view('<u2'), decoded['spec1-diff1'][signal].view('<u2')),
                 'independent active lobes equal combined graph-oracle histories')
            need(np.array_equal(decoded['zero'][signal].view('<u2'), decoded['off'][signal].view('<u2')),
                 'OFF/zero exact entire actual RR words')
        factors = {s: np.rint(data['qs_current' if s == 'spec' else 'qd_current'].astype(np.float64)*255)/255
                   for s in ('spec', 'diff')}
        geometry = corrected.transport.frame_geometry(index, camera)
        old = corrected.ghosts(data, geometry, previous_diff, previous_age, True)
        previous_diff, previous_age = old['diff'], data['reveal_age']
        refs = {s: data['reference_'+s].astype(np.float64) for s in ('spec', 'diff')}
        refs['combined'] = refs['spec']+refs['diff']
        replica = {s: (data['reference_spec_a'].astype(np.float64), data['reference_spec_b'].astype(np.float64))
                   if s == 'spec' else (refs['diff'], refs['diff']) for s in ('spec', 'diff')}
        replica['combined'] = tuple(value+refs['diff'] for value in replica['spec'])
        physical = {key: {s: value[s][..., :3].astype(np.float64)*factors[s] for s in ('spec', 'diff')}
                    for key, value in decoded.items()}
        row = dict(frame=frame['frame'], domains={}, cohorts={}, recovery_statistics=stats)
        for value in physical.values(): value['combined'] = value['spec']+value['diff']
        for signal in ('spec', 'diff', 'combined'):
            ghost = old[signal]*factors[signal] if signal != 'combined' else old['spec']*factors['spec']+old['diff']*factors['diff']
            row['domains'][signal] = {}; row['cohorts'][signal] = {}
            masks = recovery_metrics.evaluation_masks(data, refs[signal], signal, manifest['comparison_crop'])
            for key in names:
                row['domains'][signal][key] = camera['metrics'](physical[key][signal], refs[signal], data['reveal_age'], ghost, manifest['comparison_crop'])
                row['cohorts'][signal][key] = recovery_metrics.cohort_metrics(physical[key][signal], refs[signal], masks)
            for variant in pairs:
                pairs[variant][signal].append(corrected.uncertainty.paired_mse(physical[variant][signal], physical['rr-both'][signal],
                    *replica[signal], manifest['comparison_crop']))
        crop = np.s_[16:112, 16:112]
        for key in gradients:
            gradients[key]['physical'].append(corrected.detail.gradients(physical[key]['spec'][crop], *[v[crop] for v in replica['spec']]))
            gradients[key]['demod_same_material'].append(corrected.detail.gradients(decoded[key]['spec'][crop][..., :3],
                *[(v/factors['spec'])[crop] for v in replica['spec']], data['material_id'][crop]))
        frames.append(row)
        if frame['frame'] in (2, 33, 65):
            fixed_crops[frame['frame']] = ({k: {s: v.copy() for s, v in x.items()} for k, x in physical.items()},
                                          {s: v.copy() for s, v in refs.items()})
        current_peak = recovery_metrics.peak_resident_bytes()
        need(current_peak is not None and current_peak < 2_500_000_000, 'CPU RSS below2.5GB')
        peak = max(peak, current_peak)
        if (index+1) % 8 == 0:
            print(json.dumps(dict(frames_complete=index+1, checks=CHECKS, peak_resident_bytes=peak)), flush=True)
    summaries = corrected.signed.summarize(frames, names)
    phases = {key: corrected.signed.summarize(frames[start:stop], names)
              for key, start, stop in (('initial_first8', 0, 8), ('transient_next24', 8, 32), ('settled_last32', 32, 64))}
    result = dict(schema='unchanged-causal-recovery-corrected-colored-v8-cpu-v1', manifest_sha256=manifest_sha,
        input_case=str(CASE), baseline='actual signed coloredV8 BOTH-albedo RR', frames=frames, outputs_sha256=outputs,
        summaries=summaries, phase_summaries=phases, cohorts=summarize_cohorts(frames, names),
        paired_physical_mse={v: {s: corrected.uncertainty.summarize_paired(rows) for s, rows in signals.items()}
                             for v, signals in pairs.items()},
        gradients={v: {d: corrected.detail.summarize(rows) for d, rows in domains.items()} for v, domains in gradients.items()},
        settings={v: {s: asdict(model.settings) for s, model in models.items()} for v, models in histories.items()},
        algorithm_source_sha256={str(MAIN/n): sha(MAIN/n) for n in algorithm_names},
        algorithm_canonical_lf_sha256=ALGORITHM_CANONICAL_SHA,
        source_line_endings='mainCRLF/ownerLF; exact pinned canonicalLF source bytes, raw identities retained',
        comparator_source_sha256=sha(Path(corrected.__file__)), script_sha256=sha(Path(__file__)),
        baseline_run_sha256={candidate: sha(directory/'runs.json') for candidate, (directory, run) in runs.items()},
        peak_resident_bytes=peak, cpu_seconds=time.perf_counter()-started,
        compiler_executed=False, gpu_executed=False, production_changes=False, algorithm_changed=False,
        all_frames_used=True, zero_roughness_used=False, all_lighting_passed_actual_rr=True, oracle_inputs_enter_recovery=False,
        uncertainty_scope='two independent256spp physical spec replicas; diffuse analytic; temporal8frame block bootstrap',
        interpretation='CPU prediction from unchanged FP32 oracle. New colored case has not been recovery-GPU replayed; no title quality/FPS verdict.',
        checks=CHECKS)
    write_json(OUT/'comparison.json', result)
    # The complete metrics above precede the fixed-frame visual publication.
    crops = [crop_sheet(OUT/('frame%03d.png'%frame), *values, manifest['comparison_crop']) for frame, values in fixed_crops.items()]
    write_json(OUT/'crops.json', crops)
    print(json.dumps(dict(comparison=str(OUT/'comparison.json'), checks=CHECKS, frames=64,
        cpu_seconds=result['cpu_seconds'], peak_resident_bytes=peak, gpu_executed=False, compiler_executed=False,
        summaries={v: summaries[v] for v in ('rr-both', 'spec1-diff0', 'spec0-diff1', 'spec1-diff1')}), indent=2), flush=True)


if __name__ == '__main__':
    main()
