"""Single native RR context with explicit ID3D12Debug1 GPU-based validation."""
from pathlib import Path
import hashlib,json,re,subprocess,sys,time
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'OptiScaler/shaders/shader_tools'))
from fsrd_toolchain import compile_cpp
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
    folder=Path(__file__).resolve().parent;out=folder/'evidence'
    if out.exists():raise ValueError('Preserve GPU validation attempt')
    out.mkdir();parent=ROOT/'OptiScaler/shaders/shader_tools/tests/fsrd_rr_runner.cpp';text=parent.read_text()
    for path in ('api/include/ffx_api_loader.h','api/include/dx12/ffx_api_dx12.h','denoisers/include/ffx_denoiser.h'):
        old='../../../../external/FidelityFX-SDK-v2/Kits/FidelityFX/'+path
        if text.count(old)!=1:raise ValueError('Include anchor')
        text=text.replace(old,(ROOT/'external/FidelityFX-SDK-v2/Kits/FidelityFX'/path).as_posix(),1)
    anchor='    if(debugOn) debug->EnableDebugLayer();'
    if text.count(anchor)!=1:raise ValueError('Debug anchor')
    replacement=anchor+'\n    if(!debugOn) throw std::runtime_error("GPU validation requires debug layer");\n    ComPtr<ID3D12Debug1> gpuDebug;hr(debug.As(&gpuDebug),"ID3D12Debug1");\n    gpuDebug->SetEnableGPUBasedValidation(TRUE);\n    std::cout<<"gpu_based_validation=1\\n";'
    text=text.replace(anchor,replacement,1)
    cpp=out/'gpu_validation_runner.cpp';cpp.write_text(text,encoding='utf-8')
    source=ROOT/'tools_tmp/default_tuning_context_repeat_20260930/evidence/repeat_0'
    reference=ROOT/'tools_tmp/controlled_context_repeat_20260930/evidence/repeat_0'
    original=json.loads((reference/'amd_context_identity.json').read_text())
    inputs={f'input{i}.bin':sha(source/f'input{i}.bin') for i in range(7)}
    if inputs!=original['inputs']:raise ValueError('Seven source inputs differ')
    controls=source/'frame_controls.txt'
    if controls.read_bytes()!=(reference/'frame_controls.txt').read_bytes():raise ValueError('Frame controls differ')
    (out/'frame_controls.txt').write_bytes(controls.read_bytes())
    rows=(source/'job.txt').read_text().splitlines()
    header=rows[0].replace('128 80 64 2 32 0 0 0','128 80 64 2 32 0 1 0')
    if header==rows[0]:raise ValueError('Tuning header anchor')
    job=out/'job.txt';job.write_text('\n'.join([header]+rows[1:8]+[f'"{(out/"diffuse.bin").as_posix()}" "{(out/"specular.bin").as_posix()}"'])+'\n')
    dll=ROOT/'external/FidelityFX-SDK-v2/Kits/FidelityFX/signedbin/amd_fidelityfx_denoiser_dx12.dll'
    result=dict(schema='explicit-gpu-based-validation-native-diagnostic-v1',status='preparing',quality_accepted=False,
        contexts=0,native_dispatches=0,script_sha256=sha(__file__),preregistration_sha256=sha(folder/'preregistration.md'),
        parent_source_sha256=sha(parent),generated_source_sha256=sha(cpp),
        source_input_identities=inputs,reference_manifest_sha256=sha(reference/'amd_context_identity.json'),
        provider_sha256=sha(dll),dimensions=[128,80],frames=64,signals=[2,32],tuning=1,
        tuning_values=[.1,.5,.5,40000.,40.,.5],context_create_flags=2,
        different_binary_instrumented=True,game_run=False,
        limitations=['GPU validation instrumentation may change scheduling.','Single context is a diagnostic, not a repeatability or quality bound.','Zero messages would not prove absence of all defects.'])
    def save():(out/'results.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    save();exe=out/'gpu_validation_runner.exe';compile_cpp(cpp,exe,('d3d12.lib','dxgi.lib'))
    result['runner_sha256']=sha(exe);result['job_sha256']=sha(job);result['status']='running';save()
    start=time.monotonic()
    try:
        proc=subprocess.run([str(exe),str(job)],capture_output=True,text=True,timeout=300)
    except Exception as exc:
        result['status']='process_exception';result['error']=str(exc);save();raise
    log=out/'runner.log';log.write_text(proc.stdout+proc.stderr,encoding='utf-8')
    result.update(returncode=proc.returncode,elapsed_seconds=time.monotonic()-start,log_sha256=sha(log),
        gpu_based_validation_reported='gpu_based_validation=1' in proc.stdout)
    complete=re.search(r'dispatches=(\d+) validation_errors=(\d+) validation_warnings=(\d+) sdk_errors=(\d+) sdk_warnings=(\d+)',proc.stdout)
    if complete:
        result['native_dispatches']=int(complete[1]);result['contexts']=int(int(complete[1])==64)
        result['validation_counts']={k:int(v) for k,v in zip(('d3d_errors','d3d_warnings','sdk_errors','sdk_warnings'),complete.groups()[1:])}
    output={}
    for name in ('diffuse','specular'):
        p=out/(name+'.bin');entry=dict(path=str(p),size=p.stat().st_size,sha256=sha(p))
        if p.stat().st_size==64*80*128*8:
            a=np.fromfile(p,dtype='<f2').reshape(64,80,128,4)
            entry.update(finite=bool(np.isfinite(a).all()),alpha_min=float(a[...,3].min()),alpha_max=float(a[...,3].max()))
        output[name]=entry
    result['output_identities']=output
    applied=out/'dispatch_controls.bin'
    result['applied_controls_sha256']=sha(applied)
    result['applied_controls_equal_reference']=result['applied_controls_sha256']==original['applied_dispatch_sha256']
    result['source_input_provider_unchanged']=inputs=={f'input{i}.bin':sha(source/f'input{i}.bin') for i in range(7)} and sha(dll)==result['provider_sha256']
    result['status']='completed_diagnostic_not_solution' if proc.returncode==0 and complete else 'failed_native_validation'
    save();print(json.dumps({k:result.get(k) for k in ('status','native_dispatches','gpu_based_validation_reported','validation_counts','applied_controls_equal_reference','elapsed_seconds')}),flush=True)
    if proc.returncode:raise RuntimeError('Native GPU validation failed; retain log and outputs')
if __name__=='__main__':main()
