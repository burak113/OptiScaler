"""Query six provider defaults in a fresh context, before any effect override or RR dispatch."""
from pathlib import Path
import hashlib,json,math,re,sys,subprocess

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'OptiScaler/shaders/shader_tools'))
from fsrd_toolchain import compile_cpp

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def main():
    folder=Path(__file__).resolve().parent;out=folder/'evidence'
    if out.exists():raise ValueError('Preserve prior default query')
    out.mkdir()
    parent=ROOT/'OptiScaler/shaders/shader_tools/tests/fsrd_rr_runner.cpp'
    text=parent.read_text();parent_hash=sha(parent)
    for path in ('api/include/ffx_api_loader.h','api/include/dx12/ffx_api_dx12.h','denoisers/include/ffx_denoiser.h'):
        old='../../../../external/FidelityFX-SDK-v2/Kits/FidelityFX/'+path
        if text.count(old)!=1:raise ValueError('Include anchor')
        text=text.replace(old,(ROOT/'external/FidelityFX-SDK-v2/Kits/FidelityFX'/path).as_posix(),1)
    anchor='    ff(api.CreateContext(&context,&create.header,nullptr),"create RR");'
    if text.count(anchor)!=1:raise ValueError('Context anchor')
    block=r'''
    const uint64_t defaultKeys[]={FFX_API_CONFIGURE_DENOISER_KEY_DISOCCLUSION_THRESHOLD,FFX_API_CONFIGURE_DENOISER_KEY_CROSS_BILATERAL_NORMAL_STRENGTH,FFX_API_CONFIGURE_DENOISER_KEY_STABILITY_BIAS,FFX_API_CONFIGURE_DENOISER_KEY_MAX_RADIANCE,FFX_API_CONFIGURE_DENOISER_KEY_RADIANCE_CLIP_STD_K,FFX_API_CONFIGURE_DENOISER_KEY_GAUSSIAN_KERNEL_RELAXATION};
    for(unsigned i=0;i<6;++i) {
        float value=std::nanf("");
        ffxQueryDescDenoiserGetDefaultKeyValue query{{FFX_API_QUERY_DESC_TYPE_DENOISER_GET_DEFAULT_KEYVALUE,nullptr},defaultKeys[i],1,&value};
        auto code=api.Query(&context,&query.header); uint32_t bits=0; memcpy(&bits,&value,sizeof(bits));
        std::cout<<"default_key="<<defaultKeys[i]<<" query_result="<<code<<" finite="<<std::isfinite(value)<<" float_bits="<<bits<<" value="<<std::setprecision(9)<<value<<'\n';
    }
    unsigned queryValidationErrors=0,queryValidationWarnings=0;
    if(info) {
        for(UINT64 i=0;i<info->GetNumStoredMessages();++i) {
            SIZE_T bytes=0;info->GetMessage(i,nullptr,&bytes);std::vector<char> storage(bytes);
            auto* m=reinterpret_cast<D3D12_MESSAGE*>(storage.data());info->GetMessage(i,m,&bytes);
            if(m->Severity<=D3D12_MESSAGE_SEVERITY_ERROR) {++queryValidationErrors;std::cerr<<m->pDescription<<'\n';}
            else if(m->Severity==D3D12_MESSAGE_SEVERITY_WARNING) {++queryValidationWarnings;std::cerr<<m->pDescription<<'\n';}
        }
    }
    ff(api.DestroyContext(&context,nullptr),"destroy query RR");CloseHandle(event);FreeLibrary(module);
    std::cout<<"query_only=1 context_create_flags="<<create.flags<<" signals="<<create.signalFlags<<" requested_api="<<FFX_DENOISER_VERSION<<" dispatches=0 validation_errors="<<queryValidationErrors<<" validation_warnings="<<queryValidationWarnings<<" sdk_errors="<<sdkErrors<<" sdk_warnings="<<sdkWarnings<<'\n';
    return queryValidationErrors||sdkErrors?2:0;
'''
    # Immediate return makes all later effect-key Configure/Dispatch code unreachable.
    text=text.replace(anchor,anchor+'\n'+block,1)
    cpp=out/'query_defaults.cpp';cpp.write_text(text,encoding='utf-8')
    dll=ROOT/'external/FidelityFX-SDK-v2/Kits/FidelityFX/signedbin/amd_fidelityfx_denoiser_dx12.dll'
    provider_hash=sha(dll)
    inputs=ROOT/'tools_tmp/matched_camera_input_contract_20260930/evidence'
    rows=[];identities={}
    for slot,fmt in enumerate([41,10,24,28,28,10,10]):
        path=inputs/f'frame_0_matched_0_input{slot}.bin'
        identities[str(slot)]=dict(path=str(path),sha256=sha(path))
        rows.append(f'"{path.as_posix()}" {fmt} 1')
    job=out/'job.txt';job.write_text('\n'.join([f'128 80 1 2 32 0 0 0 "{dll.as_posix()}"']+rows+[f'"{(out/"unused_diffuse.bin").as_posix()}" "{(out/"unused_specular.bin").as_posix()}"'])+'\n')
    exe=out/'query_defaults.exe';compile_cpp(cpp,exe,('d3d12.lib','dxgi.lib'))
    proc=subprocess.run([str(exe),str(job)],capture_output=True,text=True,timeout=60)
    log=out/'runner.log';log.write_text(proc.stdout+proc.stderr,encoding='utf-8')
    keys=[]
    for key,code,finite,bits,value in re.findall(r'default_key=(\d+) query_result=(\d+) finite=(\d+) float_bits=(\d+) value=(\S+)',proc.stdout):
        measured=int(code)==0 and bool(int(finite))
        keys.append(dict(key_id=int(key),returncode=int(code),finite=bool(int(finite)),float32_bits=int(bits),value=float(value) if measured else None,measured=measured))
    if len(keys)!=6:raise ValueError('Missing default query results; retain log')
    result=dict(schema='fresh-context-provider-default-query-v1',quality_accepted=False,contexts=1,native_dispatches=0,
        queries_before_effect_configuration=True,source_derivation=dict(parent=str(parent),parent_sha256=parent_hash,
        generated_source_sha256=sha(cpp),script_sha256=sha(__file__),control='Add query-only block immediately after context creation and return before Configure/Dispatch; absolute SDK includes'),
        runner_sha256=sha(exe),provider_path=str(dll),provider_sha256=provider_hash,job_sha256=sha(job),input_identities=identities,
        dimensions=[128,80],signals=[2,32],context_create_flags=2,query_utility_is_existing_pinned_runner=False,
        returncode=proc.returncode,log_sha256=sha(log),keys=keys,
        limitations=['Default query does not expose current configured values.','Separate query utility; original pinned runner does not perform these queries.','No RR dispatch or game quality observation.','Ordinary D3D12 validation; GPU-based validation is not enabled.'])
    (out/'results.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    if sha(parent)!=parent_hash or sha(dll)!=provider_hash:raise ValueError('Parent/provider changed')
    print(json.dumps(keys),flush=True)
    if proc.returncode:raise RuntimeError('Default query utility failed; see retained evidence')
if __name__=='__main__':main()
