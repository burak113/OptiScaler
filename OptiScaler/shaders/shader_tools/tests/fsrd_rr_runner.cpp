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
#include <string>
#include <stdexcept>
#include <cstring>
#include <cmath>
#include "../../../../external/FidelityFX-SDK-v2/Kits/FidelityFX/api/include/ffx_api_loader.h"
#include "../../../../external/FidelityFX-SDK-v2/Kits/FidelityFX/api/include/dx12/ffx_api_dx12.h"
#include "../../../../external/FidelityFX-SDK-v2/Kits/FidelityFX/denoisers/include/ffx_denoiser.h"
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
    if(argc!=2) throw std::runtime_error("usage: fsrd_rr_runner job.txt");
    std::ifstream job(argv[1]);
    unsigned w,h,frames,diffFlag,specFlag,resetEvery,tuning,passthrough;
    std::string dllPath;
    job>>w>>h>>frames>>diffFlag>>specFlag>>resetEvery>>tuning>>passthrough>>std::quoted(dllPath);
    if(!job||!w||!h||!frames) throw std::runtime_error("invalid header");
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
    ComPtr<ID3D12CommandAllocator> alloc; hr(dev->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT,IID_PPV_ARGS(&alloc)),"allocator");
    ComPtr<ID3D12GraphicsCommandList> cmd; hr(dev->CreateCommandList(0,D3D12_COMMAND_LIST_TYPE_DIRECT,alloc.Get(),nullptr,IID_PPV_ARGS(&cmd)),"list");
    hr(cmd->Close(),"initial close");
    ComPtr<ID3D12Fence> fence; hr(dev->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&fence)),"fence");
    HANDLE event=CreateEventW(nullptr,FALSE,FALSE,nullptr);
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
    bool alternates=false;
#ifdef FSRD_RR_EXTRA_SIGNALS
    alternates=getenv("FSRD_RR_ALTERNATES")!=nullptr;
    if(alternates&&(diffFlag!=FFX_DENOISER_SIGNAL_DIRECT_DIFFUSE||specFlag!=FFX_DENOISER_SIGNAL_INDIRECT_SPECULAR))
        throw std::runtime_error("alternate replay requires direct diffuse and indirect specular main signals");
#endif
    auto isInput=[&](unsigned index) { return index<7||(alternates&&(index==9||index==11)); };
    std::vector<Tex> tex(alternates?13:9);
    for(unsigned i=0;i<tex.size();++i) {
        auto& t=tex[i]; int fmt=DXGI_FORMAT_R16G16B16A16_FLOAT; std::string path;
        if(isInput(i)) { job>>std::quoted(path)>>fmt>>t.frames; t.input.open(path,std::ios::binary); if(!t.input) throw std::runtime_error("input: "+path); }
        t.format=DXGI_FORMAT(fmt); t.bpp=fmt==DXGI_FORMAT_R16G16B16A16_FLOAT?8:4;
        D3D12_RESOURCE_DESC d{}; d.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D; d.Width=w; d.Height=h; d.DepthOrArraySize=1; d.MipLevels=1; d.Format=t.format; d.SampleDesc.Count=1;
        d.Flags=!isInput(i)?D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS:D3D12_RESOURCE_FLAG_NONE;
        D3D12_HEAP_PROPERTIES hp{}; hp.Type=D3D12_HEAP_TYPE_DEFAULT;
        t.state=!isInput(i)?D3D12_RESOURCE_STATE_UNORDERED_ACCESS:D3D12_RESOURCE_STATE_COPY_DEST;
        hr(dev->CreateCommittedResource(&hp,D3D12_HEAP_FLAG_NONE,&d,t.state,nullptr,IID_PPV_ARGS(&t.tex)),"texture");
        std::wstring resourceName=L"RR_test_"+std::to_wstring(i); t.tex->SetName(resourceName.c_str());
        dev->GetCopyableFootprints(&d,0,1,0,&t.footprint,nullptr,nullptr,&t.size);
        t.staging=buffer(t.size,!isInput(i)?D3D12_HEAP_TYPE_READBACK:D3D12_HEAP_TYPE_UPLOAD);
        t.api.resource=t.tex.Get(); t.api.state=!isInput(i)?FFX_API_RESOURCE_STATE_UNORDERED_ACCESS:FFX_API_RESOURCE_STATE_PIXEL_COMPUTE_READ;
        t.api.description={FFX_API_RESOURCE_TYPE_TEXTURE2D,ffxApiGetSurfaceFormatDX12(t.format),w,h,1,1,0,uint32_t(!isInput(i)?FFX_API_RESOURCE_USAGE_UAV:FFX_API_RESOURCE_USAGE_READ_ONLY)};
        if(isInput(i)) {
            t.input.seekg(0,std::ios::end);
            if(t.input.tellg()!=std::streamoff(uint64_t(w)*h*t.bpp*t.frames)) throw std::runtime_error("input byte count: "+path);
            t.input.seekg(0);
        }
    }
    std::string diffOut,specOut,directSpecOut,indirectDiffOut; job>>std::quoted(diffOut)>>std::quoted(specOut);
    if(alternates) job>>std::quoted(directSpecOut)>>std::quoted(indirectDiffOut);
    if(!job) throw std::runtime_error("invalid texture records");
    std::ofstream outD(diffOut,std::ios::binary),outS(specOut,std::ios::binary),outDirectSpec,outIndirectDiff;
    if(alternates) { outDirectSpec.open(directSpecOut,std::ios::binary); outIndirectDiff.open(indirectDiffOut,std::ios::binary); }
    if(!outD||!outS||(alternates&&(!outDirectSpec||!outIndirectDiff))) throw std::runtime_error("output open");
    // Load this exact DLL directly, so provider selection cannot silently use a different DLL.
    HMODULE module=LoadLibraryExW(std::filesystem::path(dllPath).c_str(),nullptr,LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR|LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
    if(!module) throw std::runtime_error("LoadLibrary error="+std::to_string(GetLastError()));
    ffxFunctions api{}; ffxLoadFunctions(&api,module);
    if(!api.CreateContext||!api.Query||!api.Dispatch||!api.Configure||!api.DestroyContext) throw std::runtime_error("missing FFX exports");
    wchar_t actualPath[32768]{}; GetModuleFileNameW(module,actualPath,32768); std::wcout<<L"dll="<<actualPath<<L'\n';
    ffxConfigureDescGlobalDebug logging{{FFX_API_CONFIGURE_DESC_TYPE_GLOBALDEBUG,nullptr},FFX_API_EFFECT_ID_DENOISER,message,FFX_API_CONFIGURE_GLOBALDEBUG_LEVEL_VERBOSE};
    ff(api.Configure(nullptr,&logging.header),"global debug");
    ffxCreateBackendDX12Desc backend{{FFX_API_CREATE_CONTEXT_DESC_TYPE_BACKEND_DX12,nullptr},dev.Get()};
    const unsigned signalMask=diffFlag|specFlag|(alternates?(FFX_DENOISER_SIGNAL_DIRECT_SPECULAR|FFX_DENOISER_SIGNAL_INDIRECT_DIFFUSE):0);
    ffxCreateContextDescDenoiser create{{FFX_API_CREATE_CONTEXT_DESC_TYPE_DENOISER,&backend.header},FFX_DENOISER_VERSION,{w,h},signalMask,0,FFX_DENOISER_ENABLE_VALIDATION};
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
    ffxDispatchDescDenoiserDirectSpecular directSpec{};
    ffxDispatchDescDenoiserIndirectDiffuse indirectDiff{};
    if(alternates) {
        directSpec.header.type=FFX_API_DISPATCH_DESC_TYPE_DENOISER_DIRECT_SPECULAR;
        directSpec.signal.input=tex[9].api; directSpec.signal.output=tex[10].api;
        indirectDiff.header.type=FFX_API_DISPATCH_DESC_TYPE_DENOISER_INDIRECT_DIFFUSE;
        indirectDiff.signal.input=tex[11].api; indirectDiff.signal.output=tex[12].api;
        // Match production's sort by typed descriptor ID.
        diff.header.pNext=&directSpec.header; directSpec.header.pNext=&indirectDiff.header;
        indirectDiff.header.pNext=&spec.header; spec.header.pNext=nullptr;
        std::cout<<"alternate_signals=direct_specular,indirect_diffuse signal_mask="<<signalMask<<'\n';
    }
    unsigned validationErrors=0,validationWarnings=0;
    // Pointer-free, exact applied controls, not merely the texture identities.
    std::ofstream controlsOut(std::filesystem::path(argv[1]).parent_path()/"dispatch_controls.bin",std::ios::binary);
    std::ifstream controlsIn(std::filesystem::path(argv[1]).parent_path()/"frame_controls.txt");
    if(!controlsOut) throw std::runtime_error("controls output open");
    std::vector<char> row(size_t(w)*8);
    for(unsigned frame=0;frame<frames;++frame) {
        hr(alloc->Reset(),"reset allocator"); hr(cmd->Reset(alloc.Get(),nullptr),"reset list");
        for(unsigned i=0;i<tex.size();++i) {
            if(!isInput(i)) continue;
            auto& t=tex[i]; if(frame&&t.frames==1) continue;
            if(t.frames!=1&&t.frames!=frames) throw std::runtime_error("input frames must be 1 or job frames");
            barrier(t,D3D12_RESOURCE_STATE_COPY_DEST);
            char* mapped=nullptr; D3D12_RANGE empty{0,0}; hr(t.staging->Map(0,&empty,reinterpret_cast<void**>(&mapped)),"upload map");
            for(unsigned y=0;y<h;++y) t.input.read(mapped+t.footprint.Offset+y*t.footprint.Footprint.RowPitch,size_t(w)*t.bpp);
            t.staging->Unmap(0,nullptr); if(!t.input) throw std::runtime_error("input read");
            D3D12_TEXTURE_COPY_LOCATION src{}; src.pResource=t.staging.Get(); src.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT; src.PlacedFootprint=t.footprint;
            D3D12_TEXTURE_COPY_LOCATION dst{}; dst.pResource=t.tex.Get(); dst.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
            cmd->CopyTextureRegion(&dst,0,0,0,&src,nullptr);
            barrier(t,D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE|D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
        }
        dispatch.frameIndex=frame;
        dispatch.flags=FFX_DENOISER_DISPATCH_NON_GAMMA_ALBEDO|((frame==0||resetEvery)?FFX_DENOISER_DISPATCH_RESET:0);
        if(controlsIn.is_open()) {
            unsigned reset; float jx,jy;
            controlsIn>>reset>>jx>>jy;
            if(!controlsIn||reset>1||!std::isfinite(jx)||!std::isfinite(jy))
                throw std::runtime_error("invalid per-frame controls");
            dispatch.flags=FFX_DENOISER_DISPATCH_NON_GAMMA_ALBEDO|((frame==0||reset)?FFX_DENOISER_DISPATCH_RESET:0);
            dispatch.jitterOffsets={jx,jy};
        }
#ifdef FSRD_RR_FRAME_CAMERA_HOOK
        FSRD_RR_FRAME_CAMERA_HOOK(dispatch,frame,frames,argv[1]);
#endif
        auto record=[&](const auto& value) { controlsOut.write(reinterpret_cast<const char*>(&value),sizeof(value)); };
        record(dispatch.frameIndex); record(dispatch.flags); record(dispatch.renderSize);
        record(dispatch.motionVectorScale); record(dispatch.cameraPositionDelta);
        record(dispatch.jitterOffsets); record(dispatch.linearDepthBounds);
        record(dispatch.view); record(dispatch.projection);
        ff(api.Dispatch(&context,&dispatch.header),"dispatch RR");
        for(unsigned i=7;i<tex.size();++i) {
            if(isInput(i)) continue;
            if((i==7&&!diffFlag)||(i==8&&!specFlag)) continue;
            auto& t=tex[i]; barrier(t,D3D12_RESOURCE_STATE_COPY_SOURCE);
            D3D12_TEXTURE_COPY_LOCATION src{}; src.pResource=t.tex.Get(); src.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
            D3D12_TEXTURE_COPY_LOCATION dst{}; dst.pResource=t.staging.Get(); dst.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT; dst.PlacedFootprint=t.footprint;
            cmd->CopyTextureRegion(&dst,0,0,0,&src,nullptr); barrier(t,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
        }
        hr(cmd->Close(),"close"); ID3D12CommandList* lists[]={cmd.Get()}; queue->ExecuteCommandLists(1,lists);
        hr(queue->Signal(fence.Get(),frame+1),"signal"); hr(fence->SetEventOnCompletion(frame+1,event),"event");
        if(WaitForSingleObject(event,60000)!=WAIT_OBJECT_0) throw std::runtime_error("GPU timeout");
        hr(dev->GetDeviceRemovedReason(),"device removed");
        for(unsigned i=7;i<tex.size();++i) {
            if(isInput(i)) continue;
            if((i==7&&!diffFlag)||(i==8&&!specFlag)) continue;
            auto& t=tex[i]; char* mapped=nullptr; hr(t.staging->Map(0,nullptr,reinterpret_cast<void**>(&mapped)),"readback");
            auto& output=i==7?outD:(i==8?outS:(i==10?outDirectSpec:outIndirectDiff));
            for(unsigned y=0;y<h;++y) output.write(mapped+t.footprint.Offset+y*t.footprint.Footprint.RowPitch,size_t(w)*8);
            t.staging->Unmap(0,nullptr);
        }
        if(info) {
            for(UINT64 i=0;i<info->GetNumStoredMessages();++i) {
                SIZE_T n=0; info->GetMessage(i,nullptr,&n); std::vector<char> bytes(n); auto* m=reinterpret_cast<D3D12_MESSAGE*>(bytes.data()); info->GetMessage(i,m,&n);
                if(m->Severity<=D3D12_MESSAGE_SEVERITY_ERROR) {++validationErrors; std::cerr<<m->pDescription<<'\n';}
                else if(m->Severity==D3D12_MESSAGE_SEVERITY_WARNING) {++validationWarnings; if(validationWarnings<8) std::cerr<<m->pDescription<<'\n';}
            }
            info->ClearStoredMessages();
        }
    }
    controlsOut.close(); if(!controlsOut) throw std::runtime_error("controls output write");
    ff(api.DestroyContext(&context,nullptr),"destroy RR"); CloseHandle(event); FreeLibrary(module);
    std::cout<<"dispatches="<<frames<<" validation_errors="<<validationErrors<<" validation_warnings="<<validationWarnings<<" sdk_errors="<<sdkErrors<<" sdk_warnings="<<sdkWarnings<<'\n';
    if(validationErrors||sdkErrors) return 2;
    return 0;
} catch(const std::exception& e) { std::cerr<<e.what()<<'\n'; return 1; }
