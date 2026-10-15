"""Actual NEW recovery graph research, ONLY after a lead compiler/GPU grant.

Default is source/layout preparation, never compilation or GPU. --run must be
inside lead_ops/run_task_test.py WITHOUT --cpu. It compiles the complete three
shaders, tests an odd-size deterministic history, runs BOTH immutable positive
GGX signed-RR histories, then measures the whole13-pass graph at1505/2560.
"""
import argparse
import json
import os
from pathlib import Path
import struct
import subprocess
import time

import numpy as np

from fsrd_gpu_chain import ChainJob
from fsrd_nrd_lobe_recovery_graph import LobeGraph,compile_shaders,PRE,STORAGE
from fsrd_nrd_lobe_reference_prototype import LobeReferenceRecovery,ReferenceSettings
from fsrd_nrd_recovery_uncertainty import PairedMSE
import fsrd_nrd_recovery_replay as analysis

TASK = Path('F:/FSRD/sol_batch/15b-inputs')
CHECKS = 0


def need(value,message):
    global CHECKS
    CHECKS += 1
    if not bool(value):raise AssertionError(message)


def write_json(path,value):
    path.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n',encoding='utf-8')


class BoundedRunner:
    def __init__(self,executable):
        self.executable = executable
        self.runs = []

    def run_runner(self,job):
        from test_fsrd_nrd_bridge_rr import bounded_run
        text,peak,elapsed,log = bounded_run([str(self.executable),str(job)],job.parent/'native')
        self.runs.append(dict(job=str(job),native_seconds=elapsed,peak_resident_bytes=peak,log=str(log)))
        return subprocess.CompletedProcess([str(self.executable),str(job)],0,text,'')


def texture_inputs(job,prefix,arrays):
    return {name:job.texture(prefix+'_'+name,array,format=24 if name=='normals' else 41 if name=='depth' else 10,
                            size=(array.shape[1],array.shape[0])) for name,array in arrays.items()}


def checked_run(job,runner,repetitions=1,warmup=0):
    outputs,metadata = job.run(repetitions=repetitions,warmup=warmup,keep_staging=True)
    need('validation_errors' in metadata['counters'] and 'validation_warnings' in metadata['counters'], 'actual native debug counters present')
    need(metadata['counters']['validation_errors'] == metadata['counters']['validation_warnings'] == 0, 'zero actual D3D12 errors AND warnings')
    need(runner.runs[-1]['peak_resident_bytes'] < 2_500_000_000, 'bounded actual native RSS below2.5GB')
    return outputs,metadata


def deterministic_history(directory,shaders,runner,storage='fp32'):
    job = ChainJob(directory,runner)
    width,height = 33,29
    graph = LobeGraph(job,shaders,width,height,prefix='odd',storage=storage)
    cpu = {signal:LobeReferenceRecovery(ReferenceSettings(bound_projection='local_anchor',texture_storage=storage)) for signal in ('spec','diff')}
    expected,outputs = [],[]
    yy,xx = np.mgrid[:height,:width]
    for index in range(24):
        rr = np.full((height,width,4),.5,'<f2');rr[...,3]=7
        raw = rr.copy()
        raw[...,:3] += np.where((xx+yy)%2,.0625,-.0625)[...,None].astype('<f2')
        rr[...,:3] += np.where((xx+yy)%2,.03125,-.03125)[...,None].astype('<f2')
        raw[...,3]=9
        depth = np.full((height,width),-8 if index<12 else -3,'<f4')
        normal = np.full((height,width),512|(512<<10)|((0 if index>=20 else 123)<<20),'<u4')
        motion = np.zeros((height,width,4),'<f2');motion[...,3]=1
        arrays = dict(spec=raw,diff=raw,rr_spec=rr,rr_diff=rr,depth=depth,normals=normal,motion=motion)
        inputs = texture_inputs(job,'f%d'%index,arrays)
        outputs.append(graph.record(index,inputs))
        expected.append({s:cpu[s].step(raw,rr,depth,normal,motion,index,reset=index==0) for s in cpu})
    actual,metadata = checked_run(job,runner)
    for index,frame in enumerate(expected):
        for signal,reference in frame.items():
            value = actual[outputs[index][signal]]
            need(np.array_equal(value[...,3],reference[...,3]), 'GPU graph preserves opaque RR alpha exactly')
            need(np.isfinite(value).all() and np.all(value[...,:3]>=0), 'finite nonnegative GPU output')
            need(np.array_equal(value,reference), 'noise-free binary odd-size fullgraph CPU/GPU words exact for declared storage, including cold/depthjump/R0')
    return dict(metadata=metadata,native=runner.runs[-1],frames=24,passes=len(job.passes),checks=CHECKS,
                packed_native_payload_bytes=graph.allocated_native_bytes())


def case_contract(manifest_path,completed,view):
    manifest = json.loads(manifest_path.read_bytes())
    case = json.loads((completed/'runs.json').read_bytes())
    seal = json.loads((completed.parent/'runs.json').read_bytes())
    native = case['runs'][view]
    need(case['prepared_manifest_sha256'] == analysis.file_sha(manifest_path), 'exact frozen positiveGGX manifest')
    need(seal['provider_dll_sha256'] == analysis.PROVIDER_SHA, 'exact signed AMD1.2 data')
    need(seal['runs'][completed.name] == native, 'case/parent signed-native records identical')
    need(native['debug_errors'] == native['debug_warnings'] == 0, 'baseline signed-provider debug clean')
    need(native['effective_words'] == seal['probe']['effective_words'], 'unchanged effective SDK bits')
    physical_root = Path(manifest['physical_case'])
    physical_path = physical_root/'ggx-sequence.json'
    need(analysis.file_sha(physical_path) == manifest['physical_manifest_sha256'], 'shared physical reference unchanged')
    physical = json.loads(physical_path.read_bytes())
    native_directory = Path(native['directory'])
    need(native_directory.resolve().is_relative_to(completed.resolve()), 'native output read stays inside declared run')
    view_directory = Path(manifest['views'][view])
    table = (view_directory/'native-replay.txt').read_bytes()
    need(analysis.sha(table) == manifest['native_replay']['sha256'], 'exact original camera/jitter table')
    rows = [line.split() for line in table.decode('ascii').splitlines()[1:] if line.strip()]
    need([int(row[0]) for row in rows] == [frame['frame'] for frame in manifest['frames']], 'complete camera chronology')
    jitters = [np.asarray([float(v) for v in row[-2:]],np.float32) for row in rows]
    return manifest,case,seal,native,physical_root,physical,native_directory,view_directory,jitters


def load_case_frame(prepared,manifest,physical_root,frame,native,native_directory,view_directory):
    derived = set(frame.get('derived_names',()))
    data = {name:analysis.load((prepared if name in derived else physical_root)/'dataset'/frame['directory'],record)
            for name,record in frame['payloads'].items()}
    for name in ('spec','diff','depth','motion','normals'):
        need(analysis.file_sha(view_directory/frame['directory']/(name+'.bin')) == frame['payloads'][name]['sha256'], 'exact actual GPU-bound input bytes')
    for signal in ('spec','diff'):
        path = native_directory/frame['directory']/(signal+'.bin')
        need(analysis.file_sha(path) == native['outputs'][str(frame['frame'])][signal], 'unchanged actual signed-RR RGB/alpha')
        data['rr_'+signal] = np.fromfile(path,'<f2').reshape(data[signal].shape)
    return data


def real_history(directory,shaders,runner,manifest_path,completed,view,storage='fp32',baseline=None):
    contract = case_contract(manifest_path,completed,view)
    manifest,case,seal,native,physical_root,physical,native_directory,view_directory,jitters = contract
    width,height = manifest['width'],manifest['height']
    job = ChainJob(directory,runner)
    graph = LobeGraph(job,shaders,width,height,prefix='real',storage=storage)
    cpu = {s:LobeReferenceRecovery(ReferenceSettings(bound_projection='local_anchor',texture_storage=storage)) for s in ('spec','diff')}
    expected,outputs = [],[]
    for index,frame in enumerate(manifest['frames']):
        data = load_case_frame(manifest_path.parent,manifest,physical_root,frame,native,native_directory,view_directory)
        inputs = texture_inputs(job,frame['directory'],{name:data[name] for name in ('spec','diff','rr_spec','rr_diff','depth','normals','motion')})
        jitter_delta = (jitters[index-1]-jitters[index])/(width,height) if index else np.zeros(2)
        outputs.append(graph.record(index,inputs,jitter=jitters[index],jitter_delta_uv=jitter_delta))
        expected.append({s:cpu[s].step(data[s],data['rr_'+s],data['depth'],data['normals'],data['motion'],frame['frame'],
            reset=index==0,jitter=jitters[index]) for s in cpu})
    actual,metadata = checked_run(job,runner)
    uncertainty = {signal:PairedMSE(manifest['comparison_crop']) for signal in ('spec','diff','physical_spec')}
    storage_uncertainty = {signal:PairedMSE(manifest['comparison_crop']) for signal in uncertainty} if baseline else {}
    rows = []
    for index,frame in enumerate(manifest['frames']):
        data = load_case_frame(manifest_path.parent,manifest,physical_root,frame,native,native_directory,view_directory)
        row = dict(frame=frame['frame'],signals={},cpu_comparison={})
        prior_outputs = {}
        for signal in ('spec','diff'):
            value,reference = actual[outputs[index][signal]],expected[index][signal]
            rr = data['rr_'+signal]
            need(np.array_equal(value[...,3],rr[...,3]), 'actual recovery never changes opaque alpha')
            need(np.isfinite(value).all() and np.all(value[...,:3]>=0), 'actual GPU recovered RGB finite/nonnegative')
            if index<7:need(np.array_equal(value,rr), 'first/reset seven cold frames exact RR no-op')
            # A full stochastic graph can branch at rounded Wiener thresholds.
            # Report its measured CPU error honestly; exact word parity is
            # required above for deterministic binary histories, not invented.
            error = value[...,:3].astype(np.float64)-reference[...,:3].astype(np.float64)
            row['cpu_comparison'][signal] = dict(rgb_rmse=float(np.sqrt(np.mean(error*error))),
                max_abs_error=float(np.max(np.abs(error))),equal_rgb_words=int(np.sum(value[...,:3].view('<u2')==reference[...,:3].view('<u2'))))
            replicas = dict(mean=data['reference_'+signal])
            for suffix in ('a','b'):
                if 'reference_'+signal+'_'+suffix in data:replicas[suffix]=data['reference_'+signal+'_'+suffix]
            uncertainty[signal].update(index,rr,value,replicas)
            if baseline:
                prior_case=baseline['result']['cases'][str(int(view.split('-')[1][1:]))]
                prior_row=prior_case['frames'][index]
                prior_path=baseline['root']/('demod-r%d'%int(view.split('-')[1][1:]))/(frame['directory']+'_'+signal+'_recovered.bin')
                need(prior_row['frame']==frame['frame'] and analysis.file_sha(prior_path)==prior_row['output_sha256'][signal], 'sealed FP32 output chronology/hash unchanged')
                prior=np.fromfile(prior_path,'<f2').reshape(value.shape)
                need(np.array_equal(value[...,3],prior[...,3]), 'storage experiment never changes opaque FP32 baseline alpha')
                prior_outputs[signal]=prior
                delta=value[...,:3].astype(np.float64)-prior[...,:3].astype(np.float64)
                row.setdefault('fp32_comparison',{})[signal]=dict(rgb_rmse=float(np.sqrt(np.mean(delta*delta))),
                    max_abs_error=float(np.max(np.abs(delta))),equal_rgb_words=int(np.sum(value[...,:3].view('<u2')==prior[...,:3].view('<u2'))))
                storage_uncertainty[signal].update(index,prior,value,replicas)
            ids = data['object'].astype(np.int32)*(3 if signal=='spec' else 1)
            if signal=='spec':ids+=data['secondary_object']
            masks = analysis.evaluation_masks(data,replicas['mean'],signal,manifest['comparison_crop'])
            metric_sha = next(v for k,v in manifest['source_files'].items() if Path(k).name=='fsrd_nrd_motion_quality_oracle.py')
            metric = analysis.original_metrics(Path('F:/OptiRevelations/OSA-15-nrd-ghosting/OptiScaler/shaders/shader_tools/tests/fsrd_nrd_motion_quality_oracle.py'),metric_sha)
            row['signals'][signal] = {name:dict(original=metric(image,replicas['mean'],data['reveal_age'],data['ghost_'+signal],manifest['comparison_crop']),
                same_surface=analysis.same_surface_detail(image,replicas['mean'],ids,manifest['comparison_crop']),
                cohorts=analysis.cohort_metrics(image,replicas['mean'],masks)) for name,image in (('rr',rr),('recovery_gpu',value),('recovery_cpu',reference))}
            path = directory/(frame['directory']+'_'+signal+'_recovered.bin')
            path.write_bytes(value.tobytes())
            row.setdefault('output_sha256',{})[signal]=analysis.file_sha(path)
        physical_frame = physical['frames'][index]
        physical_data = {name:analysis.load(physical_root/'dataset'/frame['directory'],physical_frame['payloads'][name])
                         for name in ('reference_spec','reference_spec_a','reference_spec_b')}
        qs = data['spec_albedo'][...,:3].astype(np.float64)/255
        uncertainty['physical_spec'].update(index,data['rr_spec'][...,:3]*qs,actual[outputs[index]['spec']][...,:3]*qs,
            dict(mean=physical_data['reference_spec'],a=physical_data['reference_spec_a'],b=physical_data['reference_spec_b']))
        if baseline:storage_uncertainty['physical_spec'].update(index,prior_outputs['spec'][...,:3]*qs,actual[outputs[index]['spec']][...,:3]*qs,
            dict(mean=physical_data['reference_spec'],a=physical_data['reference_spec_a'],b=physical_data['reference_spec_b']))
        rows.append(row)
    result = dict(schema='fsrd-separate-nrd-native-recovery-graph-v1',manifest_sha256=analysis.file_sha(manifest_path),
        signed_run_seal_sha256=analysis.file_sha(completed/'runs.json'),signal_domain=case['signal_domain'],
        native_provider_sha256=seal['provider_dll_sha256'],native_baseline_executable_sha256=seal['executable_sha256'],
        frames=rows,storage=storage,storage_formats=graph.formats,paired_uncertainty={s:u.summarize() for s,u in uncertainty.items()},
        storage_paired_uncertainty={s:u.summarize() for s,u in storage_uncertainty.items()},
        summaries=analysis.aggregate(rows,['rr','recovery_gpu','recovery_cpu']),
        graph=metadata,native=runner.runs[-1],passes=len(job.passes),packed_native_payload_bytes=graph.allocated_native_bytes(),
        all_light_passed_rr=True,oracle_inputs_enter_recovery=False,game_quality_claimed=False,checks=CHECKS)
    if baseline:
        prior_case=baseline['result']['cases'][str(int(view.split('-')[1][1:]))]
        result['noise_and_reveal_comparison_to_fp32']={}
        for signal in ('spec','diff'):
            old=prior_case['summaries']['recovery_gpu'][signal]
            new=result['summaries']['recovery_gpu'][signal]
            pairs={name:(old[name],new[name]) for name in ('chroma_rmse','chroma_absolute_p99')}
            for cohort in ('flat_reference','below_hemisphere','real_miss','reveal_first_two','reveal_tail_9_16'):
                if cohort in old['cohorts']:
                    pairs.update({cohort+'.'+name:(old['cohorts'][cohort][name],new['cohorts'][cohort][name])
                        for name in ('rgb_rmse','chroma_rmse','absolute_rgb_p99_frame_mean','absolute_chroma_p99_frame_mean')})
            pairs.update({'stale_age'+age:(old['reveal_tail'][age]['positive_stale_energy'],new['reveal_tail'][age]['positive_stale_energy'])
                for age in old['reveal_tail']})
            result['noise_and_reveal_comparison_to_fp32'][signal]={name:dict(fp32=a,mixed=b,delta=b-a,increased=b>a) for name,(a,b) in pairs.items()}
    write_json(directory/'comparison.json',result)
    return result


def measure(directory,shaders,runner,width,height,storage='fp32'):
    yy,xx = np.mgrid[:height,:width]
    rr = np.full((height,width,4),.5,'<f2');rr[...,3]=7
    raw = rr.copy();raw[...,:3] += np.where((xx+yy)%2,.0625,-.0625)[...,None].astype('<f2');raw[...,3]=9
    rr[...,:3] += np.where((xx+yy)%2,.03125,-.03125)[...,None].astype('<f2')
    motion = np.zeros((height,width,4),'<f2');motion[...,3]=1
    arrays = dict(spec=raw,diff=raw,rr_spec=rr,rr_diff=rr,depth=np.full((height,width),-8,'<f4'),
        normals=np.full((height,width),512|(512<<10)|(123<<20),'<u4'),motion=motion)
    job = ChainJob(directory,runner)
    inputs = texture_inputs(job,'timing',arrays)
    graph = LobeGraph(job,shaders,width,height,prefix='timing',storage=storage)
    for index in range(2):graph.record(index,inputs,history_valid=True,readback=False)
    need(graph.allocated_native_bytes()<1_600_000_000, 'packed GPU+upload payload known before native allocation; bounded single job')
    _,metadata = checked_run(job,runner,repetitions=16,warmup=4)
    samples = metadata['samples']
    names = [p['name'] for p in job.passes]
    need(all(name in samples for name in names), 'every actual dispatch timestamp sample present')
    total = np.stack([samples[name] for name in names]).sum(0)/2
    result = dict(width=width,height=height,storage=storage,storage_formats=graph.formats,thirteen_pass_median_ms=float(np.median(total)),
        thirteen_pass_p95_ms=float(np.quantile(total,.95)),samples_ms=total.tolist(),graph=metadata,native=runner.runs[-1],
        packed_native_payload_bytes=graph.allocated_native_bytes(),scope='actual all-active synthetic compute graph cost; no provider/Commit/title/hook/FPS timing claim')
    write_json(directory/'timing-summary.json',result)
    return result


def reuse_artifacts(path):
    need(path.resolve().is_relative_to(TASK.resolve()), 'reuse only sealed own-task native artifacts')
    result=json.loads(path.read_bytes())
    need(result['gpu_executed'] and result.get('storage','fp32')=='fp32', 'controlled storage experiment uses completed FP32 baseline')
    shaders=result['shaders']
    for role,record in shaders.items():
        need(analysis.file_sha(Path(record['output']))==record['dxil_sha256'], 'same immutable compiled '+role+' CSO')
        need(all(analysis.file_sha(Path(source))==digest for source,digest in record['source_sha256'].items()), 'shader arithmetic/source snapshots unchanged')
    executable=path.parent.parent/'fsrd_gpu_runner.exe'
    need(analysis.file_sha(executable)==result['runner_sha256'], 'same immutable native runner executable')
    return shaders,executable,dict(root=path.parent,result=result,manifest=str(path),sha256=analysis.file_sha(path))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',action='store_true')
    parser.add_argument('--skip-timing',action='store_true')
    parser.add_argument('--storage',choices=tuple(STORAGE),default='fp32')
    parser.add_argument('--reuse-fp32',type=Path)
    parser.add_argument('--output',type=Path)
    args = parser.parse_args()
    if not args.run:
        reused = reuse_artifacts(args.reuse_fp32)[2] if args.reuse_fp32 else None
        print(json.dumps(dict(source_only=True,graph_passes=13,cb_bytes=128,storage=args.storage,storage_formats=STORAGE[args.storage],
            reused_fp32_manifest_sha256=reused['sha256'] if reused else None,
            source_sha256={str(path):analysis.file_sha(path) for path in sorted(PRE.glob('FSRDNrdLobeRecovery*.*'))},
            compiler_executed=False,gpu_executed=False),indent=2));return
    need('FSRD_GPU_TEST_OUTPUT' in os.environ, 'explicit lead wrapper GPU output required; no unguarded native execution')
    output = args.output or Path(os.environ['FSRD_GPU_TEST_OUTPUT'])/'recovery-graph'
    need(output.resolve().is_relative_to(TASK.resolve()) and not output.exists(), 'fresh own scratch keeps all negative artifacts')
    output.mkdir(parents=True)
    need((args.storage=='mixed')==(args.reuse_fp32 is not None), 'mixed experiment requires explicit immutable FP32 artifact reuse; baseline remains fresh')
    if args.reuse_fp32:
        shaders,executable,baseline=reuse_artifacts(args.reuse_fp32)
    else:
        import run_fsrd_gpu_tests as native_runner
        native_runner.build_runner()
        shaders=compile_shaders(output/'compiled')
        executable,baseline=native_runner.runner,None
    runner = BoundedRunner(executable)
    result = dict(schema='fsrd-nrd-lobe-recovery-full-native-v1',shaders=shaders,
        runner_sha256=analysis.file_sha(executable),script_sha256=analysis.file_sha(Path(__file__)),storage=args.storage,storage_formats=STORAGE[args.storage],
        reused_fp32_manifest=(dict(path=baseline['manifest'],sha256=baseline['sha256']) if baseline else None),
        toy=deterministic_history(output/'binary-odd-history',shaders,runner,args.storage),cases={},timings=[])
    for code in (123,307):
        root = Path('F:/FSRD/sol_batch/15c-rr')
        result['cases'][str(code)] = real_history(output/('demod-r%d'%code),shaders,runner,
            root/('ggx-v5-demod/r%d/ggx-sequence.json'%code),root/('ggx-v5-rr-run1/demod-r%d'%code),'ggx-r%d-demod'%code,args.storage,baseline)
    if not args.skip_timing:
        for width,height in ((1505,847),(2560,1440)):
            result['timings'].append(measure(output/('cost-%dx%d'%(width,height)),shaders,runner,width,height,args.storage))
    result.update(checks=CHECKS,gpu_executed=True,compiler_executed=baseline is None)
    write_json(output/'result.json',result)
    print(json.dumps(dict(output=str(output),checks=CHECKS,toy_passes=result['toy']['passes'],
        cases={k:v['paired_uncertainty'] for k,v in result['cases'].items()},
        timings=[{k:v[k] for k in ('width','height','thirteen_pass_median_ms','thirteen_pass_p95_ms')} for v in result['timings']]),indent=2))


if __name__ == '__main__':main()
