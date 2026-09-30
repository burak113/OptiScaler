"""Create an isolated diagnostic runner; original production/test sources untouched."""
from pathlib import Path
import hashlib,json,shutil,sys
ROOT=Path(__file__).resolve().parents[2];HERE=Path(__file__).resolve().parent
ORIGINAL=ROOT/'OptiScaler/shaders/shader_tools/tests/fsrd_rr_runner.cpp'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 if (HERE/'fsrd_rr_output_init.exe').exists()or(HERE/'fsrd_rr_output_init.cpp').exists():raise ValueError('Preserve build')
 assert sha(ORIGINAL)=='f6cfbecc4704d7f4f891f5c2ae88baf69546a316a9738ed03da0413d6ef0d077'
 text=ORIGINAL.read_text()
 for token in ('api/include/ffx_api_loader.h','api/include/dx12/ffx_api_dx12.h','denoisers/include/ffx_denoiser.h'):
  text=text.replace('../../../../external/FidelityFX-SDK-v2/Kits/FidelityFX/'+token,(ROOT/'external/FidelityFX-SDK-v2/Kits/FidelityFX'/token).as_posix())
 old='if(argc!=2) throw std::runtime_error("usage: fsrd_rr_runner job.txt");'
 new='''if(argc!=2&&argc!=3) throw std::runtime_error("usage: fsrd_rr_output_init job.txt [mode]");
    const unsigned outputInitMode=argc==3?unsigned(std::stoi(argv[2])):0;
    if(outputInitMode>5) throw std::runtime_error("invalid output initialization mode");
    std::cout<<"output_initialization_mode="<<outputInitMode<<'\\n';'''
 assert text.count(old)==1;text=text.replace(old,new)
 anchor='    std::string diffOut,specOut; job>>std::quoted(diffOut)>>std::quoted(specOut);'
 block='''    // Diagnostic only. Mode0 creates no heaps and keeps legacy output lifecycle.
    // Mode1 heap binding + UAV barriers is the matched allocation/binding control.
    ComPtr<ID3D12DescriptorHeap> clearVisible,clearCPU;
    UINT clearStride=dev->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
    if(outputInitMode) {
        D3D12_DESCRIPTOR_HEAP_DESC hd{};hd.Type=D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;hd.NumDescriptors=2;
        hd.Flags=D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
        hr(dev->CreateDescriptorHeap(&hd,IID_PPV_ARGS(&clearVisible)),"diagnostic visible UAV heap");
        hd.Flags=D3D12_DESCRIPTOR_HEAP_FLAG_NONE;
        hr(dev->CreateDescriptorHeap(&hd,IID_PPV_ARGS(&clearCPU)),"diagnostic CPU UAV heap");
        for(unsigned j=0;j<2;++j) {
            D3D12_UNORDERED_ACCESS_VIEW_DESC ud{};ud.Format=tex[7+j].format;ud.ViewDimension=D3D12_UAV_DIMENSION_TEXTURE2D;
            auto c=clearCPU->GetCPUDescriptorHandleForHeapStart();c.ptr+=SIZE_T(j)*clearStride;
            auto v=clearVisible->GetCPUDescriptorHandleForHeapStart();v.ptr+=SIZE_T(j)*clearStride;
            dev->CreateUnorderedAccessView(tex[7+j].tex.Get(),nullptr,&ud,c);
            dev->CopyDescriptorsSimple(1,v,c,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
        }
    }
'''
 assert text.count(anchor)==1;text=text.replace(anchor,block+anchor)
 anchor='        ff(api.Dispatch(&context,&dispatch.header),"dispatch RR");'
 block='''        if(outputInitMode) {
            ID3D12DescriptorHeap* heaps[]={clearVisible.Get()};cmd->SetDescriptorHeaps(1,heaps);
            bool clearNow=(outputInitMode==2||outputInitMode==4)?frame==0:(outputInitMode==3||outputInitMode==5);
            const float zero[4]={0,0,0,0};const float sentinel[4]={257,513,769,17};
            const float* value=outputInitMode>=4?sentinel:zero;
            for(unsigned j=0;j<2;++j) {
                if((j==0&&!diffFlag)||(j==1&&!specFlag))continue;
                auto c=clearCPU->GetCPUDescriptorHandleForHeapStart();c.ptr+=SIZE_T(j)*clearStride;
                auto g=clearVisible->GetGPUDescriptorHandleForHeapStart();g.ptr+=UINT64(j)*clearStride;
                if(clearNow)cmd->ClearUnorderedAccessViewFloat(g,c,tex[7+j].tex.Get(),value,0,nullptr);
                // All nonlegacy modes share this barrier, including no-clear mode1.
                D3D12_RESOURCE_BARRIER ub{};ub.Type=D3D12_RESOURCE_BARRIER_TYPE_UAV;ub.UAV.pResource=tex[7+j].tex.Get();
                cmd->ResourceBarrier(1,&ub);
            }
        }
'''
 assert text.count(anchor)==1;text=text.replace(anchor,block+anchor)
 cpp=HERE/'fsrd_rr_output_init.cpp';cpp.write_text(text)
 sys.path.insert(0,str(ROOT/'OptiScaler/shaders/shader_tools'))
 from fsrd_toolchain import compile_cpp
 exe=HERE/'fsrd_rr_output_init.exe';compile_cpp(cpp,exe,('d3d12.lib','dxgi.lib'))
 assert sha(ORIGINAL)=='f6cfbecc4704d7f4f891f5c2ae88baf69546a316a9738ed03da0413d6ef0d077'
 old=ROOT/'tools_tmp/native_guide_alpha_wave_identical_repeat_20260930';shutil.copyfile(old/'native_resource_guard.py',HERE/'native_resource_guard.py')
 driver=(old/'analyze.py').read_text()
 previous="EXE=Path('C:/Users/burak/.codex/visualizations/2026/09/29/01a0eeeb-48a8-7733-add1-58a3bd1f37ce/response_soft_temporal_long_alpha_fresh/fsrd_rr_runner.exe')"
 assert driver.count(previous)==1;driver=driver.replace(previous,"EXE=HERE/'fsrd_rr_output_init.exe'")
 variants=tuple([f'round0_mode{i}'for i in range(6)]+[f'round1_mode{i}'for i in reversed(range(6))])
 driver=driver.replace("VARIANTS=('repeat0','repeat1','repeat2')",'VARIANTS='+repr(variants))
 driver=driver.replace('identical-wave-seven-input-fresh-context-repeat-v1','wave-external-output-initialization-native-diagnostic-v1')
 driver=driver.replace('native_contexts=3,native_RR_calls=192','native_contexts=12,native_RR_calls=768')
 driver=driver.replace('3427689a4764380f885545c353250277e4d71944d3310c8a17b3cbba0f3c21d2',sha(exe))
 driver=driver.replace('run_guarded([str(EXE),str(job)],folder)',"run_guarded([str(EXE),str(job),variant.rsplit('mode',1)[1]],folder)")
 driver=driver.replace("case_dir/'repeat0'/name","case_dir/'round0_mode0'/name")
 driver=driver.replace("assert report['completed_native_contexts']==3","assert report['completed_native_contexts']==12")
 driver=driver.replace("{'contexts':3,'RR_calls':192","{'contexts':12,'RR_calls':768")
 (HERE/'analyze.py').write_text(driver)
 registration={'schema':'isolated-external-output-initialization-registration-v1','quality_accepted':False,
  'hypothesis':'Test whether external output UAV initial contents/completeness can influence identicalinput native variation; not identified cause.',
  'original_runner_source_sha256':sha(ORIGINAL),'new_runner_source_sha256':sha(cpp),'new_runner_binary_sha256':sha(exe),
  'modes':{'0':'legacy no extra heaps/binding/barriers','1':'two UAV heaps, bind and UAV barrier only, no clear',
   '2':'same heaps/binding/barrier + zero firstframe','3':'same heaps/binding/barrier + zero everyframe',
   '4':'same heaps/binding/barrier + sentinel firstframe','5':'same heaps/binding/barrier + sentinel everyframe'},
  'sentinel_RGBA':[257,513,769,17],'mode_order':list(variants),'native_contexts':12,'RR_calls':768,
  'matching':'All7originalwaveP inputs,formats/uploadcounts,184appliedcontrols/provider match; only isolatedrunneroutputlifecycle changes.',
  'comparisons':'Fresh eachmode repeats/allpairs, rawRGBA + sentinel survival and defaultC vsoldB; no averaging, quality scores or outputpatch',
  'confounds':'Heap/binding/barrier mode1 separates some resource-allocation/order changes. Two repeats do not establish deterministic or population guarantees.',
  'no_production_change':True,'no_new_P':True,'no_conversion_or_composition':True}
 (HERE/'registration.json').write_text(json.dumps(registration,indent=2)+'\n')
 print(json.dumps({'runner_sha256':sha(exe),'source_sha256':sha(cpp),'contexts_registered':12},indent=2),flush=True)
if __name__=='__main__':main()
