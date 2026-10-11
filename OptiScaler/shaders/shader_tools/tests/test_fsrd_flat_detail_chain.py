"""Flat Detail D3D12 fixture gate, with raw buffers and six-slice histories.

Pass --fixture one or more immutable NPZ/JSON fixture manifests. Compilation is
timed separately. Fixtures provide original Refine RGB/sigma and an independent
NumPy Temporal reference; the full Seed/Refine production parity is a separate
experiment because its inherited FP32/FP16 error should not mask new-pass drift.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import sys
import time
import ctypes
sys.dont_write_bytecode = True
if os.name == "nt":
    ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)
import numpy as np
import run_fsrd_gpu_tests as t
from fsrd_flat_chain import SHADERS, build_chain
from fsrd_gpu_chain import compile_shader


def relative_rmse(actual, expected, mask):
    a=np.asarray(actual,np.float64)[mask];b=np.asarray(expected,np.float64)[mask]
    return float(np.sqrt(np.mean((a-b)**2))/max(np.sqrt(np.mean(b*b)),1e-6))


def check_fixture(manifest_path, shaders, directory):
    manifest_path=Path(manifest_path)
    manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    frames=[];golden=[]
    for item in manifest['frames']:
        path=Path(item['path'])
        if hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:
            raise AssertionError('fixture hash mismatch: '+str(path))
        with np.load(path) as archive:data={name:archive[name] for name in archive.files}
        frame={name:data[name] for name in ('U','V','qs8','qd8','skip','packed','depth','motion','rr','original_reference')}
        frame.update(full=item['full_render_size'],jitter_delta=item['jitter_delta'],
                     reset=item['reset'],frame=item['frame'],cap_id=manifest['name'])
        frames.append(frame);golden.append(data)
    job,names=build_chain(frames,shaders,directory,cached_reference=True,
                         parameters=manifest['parameters'])
    outputs,run=job.run()
    checks=[]
    for frame,expected,n in zip(frames,golden,names):
        flat=((frame['packed']>>30)==1)&(frame['skip'][...,3]!=-1)&np.isfinite(frame['depth'])&(np.abs(frame['depth'])>1e-5)
        error=relative_rmse(outputs[n['temporal']],expected['expected_reference'],flat)
        checks.extend([
            dict(frame=frame['frame'],test='temporal NumPy relative RMSE <= 0.0005',value=error,passed=error<=.0005),
            dict(frame=frame['frame'],test='accepted history count exactly matches',passed=bool(np.array_equal(
                 outputs[n['diagnostics']][...,0][flat],expected['expected_diagnostics'][...,0][flat]))),
            dict(frame=frame['frame'],test='nonflat pixels preserve RR exactly',passed=bool(np.array_equal(
                 outputs[n['composition']][...,:3][~flat],frame['rr'][...,:3][~flat]))),
            dict(frame=frame['frame'],test='finite composition',passed=bool(np.isfinite(outputs[n['composition']]).all()))])
        invalid_confidence=flat & ~np.isfinite(frame['motion'][...,3])
        if np.any(invalid_confidence):
            checks.append(dict(frame=frame['frame'],test='NaN confidence takes exact current reference fallback',
                               pixels=int(np.sum(invalid_confidence)),
                               passed=bool(np.array_equal(outputs[n['temporal']][invalid_confidence],
                                                          frame['original_reference'][invalid_confidence])) and
                                      bool(np.all(outputs[n['diagnostics']][invalid_confidence]==0))))
    slots=sorted(set(item['history_head_before'] for item in manifest['frames']))
    for key in ('reference','motion_depth','normal_lp'):
        a=outputs['history_'+key][slots].astype(np.float32)
        b=golden[-1]['history_'+key][slots].astype(np.float32)
        # LP sums may differ by a few half ULP at tie boundaries; index/validity,
        # log-reference and motion/depth storage must agree much more tightly.
        tolerance=.003 if key=='normal_lp' else .002
        error=float(np.max(np.abs(a-b)))
        checks.append(dict(test='history '+key+' absolute error',value=error,limit=tolerance,passed=error<=tolerance))
    checks.append(dict(test='zero D3D12 validation errors and warnings',passed=
                      run['counters'].get('validation_errors')==0 and run['counters'].get('validation_warnings')==0))
    result=dict(fixture=str(manifest_path),checks=checks,run=run,
                passed=all(item['passed'] for item in checks))
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture',nargs='+',required=True,type=Path)
    parser.add_argument('--output',type=Path,default=t.OUT/'flat_detail_chain')
    parser.add_argument('--runner',type=Path,help='Use an already built runner; shader compilation is still fresh.')
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    kernels={json.loads(path.read_text())['parameters']['cubic_a'] for path in args.fixture}
    if len(kernels)!=1:
        raise ValueError('all fixtures in a run must use the same compiled cubic kernel')
    kernel=kernels.pop()
    compiled={};paths={};start=time.perf_counter()
    if args.runner:t.runner=args.runner
    else:t.build_runner()
    for shader in SHADERS:
        path=args.output/(shader+'.cso')
        defines=()
        # A manifest identifies the actual selected cubic kernel, never a blend substitute.
        if shader=='FSRDFlatTemporal':
            defines=(f'FSRD_TEMPORAL_CUBIC_A={kernel}',)
        compiled[shader]=compile_shader(t.PRE/(shader+'.hlsl'),path,defines)
        paths[shader]=path
    compile_seconds=time.perf_counter()-start
    start=time.perf_counter()
    results=[check_fixture(path,paths,args.output/path.parent.name) for path in args.fixture]
    test_seconds=time.perf_counter()-start
    report=dict(compilation_seconds=compile_seconds,test_seconds=test_seconds,
                runtime_limit_seconds=45,runtime_limit_passed=test_seconds<=45,
                shaders=compiled,results=results,
                passed=all(r['passed'] for r in results) and test_seconds<=45)
    (args.output/'results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(dict(passed=report['passed'],test_seconds=report['test_seconds'],
                          compilation_seconds=compile_seconds)),flush=True)
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
