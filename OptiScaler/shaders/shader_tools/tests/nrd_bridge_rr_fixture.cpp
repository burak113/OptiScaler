#ifndef NOMINMAX
#define NOMINMAX
#endif
#define FSRD_NRD_BRIDGE_RR_TEST_BACKEND
#include "../../fsrd_preprocess/FSRDNrdBridgeRR_Dx12.cpp"
#include <d3d12sdklayers.h>
#include <d3dcompiler.h>
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
SLConstantsSnapshot camera(uint32_t frame = 100, float aspect = 4.f/3.f, float nearPlane = .01f)
{
    SLConstantsSnapshot snapshot;
    snapshot.frameIndex = frame;
    auto& c = snapshot.constants;
    const float y = 1.f / std::tan(XM_PI/6.f);
    c.cameraViewToClip[0] = sl::float4(y/aspect,0,0,0);
    c.cameraViewToClip[1] = sl::float4(0,y,0,0);
    c.cameraViewToClip[2] = sl::float4(0,0,0,-1);
    c.cameraViewToClip[3] = sl::float4(0,0,nearPlane,0);
    c.cameraPos = sl::float3(0,0,0);
    c.cameraRight = sl::float3(1,0,0);
    c.cameraUp = sl::float3(0,1,0);
    c.cameraFwd = sl::float3(0,0,-1);
    c.cameraNear = nearPlane; c.cameraFar = 0; c.cameraFOV = XM_PI/3.f; c.cameraAspectRatio = aspect;
    c.mvecScale = sl::float2(.5f,.25f); c.jitterOffset = sl::float2(.25f,-.125f);
    c.depthInverted = sl::Boolean::eTrue; c.reset = sl::Boolean::eFalse;
    c.cameraMotionIncluded = sl::Boolean::eTrue; c.motionVectors3D = sl::Boolean::eFalse;
    return snapshot;
}
void commitRootLayoutChecks()
{
    ComPtr<ID3DBlob> serialized;hr(D3DGetBlobPart(FSRDNrdBridgePureCommit_cso,sizeof(FSRDNrdBridgePureCommit_cso),D3D_BLOB_ROOT_SIGNATURE,0,&serialized));
    ComPtr<ID3D12VersionedRootSignatureDeserializer> reader;
    hr(D3D12CreateVersionedRootSignatureDeserializer(serialized->GetBufferPointer(),serialized->GetBufferSize(),IID_PPV_ARGS(&reader)));
    const D3D12_VERSIONED_ROOT_SIGNATURE_DESC* versioned=nullptr;hr(reader->GetRootSignatureDescAtVersion(D3D_ROOT_SIGNATURE_VERSION_1_0,&versioned));
    const auto& root=versioned->Desc_1_0;need(root.NumParameters==4 && root.NumStaticSamplers==0,"actual compiled commit retains exactly four root parameters and no samplers");
    const auto& constants=root.pParameters[0];need(constants.ParameterType==D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS &&
        constants.Constants.ShaderRegister==0 && constants.Constants.RegisterSpace==0 && constants.Constants.Num32BitValues==5,
        "actual compiled commit has five unpacked32-bit constants at b0space0");
    unsigned cost=constants.Constants.Num32BitValues;
    for(unsigned i=1;i<3;++i)
    {
        const auto& table=root.pParameters[i];need(table.ParameterType==D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE &&
            table.DescriptorTable.NumDescriptorRanges==1,"actual commit has distinct single-range SRV and UAV tables");
        const auto& range=table.DescriptorTable.pDescriptorRanges[0];need(range.NumDescriptors==2 && range.BaseShaderRegister==0 && range.RegisterSpace==0 &&
            range.RangeType==(i==1?D3D12_DESCRIPTOR_RANGE_TYPE_SRV:D3D12_DESCRIPTOR_RANGE_TYPE_UAV),"actual commit tables preserve t0/t1 and u0/u1 ranges");++cost;
    }
    const auto& cbv=root.pParameters[3];need(cbv.ParameterType==D3D12_ROOT_PARAMETER_TYPE_CBV && cbv.Descriptor.ShaderRegister==6 &&
        cbv.Descriptor.RegisterSpace==0,"actual commit keeps live native flag snapshot at rootCBV b6space0");cost+=2;
    need(cost==9 && cost<=64,"actual compiled root costs5+1+1+2=9DWORDs within the native limit");
    std::cout<<"commit_root actual_parameters="<<root.NumParameters<<" constants="<<constants.Constants.Num32BitValues<<" cost_dwords="<<cost<<'\n';
}
void settingsValidationChecks()
{
    RRWrapper wrapper; RRSettings requested; std::string error;
    const auto creates=FfxApiProxy::creates,configures=FfxApiProxy::configures,dispatches=FfxApiProxy::dispatches;
    need(ValidateRRSettings(requested,error) && wrapper.Configure(requested,error),"default AMD settings validate lazily");
    need(!wrapper.GetSettingsState().ready && wrapper.ContextGeneration()==0 &&
        wrapper.OwnedStagingBytes()==0 && wrapper.OwnedAuxiliaryBytes()==0,"default settings allocate no GPU context or surfaces");
    need(!wrapper.GetNativeDebugOutputSnapshot().resource && !wrapper.GetNativeDebugOutputSnapshot().owner,
        "default native debug image is absent");
    requested.values.fill(std::numeric_limits<float>::quiet_NaN());
    need(ValidateRRSettings(requested,error) && wrapper.Configure(requested,error),"unselected override storage is ignored");
    need(wrapper.GetSettingsState().requested.values==std::array<float,8>{},"unselected overrides are canonicalized");
    for(const auto [value,expected]:std::array<std::array<float,2>,8>{{{-1.f,0.f},{2.f,0.f},{.375f,0.f},{-0.f,0.f},{1.f,0.f},
        {std::numeric_limits<float>::quiet_NaN(),0.f},{std::numeric_limits<float>::infinity(),0.f},{-std::numeric_limits<float>::infinity(),0.f}}})
    {
        RRSettings blend;blend.nativeSpecularBlend=value;need(ValidateRRSettings(blend,error) && wrapper.Configure(blend,error),"deprecated coefficient is ignored without invalidating AMD scalar settings");
        const auto normalized=wrapper.GetSettingsState().requested.nativeSpecularBlend;
        need(normalized==expected && std::isfinite(normalized),"every deprecated coefficient canonicalizes to finite positive zero");
        need(std::bit_cast<uint32_t>(normalized)==0u && std::bit_cast<uint32_t>(NormalizeNativeSpecularBlend(value))==0u,
            "API and shared boundary reject every native coefficient with positive-zero bits");
        need(wrapper.OwnedStagingBytes()==0 && wrapper.OwnedAuxiliaryBytes()==0 && wrapper.ContextGeneration()==0,"coefficient-only settings allocate no GPU resources or context");
    }
    const RRSettings valid{0x7fu,{.8f,.6f,3000.f,12.f,.9f,.025f,.01f,80.f},-1,0};
    need(ValidateRRSettings(valid,error) && wrapper.Configure(valid,error),"all seven supported keys validate before context creation");
    const auto retained=wrapper.GetSettingsState().requested;
    auto rejected=[&](RRSettings value,const char* reason){
        need(!ValidateRRSettings(value,error) && !error.empty(),reason);
        need(!wrapper.Configure(value,error),"invalid settings cannot be applied");
        const auto state=wrapper.GetSettingsState();
        need(state.requested.overrideMask==retained.overrideMask && state.requested.values==retained.values &&
            state.requested.nativeDebugView==retained.nativeDebugView &&
            state.requested.nativeDebugViewport==retained.nativeDebugViewport &&
            state.requested.preserveNativeMaterialIDs==retained.preserveNativeMaterialIDs &&
            state.requested.nativeSpecularBlend==retained.nativeSpecularBlend,"invalid settings preserve prior requested snapshot");
    };
    auto bad=valid;bad.overrideMask|=0x80u;rejected(bad,"unknown AMD key bit rejected");
    for(unsigned i=0;i<8;++i)
    {
        bad=valid;bad.values[i]=std::numeric_limits<float>::quiet_NaN();rejected(bad,"selected NaN override rejected");
        bad=valid;bad.values[i]=std::numeric_limits<float>::infinity();rejected(bad,"selected infinite override rejected");
    }
    for(unsigned i:{0u,1u,4u}){bad=valid;bad.values[i]=-0.01f;rejected(bad,"negative bounded override rejected");
        bad=valid;bad.values[i]=1.01f;rejected(bad,"bounded override above one rejected");}
    for(unsigned i:{2u,3u,5u}){bad=valid;bad.values[i]=0;rejected(bad,"zero positive override rejected");}
    bad=valid;bad.values[2]=65505.f;rejected(bad,"radiance outside finite FP16 bridge domain rejected");
    bad=valid;bad.values[5]=1.01f;rejected(bad,"disocclusion outside conservative bridge domain rejected");
    bad=valid;bad.values[6]=-1;rejected(bad,"negative debug depth minimum rejected");
    bad=valid;bad.values[7]=bad.values[6];rejected(bad,"empty debug depth interval rejected");
    for(int32_t view:{-2,2,INT32_MAX}){bad=valid;bad.nativeDebugView=view;rejected(bad,"unsupported native view rejected");}
    bad=valid;bad.nativeDebugViewport=12;rejected(bad,"native viewport upper bound rejected");
    for(int32_t view:{-1,0,1})for(uint32_t viewport:{0u,11u})
    { auto value=valid;value.nativeDebugView=view;value.nativeDebugViewport=viewport;
        need(ValidateRRSettings(value,error),"all supported native mode/viewport boundaries validate"); }
    need(FfxApiProxy::creates==creates && FfxApiProxy::configures==configures && FfxApiProxy::dispatches==dispatches,
        "settings-only validation calls no provider and allocates no GPU context");
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
        unsigned errors=0,warnings=0;
        for(UINT64 i=0;i<info->GetNumStoredMessages();++i)
        {
            SIZE_T bytes=0; info->GetMessage(i,nullptr,&bytes); std::vector<uint8_t> memory(bytes);
            auto* message=reinterpret_cast<D3D12_MESSAGE*>(memory.data()); hr(info->GetMessage(i,message,&bytes));
            if(message->Severity==D3D12_MESSAGE_SEVERITY_ERROR || message->Severity==D3D12_MESSAGE_SEVERITY_CORRUPTION)
            { ++errors; std::cerr<<message->pDescription<<'\n'; }
            if(message->Severity==D3D12_MESSAGE_SEVERITY_WARNING)
            { ++warnings; std::cerr<<message->pDescription<<'\n'; }
        }
        need(errors==0,"D3D12 debug layer errors");
        need(warnings==0,"D3D12 debug layer warnings");
        std::cout<<"debug_errors="<<errors<<" debug_warnings="<<warnings<<'\n';
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
        type==D3D12_HEAP_TYPE_UPLOAD?D3D12_RESOURCE_STATE_GENERIC_READ:
            (type==D3D12_HEAP_TYPE_DEFAULT?D3D12_RESOURCE_STATE_COMMON:D3D12_RESOURCE_STATE_COPY_DEST),nullptr,IID_PPV_ARGS(&resource)));
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
    auto s=FfxApiProxy::mockSpec,d=FfxApiProxy::mockDiff;
    for(unsigned c=0;c<3;++c)
    {
        s[c]=std::min(s[c]*FfxApiProxy::mockSpecularScale,65504.f);
        d[c]=std::min(d[c]*FfxApiProxy::mockDiffuseScale,65504.f);
    }
    ClearPair(list,spec,diff,s,d);
}
void ClearTexture(ID3D12GraphicsCommandList* list,ID3D12Resource* resource,const std::array<float,4>& value,
                  const D3D12_RECT* rect=nullptr)
{
    struct Owner { ComPtr<ID3D12Device> device;ComPtr<ID3D12DescriptorHeap> gpu,cpu; };
    auto owner=MakeOwnedShared<Owner>();hr(list->GetDevice(IID_PPV_ARGS(&owner->device)));
    D3D12_DESCRIPTOR_HEAP_DESC desc{};desc.Type=D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;desc.NumDescriptors=1;
    desc.Flags=D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;hr(owner->device->CreateDescriptorHeap(&desc,IID_PPV_ARGS(&owner->gpu)));
    desc.Flags=D3D12_DESCRIPTOR_HEAP_FLAG_NONE;hr(owner->device->CreateDescriptorHeap(&desc,IID_PPV_ARGS(&owner->cpu)));
    D3D12_UNORDERED_ACCESS_VIEW_DESC uav{};uav.Format=resource->GetDesc().Format;uav.ViewDimension=D3D12_UAV_DIMENSION_TEXTURE2D;
    owner->device->CreateUnorderedAccessView(resource,nullptr,&uav,owner->gpu->GetCPUDescriptorHandleForHeapStart());
    owner->device->CreateUnorderedAccessView(resource,nullptr,&uav,owner->cpu->GetCPUDescriptorHandleForHeapStart());
    need(ResTrack_Dx12::RetainComputeDispatch(owner->device.Get(),list,owner),"retain independent debug/test clear descriptors");
    ID3D12DescriptorHeap* heaps[]={owner->gpu.Get()};list->SetDescriptorHeaps(1,heaps);
    list->ClearUnorderedAccessViewFloat(owner->gpu->GetGPUDescriptorHandleForHeapStart(),
        owner->cpu->GetCPUDescriptorHandleForHeapStart(),resource,value.data(),rect?1u:0u,rect);
    D3D12_RESOURCE_BARRIER b{};b.Type=D3D12_RESOURCE_BARRIER_TYPE_UAV;b.UAV.pResource=resource;list->ResourceBarrier(1,&b);
}
void RecordTestProviderDebugWrites(ID3D12GraphicsCommandList* list,ID3D12Resource* output,uint32_t width,uint32_t height)
{
    ClearTexture(list,output,FfxApiProxy::mockDebug);
    const D3D12_RECT uncovered{LONG(width/2u),0,LONG(width),LONG(height)};
    ClearTexture(list,output,{0,0,0,0},&uncovered);
}
struct Scene
{
    ConvertedResources resources;
    std::array<ComPtr<ID3D12Resource>,9> textures;
    std::vector<ComPtr<ID3D12Resource>> uploads;
    uint32_t width,height;
    Scene(Host& host,uint32_t w,uint32_t h,const std::filesystem::path& files={},bool asymmetric=false) : width(w),height(h)
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
                    for(unsigned c=0;c<3;++c)value[c]=PackedVector::XMConvertFloatToHalf((i==0?.02f:.1f)*(asymmetric?std::array<float,3>{1.f,2.7f,.35f}[c]:1.f)+noise);
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
    std::vector<uint16_t> values(uint32_t width,uint32_t height)
    {
        uint8_t* data;hr(bufferResource->Map(0,nullptr,reinterpret_cast<void**>(&data)));
        std::vector<uint16_t> result(size_t(width)*height*4);
        for(uint32_t y=0;y<height;++y)std::memcpy(result.data()+size_t(y)*width*4,
            data+footprint.Offset+y*footprint.Footprint.RowPitch,size_t(width)*8);
        bufferResource->Unmap(0,nullptr);return result;
    }
    void save(const std::filesystem::path& file,uint32_t width,uint32_t height)
    {
        const auto words=values(width,height);std::ofstream output(file,std::ios::binary);
        need(bool(output),"native debug evidence output opens");
        output.write(reinterpret_cast<const char*>(words.data()),words.size()*sizeof(uint16_t));
        need(bool(output),"native debug evidence output is complete");
    }
    void consumerRoundtrip(Readback& staged,uint32_t width,uint32_t height,bool encoded,float nativeAlpha)
    {
        const auto output=values(width,height),source=staged.values(width,height);
        uint64_t finite=0,sourceFinite=0,alphas=0,within=0,exactRgb=0,chroma=0,nearest=0;
        for(size_t p=0;p<size_t(width)*height;++p)
        {
            std::array<float,3> color,original;
            for(unsigned c=0;c<3;++c){color[c]=PackedVector::XMConvertHalfToFloat(output[p*4+c]);
                original[c]=PackedVector::XMConvertHalfToFloat(source[p*4+c]);finite+=std::isfinite(color[c]);
                sourceFinite+=std::isfinite(original[c]);exactRgb+=output[p*4+c]==source[p*4+c];}
            const float bound=(std::abs(color[0])+std::abs(color[1])+std::abs(color[2]))*std::ldexp(1.f,-11)+3*std::ldexp(1.f,-25);
            const std::array<float,3> expectedHalf {(original[0]+2.f*original[1]+original[2])*.25f,
                (original[0]-original[2])*.5f,(-original[0]+2.f*original[1]-original[2])*.25f};
            for(unsigned c=0;c<3;++c)nearest+=output[p*4+c]==PackedVector::XMConvertFloatToHalf(expectedHalf[c]);
            const auto decoded=encoded?std::array<float,3>{std::max(color[0]-color[2]+color[1],0.f),
                std::max(color[0]+color[2],0.f),std::max(color[0]-color[2]-color[1],0.f)}:color;
            for(unsigned c=0;c<3;++c)within+=std::abs(decoded[c]-(encoded?std::max(original[c],0.f):original[c]))<=bound*1.01f;
            chroma+=encoded && color[1]!=0.f && color[2]!=0.f;
            alphas+=output[p*4+3]==PackedVector::XMConvertFloatToHalf(nativeAlpha);
        }
        need(finite==uint64_t(width)*height*3,"encoded title RGB finite");
        need(sourceFinite==uint64_t(width)*height*3,"actual RR staged RGB finite before encoding");
        need(alphas==uint64_t(width)*height,"encoding preserves every native title alpha byte");
        need(within==uint64_t(width)*height*3,"exact Consumer inverse roundtrip within FP16 rounding bound");
        if(!encoded)need(exactRgb==uint64_t(width)*height*3,"native flag zero bypasses fallback encoding with exact RR RGB");
        else { need(chroma>0,"asymmetric codec test must exercise both nonzero chroma channels");
            need(nearest==uint64_t(width)*height*3,"encoded title RGB matches exact nearest-half identity"); }
    }
    void nearestHalfEdges(Readback& staged,uint32_t width,uint32_t height,float nativeAlpha,unsigned edge)
    {
        const auto output=values(width,height),source=staged.values(width,height);
        uint64_t nearest=0,finite=0,alpha=0;
        std::array<uint16_t,3> firstExpected{};
        for(size_t p=0;p<size_t(width)*height;++p)
        {
            std::array<float,3> rgb;
            for(unsigned c=0;c<3;++c)rgb[c]=PackedVector::XMConvertHalfToFloat(source[p*4+c]);
            const std::array<float,3> expected {(rgb[0]+2.f*rgb[1]+rgb[2])*.25f,
                (rgb[0]-rgb[2])*.5f,(-rgb[0]+2.f*rgb[1]-rgb[2])*.25f};
            for(unsigned c=0;c<3;++c)
            {
                const auto word=PackedVector::XMConvertFloatToHalf(expected[c]);
                if(p==0)firstExpected[c]=word;
                nearest+=output[p*4+c]==word;
                finite+=std::isfinite(PackedVector::XMConvertHalfToFloat(output[p*4+c]));
            }
            alpha+=output[p*4+3]==PackedVector::XMConvertFloatToHalf(nativeAlpha);
        }
        need(nearest==uint64_t(width)*height*3,"GPU edge codec matches independent CPU nearest-even half bits");
        need(finite==uint64_t(width)*height*3,"GPU edge codec remains finite including half subnormals");
        need(alpha==uint64_t(width)*height,"GPU edge codec preserves native title alpha bits");
        std::cout<<"nearest_half_edge="<<edge<<" matched_components="<<nearest<<" words="
                 <<firstExpected[0]<<','<<firstExpected[1]<<','<<firstExpected[2]<<'\n';
    }
    void consumerGpuRoundtrip(Readback& title,Readback& staged,uint32_t width,uint32_t height,bool encoded)
    {
        const auto native=title.values(width,height),source=staged.values(width,height);
        uint8_t* data;hr(bufferResource->Map(0,nullptr,reinterpret_cast<void**>(&data)));
        uint64_t finite=0,within=0,alpha=0;
        for(uint32_t y=0;y<height;++y)
        {
            const auto* row=reinterpret_cast<const float*>(data+footprint.Offset+y*footprint.Footprint.RowPitch);
            for(uint32_t x=0;x<width;++x)
            {
                const auto p=size_t(y)*width+x;
                float bound=3*std::ldexp(1.f,-25);
                for(unsigned c=0;c<3;++c)bound+=std::abs(PackedVector::XMConvertHalfToFloat(native[p*4+c]))*std::ldexp(1.f,-11);
                for(unsigned c=0;c<3;++c)
                {
                    const auto expected=PackedVector::XMConvertHalfToFloat(source[p*4+c]);
                    finite+=std::isfinite(row[x*4+c]);
                    within+=encoded?std::abs(row[x*4+c]-std::max(expected,0.f)*64.f)<=bound*64.f*1.01f:
                        row[x*4+c]==expected*64.f;
                }
                alpha+=row[x*4+3]==1.f;
            }
        }
        bufferResource->Unmap(0,nullptr);
        need(finite==uint64_t(width)*height*3,"original Consumer GPU decoded RGB finite");
        need(within==uint64_t(width)*height*3,"actual Consumer GPU read matches RR RGB within derived half rounding");
        need(alpha==uint64_t(width)*height,"original Consumer stores alpha1 independently of title signal alpha");
    }
    void nativeDebugPresentation(Readback& source,uint32_t sourceWidth,uint32_t sourceHeight,
                                 uint32_t width,uint32_t height,const std::array<float,4>& sentinel,bool requireUncovered)
    {
        const auto src=source.values(sourceWidth,sourceHeight),dst=values(width,height);
        uint64_t finite=0,matched=0,alpha=0,covered=0,uncovered=0;
        for(auto word:src)finite+=std::isfinite(PackedVector::XMConvertHalfToFloat(word));
        need(finite==uint64_t(sourceWidth)*sourceHeight*4,"actual SDK debug target is finite in every component");
        for(uint32_t y=0;y<height;++y)for(uint32_t x=0;x<width;++x)
        {
            const auto from=(size_t((uint64_t(y)*sourceHeight)/height)*sourceWidth+(uint64_t(x)*sourceWidth)/width)*4;
            const auto to=(size_t(y)*width+x)*4;
            const bool written=PackedVector::XMConvertHalfToFloat(src[from+3])>0.f;
            covered+=written;uncovered+=!written;
            for(unsigned c=0;c<3;++c)matched+=dst[to+c]==(written?src[from+c]:PackedVector::XMConvertFloatToHalf(sentinel[c]));
            alpha+=dst[to+3]==PackedVector::XMConvertFloatToHalf(sentinel[3]);
        }
        need(covered>0,"native SDK debug display exercises written coverage");
        if(requireUncovered)need(uncovered>0,"independent mock SDK debug coverage preserves unwritten title pixels");
        need(matched==uint64_t(width)*height*3,"native debug presentation preserves exact SDK colors under nearest scaling and coverage");
        need(alpha==uint64_t(width)*height,"native debug presentation preserves every original title alpha word");
        std::cout<<"native_debug_color covered="<<covered<<" uncovered="<<uncovered<<" exact_rgb="<<matched<<" preserved_alpha="<<alpha<<'\n';
    }
};
void runtimeSettingsChecks(Host& host)
{
    Scene scene(host,FfxApiProxy::real?1505u:64u,FfxApiProxy::real?847u:64u);host.submit();host.reset();
    RRWrapper wrapper;FrameParameters frame;std::string error;uint32_t token=2000;
    auto step=[&](bool expectedReset){
        const auto scale=wrapper.GetSettingsState().requested.radianceScale;
        FfxApiProxy::mockDiffuseScale=scale.enabled?float(scale.diffuse):256.f;
        FfxApiProxy::mockSpecularScale=scale.enabled?float(scale.specular):256.f;
        need(wrapper.PrepareFrame(camera(token++),false,frame,error),"prepare configured frame");
        need(frame.reset==expectedReset,"RR settings reset only the intended history frame");
        need(wrapper.Dispatch(host.list.Get(),scene.resources,scene.spec(),scene.diff(),frame,error),error.c_str());
        need(bool(FfxApiProxy::lastDispatch.flags&FFX_DENOISER_DISPATCH_RESET)==expectedReset,"SDK receives configured history reset");
        host.submit();host.reset();
    };
    need(wrapper.Configure({},error),"lazy provider-default settings configure");step(true);
    const auto defaults=wrapper.GetSettingsState().defaults;
    std::cout<<"runtime_settings_defaults values=";for(auto value:defaults)std::cout<<value<<',';std::cout<<'\n';
    need(wrapper.GetSettingsState().ready && wrapper.GetSettingsState().effective==defaults,"queried provider defaults are effective baseline");
    RRSettings explicitDefaults;explicitDefaults.overrideMask=0x3fu;explicitDefaults.values=defaults;
    auto calls=FfxApiProxy::configures;
    need(wrapper.Configure(explicitDefaults,error) && FfxApiProxy::configures==calls,"explicit default values cause no SDK reconfiguration");step(false);
    RRSettings custom{0x3fu,{.8f,.6f,3000.f,12.f,.9f,.025f,0,0},-1,0};
    custom.values[0]=defaults[0]==.25f?.75f:.25f;
    uint32_t changes=0;for(unsigned i=0;i<6;++i)changes+=custom.values[i]!=defaults[i];
    need(changes>0,"runtime settings exercise actual effective changes");
    calls=FfxApiProxy::configures;
    need(wrapper.Configure(custom,error) && FfxApiProxy::configures==calls+changes,"only changed effective AMD scalar keys configure");
    auto state=wrapper.GetSettingsState();
    need(state.defaults==defaults && state.requested.overrideMask==custom.overrideMask,"runtime settings retain queried defaults and requested mask");
    for(unsigned i=0;i<6;++i)need(state.effective[i]==custom.values[i],"cached effective scalar equals applied override");
    calls=FfxApiProxy::configures;
    need(wrapper.Configure(custom,error) && FfxApiProxy::configures==calls,"same requested settings issue no provider calls");step(true);step(false);
    const auto blendGeneration=wrapper.ContextGeneration(),blendBytes=wrapper.OwnedStagingBytes(),blendAux=wrapper.OwnedAuxiliaryBytes();
    for(float value:{.25f,.5f,1.f,0.f,std::numeric_limits<float>::quiet_NaN(),std::numeric_limits<float>::infinity()})
    {
        custom.nativeSpecularBlend=value;need(wrapper.Configure(custom,error),"ignore deprecated commit-only coefficient");
        need(FfxApiProxy::configures==calls && wrapper.ContextGeneration()==blendGeneration && wrapper.OwnedStagingBytes()==blendBytes && wrapper.OwnedAuxiliaryBytes()==blendAux,
            "ignored native coefficient changes no AMD key/context/staging/allocation");
        need(std::bit_cast<uint32_t>(wrapper.GetSettingsState().requested.nativeSpecularBlend)==0u,
            "live requested native coefficient is always positive zero");step(false);
    }
    custom.radianceScale={true,16,256};
    need(wrapper.Configure(custom,error) && FfxApiProxy::configures==calls,
        "shared scale is stored without inventing an AMD configure key");step(true);step(false);
    need(wrapper.GetSettingsState().requested.radianceScale==custom.radianceScale,
        "shared scale runtime snapshot keeps both lobe factors");
    need(wrapper.PrepareFrame(camera(token++),false,frame,error),"prepare per-lobe capture frame");
    { // Release this deliberately retained snapshot before later context-retirement checks.
        RRRecordedOutputLease scaledOutput;
        need(wrapper.RecordOwned(host.list.Get(),scene.resources,frame,scaledOutput,error),error.c_str());
        need(wrapper.CommitOwned(host.list.Get(),scaledOutput,scene.spec(),scene.diff(),frame,error),error.c_str());
        host.submit();host.reset();
        custom.radianceScale.diffuse=64;
        need(wrapper.Configure(custom,error),"change diffuse scale after retaining an older output");
        const auto frozenScale=wrapper.GetOwnedOutputSnapshot(scaledOutput);
        need(frozenScale.providerDiffuseRadianceScale==16.f && frozenScale.providerSpecularRadianceScale==256.f &&
             frozenScale.providerRadianceScale==0.f,"captured scales belong to the recorded frame, not later settings");step(true);
    }
    custom.radianceScale={};
    need(wrapper.Configure(custom,error) && FfxApiProxy::configures==calls,
        "shared scale OFF restores the legacy normalization without changing SDK keys");step(true);
    const auto generation=wrapper.ContextGeneration();custom.preserveNativeMaterialIDs=true;
    need(wrapper.Configure(custom,error) && FfxApiProxy::configures==calls && wrapper.ContextGeneration()==generation,
        "material ID experiment is stored without inventing an AMD configure key or recreating context");
    need(wrapper.GetSettingsState().requested.preserveNativeMaterialIDs,"material ID snapshot is coherent");step(true);
    need(wrapper.Configure(custom,error) && FfxApiProxy::configures==calls,"unchanged material ID setting is inert");step(false);
    custom.preserveNativeMaterialIDs=false;
    need(wrapper.Configure(custom,error) && FfxApiProxy::configures==calls,"returning material ID experiment to baseline uses no provider key");step(true);
    custom.overrideMask|=0x40u;custom.values[6]=.02f;custom.values[7]=defaults[7]==80.f?40.f:80.f;
    calls=FfxApiProxy::configures;
    need(wrapper.Configure(custom,error) && FfxApiProxy::configures==calls+1,"debug depth bound pair is one AMD key/value");
    state=wrapper.GetSettingsState();need(state.effective[6]==custom.values[6] && state.effective[7]==custom.values[7],"both cached debug bounds match the pair");step(false);
    calls=FfxApiProxy::configures;
    need(wrapper.Configure({},error) && FfxApiProxy::configures==calls+changes+1,"provider defaults restore all changed selected keys");
    need(wrapper.GetSettingsState().effective==defaults,"restoring AMD defaults preserves exact queried values");step(true);step(false);
    calls=FfxApiProxy::configures;auto invalid=custom;invalid.values[0]=std::numeric_limits<float>::quiet_NaN();
    need(!wrapper.Configure(invalid,error) && FfxApiProxy::configures==calls,"invalid live overrides fail before provider configuration");
    need(wrapper.GetSettingsState().requested.overrideMask==0 && wrapper.GetSettingsState().effective==defaults,"rejected live override preserves baseline snapshot");step(false);
    if(!FfxApiProxy::real)
    {
        need(wrapper.PrepareFrame(camera(token++),false,frame,error),"prepare recorded work before configure failure");
        need(wrapper.Dispatch(host.list.Get(),scene.resources,scene.spec(),scene.diff(),frame,error),"record before configure failure");
        const auto destroys=FfxApiProxy::destroys,creates=FfxApiProxy::creates;
        RRSettings failure;failure.overrideMask=1;failure.values[0]=defaults[0]==.25f?.75f:.25f;
        FfxApiProxy::rejectConfigureKey=1;
        need(!wrapper.Configure(failure,error) && !error.empty(),"SDK runtime configuration error is propagated");
        need(!wrapper.GetSettingsState().ready && wrapper.OwnedStagingBytes()==0,"SDK configure failure retires active generation");
        need(FfxApiProxy::destroys==destroys,"failed configuration cannot destroy a recorded GPU generation");
        host.submit();host.reset();need(FfxApiProxy::destroys==destroys+1,"configuration failure destroys old context only after GPU completion");
        FfxApiProxy::rejectConfigureKey=0;step(true);
        need(FfxApiProxy::creates==creates+1 && wrapper.GetSettingsState().effective[0]==failure.values[0],
            "fresh recovery context inherits the retained valid desired override");
    }
    auto turnSettings=wrapper.GetSettingsState().requested;
    turnSettings.turnColourFilter=true;turnSettings.turnColourFrames=0.f;
    turnSettings.radianceScale={true,16,256};
    need(wrapper.Configure(turnSettings,error),"enable preserved colour filter with shared per-lobe scaling");step(true);
    need(FfxApiProxy::lastDiffuse.signal.input.resource!=scene.resources.diff &&
         FfxApiProxy::lastSpecular.signal.input.resource!=scene.resources.spec,
         "colour filter keeps provider inputs in separate RR-only copies with shared scaling");
    turnSettings.radianceScale={};
    need(wrapper.Configure(turnSettings,error),"return to legacy scaling with the colour filter still active");step(true);
    need(FfxApiProxy::lastDiffuse.signal.input.resource!=scene.resources.diff,
         "legacy colour-filter input copy survives shared scaling rollback");
    turnSettings.turnColourFilter=false;turnSettings.turnColourFrames=30.f;
    need(wrapper.Configure(turnSettings,error),"restore preserved colour filter OFF");step(false);
    need(FfxApiProxy::lastDiffuse.signal.input.resource==scene.resources.diff,
         "colour filter OFF restores direct provider input binding");
    // G2 uses the actual production Configure/Prepare/Dispatch path, including repeated native Configure calls.
    auto temporal=wrapper.GetSettingsState().requested;temporal.motionStability.enabled=true;
    need(wrapper.Configure(temporal,error),"enable motion stability without resetting provider history");
    const auto adaptiveGeneration=wrapper.ContextGeneration(),adaptiveBytes=wrapper.OwnedStagingBytes(),adaptiveAux=wrapper.OwnedAuxiliaryBytes();
    float expected=.5f;
    for(unsigned k=0;k<14;++k)
    {
        calls=FfxApiProxy::configures;
        need(wrapper.Configure(temporal,error)&&FfxApiProxy::configures==calls,
            "native per-recording Configure preserves runtime key 2 and issues no call");
        step(false);
        if(k)expected=std::min(.85f,expected+.035f);
        need(near(wrapper.GetSettingsState().effective[1],expected),"still schedule ramps without history reset");
        need(wrapper.ContextGeneration()==adaptiveGeneration&&wrapper.OwnedStagingBytes()==adaptiveBytes&&wrapper.OwnedAuxiliaryBytes()==adaptiveAux,
            "adaptive stability adds no context, GPU storage or owned allocation");
    }
    auto moved=camera(token++);moved.constants.cameraPos.x=.02f;
    need(wrapper.Configure(temporal,error)&&wrapper.PrepareFrame(moved,false,frame,error)&&!frame.reset,
        "walking-only frame keeps valid history");
    need(wrapper.Dispatch(host.list.Get(),scene.resources,scene.spec(),scene.diff(),frame,error),error.c_str());
    need(wrapper.GetSettingsState().effective[1]==.5f&&!(FfxApiProxy::lastDispatch.flags&FFX_DENOISER_DISPATCH_RESET),
        "translation instantly lowers key 2 without global history reset");host.submit();host.reset();
    temporal.motionStability.enabled=false;need(wrapper.Configure(temporal,error),"disable adaptive stability");step(true);step(false);
    need(wrapper.GetSettingsState().effective[1]==((temporal.overrideMask&2)?temporal.values[1]:defaults[1]),
        "OFF restores the exact fixed/provider stability");
    std::cout<<"motion_stability frames=15 repeated_configure_calls=0 history_resets=0 translation_drop=1 extra_gpu_bytes=0\n";
    need(FfxApiProxy::badDefaults==0,"all context initializations still apply seven exact queried AMD defaults");
    need(FfxApiProxy::badConfigureLayouts==0,"all runtime configuration descriptors preserve exact key/count/data ABI");
    std::cout<<"runtime_settings effective_changes="<<changes<<" unchanged_calls=0 debug_bounds_count=1 material_key_calls=0\n";
}
void nativeDebugChecks(Host& host,const std::filesystem::path& evidence={})
{
    const uint32_t width=FfxApiProxy::real?1505u:64u,height=FfxApiProxy::real?847u:64u,outWidth=137,outHeight=73;
    if(!evidence.empty())std::filesystem::create_directories(evidence);
    Scene scene(host,width,height,{},true);host.submit();host.reset();RRWrapper wrapper;FrameParameters frame;std::string error;
    uint32_t token=2200;RRSettings settings;
    auto dispatch=[&]{need(wrapper.PrepareFrame(camera(token++,float(width)/height),false,frame,error),"prepare native SDK debug frame");
        need(wrapper.Dispatch(host.list.Get(),scene.resources,scene.spec(),scene.diff(),frame,error),error.c_str());};
    const auto debugBefore=FfxApiProxy::nativeDebugDispatches;
    dispatch();need(FfxApiProxy::lastCreate.flags==0 && FfxApiProxy::nativeDebugDispatches==debugBefore,
        "native debug OFF creates no debugging context and chains no extra SDK dispatch");
    need(!wrapper.GetNativeDebugOutputSnapshot().resource && !wrapper.GetNativeDebugOutputSnapshot().owner,"native debug OFF publishes no image");
    const auto baselineAux=wrapper.OwnedAuxiliaryBytes(),baselineStage=wrapper.OwnedStagingBytes();host.submit();host.reset();
    D3D12_HEAP_PROPERTIES heap{};heap.Type=D3D12_HEAP_TYPE_DEFAULT;
    D3D12_RESOURCE_DESC desc{};desc.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D;desc.Width=outWidth;desc.Height=outHeight;
    desc.DepthOrArraySize=desc.MipLevels=1;desc.SampleDesc.Count=1;desc.Format=DXGI_FORMAT_R16G16B16A16_FLOAT;desc.Flags=D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
    ComPtr<ID3D12Resource> target;hr(host.device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&desc,
        D3D12_RESOURCE_STATE_UNORDERED_ACCESS,nullptr,IID_PPV_ARGS(&target)));
    const std::array<float,4> sentinel{.125f,.25f,.5f,7.f};
    const auto initialGeneration=wrapper.ContextGeneration();const auto initialDestroys=FfxApiProxy::destroys;
    settings.nativeDebugView=0;need(wrapper.Configure(settings,error),"enable AMD native overview");
    need(!wrapper.GetSettingsState().ready && FfxApiProxy::destroys==initialDestroys+1,
        "enabling SDK debugging physically retires completed ordinary context");
    RRWrapperNativeDebugOutputSnapshot image;uint64_t warmAux=0;
    for(uint32_t view=0;view<13;++view)
    {
        settings.nativeDebugView=view?1:0;settings.nativeDebugViewport=view?view-1u:0u;
        const auto generation=wrapper.ContextGeneration();const auto calls=FfxApiProxy::configures;
        need(wrapper.Configure(settings,error),"select documented native SDK viewport");
        if(view)need(wrapper.ContextGeneration()==generation && FfxApiProxy::configures==calls,
            "native active viewport selection neither recreates context nor configures lighting keys");
        dispatch();need(frame.reset==(view==0),"only enabling native SDK context resets lighting history");
        image=wrapper.GetNativeDebugOutputSnapshot();
        need(image.resource && image.owner && image.recording==host.list.Get() && image.frameSL==frame.streamlineFrame &&
            image.width==width && image.height==height && image.state==D3D12_RESOURCE_STATE_UNORDERED_ACCESS,
            "successful SDK debug dispatch publishes owned source provenance");
        need(image.resource!=scene.spec() && image.resource!=scene.diff(),"SDK native visualization never aliases lighting outputs");
        need(FfxApiProxy::lastCreate.flags==FFX_DENOISER_ENABLE_DEBUGGING &&
            FfxApiProxy::lastCreate.signalFlags==(FFX_DENOISER_SIGNAL_DIRECT_DIFFUSE|FFX_DENOISER_SIGNAL_INDIRECT_SPECULAR),
            "native debugging creation flag preserves original two lighting signals");
        need(FfxApiProxy::lastDebug.header.type==FFX_API_DISPATCH_DESC_TYPE_DENOISER_DEBUG_VIEW &&
            FfxApiProxy::lastDebug.header.pNext==nullptr && FfxApiProxy::lastDebug.output.resource==image.resource &&
            FfxApiProxy::lastDebug.output.state==FFX_API_RESOURCE_STATE_UNORDERED_ACCESS &&
            FfxApiProxy::lastDebug.outputSize.width==width && FfxApiProxy::lastDebug.outputSize.height==height &&
            FfxApiProxy::lastDebug.mode==uint32_t(settings.nativeDebugView) &&
            FfxApiProxy::lastDebug.viewportIndex==settings.nativeDebugViewport,"actual provider receives exact supported debug descriptor");
        ClearTexture(host.list.Get(),target.Get(),sentinel);
        if(view==0)
        {
            need(wrapper.ContextGeneration()==initialGeneration+1,"debug flag creates a fresh generation");
            const auto resourceDesc=image.resource->GetDesc();const auto bytes=host.device->GetResourceAllocationInfo(0,1,&resourceDesc).SizeInBytes;
            warmAux=wrapper.OwnedAuxiliaryBytes();need(warmAux==baselineAux+4u*bytes && wrapper.OwnedStagingBytes()==baselineStage,
                "only debug ON allocates four separate native image slots; lighting staging size is unchanged");
            need(!wrapper.PresentNativeDebug(host.list.Get(),target.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,image.frameSL-1,error),
                "native debug rejects mismatched requested source SL frame");
            auto bad=image;bad.width++;
            need(!wrapper.PresentNativeDebug(host.list.Get(),target.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,bad,error),"native snapshot dimensions are validated");
            bad=image;bad.owner.reset();
            need(!wrapper.PresentNativeDebug(host.list.Get(),target.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,bad,error),"native image without lifetime owner fails closed");
            bad=image;bad.state=D3D12_RESOURCE_STATE_COMMON;
            need(!wrapper.PresentNativeDebug(host.list.Get(),target.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,bad,error),"native source state is validated before recording");
            need(!wrapper.PresentNativeDebug(host.list.Get(),image.resource,D3D12_RESOURCE_STATE_UNORDERED_ACCESS,image.frameSL,error),
                "native presentation rejects source-output alias");
        }
        std::unique_ptr<Readback> cancelledPresentation;
        if(view==0 && !FfxApiProxy::real)
        {
            struct Probe
            {
                uint32_t calls=0,actions=0;
                static bool Deny(void* state,OutputCommitGuard::Action,void*) noexcept
                { ++static_cast<Probe*>(state)->calls;return false; }
            } probe;
            const OutputCommitGuard guard{&probe,Probe::Deny};
            const auto sdkCalls=FfxApiProxy::dispatches;
            need(!wrapper.PresentNativeDebug(host.list.Get(),target.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,image.frameSL,error,false,guard),
                "latest-source final presentation admission cancels after allocation and lease preparation");
            need(!wrapper.PresentNativeDebug(host.list.Get(),target.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,image,error,false,guard),
                "explicit submitted-source final presentation admission cancels after preparation");
            need(probe.calls==2 && probe.actions==0 && FfxApiProxy::dispatches==sdkCalls &&
                error.find("final admission")!=std::string::npos,"presentation guard runs exactly once per attempt without SDK work");
            need(wrapper.GetNativeDebugOutputSnapshot().resource==image.resource && wrapper.GetNativeDebugOutputSnapshot().owner,
                "cancelled diagnostic display retains valid original producer source");
            cancelledPresentation=std::make_unique<Readback>(host,target.Get());
        }
        barrier(host.list.Get(),target.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
        need(wrapper.PresentNativeDebug(host.list.Get(),target.Get(),D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,image.frameSL,error),error.c_str());
        // This next explicit barrier proves the caller's read state was restored;
        // strict debug warnings/errors fail if presentation left the target UAV.
        barrier(host.list.Get(),target.Get(),D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
        Readback source(host,image.resource),display(host,target.Get());host.submit();host.reset();
        if(cancelledPresentation)cancelledPresentation->exact(sentinel,outWidth,outHeight);
        display.nativeDebugPresentation(source,width,height,outWidth,outHeight,sentinel,!FfxApiProxy::real);
        if(!evidence.empty())
        {
            const auto name=view?"viewport_"+std::to_string(view-1u):"overview";
            source.save(evidence/(name+".rgba16f"),width,height);display.save(evidence/(name+"_present.rgba16f"),outWidth,outHeight);
        }
        need(wrapper.OwnedAuxiliaryBytes()==warmAux,"native viewport changes allocate no additional warmed image slots");
    }
    {
        const auto submitted=image;
        // The source fence was completed by the last host.submit()/reset(); a
        // distinct display list now exercises an explicit immutable old source.
        const auto originalAllocator=host.allocator;const auto originalList=host.list;hr(originalList->Close());
        hr(host.device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT,IID_PPV_ARGS(&host.allocator)));
        hr(host.device->CreateCommandList(0,D3D12_COMMAND_LIST_TYPE_DIRECT,host.allocator.Get(),nullptr,IID_PPV_ARGS(&host.list)));
        ClearTexture(host.list.Get(),target.Get(),sentinel);
        need(!wrapper.PresentNativeDebug(host.list.Get(),target.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,submitted,error),
            "different recording requires an explicit proven GPU dependency");
        for(auto* input:{scene.resources.spec,scene.resources.diff})
        {
            barrier(host.list.Get(),input,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
            ClearTexture(host.list.Get(),input,input==scene.resources.spec?std::array<float,4>{.7f,.2f,.4f,5.f}:std::array<float,4>{1.8f,.1f,.6f,5.f});
            barrier(host.list.Get(),input,D3D12_RESOURCE_STATE_UNORDERED_ACCESS,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
        }
        const auto savedMock=FfxApiProxy::mockDebug;FfxApiProxy::mockDebug={.875f,.25f,.0625f,1.f};
        dispatch();const auto latest=wrapper.GetNativeDebugOutputSnapshot();
        need(latest.frameSL!=submitted.frameSL && latest.resource!=submitted.resource,"new unsubmitted source has distinct frame and owned image");
        need(wrapper.PresentNativeDebug(host.list.Get(),target.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,submitted,error,true),error.c_str());
        Readback source(host,submitted.resource),newSource(host,latest.resource),display(host,target.Get());host.submit();host.reset();
        FfxApiProxy::mockDebug=savedMock;
        display.nativeDebugPresentation(source,width,height,outWidth,outHeight,sentinel,!FfxApiProxy::real);
        const auto oldWords=source.values(width,height),newWords=newSource.values(width,height);
        uint64_t changed=0;for(size_t i=0;i<oldWords.size();++i)if(i%4<3)changed+=oldWords[i]!=newWords[i];
        if(!FfxApiProxy::real)need(changed>0,"independent native mock colors prove explicit presentation selects submitted old image");
        std::cout<<"native_debug_cached_source source_SL="<<submitted.frameSL<<" current_SL="<<frame.streamlineFrame
            <<" source_fence_complete=1 distinct_recording=1 explicit_source_owner=1 changed_rgb="<<changed<<'\n';
        hr(host.list->Close());host.allocator=originalAllocator;host.list=originalList;host.reset();
    }
    dispatch();image=wrapper.GetNativeDebugOutputSnapshot();const auto destroys=FfxApiProxy::destroys;
    need(wrapper.Configure({},error),"disable native SDK debug with pending recording");image={};
    need(!wrapper.GetNativeDebugOutputSnapshot().resource && !wrapper.GetSettingsState().ready,
        "disabling native debug clears observation and retires active generation");
    need(FfxApiProxy::destroys==destroys,"native debug context cannot be destroyed while its recording is outstanding");
    host.submit();host.reset();need(FfxApiProxy::destroys==destroys+1,"native debug context retires only after its last owned GPU lease completes");
    const auto nativeCalls=FfxApiProxy::nativeDebugDispatches;dispatch();
    need(frame.reset && FfxApiProxy::lastCreate.flags==0 && FfxApiProxy::nativeDebugDispatches==nativeCalls &&
        wrapper.OwnedAuxiliaryBytes()==baselineAux,"returning native debug OFF restores zero-extra-surface baseline and reset");
    host.submit();host.reset();
    if(!FfxApiProxy::real)
    {
        settings.nativeDebugView=0;settings.nativeDebugViewport=0;need(wrapper.Configure(settings,error),"prepare debug failure cases");
        for(bool cancelled:{false,true})
        {
            ClearPair(host.list.Get(),scene.spec(),scene.diff(),{.125f,.25f,.5f,.75f},{1.25f,1.5f,1.75f,2.f});
            ClearTexture(host.list.Get(),target.Get(),sentinel);host.submit();host.reset();
            need(wrapper.PrepareFrame(camera(token++,float(width)/height),false,frame,error),"prepare partial/cancelled native debug SDK recording");
            FfxApiProxy::recordPartialWrites=true;FfxApiProxy::rejectDispatch=!cancelled;
            OutputCommitGuard guard;guard.admit=+[](void*,OutputCommitGuard::Action,void*) noexcept {return false;};
            need(!wrapper.Dispatch(host.list.Get(),scene.resources,scene.spec(),scene.diff(),frame,error,cancelled?guard:OutputCommitGuard{}),
                "SDK error or cancelled final admission rejects native debug and lighting together");
            need(!wrapper.GetNativeDebugOutputSnapshot().resource && !wrapper.GetNativeDebugOutputSnapshot().owner,
                "partial SDK debug writes are never published on failed admission");
            need(!wrapper.PresentNativeDebug(host.list.Get(),target.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,frame.streamlineFrame,error),
                "failed native debug cannot write the final title target");
            Readback spec(host,scene.spec()),diff(host,scene.diff()),display(host,target.Get());host.submit();host.reset();
            spec.exact({.125f,.25f,.5f,.75f},width,height);diff.exact({1.25f,1.5f,1.75f,2.f},width,height);display.exact(sentinel,outWidth,outHeight);
            FfxApiProxy::rejectDispatch=false;FfxApiProxy::recordPartialWrites=false;
        }
    }
    std::cout<<"native_debug views=13 warmed_auxiliary_bytes="<<warmAux<<" baseline_auxiliary_bytes="<<baselineAux
        <<" lighting_staging_bytes="<<baselineStage<<" default_extra_dispatch=0 default_extra_image_bytes=0\n";
}
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
struct ConsumerBuffer
{
    ComPtr<ID3D12Resource> upload, binding;
    UINT64 offset=0;
    ConsumerBuffer(Host& host,bool defaultHeap=false,UINT64 byteOffset=0,UINT64 byteSize=1536) : offset(byteOffset)
    {
        upload=buffer(host.device.Get(),byteSize,D3D12_HEAP_TYPE_UPLOAD);
        void* mapped=nullptr;hr(upload->Map(0,nullptr,&mapped));std::memset(mapped,0,size_t(byteSize));upload->Unmap(0,nullptr);
        if(defaultHeap)
        {
            binding=buffer(host.device.Get(),byteSize,D3D12_HEAP_TYPE_DEFAULT);
            barrier(host.list.Get(),binding.Get(),D3D12_RESOURCE_STATE_COMMON,D3D12_RESOURCE_STATE_COPY_DEST);
            host.list->CopyBufferRegion(binding.Get(),0,upload.Get(),0,byteSize);
            barrier(host.list.Get(),binding.Get(),D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_VERTEX_AND_CONSTANT_BUFFER);
            D3D12_HEAP_PROPERTIES heap{};hr(binding->GetHeapProperties(&heap,nullptr));
            need(heap.Type==D3D12_HEAP_TYPE_DEFAULT,"native default-heap CBV test is not an upload buffer");
        }
        else binding=upload;
    }
    TitleSignalConstants constants(){return {binding.Get(),binding->GetGPUVirtualAddress()+offset};}
    void flag(uint32_t bits)
    {
        uint32_t* mapped=nullptr;hr(upload->Map(0,nullptr,reinterpret_cast<void**>(&mapped)));
        mapped[offset/4+303]=bits;upload->Unmap(0,nullptr);
    }
    ULONG references(){const auto value=binding->AddRef();binding->Release();return value-1;}
};
#include "nrd_bridge_consumer_test.h"
void seedNativeSpecular(Host& host,Scene& scene,const std::array<uint16_t,4>& words)
{
    const auto desc=scene.spec()->GetDesc();D3D12_PLACED_SUBRESOURCE_FOOTPRINT fp{};UINT64 bytes=0;
    host.device->GetCopyableFootprints(&desc,0,1,0,&fp,nullptr,nullptr,&bytes);auto upload=buffer(host.device.Get(),bytes,D3D12_HEAP_TYPE_UPLOAD);
    uint8_t* mapped=nullptr;hr(upload->Map(0,nullptr,reinterpret_cast<void**>(&mapped)));std::memset(mapped,0,size_t(bytes));
    for(uint32_t y=0;y<scene.height;++y)for(uint32_t x=0;x<scene.width;++x)
        std::memcpy(mapped+fp.Offset+size_t(y)*fp.Footprint.RowPitch+size_t(x)*8,words.data(),8);
    upload->Unmap(0,nullptr);barrier(host.list.Get(),scene.spec(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,D3D12_RESOURCE_STATE_COPY_DEST);
    D3D12_TEXTURE_COPY_LOCATION from{},to{};from.pResource=upload.Get();from.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;from.PlacedFootprint=fp;
    to.pResource=scene.spec();to.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;host.list->CopyTextureRegion(&to,0,0,0,&from,nullptr);
    barrier(host.list.Get(),scene.spec(),D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);scene.uploads.push_back(std::move(upload));
}
// The deprecated coefficient is adversarial input. Only owned RR RGB and opaque title alpha are valid inputs.
void nativeBlendReference(Readback& output,Readback& staged,Readback& native,uint32_t width,uint32_t height,float requested,bool encoded)
{
    const auto actual=output.values(width,height),rr=staged.values(width,height),before=native.values(width,height);
    need(std::bit_cast<uint32_t>(NormalizeNativeSpecularBlend(requested))==0u,"direct frame coefficient always normalizes to positive zero");
    uint64_t finite=0,stageFinite=0,alpha=0,within=0,exact=0;
    for(size_t p=0;p<size_t(width)*height;++p)
    {
        std::array<float,3> source;
        for(unsigned c=0;c<3;++c){source[c]=PackedVector::XMConvertHalfToFloat(rr[p*4+c]);
            stageFinite+=std::isfinite(source[c]);finite+=std::isfinite(PackedVector::XMConvertHalfToFloat(actual[p*4+c]));}
        alpha+=actual[p*4+3]==before[p*4+3];
        if(encoded)source={(source[0]+2.f*source[1]+source[2])*.25f,(source[0]-source[2])*.5f,(-source[0]+2.f*source[1]-source[2])*.25f};
        for(unsigned c=0;c<3;++c)
        {
            const auto word=PackedVector::XMConvertFloatToHalf(source[c]);exact+=actual[p*4+c]==word;
            const auto value=PackedVector::XMConvertHalfToFloat(actual[p*4+c]);
            const float bound=std::abs(source[c])*std::ldexp(1.f,-10)+std::ldexp(1.f,-24);
            within+=std::abs(value-source[c])<=bound;
        }
    }
    const auto components=uint64_t(width)*height*3;
    need(stageFinite==components && finite==components,"RR-only commit runs both RR lobes and produces finite RGB in every pixel");
    need(alpha==uint64_t(width)*height,"RR-only commit preserves every opaque native alpha word including NaN payloads");
    need(within==components,"RR-only commit agrees with the independent codec reference within the unchanged half-storage bound");
    need(exact==components,"every deprecated coefficient produces exact staged-RR RGB or nearest-half YCoCg bits");
}
void nativeConsumerTitleIdentity(Readback& decoded,Readback& title,uint32_t width,uint32_t height,bool encoded)
{
    const auto words=title.values(width,height);uint8_t* data=nullptr;hr(decoded.bufferResource->Map(0,nullptr,reinterpret_cast<void**>(&data)));
    uint64_t matched=0,alpha=0,finite=0;
    for(uint32_t y=0;y<height;++y)for(uint32_t x=0;x<width;++x)
    {
        const auto p=size_t(y)*width+x;std::array<float,3> rgb;
        for(unsigned c=0;c<3;++c)rgb[c]=PackedVector::XMConvertHalfToFloat(words[p*4+c]);
        if(encoded)rgb={std::max(rgb[0]-rgb[2]+rgb[1],0.f),std::max(rgb[0]+rgb[2],0.f),std::max(rgb[0]-rgb[2]-rgb[1],0.f)};
        const auto* row=reinterpret_cast<const float*>(data+decoded.footprint.Offset+size_t(y)*decoded.footprint.Footprint.RowPitch);
        for(unsigned c=0;c<3;++c){matched+=row[x*4+c]==rgb[c]*64.f;finite+=std::isfinite(row[x*4+c]);}alpha+=row[x*4+3]==1.f;
    }
    decoded.bufferResource->Unmap(0,nullptr);need(matched==uint64_t(width)*height*3 && finite==matched,"actual original Consumer GPU decodes RR-only commit with exact execution-time mode/factor64");
    need(alpha==uint64_t(width)*height,"original Consumer alpha1 remains independent of opaque native alpha");
}
void nativeBlendChecks(Host& host)
{
    const uint32_t width=128,height=128;Scene scene(host,width,height,{},true);host.submit();host.reset();RRWrapper wrapper;FrameParameters frame;std::string error;
    const auto oldSpec=FfxApiProxy::mockSpec,oldDiff=FfxApiProxy::mockDiff;const bool oldWrites=FfxApiProxy::recordPartialWrites;
    if(!FfxApiProxy::real){FfxApiProxy::mockSpec={1.5f,7.f,9.25f,99.f};FfxApiProxy::mockDiff={9.f,2.75f,.5f,98.f};FfxApiProxy::recordPartialWrites=true;}
    struct Case {float strength;bool table;uint32_t flag;bool nanAlpha=false,invalidRgb=false;};
    const Case cases[] {{0.f,false,0,false,true},{1.f,false,0,true,true},{.375f,false,0,false,true},{.5f,false,1},{.75f,true,0},{1.f,true,1,true,true},
        {std::numeric_limits<float>::quiet_NaN(),false,1,false,true},{std::numeric_limits<float>::infinity(),false,0},
        {-1.f,true,1},{2.f,true,0,true},{.5f,true,0x80000000u},{.5f,true,0x7fc00000u},{.375f,false,1,false,true},{.375f,true,0,false,true}};
    uint64_t staging=0,auxiliary=0;
    for(unsigned i=0;i<std::size(cases);++i)
    {
        const auto& test=cases[i];const bool encoded=test.flag!=0;ConsumerBuffer old(host),next(host);old.flag(encoded?0u:1u);
        NativeTableConsumer consumer(host,scene.spec(),scene.diff(),width,height);consumer.Overwrite(host.device.Get(),old.constants().address);
        const auto refs=old.references(),nextRefs=next.references(),heapRefs=consumer.References();
        ClearPair(host.list.Get(),scene.spec(),scene.diff(),{.125f,.25f,.5f,9.f},{1.25f,1.5f,1.75f,11.f});
        const std::array<float,3> nativeRgb {2.25f,.75f,5.5f};const std::array<float,3> nativeColor=encoded?
            std::array<float,3>{(nativeRgb[0]+2.f*nativeRgb[1]+nativeRgb[2])*.25f,(nativeRgb[0]-nativeRgb[2])*.5f,(-nativeRgb[0]+2.f*nativeRgb[1]-nativeRgb[2])*.25f}:nativeRgb;
        std::array<uint16_t,4> nativeWords;for(unsigned c=0;c<3;++c)nativeWords[c]=PackedVector::XMConvertFloatToHalf(nativeColor[c]);
        nativeWords[3]=test.nanAlpha?uint16_t(0x7e55u):PackedVector::XMConvertFloatToHalf(9.f);if(test.invalidRgb){nativeWords[0]=0x7e31u;nativeWords[1]=0x7c00u;nativeWords[2]=0xfc00u;}
        seedNativeSpecular(host,scene,nativeWords);Readback before(host,scene.spec());
        RRSettings settings;settings.nativeSpecularBlend=test.strength;const auto calls=FfxApiProxy::configures;
        need(wrapper.Configure(settings,error) && FfxApiProxy::configures==calls,"ignored native coefficient emits no AMD key calls");
        need(wrapper.PrepareFrame(camera(900+i,1.f),false,frame,error),"prepare adversarial native-coefficient RR-only frame");frame.nativeSpecularBlend=test.strength;
        frame.outputEncoding=encoded?SignalEncoding::Rgb:SignalEncoding::YCoCg; // Deliberately WRONG fallback: only live b6 is authoritative.
        frame.outputConstants=test.table?TitleSignalConstants{nullptr,0,consumer.heap.Get(),consumer.Handle()}:TitleSignalConstants{nullptr,old.constants().address};
        const auto dispatches=FfxApiProxy::dispatches;need(wrapper.Dispatch(host.list.Get(),scene.resources,scene.spec(),scene.diff(),frame,error),error.c_str());
        need(FfxApiProxy::dispatches==dispatches+1 && wrapper.ContextGeneration()==1,"both RR lobes dispatch once with one unchanged context for every ignored coefficient");
        need(bool(FfxApiProxy::lastDispatch.flags&FFX_DENOISER_DISPATCH_RESET)==(i==0),"coefficient/native mode changes never reset valid RR history");descriptorChecks(frame);
        if(i==0){staging=wrapper.OwnedStagingBytes();auxiliary=wrapper.OwnedAuxiliaryBytes();}
        need(wrapper.OwnedStagingBytes()==staging && wrapper.OwnedAuxiliaryBytes()==auxiliary,"ignored coefficient adds no owned staging or auxiliary allocation beyond existing live-flag capture");
        consumer.Record(host);Readback decodedSpec(host,consumer.spec.Get()),decodedDiff(host,consumer.diff.Get());
        Readback spec(host,scene.spec()),diff(host,scene.diff()),stagedSpec(host,static_cast<ID3D12Resource*>(FfxApiProxy::lastSpecular.signal.output.resource)),stagedDiff(host,static_cast<ID3D12Resource*>(FfxApiProxy::lastDiffuse.signal.output.resource));
        if(test.table){next.flag(test.flag);consumer.Overwrite(host.device.Get(),next.constants().address);}
        else old.flag(test.flag); // AFTER capture/commit and original Consumer recording.
        if(i==0)
        {
            hr(host.list->Close());settings.nativeSpecularBlend=1.f;const auto generation=wrapper.ContextGeneration();const auto configureCalls=FfxApiProxy::configures;
            need(wrapper.Configure(settings,error) && wrapper.ContextGeneration()==generation && FfxApiProxy::configures==configureCalls &&
                std::bit_cast<uint32_t>(wrapper.GetSettingsState().requested.nativeSpecularBlend)==0u,
                "forbidden coefficient after Close remains zero and cannot alter old RR recording or context");
            ComPtr<IUnknown> identity;hr(host.list.As(&identity));auto submission=RecordedComputeLease::BeforeSubmission(host.queue.Get(),{identity.Get()});
            ID3D12CommandList* lists[]{host.list.Get()};host.queue->ExecuteCommandLists(1,lists);RecordedComputeLease::AfterSubmission(submission);host.finish();host.reset();
        }
        else {host.submit();host.reset();}
        need(consumer.Flag()==test.flag,"actual Consumer and RR-only commit follow the same execution-time word303 despite wrong fallback enum");
        need(old.references()==refs && next.references()==nextRefs && consumer.References()==heapRefs,"RR-only commit never retains borrowed native CBV/heap targets");
        if(test.nanAlpha) {const auto seeded=before.values(width,height);uint64_t same=0;for(size_t p=0;p<size_t(width)*height;++p)same+=seeded[p*4+3]==0x7e55u;
            need(same==uint64_t(width)*height,"NaN alpha seed is transported to native OUT without any payload conversion");}
        if(test.invalidRgb){const auto seeded=before.values(width,height);uint64_t poison=0;
            for(size_t p=0;p<size_t(width)*height;++p)for(unsigned c=0;c<3;++c)poison+=!std::isfinite(PackedVector::XMConvertHalfToFloat(seeded[p*4+c]));
            need(poison==uint64_t(width)*height*3,"all native RGB NaN/Inf poison words reached the destination before RR-only commit");}
        nativeBlendReference(spec,stagedSpec,before,width,height,test.strength,encoded);diff.consumerRoundtrip(stagedDiff,width,height,encoded,11.f);
        nativeConsumerTitleIdentity(decodedSpec,spec,width,height,encoded);nativeConsumerTitleIdentity(decodedDiff,diff,width,height,encoded);
    }
    if(!FfxApiProxy::real){FfxApiProxy::mockSpec=oldSpec;FfxApiProxy::mockDiff=oldDiff;FfxApiProxy::recordPartialWrites=oldWrites;}
    std::cout<<"native_blend cases="<<std::size(cases)<<" policy_zero=1 rr_rgb_exact=1 native_rgb_ignored=1 alpha_bits_exact=1 live_root_and_table=1 fallback_wrong=1 closed_recording_immutable=1 extra_dispatches=0 extra_owned_bytes=0 history_resets_on_change=0\n";
}
void nativeBlendFailureChecks(Host& host)
{
    Scene scene(host,64,64);host.submit();host.reset();const auto oldWrites=FfxApiProxy::recordPartialWrites;FfxApiProxy::recordPartialWrites=true;
    for(bool table:{false,true})for(bool cancelled:{false,true})
    {
        RRWrapper wrapper;FrameParameters frame;std::string error;ConsumerBuffer native(host);native.flag(1);
        NativeTableConsumer consumer(host,scene.spec(),scene.diff(),64,64);consumer.Overwrite(host.device.Get(),native.constants().address);
        ClearPair(host.list.Get(),scene.spec(),scene.diff(),{.125f,.25f,.5f,9.f},{1.25f,1.5f,1.75f,11.f});
        Readback originalSpec(host,scene.spec()),originalDiff(host,scene.diff());RRSettings desired;desired.nativeSpecularBlend=.5f;need(wrapper.Configure(desired,error),"configure weighted failure fixture");
        need(wrapper.PrepareFrame(camera(1000),false,frame,error),"prepare weighted partial-provider/cancel fixture");frame.nativeSpecularBlend=.5f;
        frame.outputConstants=table?TitleSignalConstants{nullptr,0,consumer.heap.Get(),consumer.Handle()}:TitleSignalConstants{nullptr,native.constants().address};
        const auto destroys=FfxApiProxy::destroys,creates=FfxApiProxy::creates;CommitProbe probe;FfxApiProxy::rejectDispatch=!cancelled;
        const OutputCommitGuard guard=cancelled?OutputCommitGuard{&probe,CommitProbe::Admit}:OutputCommitGuard{};
        need(!wrapper.Dispatch(host.list.Get(),scene.resources,scene.spec(),scene.diff(),frame,error,guard),"weighted SDK runtime-error/denied admission fails closed");
        if(cancelled)need(probe.calls==1&&probe.actions==0,"denied weighted guard records zero flag capture or commit");
        need(wrapper.OwnedStagingBytes()==0&&FfxApiProxy::destroys==destroys,"weighted failure retires context while partial SDK recording remains leased");
        Readback spec(host,scene.spec()),diff(host,scene.diff());host.submit();host.reset();
        need(spec.values(64,64)==originalSpec.values(64,64)&&diff.values(64,64)==originalDiff.values(64,64),"weighted provider failure/cancel preserves every original native RGBA bit");
        need(FfxApiProxy::destroys==destroys+1,"failed weighted context destroys only after actual GPU completion");FfxApiProxy::rejectDispatch=false;probe.accepted=true;
        need(wrapper.PrepareFrame(camera(1001),false,frame,error)&&frame.reset&&!frame.previousValid,"weighted failure resets private history before physically fresh recovery");
        frame.nativeSpecularBlend=.5f;frame.outputConstants=table?TitleSignalConstants{nullptr,0,consumer.heap.Get(),consumer.Handle()}:TitleSignalConstants{nullptr,native.constants().address};
        Readback before(host,scene.spec());need(wrapper.Dispatch(host.list.Get(),scene.resources,scene.spec(),scene.diff(),frame,error,guard),error.c_str());
        need(FfxApiProxy::creates==creates+2&&wrapper.ContextGeneration()==2,"weighted failed provider never reuses a partially recorded CPU/GPU context");
        Readback recovered(host,scene.spec()),staged(host,static_cast<ID3D12Resource*>(FfxApiProxy::lastSpecular.signal.output.resource));host.submit();host.reset();
        nativeBlendReference(recovered,staged,before,64,64,.5f,true);
    }
    FfxApiProxy::recordPartialWrites=oldWrites;std::cout<<"native_blend_failures partial_provider=2 denied_admission=2 native_rgba_exact=1 fresh_recovery_context=1\n";
}
void tableEncodingChecks(Host& host)
{
    const auto width=FfxApiProxy::real?1505u:64u,height=FfxApiProxy::real?847u:64u;
    Scene scene(host,width,height,{},true);host.submit();host.reset();RRWrapper wrapper;FrameParameters frame;std::string error;
    const auto previousSpec=FfxApiProxy::mockSpec,previousDiff=FfxApiProxy::mockDiff;
    if(!FfxApiProxy::real){FfxApiProxy::mockSpec={1.5f,7.f,9.25f,99.f};FfxApiProxy::mockDiff={9.f,2.75f,.5f,98.f};FfxApiProxy::recordPartialWrites=true;}
    const uint32_t flags[] {0u,1u,0x80000000u,0x7fc00000u,0u,1u,0u,1u};
    uint64_t auxiliary=0;
    for(unsigned i=0;i<std::size(flags);++i)
    {
        ConsumerBuffer old(host),next(host,i>=4);old.flag(flags[i]?0:1);
        NativeTableConsumer consumer(host,scene.spec(),scene.diff(),width,height);consumer.Overwrite(host.device.Get(),old.constants().address);
        const auto heapRefs=consumer.References(),oldRefs=old.references(),nextRefs=next.references();
        ClearPair(host.list.Get(),scene.spec(),scene.diff(),{.125f,.25f,.5f,9.f},{1.25f,1.5f,1.75f,11.f});
        need(wrapper.PrepareFrame(camera(800+i,width/float(height)),false,frame,error),"prepare volatile native table frame");
        frame.outputEncoding=flags[i]?SignalEncoding::Rgb:SignalEncoding::YCoCg;
        frame.outputConstants=i<6?TitleSignalConstants{old.binding.Get(),old.constants().address,consumer.heap.Get(),consumer.Handle()}
            :TitleSignalConstants{nullptr,0,consumer.heap.Get(),consumer.Handle()};
        if(i>=6)need(!frame.outputConstants.resource && !frame.outputConstants.address,
            "ownerless table-only test supplies neither source resource nor VA");
        need(wrapper.Dispatch(host.list.Get(),scene.resources,scene.spec(),scene.diff(),frame,error),error.c_str());
        if(i==0)auxiliary=wrapper.OwnedAuxiliaryBytes();
        need(wrapper.OwnedAuxiliaryBytes()==auxiliary,"warm native flag snapshots reused without new allocation");
        need(consumer.References()==heapRefs && old.references()==oldRefs && next.references()==nextRefs,
             "bridge never AddRef's native volatile heap or either CBV target");
        consumer.Record(host);
        Readback decodedSpec(host,consumer.spec.Get()),decodedDiff(host,consumer.diff.Get());
        Readback spec(host,scene.spec()),diff(host,scene.diff());
        Readback stagedSpec(host,static_cast<ID3D12Resource*>(FfxApiProxy::lastSpecular.signal.output.resource));
        Readback stagedDiff(host,static_cast<ID3D12Resource*>(FfxApiProxy::lastDiffuse.signal.output.resource));
        // Overwrite the genuine native CBV descriptor to a DIFFERENT resource,
        // after both our capture/commit and original Consumer were recorded.
        next.flag(flags[i]);need(next.constants().address!=old.constants().address,"table overwrite must target a different buffer");
        consumer.Overwrite(host.device.Get(),next.constants().address);host.submit();host.reset();
        need(consumer.Flag()==flags[i],"original Consumer GPU table read follows overwritten native descriptor");
        spec.consumerRoundtrip(stagedSpec,width,height,flags[i]!=0,9.f);
        diff.consumerRoundtrip(stagedDiff,width,height,flags[i]!=0,11.f);
        decodedSpec.consumerGpuRoundtrip(spec,stagedSpec,width,height,flags[i]!=0);
        decodedDiff.consumerGpuRoundtrip(diff,stagedDiff,width,height,flags[i]!=0);
    }
    need(auxiliary==5u*65536u,"four committed64K flag slots plus committed64K fallback CB");
    if(!FfxApiProxy::real){FfxApiProxy::recordPartialWrites=false;FfxApiProxy::mockSpec=previousSpec;FfxApiProxy::mockDiff=previousDiff;}
    std::cout<<"volatile_table cases=8 original_consumer_RSG1.0=1 overwrite_different_buffer=8 default_heap=4 ownerless_table_address0=2 native_alpha=9,11 auxiliary_bytes="<<auxiliary<<'\n';
}
void nearestHalfEdgeChecks(Host& host)
{
    const float sub=std::ldexp(1.f,-24),normal=std::ldexp(1.f,-14);
    const std::array<std::array<float,4>,9> cases {{
        {sub,0.f,0.f,99.f}, {0.f,sub,0.f,99.f}, {0.f,0.f,sub,99.f},
        {2.f*sub,0.f,0.f,99.f}, {4.f*normal,0.f,0.f,99.f},
        {0.f,std::ldexp(1.f,-13)-sub,0.f,99.f},
        {1.9990234375f,2.f,1.9990234375f,99.f},
        {65504.f,65504.f,65504.f,99.f}, {-0.f,0.f,0.f,99.f}
    }};
    Scene scene(host,64,64);host.submit();host.reset();RRWrapper wrapper;FrameParameters frame;std::string error;
    ConsumerBuffer old(host),next(host);next.flag(1);
    NativeTableConsumer consumer(host,scene.spec(),scene.diff(),64,64);
    const auto priorSpec=FfxApiProxy::mockSpec,priorDiff=FfxApiProxy::mockDiff;
    const auto priorSpecScale=FfxApiProxy::mockSpecularScale,priorDiffScale=FfxApiProxy::mockDiffuseScale;
    // This is a codec endpoint test, so use unity units to retain the complete
    // half range (including 65504), independent of radiance normalization.
    RRSettings codecSettings;codecSettings.radianceScale={true,1,1};
    need(wrapper.Configure(codecSettings,error),"codec endpoint test uses explicit unity provider units");
    FfxApiProxy::mockSpecularScale=FfxApiProxy::mockDiffuseScale=1.f;
    FfxApiProxy::recordPartialWrites=true;
    for(unsigned i=0;i<cases.size();++i)
    {
        FfxApiProxy::mockSpec=cases[i];FfxApiProxy::mockDiff=cases[i];
        consumer.Overwrite(host.device.Get(),old.constants().address);
        ClearPair(host.list.Get(),scene.spec(),scene.diff(),{.125f,.25f,.5f,9.f},{1.25f,1.5f,1.75f,11.f});
        need(wrapper.PrepareFrame(camera(850+i),false,frame,error),"prepare half-rounding GPU edge frame");
        frame.outputConstants={old.binding.Get(),old.constants().address,consumer.heap.Get(),consumer.Handle()};
        need(wrapper.Dispatch(host.list.Get(),scene.resources,scene.spec(),scene.diff(),frame,error),error.c_str());
        consumer.Record(host);Readback decodedSpec(host,consumer.spec.Get()),decodedDiff(host,consumer.diff.Get());
        Readback spec(host,scene.spec()),diff(host,scene.diff());
        Readback stagedSpec(host,static_cast<ID3D12Resource*>(FfxApiProxy::lastSpecular.signal.output.resource));
        Readback stagedDiff(host,static_cast<ID3D12Resource*>(FfxApiProxy::lastDiffuse.signal.output.resource));
        consumer.Overwrite(host.device.Get(),next.constants().address);host.submit();host.reset();
        need(consumer.Flag()==1,"edge Consumer GPU sees overwritten YCoCg table");
        spec.nearestHalfEdges(stagedSpec,64,64,9.f,i);diff.nearestHalfEdges(stagedDiff,64,64,11.f,i);
        decodedSpec.consumerGpuRoundtrip(spec,stagedSpec,64,64,true);
        decodedDiff.consumerGpuRoundtrip(diff,stagedDiff,64,64,true);
    }
    FfxApiProxy::recordPartialWrites=false;FfxApiProxy::mockSpec=priorSpec;FfxApiProxy::mockDiff=priorDiff;
    FfxApiProxy::mockSpecularScale=priorSpecScale;FfxApiProxy::mockDiffuseScale=priorDiffScale;
}
void tableFailureChecks(Host& host)
{
    Scene scene(host,64,64);host.submit();host.reset();FfxApiProxy::recordPartialWrites=true;
    for(bool cancelled:{false,true})
    {
        ConsumerBuffer old(host),next(host);next.flag(1);
        NativeTableConsumer consumer(host,scene.spec(),scene.diff(),64,64);consumer.Overwrite(host.device.Get(),old.constants().address);
        ClearPair(host.list.Get(),scene.spec(),scene.diff(),{.125f,.25f,.5f,9.f},{1.25f,1.5f,1.75f,11.f});host.submit();host.reset();
        RRWrapper wrapper;FrameParameters frame;std::string error;CommitProbe probe;
        const auto creates=FfxApiProxy::creates,destroys=FfxApiProxy::destroys;
        const auto refs=consumer.References();
        need(wrapper.PrepareFrame(camera(820),false,frame,error),"prepare volatile table error/cancel");
        frame.outputConstants={old.binding.Get(),old.constants().address,consumer.heap.Get(),consumer.Handle()};
        FfxApiProxy::rejectDispatch=!cancelled;OutputCommitGuard guard=cancelled?OutputCommitGuard{&probe,CommitProbe::Admit}:OutputCommitGuard{};
        need(!wrapper.Dispatch(host.list.Get(),scene.resources,scene.spec(),scene.diff(),frame,error,guard),"table SDK error/denied guard propagated");
        need(wrapper.OwnedAuxiliaryBytes()==0 && FfxApiProxy::destroys==destroys,"failed table snapshots/context leased until partial GPU completion");
        if(cancelled)need(probe.calls==1 && probe.actions==0,"denied table guard records no capture or commit action");
        consumer.Record(host);Readback spec(host,scene.spec()),diff(host,scene.diff());
        consumer.Overwrite(host.device.Get(),next.constants().address);host.submit();host.reset();
        need(consumer.Flag()==1,"Consumer independently observes overwritten table after cancelled commit");
        spec.exact({.125f,.25f,.5f,9.f},64,64);diff.exact({1.25f,1.5f,1.75f,11.f},64,64);
        need(FfxApiProxy::destroys==destroys+1 && consumer.References()==refs,"failed table generation deferred, native heap remains unretained");
        FfxApiProxy::rejectDispatch=false;probe.accepted=true;
        need(wrapper.PrepareFrame(camera(821),false,frame,error) && frame.reset && !frame.previousValid,"failed table history reset");
        frame.outputConstants={next.binding.Get(),next.constants().address,consumer.heap.Get(),consumer.Handle()};
        need(wrapper.Dispatch(host.list.Get(),scene.resources,scene.spec(),scene.diff(),frame,error,guard),error.c_str());
        need(FfxApiProxy::creates==creates+2 && wrapper.ContextGeneration()==2,"table failure recovery physically recreates provider");
        Readback recoveredSpec(host,scene.spec()),recoveredDiff(host,scene.diff());
        Readback stagedSpec(host,static_cast<ID3D12Resource*>(FfxApiProxy::lastSpecular.signal.output.resource));
        Readback stagedDiff(host,static_cast<ID3D12Resource*>(FfxApiProxy::lastDiffuse.signal.output.resource));
        host.submit();host.reset();recoveredSpec.consumerRoundtrip(stagedSpec,64,64,true,9.f);recoveredDiff.consumerRoundtrip(stagedDiff,64,64,true,11.f);
    }
    FfxApiProxy::recordPartialWrites=false;
}
void tableDiscardChecks(Host& host)
{
    const auto width=FfxApiProxy::real?1505u:64u,height=FfxApiProxy::real?847u:64u;
    Scene scene(host,width,height,{},true);host.submit();host.reset();ConsumerBuffer native(host);native.flag(1);
    NativeTableConsumer consumer(host,scene.spec(),scene.diff(),width,height);consumer.Overwrite(host.device.Get(),native.constants().address);
    RRWrapper wrapper;FrameParameters frame;std::string error;const auto creates=FfxApiProxy::creates,destroys=FfxApiProxy::destroys;
    if(!FfxApiProxy::real)FfxApiProxy::recordPartialWrites=true;
    need(wrapper.PrepareFrame(camera(830),false,frame,error),"prepare unsubmitted table capture");
    frame.outputConstants={native.binding.Get(),native.constants().address,consumer.heap.Get(),consumer.Handle()};
    need(wrapper.Dispatch(host.list.Get(),scene.resources,scene.spec(),scene.diff(),frame,error),error.c_str());
    hr(host.list->Close());host.reset();wrapper.DiscardRecordingHistory();
    need(wrapper.OwnedAuxiliaryBytes()==0 && FfxApiProxy::destroys==destroys+1,"discarded table snapshot generation destroyed only after list reset");
    need(wrapper.PrepareFrame(camera(831),false,frame,error) && frame.reset && !frame.previousValid,"discarded table private history absent");
    frame.outputConstants={native.binding.Get(),native.constants().address,consumer.heap.Get(),consumer.Handle()};
    need(wrapper.Dispatch(host.list.Get(),scene.resources,scene.spec(),scene.diff(),frame,error),error.c_str());
    need(FfxApiProxy::creates==creates+2,"post-discard table context is physically new");
    consumer.Record(host);Readback decodedSpec(host,consumer.spec.Get()),decodedDiff(host,consumer.diff.Get());
    Readback spec(host,scene.spec()),diff(host,scene.diff());
    Readback stagedSpec(host,static_cast<ID3D12Resource*>(FfxApiProxy::lastSpecular.signal.output.resource));
    Readback stagedDiff(host,static_cast<ID3D12Resource*>(FfxApiProxy::lastDiffuse.signal.output.resource));
    host.submit();host.reset();need(consumer.Flag()==1,"post-discard actual Consumer uses table flag");
    spec.consumerRoundtrip(stagedSpec,width,height,true,.75f);diff.consumerRoundtrip(stagedDiff,width,height,true,2.f);
    decodedSpec.consumerGpuRoundtrip(spec,stagedSpec,width,height,true);decodedDiff.consumerGpuRoundtrip(diff,stagedDiff,width,height,true);
    if(!FfxApiProxy::real)FfxApiProxy::recordPartialWrites=false;
}
void sameBatchSnapshotChecks(Host& host)
{
    Scene scene(host,64,64);host.submit();host.reset();ConsumerBuffer old(host),next(host);next.flag(1);
    NativeTableConsumer consumer(host,scene.spec(),scene.diff(),64,64);consumer.Overwrite(host.device.Get(),old.constants().address);
    const TitleSignalConstants constants {old.binding.Get(),old.constants().address,consumer.heap.Get(),consumer.Handle()};
    std::shared_ptr<Context> owner;std::string error;const auto destroys=FfxApiProxy::destroys;
    need(CreateContext(host.device.Get(),64,64,owner,error),"create state-balance helper context");
    need(owner->PrepareTableFlags(error),"prepare state-balance helper snapshots");
    auto slot=owner->AcquireSlot(scene.spec(),scene.diff(),error);need(bool(slot),"acquire state-balance helper slot");
    ComPtr<ID3D12CommandAllocator> secondAllocator;ComPtr<ID3D12GraphicsCommandList> secondList;
    hr(host.device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT,IID_PPV_ARGS(&secondAllocator)));
    hr(host.device->CreateCommandList(0,D3D12_COMMAND_LIST_TYPE_DIRECT,secondAllocator.Get(),nullptr,IID_PPV_ARGS(&secondList)));
    std::array<std::shared_ptr<DispatchLease>,2> leases;
    ID3D12GraphicsCommandList* lists[] {host.list.Get(),secondList.Get()};
    for(unsigned i=0;i<2;++i)
    {
        leases[i]=MakeOwnedShared<DispatchLease>();leases[i]->context=owner;leases[i]->slot=slot;
        need(ResTrack_Dx12::RetainComputeDispatch(host.device.Get(),lists[i],leases[i]),"explicit lease of shared state-balance snapshot");
        ClearPair(lists[i],scene.spec(),scene.diff(),{.125f,.25f,.5f,9.f},{1.25f,1.5f,1.75f,11.f});
        ClearPair(lists[i],slot->spec.Get(),slot->diff.Get(),{1.5f,7.f,9.25f,99.f},{9.f,2.75f,.5f,98.f});
        // Deliberately reuse the SAME private slot to exercise its real production
        // Commit/FlagCapture state balance. Normal pool admission never reuses an
        // outstanding lease; two distinct lists are required by the native API.
        owner->Commit(lists[i],*slot,scene.spec(),scene.diff(),SignalEncoding::Rgb,constants,0.0f);
    }
    hr(host.list->Close());auto firstList=host.list;host.list=secondList;
    consumer.Record(host);Readback decodedSpec(host,consumer.spec.Get()),decodedDiff(host,consumer.diff.Get());
    Readback spec(host,scene.spec()),diff(host,scene.diff()),stagedSpec(host,slot->spec.Get()),stagedDiff(host,slot->diff.Get());
    hr(secondList->Close());host.list=firstList;
    consumer.Overwrite(host.device.Get(),next.constants().address);
    ComPtr<IUnknown> firstIdentity,secondIdentity;hr(firstList.As(&firstIdentity));hr(secondList.As(&secondIdentity));
    ComPtr<ID3D12Fence> gate;hr(host.device->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&gate)));
    struct Unblock { ID3D12Fence* fence; ~Unblock(){fence->Signal(1);} } unblock {gate.Get()};
    hr(host.queue->Wait(gate.Get(),1));
    {
        auto submission=RecordedComputeLease::BeforeSubmission(host.queue.Get(),{firstIdentity.Get(),secondIdentity.Get()});
        ID3D12CommandList* submitted[] {firstList.Get(),secondList.Get()};host.queue->ExecuteCommandLists(2,submitted);
        RecordedComputeLease::AfterSubmission(submission);
    } // Release the fixture's own strong submission handle before testing retirement.
    owner.reset();for(auto& lease:leases)lease.reset();
    for(auto* list:lists){auto recording=RecordedComputeLease::Capture(list);RecordedComputeLease::Detach(recording);}
    need(FfxApiProxy::destroys==destroys,"shared snapshot/commit pipeline retained while two-list GPU batch is blocked");
    hr(gate->Signal(1));host.finish();need(FfxApiProxy::destroys==destroys+1,"shared helper context retires after batch completion");
    need(consumer.Flag()==1,"actual Consumer sees overwritten CBV after both distinct-list captures");
    spec.consumerRoundtrip(stagedSpec,64,64,true,9.f);diff.consumerRoundtrip(stagedDiff,64,64,true,11.f);
    decodedSpec.consumerGpuRoundtrip(spec,stagedSpec,64,64,true);decodedDiff.consumerGpuRoundtrip(diff,stagedDiff,64,64,true);
    host.reset();std::cout<<"same_batch distinct_lists=2 shared_snapshot=1 end_start_COMMON=1 native_alpha=9,11 debug_strict=1\n";
}
void encodingValidationChecks(Host& host)
{
    Scene scene(host,FfxApiProxy::real?1505u:64u,FfxApiProxy::real?847u:64u);host.submit();host.reset();
    ConsumerBuffer native(host);RRWrapper wrapper;FrameParameters frame;std::string error;
    need(wrapper.PrepareFrame(camera(420),false,frame,error),"prepare native encoding validation");
    const auto creates=FfxApiProxy::creates,dispatches=FfxApiProxy::dispatches;
    frame.outputEncoding=static_cast<SignalEncoding>(2);
    need(!wrapper.Dispatch(host.list.Get(),scene.resources,scene.spec(),scene.diff(),frame,error),"invalid encoding enum fails closed");
    frame.outputEncoding=SignalEncoding::Rgb;
    const auto address=native.constants().address;
    auto makeHeap=[](ID3D12Device* device,D3D12_DESCRIPTOR_HEAP_TYPE type,D3D12_DESCRIPTOR_HEAP_FLAGS flags) {
        D3D12_DESCRIPTOR_HEAP_DESC desc{};desc.Type=type;desc.NumDescriptors=4;desc.Flags=flags;
        ComPtr<ID3D12DescriptorHeap> heap;hr(device->CreateDescriptorHeap(&desc,IID_PPV_ARGS(&heap)));return heap;
    };
    auto heap=makeHeap(host.device.Get(),D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV,D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE);
    auto otherHeap=makeHeap(host.device.Get(),D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV,D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE);
    auto sampler=makeHeap(host.device.Get(),D3D12_DESCRIPTOR_HEAP_TYPE_SAMPLER,D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE);
    auto hidden=makeHeap(host.device.Get(),D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV,D3D12_DESCRIPTOR_HEAP_FLAG_NONE);
    const auto handle=heap->GetGPUDescriptorHandleForHeapStart(),otherHandle=otherHeap->GetGPUDescriptorHandleForHeapStart();
    const auto stride=host.device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
    need(otherHandle.ptr<handle.ptr || otherHandle.ptr>=handle.ptr+UINT64(4)*stride,
         "wrong-target probe uses a descriptor from a genuinely different heap");
    // Source owner/identity/width is diagnostic-only. Replace those obsolete
    // rejection probes with actual native binding shape/device contracts.
    struct Invalid { TitleSignalConstants constants; const char* reason; };
    const Invalid cases[] {
        {{nullptr,address+1},"unaligned direct root VA fails closed"},
        {{nullptr,0,heap.Get(),{}},"native heap without handle fails closed"},
        {{nullptr,0,nullptr,handle},"native handle without heap fails closed"},
        {{nullptr,0,heap.Get(),otherHandle},"native handle targeting another heap fails closed"},
        {{nullptr,0,heap.Get(),{handle.ptr+1}},"unaligned native descriptor handle fails closed"},
        {{nullptr,0,heap.Get(),{handle.ptr+UINT64(4)*stride}},"out-of-range native descriptor handle fails closed"},
        {{nullptr,0,sampler.Get(),sampler->GetGPUDescriptorHandleForHeapStart()},"wrong native heap type fails closed"},
        {{nullptr,0,hidden.Get(),handle},"non-shader-visible native heap fails closed"}
    };
    for(const auto& test:cases)
    {
        frame.outputConstants=test.constants;
        need(!wrapper.Dispatch(host.list.Get(),scene.resources,scene.spec(),scene.diff(),frame,error),test.reason);
        need(!error.empty(),"invalid CBV reports concrete reason");
    }
    ComPtr<IDXGIFactory4> foreignFactory;hr(CreateDXGIFactory1(IID_PPV_ARGS(&foreignFactory)));
    ComPtr<IDXGIAdapter> foreignAdapter;hr(foreignFactory->EnumWarpAdapter(IID_PPV_ARGS(&foreignAdapter)));
    ComPtr<ID3D12Device> foreignDevice;hr(D3D12CreateDevice(foreignAdapter.Get(),D3D_FEATURE_LEVEL_12_0,IID_PPV_ARGS(&foreignDevice)));
    auto foreign=makeHeap(foreignDevice.Get(),D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV,D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE);
    const auto foreignHandle=foreign->GetGPUDescriptorHandleForHeapStart();
    need(foreignHandle.ptr!=0,"foreign device probe supplies a genuine native GPU descriptor handle");
    frame.outputConstants={nullptr,0,foreign.Get(),foreignHandle};
    need(!wrapper.Dispatch(host.list.Get(),scene.resources,scene.spec(),scene.diff(),frame,error),"foreign device native heap fails closed");
    need(error.find("device mismatch")!=std::string::npos,"native heap device rejection diagnosed");
    need(FfxApiProxy::creates==creates && FfxApiProxy::dispatches==dispatches && wrapper.ContextGeneration()==0,
        "invalid encoding/CBV invokes no provider and creates no context");
    need(!RecordedComputeLease::Capture(host.list.Get()),"invalid encoding/CBV records no GPU work");
    std::cout<<"native_binding_negative obsolete_source_owner_range_probes_replaced=5 unaligned_rootVA_retained=1 native_shape_cases=9 provider_calls=0 recorded_work=0\n";
}
void encodingChecks(Host& host)
{
    const auto width=FfxApiProxy::real?1505u:64u,height=FfxApiProxy::real?847u:64u;
    Scene scene(host,width,height,{},true);host.submit();host.reset();RRWrapper wrapper;FrameParameters frame;std::string error;
    const auto previousSpec=FfxApiProxy::mockSpec,previousDiff=FfxApiProxy::mockDiff;
    if(!FfxApiProxy::real)
    {
        // Both signs of chroma are exercised with unequal channels and staged
        // alpha distinct from native alpha. Original fixture values are restored.
        FfxApiProxy::mockSpec={1.5f,7.f,9.25f,99.f};FfxApiProxy::mockDiff={9.f,2.75f,.5f,98.f};
        FfxApiProxy::recordPartialWrites=true;
    }
    struct Case { bool native,defaultHeap; UINT64 offset; uint32_t flag; SignalEncoding fallback; bool encoded; bool ownerless=false; };
    const Case cases[] {
        {false,false,0,0,SignalEncoding::Rgb,false},
        {false,false,0,0,SignalEncoding::YCoCg,true},
        {true,false,0,0,SignalEncoding::YCoCg,false},
        {true,false,0,1,SignalEncoding::Rgb,true},
        {true,false,0,0x80000000u,SignalEncoding::Rgb,true},
        {true,false,0,0x7fc00000u,SignalEncoding::Rgb,true},
        {true,true,0,1,SignalEncoding::Rgb,true},
        {true,false,256,1,SignalEncoding::Rgb,true},
        {true,false,0,0,SignalEncoding::YCoCg,false,true},
        {true,false,0,1,SignalEncoding::Rgb,true,true},
    };
    for(unsigned i=0;i<std::size(cases);++i)
    {
        const auto& test=cases[i];ConsumerBuffer native(host,test.defaultHeap,test.offset,test.ownerless?1216:1536);
        const auto nativeRefs=native.references();
        need(wrapper.PrepareFrame(camera(430+i,width/float(height)),false,frame,error),"prepare asymmetric codec frame");
        frame.outputEncoding=test.fallback;if(test.native)frame.outputConstants=native.constants();
        if(test.ownerless)
        {
            frame.outputConstants.resource=nullptr;
            need(native.binding->GetDesc().Width==1216 && !frame.outputConstants.resource && frame.outputConstants.address,
                 "ownerless direct-root test supplies only exact VA of a1216-byte buffer");
            native.flag(test.flag?0u:1u); // Both ownerless flags change AFTER the recording below.
        }
        need(wrapper.Dispatch(host.list.Get(),scene.resources,scene.spec(),scene.diff(),frame,error),error.c_str());
        need(wrapper.ContextGeneration()==1,"encoding changes do not recreate provider or history");
        need(native.references()==nativeRefs,"RR commit never AddRef's borrowed native Consumer CBV");
        Readback spec(host,scene.spec()),diff(host,scene.diff());
        Readback stagedSpec(host,static_cast<ID3D12Resource*>(FfxApiProxy::lastSpecular.signal.output.resource));
        Readback stagedDiff(host,static_cast<ID3D12Resource*>(FfxApiProxy::lastDiffuse.signal.output.resource));
        native.flag(test.flag); // AFTER Dispatch/readback recording, BEFORE Execute.
        host.submit();host.reset();
        spec.consumerRoundtrip(stagedSpec,width,height,test.encoded,.75f);
        diff.consumerRoundtrip(stagedDiff,width,height,test.encoded,2.f);
        if(i==0)need(FfxApiProxy::lastDispatch.flags&FFX_DENOISER_DISPATCH_RESET,"first encoding frame resets history");
        else need(!(FfxApiProxy::lastDispatch.flags&FFX_DENOISER_DISPATCH_RESET),"mode changes preserve valid provider history");
    }
    if(!FfxApiProxy::real){FfxApiProxy::recordPartialWrites=false;FfxApiProxy::mockSpec=previousSpec;FfxApiProxy::mockDiff=previousDiff;}
    std::cout<<"codec cases=10 native_upload_update_after_record=6 native_default_heap=1 native_offset=256 ownerless_rootVA=2 exact_root_buffer_bytes=1216 integer_nonzero_bits=1,80000000,7fc00000 alpha_exact=1\n";
}
void encodedFailureChecks(Host& host)
{
    Scene scene(host,64,64);host.submit();host.reset();FfxApiProxy::recordPartialWrites=true;
    for(bool cancelled:{false,true})
    {
        ClearPair(host.list.Get(),scene.spec(),scene.diff(),{.125f,.25f,.5f,.75f},{1.25f,1.5f,1.75f,2.f});host.submit();host.reset();
        ConsumerBuffer native(host);RRWrapper wrapper;FrameParameters frame;std::string error;CommitProbe probe;
        const auto creates=FfxApiProxy::creates,destroys=FfxApiProxy::destroys;
        need(wrapper.PrepareFrame(camera(470),false,frame,error),"prepare encoded failure/cancel");
        frame.outputConstants=native.constants();OutputCommitGuard guard=cancelled?OutputCommitGuard{&probe,CommitProbe::Admit}:OutputCommitGuard{};
        FfxApiProxy::rejectDispatch=!cancelled;
        need(!wrapper.Dispatch(host.list.Get(),scene.resources,scene.spec(),scene.diff(),frame,error,guard),"encoded failure/cancel propagated");
        need(wrapper.OwnedStagingBytes()==0 && FfxApiProxy::destroys==destroys,"encoded failed context held by recorded GPU work");
        Readback oldSpec(host,scene.spec()),oldDiff(host,scene.diff());native.flag(1);host.submit();host.reset();
        oldSpec.exact({.125f,.25f,.5f,.75f},64,64);oldDiff.exact({1.25f,1.5f,1.75f,2.f},64,64);
        need(FfxApiProxy::destroys==destroys+1,"encoded failure/cancel destroys only after GPU completion");
        FfxApiProxy::rejectDispatch=false;probe.accepted=true;
        need(wrapper.PrepareFrame(camera(471),false,frame,error) && frame.reset && !frame.previousValid,"encoded recovery has no failed private history");
        frame.outputConstants=native.constants();
        need(wrapper.Dispatch(host.list.Get(),scene.resources,scene.spec(),scene.diff(),frame,error,guard),error.c_str());
        need(wrapper.ContextGeneration()==2 && FfxApiProxy::creates==creates+2,"encoded recovery uses physically fresh context");
        Readback spec(host,scene.spec()),diff(host,scene.diff());
        Readback stagedSpec(host,static_cast<ID3D12Resource*>(FfxApiProxy::lastSpecular.signal.output.resource));
        Readback stagedDiff(host,static_cast<ID3D12Resource*>(FfxApiProxy::lastDiffuse.signal.output.resource));
        host.submit();host.reset();spec.consumerRoundtrip(stagedSpec,64,64,true,.75f);diff.consumerRoundtrip(stagedDiff,64,64,true,2.f);
    }
    FfxApiProxy::recordPartialWrites=false;
}
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
              const std::filesystem::path& output,const char* label,bool nativeTable=false,bool nativeDebug=false)
{
    Scene scene(host,width,height,input);host.submit();host.reset();RRWrapper wrapper;
    ComPtr<ID3D12Resource> debugTarget;
    const uint32_t targetWidth=2560,targetHeight=1440;const std::array<float,4> debugSentinel{.125f,.25f,.5f,7.f};
    if(nativeDebug)
    {
        RRSettings settings;settings.nativeDebugView=1;settings.nativeDebugViewport=4;std::string error;
        need(wrapper.Configure(settings,error),"real timing enables actual SDK confidence debug view");
        D3D12_HEAP_PROPERTIES heap{};heap.Type=D3D12_HEAP_TYPE_DEFAULT;
        D3D12_RESOURCE_DESC target{};target.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D;target.Width=targetWidth;target.Height=targetHeight;
        target.DepthOrArraySize=target.MipLevels=1;target.SampleDesc.Count=1;target.Format=DXGI_FORMAT_R16G16B16A16_FLOAT;target.Flags=D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
        hr(host.device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&target,D3D12_RESOURCE_STATE_UNORDERED_ACCESS,nullptr,IID_PPV_ARGS(&debugTarget)));
        ClearTexture(host.list.Get(),debugTarget.Get(),debugSentinel);host.submit();host.reset();
    }
    std::unique_ptr<ConsumerBuffer> native;
    std::unique_ptr<NativeTableConsumer> consumer;
    if(nativeTable)
    {
        native=std::make_unique<ConsumerBuffer>(host);native->flag(1);
        consumer=std::make_unique<NativeTableConsumer>(host,scene.spec(),scene.diff(),width,height);
        consumer->Overwrite(host.device.Get(),native->constants().address);
    }
    ComPtr<ID3D12QueryHeap> queries;D3D12_QUERY_HEAP_DESC desc{};desc.Type=D3D12_QUERY_HEAP_TYPE_TIMESTAMP;desc.Count=2;
    hr(host.device->CreateQueryHeap(&desc,IID_PPV_ARGS(&queries)));auto timing=buffer(host.device.Get(),16,D3D12_HEAP_TYPE_READBACK);
    UINT64 frequency;hr(host.queue->GetTimestampFrequency(&frequency));std::vector<double> milliseconds;
    uint64_t warmedStagingBytes=0,warmedAuxiliaryBytes=0;
    for(unsigned index=0;index<frames;++index)
    {
        auto snapshot=camera(index,width/float(height),input.empty()?.01f:.02f);snapshot.constants.jitterOffset=sl::float2(0,0);
        snapshot.constants.mvecScale=sl::float2(1,1);FrameParameters frame;std::string error;
        need(wrapper.PrepareFrame(snapshot,false,frame,error),"real loop camera preparation");
        if(nativeTable)frame.outputConstants={native->binding.Get(),native->constants().address,consumer->heap.Get(),consumer->Handle()};
        host.list->EndQuery(queries.Get(),D3D12_QUERY_TYPE_TIMESTAMP,0);
        need(wrapper.Dispatch(host.list.Get(),scene.resources,scene.spec(),scene.diff(),frame,error),error.c_str());
        if(nativeDebug)need(wrapper.PresentNativeDebug(host.list.Get(),debugTarget.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,
            frame.streamlineFrame,error),"real timing presents actual SDK output after complete RR lighting commit");
        if(index==0){warmedStagingBytes=wrapper.OwnedStagingBytes();warmedAuxiliaryBytes=wrapper.OwnedAuxiliaryBytes();}
        need(wrapper.OwnedStagingBytes()==warmedStagingBytes,"sequential recordings reuse warmed staging without allocation");
        need(wrapper.OwnedAuxiliaryBytes()==warmedAuxiliaryBytes,"sequential recording reuses owned fallback/snapshot buffers without allocation");
        host.list->EndQuery(queries.Get(),D3D12_QUERY_TYPE_TIMESTAMP,1);
        host.list->ResolveQueryData(queries.Get(),D3D12_QUERY_TYPE_TIMESTAMP,0,2,timing.Get(),0);
        host.submit();UINT64* ticks;hr(timing->Map(0,nullptr,reinterpret_cast<void**>(&ticks)));
        milliseconds.push_back(double(ticks[1]-ticks[0])*1000/double(frequency));timing->Unmap(0,nullptr);host.reset();
    }
    Readback spec(host,scene.spec()),diff(host,scene.diff());host.submit();host.reset();
    spec.verify(output/(std::string(label)+"_spec.rgba16f"),width,height);
    diff.verify(output/(std::string(label)+"_diff.rgba16f"),width,height);
    if(nativeDebug)
    {
        const auto image=wrapper.GetNativeDebugOutputSnapshot();need(image.resource && image.owner,"real debug timing keeps actual source lease");
        Readback source(host,image.resource),display(host,debugTarget.Get());host.submit();host.reset();
        display.nativeDebugPresentation(source,width,height,targetWidth,targetHeight,debugSentinel,false);
        source.save(output/(std::string(label)+"_native_source.rgba16f"),width,height);
        display.save(output/(std::string(label)+"_native_present.rgba16f"),targetWidth,targetHeight);
    }
    const unsigned warm=std::min(4u,frames-1);std::vector<double> steady(milliseconds.begin()+warm,milliseconds.end());
    std::sort(steady.begin(),steady.end());const double mean=std::accumulate(steady.begin(),steady.end(),0.0)/steady.size();
    std::cout<<"timing "<<label<<" size="<<width<<'x'<<height<<" frames="<<frames<<" warmup="<<warm
        <<" mean_ms="<<mean<<" median_ms="<<steady[steady.size()/2]<<" first_ms="<<milliseconds[0]
        <<" staging_bytes="<<warmedStagingBytes<<" staging_slots=4 auxiliary_bytes="<<warmedAuxiliaryBytes
        <<" scope="<<(nativeDebug?"RR_stage_RGB_commit_SDK_native_debug_clear_and_2560x1440_present":
            (nativeTable?"RR_stage_plus_native_table_capture_YCoCg_commit":"RR_stage_plus_RGB_commit_preserving_title_alpha"))<<" samples_ms=";
    for(auto value:milliseconds)std::cout<<value<<',';std::cout<<'\n';
}
void nativeBlendCommitTiming(Host& host,uint32_t width,uint32_t height)
{
    Scene scene(host,width,height);host.submit();host.reset();std::string error;
    auto owner=MakeOwnedShared<Context>();owner->device=host.device;owner->width=width;owner->height=height;
    need(owner->InitializeCommit(error)&&owner->PrepareTableFlags(error),"commit-only benchmark initializes actual production PSO/root/staging/flag capture without ML provider");
    auto slot=owner->AcquireSlot(scene.spec(),scene.diff(),error);need(bool(slot),"commit timing uses one valid preallocated production descriptor/staging slot");
    ClearPair(host.list.Get(),slot->spec.Get(),slot->diff.Get(),{1.5f,7.f,9.25f,99.f},{9.f,2.75f,.5f,98.f});host.submit();host.reset();
    ConsumerBuffer native(host);const TitleSignalConstants constants{nullptr,native.constants().address};
    ComPtr<ID3D12QueryHeap> query;D3D12_QUERY_HEAP_DESC desc{D3D12_QUERY_HEAP_TYPE_TIMESTAMP,2,0};hr(host.device->CreateQueryHeap(&desc,IID_PPV_ARGS(&query)));
    auto timing=buffer(host.device.Get(),16,D3D12_HEAP_TYPE_READBACK);UINT64 frequency=0;hr(host.queue->GetTimestampFrequency(&frequency));need(frequency>0,"commit timing native GPU frequency");
    constexpr unsigned warmBatches=4,batches=9,repeats=16;const auto staging=owner->stagingBytes,auxiliary=owner->AuxiliaryBytes();
    const auto providerCalls=FfxApiProxy::dispatches;
    for(uint32_t mode=0;mode<2;++mode)for(float strength:{0.f,.5f,1.f})
    {
        native.flag(mode);std::vector<double> samples;
        for(unsigned batch=0;batch<warmBatches+batches;++batch)
        {
            auto lease=MakeOwnedShared<DispatchLease>();lease->context=owner;lease->slot=slot;
            need(ResTrack_Dx12::RetainComputeDispatch(host.device.Get(),host.list.Get(),lease),"commit benchmark retains actual context/pipeline/staging/flag GPU lifetime");
            host.list->EndQuery(query.Get(),D3D12_QUERY_TYPE_TIMESTAMP,0);
            for(unsigned repeat=0;repeat<repeats;++repeat)owner->Commit(host.list.Get(),*slot,scene.spec(),scene.diff(),SignalEncoding::Rgb,constants,strength);
            host.list->EndQuery(query.Get(),D3D12_QUERY_TYPE_TIMESTAMP,1);host.list->ResolveQueryData(query.Get(),D3D12_QUERY_TYPE_TIMESTAMP,0,2,timing.Get(),0);
            host.submit();UINT64* ticks=nullptr;hr(timing->Map(0,nullptr,reinterpret_cast<void**>(&ticks)));need(ticks[1]>=ticks[0],"commit timestamp pair ordered");
            const double ms=double(ticks[1]-ticks[0])*1000./double(frequency)/repeats;timing->Unmap(0,nullptr);if(batch>=warmBatches)samples.push_back(ms);host.reset();
            need(owner->stagingBytes==staging&&owner->AuxiliaryBytes()==auxiliary&&owner->slots.size()==4,"commit benchmark GPU allocation remains fixed after warmup");
        }
        auto sorted=samples;std::sort(sorted.begin(),sorted.end());const double mean=std::accumulate(samples.begin(),samples.end(),0.0)/samples.size();
        std::cout<<"commit_timing size="<<width<<'x'<<height<<" encoding="<<(mode?"YCoCg":"RGB")<<" strength="<<strength<<" median_ms="<<sorted[sorted.size()/2]
            <<" mean_ms="<<mean<<" batches="<<batches<<" repeats="<<repeats<<" warm_batches="<<warmBatches<<" allocation_growth=0 scope=native_root_flag_capture_plus_two_lobe_Commit_only samples_ms=";
        for(double value:samples)std::cout<<value<<',';std::cout<<'\n';
    }
    need(FfxApiProxy::dispatches==providerCalls&&owner->handle==nullptr,"commit-only cost contains zero provider dispatch/model work");
}
int main(int argc,char** argv) try
{
    std::cout.setf(std::ios::unitbuf);
    commitRootLayoutChecks();
    settingsValidationChecks();
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
    if(mode=="--commit-timing") {nativeBlendCommitTiming(host,1505,847);nativeBlendCommitTiming(host,2560,1440);hr(host.list->Close());RecordedComputeLease::Poll();host.checkDebug();
        need(FfxApiProxy::creates==0 && FfxApiProxy::dispatches==0,"commit-only benchmark uses no provider context");
        std::cout<<"PASS checks="<<checks<<" mode=--commit-timing provider_dispatches=0 debug_errors=0 debug_warnings=0\n";return 0;}
    std::cout<<"stage history checks\n";historyChecks(host);
    std::cout<<"stage deferred lifetime checks\n";lifecycleChecks(host);
    std::cout<<"stage minimum-size fail-closed check\n";minimumChecks(host);
    std::cout<<"stage encoding/CBV fail-closed checks\n";encodingValidationChecks(host);
    std::cout<<"stage native Consumer codec checks\n";encodingChecks(host);
    std::cout<<"stage ignored native specular coefficient policy checks\n";nativeBlendChecks(host);
    std::cout<<"stage volatile native descriptor table checks\n";tableEncodingChecks(host);
    std::cout<<"stage discarded volatile table checks\n";tableDiscardChecks(host);
    if(mode=="--mock")providerChecks(host);
    if(mode=="--mock"){nativeBlendFailureChecks(host);partialFailureChecks(host);cancelledCommitChecks(host);encodedFailureChecks(host);tableFailureChecks(host);sameBatchSnapshotChecks(host);nearestHalfEdgeChecks(host);}
    if(mode=="--mock")stagingPoolChecks(host);
    std::cout<<"stage coherent runtime AMD settings checks\n";runtimeSettingsChecks(host);
    std::cout<<"stage native AMD debug view and presentation checks\n";
    nativeDebugChecks(host,mode=="--real" && argc==4?std::filesystem::path(argv[3])/"native_debug":std::filesystem::path{});
    if(mode=="--real")
    {
        need(argc==4,"real test needs capture input/output directories");std::filesystem::path output=argv[3];std::filesystem::create_directories(output);
        discardedRecordingChecks(host,output);
        realLoop(host,1505,847,24,{},output,"synthetic_1505x847");
        realLoop(host,1505,847,24,argv[2],output,"da9f_1505x847");
        realLoop(host,2560,1440,16,{},output,"synthetic_2560x1440");
        realLoop(host,1505,847,24,{},output,"native_table_1505x847",true);
        realLoop(host,2560,1440,16,{},output,"native_table_2560x1440",true);
        realLoop(host,1505,847,24,{},output,"native_debug_1505x847_to_2560x1440",false,true);
        realLoop(host,2560,1440,16,{},output,"native_debug_2560x1440",false,true);
    }
    RecordedComputeLease::Poll();need(FfxApiProxy::live.empty(),"all completed contexts retired");
    need(FfxApiProxy::creates==FfxApiProxy::destroys,"exact context create/destroy balance");host.checkDebug();
    need(FfxApiProxy::badCreateChains==0,"all deferred create descriptor chains survive through destroy");
    need(FfxApiProxy::badDefaults==0 && FfxApiProxy::badConfigureLayouts==0,"every original AMD default and runtime configure descriptor remains valid");
    std::cout<<"PASS checks="<<checks<<" mode="<<mode<<" creates="<<FfxApiProxy::creates<<" destroys="<<FfxApiProxy::destroys
        <<" dispatches="<<FfxApiProxy::dispatches<<" defaults="<<FfxApiProxy::defaults<<" configures="<<FfxApiProxy::configures
        <<" native_debug_dispatches="<<FfxApiProxy::nativeDebugDispatches
        <<" debug_errors=0\n";return 0;
}
catch(const std::exception& error){std::cerr<<"FAIL after checks="<<checks<<": "<<error.what()<<'\n';return 1;}
