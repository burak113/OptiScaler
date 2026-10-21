"""Replay deterministic packed inputs through the ACTUAL new HLSL on Windows.

This tests shader parity separately from review/run_native_smoke.py, which tests
the actual native Prepare/Record class. Neither one proves live provider routing,
quality, lifetime integration or performance. No game deployment occurs.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from types import SimpleNamespace

import numpy as np
from fixtures import CASES, make_case, write_fixtures
from verify_output import verify

HERE=Path(__file__).resolve().parent
BASE=HERE.parent
REPO=HERE.parents[4]


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--gpu-lock-root',type=Path,
        default=Path(os.environ['FSRD_GPU_LOCK_ROOT']) if 'FSRD_GPU_LOCK_ROOT' in os.environ else None)
    p.add_argument('--compile-only',action='store_true')
    p.add_argument('--build-child',action='store_true',help=argparse.SUPPRESS)
    args=p.parse_args()
    out=args.output.resolve()
    out.mkdir(parents=True,exist_ok=True)
    receipt=dict(schema='astra10-packed-shader-gpu-v1',platform=platform.platform(),
        python=platform.python_version(),gpu_executed=False,shader_compiled=False,
        quality_accepted=False,cases=[],commands=[],source_sha256={
            str(path.relative_to(BASE)):sha(path) for path in
            (BASE/'native/NativeColourPacked.hlsl',HERE/'packed_model.py',HERE/'fixtures.py',Path(__file__))})
    def finish(status,code):
        receipt['status']=status
        (out/'execution.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(dict(status=status,gpu_executed=receipt['gpu_executed'])))
        return code
    if os.name!='nt': return finish('pending_windows_d3d12_dxc_msvc',2)
    toolpath=REPO/'OptiScaler/shaders/shader_tools'
    sys.path[:0]=[str(toolpath),str(toolpath/'tests')]
    from fsrd_toolchain import compile_cpp,dxc
    from fsrd_gpu_chain import ChainJob
    runner=out/'fsrd_gpu_runner.exe'
    if args.build_child:
        compile_cpp(toolpath/'tests/fsrd_gpu_runner.cpp',runner,('d3d12.lib','dxgi.lib'))
        return 0
    try:
        write_fixtures(out/'fixtures')
        def execute(name,command,timeout=180):
            start=time.perf_counter()
            result=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=timeout)
            log=out/(name+'.log')
            log.write_text(result.stdout+result.stderr,encoding='utf-8')
            receipt['commands'].append(dict(name=name,command=command,exit=result.returncode,
                seconds=time.perf_counter()-start,log_sha256=sha(log)))
            if result.returncode: raise RuntimeError(name+' failed; see '+str(log))
        compiler=Path(dxc())
        shader=BASE/'native/NativeColourPacked.hlsl'
        cso=out/'NativeColourPacked.cso'
        execute('dxc',[str(compiler),'-T','cs_6_2','-E','CSMain','-HV','2021','-Ges','-Gis','-O3',str(shader),'-Fo',str(cso)])
        receipt['shader_compiled']=True
        execute('msvc',[sys.executable,'-B',str(Path(__file__)),'--output',str(out),'--build-child'],300)
        receipt['compiler_sha256']=sha(compiler)
        receipt['runner_sha256']=sha(runner)
        receipt['dxil_sha256']=sha(cso)
        if args.compile_only: return finish('compiled_gpu_pending',0)
        if args.gpu_lock_root is None or not (args.gpu_lock_root/'gpu_lock.py').is_file():
            return finish('compiled_pending_existing_shared_gpu_lock_provider',2)
        sys.path.insert(0,str(args.gpu_lock_root.resolve()))
        from gpu_lock import gpu_lock
        rm=SimpleNamespace(run_runner=lambda path:subprocess.run([str(runner),str(path)],
            capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=60))
        with gpu_lock(os.environ.get('FSRD_GPU_TEST_OWNER','astra10-packed-shader')):
            for name in CASES:
                c=make_case(name)
                j=ChainJob(out/name,rm)
                for label in ('source','raw','selected'):
                    j.raw(label,c['packed'][label].view(np.uint32))
                j.raw('output',c['packed']['initial_output'].view(np.uint32),writable=True,readback=True)
                j.texture('depth',c['depth'],format=41)
                j.texture('normal',c['normal'],format=24)
                j.texture('authority',c['authority'],format=42)
                j.texture('support',c['support'],format=42)
                j.texture('diagnostic',np.zeros_like(c['diagnostic']),format=2,writable=True,readback=True)
                j.compute(name,cso,c['constants'],['source','raw','selected','depth','normal','authority','support'],
                    ['output','diagnostic'],((c['identity'].active_width+7)//8,(c['identity'].active_height+7)//8,1))
                outputs,metadata=j.run(keep_staging=True)
                receipt['gpu_executed']=True
                checks=verify(c,outputs['output'].view(np.uint8))
                np.testing.assert_array_equal(outputs['diagnostic'][...,:2],c['diagnostic'][...,:2])
                counters=metadata['counters']
                assert counters.get('debug_layer')==1,'debug layer not enabled'
                assert counters.get('validation_errors',-1)==0,'D3D12 validation errors'
                assert counters.get('validation_warnings',-1)==0,'D3D12 validation warnings'
                receipt['cases'].append(dict(name=name,host_dispatch_expected=c['decision']=='Ready',
                    shader_failsafe_only=c['decision']!='Ready',checks=checks,adapter=metadata['adapter'],counters=counters))
        return finish('shader_mechanics_passed_quality_rejected',0)
    except Exception as error:
        receipt['error']=str(error)
        return finish('failed_or_blocked_see_error',1)


if __name__=='__main__':
    raise SystemExit(main())
