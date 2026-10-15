"""Stream immutable noisy inputs + actual signed-RR lobes through CPU recovery.

This never invokes a compiler, provider, GPU, or a title-resource hook. Reference,
object, reveal and outlier arrays are passed ONLY to measurement functions. V4
R0 / the deliberately mismatched .12 view are diagnostic controls; a useful
quality result requires the independently integrated nonzero-GGX dataset.
"""
from __future__ import annotations

import argparse
import ast
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from fsrd_nrd_recovery_prototype import Recovery, Settings, neighbourhood
from fsrd_nrd_lobe_reference_prototype import LobeReferenceRecovery, ReferenceSettings
from fsrd_nrd_rr_band_gain_prototype import RRBandGainRecovery, BandGainSettings
from fsrd_nrd_recovery_uncertainty import PairedMSE


PROVIDER_SHA = '48f1e5888ba6a0a3d59a98b9751e37c392b0f7b8c223d0082d5c1f40642879d3'
TASK = Path('F:/FSRD/sol_batch/15b-inputs')
VARIANTS = {
    'paired-3sigma-anchor4': Settings(),
    'paired-3sigma-no-anchor': Settings(anchor=0),
    'paired-luma-3sigma-anchor4': Settings(luma_only=True),
    'lobe-gradient-threshold3-anchor4': ReferenceSettings(),
    'lobe-gradient-threshold3-no-anchor': ReferenceSettings(anchor=0),
    'rr-band-gain3sigma-anchor4': BandGainSettings(),
    'lobe-gradient-threshold3-local-anchor4': ReferenceSettings(bound_projection='local_anchor'),
    'rr-band-gain3sigma-local-anchor4': BandGainSettings(bound_projection='local_anchor'),
}
CHECKS = 0


def need(condition, message):
    global CHECKS
    CHECKS += 1
    if not condition:
        raise AssertionError(message)


def sha(value):
    return hashlib.sha256(value).hexdigest()


def file_sha(path):
    return sha(Path(path).read_bytes())


def load(folder, record):
    name = Path(record['file'])
    need(name.name == str(name), 'sealed payload has one exact local basename')
    data = (folder/name).read_bytes()
    need(len(data) == record['bytes'] and sha(data) == record['sha256'], 'payload bytes/SHA unchanged')
    dtype, shape = np.dtype(record['dtype']), tuple(record['shape'])
    need(dtype.itemsize*np.prod(shape) == len(data), 'sealed dtype/shape equals payload length')
    return np.frombuffer(data, dtype).reshape(shape)


def original_metrics(source, expected_sha):
    code = source.read_bytes()
    need(sha(code) == expected_sha, 'exact sealed camera/metric source; no oracle threshold edits')
    tree = ast.parse(code, filename=str(source))
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'metrics']
    need(len(nodes) == 1, 'one exact original metrics function')
    namespace = {'np': np}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), 'exec'), namespace)
    return namespace['metrics']


def same_surface_detail(value, reference, ids, crop):
    x,y,w,h = crop
    out, ref, surface = value[y:y+h,x:x+w,:3].astype(np.float64), reference[y:y+h,x:x+w].astype(np.float64), ids[y:y+h,x:x+w]
    numerator = denominator = square_error = 0.
    count = 0
    for axis in (0,1):
        valid = np.diff(surface.astype(np.int32),axis=axis) == 0
        actual, target = np.diff(out,axis=axis)[valid], np.diff(ref,axis=axis)[valid]
        numerator += float(np.sum(actual*target))
        denominator += float(np.sum(target*target))
        square_error += float(np.sum((actual-target)**2))
        count += int(valid.sum())
    return dict(adjacent_pairs=count, reference_gradient_energy=denominator,
        gradient_projection_ratio=numerator/denominator if denominator else None,
        rgb_gradient_rmse=float(np.sqrt(square_error/(3*count))) if count else None)


def cohort_metrics(output, reference, masks):
    out, ref = output[...,:3].astype(np.float64), reference.astype(np.float64)
    error = out-ref
    chroma = np.stack((error[...,0]-error[...,1],error[...,2]-error[...,1]),-1)
    result = {}
    for name, mask in masks.items():
        if not mask.any():
            continue
        result[name] = dict(pixels=int(mask.sum()), rgb_rmse=float(np.sqrt(np.mean(error[mask]**2))),
            chroma_rmse=float(np.sqrt(np.mean(chroma[mask]**2))),
            absolute_rgb_p99=float(np.quantile(np.abs(error[mask]),.99)),
            absolute_chroma_p99=float(np.quantile(np.abs(chroma[mask]),.99)),
            rgb_energy=float(np.sum(out[mask])), reference_rgb_energy=float(np.sum(ref[mask])))
    return result


def evaluation_masks(data, reference, signal, crop):
    height,width = reference.shape[:2]
    x,y,w,h = crop
    inside = np.zeros((height,width),bool)
    inside[y:y+h,x:x+w] = True
    # Truth defines evaluation cohorts only; it cannot enter Recovery.step.
    spread = neighbourhood(reference,maximum=True)-neighbourhood(reference,minimum=True)
    magnitude = np.maximum(np.abs(neighbourhood(reference)),.01)
    flat = np.max(spread/(magnitude+1e-20),-1) <= .005
    masks = dict(all=inside, flat_reference=inside&flat,
        moving_primary=inside&(np.linalg.norm(data['motion'][...,:2].astype(np.float32)*(width,height),axis=-1) >= 1),
        reveal_first_two=inside&(data['reveal_age'] <= 1), reveal_tail_9_16=inside&(data['reveal_age'] >= 9)&(data['reveal_age'] <= 16))
    if 'outliers_'+signal in data:
        masks['input_noise_event'] = inside&(data['outliers_'+signal] > 0)
    for name in ('below_hemisphere','real_miss'):
        if name in data:
            masks[name] = inside&(data[name] > 0)
    return masks


def aggregate(rows, keys):
    output = {}
    for key in keys:
        output[key] = {}
        for signal in ('spec','diff'):
            values = [row['signals'][signal][key] for row in rows]
            common = {name:float(np.mean([v['original'][name] for v in values])) for name in
                ('rgb_rmse','chroma_rmse','chroma_absolute_p99','detail_gradient_rmse','gradient_projection_ratio')}
            common['same_surface_gradient_projection'] = float(np.mean([v['same_surface']['gradient_projection_ratio'] for v in values]))
            common['same_surface_gradient_rmse'] = float(np.mean([v['same_surface']['rgb_gradient_rmse'] for v in values]))
            cohorts = {}
            for name in sorted(set().union(*(v['cohorts'] for v in values))):
                selected = [v['cohorts'][name] for v in values if name in v['cohorts']]
                count = sum(v['pixels'] for v in selected)
                cohorts[name] = dict(pixels=count,
                    rgb_rmse=float(np.sqrt(sum(v['rgb_rmse']**2*v['pixels'] for v in selected)/count)),
                    chroma_rmse=float(np.sqrt(sum(v['chroma_rmse']**2*v['pixels'] for v in selected)/count)),
                    absolute_rgb_p99_frame_mean=float(np.mean([v['absolute_rgb_p99'] for v in selected])),
                    absolute_chroma_p99_frame_mean=float(np.mean([v['absolute_chroma_p99'] for v in selected])),
                    rgb_energy_ratio=sum(v['rgb_energy'] for v in selected)/max(sum(v['reference_rgb_energy'] for v in selected),1e-30))
            tails = {}
            for age in [str(i) for i in range(9)]+['9..16']:
                selected = [v['original']['reveal_tail'][age] for v in values if age in v['original']['reveal_tail']]
                count = sum(v['pixels'] for v in selected)
                if count:
                    tails[age] = dict(pixels=count,
                        rgb_rmse=float(np.sqrt(sum(v['rgb_rmse']**2*v['pixels'] for v in selected)/count)),
                        positive_stale_energy=sum(v['positive_stale_energy']*v['pixels'] for v in selected)/count,
                        signed_stale_fraction=sum(v['mean_signed_stale_fraction']*v['pixels'] for v in selected)/count)
            output[key][signal] = dict(**common,cohorts=cohorts,reveal_tail=tails)
    return output


def crop_sheet(destination, frame, lighting, reference, crop):
    from PIL import Image, ImageDraw
    x,y,w,h = crop
    names = list(lighting)+['reference']
    sheet = Image.new('RGB',(2*w+180,len(names)*(h+20)),(24,24,24))
    draw = ImageDraw.Draw(sheet)
    for row,name in enumerate(names):
        draw.text((4,row*(h+20)+4),name,fill=(255,255,255))
        for column,signal in enumerate(('spec','diff')):
            value = reference[signal] if name == 'reference' else lighting[name][signal]
            rgb = value[y:y+h,x:x+w,:3].astype(np.float32)
            # One fixed display transform for every candidate/frame; no auto gain.
            pixels = np.rint(np.clip(rgb*3,0,1)**(1/2.2)*255).astype(np.uint8)
            sheet.paste(Image.fromarray(pixels),(180+column*w,row*(h+20)+20))
    path = destination/('frame%03d.png'%frame)
    sheet.save(path)
    return dict(file=path.name,sha256=file_sha(path),display_gain=3,gamma=2.2,crop=list(crop))


def peak_resident_bytes():
    import ctypes
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_ = [('cb',wintypes.DWORD),('PageFaultCount',wintypes.DWORD)]+[(name,ctypes.c_size_t) for name in
            ('PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage',
             'QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage')]
    value = Counters()
    value.cb = ctypes.sizeof(value)
    current = ctypes.windll.kernel32.GetCurrentProcess
    current.restype = wintypes.HANDLE
    query = ctypes.windll.psapi.GetProcessMemoryInfo
    query.argtypes = (wintypes.HANDLE,ctypes.POINTER(Counters),wintypes.DWORD)
    query.restype = wintypes.BOOL
    okay = query(current(),ctypes.byref(value),value.cb)
    return int(value.PeakWorkingSetSize) if okay else None


def replay(manifest_path, completed, view_name, output, oracle_source):
    start = time.perf_counter()
    need(output.resolve().is_relative_to(TASK.resolve()) and not output.exists(), 'fresh own-task destination; preserve all prior evidence')
    manifest = json.loads(manifest_path.read_bytes())
    run_info = json.loads((completed/'runs.json').read_bytes())
    need(run_info['prepared_manifest_sha256'] == file_sha(manifest_path), 'signed RR runs match exact prepared data')
    native_seal = run_info
    if 'provider_dll_sha256' not in native_seal:
        native_seal = json.loads((completed.parent/'runs.json').read_bytes())
        need(native_seal['schema'] == 'fsrd-positive-ggx-nearest-surface-v5-signed-runs', 'exact V5 parent signed-run seal')
        need(native_seal['runs'][completed.name] == run_info['runs'][view_name], 'case/parent record is identical, including output hashes')
    need(native_seal['provider_dll_sha256'] == PROVIDER_SHA, 'actual signed AMD1.2 baseline')
    need(view_name in manifest['views'] and view_name in run_info['runs'], 'explicit measured view exists in sealed inputs and signed outputs')
    need(len(manifest['frames']) == 64, 'complete original64-frame history, no selected easy phase')
    metric_sha = manifest.get('camera_source_sha256')
    if metric_sha is None:
        matches = [value for path,value in manifest['source_files'].items()
            if Path(path).name == oracle_source.name]
        need(len(matches) == 1, 'one sealed original camera/metric source')
        metric_sha = matches[0]
    metric = original_metrics(oracle_source,metric_sha)
    native = run_info['runs'][view_name]
    native_directory = Path(native['directory'])
    need(native_directory.resolve().is_relative_to(completed.resolve()), 'sealed actual output directory stays inside declared completed run')
    need(native['debug_errors'] == native['debug_warnings'] == 0, 'baseline native debug errors/warnings zero')
    need(native['effective_words'] == native_seal['probe']['effective_words'], 'same sealed SDK setting bits')
    view, prepared = Path(manifest['views'][view_name]), manifest_path.parent
    physical = None
    if 'physical_case' in manifest:
        physical_root = Path(manifest['physical_case'])
        physical_path = physical_root/'ggx-sequence.json'
        need(file_sha(physical_path) == manifest['physical_manifest_sha256'], 'shared physical source manifest remains immutable')
        physical = json.loads(physical_path.read_bytes())
        need(len(physical['frames']) == len(manifest['frames']), 'physical/demod histories align')
    models = {name:{signal:(RRBandGainRecovery(settings) if isinstance(settings,BandGainSettings) else
        LobeReferenceRecovery(settings) if isinstance(settings,ReferenceSettings) else Recovery(settings))
        for signal in ('spec','diff')} for name,settings in VARIANTS.items()}
    replay_bytes = (view/'native-replay.txt').read_bytes()
    need(sha(replay_bytes) == manifest['native_replay']['sha256'], 'sealed whole-history camera/jitter table')
    replay_rows = [line.split() for line in replay_bytes.decode('ascii').splitlines() if line.strip()]
    need([int(word) for word in replay_rows[0]] == [64,manifest['width'],manifest['height']], 'complete declared replay extent')
    need([int(row[0]) for row in replay_rows[1:]] == [f['frame'] for f in manifest['frames']], 'camera rows align with every submitted frame')
    jitters = {int(row[0]):tuple(float(word) for word in row[-2:]) for row in replay_rows[1:]}
    rows,images = [],[]
    uncertainty = {name:{signal:PairedMSE(manifest['comparison_crop']) for signal in ('spec','diff')} for name in VARIANTS}
    if physical is not None:
        for by_signal in uncertainty.values():
            by_signal['physical_spec'] = PairedMSE(manifest['comparison_crop'])
    output.mkdir(parents=True)
    for index,frame in enumerate(manifest['frames']):
        folder = prepared/'dataset'/frame['directory']
        derived = set(frame.get('derived_names',()))
        data = {name:load((physical_root/'dataset'/frame['directory'] if physical is not None and name not in derived else folder),record)
            for name,record in frame['payloads'].items()}
        # A view may change only declared roughness for V4's mismatch control.
        # Validate the actual GPU-bound bytes rather than assuming source normals.
        for name in ('spec','diff','depth','motion','normals'):
            path = view/frame['directory']/(name+'.bin')
            raw = path.read_bytes()
            if view_name == 'negative-r012' and name == 'normals':
                actual = np.frombuffer(raw,'<u4').reshape(data[name].shape)
                expected = (data[name] & np.uint32(~(1023<<20)&0xffffffff)) | np.uint32(123<<20)
                need(np.array_equal(actual,expected), 'V4 mismatch changes ONLY declared native roughness bits to123')
                data[name] = actual
            else:
                need(sha(raw) == frame['payloads'][name]['sha256'], 'actual selected view inputs equal sealed source bytes')
        references = {signal:data['reference_'+signal] for signal in ('spec','diff')}
        lighting = dict(noisy_input={signal:data[signal] for signal in ('spec','diff')},rr={})
        row = dict(frame=frame['frame'],signals={signal:{} for signal in ('spec','diff')},operator={})
        for signal in ('spec','diff'):
            path = native_directory/frame['directory']/(signal+'.bin')
            raw = path.read_bytes()
            need(sha(raw) == native['outputs'][str(frame['frame'])][signal], 'every actual signed output hash unchanged')
            rr = np.frombuffer(raw,'<f2').reshape(data[signal].shape)
            need(np.isfinite(rr).all(), 'all actual output components finite')
            lighting['rr'][signal] = rr
            for name,by_signal in models.items():
                begin = time.perf_counter()
                kwargs = dict(jitter=jitters[frame['frame']]) if isinstance(by_signal[signal],LobeReferenceRecovery) else {}
                recovered = by_signal[signal].step(data[signal],rr,data['depth'],data['normals'],data['motion'],frame['frame'],reset=index==0,**kwargs)
                seconds = time.perf_counter()-begin
                need(np.array_equal(recovered[...,3],rr[...,3]), 'recovery never changes opaque destination alpha')
                need(np.isfinite(recovered).all() and np.all(recovered[...,:3]>=0), 'finite nonnegative recovered linear lobe')
                if index < 7 or view_name == 'mirror-r0':
                    need(np.array_equal(recovered,rr), 'cold/reset and R0 ordinary-recovery controls are byte exact no-ops')
                lighting.setdefault(name,{})[signal] = recovered
                row['operator'].setdefault(name,{})[signal] = dict(**by_signal[signal].last_stats,cpu_numpy_seconds=seconds)
        for signal in ('spec','diff'):
            ids = data['object'].astype(np.int32)
            if signal == 'spec' and 'secondary_object' in data:
                ids = ids*3+data['secondary_object']
            masks = evaluation_masks(data,references[signal],signal,manifest['comparison_crop'])
            replicas = dict(mean=references[signal])
            for label in ('a','b'):
                if 'reference_'+signal+'_'+label in data:
                    replicas[label] = data['reference_'+signal+'_'+label]
            for name in VARIANTS:
                uncertainty[name][signal].update(index,lighting['rr'][signal],lighting[name][signal],replicas)
            for name,by_signal in lighting.items():
                row['signals'][signal][name] = dict(original=metric(by_signal[signal],references[signal],data['reveal_age'],
                    data['ghost_'+signal],manifest['comparison_crop']), same_surface=same_surface_detail(by_signal[signal],
                    references[signal],ids,manifest['comparison_crop']),cohorts=cohort_metrics(by_signal[signal],references[signal],masks))
        if physical is not None:
            old = physical['frames'][index]
            need(old['frame'] == frame['frame'] and old['directory'] == frame['directory'], 'exact physical/reference frame alignment')
            physical_data = {name:load(physical_root/'dataset'/old['directory'],old['payloads'][name]) for name in
                ('reference_spec','reference_spec_a','reference_spec_b','ghost_spec')}
            qs = data['spec_albedo'][...,:3].astype(np.float64)/255
            need(np.all(qs>0), 'exact positive quantized guide; no epsilon remodulation')
            physical_lighting = {name:dict(spec=by_signal['spec'][...,:3].astype(np.float64)*qs,diff=by_signal['diff'])
                for name,by_signal in lighting.items()}
            physical_references = dict(spec=physical_data['reference_spec'],diff=references['diff'])
            row['physical_signals'] = dict(spec={},diff=row['signals']['diff'])
            ids = data['object'].astype(np.int32)*3+data['secondary_object']
            masks = evaluation_masks(data,physical_references['spec'],'spec',manifest['comparison_crop'])
            replicas = dict(mean=physical_data['reference_spec'],a=physical_data['reference_spec_a'],b=physical_data['reference_spec_b'])
            for name,by_signal in physical_lighting.items():
                value = by_signal['spec']
                row['physical_signals']['spec'][name] = dict(original=metric(value,physical_references['spec'],data['reveal_age'],
                    physical_data['ghost_spec'],manifest['comparison_crop']),same_surface=same_surface_detail(value,
                    physical_references['spec'],ids,manifest['comparison_crop']),cohorts=cohort_metrics(value,physical_references['spec'],masks))
                if name in VARIANTS:
                    uncertainty[name]['physical_spec'].update(index,physical_lighting['rr']['spec'],value,replicas)
            if frame['frame'] in (28,33,65):
                physical_crops = output/'physical-crops'
                physical_crops.mkdir(exist_ok=True)
                images.append(dict(domain='remodulated_physical',**crop_sheet(physical_crops,frame['frame'],physical_lighting,
                    physical_references,manifest['comparison_crop'])))
        rows.append(row)
        if frame['frame'] in (28,33,65):
            images.append(crop_sheet(output,frame['frame'],lighting,references,manifest['comparison_crop']))
    names = ['noisy_input','rr',*VARIANTS]
    phases = dict(first_reset=rows[:1],cold_history=rows[:7],jittered_static=rows[1:16],
        camera_and_object=rows[16:48],camera_only=rows[48:56],settled_tail=rows[56:])
    paths = [Path(__file__),Path(__file__).with_name('fsrd_nrd_recovery_prototype.py'),
        Path(__file__).with_name('fsrd_nrd_lobe_reference_prototype.py'),
        Path(__file__).with_name('fsrd_nrd_rr_band_gain_prototype.py'),
        Path(__file__).with_name('fsrd_nrd_recovery_uncertainty.py')]
    result = dict(schema='fsrd-separate-nrd-lobe-recovery-cpu-v1',manifest=str(manifest_path),manifest_sha256=file_sha(manifest_path),
        actual_signed_runs=str(completed/'runs.json'),actual_signed_runs_sha256=file_sha(completed/'runs.json'),
        native_provider_sha256=PROVIDER_SHA,native_executable_sha256=native_seal['executable_sha256'],
        view=view_name,seed=manifest.get('seed',manifest.get('input_seed')),variants={name:asdict(settings) for name,settings in VARIANTS.items()},
        paired_reference_uncertainty={name:{signal:value.summarize() for signal,value in by_signal.items()} for name,by_signal in uncertainty.items()},
        dataset_contract={key:manifest[key] for key in ('schema','roughness','noisy_sampling','reference_sampling','albedo_guide','units','native_nrd_paired') if key in manifest},
        scripts={str(path):file_sha(path) for path in paths},summaries=aggregate(rows,names),
        physical_summaries=(aggregate([dict(signals=row['physical_signals']) for row in rows],names) if physical is not None else None),
        phases={name:aggregate(values,names) for name,values in phases.items()},frames=rows,crops=images,
        checks=CHECKS,elapsed_seconds=time.perf_counter()-start,peak_resident_bytes=peak_resident_bytes(),
        gpu_executed=False,compiler_executed=False,native_parity_measured=False,game_fps_measured=False,
        all_light_passed_through_rr=True,oracle_arrays_used_by_operator=False,quality_improvement_asserted=False,
        scope='CPU FP32 history with half final outputs over hashed actual signed-RR RGB; native output alpha preserved. This is not a native shader or game-quality measurement.',
        qualification=('diagnostic_only_zero_roughness_or_mismatched_mirror' if 'mirror-v4' in str(manifest_path) else 'synthetic_positive_GGX_domain_declared_in_dataset_contract_not_nativeRecon_parity'))
    (output/'comparison.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--completed',type=Path,required=True)
    parser.add_argument('--view',required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--oracle-source',type=Path,default=Path(__file__).resolve().parent / 'fsrd_nrd_motion_quality_oracle_v1_frozen.py')
    args = parser.parse_args()
    result = replay(args.manifest,args.completed,args.view,args.output,args.oracle_source)
    brief = {name:{signal:{key:values[key] for key in ('rgb_rmse','chroma_rmse','same_surface_gradient_projection')}
        for signal,values in signals.items()} for name,signals in result['summaries'].items()}
    print(json.dumps(dict(view=result['view'],checks=result['checks'],elapsed_seconds=result['elapsed_seconds'],
        peak_resident_bytes=result['peak_resident_bytes'],qualification=result['qualification'],summaries=brief),indent=2))


if __name__ == '__main__':
    main()
