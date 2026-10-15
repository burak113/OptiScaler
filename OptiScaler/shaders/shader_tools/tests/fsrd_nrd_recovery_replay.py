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


PROVIDER_SHA = '48f1e5888ba6a0a3d59a98b9751e37c392b0f7b8c223d0082d5c1f40642879d3'
TASK = Path('F:/FSRD/sol_batch/15b-inputs')
VARIANTS = {
    'paired-3sigma-anchor4': Settings(),
    'paired-3sigma-no-anchor': Settings(anchor=0),
    'paired-luma-3sigma-anchor4': Settings(luma_only=True),
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
    okay = ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.windll.kernel32.GetCurrentProcess(),ctypes.byref(value),value.cb)
    return int(value.PeakWorkingSetSize) if okay else None


def replay(manifest_path, completed, view_name, output, oracle_source):
    start = time.perf_counter()
    need(output.resolve().is_relative_to(TASK.resolve()) and not output.exists(), 'fresh own-task destination; preserve all prior evidence')
    manifest = json.loads(manifest_path.read_bytes())
    run_info = json.loads((completed/'runs.json').read_bytes())
    need(run_info['prepared_manifest_sha256'] == file_sha(manifest_path), 'signed RR runs match exact prepared data')
    need(run_info['provider_dll_sha256'] == PROVIDER_SHA, 'actual signed AMD1.2 baseline')
    need(view_name in manifest['views'] and view_name in run_info['runs'], 'explicit measured view exists in sealed inputs and signed outputs')
    need(len(manifest['frames']) == 64, 'complete original64-frame history, no selected easy phase')
    metric = original_metrics(oracle_source,manifest['camera_source_sha256'])
    native = run_info['runs'][view_name]
    need(native['debug_errors'] == native['debug_warnings'] == 0, 'baseline native debug errors/warnings zero')
    need(native['effective_words'] == run_info['probe']['effective_words'], 'same sealed SDK setting bits')
    view, prepared = Path(manifest['views'][view_name]), manifest_path.parent
    models = {name:{signal:Recovery(settings) for signal in ('spec','diff')} for name,settings in VARIANTS.items()}
    rows,images = [],[]
    output.mkdir(parents=True)
    for index,frame in enumerate(manifest['frames']):
        folder = prepared/'dataset'/frame['directory']
        data = {name:load(folder,record) for name,record in frame['payloads'].items()}
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
            path = completed/view_name/frame['directory']/(signal+'.bin')
            raw = path.read_bytes()
            need(sha(raw) == native['outputs'][str(frame['frame'])][signal], 'every actual signed output hash unchanged')
            rr = np.frombuffer(raw,'<f2').reshape(data[signal].shape)
            need(np.isfinite(rr).all(), 'all actual output components finite')
            lighting['rr'][signal] = rr
            for name,by_signal in models.items():
                begin = time.perf_counter()
                recovered = by_signal[signal].step(data[signal],rr,data['depth'],data['normals'],data['motion'],frame['frame'],reset=index==0)
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
            for name,by_signal in lighting.items():
                row['signals'][signal][name] = dict(original=metric(by_signal[signal],references[signal],data['reveal_age'],
                    data['ghost_'+signal],manifest['comparison_crop']), same_surface=same_surface_detail(by_signal[signal],
                    references[signal],ids,manifest['comparison_crop']),cohorts=cohort_metrics(by_signal[signal],references[signal],masks))
        rows.append(row)
        if frame['frame'] in (28,33,65):
            images.append(crop_sheet(output,frame['frame'],lighting,references,manifest['comparison_crop']))
    names = ['noisy_input','rr',*VARIANTS]
    phases = dict(first_reset=rows[:1],cold_history=rows[:7],jittered_static=rows[1:16],
        camera_and_object=rows[16:48],camera_only=rows[48:56],settled_tail=rows[56:])
    paths = [Path(__file__),Path(__file__).with_name('fsrd_nrd_recovery_prototype.py')]
    result = dict(schema='fsrd-separate-nrd-lobe-recovery-cpu-v1',manifest=str(manifest_path),manifest_sha256=file_sha(manifest_path),
        actual_signed_runs=str(completed/'runs.json'),actual_signed_runs_sha256=file_sha(completed/'runs.json'),
        native_provider_sha256=PROVIDER_SHA,native_executable_sha256=run_info['executable_sha256'],
        view=view_name,seed=manifest['seed'],variants={name:asdict(settings) for name,settings in VARIANTS.items()},
        scripts={str(path):file_sha(path) for path in paths},summaries=aggregate(rows,names),
        phases={name:aggregate(values,names) for name,values in phases.items()},frames=rows,crops=images,
        checks=CHECKS,elapsed_seconds=time.perf_counter()-start,peak_resident_bytes=peak_resident_bytes(),
        gpu_executed=False,compiler_executed=False,native_parity_measured=False,game_fps_measured=False,
        all_light_passed_through_rr=True,oracle_arrays_used_by_operator=False,quality_improvement_asserted=False,
        scope='CPU FP32 history with half final outputs over hashed actual signed-RR RGB; native output alpha preserved. This is not a native shader or game-quality measurement.',
        qualification=('diagnostic_only_zero_roughness_or_mismatched_mirror' if 'mirror-v4' in str(manifest_path) else 'verify_nonzero_GGX_reference_before_quality_claim'))
    (output/'comparison.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--completed',type=Path,required=True)
    parser.add_argument('--view',required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--oracle-source',type=Path,default=Path('F:/OptiRevelations/OSA-15-nrd-ghosting/OptiScaler/shaders/shader_tools/tests/fsrd_nrd_motion_quality_oracle.py'))
    args = parser.parse_args()
    result = replay(args.manifest,args.completed,args.view,args.output,args.oracle_source)
    print(json.dumps({key:result[key] for key in ('view','checks','elapsed_seconds','peak_resident_bytes','qualification','summaries')},indent=2))


if __name__ == '__main__':
    main()
