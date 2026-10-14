#define FSRD_NRD_BRIDGE_RR_TEST_BACKEND
#include "../../fsrd_preprocess/FSRDNrdBridgeRR_Dx12.cpp"
#include <d3d12sdklayers.h>
#include <DirectXPackedVector.h>
#include <fstream>
#include <iostream>
#include <filesystem>
#include <stdexcept>
#include <numeric>
#ifdef near
#undef near
#endif

namespace FrameSurvey
{
ScopedInternal::ScopedInternal() noexcept : previous_(false) {}
ScopedInternal::~ScopedInternal() {}
}

using Microsoft::WRL::ComPtr;
using namespace DirectX;
using namespace NrdBridge;
static unsigned checks = 0;
void need(bool value, const char* text) { ++checks; if (!value) throw std::runtime_error(text); }
void hr(HRESULT code) { if (FAILED(code)) throw std::runtime_error("D3D12 call failed: " + std::to_string(uint32_t(code))); }
bool near(float a, float b) { return std::abs(a-b) < 1.e-5f; }
SLConstantsSnapshot camera(uint32_t frame = 100, float aspect = 4.f/3.f)
{
    SLConstantsSnapshot snapshot;
    snapshot.frameIndex = frame;
    auto& c = snapshot.constants;
    const float y = 1.f / std::tan(XM_PI/6.f);
    c.cameraViewToClip[0] = sl::float4(y/aspect,0,0,0);
    c.cameraViewToClip[1] = sl::float4(0,y,0,0);
    c.cameraViewToClip[2] = sl::float4(0,0,0,-1);
    c.cameraViewToClip[3] = sl::float4(0,0,.01f,0);
    c.cameraPos = sl::float3(0,0,0);
    c.cameraRight = sl::float3(1,0,0);
    c.cameraUp = sl::float3(0,1,0);
    c.cameraFwd = sl::float3(0,0,-1);
    c.cameraNear = .01f; c.cameraFar = 0; c.cameraFOV = XM_PI/3.f; c.cameraAspectRatio = aspect;
    c.mvecScale = sl::float2(.5f,.25f); c.jitterOffset = sl::float2(.25f,-.125f);
    c.depthInverted = sl::Boolean::eTrue; c.reset = sl::Boolean::eFalse;
    c.cameraMotionIncluded = sl::Boolean::eTrue; c.motionVectors3D = sl::Boolean::eFalse;
    return snapshot;
}
void cameraChecks()
{
    RRWrapper wrapper;
    FrameParameters frame;
    std::string error;
    need(wrapper.ContextGeneration()==0, "context must be lazy");
    need(wrapper.CameraConventionDescription().empty(), "logging must be lazy");
    auto snapshot = camera();
    need(wrapper.PrepareFrame(snapshot,false,frame,error), "valid SL camera rejected");
    need(frame.reset && !frame.previousValid && frame.frameIndex==0, "first frame reset");
    need(frame.streamlineFrame==100 && near(frame.nearPlane,.01f) && frame.farPlane==65504.f,
         "SL frame/infinite planes");
    need(frame.depthSign==-1 && frame.camera.isRightHanded, "RH signed depth");
    need(near(frame.motionScale.x,.5f) && near(frame.motionScale.y,.25f), "MV scales retained");
    need(near(frame.jitter.x,.25f) && near(frame.jitter.y,-.125f), "jitter must remain pixels");
    need(!wrapper.CameraConventionDescription().empty(), "one convention log available");
    const auto log = wrapper.CameraConventionDescription();
    snapshot.constants.cameraViewToClip[2].x = .11f;
    snapshot.constants.cameraViewToClip[2].y = -.07f;
    need(wrapper.PrepareFrame(snapshot,false,frame,error), "asymmetric camera rejected");
    XMFLOAT4X4 matrix; XMStoreFloat4x4(&matrix,frame.camera.projection);
    need(near(matrix.m[0][2],.11f) && near(matrix.m[1][2],-.07f), "SL off-axis terms preserved");
    need(wrapper.CameraConventionDescription()==log, "convention description allocated once");
    need(frame.frameIndex==0 && frame.reset, "Prepare does not commit history");
    const auto rr = GetRRMatrix(frame.camera.projection);
    XMFLOAT4X4 expected; XMStoreFloat4x4(&expected, XMMatrixTranspose(frame.camera.projection));
    need(std::memcmp(&rr,&expected,sizeof(rr))==0, "RR matrix contract uses shared transpose");
    auto rejected = [&](SLConstantsSnapshot value, const char* reason) {
        need(!wrapper.PrepareFrame(value,false,frame,error), reason);
        need(!error.empty(), "fail closed must explain rejection");
    };
    SLConstantsSnapshot missing;
    rejected(missing, "missing snapshot rejected");
    auto bad = camera(); bad.constants.motionVectors3D=sl::Boolean::eTrue; rejected(bad,"3D MV rejected");
    bad=camera(); bad.constants.motionVectors3D=sl::Boolean::eInvalid; rejected(bad,"missing MV dimension rejected");
    bad=camera(); bad.constants.motionVectorsJittered=sl::Boolean::eInvalid; rejected(bad,"missing jitter convention rejected");
    bad=camera(); bad.constants.depthInverted=sl::Boolean::eInvalid; rejected(bad,"missing depth convention rejected");
    bad=camera(); bad.constants.reset=sl::Boolean::eInvalid; rejected(bad,"missing reset rejected");
    bad=camera(); bad.constants.cameraMotionIncluded=sl::Boolean::eFalse; rejected(bad,"camera motion absent rejected");
    bad=camera(); bad.constants.mvecScale.x=sl::INVALID_FLOAT; rejected(bad,"sentinel MV scale rejected");
    bad=camera(); bad.constants.mvecScale.y=0; rejected(bad,"zero MV scale rejected");
    bad=camera(); bad.constants.jitterOffset.x=std::numeric_limits<float>::quiet_NaN(); rejected(bad,"NaN jitter rejected");
    bad=camera(); bad.constants.cameraPos.z=sl::INVALID_FLOAT; rejected(bad,"sentinel camera rejected");
    bad=camera(); bad.constants.cameraRight=sl::float3(0,0,0); rejected(bad,"singular basis rejected");
    bad=camera(); bad.constants.orthographicProjection=sl::Boolean::eTrue; rejected(bad,"ortho rejected");
    bad=camera(); for(unsigned r=0;r<4;++r) bad.constants.cameraViewToClip[r]=sl::float4(0,0,0,0);
    bad.constants.cameraFOV=sl::INVALID_FLOAT; rejected(bad,"missing projection rejected");
    for(bool rightHanded : {false,true}) for(bool inverted : {false,true})
    {
        auto valid=camera();
        const auto rows=rightHanded ? XMMatrixPerspectiveFovRH(XM_PI/3,4.f/3,inverted?100.f:.1f,inverted?.1f:100.f)
            : XMMatrixPerspectiveFovLH(XM_PI/3,4.f/3,inverted?100.f:.1f,inverted?.1f:100.f);
        XMFLOAT4X4 p; XMStoreFloat4x4(&p,rows);
        for(unsigned r=0;r<4;++r) valid.constants.cameraViewToClip[r]=sl::float4(p.m[r][0],p.m[r][1],p.m[r][2],p.m[r][3]);
        valid.constants.depthInverted=inverted?sl::Boolean::eTrue:sl::Boolean::eFalse;
        valid.constants.cameraFwd=sl::float3(0,0,rightHanded?-1.f:1.f);
        need(wrapper.PrepareFrame(valid,false,frame,error), "finite projection rejected");
        need(std::abs(frame.nearPlane-.1f)<.001f && std::abs(frame.farPlane-100.f)<.01f, "finite planes");
        need(frame.depthSign==(rightHanded?-1.f:1.f), "handedness is independent of depth inversion");
    }
}
struct Host
{
    ComPtr<ID3D12Device> device;
    ComPtr<ID3D12CommandQueue> queue;
    ComPtr<ID3D12CommandAllocator> allocator;
    ComPtr<ID3D12GraphicsCommandList> list;
    ComPtr<ID3D12InfoQueue> info;
    Host()
    {
        ComPtr<ID3D12Debug> debug; hr(D3D12GetDebugInterface(IID_PPV_ARGS(&debug))); debug->EnableDebugLayer();
        ComPtr<IDXGIFactory6> factory; hr(CreateDXGIFactory1(IID_PPV_ARGS(&factory)));
        ComPtr<IDXGIAdapter1> adapter; hr(factory->EnumAdapterByGpuPreference(0,DXGI_GPU_PREFERENCE_HIGH_PERFORMANCE,IID_PPV_ARGS(&adapter)));
        hr(D3D12CreateDevice(adapter.Get(),D3D_FEATURE_LEVEL_12_0,IID_PPV_ARGS(&device)));
        hr(device.As(&info));
        D3D12_COMMAND_QUEUE_DESC desc{}; hr(device->CreateCommandQueue(&desc,IID_PPV_ARGS(&queue)));
        hr(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT,IID_PPV_ARGS(&allocator)));
        hr(device->CreateCommandList(0,D3D12_COMMAND_LIST_TYPE_DIRECT,allocator.Get(),nullptr,IID_PPV_ARGS(&list)));
        RecordedComputeLease::SetHooksAvailable(true,true);
    }
    void reset()
    {
        auto recording=RecordedComputeLease::Capture(list.Get());
        hr(allocator->Reset()); hr(list->Reset(allocator.Get(),nullptr));
        RecordedComputeLease::Detach(recording);
    }
    void submit(bool wait=true)
    {
        hr(list->Close());
        ComPtr<IUnknown> identity; hr(list.As(&identity));
        auto submission=RecordedComputeLease::BeforeSubmission(queue.Get(),{identity.Get()});
        ID3D12CommandList* lists[]={list.Get()}; queue->ExecuteCommandLists(1,lists);
        RecordedComputeLease::AfterSubmission(submission);
        if(wait) finish();
    }
    void finish()
    {
        ComPtr<ID3D12Fence> fence; hr(device->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&fence)));
        hr(queue->Signal(fence.Get(),1));
        HANDLE event=CreateEvent(nullptr,FALSE,FALSE,nullptr); need(event!=nullptr,"create fence event");
        hr(fence->SetEventOnCompletion(1,event));
        const auto wait=WaitForSingleObject(event,60000); CloseHandle(event); need(wait==WAIT_OBJECT_0,"GPU timeout");
        RecordedComputeLease::Poll();
    }
    void checkDebug()
    {
        unsigned errors=0;
        for(UINT64 i=0;i<info->GetNumStoredMessages();++i)
        {
            SIZE_T bytes=0; info->GetMessage(i,nullptr,&bytes); std::vector<uint8_t> memory(bytes);
            auto* message=reinterpret_cast<D3D12_MESSAGE*>(memory.data()); hr(info->GetMessage(i,message,&bytes));
            if(message->Severity==D3D12_MESSAGE_SEVERITY_ERROR || message->Severity==D3D12_MESSAGE_SEVERITY_CORRUPTION)
            { ++errors; std::cerr<<message->pDescription<<'\n'; }
        }
        need(errors==0,"D3D12 debug layer errors");
    }
};
void barrier(ID3D12GraphicsCommandList* list,ID3D12Resource* resource,D3D12_RESOURCE_STATES before,D3D12_RESOURCE_STATES after)
{
    D3D12_RESOURCE_BARRIER b{}; b.Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    b.Transition={resource,D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,before,after}; list->ResourceBarrier(1,&b);
}
ComPtr<ID3D12Resource> buffer(ID3D12Device* device,UINT64 size,D3D12_HEAP_TYPE type)
{
    D3D12_HEAP_PROPERTIES heap{}; heap.Type=type;
    D3D12_RESOURCE_DESC desc{}; desc.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER; desc.Width=size;
    desc.Height=desc.DepthOrArraySize=desc.MipLevels=1; desc.SampleDesc.Count=1; desc.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
    ComPtr<ID3D12Resource> resource;
    hr(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&desc,
        type==D3D12_HEAP_TYPE_UPLOAD?D3D12_RESOURCE_STATE_GENERIC_READ:D3D12_RESOURCE_STATE_COPY_DEST,nullptr,IID_PPV_ARGS(&resource)));
    return resource;
}
void ClearPair(ID3D12GraphicsCommandList* list, ID3D12Resource* spec, ID3D12Resource* diff,
               const std::array<float,4>& specValue, const std::array<float,4>& diffValue)
{
    struct Owner { ComPtr<ID3D12Device> device; ComPtr<ID3D12DescriptorHeap> heap, cpuHeap; };
    auto owner=MakeOwnedShared<Owner>();hr(list->GetDevice(IID_PPV_ARGS(&owner->device)));
    D3D12_DESCRIPTOR_HEAP_DESC desc{};desc.Type=D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;
    desc.Flags=D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;desc.NumDescriptors=2;
    hr(owner->device->CreateDescriptorHeap(&desc,IID_PPV_ARGS(&owner->heap)));
    desc.Flags=D3D12_DESCRIPTOR_HEAP_FLAG_NONE;hr(owner->device->CreateDescriptorHeap(&desc,IID_PPV_ARGS(&owner->cpuHeap)));
    need(ResTrack_Dx12::RetainComputeDispatch(owner->device.Get(),list,owner),"retain mock provider writes");
    ID3D12DescriptorHeap* heaps[]={owner->heap.Get()};list->SetDescriptorHeaps(1,heaps);
    auto cpu=owner->heap->GetCPUDescriptorHandleForHeapStart();auto gpu=owner->heap->GetGPUDescriptorHandleForHeapStart();
    auto nonVisible=owner->cpuHeap->GetCPUDescriptorHandleForHeapStart();
    const auto stride=owner->device->GetDescriptorHandleIncrementSize(desc.Type);
    for(auto* resource:{spec,diff})
    {
        D3D12_UNORDERED_ACCESS_VIEW_DESC view{};view.Format=DXGI_FORMAT_R16G16B16A16_FLOAT;view.ViewDimension=D3D12_UAV_DIMENSION_TEXTURE2D;
        owner->device->CreateUnorderedAccessView(resource,nullptr,&view,cpu);
        owner->device->CreateUnorderedAccessView(resource,nullptr,&view,nonVisible);
        list->ClearUnorderedAccessViewFloat(gpu,nonVisible,resource,resource==spec?specValue.data():diffValue.data(),0,nullptr);
        D3D12_RESOURCE_BARRIER barrier{};barrier.Type=D3D12_RESOURCE_BARRIER_TYPE_UAV;barrier.UAV.pResource=resource;
        list->ResourceBarrier(1,&barrier);cpu.ptr+=stride;gpu.ptr+=stride;nonVisible.ptr+=stride;
    }
}
void RecordTestProviderWrites(ID3D12GraphicsCommandList* list, ID3D12Resource* spec, ID3D12Resource* diff)
{
    ClearPair(list,spec,diff,{2.5f,3.75f,4.25f,5.5f},{6.5f,7.75f,8.25f,9.5f});
}
struct Scene
{
    ConvertedResources resources;
    std::array<ComPtr<ID3D12Resource>,9> textures;
    std::vector<ComPtr<ID3D12Resource>> uploads;
    uint32_t width,height;
    Scene(Host& host,uint32_t w,uint32_t h,const std::filesystem::path& files={}) : width(w),height(h)
    {
        resources.width=w;resources.height=h;
        const std::array<DXGI_FORMAT,9> formats{DXGI_FORMAT_R16G16B16A16_FLOAT,DXGI_FORMAT_R16G16B16A16_FLOAT,
            DXGI_FORMAT_R32_FLOAT,DXGI_FORMAT_R16G16B16A16_FLOAT,DXGI_FORMAT_R10G10B10A2_UNORM,
            DXGI_FORMAT_R8G8B8A8_UNORM,DXGI_FORMAT_R8G8B8A8_UNORM,DXGI_FORMAT_R16G16B16A16_FLOAT,DXGI_FORMAT_R16G16B16A16_FLOAT};
        const std::array<const char*,7> names{"spec","diff","depth","motion","normals","spec_albedo","diff_albedo"};
        D3D12_HEAP_PROPERTIES heap{};heap.Type=D3D12_HEAP_TYPE_DEFAULT;
        for(unsigned i=0;i<9;++i)
        {
            D3D12_RESOURCE_DESC desc{};desc.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D;desc.Width=w;desc.Height=h;
            desc.DepthOrArraySize=desc.MipLevels=1;desc.SampleDesc.Count=1;desc.Format=formats[i];desc.Flags=D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
            hr(host.device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&desc,i<7?D3D12_RESOURCE_STATE_COPY_DEST:
                D3D12_RESOURCE_STATE_UNORDERED_ACCESS,nullptr,IID_PPV_ARGS(&textures[i])));
            if(i>=7)continue;
            const unsigned bpp=(i==0 || i==1 || i==3)?8:4;
            std::vector<uint8_t> data(size_t(w)*h*bpp);
            if(!files.empty())
            {
                std::ifstream input(files/(std::string(names[i])+".bin"),std::ios::binary);
                need(bool(input),"capture fixture input missing");input.read(reinterpret_cast<char*>(data.data()),data.size());
                need(input.gcount()==data.size(),"capture fixture input size mismatch");
            }
            else for(size_t p=0;p<size_t(w)*h;++p)
            {
                if(i==0 || i==1)
                {
                    auto* value=reinterpret_cast<uint16_t*>(data.data()+p*bpp);
                    const float noise=((p*17+13)%11)/1000.f;
                    for(unsigned c=0;c<3;++c)value[c]=PackedVector::XMConvertFloatToHalf((i==0?.02f:.1f)+noise);
                    value[3]=PackedVector::XMConvertFloatToHalf(5.f);
                }
                else if(i==2)*reinterpret_cast<float*>(data.data()+p*bpp)=-10.f;
                else if(i==3)reinterpret_cast<uint16_t*>(data.data()+p*bpp)[3]=PackedVector::XMConvertFloatToHalf(1.f);
                else if(i==4)*reinterpret_cast<uint32_t*>(data.data()+p*bpp)=512u|(512u<<10)|(512u<<20);
                else { auto* value=data.data()+p*bpp;value[0]=value[1]=value[2]=255;value[3]=i==5?255:0; }
            }
            D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint{};UINT rows;UINT64 rowBytes,total;
            host.device->GetCopyableFootprints(&desc,0,1,0,&footprint,&rows,&rowBytes,&total);
            auto upload=buffer(host.device.Get(),total,D3D12_HEAP_TYPE_UPLOAD);void* mapped;hr(upload->Map(0,nullptr,&mapped));
            for(UINT row=0;row<h;++row)std::memcpy(static_cast<uint8_t*>(mapped)+footprint.Offset+row*footprint.Footprint.RowPitch,
                data.data()+size_t(row)*w*bpp,size_t(w)*bpp);
            upload->Unmap(0,nullptr);
            D3D12_TEXTURE_COPY_LOCATION target{},source{};target.pResource=textures[i].Get();target.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
            source.pResource=upload.Get();source.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;source.PlacedFootprint=footprint;
            host.list->CopyTextureRegion(&target,0,0,0,&source,nullptr);
            barrier(host.list.Get(),textures[i].Get(),D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
            uploads.push_back(std::move(upload));
        }
        resources.spec=textures[0].Get();resources.diff=textures[1].Get();resources.linearDepth=textures[2].Get();
        resources.motion=textures[3].Get();resources.normals=textures[4].Get();resources.specAlbedo=textures[5].Get();resources.diffAlbedo=textures[6].Get();
        // Opaque title alpha is initialized independently of both RR signal inputs
        // and the provider's staged alpha, then checked after real and mock dispatches.
        ClearPair(host.list.Get(),spec(),diff(),{.125f,.25f,.5f,.75f},{1.25f,1.5f,1.75f,2.f});
    }
    ID3D12Resource* spec(){return textures[7].Get();} ID3D12Resource* diff(){return textures[8].Get();}
};
void descriptorChecks(const FrameParameters& frame)
{
    const auto& d=FfxApiProxy::lastDispatch;
    need(d.header.type==FFX_API_DISPATCH_DESC_TYPE_DENOISER, "dispatch descriptor header");
    need(FfxApiProxy::lastDiffuse.header.type==FFX_API_DISPATCH_DESC_TYPE_DENOISER_DIRECT_DIFFUSE &&
        FfxApiProxy::lastSpecular.header.type==FFX_API_DISPATCH_DESC_TYPE_DENOISER_INDIRECT_SPECULAR, "ordered two-signal chain");
    need(FfxApiProxy::lastSpecular.header.pNext==nullptr,"exactly two signals");
    for(auto* guide:{&d.linearDepth,&d.motionVectors,&d.normals,&d.specularAlbedo,&d.diffuseAlbedo})
        need(guide->state==FFX_API_RESOURCE_STATE_COMPUTE_READ,"guides COMPUTE_READ");
    need(FfxApiProxy::lastDiffuse.signal.input.state==FFX_API_RESOURCE_STATE_COMPUTE_READ &&
        FfxApiProxy::lastSpecular.signal.input.state==FFX_API_RESOURCE_STATE_COMPUTE_READ,"signal inputs COMPUTE_READ");
    need(FfxApiProxy::lastDiffuse.signal.output.state==FFX_API_RESOURCE_STATE_UNORDERED_ACCESS &&
        FfxApiProxy::lastSpecular.signal.output.state==FFX_API_RESOURCE_STATE_UNORDERED_ACCESS,"title outputs UAV");
    need(d.motionVectorScale.x==1 && d.motionVectorScale.y==1 && d.motionVectorScale.z==1,"normalized motion unit scales");
    need(near(d.jitterOffsets.x,frame.jitter.x) && near(d.jitterOffsets.y,frame.jitter.y),"RR jitter in pixels");
    need(d.flags&FFX_DENOISER_DISPATCH_NON_GAMMA_ALBEDO,"linear white albedos flag");
}
void historyChecks(Host& host)
{
    Scene scene(host,FfxApiProxy::real?1505u:64u,FfxApiProxy::real?847u:64u);host.submit();host.reset();
    RRWrapper wrapper;FrameParameters frame;std::string error;
    auto step=[&](SLConstantsSnapshot snapshot,bool requested=false){
        need(wrapper.PrepareFrame(snapshot,requested,frame,error),"prepare history frame");
        need(wrapper.Dispatch(host.list.Get(),scene.resources,scene.spec(),scene.diff(),frame,error),error.c_str());
        host.submit();host.reset();
    };
    step(camera(100));need(FfxApiProxy::lastDispatch.flags&FFX_DENOISER_DISPATCH_RESET,"first dispatch reset");
    need(wrapper.ContextGeneration()==1,"lazy context creation once");
    need(FfxApiProxy::lastCreate.signalFlags==(FFX_DENOISER_SIGNAL_DIRECT_DIFFUSE|FFX_DENOISER_SIGNAL_INDIRECT_SPECULAR),"two-signal context mask");
    descriptorChecks(frame);
    auto next=camera(101);next.constants.cameraPos=sl::float3(1,2,3);next.constants.jitterOffset=sl::float2(-.2f,.3f);step(next);
    need(!frame.reset && frame.previousValid && frame.frameIndex==1,"successful history advances");
    need(near(frame.previousJitter.x,.25f) && near(frame.previousJitter.y,-.125f),"previous jitter from dispatched frame");
    need(!(FfxApiProxy::lastDispatch.flags&FFX_DENOISER_DISPATCH_RESET),"consecutive dispatch preserves history");
    need(FfxApiProxy::lastDispatch.cameraPositionDelta.x==-1 && FfxApiProxy::lastDispatch.cameraPositionDelta.y==-2 &&
        FfxApiProxy::lastDispatch.cameraPositionDelta.z==-3,"camera delta is previous minus current");
    step(camera(103));need(frame.reset,"SL frame gap resets history");
    step(camera(104),true);need(frame.reset,"discovery/menu request resets history");
    wrapper.ResetHistory();step(camera(105));need(frame.reset,"explicit reset resets history");
    next=camera(106);next.constants.reset=sl::Boolean::eTrue;step(next);need(frame.reset,"SL reset honored");
    next=camera(107);next.constants.motionVectorsJittered=sl::Boolean::eTrue;step(next);need(frame.reset,"MV convention change resets");
    auto invalid=camera(108);invalid.constants.jitterOffset.x=sl::INVALID_FLOAT;
    need(!wrapper.PrepareFrame(invalid,false,frame,error),"invalid frame rejected between valid frames");
    step(camera(108));need(frame.reset,"rejected camera frame resets next dispatch");
    const auto before=FfxApiProxy::dispatches;
    need(wrapper.PrepareFrame(camera(109),false,frame,error),"prepare rejected dispatch");
    ConvertedResources alias=scene.resources;alias.diff=scene.diff();
    need(!wrapper.Dispatch(host.list.Get(),alias,scene.spec(),scene.diff(),frame,error),"output-input alias fails closed");
    need(FfxApiProxy::dispatches==before,"validation failure dispatches no AMD work");
    step(camera(109));need(frame.reset,"rejected input dispatch resets next frame");
    if(!FfxApiProxy::real)
    {
        FfxApiProxy::rejectDispatch=true;
        need(wrapper.PrepareFrame(camera(110),false,frame,error),"prepare AMD failure");
        need(!wrapper.Dispatch(host.list.Get(),scene.resources,scene.spec(),scene.diff(),frame,error),"AMD failure propagated");
        host.submit();host.reset();FfxApiProxy::rejectDispatch=false;
        step(camera(110));need(frame.reset && frame.frameIndex==9,"AMD failure does not commit history");
    }
    step(camera(UINT32_MAX-1));need(frame.reset,"nonconsecutive high SL token resets history");
    step(camera(0));need(!frame.reset && frame.previousValid,"SL token wraps while skipping missing-token sentinel");
    step(camera(1));need(!frame.reset,"history advances normally after SL wrap");
    need(scene.spec()->AddRef()==2 && scene.spec()->Release()==1,"wrapper never retains title spec output");
    need(scene.diff()->AddRef()==2 && scene.diff()->Release()==1,"wrapper never retains title diffuse output");
    need(FfxApiProxy::badDefaults==0,"queried AMD defaults applied unchanged");
}
void lifecycleChecks(Host& host)
{
    const unsigned initialCreates=FfxApiProxy::creates,initialDestroys=FfxApiProxy::destroys;
    ComPtr<ID3D12Fence> gate;hr(host.device->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&gate)));
    struct GateRelease { ID3D12Fence* fence; ~GateRelease(){fence->Signal(1);} } release{gate.Get()};
    auto wrapper=std::make_unique<RRWrapper>();FrameParameters frame;std::string error;
    Scene first(host,FfxApiProxy::real?1505u:64u,FfxApiProxy::real?847u:64u);host.submit();host.reset();
    need(wrapper->PrepareFrame(camera(200),false,frame,error),"prepare first generation");
    need(wrapper->Dispatch(host.list.Get(),first.resources,first.spec(),first.diff(),frame,error),error.c_str());
    hr(host.queue->Wait(gate.Get(),1));host.submit(false);
    auto old=RecordedComputeLease::Capture(host.list.Get());RecordedComputeLease::Detach(old);old.reset();
    // A second command list can record/recreate while generation one remains on a blocked GPU queue.
    ComPtr<ID3D12CommandAllocator> secondAllocator;ComPtr<ID3D12GraphicsCommandList> secondList;
    hr(host.device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT,IID_PPV_ARGS(&secondAllocator)));
    hr(host.device->CreateCommandList(0,D3D12_COMMAND_LIST_TYPE_DIRECT,secondAllocator.Get(),nullptr,IID_PPV_ARGS(&secondList)));
    auto firstAllocator=host.allocator;auto firstList=host.list;host.allocator=secondAllocator;host.list=secondList;
    Scene second(host,FfxApiProxy::real?1536u:80u,FfxApiProxy::real?864u:64u);
    need(wrapper->PrepareFrame(camera(201),false,frame,error),"prepare resized generation");
    need(wrapper->Dispatch(host.list.Get(),second.resources,second.spec(),second.diff(),frame,error),error.c_str());
    need(wrapper->ContextGeneration()==2 && FfxApiProxy::creates==initialCreates+2,"resize recreates context");
    need(FfxApiProxy::lastDispatch.flags&FFX_DENOISER_DISPATCH_RESET,"resized dispatch resets AMD history");
    RecordedComputeLease::Poll();need(FfxApiProxy::destroys==initialDestroys,"pending old GPU context survives resize");
    wrapper.reset();RecordedComputeLease::Poll();need(FfxApiProxy::destroys==initialDestroys,"wrapper shutdown retains recorded/submitted contexts");
    hr(host.list->Close());auto unused=RecordedComputeLease::Capture(host.list.Get());RecordedComputeLease::Detach(unused);unused.reset();
    need(FfxApiProxy::destroys==initialDestroys+1,"unsubmitted discarded generation retires immediately");
    hr(gate->Signal(1));host.finish();
    need(FfxApiProxy::destroys==initialDestroys+2,"old generation destroys only after completion fence");
    host.allocator=firstAllocator;host.list=firstList;host.reset();
}
void providerChecks(Host& host)
{
    Scene scene(host,64,64);host.submit();host.reset();
    FrameParameters frame;std::string error;
    auto reject=[&](const char* text){RRWrapper wrapper;need(wrapper.PrepareFrame(camera(),false,frame,error),"prepare provider reject");
        const auto creates=FfxApiProxy::creates,dispatches=FfxApiProxy::dispatches;
        need(!wrapper.Dispatch(host.list.Get(),scene.resources,scene.spec(),scene.diff(),frame,error),text);
        need(FfxApiProxy::creates==creates && FfxApiProxy::dispatches==dispatches,"incompatible provider fails before create/dispatch");};
    FfxApiProxy::providerName="AMD FSR Denoiser v1.1.0";reject("RR1.1 provider rejected");
    FfxApiProxy::providerName="AMD FSR Denoiser v1.3.0";reject("future RR ABI rejected");
    FfxApiProxy::providerName=nullptr;reject("missing version label rejected");
    FfxApiProxy::providerName="AMD FSR Denoiser v1.2.0";FfxApiProxy::providerCount=0;reject("zero providers rejected");
    FfxApiProxy::providerCount=65;reject("unbounded provider count rejected");FfxApiProxy::providerCount=1;
    FfxApiProxy::initAvailable=false;reject("missing DLL rejected");FfxApiProxy::initAvailable=true;
}
void minimumChecks(Host& host)
{
    Scene scene(host,64,48);host.submit();host.reset();
    RRWrapper wrapper;FrameParameters frame;std::string error;
    need(wrapper.PrepareFrame(camera(),false,frame,error),"prepare tiny-size negative case");
    const auto creates=FfxApiProxy::creates,dispatches=FfxApiProxy::dispatches;
    need(!wrapper.Dispatch(host.list.Get(),scene.resources,scene.spec(),scene.diff(),frame,error),"tiny context fails closed");
    need(error.find("64x64 minimum")!=std::string::npos,"tiny-size rejection reports measured bound");
    need(FfxApiProxy::creates==creates && FfxApiProxy::dispatches==dispatches && wrapper.ContextGeneration()==0,
        "tiny-size guard invokes no provider create/dispatch");
}
void loadReal()
{
    const auto dll=LoadLibraryExW(L"F:/OptiRevelations/OptiScaler-ffxD-alpha/external/FidelityFX-SDK-v2/Kits/FidelityFX/signedbin/amd_fidelityfx_denoiser_dx12.dll",
        nullptr,LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR|LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
    need(dll!=nullptr,"signed real AMD DLL missing");
    FfxApiProxy::createFunction=reinterpret_cast<PfnFfxCreateContext>(GetProcAddress(dll,"ffxCreateContext"));
    FfxApiProxy::destroyFunction=reinterpret_cast<PfnFfxDestroyContext>(GetProcAddress(dll,"ffxDestroyContext"));
    FfxApiProxy::configureFunction=reinterpret_cast<PfnFfxConfigure>(GetProcAddress(dll,"ffxConfigure"));
    FfxApiProxy::queryFunction=reinterpret_cast<PfnFfxQuery>(GetProcAddress(dll,"ffxQuery"));
    FfxApiProxy::dispatchFunction=reinterpret_cast<PfnFfxDispatch>(GetProcAddress(dll,"ffxDispatch"));
    need(FfxApiProxy::createFunction && FfxApiProxy::destroyFunction && FfxApiProxy::configureFunction &&
        FfxApiProxy::queryFunction && FfxApiProxy::dispatchFunction,"real AMD exports missing");FfxApiProxy::real=true;
    struct RRTestGlobalDebug { ffxConfigureDescHeader header; uint64_t effectId; ffxApiMessage fpMessage; uint32_t debugLevel; };
    RRTestGlobalDebug logging {};
    logging.header.type=7u; // v2 generic debug extension; old shared SDK exposes only debug1.
    logging.effectId=FFX_API_EFFECT_ID_DENOISER;
    logging.fpMessage=[](uint32_t type,const wchar_t* message){std::fwprintf(stderr,L"AMD type=%u: %ls\n",type,message);};
    logging.debugLevel=FFX_API_CONFIGURE_GLOBALDEBUG_LEVEL_VERBOSE;
    need(FfxApiProxy::configureFunction(nullptr,&logging.header)==FFX_API_RETURN_OK,"real SDK global debug configure");
}
struct Readback
{
    ComPtr<ID3D12Resource> bufferResource;
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint{};
    Readback(Host& host,ID3D12Resource* output)
    {
        const auto desc=output->GetDesc();UINT rows;UINT64 rowBytes,total;
        host.device->GetCopyableFootprints(&desc,0,1,0,&footprint,&rows,&rowBytes,&total);
        bufferResource=buffer(host.device.Get(),total,D3D12_HEAP_TYPE_READBACK);
        barrier(host.list.Get(),output,D3D12_RESOURCE_STATE_UNORDERED_ACCESS,D3D12_RESOURCE_STATE_COPY_SOURCE);
        D3D12_TEXTURE_COPY_LOCATION source{},target{};source.pResource=output;source.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        target.pResource=bufferResource.Get();target.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;target.PlacedFootprint=footprint;
        host.list->CopyTextureRegion(&target,0,0,0,&source,nullptr);
        barrier(host.list.Get(),output,D3D12_RESOURCE_STATE_COPY_SOURCE,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
    }
    void verify(const std::filesystem::path& file,uint32_t width,uint32_t height)
    {
        uint8_t* data;hr(bufferResource->Map(0,nullptr,reinterpret_cast<void**>(&data)));
        std::ofstream out(file,std::ios::binary);uint64_t finite=0,alphaPreserved=0;double sum=0;float maximum=0;
        const auto nativeAlpha=PackedVector::XMConvertFloatToHalf(file.filename().string().find("spec")!=std::string::npos?.75f:2.f);
        for(uint32_t y=0;y<height;++y)
        {
            const auto* row=reinterpret_cast<const uint16_t*>(data+footprint.Offset+y*footprint.Footprint.RowPitch);
            out.write(reinterpret_cast<const char*>(row),width*8);
            for(uint32_t i=0;i<width*4;++i){const float value=PackedVector::XMConvertHalfToFloat(row[i]);
                finite+=std::isfinite(value);if(i%4<3){sum+=value;maximum=std::max(maximum,value);}
                else alphaPreserved+=row[i]==nativeAlpha;}
        }
        bufferResource->Unmap(0,nullptr);
        need(finite==uint64_t(width)*height*4,"real RR output contains NaN/Inf");
        need(sum>0 && maximum<65504.f,"real RR output is black or saturated");
        need(alphaPreserved==uint64_t(width)*height,"real RR RGB commit preserves every native title alpha sample");
        std::cout<<"output "<<file.filename().string()<<" finite="<<finite<<" meanRGB="<<sum/(double(width)*height*3)
            <<" maxRGB="<<maximum<<'\n';
    }
    void exact(const std::array<float,4>& expected,uint32_t width,uint32_t height)
    {
        uint8_t* data;hr(bufferResource->Map(0,nullptr,reinterpret_cast<void**>(&data)));
        uint64_t matched=0;
        for(uint32_t y=0;y<height;++y)
        {
            const auto* row=reinterpret_cast<const uint16_t*>(data+footprint.Offset+y*footprint.Footprint.RowPitch);
            for(uint32_t x=0;x<width;++x)for(uint32_t c=0;c<4;++c)
                matched+=row[x*4+c]==PackedVector::XMConvertFloatToHalf(expected[c]);
        }
        bufferResource->Unmap(0,nullptr);
        need(matched==uint64_t(width)*height*4,"transactional output must preserve exact RGBA bytes");
    }
};
void partialFailureChecks(Host& host)
{
    Scene scene(host,64,64);host.submit();host.reset();
    const std::array<float,4> specSentinel{.125f,.25f,.5f,.75f},diffSentinel{1.25f,1.5f,1.75f,2.f};
    ClearPair(host.list.Get(),scene.spec(),scene.diff(),specSentinel,diffSentinel);host.submit();host.reset();
    RRWrapper wrapper;FrameParameters frame;std::string error;
    need(wrapper.PrepareFrame(camera(400),false,frame,error),"prepare partial provider failure");
    const auto destroys=FfxApiProxy::destroys,creates=FfxApiProxy::creates;
    FfxApiProxy::recordPartialWrites=true;FfxApiProxy::rejectDispatch=true;
    need(!wrapper.Dispatch(host.list.Get(),scene.resources,scene.spec(),scene.diff(),frame,error),"partially recorded provider error propagated");
    need(FfxApiProxy::lastSpecular.signal.output.resource!=scene.spec() &&
        FfxApiProxy::lastDiffuse.signal.output.resource!=scene.diff(),"provider receives staging, never title outputs");
    need(wrapper.OwnedStagingBytes()==0 && FfxApiProxy::destroys==destroys,"failed generation retired but retained while recorded");
    host.submit();host.reset();need(FfxApiProxy::destroys==destroys+1,"failed generation retires after its partial GPU work completes");
    Readback oldSpec(host,scene.spec()),oldDiff(host,scene.diff());host.submit();host.reset();
    oldSpec.exact(specSentinel,64,64);oldDiff.exact(diffSentinel,64,64);
    FfxApiProxy::rejectDispatch=false;
    need(wrapper.PrepareFrame(camera(401),false,frame,error) && frame.reset && !frame.previousValid,"provider error clears all history");
    need(wrapper.Dispatch(host.list.Get(),scene.resources,scene.spec(),scene.diff(),frame,error),error.c_str());
    need(FfxApiProxy::creates==creates+2 && wrapper.ContextGeneration()==2,"recovery uses a physically fresh provider context");
    Readback newSpec(host,scene.spec()),newDiff(host,scene.diff());host.submit();host.reset();
    newSpec.exact({2.5f,3.75f,4.25f,specSentinel[3]},64,64);newDiff.exact({6.5f,7.75f,8.25f,diffSentinel[3]},64,64);
    need(scene.spec()->AddRef()==2 && scene.spec()->Release()==1,"commit heap never retains title spec output");
    need(scene.diff()->AddRef()==2 && scene.diff()->Release()==1,"commit heap never retains title diffuse output");
    FfxApiProxy::recordPartialWrites=false;
}
struct CommitProbe
{
    bool accepted=false;
    unsigned calls=0,actions=0;
    static bool Admit(void* state,OutputCommitGuard::Action action,void* prepared) noexcept
    {
        auto& probe=*static_cast<CommitProbe*>(state);++probe.calls;
        if(!probe.accepted)return false;
        action(prepared);++probe.actions;return true;
    }
};
void cancelledCommitChecks(Host& host)
{
    Scene scene(host,64,64);host.submit();host.reset();
    RRWrapper wrapper;FrameParameters frame;std::string error;CommitProbe probe;
    OutputCommitGuard guard{&probe,CommitProbe::Admit};
    FfxApiProxy::recordPartialWrites=true;
    const auto creates=FfxApiProxy::creates,destroys=FfxApiProxy::destroys;
    need(wrapper.PrepareFrame(camera(450),false,frame,error),"prepare provider-success cancellation");
    need(!wrapper.Dispatch(host.list.Get(),scene.resources,scene.spec(),scene.diff(),frame,error,guard),
        "expired coordinator admission cancels provider-success title commit");
    need(probe.calls==1 && probe.actions==0 && error.find("ticket expired")!=std::string::npos,
        "allocation-free guard runs exactly once and never records a denied commit");
    need(wrapper.OwnedStagingBytes()==0 && FfxApiProxy::destroys==destroys,"cancelled SDK context stays alive while its commands are unsubmitted");
    Readback oldSpec(host,scene.spec()),oldDiff(host,scene.diff());host.submit();host.reset();
    oldSpec.exact({.125f,.25f,.5f,.75f},64,64);oldDiff.exact({1.25f,1.5f,1.75f,2.f},64,64);
    need(FfxApiProxy::destroys==destroys+1,"cancelled context retires only after its actual GPU work completes");
    probe.accepted=true;
    need(wrapper.PrepareFrame(camera(451),false,frame,error) && frame.reset && !frame.previousValid,
        "denied commit invalidates all private SDK history");
    need(wrapper.Dispatch(host.list.Get(),scene.resources,scene.spec(),scene.diff(),frame,error,guard),error.c_str());
    need(probe.calls==2 && probe.actions==1 && FfxApiProxy::creates==creates+2,
        "accepted recovery records once into a physically new SDK context");
    Readback newSpec(host,scene.spec()),newDiff(host,scene.diff());host.submit();host.reset();
    newSpec.exact({2.5f,3.75f,4.25f,.75f},64,64);newDiff.exact({6.5f,7.75f,8.25f,2.f},64,64);
    FfxApiProxy::recordPartialWrites=false;
}
void stagingPoolChecks(Host& host)
{
    Scene scene(host,64,64);host.submit();host.reset();RRWrapper wrapper;FrameParameters frame;std::string error;
    uint64_t warmed=0;
    for(uint32_t i=0;i<32;++i)
    {
        need(wrapper.PrepareFrame(camera(1000+i),false,frame,error),"prepare pooled recording");
        need(wrapper.Dispatch(host.list.Get(),scene.resources,scene.spec(),scene.diff(),frame,error),error.c_str());
        if(i==0)warmed=wrapper.OwnedStagingBytes();
        if(i<4)need(wrapper.OwnedStagingBytes()==warmed,"first four unretired recordings use warmed staging");
    }
    need(wrapper.OwnedStagingBytes()==warmed*8,"32 pending recordings own 32 independent staging slots");
    const auto calls=FfxApiProxy::dispatches;
    need(wrapper.PrepareFrame(camera(1032),false,frame,error),"prepare staging-pool rejection");
    need(!wrapper.Dispatch(host.list.Get(),scene.resources,scene.spec(),scene.diff(),frame,error),"33rd unretired recording fails closed");
    need(FfxApiProxy::dispatches==calls && error.find("32 unretired")!=std::string::npos,"pool exhaustion fails before provider work");
    const auto peak=wrapper.OwnedStagingBytes();host.submit();host.reset();
    need(wrapper.PrepareFrame(camera(1032),false,frame,error) && frame.reset,"pool rejection resets next recorded history");
    need(wrapper.Dispatch(host.list.Get(),scene.resources,scene.spec(),scene.diff(),frame,error),error.c_str());
    need(wrapper.OwnedStagingBytes()==peak,"completed staging slots reused without further allocation");
    host.submit();host.reset();
}
void discardedRecordingChecks(Host& host,const std::filesystem::path& output)
{
    Scene scene(host,1505,847);host.submit();host.reset();RRWrapper wrapper;FrameParameters frame;std::string error;
    const auto creates=FfxApiProxy::creates,destroys=FfxApiProxy::destroys;
    need(wrapper.PrepareFrame(camera(500),false,frame,error),"prepare unsubmitted real provider work");
    need(wrapper.Dispatch(host.list.Get(),scene.resources,scene.spec(),scene.diff(),frame,error),error.c_str());
    // Reset the actual command list without submission, then explicitly discard the
    // provider's private CPU/model state as the integrated coordinator will do.
    hr(host.list->Close());host.reset();wrapper.DiscardRecordingHistory();
    need(FfxApiProxy::destroys==destroys+1 && wrapper.OwnedStagingBytes()==0,"discard retires unsubmitted real context and staged resources");
    need(wrapper.PrepareFrame(camera(501),false,frame,error) && frame.reset && !frame.previousValid,"discarded recording cannot supply history");
    need(wrapper.Dispatch(host.list.Get(),scene.resources,scene.spec(),scene.diff(),frame,error),error.c_str());
    need(FfxApiProxy::creates==creates+2 && wrapper.ContextGeneration()==2,"post-discard recording creates fresh physical context");
    Readback spec(host,scene.spec()),diff(host,scene.diff());host.submit();host.reset();
    spec.verify(output/"discard_recovery_spec.rgba16f",1505,847);diff.verify(output/"discard_recovery_diff.rgba16f",1505,847);
}
void realLoop(Host& host,uint32_t width,uint32_t height,unsigned frames,const std::filesystem::path& input,
              const std::filesystem::path& output,const char* label)
{
    Scene scene(host,width,height,input);host.submit();host.reset();RRWrapper wrapper;
    ComPtr<ID3D12QueryHeap> queries;D3D12_QUERY_HEAP_DESC desc{};desc.Type=D3D12_QUERY_HEAP_TYPE_TIMESTAMP;desc.Count=2;
    hr(host.device->CreateQueryHeap(&desc,IID_PPV_ARGS(&queries)));auto timing=buffer(host.device.Get(),16,D3D12_HEAP_TYPE_READBACK);
    UINT64 frequency;hr(host.queue->GetTimestampFrequency(&frequency));std::vector<double> milliseconds;
    uint64_t warmedStagingBytes=0;
    for(unsigned index=0;index<frames;++index)
    {
        auto snapshot=camera(index,width/float(height));snapshot.constants.jitterOffset=sl::float2(0,0);
        snapshot.constants.mvecScale=sl::float2(1,1);FrameParameters frame;std::string error;
        need(wrapper.PrepareFrame(snapshot,false,frame,error),"real loop camera preparation");
        host.list->EndQuery(queries.Get(),D3D12_QUERY_TYPE_TIMESTAMP,0);
        need(wrapper.Dispatch(host.list.Get(),scene.resources,scene.spec(),scene.diff(),frame,error),error.c_str());
        if(index==0)warmedStagingBytes=wrapper.OwnedStagingBytes();
        need(wrapper.OwnedStagingBytes()==warmedStagingBytes,"sequential recordings reuse warmed staging without allocation");
        host.list->EndQuery(queries.Get(),D3D12_QUERY_TYPE_TIMESTAMP,1);
        host.list->ResolveQueryData(queries.Get(),D3D12_QUERY_TYPE_TIMESTAMP,0,2,timing.Get(),0);
        host.submit();UINT64* ticks;hr(timing->Map(0,nullptr,reinterpret_cast<void**>(&ticks)));
        milliseconds.push_back(double(ticks[1]-ticks[0])*1000/double(frequency));timing->Unmap(0,nullptr);host.reset();
    }
    Readback spec(host,scene.spec()),diff(host,scene.diff());host.submit();host.reset();
    spec.verify(output/(std::string(label)+"_spec.rgba16f"),width,height);
    diff.verify(output/(std::string(label)+"_diff.rgba16f"),width,height);
    const unsigned warm=std::min(4u,frames-1);std::vector<double> steady(milliseconds.begin()+warm,milliseconds.end());
    std::sort(steady.begin(),steady.end());const double mean=std::accumulate(steady.begin(),steady.end(),0.0)/steady.size();
    std::cout<<"timing "<<label<<" size="<<width<<'x'<<height<<" frames="<<frames<<" warmup="<<warm
        <<" mean_ms="<<mean<<" median_ms="<<steady[steady.size()/2]<<" first_ms="<<milliseconds[0]
        <<" staging_bytes="<<warmedStagingBytes<<" staging_slots=4 scope=RR_stage_plus_exact_RGBA_commit samples_ms=";
    for(auto value:milliseconds)std::cout<<value<<',';std::cout<<'\n';
}
int main(int argc,char** argv) try
{
    std::cout.setf(std::ios::unitbuf);
    cameraChecks();
    const std::string mode=argc>1?argv[1]:"--camera";
    if(mode=="--camera") {std::cout<<"PASS checks="<<checks<<" camera\n";return 0;}
    if(mode=="--probe")
    {
        need(argc==4,"create probe requires width/height");loadReal();Host probeHost;
        const uint32_t width=std::stoul(argv[2]),height=std::stoul(argv[3]);
        std::shared_ptr<Context> owner;std::string error;
        need(CreateContext(probeHost.device.Get(),width,height,owner,error),error.c_str());
        owner.reset();need(FfxApiProxy::creates==1 && FfxApiProxy::destroys==1,"create-only context balance");
        need(FfxApiProxy::badCreateChains==0,"create descriptor chain survives through destroy");
        hr(probeHost.list->Close());probeHost.checkDebug();
        std::cout<<"PASS checks="<<checks<<" create-only size="<<width<<'x'<<height<<" creates=1 destroys=1 dispatches=0 debug_errors=0\n";return 0;
    }
    if(mode=="--real"){std::cout<<"stage load real AMD DLL\n";loadReal();}
    std::cout<<"stage create D3D12 host\n";Host host;
    std::cout<<"stage history checks\n";historyChecks(host);
    std::cout<<"stage deferred lifetime checks\n";lifecycleChecks(host);
    std::cout<<"stage minimum-size fail-closed check\n";minimumChecks(host);
    if(mode=="--mock")providerChecks(host);
    if(mode=="--mock"){partialFailureChecks(host);cancelledCommitChecks(host);}
    if(mode=="--mock")stagingPoolChecks(host);
    if(mode=="--real")
    {
        need(argc==4,"real test needs capture input/output directories");std::filesystem::path output=argv[3];std::filesystem::create_directories(output);
        discardedRecordingChecks(host,output);
        realLoop(host,1505,847,24,{},output,"synthetic_1505x847");
        realLoop(host,1505,847,24,argv[2],output,"da9f_1505x847");
        realLoop(host,2560,1440,16,{},output,"synthetic_2560x1440");
    }
    RecordedComputeLease::Poll();need(FfxApiProxy::live.empty(),"all completed contexts retired");
    need(FfxApiProxy::creates==FfxApiProxy::destroys,"exact context create/destroy balance");host.checkDebug();
    need(FfxApiProxy::badCreateChains==0,"all deferred create descriptor chains survive through destroy");
    std::cout<<"PASS checks="<<checks<<" mode="<<mode<<" creates="<<FfxApiProxy::creates<<" destroys="<<FfxApiProxy::destroys
        <<" dispatches="<<FfxApiProxy::dispatches<<" defaults="<<FfxApiProxy::defaults<<" configures="<<FfxApiProxy::configures
        <<" debug_errors=0\n";return 0;
}
catch(const std::exception& error){std::cerr<<"FAIL after checks="<<checks<<": "<<error.what()<<'\n';return 1;}
