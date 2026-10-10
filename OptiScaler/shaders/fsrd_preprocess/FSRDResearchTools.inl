// Included after ComputeState: uses the renderer's existing dispatch leases.
#include <future>
#include <fstream>
#include <chrono>
#include "FSRDResearchTools.h"
#include "precompile/FSRDProbeInputs_Shader.h"
#include "precompile/FSRDReference_Shader.h"
#include "precompile/FSRDLeak_Shader.h"

namespace FSRDResearch
{
namespace
{
using Json = nlohmann::json;
struct Shared
{
    std::mutex mutex;
    Status status;
    uint32_t request = 0;
    bool stop = false;
    std::atomic<bool> wanted {false}, reference {false};
};
Shared& Global() { static Shared shared; return shared; }
void Message(const std::string& text, bool busy)
{
    auto& g=Global(); std::scoped_lock lock(g.mutex);
    g.status.message=text; g.status.busy=busy;
    if(!busy) { g.wanted=false; g.reference=false; g.request=0; g.stop=false; }
}
std::pair<uint32_t,uint32_t> Format(DXGI_FORMAT f)
{
    switch(f)
    {
    case DXGI_FORMAT_R32G32B32A32_FLOAT: return {16,4};
    case DXGI_FORMAT_R32G32B32_FLOAT: return {12,3};
    case DXGI_FORMAT_R16G16B16A16_FLOAT: case DXGI_FORMAT_R16G16B16A16_UNORM:
    case DXGI_FORMAT_R16G16B16A16_SNORM: return {8,4};
    case DXGI_FORMAT_R32G32_FLOAT: return {8,2};
    case DXGI_FORMAT_R16G16_FLOAT: case DXGI_FORMAT_R16G16_UNORM: case DXGI_FORMAT_R16G16_SNORM: return {4,2};
    case DXGI_FORMAT_R10G10B10A2_UNORM: case DXGI_FORMAT_R8G8B8A8_UNORM:
    case DXGI_FORMAT_R8G8B8A8_UNORM_SRGB: case DXGI_FORMAT_B8G8R8A8_UNORM: return {4,4};
    case DXGI_FORMAT_R11G11B10_FLOAT: return {4,3};
    case DXGI_FORMAT_R32_FLOAT: case DXGI_FORMAT_R24_UNORM_X8_TYPELESS: return {4,1};
    case DXGI_FORMAT_R16_FLOAT: case DXGI_FORMAT_R16_UNORM: case DXGI_FORMAT_R16_SNORM: return {2,1};
    case DXGI_FORMAT_R8_UNORM: case DXGI_FORMAT_R8_SNORM: return {1,1};
    case DXGI_FORMAT_R8G8_UNORM: case DXGI_FORMAT_R8G8_SNORM: return {2,2};
    default: return {};
    }
}
Row Describe(ID3D12Device* dev,const Input& in)
{
    Row row; row.name=in.name; row.bound=in.resource!=nullptr; row.x=in.x; row.y=in.y;
    if(!in.resource) { row.status="not bound / null"; return row; }
    auto d=in.resource->GetDesc(); row.format=d.Format; row.width=uint32_t(d.Width); row.height=d.Height;
    auto f=FSRD::GetViewFormat(d.Format); auto [bytes,channels]=Format(f);
    D3D12_FEATURE_DATA_FORMAT_SUPPORT support {f};
    if(!bytes || FAILED(dev->CheckFeatureSupport(D3D12_FEATURE_FORMAT_SUPPORT,&support,sizeof(support))) ||
       !(support.Support1&D3D12_FORMAT_SUPPORT1_SHADER_LOAD)) row.status="unsupported typed sampling format";
    else if(d.Dimension!=D3D12_RESOURCE_DIMENSION_TEXTURE2D || d.DepthOrArraySize!=1 ||
        d.SampleDesc.Count!=1 || !d.MipLevels || (d.Flags&D3D12_RESOURCE_FLAG_DENY_SHADER_RESOURCE) ||
        !in.width || !in.height || uint64_t(in.x)+in.width>d.Width || uint64_t(in.y)+in.height>d.Height)
        row.status="incompatible extent / subrect / resource";
    else { row.status="bound; awaiting probe"; row.sampled=true; }
    return row;
}
Json RowJson(const Row& row)
{
    return {{"name",row.name},{"bound",row.bound},{"dxgi_format",row.format},{"size",{row.width,row.height}},
        {"subrect_base",{row.x,row.y}},{"sampled",row.sampled},{"status",row.status},
        {"mean",row.sampled?Json(row.mean):Json(nullptr)},{"max_abs",row.sampled?Json(row.maximum):Json(nullptr)},
        {"fraction_nonzero",row.sampled?Json(row.nonzero):Json(nullptr)},
        {"fraction_nonfinite",row.sampled?Json(row.nonfinite):Json(nullptr)}};
}
std::filesystem::path LogDirectory()
{
    auto path=std::filesystem::path(Config::Instance()->LogFileName.value_or_default());
    if(!path.has_parent_path() && !path.is_absolute()) path=Util::ExePath().parent_path()/path;
    else if(std::filesystem::is_directory(path)) path/=L"OptiScaler.log";
    if(!std::filesystem::is_directory(path.parent_path())) path=Util::ExePath().parent_path()/L"OptiScaler.log";
    return path.parent_path();
}
struct Copy
{
    ComPtr<ID3D12Resource> source, buffer;
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint {};
    uint64_t bytes=0;
    uint32_t x=0,y=0,width=0,height=0,bpp=0,channels=0;
    bool whole=false;
    std::string name;
    Json meta;
};
Copy Plan(ID3D12Device* dev,const std::string& name,ID3D12Resource* source,uint32_t x,uint32_t y,uint32_t w,uint32_t h,uint64_t* total=nullptr)
{
    Copy c; c.name=name; c.source=source; c.x=x; c.y=y; c.width=w; c.height=h;
    auto d=source->GetDesc(); auto f=FSRD::GetViewFormat(d.Format);
    auto [bpp,channels]=Format(f); c.bpp=bpp; c.channels=channels;
    if(!bpp || uint64_t(x)+w>d.Width || uint64_t(y)+h>d.Height) throw std::runtime_error("Unsupported snapshot: "+name);
    c.meta={{"file",name+".bin"},{"dxgi_format",uint32_t(d.Format)},{"view_format",uint32_t(f)},
        {"width",w},{"height",h},{"channels",channels},{"bytes_per_pixel",bpp},{"source_base",{x,y}}};
    c.whole=(d.Flags&D3D12_RESOURCE_FLAG_ALLOW_DEPTH_STENCIL)!=0;
    if(c.whole)
    {
        c.width=uint32_t(d.Width); c.height=d.Height;
        c.meta["width"]=c.width; c.meta["height"]=c.height; c.meta["crop"]={x,y,w,h};
    }
    d.Width=c.width; d.Height=c.height; d.MipLevels=1;
    dev->GetCopyableFootprints(&d,0,1,0,&c.footprint,nullptr,nullptr,&c.bytes);
    if(!c.bytes || c.bytes>(768ull<<20)) throw std::runtime_error("Snapshot exceeds readback budget");
    if(total) { if(*total+c.bytes>(768ull<<20)) throw std::runtime_error("Reference snapshot exceeds 768 MiB; lower render resolution"); *total+=c.bytes; }
    D3D12_HEAP_PROPERTIES heap {D3D12_HEAP_TYPE_READBACK};
    D3D12_RESOURCE_DESC b {}; b.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER; b.Width=c.bytes;
    b.Height=b.DepthOrArraySize=b.MipLevels=b.SampleDesc.Count=1; b.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
    ThrowIfFailed(dev->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&b,D3D12_RESOURCE_STATE_COPY_DEST,nullptr,IID_PPV_ARGS(&c.buffer)),"Research readback allocation failed");
    return c;
}
void Record(ID3D12GraphicsCommandList* cmd,Copy& c)
{
    AddBarrier(cmd,c.source.Get(),kSrvState,D3D12_RESOURCE_STATE_COPY_SOURCE);
    D3D12_TEXTURE_COPY_LOCATION dst {}; dst.pResource=c.buffer.Get(); dst.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT; dst.PlacedFootprint=c.footprint;
    D3D12_TEXTURE_COPY_LOCATION src {}; src.pResource=c.source.Get(); src.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
    D3D12_BOX box {c.x,c.y,0,c.x+c.width,c.y+c.height,1};
    cmd->CopyTextureRegion(&dst,0,0,0,&src,c.whole?nullptr:&box);
    AddBarrier(cmd,c.source.Get(),D3D12_RESOURCE_STATE_COPY_SOURCE,kSrvState);
}
void WriteJson(const std::filesystem::path& path,const Json& json)
{
    auto temp=path; temp+=L".tmp";
    { std::ofstream file(temp,std::ios::binary|std::ios::trunc); file<<json.dump(2)<<'\n'; if(!file) throw std::runtime_error("Research JSON write failed"); }
    if(!MoveFileExW(temp.c_str(),path.c_str(),MOVEFILE_REPLACE_EXISTING|MOVEFILE_WRITE_THROUGH)) throw std::runtime_error("Research JSON publication failed");
}
struct Job
{
    bool probe=false;
    std::shared_ptr<RRTraceFence::Ticket> ticket;
    std::vector<Copy> copies;
    std::vector<Row> rows;
    Json metadata;
    std::filesystem::path folder;
};
void Export(std::shared_ptr<Job> job)
{
    SetThreadPriority(GetCurrentThread(),THREAD_PRIORITY_BELOW_NORMAL);
    try
    {
        std::filesystem::create_directories(job->folder);
        if(job->probe)
        {
            auto& c=job->copies.front(); void* ptr=nullptr; D3D12_RANGE read{0,SIZE_T(c.bytes)};
            ThrowIfFailed(c.buffer->Map(0,&read,&ptr),"Probe readback Map failed");
            for(size_t row=0;row<job->rows.size();++row) if(job->rows[row].sampled)
            {
                const auto* data=reinterpret_cast<const float*>(static_cast<const uint8_t*>(ptr)+c.footprint.Offset+row*c.footprint.Footprint.RowPitch);
                auto& r=job->rows[row];
                std::copy_n(data,4,r.mean.begin()); std::copy_n(data+4,4,r.maximum.begin());
                std::copy_n(data+8,4,r.nonzero.begin()); std::copy_n(data+12,4,r.nonfinite.begin());
                bool nonzero=false,finite=true;
                for(unsigned n=0;n<4;++n) { nonzero|=r.nonzero[n]>0; finite&=r.nonfinite[n]==0; }
                r.status=!finite?"contains nonfinite samples":nonzero?"populated samples":"all sampled channels zero";
            }
            D3D12_RANGE written{0,0}; c.buffer->Unmap(0,&written);
            Json rows=Json::array();
            for(const auto& row:job->rows) { auto j=RowJson(row); rows.push_back(j); LOG_INFO("[RR_INPUTS] {}",j.dump()); }
            Json out={{"schema","fsrd-rr-inputs-v1"},{"sample_grid",{64,64}},{"inputs",rows},
                {"note","A one-time probe cannot establish freshness. Populated means nonzero sampled channels only."}};
            { auto& g=Global(); std::scoped_lock lock(g.mutex); if(g.stop) throw std::runtime_error("Input probe cancelled before publication"); }
            WriteJson(job->folder/"OptiScaler_rr_inputs.json",out);
            { auto& g=Global(); std::scoped_lock lock(g.mutex); g.status.rows=job->rows; g.status.folder=job->folder.string(); }
            Message("Input probe saved: "+(job->folder/"OptiScaler_rr_inputs.json").string(),false);
        }
        else
        {
            Json images=Json::object();
            for(auto& c:job->copies)
            {
                void* ptr=nullptr; D3D12_RANGE read{0,SIZE_T(c.bytes)};
                ThrowIfFailed(c.buffer->Map(0,&read,&ptr),"Reference readback Map failed");
                std::ofstream file(job->folder/(c.name+".bin"),std::ios::binary|std::ios::trunc);
                const auto* data=static_cast<const char*>(ptr)+c.footprint.Offset;
                for(uint32_t y=0;y<c.height;++y) file.write(data+size_t(y)*c.footprint.Footprint.RowPitch,size_t(c.width)*c.bpp);
                D3D12_RANGE written{0,0}; c.buffer->Unmap(0,&written);
                if(!file) throw std::runtime_error("Reference image write failed");
                images[c.name]=c.meta;
            }
            { auto& g=Global(); std::scoped_lock lock(g.mutex); if(g.stop) throw std::runtime_error("Reference export cancelled before publication"); }
            job->metadata["images"]=images; job->metadata["complete"]=true;
            WriteJson(job->folder/"reference.json",job->metadata);
            LOG_INFO("[RR_REFERENCE] Saved {}",job->folder.string());
            Message("Reference saved: "+job->folder.string(),false);
        }
    }
    catch(const std::exception& e) { LOG_ERROR("[RR_INPUTS] {}",e.what()); Message(std::string("Research export failed: ")+e.what(),false); }
}
}

bool RequestProbe()
{
    auto& g=Global(); std::scoped_lock lock(g.mutex); if(g.status.busy) return false;
    g.status.busy=true; g.status.frames=0; g.status.target=0; g.request=1; g.stop=false; g.wanted=true;
    g.status.message="Input probe requested; waiting for an FSR-RR frame."; return true;
}
bool RequestReference(uint32_t frames)
{
    if(frames!=64 && frames!=256 && frames!=1024) return false;
    auto& g=Global(); std::scoped_lock lock(g.mutex); if(g.status.busy) return false;
    g.status.busy=true; g.status.frames=0; g.status.target=frames; g.request=frames; g.stop=false;
    g.wanted=true; g.reference=true; g.status.message="Reference requested; keep the photo-mode camera frozen."; return true;
}
void RequestStop() { auto& g=Global(); std::scoped_lock lock(g.mutex); g.stop=true; }
bool WantsInputs() { return Global().wanted.load(); }
bool ReferenceActive() { return Global().reference.load(); }
Status GetStatus() { auto& g=Global(); std::scoped_lock lock(g.mutex); return g.status; }

struct Session::Impl
{
    ID3D12Device* device=nullptr;
    FSRDStageTimings* timings=nullptr;
    ComputeState probe,reference;
    std::array<ComPtr<ID3D12Resource>,3> sums;
    std::vector<Input> inputs;
    XMFLOAT4X4 camera {};
    uint32_t count=0,target=0,width=0,height=0;
    std::string settings;
    Json controls=Json::array();
    std::shared_ptr<Job> pending;
    std::future<void> writer;
    bool owns=false;
    ~Impl() { Abort("Reference owner ended before completion."); if(writer.valid()) writer.wait(); }
    void Abort(const char* reason)
    {
        if(!owns) return;
        if(writer.valid() && writer.wait_for(std::chrono::seconds(0))!=std::future_status::ready)
        {
            { auto& g=Global(); std::scoped_lock lock(g.mutex); g.stop=true; }
            target=0; Global().wanted=false;
            Message(std::string(reason)+" Waiting for the export worker to release its buffers.",true);
            return;
        }
        if(pending && pending->ticket) { pending->ticket->Abandon(); RRTraceFence::Forget(pending->ticket); pending.reset(); }
        for(auto& s:sums) s.Reset(); inputs.clear(); count=target=0; owns=false;
        Message(reason,false);
    }
    void Queue(ID3D12GraphicsCommandList* cmd,const std::shared_ptr<Job>& job)
    {
        uint64_t total=0; for(const auto& c:job->copies) total+=c.bytes;
        if(total>(768ull<<20)) throw std::runtime_error("Reference snapshot exceeds 768 MiB; use a lower render resolution");
        job->ticket=RRTraceFence::Arm(device,cmd);
        pending=job;
        try {
        for(auto& c:job->copies) { job->ticket->Retain(c.source.Get()); job->ticket->Retain(c.buffer.Get()); }
        // Store ownership before the first copy; an exception must abandon the ticket.
        } catch(...) { job->ticket->CancelUnrecorded(); throw; }
        job->ticket->Recorded();
        for(auto& c:job->copies) Record(cmd,c);
        Global().wanted=false;
        for(auto& s:sums) s.Reset(); inputs.clear();
        Message("Waiting for GPU completion and command-list Reset before export.",true);
    }
    void Poll()
    {
        if(writer.valid() && writer.wait_for(std::chrono::seconds(0))==std::future_status::ready) { writer.get(); owns=false; }
        if(!pending) return;
        if(pending->ticket->Invalid()) { Abort("Research snapshot invalidated; nothing published."); return; }
        if(!pending->ticket->Ready()) return;
        RRTraceFence::Forget(pending->ticket); pending->ticket.reset();
        auto job=std::move(pending);
        writer=std::async(std::launch::async,[job] { Export(job); });
    }
    void Begin(ID3D12Device* dev,ID3D12GraphicsCommandList* cmd,std::span<const Input> source,uint32_t w,uint32_t h,const XMFLOAT4X4& view,bool normal)
    {
        Poll();
        if(owns)
        {
            bool stop; { auto& g=Global(); std::scoped_lock lock(g.mutex); stop=g.stop; }
            if(stop && !writer.valid()) { Abort("Research capture cancelled; no reference published."); return; }
        }
        if(!WantsInputs()) return;
        uint32_t request=0;
        if(!owns) { auto& g=Global(); std::scoped_lock lock(g.mutex); request=g.request; if(request) {g.request=0; owns=true;} }
        if(!owns) return;
        if(!normal) { Abort("Research capture aborted: normal RR rendering required (debug/bypass is active)."); return; }
        if(!dev || !cmd || !ResTrack_Dx12::EnsureRRTraceHooks(dev)) { Abort("Research capture unavailable: submission tracking hooks missing."); return; }
        device=dev;
        if(request>1)
        {
            if(uint64_t(w)*h*48>(512ull<<20)) { Abort("Reference accumulation exceeds 512 MiB; lower render resolution."); return; }
            count=0; target=request; width=w; height=h; camera=view; settings.clear(); controls=Json::array();
            if(!reference.m_pso) reference.Initialize(dev,{reinterpret_cast<const byte*>(FSRDReference_cso),sizeof(FSRDReference_cso)},32,2,3,L"FSRD_Reference");
            for(auto& s:sums) s=CreateTexture2D(dev,w,h,DXGI_FORMAT_R32G32B32A32_FLOAT,L"FSRD_ReferenceAccumulator",kSrvState);
        }
        if(request==1)
        {
            FSRDStageTimings::Scope timing(timings,FSRDStageTimings::InputInventory);
            auto job=std::make_shared<Job>(); job->probe=true; job->folder=LogDirectory();
            for(const auto& in:source) job->rows.push_back(Describe(dev,in));
            if(source.empty()) { Abort("No input inventory is available for this frame."); return; }
            if(!probe.m_pso) probe.Initialize(dev,{reinterpret_cast<const byte*>(FSRDProbeInputs_cso),sizeof(FSRDProbeInputs_cso)},48,1,1,L"FSRD_InputInventory");
            auto output=CreateTexture2D(dev,4,UINT(source.size()),DXGI_FORMAT_R32G32B32A32_FLOAT,L"FSRD_InputStats",kSrvState);
            for(size_t i=0;i<source.size();++i) if(job->rows[i].sampled)
            {
                auto channels=Format(GetViewFormat(source[i].resource->GetDesc().Format)).second;
                struct Constants { XMUINT2 extent,base; XMFLOAT4 mask; uint32_t row,pad[3]; };
                static_assert(sizeof(Constants)==48);
                Constants c {{source[i].width,source[i].height},{source[i].x,source[i].y},{1,channels>1?1.f:0.f,channels>2?1.f:0.f,channels>3?1.f:0.f},uint32_t(i),{}};
                auto srvs=std::to_array({source[i].resource}); auto uavs=std::to_array({output.Get()});
                probe.Dispatch(cmd,GetAsByteSpan(c),srvs,uavs,{1,1});
            }
            job->copies.push_back(Plan(dev,"probe",output.Get(),0,0,4,UINT(source.size()))); Queue(cmd,job); return;
        }
        if(!target || pending || writer.valid()) return;
        const auto* a=reinterpret_cast<const float*>(&view); const auto* b=reinterpret_cast<const float*>(&camera);
        for(unsigned i=0;i<16;++i) if(!std::isfinite(a[i]) || std::abs(a[i]-b[i])>1e-5f) { Abort("Reference aborted: camera moved (matrix epsilon 1e-5)."); return; }
        if(w!=width || h!=height) { Abort("Reference aborted: render resolution changed."); return; }
        inputs.assign(source.begin(),source.end());
    }
    void Finish(ID3D12GraphicsCommandList* cmd,ID3D12Resource* finalColor,ID3D12Resource* depth,ID3D12Resource* normals,const std::string& config,const std::string& control)
    {
        if(!owns || !target || pending || writer.valid()) return;
        auto raw=std::find_if(inputs.begin(),inputs.end(),[](const Input& i) {return i.name=="Color";});
        if(raw==inputs.end() || !Describe(device,*raw).sampled) { Abort("Reference aborted: raw Color is incompatible."); return; }
        if(count && settings!=config) { Abort("Reference aborted: applied settings changed."); return; }
        settings=config; auto cjson=Json::parse(control);
        if(count && controls.front().value("pre_exposure",1.0)!=cjson.value("pre_exposure",1.0)) { Abort("Reference aborted: pre-exposure changed; lock exposure."); return; }
        controls.push_back(cjson);
        struct Constants { XMUINT2 extent,base; uint32_t count,target,pad[2]; };
        static_assert(sizeof(Constants)==32);
        Constants c {{width,height},{raw->x,raw->y},++count,target,{}};
        auto srvs=std::to_array({raw->resource,finalColor}); auto uavs=std::to_array({sums[0].Get(),sums[1].Get(),sums[2].Get()});
        { FSRDStageTimings::Scope timing(timings,FSRDStageTimings::ReferenceAccumulation);
          reference.Dispatch(cmd,GetAsByteSpan(c),srvs,uavs,{float(width),float(height)}); }
        { auto& g=Global(); std::scoped_lock lock(g.mutex); g.status.frames=count; g.status.message="Reference accumulation "+std::to_string(count)+" / "+std::to_string(target); }
        if(count!=target) return;
        auto job=std::make_shared<Job>();
        job->folder=Util::DllPath().parent_path()/"GAME_TRACE"/std::format("reference-{}-{}",GetCurrentProcessId(),GetTickCount64());
        uint64_t plannedBytes=0;
        job->metadata={{"schema","fsrd-reference-v1"},{"complete",false},{"frames",count},{"width",width},{"height",height},
            {"settings",Json::parse(settings)},{"controls",controls},{"variance","population E[x*x]-E[x]^2, clamped nonnegative"},
            {"jitter_running",true},{"interpretation","jitter-averaged means; subpixel blur; compare at scales >=2 pixels"},
            {"raw_scope","game composite before skin processing"},{"denoised_scope","final configured composition after Recovery and SSS, before upscaling"},
            {"camera_epsilon",1e-5},{"renderer_compile_stamp",__DATE__ " " __TIME__},{"observer_effect","GPU accumulation and final snapshots add work; primary output is never overwritten"}};
        for(unsigned i=0;i<3;++i) job->copies.push_back(Plan(device,i==0?"raw_mean":i==1?"raw_variance":"denoised_mean",sums[i].Get(),0,0,width,height,&plannedBytes));
        job->copies.push_back(Plan(device,"last_raw",raw->resource,raw->x,raw->y,width,height,&plannedBytes));
        job->copies.push_back(Plan(device,"last_denoised",finalColor,0,0,width,height,&plannedBytes));
        job->copies.push_back(Plan(device,"linear_depth",depth,0,0,width,height,&plannedBytes));
        job->copies.push_back(Plan(device,"packed_normals",normals,0,0,width,height,&plannedBytes));
        Json inventory=Json::array();
        for(const auto& in:inputs)
        {
            auto row=Describe(device,in); auto metadata=RowJson(row);
            metadata["compatible"]=row.sampled; metadata["sampled"]=false;
            metadata["mean"]=metadata["max_abs"]=metadata["fraction_nonzero"]=metadata["fraction_nonfinite"]=nullptr;
            metadata["status"]=row.sampled?"compatible; reference snapshot only":row.status;
            inventory.push_back(std::move(metadata));
            if(row.sampled) job->copies.push_back(Plan(device,"input_"+in.name,in.resource,in.x,in.y,in.width,in.height,&plannedBytes));
        }
        job->metadata["input_inventory"]=inventory;
        job->metadata["reference_shader_sha256"]=RRTraceAdditiveIO::Sha256({FSRDReference_cso,sizeof(FSRDReference_cso)});
        Queue(cmd,job);
        { auto& g=Global(); std::scoped_lock lock(g.mutex); g.status.folder=job->folder.string(); }
    }
};
Session::Session():impl(std::make_unique<Impl>()) {}
Session::~Session()=default;
void Session::SetTimings(FSRDStageTimings* t) {impl->timings=t;}
void Session::Begin(ID3D12Device* d,ID3D12GraphicsCommandList* c,std::span<const Input> i,uint32_t w,uint32_t h,const XMFLOAT4X4& v,bool n)
{ try { impl->Begin(d,c,i,w,h,v,n); } catch(const std::exception& e) { impl->Abort(e.what()); } }
void Session::Finish(ID3D12GraphicsCommandList* c,ID3D12Resource* f,ID3D12Resource* d,ID3D12Resource* n,const std::string& s,const std::string& m)
{ try { impl->Finish(c,f,d,n,s,m); } catch(const std::exception& e) { impl->Abort(e.what()); } }
void Session::Abort(const char* reason) { impl->Abort(reason); }
}
