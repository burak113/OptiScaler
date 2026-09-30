// Standalone real AMD FSR Ray Regeneration experiment. No OptiScaler/Floor code runs here.
// All signals and guides are supplied explicitly by the Python experiment driver.
#define NOMINMAX
#define _WINDOWS
#include <windows.h>
#include <d3d12.h>
#include <dxgi1_6.h>
#include <wrl/client.h>
#include <DirectXMath.h>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <iomanip>
#include <vector>
#include <array>
#include <sstream>
#include <iterator>
#include <limits>
#include <string>
#include <stdexcept>
#include <cstring>
#include <cmath>
#include "F:/OptiRevelations/OptiScaler-ffxD-alpha/external/FidelityFX-SDK-v2/Kits/FidelityFX/api/include/ffx_api_loader.h"
#include "F:/OptiRevelations/OptiScaler-ffxD-alpha/external/FidelityFX-SDK-v2/Kits/FidelityFX/api/include/dx12/ffx_api_dx12.h"
#include "F:/OptiRevelations/OptiScaler-ffxD-alpha/external/FidelityFX-SDK-v2/Kits/FidelityFX/denoisers/include/ffx_denoiser.h"
using Microsoft::WRL::ComPtr;
void hr(HRESULT h, const char* s) { if(FAILED(h)) throw std::runtime_error(std::string(s)+" HRESULT="+std::to_string(uint32_t(h))); }
void ff(ffxReturnCode_t h, const char* s) { if(h) throw std::runtime_error(std::string(s)+" FFX="+std::to_string(h)); }
unsigned sdkErrors=0, sdkWarnings=0;
void message(uint32_t type,const wchar_t* s) { if(type==FFX_API_MESSAGE_TYPE_ERROR) ++sdkErrors; else ++sdkWarnings; std::wcerr<<L"SDK: "<<s<<L'\n'; }
struct Tex {
    ComPtr<ID3D12Resource> tex, staging;
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint{};
    UINT64 size=0;
    unsigned bpp=0, frames=1;
    DXGI_FORMAT format{};
    std::ifstream input;
    D3D12_RESOURCE_STATES state=D3D12_RESOURCE_STATE_COPY_DEST;
    FfxApiResource api{};
};
int main(int argc,char** argv) try {
    std::cout<<std::unitbuf;
    if(argc!=4) throw std::runtime_error("usage: fsrd_rr_rotation job.txt K rotation");
    const unsigned batchSize=unsigned(std::stoul(argv[2]));
    if(batchSize!=1||std::string(argv[2])!="1") throw std::runtime_error("K must be 1");
    const std::string rotationArg=argv[3];
    if(rotationArg!="1"&&rotationArg!="4") throw std::runtime_error("rotation must be 1/4");
    const unsigned poolRotation=rotationArg=="1"?1u:4u;
    std::ifstream job(argv[1]);
    unsigned w,h,frames,diffFlag,specFlag,resetEvery,tuning,passthrough;
    std::string dllPath;
    job>>w>>h>>frames>>diffFlag>>specFlag>>resetEvery>>tuning>>passthrough>>std::quoted(dllPath);
    if(!job||w!=128||h!=80||frames!=64||diffFlag!=2||specFlag!=32||resetEvery!=0||tuning!=1||passthrough!=0) throw std::runtime_error("frozen job header mismatch");
    ComPtr<ID3D12Debug> debug;
    bool debugOn=SUCCEEDED(D3D12GetDebugInterface(IID_PPV_ARGS(&debug)));
    if(debugOn) debug->EnableDebugLayer();
    ComPtr<IDXGIFactory6> factory; hr(CreateDXGIFactory2(0,IID_PPV_ARGS(&factory)),"factory");
    ComPtr<IDXGIAdapter1> adapter;
    hr(factory->EnumAdapterByGpuPreference(0,DXGI_GPU_PREFERENCE_HIGH_PERFORMANCE,IID_PPV_ARGS(&adapter)),"adapter");
    DXGI_ADAPTER_DESC1 ad{}; adapter->GetDesc1(&ad);
    char name[512]{}; WideCharToMultiByte(CP_UTF8,0,ad.Description,-1,name,sizeof(name),nullptr,nullptr);
    LARGE_INTEGER driver{}; adapter->CheckInterfaceSupport(__uuidof(IDXGIDevice),&driver);
    std::cout<<"adapter="<<name<<" driver="<<driver.QuadPart<<" debug_layer="<<debugOn<<'\n';
    ComPtr<ID3D12Device> dev; hr(D3D12CreateDevice(adapter.Get(),D3D_FEATURE_LEVEL_12_0,IID_PPV_ARGS(&dev)),"device");
    ComPtr<ID3D12InfoQueue> info; dev.As(&info);
    ComPtr<ID3D12CommandQueue> queue; D3D12_COMMAND_QUEUE_DESC qd{};
    hr(dev->CreateCommandQueue(&qd,IID_PPV_ARGS(&queue)),"queue");
    std::array<ComPtr<ID3D12CommandAllocator>,4> allocators;
    std::array<ComPtr<ID3D12GraphicsCommandList>,4> commands;
    for(unsigned slot=0;slot<4;++slot) {
        hr(dev->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT,IID_PPV_ARGS(&allocators[slot])),"allocator");
        hr(dev->CreateCommandList(0,D3D12_COMMAND_LIST_TYPE_DIRECT,allocators[slot].Get(),nullptr,IID_PPV_ARGS(&commands[slot])),"list");
        hr(commands[slot]->Close(),"initial close");
    }
    ComPtr<ID3D12GraphicsCommandList> cmd=commands[0];
    ComPtr<ID3D12Fence> fence; hr(dev->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&fence)),"fence");
    HANDLE event=CreateEventW(nullptr,FALSE,FALSE,nullptr);
    if(!event) throw std::runtime_error("CreateEvent failed");
    auto buffer=[&](UINT64 size,D3D12_HEAP_TYPE heap) {
        D3D12_HEAP_PROPERTIES hp{}; hp.Type=heap;
        D3D12_RESOURCE_DESC d{}; d.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER; d.Width=size; d.Height=1; d.DepthOrArraySize=1; d.MipLevels=1; d.SampleDesc.Count=1; d.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        ComPtr<ID3D12Resource> r;
        hr(dev->CreateCommittedResource(&hp,D3D12_HEAP_FLAG_NONE,&d,heap==D3D12_HEAP_TYPE_UPLOAD?D3D12_RESOURCE_STATE_GENERIC_READ:D3D12_RESOURCE_STATE_COPY_DEST,nullptr,IID_PPV_ARGS(&r)),"buffer"); return r;
    };
    auto barrier=[&](Tex& t,D3D12_RESOURCE_STATES next) {
        if(t.state==next) return;
        D3D12_RESOURCE_BARRIER b{}; b.Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        b.Transition={t.tex.Get(),D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,t.state,next}; cmd->ResourceBarrier(1,&b); t.state=next;
    };
    std::vector<Tex> tex(9);
    for(unsigned i=0;i<9;++i) {
        auto& t=tex[i]; int fmt=DXGI_FORMAT_R16G16B16A16_FLOAT; std::string path;
        if(i<7) { job>>std::quoted(path)>>fmt>>t.frames; t.input.open(path,std::ios::binary); if(!t.input) throw std::runtime_error("input: "+path); }
        t.format=DXGI_FORMAT(fmt); t.bpp=fmt==DXGI_FORMAT_R16G16B16A16_FLOAT?8:4;
        D3D12_RESOURCE_DESC d{}; d.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D; d.Width=w; d.Height=h; d.DepthOrArraySize=1; d.MipLevels=1; d.Format=t.format; d.SampleDesc.Count=1;
        d.Flags=i>=7?D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS:D3D12_RESOURCE_FLAG_NONE;
        D3D12_HEAP_PROPERTIES hp{}; hp.Type=D3D12_HEAP_TYPE_DEFAULT;
        t.state=i>=7?D3D12_RESOURCE_STATE_UNORDERED_ACCESS:D3D12_RESOURCE_STATE_COPY_DEST;
        hr(dev->CreateCommittedResource(&hp,D3D12_HEAP_FLAG_NONE,&d,t.state,nullptr,IID_PPV_ARGS(&t.tex)),"texture");
        std::wstring resourceName=L"RR_test_"+std::to_wstring(i); t.tex->SetName(resourceName.c_str());
        dev->GetCopyableFootprints(&d,0,1,0,&t.footprint,nullptr,nullptr,&t.size);
        // Staging is allocated per immutable source slice and output frame below.
        t.api.resource=t.tex.Get(); t.api.state=i>=7?FFX_API_RESOURCE_STATE_UNORDERED_ACCESS:FFX_API_RESOURCE_STATE_PIXEL_COMPUTE_READ;
        t.api.description={FFX_API_RESOURCE_TYPE_TEXTURE2D,ffxApiGetSurfaceFormatDX12(t.format),w,h,1,1,0,uint32_t(i>=7?FFX_API_RESOURCE_USAGE_UAV:FFX_API_RESOURCE_USAGE_READ_ONLY)};
        if(i<7) {
            t.input.seekg(0,std::ios::end);
            if(t.input.tellg()!=std::streamoff(uint64_t(w)*h*t.bpp*t.frames)) throw std::runtime_error("input byte count: "+path);
            t.input.seekg(0);
        }
    }
    std::string diffOut,specOut; job>>std::quoted(diffOut)>>std::quoted(specOut);
    if(!job) throw std::runtime_error("invalid texture records");
    std::ofstream outD(diffOut,std::ios::binary),outS(specOut,std::ios::binary);
    if(!outD||!outS) throw std::runtime_error("output open");
    std::array<std::vector<ComPtr<ID3D12Resource>>,7> uploads;
    std::array<std::array<ComPtr<ID3D12Resource>,2>,64> readbacks;
    std::array<ComPtr<ID3D12Resource>,2> initializers;
    for(unsigned i=0;i<7;++i) {
        auto& t=tex[i];if(t.frames!=1&&t.frames!=64) throw std::runtime_error("input frames");uploads[i].resize(t.frames);
        for(unsigned frame=0;frame<t.frames;++frame) {
            uploads[i][frame]=buffer(t.size,D3D12_HEAP_TYPE_UPLOAD);char* mapped=nullptr;D3D12_RANGE empty{0,0};
            hr(uploads[i][frame]->Map(0,&empty,reinterpret_cast<void**>(&mapped)),"immutable upload map");memset(mapped,0,SIZE_T(t.size));
            for(unsigned y=0;y<h;++y) t.input.read(mapped+t.footprint.Offset+y*t.footprint.Footprint.RowPitch,size_t(w)*t.bpp);
            uploads[i][frame]->Unmap(0,nullptr);if(!t.input) throw std::runtime_error("immutable input read");
        }
    }
    for(unsigned i=7;i<9;++i) {
        auto& t=tex[i];initializers[i-7]=buffer(t.size,D3D12_HEAP_TYPE_UPLOAD);char* mapped=nullptr;D3D12_RANGE empty{0,0};
        hr(initializers[i-7]->Map(0,&empty,reinterpret_cast<void**>(&mapped)),"zero initializer map");memset(mapped,0,SIZE_T(t.size));initializers[i-7]->Unmap(0,nullptr);
        for(unsigned frame=0;frame<64;++frame) readbacks[frame][i-7]=buffer(t.size,D3D12_HEAP_TYPE_READBACK);
    }
    // Load this exact DLL directly, so provider selection cannot silently use a different DLL.
    HMODULE module=LoadLibraryExW(std::filesystem::path(dllPath).c_str(),nullptr,LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR|LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
    if(!module) throw std::runtime_error("LoadLibrary error="+std::to_string(GetLastError()));
    ffxFunctions api{}; ffxLoadFunctions(&api,module);
    if(!api.CreateContext||!api.Query||!api.Dispatch||!api.Configure||!api.DestroyContext) throw std::runtime_error("missing FFX exports");
    wchar_t actualPath[32768]{}; GetModuleFileNameW(module,actualPath,32768); std::wcout<<L"dll="<<actualPath<<L'\n';
    ffxConfigureDescGlobalDebug logging{{FFX_API_CONFIGURE_DESC_TYPE_GLOBALDEBUG,nullptr},FFX_API_EFFECT_ID_DENOISER,message,FFX_API_CONFIGURE_GLOBALDEBUG_LEVEL_VERBOSE};
    ff(api.Configure(nullptr,&logging.header),"global debug");
    ffxCreateBackendDX12Desc backend{{FFX_API_CREATE_CONTEXT_DESC_TYPE_BACKEND_DX12,nullptr},dev.Get()};
    ffxCreateContextDescDenoiser create{{FFX_API_CREATE_CONTEXT_DESC_TYPE_DENOISER,&backend.header},FFX_DENOISER_VERSION,{w,h},diffFlag|specFlag,0,FFX_DENOISER_ENABLE_VALIDATION};
    ffxContext context=nullptr;
    ff(api.CreateContext(&context,&create.header,nullptr),"create RR");
    ffxQueryGetProviderVersion version{{FFX_API_QUERY_DESC_TYPE_GET_PROVIDER_VERSION,nullptr}};
    auto versionResult=api.Query(&context,&version.header);
    std::cout<<"provider="<<(version.versionName?version.versionName:"unavailable from direct effect DLL")<<" id="<<version.versionId<<" version_query_result="<<versionResult<<" requested_api="<<FFX_DENOISER_VERSION<<'\n';
    if(tuning) {
        const uint64_t keys[]={FFX_API_CONFIGURE_DENOISER_KEY_DISOCCLUSION_THRESHOLD,FFX_API_CONFIGURE_DENOISER_KEY_CROSS_BILATERAL_NORMAL_STRENGTH,FFX_API_CONFIGURE_DENOISER_KEY_STABILITY_BIAS,FFX_API_CONFIGURE_DENOISER_KEY_MAX_RADIANCE,FFX_API_CONFIGURE_DENOISER_KEY_RADIANCE_CLIP_STD_K,FFX_API_CONFIGURE_DENOISER_KEY_GAUSSIAN_KERNEL_RELAXATION};
        const float values[]={.1f,.5f,.5f,40000.f,40.f,.5f};
        for(unsigned i=0;i<6;++i) { ffxConfigureDescDenoiserKeyValue c{{FFX_API_CONFIGURE_DESC_TYPE_DENOISER_KEYVALUE,nullptr},keys[i],1,values+i}; ff(api.Configure(&context,&c.header),"configuration"); }
    }
    ffxDispatchDescDenoiser dispatch{}; dispatch.header.type=FFX_API_DISPATCH_DESC_TYPE_DENOISER;
    dispatch.commandList=cmd.Get(); dispatch.renderSize={w,h}; dispatch.motionVectorScale={1,1,1};
    dispatch.linearDepthBounds=passthrough?FfxApiFloatBounds{0,1}:FfxApiFloatBounds{0,1024};
    DirectX::XMFLOAT4X4 matrix;
    DirectX::XMStoreFloat4x4(&matrix,DirectX::XMMatrixIdentity()); memcpy(&dispatch.view,&matrix,sizeof(matrix));
    DirectX::XMStoreFloat4x4(&matrix,DirectX::XMMatrixPerspectiveFovLH(DirectX::XM_PI/3.0f,float(w)/h,.1f,1000.f)); memcpy(&dispatch.projection,&matrix,sizeof(matrix));
    // Optional captured-geometry probes use a verified cropped camera. Existing
    // jobs retain the synthetic camera above; the override is local to this job.
    std::ifstream camera(std::filesystem::path(argv[1]).parent_path()/"camera.txt");
    if(camera) {
        float view[16],projection[16],jx,jy,lo,hi;
        for(float& value:view) camera>>value;
        for(float& value:projection) camera>>value;
        camera>>jx>>jy>>lo>>hi;
        if(!camera) throw std::runtime_error("invalid camera override");
        for(float value:view) if(!std::isfinite(value)) throw std::runtime_error("nonfinite camera view");
        for(float value:projection) if(!std::isfinite(value)) throw std::runtime_error("nonfinite camera projection");
        if(!std::isfinite(jx)||!std::isfinite(jy)||!std::isfinite(lo)||!std::isfinite(hi)||lo>=hi)
            throw std::runtime_error("invalid camera jitter/depth bounds");
        memcpy(&dispatch.view,view,sizeof(view)); memcpy(&dispatch.projection,projection,sizeof(projection));
        dispatch.jitterOffsets={jx,jy};
        if(!passthrough) dispatch.linearDepthBounds={lo,hi};
        std::cout<<"custom_camera=1\n";
    }
    dispatch.linearDepth=tex[0].api; dispatch.motionVectors=tex[1].api; dispatch.normals=tex[2].api;
    // The SDK requires an empty descriptor for an unused signal's guide.
    dispatch.specularAlbedo=specFlag?tex[3].api:FfxApiResource{};
    dispatch.diffuseAlbedo=diffFlag?tex[4].api:FfxApiResource{};
    // All four descriptors have the same payload; choose their documented type explicitly.
    ffxDispatchDescDenoiserDirectDiffuse diff{};
    diff.header.type=diffFlag==FFX_DENOISER_SIGNAL_INDIRECT_DIFFUSE?FFX_API_DISPATCH_DESC_TYPE_DENOISER_INDIRECT_DIFFUSE:FFX_API_DISPATCH_DESC_TYPE_DENOISER_DIRECT_DIFFUSE;
    diff.signal.input=tex[5].api; diff.signal.output=tex[7].api;
    ffxDispatchDescDenoiserIndirectSpecular spec{};
    spec.header.type=specFlag==FFX_DENOISER_SIGNAL_DIRECT_SPECULAR?FFX_API_DISPATCH_DESC_TYPE_DENOISER_DIRECT_SPECULAR:FFX_API_DISPATCH_DESC_TYPE_DENOISER_INDIRECT_SPECULAR;
    spec.signal.input=tex[6].api; spec.signal.output=tex[8].api;
    if(diffFlag) { dispatch.header.pNext=&diff.header; if(specFlag) diff.header.pNext=&spec.header; }
    else dispatch.header.pNext=&spec.header;
    unsigned validationErrors=0,validationWarnings=0;
    struct Counts {
        unsigned api=0,queued=0,completed=0,observed=0,executes=0;
        unsigned signalAttempts=0,signals=0,eventAttempts=0,events=0,waitAttempts=0,waits=0;
    } counts;
    const auto folder=std::filesystem::path(argv[1]).parent_path();
    std::ofstream controlsOut(folder/"dispatch_controls.bin",std::ios::binary);
    std::ifstream controlsIn(folder/"frame_controls.txt");
    std::ifstream expectedIn(folder/"expected_applied_dispatch_controls.bin",std::ios::binary);
    std::vector<char> expectedControls((std::istreambuf_iterator<char>(expectedIn)),{});
    if(!controlsOut||!controlsIn||expectedControls.size()!=64*184) throw std::runtime_error("controls files/size");
    std::ofstream recordedOut(folder/"recorded_frame_indices.bin",std::ios::binary);
    std::ofstream queuedOut(folder/"queued_frame_indices.bin",std::ios::binary);
    std::ofstream completedOut(folder/"completed_frame_indices.bin",std::ios::binary);
    std::ofstream observedOut(folder/"observed_frame_indices.bin",std::ios::binary);
    std::ofstream presenceOut(folder/"output_presence.bin",std::ios::binary);
    std::ofstream ledger(folder/"stage_events.jsonl");
    if(!recordedOut||!queuedOut||!completedOut||!observedOut||!presenceOut||!ledger) throw std::runtime_error("stage files");
    auto snapshot=[&](const char* stage,int frame,UINT64 target,bool terminal=false,bool destroyed=false) {
        std::ostringstream text;
        text<<"{\"stage\":\""<<stage<<"\",\"frame\":"<<frame<<",\"fence\":"<<target
            <<",\"terminal\":"<<(terminal?"true":"false")<<",\"context_destroyed\":"<<(destroyed?"true":"false")
            <<",\"api\":"<<counts.api<<",\"queued\":"<<counts.queued<<",\"completed\":"<<counts.completed
            <<",\"observed\":"<<counts.observed<<",\"executes\":"<<counts.executes
            <<",\"signal_attempts\":"<<counts.signalAttempts<<",\"signals\":"<<counts.signals
            <<",\"event_attempts\":"<<counts.eventAttempts<<",\"events\":"<<counts.events
            <<",\"wait_attempts\":"<<counts.waitAttempts<<",\"waits\":"<<counts.waits
            <<",\"validation_errors\":"<<validationErrors<<",\"validation_warnings\":"<<validationWarnings
            <<",\"sdk_errors\":"<<sdkErrors<<",\"sdk_warnings\":"<<sdkWarnings
            <<",\"discarded\":0,\"omitted\":0}";
        ledger<<text.str()<<'\n'; ledger.flush();
        if(terminal) std::cout<<"BATCH_COUNTERS "<<text.str()<<'\n';
        if(!ledger) throw std::runtime_error("stage ledger write");
    };
    auto writeIndex=[&](std::ofstream& output,unsigned frame) {
        output.write(reinterpret_cast<const char*>(&frame),sizeof(frame));output.flush();
        if(!output) throw std::runtime_error("index write");
    };
    auto diagnostics=[&]() {
        if(info) {
            for(UINT64 i=0;i<info->GetNumStoredMessages();++i) {
                SIZE_T n=0; hr(info->GetMessage(i,nullptr,&n),"message size"); std::vector<char> bytes(n);
                auto* m=reinterpret_cast<D3D12_MESSAGE*>(bytes.data()); hr(info->GetMessage(i,m,&n),"message read");
                if(m->Severity<=D3D12_MESSAGE_SEVERITY_ERROR) {++validationErrors; std::cerr<<m->pDescription<<'\n';}
                else if(m->Severity==D3D12_MESSAGE_SEVERITY_WARNING) {++validationWarnings; std::cerr<<m->pDescription<<'\n';}
            }
            info->ClearStoredMessages();
        }
        if(validationErrors||validationWarnings||sdkErrors||sdkWarnings) throw std::runtime_error("unexpected ordinary D3D12/SDK diagnostic");
    };
    std::array<ffxDispatchDescDenoiser,64> frameDispatch{};
    std::array<ffxDispatchDescDenoiserDirectDiffuse,64> frameDiff{};
    std::array<ffxDispatchDescDenoiserIndirectSpecular,64> frameSpec{};
    bool inFlight=false; UINT64 retiredFence=0;
    snapshot("context_created",-1,0);
    try {
        diagnostics();
        for(unsigned begin=0;begin<64;begin+=batchSize) {
            if(inFlight || (retiredFence && fence->GetCompletedValue()<retiredFence)) throw std::runtime_error("pool not retired");
            for(unsigned frame=begin;frame<begin+batchSize;++frame) {
                const unsigned slot=frame%poolRotation; cmd=commands[slot];
                hr(allocators[slot]->Reset(),"reset allocator"); hr(cmd->Reset(allocators[slot].Get(),nullptr),"reset list");
                if(frame==0) for(unsigned i=7;i<9;++i) {
                    auto& t=tex[i];barrier(t,D3D12_RESOURCE_STATE_COPY_DEST);
                    D3D12_TEXTURE_COPY_LOCATION src{};src.pResource=initializers[i-7].Get();src.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;src.PlacedFootprint=t.footprint;
                    D3D12_TEXTURE_COPY_LOCATION dst{};dst.pResource=t.tex.Get();dst.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
                    cmd->CopyTextureRegion(&dst,0,0,0,&src,nullptr);barrier(t,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
                }
                for(unsigned i=0;i<7;++i) {
                    auto& t=tex[i];if(frame&&t.frames==1) continue;
                    barrier(t,D3D12_RESOURCE_STATE_COPY_DEST);
                    D3D12_TEXTURE_COPY_LOCATION src{};src.pResource=uploads[i][t.frames==1?0:frame].Get();src.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;src.PlacedFootprint=t.footprint;
                    D3D12_TEXTURE_COPY_LOCATION dst{};dst.pResource=t.tex.Get();dst.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
                    cmd->CopyTextureRegion(&dst,0,0,0,&src,nullptr);barrier(t,D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE|D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
                }
                auto& applied=frameDispatch[frame];applied=dispatch;applied.commandList=cmd.Get();applied.frameIndex=frame;
                applied.flags=FFX_DENOISER_DISPATCH_NON_GAMMA_ALBEDO|((frame==0||resetEvery)?FFX_DENOISER_DISPATCH_RESET:0);
                unsigned reset;float jx,jy;controlsIn>>reset>>jx>>jy;
                if(!controlsIn||reset>1||!std::isfinite(jx)||!std::isfinite(jy)) throw std::runtime_error("invalid per-frame controls");
                applied.flags=FFX_DENOISER_DISPATCH_NON_GAMMA_ALBEDO|((frame==0||reset)?FFX_DENOISER_DISPATCH_RESET:0);applied.jitterOffsets={jx,jy};
                frameDiff[frame]=diff;frameSpec[frame]=spec;applied.header.pNext=&frameDiff[frame].header;frameDiff[frame].header.pNext=&frameSpec[frame].header;
                std::vector<char> packet;packet.reserve(184);
                auto record=[&](const auto& value) {const char* p=reinterpret_cast<const char*>(&value);packet.insert(packet.end(),p,p+sizeof(value));};
                record(applied.frameIndex);record(applied.flags);record(applied.renderSize);record(applied.motionVectorScale);record(applied.cameraPositionDelta);
                record(applied.jitterOffsets);record(applied.linearDepthBounds);record(applied.view);record(applied.projection);
                if(packet.size()!=184 || memcmp(packet.data(),expectedControls.data()+frame*184,184)) throw std::runtime_error("applied184 mismatch");
                controlsOut.write(packet.data(),packet.size());controlsOut.flush();if(!controlsOut) throw std::runtime_error("controls write");
                ff(api.Dispatch(&context,&applied.header),"dispatch RR");++counts.api;writeIndex(recordedOut,frame);snapshot("api_ok",frame,0);
                for(unsigned i=7;i<9;++i) {
                    auto& t=tex[i];barrier(t,D3D12_RESOURCE_STATE_COPY_SOURCE);
                    D3D12_TEXTURE_COPY_LOCATION src{};src.pResource=t.tex.Get();src.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
                    D3D12_TEXTURE_COPY_LOCATION dst{};dst.pResource=readbacks[frame][i-7].Get();dst.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;dst.PlacedFootprint=t.footprint;
                    cmd->CopyTextureRegion(&dst,0,0,0,&src,nullptr);barrier(t,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
                }
                hr(cmd->Close(),"close");snapshot("list_closed",frame,0);diagnostics();
            }
            snapshot("group_recorded",int(begin+batchSize-1),0);
            for(unsigned frame=begin;frame<begin+batchSize;++frame) {
                ID3D12CommandList* list=commands[frame%poolRotation].Get();inFlight=true;queue->ExecuteCommandLists(1,&list);
                ++counts.executes;++counts.queued;writeIndex(queuedOut,frame);snapshot("execute",frame,0);
            }
            const UINT64 target=begin+batchSize;
            ++counts.signalAttempts;snapshot("signal_start",int(target-1),target);hr(queue->Signal(fence.Get(),target),"signal");++counts.signals;snapshot("signal_ok",int(target-1),target);
            ++counts.eventAttempts;snapshot("event_start",int(target-1),target);hr(fence->SetEventOnCompletion(target,event),"event");++counts.events;snapshot("event_ok",int(target-1),target);
            ++counts.waitAttempts;snapshot("wait_start",int(target-1),target);
            if(WaitForSingleObject(event,60000)!=WAIT_OBJECT_0) throw std::runtime_error("GPU timeout/wait error");
            ++counts.waits;snapshot("wait_ok",int(target-1),target);
            const UINT64 completedValue=fence->GetCompletedValue();
            if(completedValue==std::numeric_limits<UINT64>::max() || completedValue<target) throw std::runtime_error("fence not proven");
            hr(dev->GetDeviceRemovedReason(),"device removed");inFlight=false;retiredFence=target;counts.completed+=batchSize;
            for(unsigned frame=begin;frame<begin+batchSize;++frame) writeIndex(completedOut,frame);
            snapshot("group_completed",int(target-1),target);diagnostics();
            for(unsigned frame=begin;frame<begin+batchSize;++frame) {
                for(unsigned i=7;i<9;++i) {
                    auto& t=tex[i];char* mapped=nullptr;D3D12_RANGE range{0,SIZE_T(t.size)};
                    hr(readbacks[frame][i-7]->Map(0,&range,reinterpret_cast<void**>(&mapped)),"readback");auto& output=i==7?outD:outS;
                    for(unsigned y=0;y<h;++y) output.write(mapped+t.footprint.Offset+y*t.footprint.Footprint.RowPitch,size_t(w)*8);
                    D3D12_RANGE noWrites{0,0};readbacks[frame][i-7]->Unmap(0,&noWrites);output.flush();if(!output) throw std::runtime_error("output write");
                }
                const char present=1;presenceOut.write(&present,1);presenceOut.flush();if(!presenceOut) throw std::runtime_error("presence write");
                writeIndex(observedOut,frame);++counts.observed;snapshot("observed",frame,target);
            }
        }
        controlsOut.close();outD.close();outS.close();if(!controlsOut||!outD||!outS) throw std::runtime_error("output close");
        if(inFlight||retiredFence!=64) throw std::runtime_error("final retirement");
        ff(api.DestroyContext(&context,nullptr),"destroy RR");diagnostics();snapshot("context_destroyed",63,64,true,true);
        CloseHandle(event);FreeLibrary(module);
        std::cout<<"RR_recordings="<<counts.api<<" queued_RR_dispatches="<<counts.completed<<" discarded_RR_recordings=0 validation_errors="<<validationErrors<<" validation_warnings="<<validationWarnings<<" sdk_errors="<<sdkErrors<<" sdk_warnings="<<sdkWarnings<<'\n';
        return 0;
    } catch(const std::exception& e) {
        std::cerr<<e.what()<<'\n';
        try { snapshot("failed",-1,retiredFence,true,false); } catch(...) {}
        if(inFlight) {std::cerr<<"unproven_completion_owned_process_exit_without_context_destroy_or_resource_release\n";std::cerr.flush();std::cout.flush();ExitProcess(3);}
        throw;
    }
} catch(const std::exception& e) { std::cerr<<e.what()<<'\n'; return 1; }
