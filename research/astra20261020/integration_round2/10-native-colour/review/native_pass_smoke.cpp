// Direct D3D12 class smoke test, separate from the generic shader-chain runner.
// This translation unit includes the ACTUAL pass implementation to make the
// existing single-source MSVC helper sufficient. Never link that .cpp twice.
// Windows source is supplied for local execution; Linux source inspection is
// not a Windows compile, GPU validation or image-quality result.
#define NOMINMAX
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <d3d12.h>
#include <d3d12sdklayers.h>
#include <dxgi1_6.h>
#include <wrl/client.h>
#include <algorithm>
#include <array>
#include <atomic>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <memory>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>
#include "../native/NativeColourPass_Dx12.cpp"

namespace Smoke
{
using Microsoft::WRL::ComPtr;
using NativeColour::Decision;
using NativeColour::NativeColourPass;
constexpr UINT ActiveW = 13, ActiveH = 9;
constexpr D3D12_RESOURCE_STATES ReadState = D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
uint64_t SubmittedBatches=0;
bool NativeCommandsRecorded=false;

void Require(bool value, const char* what)
{
    if (!value) throw std::runtime_error(what);
}
void Hr(HRESULT result, const char* what)
{
    if (FAILED(result)) throw std::runtime_error(std::string(what) + " HRESULT=" + std::to_string(uint32_t(result)));
}
std::vector<char> File(const char* path)
{
    std::ifstream in(path, std::ios::binary | std::ios::ate);
    Require(bool(in), "Shader file cannot be opened");
    const auto size = in.tellg();
    Require(size > 0, "Shader bytecode is empty");
    std::vector<char> value(static_cast<size_t>(size));
    in.seekg(0); in.read(value.data(), std::streamsize(value.size()));
    Require(bool(in), "Shader file read failed");
    return value;
}
std::string Escape(const std::string& value)
{
    std::string result;
    for (unsigned char c : value)
    {
        if (c == '"' || c == '\\') { result += '\\'; result += char(c); }
        else if (c == '\n') result += "\\n";
        else if (c >= 32) result += char(c);
    }
    return result;
}

struct Device
{
    ComPtr<ID3D12Device> device;
    ComPtr<ID3D12InfoQueue> info;
    ComPtr<ID3D12CommandQueue> queue;
    ComPtr<ID3D12CommandAllocator> allocator;
    ComPtr<ID3D12GraphicsCommandList> list;
    ComPtr<ID3D12Fence> fence;
    HANDLE event = nullptr;
    UINT64 value = 0;
    std::string adapter;
    explicit Device(bool warp)
    {
        ComPtr<ID3D12Debug> debug;
        Hr(D3D12GetDebugInterface(IID_PPV_ARGS(&debug)), "D3D12 debug layer required; install Graphics Tools");
        debug->EnableDebugLayer();
        ComPtr<IDXGIFactory6> factory;
        Hr(CreateDXGIFactory2(DXGI_CREATE_FACTORY_DEBUG, IID_PPV_ARGS(&factory)), "Create factory");
        ComPtr<IDXGIAdapter1> gpu;
        if (warp) Hr(factory->EnumWarpAdapter(IID_PPV_ARGS(&gpu)), "Select WARP");
        else Hr(factory->EnumAdapterByGpuPreference(0, DXGI_GPU_PREFERENCE_HIGH_PERFORMANCE,
                                                    IID_PPV_ARGS(&gpu)), "Select hardware adapter");
        DXGI_ADAPTER_DESC1 desc {};
        Hr(gpu->GetDesc1(&desc), "Adapter description");
        char name[512] {};
        WideCharToMultiByte(CP_UTF8, 0, desc.Description, -1, name, sizeof(name), nullptr, nullptr);
        adapter = name;
        Hr(D3D12CreateDevice(gpu.Get(), D3D_FEATURE_LEVEL_12_0, IID_PPV_ARGS(&device)), "Create device");
        Hr(device.As(&info), "Info queue");
        D3D12_COMMAND_QUEUE_DESC q {};
        q.Type = D3D12_COMMAND_LIST_TYPE_DIRECT;
        Hr(device->CreateCommandQueue(&q, IID_PPV_ARGS(&queue)), "Create queue");
        Hr(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT, IID_PPV_ARGS(&allocator)), "Create allocator");
        Hr(device->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_DIRECT, allocator.Get(), nullptr,
                                     IID_PPV_ARGS(&list)), "Create command list");
        Hr(device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&fence)), "Create fence");
        event = CreateEventW(nullptr, FALSE, FALSE, nullptr);
        Require(event != nullptr, "Create fence event");
    }
    ~Device() { if (event) CloseHandle(event); }
    void SubmitAndWait()
    {
        Hr(list->Close(), "Close command list");
        ID3D12CommandList* lists[] {list.Get()};
        queue->ExecuteCommandLists(1, lists);
        ++SubmittedBatches;
        Hr(queue->Signal(fence.Get(), ++value), "Signal fence");
        Hr(fence->SetEventOnCompletion(value, event), "Set fence event");
        Require(WaitForSingleObject(event, 30000) == WAIT_OBJECT_0, "GPU completion timed out");
        Hr(device->GetDeviceRemovedReason(), "Device removed after execution");
        Hr(allocator->Reset(), "Reset allocator");
        Hr(list->Reset(allocator.Get(), nullptr), "Reset command list");
    }
    void Transition(ID3D12Resource* resource, D3D12_RESOURCE_STATES before, D3D12_RESOURCE_STATES after)
    {
        if (before == after) return;
        D3D12_RESOURCE_BARRIER b {};
        b.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        b.Transition = {resource, D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES, before, after};
        list->ResourceBarrier(1, &b);
    }
    ComPtr<ID3D12Resource> Buffer(UINT64 bytes, D3D12_HEAP_TYPE type)
    {
        D3D12_HEAP_PROPERTIES heap {}; heap.Type = type;
        D3D12_RESOURCE_DESC d {};
        d.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER; d.Width = bytes;
        d.Height = 1; d.DepthOrArraySize = 1; d.MipLevels = 1;
        d.SampleDesc.Count = 1; d.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        const auto state = type == D3D12_HEAP_TYPE_UPLOAD ? D3D12_RESOURCE_STATE_GENERIC_READ :
                                                                        D3D12_RESOURCE_STATE_COPY_DEST;
        ComPtr<ID3D12Resource> resource;
        Hr(device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &d, state, nullptr,
                                          IID_PPV_ARGS(&resource)), "Create transfer buffer");
        return resource;
    }
    std::array<UINT64,2> ValidationMessages() const
    {
        std::array<UINT64,2> counts {};
        for (UINT64 i=0; i<info->GetNumStoredMessages(); ++i)
        {
            SIZE_T size = 0;
            Hr(info->GetMessage(i, nullptr, &size), "Message size");
            std::vector<char> bytes(size);
            auto* message = reinterpret_cast<D3D12_MESSAGE*>(bytes.data());
            Hr(info->GetMessage(i, message, &size), "Message");
            if (message->Severity == D3D12_MESSAGE_SEVERITY_ERROR ||
                message->Severity == D3D12_MESSAGE_SEVERITY_CORRUPTION) ++counts[0];
            if (message->Severity == D3D12_MESSAGE_SEVERITY_WARNING) ++counts[1];
            if (message->Severity <= D3D12_MESSAGE_SEVERITY_WARNING)
                std::cerr << message->pDescription << '\n';
        }
        return counts;
    }
};

struct Image
{
    ComPtr<ID3D12Resource> resource, upload;
    UINT width = 0, height = 0, pixelBytes = 0;
    std::vector<uint8_t> tight;
};
Image Upload(Device& d, UINT w, UINT h, UINT bpp, DXGI_FORMAT format, const std::vector<uint8_t>& bytes)
{
    Require(bytes.size() == size_t(w)*h*bpp, "Upload dimensions mismatch");
    Image out; out.width=w; out.height=h; out.pixelBytes=bpp; out.tight=bytes;
    D3D12_RESOURCE_DESC desc {};
    desc.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D; desc.Width=w; desc.Height=h;
    desc.DepthOrArraySize=1; desc.MipLevels=1; desc.Format=format; desc.SampleDesc.Count=1;
    D3D12_HEAP_PROPERTIES heap {}; heap.Type=D3D12_HEAP_TYPE_DEFAULT;
    Hr(d.device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &desc, D3D12_RESOURCE_STATE_COPY_DEST,
                                        nullptr, IID_PPV_ARGS(&out.resource)), "Create fixture texture");
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT foot {};
    UINT64 size=0;
    d.device->GetCopyableFootprints(&desc,0,1,512,&foot,nullptr,nullptr,&size);
    size = std::max(size, foot.Offset+UINT64(foot.Footprint.RowPitch)*h)+512;
    out.upload=d.Buffer(size,D3D12_HEAP_TYPE_UPLOAD);
    void* mapped=nullptr;
    const D3D12_RANGE noRead {0,0};
    Hr(out.upload->Map(0,&noRead,&mapped),"Map upload");
    std::memset(mapped,0xA7,size_t(size));
    for (UINT y=0;y<h;++y)
        std::memcpy(static_cast<uint8_t*>(mapped)+foot.Offset+size_t(y)*foot.Footprint.RowPitch,
                    bytes.data()+size_t(y)*w*bpp,size_t(w)*bpp);
    out.upload->Unmap(0,nullptr);
    D3D12_TEXTURE_COPY_LOCATION dst {}, src {};
    dst.pResource=out.resource.Get(); dst.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
    src.pResource=out.upload.Get(); src.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT; src.PlacedFootprint=foot;
    d.list->CopyTextureRegion(&dst,0,0,0,&src,nullptr);
    d.Transition(out.resource.Get(),D3D12_RESOURCE_STATE_COPY_DEST,ReadState);
    return out;
}
template<class T> std::vector<uint8_t> Bytes(const std::vector<T>& words)
{
    std::vector<uint8_t> bytes(words.size()*sizeof(T));
    std::memcpy(bytes.data(),words.data(),bytes.size()); return bytes;
}
std::vector<uint8_t> Signal(UINT w,UINT h,bool source,bool selected)
{
    std::vector<uint16_t> words(size_t(w)*h*4);
    const std::array<uint16_t,5> alpha {0x0000,0x8000,0x7e11,0xfc01,0x3c00};
    for(UINT y=0;y<h;++y) for(UINT x=0;x<w;++x)
    {
        auto* p=words.data()+(size_t(y)*w+x)*4;
        p[0]=source?0x3a66:0x3c00; p[1]=0x3c00; p[2]=source?0x3ccc:0x3c00;
        p[3]=alpha[(x+3*y)%alpha.size()];
        if(source&&x==6&&y==3) p[0]=0x7e11;
        if(!source&&x==7&&y==3) p[0]=0x7c00;
        if(selected&&x==2&&y==1) p[0]^=1u; // one-ULP selected RGB veto
        if(selected&&x==3&&y==2) p[3]^=1u; // opaque alpha-only veto
    }
    return Bytes(words);
}

struct Family
{
    std::atomic<uint64_t> bytes {0}, peak {0};
    std::atomic<uint32_t> slots {0};
};
NativeColour::Budget Budget(const std::shared_ptr<Family>& owner)
{
    return {owner,&owner->bytes,&owner->peak,&owner->slots,512ull*1024*1024,8};
}
NativeColour::Texture View(const Image& image,const NativeColour::Identity& identity,
                          const std::shared_ptr<void>& owner)
{
    return {image.resource.Get(),owner,identity,ReadState};
}
struct Fixtures
{
    Image source,raw,selected,depth,normal,authority,support;
    NativeColour::Inputs inputs;
    std::shared_ptr<void> owner=std::make_shared<int>(42);
    Fixtures(Device& d,bool aliasRawSelected,bool unknownPixels,uint64_t recording)
    {
        const UINT sourceWidth=aliasRawSelected?21u:35u;
        source=Upload(d,sourceWidth,14,8,DXGI_FORMAT_R16G16B16A16_FLOAT,Signal(sourceWidth,14,true,false));
        raw=Upload(d,19,13,8,DXGI_FORMAT_R16G16B16A16_FLOAT,Signal(19,13,false,false));
        selected=aliasRawSelected?raw:Upload(d,69,12,8,DXGI_FORMAT_R16G16B16A16_FLOAT,Signal(69,12,false,true));
        std::vector<float> z(23*15,10.0f); z[3*23+8]=std::numeric_limits<float>::quiet_NaN();
        depth=Upload(d,23,15,4,DXGI_FORMAT_R32_FLOAT,Bytes(z));
        normal=Upload(d,22,16,4,DXGI_FORMAT_R10G10B10A2_UNORM,
                      Bytes(std::vector<uint32_t>(22*16,512u|(512u<<10)|(600u<<20))));
        std::vector<uint32_t> a(21*13,1),s(18*12,1);
        if(unknownPixels) { a[3*21+2]=0; a[3*21+3]=2; s[3*18+4]=0; s[3*18+5]=2; }
        authority=Upload(d,21,13,4,DXGI_FORMAT_R32_UINT,Bytes(a));
        support=Upload(d,18,12,4,DXGI_FORMAT_R32_UINT,Bytes(s));
        NativeColour::Identity id;
        id.frame=23; id.generation=7; id.recording=recording;
        id.renderWidth=64; id.renderHeight=64; id.cropX=5; id.cropY=7;
        id.activeWidth=ActiveW; id.activeHeight=ActiveH;
        inputs.frame.identity=id;
        inputs.evidence={id,NativeColour::EvidenceKind::SyntheticFixture,NativeColour::EvidenceKind::SyntheticFixture,
                         NativeColour::SourceStage::PreProviderPhysicalSnapshot,NativeColour::EstimatorVersion,3,1};
        inputs.source=View(source,id,owner); inputs.rawRR=View(raw,id,owner);
        inputs.selected=View(selected,id,owner); inputs.depth=View(depth,id,owner);
        inputs.normalRoughness=View(normal,id,owner); inputs.authority=View(authority,id,owner);
        inputs.support=View(support,id,owner);
        d.SubmitAndWait(); // Complete fixture upload before testing Prepare/Record.
    }
};

struct Readback
{
    ComPtr<ID3D12Resource> buffer;
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint {};
    UINT64 size=0;
    UINT width=0,height=0,bpp=0;
    std::vector<uint8_t> Read() const
    {
        void* mapped=nullptr;
        const D3D12_RANGE range {0,size_t(size)};
        Hr(buffer->Map(0,&range,&mapped),"Map readback");
        std::vector<uint8_t> result(static_cast<uint8_t*>(mapped),static_cast<uint8_t*>(mapped)+size_t(size));
        const D3D12_RANGE noWrite {0,0}; buffer->Unmap(0,&noWrite); return result;
    }
};
Readback ReadTexture(Device& d,ID3D12Resource* source,D3D12_RESOURCE_STATES state,UINT bpp)
{
    Readback out; const auto desc=source->GetDesc();
    out.width=UINT(desc.Width); out.height=desc.Height; out.bpp=bpp;
    d.device->GetCopyableFootprints(&desc,0,1,0,&out.footprint,nullptr,nullptr,&out.size);
    out.size=std::max(out.size,UINT64(out.footprint.Footprint.RowPitch)*out.height);
    out.buffer=d.Buffer(out.size,D3D12_HEAP_TYPE_READBACK);
    d.Transition(source,state,D3D12_RESOURCE_STATE_COPY_SOURCE);
    D3D12_TEXTURE_COPY_LOCATION dst {},src {};
    dst.pResource=out.buffer.Get(); dst.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT; dst.PlacedFootprint=out.footprint;
    src.pResource=source; src.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
    d.list->CopyTextureRegion(&dst,0,0,0,&src,nullptr);
    d.Transition(source,D3D12_RESOURCE_STATE_COPY_SOURCE,state);
    return out;
}
Readback ReadPacked(Device& d,const NativeColourPass::Prepared& p)
{
    Readback out; out.size=p.memory.packed[3].bytes;
    out.buffer=d.Buffer(out.size,D3D12_HEAP_TYPE_READBACK);
    d.Transition(p.packedOutput,D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_COPY_SOURCE);
    d.list->CopyBufferRegion(out.buffer.Get(),0,p.packedOutput,0,out.size);
    d.Transition(p.packedOutput,D3D12_RESOURCE_STATE_COPY_SOURCE,D3D12_RESOURCE_STATE_COPY_DEST);
    return out;
}
uint16_t Word(const uint8_t* value) { uint16_t out; std::memcpy(&out,value,2); return out; }

struct Case {std::string name; uint64_t changed=0,charge=0;};
Case Active(Device& d,D3D12_SHADER_BYTECODE shader,bool aliasRawSelected,bool linear,uint64_t recording)
{
    Fixtures f(d,aliasRawSelected,true,recording);
    auto family=std::make_shared<Family>();
    const auto budget=Budget(family);
    NativeColour::Config config; config.enabled=true; config.acknowledgeRejectedResearch=true;
    if(linear) config.representation=NativeColour::Representation::Linear;
    NativeColourPass::Prepared p;
    Require(NativeColourPass::Prepare(d.device.Get(),d.list.Get(),f.inputs,config,budget,shader,p)==Decision::Ready,
            "Active class preparation failed");
    Require(p.output&&p.packedOutput&&p.diagnostic,"Prepared resources missing");
    Require(family->bytes==p.memory.budgetChargeBytes&&family->bytes>0&&family->slots==1,
            "Budget does not retain exact charge");
    {
        const auto originalOwner=p.owner;
        Require(NativeColourPass::Prepare(d.device.Get(),d.list.Get(),f.inputs,config,budget,shader,p)==Decision::InvalidRecording,
                "Prepare overwrote a live recording");
        Require(p.owner==originalOwner&&p.decision==Decision::Ready,
                "Rejected second Prepare damaged the original recording");
    }
    const auto layout=p.memory.packed[3];
    if(!aliasRawSelected)
        Require(p.memory.packed[0].rowPitch==512&&p.memory.packed[1].rowPitch==256&&
                p.memory.packed[2].rowPitch==768,
                "Separate-selected fixture must exercise distinct native 512/256/768 pitches");
    Require(layout.bytes==p.memory.packed[2].bytes&&layout.rowPitch==p.memory.packed[2].rowPitch&&
            layout.offset==p.memory.packed[2].offset,"Selected/output full-buffer layouts mismatch");
    Require(!NativeColourPass::CanRecord(d.list.Get(),recording+1,p),"Wrong recording accepted");
    Require(!NativeColourPass::Record(d.list.Get(),recording+1,p),"Wrong recording emitted pass");
    Require(NativeColourPass::CanRecord(d.list.Get(),recording,p),"Prepared pass not recordable");
    Require(NativeColourPass::Record(d.list.Get(),recording,p),"First class Record failed");
    NativeCommandsRecorded=true;
    Require(!NativeColourPass::Record(d.list.Get(),recording,p),"Repeated class Record accepted");
    const auto packed=ReadPacked(d,p);
    const auto texture=ReadTexture(d,p.output,D3D12_RESOURCE_STATE_UNORDERED_ACCESS,8);
    const auto diagnostic=ReadTexture(d,p.diagnostic,D3D12_RESOURCE_STATE_UNORDERED_ACCESS,16);
    // Reading every input from its DECLARED original state also lets the debug
    // layer falsify a missing state restoration (including raw==selected alias).
    std::vector<std::pair<const Image*,Readback>> originals;
    std::set<ID3D12Resource*> seen;
    for(const Image* image:{&f.source,&f.raw,&f.selected,&f.depth,&f.normal,&f.authority,&f.support})
        if(seen.insert(image->resource.Get()).second)
            originals.push_back({image,ReadTexture(d,image->resource.Get(),ReadState,image->pixelBytes)});
    auto held=p;
    const uint64_t charge=p.memory.budgetChargeBytes;
    p={};
    Require(family->bytes==charge&&family->slots==1,"Owner copy failed to retain recording before submission");
    d.SubmitAndWait();
    const auto actual=packed.Read(),textureBytes=texture.Read(),diagnosticBytes=diagnostic.Read();
    std::vector<uint8_t> expected(size_t(layout.bytes),0xCD),mayChange(expected.size(),0);
    uint64_t changed=0;
    for(UINT y=0;y<f.selected.height;++y) for(UINT x=0;x<f.selected.width;++x)
    {
        const auto address=size_t(layout.offset)+size_t(y)*layout.rowPitch+size_t(x)*8;
        const auto selected=f.selected.tight.data()+(size_t(y)*f.selected.width+x)*8;
        std::memcpy(expected.data()+address,selected,8);
        bool eligible=x<ActiveW&&y<ActiveH;
        if(eligible)
        {
            const auto raw=f.raw.tight.data()+(size_t(y)*f.raw.width+x)*8;
            eligible=std::memcmp(raw,selected,8)==0 && !(y==3&&(x==2||x==3||x==4||x==5||x==6||x==7||x==8));
        }
        if(eligible) std::fill(mayChange.begin()+address,mayChange.begin()+address+6,1);
        Require(std::memcmp(actual.data()+address+6,selected+6,2)==0,"Alpha word changed");
        if(!eligible) Require(std::memcmp(actual.data()+address,selected,8)==0,"Protected/invalid/inactive pixel changed");
        else
        {
            const bool corrected=std::memcmp(actual.data()+address,selected,6)!=0;
            // Every admitted centre in this constant-chroma fixture has ample
            // valid support and a deliberately large correction. A swapped
            // input pitch must not pass merely by correcting the first row.
            Require(corrected,"Eligible fixture pixel did not correct (pitch/binding/OFF canary)");
            changed+=corrected;
            for(UINT channel=0;channel<3;++channel)
                Require((Word(actual.data()+address+2*channel)&0x7c00)!=0x7c00,"Active RGB became NaN/Inf");
        }
        const auto textureAddress=size_t(texture.footprint.Offset)+size_t(y)*texture.footprint.Footprint.RowPitch+x*8;
        Require(std::memcmp(actual.data()+address,textureBytes.data()+textureAddress,8)==0,
                "Full output texture differs from packed output");
        if(x>=ActiveW||y>=ActiveH)
        {
            const auto diagAddress=size_t(diagnostic.footprint.Offset)+size_t(y)*diagnostic.footprint.Footprint.RowPitch+x*16;
            const std::array<uint8_t,16> zero {};
            Require(std::memcmp(diagnosticBytes.data()+diagAddress,zero.data(),16)==0,"Inactive diagnostic not initialized");
        }
    }
    for(size_t i=0;i<actual.size();++i)
        if(!mayChange[i]) Require(actual[i]==expected[i],"Packed guard/padding/protected byte differs from prefill");
    Require(changed>0,"Active canary is vacuous (forced-OFF mutant)");
    for(const auto& [image,readback]:originals)
    {
        const auto bytes=readback.Read();
        for(UINT y=0;y<image->height;++y)
            Require(std::memcmp(bytes.data()+readback.footprint.Offset+size_t(y)*readback.footprint.Footprint.RowPitch,
                                image->tight.data()+size_t(y)*image->width*image->pixelBytes,
                                size_t(image->width)*image->pixelBytes)==0,"Input texture was modified");
    }
    held={};
    Require(family->bytes==0&&family->slots==0,"Budget did not retire after completed recording release");
    return {std::string(linear?"linear":"log")+(aliasRawSelected?"_raw_selected_alias":"_separate_selected"),changed,charge};
}

std::vector<Case> Rejections(Device& d,D3D12_SHADER_BYTECODE shader)
{
    Fixtures f(d,false,true,101);
    auto family=std::make_shared<Family>(); auto budget=Budget(family);
    NativeColour::Config config; config.enabled=true; config.acknowledgeRejectedResearch=true;
    std::vector<Case> cases;
    auto check=[&](const char* name,const NativeColour::Inputs& input,const NativeColour::Config& cfg,
                  const NativeColour::Budget& b,Decision expected)
    {
        NativeColourPass::Prepared p;
        const auto decision=NativeColourPass::Prepare(d.device.Get(),d.list.Get(),input,cfg,b,shader,p);
        Require(decision==expected,"Unexpected native preparation rejection code");
        Require(!p&&!p.output&&!p.packedOutput&&!p.diagnostic,"Rejected pass published resources");
        Require(family->bytes==0&&family->slots==0,"Rejected pass leaked family reservation");
        Require(!NativeColourPass::CanRecord(d.list.Get(),101,p),"Rejected pass became recordable");
        cases.push_back({name});
    };
    auto cfg=config; cfg.enabled=false; check("off",f.inputs,cfg,budget,Decision::Off);
    cfg=config; cfg.acknowledgeRejectedResearch=false; check("research_ack_absent",f.inputs,cfg,budget,Decision::Off);
    cfg=config; cfg.strength=0; check("strength_zero",f.inputs,cfg,budget,Decision::ZeroStrength);
    cfg=config; cfg.spatialSigma=std::numeric_limits<float>::quiet_NaN();
    check("invalid_config_nan",f.inputs,cfg,budget,Decision::InvalidConfig);
    cfg=config; cfg.guideChromaRadius=std::numeric_limits<float>::denorm_min();
    check("invalid_config_subnormal",f.inputs,cfg,budget,Decision::InvalidConfig);
    auto input=f.inputs; input.frame.reset=true; check("reset",input,config,budget,Decision::ResetOrResize);
    input=f.inputs; input.frame.resized=true; check("resize",input,config,budget,Decision::ResetOrResize);
    input=f.inputs; input.evidence.authority=NativeColour::EvidenceKind::Unknown;
    check("unknown_authority",input,config,budget,Decision::UnknownAuthority);
    input=f.inputs; input.evidence.support=NativeColour::EvidenceKind::Unknown;
    check("unknown_support",input,config,budget,Decision::UnknownSupport);
    input=f.inputs; input.evidence.radius=4; check("stale_support_radius",input,config,budget,Decision::UnknownSupport);
    input=f.inputs; ++input.evidence.identity.generation; check("stale_generation",input,config,budget,Decision::InvalidIdentity);
    input=f.inputs; input.evidence.sourceStage=NativeColour::SourceStage::Unknown;
    check("uncertified_source_snapshot",input,config,budget,Decision::UnsupportedSource);
    input=f.inputs; input.source.owner.reset();
    check("missing_source_graph_owner",input,config,budget,Decision::InvalidNativeResource);
    input=f.inputs; ++input.rawRR.identity.frame;
    check("mismatched_resource_identity",input,config,budget,Decision::InvalidNativeResource);
    input=f.inputs; input.authority.resource=f.depth.resource.Get();
    check("wrong_authority_native_format",input,config,budget,Decision::InvalidNativeResource);
    input=f.inputs; input.source.state=D3D12_RESOURCE_STATE_COMMON;
    check("unknown_input_resource_state",input,config,budget,Decision::InvalidNativeResource);
    input=f.inputs; input.selected=input.rawRR; input.selected.state=D3D12_RESOURCE_STATE_COPY_SOURCE;
    check("aliased_resource_conflicting_states",input,config,budget,Decision::InvalidNativeResource);
    input=f.inputs; input.source=input.rawRR;
    check("source_snapshot_aliases_mutable_raw",input,config,budget,Decision::InvalidNativeResource);
    input=f.inputs; input.source=input.selected;
    check("source_snapshot_aliases_mutable_selected",input,config,budget,Decision::InvalidNativeResource);
    auto missing=budget; missing.owner.reset();
    check("missing_shared_budget_owner",f.inputs,config,missing,Decision::MissingBudget);
    auto aliasedCounters=budget; aliasedCounters.peakBytes=aliasedCounters.bytes;
    check("aliased_live_and_peak_budget_counters",f.inputs,config,aliasedCounters,Decision::MissingBudget);
    auto tiny=budget; tiny.byteLimit=1; check("byte_budget_rejection",f.inputs,config,tiny,Decision::BudgetExceeded);
    // Completing an empty list proves these rejected preparations were callable
    // together; exact zero-command behavior is additionally reviewed in source.
    d.SubmitAndWait();
    return cases;
}
} // namespace Smoke

int main(int argc,char** argv)
{
    const char* report=argc>=3?argv[2]:nullptr;
    try
    {
        Smoke::Require(argc>=3,"Usage: native_pass_smoke.exe <shader.cso> <report.json> [--warp]");
        const bool warp=argc>=4&&std::string(argv[3])=="--warp";
        Smoke::Device device(warp);
        const auto shader=Smoke::File(argv[1]);
        const D3D12_SHADER_BYTECODE bytecode {shader.data(),shader.size()};
        auto cases=Smoke::Rejections(device,bytecode);
        cases.push_back(Smoke::Active(device,bytecode,false,false,201));
        cases.push_back(Smoke::Active(device,bytecode,true,true,202));
        const auto counters=device.ValidationMessages();
        Smoke::Require(counters[0]==0&&counters[1]==0,"D3D12 debug layer emitted errors or warnings");
        std::ostringstream out;
        out<<"{\n  \"schema\": \"native-colour-direct-pass-smoke-v1\",\n"
           <<"  \"adapter\": \""<<Smoke::Escape(device.adapter)<<"\",\n"
           <<"  \"warp\": "<<(warp?"true":"false")<<",\n  \"debug_layer\": true,\n"
           <<"  \"validation_errors\": "<<counters[0]<<",\n  \"validation_warnings\": "<<counters[1]<<",\n"
           <<"  \"gpu_executed\": true,\n  \"quality_accepted\": false,\n"
           <<"  \"submitted_batches\": "<<Smoke::SubmittedBatches<<",\n  \"native_commands_recorded\": true,\n"
           <<"  \"scope\": \"Actual D3D12 class allocation/copies/states/lease budget; synthetic inputs only\",\n"
           <<"  \"cases\": [\n";
        for(size_t i=0;i<cases.size();++i)
            out<<"    {\"name\": \""<<cases[i].name<<"\", \"passed\": true, \"changed_pixels\": "
               <<cases[i].changed<<", \"budget_charge_bytes\": "<<cases[i].charge<<"}"<<(i+1<cases.size()?",":"")<<'\n';
        out<<"  ],\n  \"passed\": true\n}\n";
        std::ofstream(report)<<out.str(); std::cout<<out.str(); return 0;
    }
    catch(const std::exception& error)
    {
        std::cerr<<error.what()<<'\n';
        if(report) std::ofstream(report)<<"{\"passed\": false, \"quality_accepted\": false, \"gpu_executed\": "
                                        <<(Smoke::SubmittedBatches?"true":"false")<<", \"native_commands_recorded\": "
                                        <<(Smoke::NativeCommandsRecorded?"true":"false")<<", \"error\": \""
                                        <<Smoke::Escape(error.what())<<"\"}\n";
        return 1;
    }
}
