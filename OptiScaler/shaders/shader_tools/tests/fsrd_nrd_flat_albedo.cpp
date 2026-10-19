// Run actual production RRWrapper and Flat Albedo Recovery, sharing only the
// existing fixture's D3D12 host, explicit lease registry and provider seam.
#define main OriginalRRFixtureMain
#include "nrd_bridge_rr_fixture.cpp"
#undef main
#include <json.hpp>
#include <cstdlib>
using Json = nlohmann::json;
using Path = std::filesystem::path;

std::vector<uint8_t> bytesFrom(const Path& path)
{
    std::ifstream f(path,std::ios::binary|std::ios::ate); need(bool(f),"input file exists");
    const auto n = f.tellg(); need(n>0,"input file nonempty"); std::vector<uint8_t> out(size_t(n),0);
    f.seekg(0); f.read(reinterpret_cast<char*>(out.data()),out.size()); need(bool(f),"input read complete"); return out;
}
void upload(Host& host,Scene& scene,ID3D12Resource* target,const std::vector<uint8_t>& data,D3D12_RESOURCE_STATES state)
{
    const auto desc = target->GetDesc(); const uint32_t bpp = desc.Format == DXGI_FORMAT_R16G16B16A16_FLOAT ? 8:4;
    need(data.size() == desc.Width*desc.Height*bpp,"upload extent matches");
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint {}; UINT rows; UINT64 rowBytes,total;
    host.device->GetCopyableFootprints(&desc,0,1,0,&footprint,&rows,&rowBytes,&total);
    auto staging = buffer(host.device.Get(),total,D3D12_HEAP_TYPE_UPLOAD); uint8_t* mapped;
    hr(staging->Map(0,nullptr,reinterpret_cast<void**>(&mapped)));
    for (uint32_t y=0;y<desc.Height;++y) std::memcpy(mapped+footprint.Offset+uint64_t(y)*footprint.Footprint.RowPitch,
        data.data()+uint64_t(y)*desc.Width*bpp,size_t(desc.Width)*bpp);
    staging->Unmap(0,nullptr); barrier(host.list.Get(),target,state,D3D12_RESOURCE_STATE_COPY_DEST);
    D3D12_TEXTURE_COPY_LOCATION src {},dst {}; src.pResource = staging.Get(); src.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
    src.PlacedFootprint = footprint; dst.pResource = target; dst.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
    host.list->CopyTextureRegion(&dst,0,0,0,&src,nullptr); barrier(host.list.Get(),target,D3D12_RESOURCE_STATE_COPY_DEST,state);
    scene.uploads.push_back(staging);
}
template<class T> std::vector<uint8_t> binary(const std::vector<T>& data)
{
    const auto* first = reinterpret_cast<const uint8_t*>(data.data()); return {first,first+data.size()*sizeof(T)};
}
Readback snapshot(Host& host,ID3D12Resource* resource,D3D12_RESOURCE_STATES state)
{
    if (state != D3D12_RESOURCE_STATE_UNORDERED_ACCESS) barrier(host.list.Get(),resource,state,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
    Readback out(host,resource);
    if (state != D3D12_RESOURCE_STATE_UNORDERED_ACCESS) barrier(host.list.Get(),resource,D3D12_RESOURCE_STATE_UNORDERED_ACCESS,state);
    return out;
}
std::vector<uint8_t> packed(Readback& readback,uint32_t w,uint32_t h,uint32_t bpp)
{
    uint8_t* mapped; hr(readback.bufferResource->Map(0,nullptr,reinterpret_cast<void**>(&mapped)));
    std::vector<uint8_t> out(size_t(w)*h*bpp);
    for (uint32_t y=0;y<h;++y) std::memcpy(out.data()+size_t(y)*w*bpp,
        mapped+readback.footprint.Offset+uint64_t(y)*readback.footprint.Footprint.RowPitch,size_t(w)*bpp);
    readback.bufferResource->Unmap(0,nullptr); return out;
}
void dump(Readback& readback,const Path& path,uint32_t w,uint32_t h,uint32_t bpp)
{
    const auto data = packed(readback,w,h,bpp); std::ofstream f(path,std::ios::binary);
    f.write(reinterpret_cast<const char*>(data.data()),data.size()); need(bool(f),"output written");
}
void helperChecks(Host& host)
{
    constexpr uint32_t w=128,h=128;
    Scene scene(host,w,h); std::vector<uint32_t> normals(w*h);
    std::vector<uint16_t> spec(w*h*4),diff(w*h*4),raw(w*h*4);
    for (uint32_t p=0;p<w*h;++p)
    {
        normals[p] = (p%1024)<<20 | ((p*17)%1024)<<10 | ((p*31)%1024) | ((p/1024)%4)<<30;
        for (uint32_t c=0;c<3;++c)
        {
            spec[4*p+c] = PackedVector::XMConvertFloatToHalf(.02f+.01f*((p/8)%2)+.001f*((p*13+c*5)%7));
            diff[4*p+c] = PackedVector::XMConvertFloatToHalf(.08f+.02f*((p/w/8)%2)+.003f*((p*19+c)%5));
            raw[4*p+c] = PackedVector::XMConvertFloatToHalf(.04f+.01f*c);
        }
        // Includes all roughness codes, all four native IDs, -1, -0 and +0.
        spec[4*p+3] = (p/1024)%4 == 0 ? 0xbc00 : ((p/1024)%4 == 1 ? 0x8000:0);
        diff[4*p+3] = (p/1024)%4 == 2 ? 0xbc00 : 0;
        raw[4*p+3] = p%2 ? 0x8000:0x3c00;
    }
    upload(host,scene,scene.resources.normals,binary(normals),D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
    upload(host,scene,scene.resources.spec,binary(spec),D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
    upload(host,scene,scene.resources.diff,binary(diff),D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
    upload(host,scene,scene.spec(),binary(raw),D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
    upload(host,scene,scene.diff(),binary(raw),D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
    auto family=MakeOwnedShared<LobeRecovery::Family>(); FlatAlbedoRecovery helper;
    FlatAlbedoSettings settings; settings.enabled=true;
    const LobeRecoveryInputs in {scene.resources.spec,scene.resources.diff,scene.resources.linearDepth,scene.resources.motion,
        scene.resources.normals,scene.spec(),scene.diff(),w,h};
    LobeRecoveryFrame frame; FlatAlbedoRecovery::Prepared prepared; std::string error;
    need(helper.Prepare(host.device.Get(),host.list.Get(),in,frame,settings,family,prepared,error),error.c_str());
    need(ResTrack_Dx12::RetainComputeDispatch(host.device.Get(),host.list.Get(),prepared.owner),"helper leased before commands");
    FlatAlbedoRecovery::Prepared denied;
    need(!helper.Prepare(host.device.Get(),host.list.Get(),in,frame,settings,family,denied,error),"unrecorded prepared predecessor denied");
    helper.RecordInputs(host.list.Get(),prepared); helper.RecordOutput(host.list.Get(),prepared);
    auto rrNormal=snapshot(host,prepared.normals,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
    auto original=snapshot(host,scene.resources.normals,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
    auto s=snapshot(host,prepared.specular,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
    auto d=snapshot(host,prepared.diffuse,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
    auto provider=snapshot(host,scene.spec(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
    host.submit();
    need(packed(original,w,h,4)==binary(normals),"original packed geometry is bit exact");
    need(packed(provider,w,h,8)==binary(raw),"raw provider observations remain bit exact");
    auto nr=packed(rrNormal,w,h,4),sp=packed(s,w,h,8),dp=packed(d,w,h,8);
    uint32_t active=0;
    for (uint32_t p=0;p<w*h;++p)
    {
        const auto rough=(normals[p]>>20)&1023; const bool sa=spec[4*p+3]!=0xbc00,da=diff[4*p+3]!=0xbc00;
        const uint32_t expected=rough<2 && (sa||da) ? (normals[p]&0xc00fffff)|(2u<<20) : normals[p];
        need(std::memcmp(nr.data()+4*p,&expected,4)==0,"floor modifies only original low-roughness B bits");
        for (uint32_t lobe=0;lobe<2;++lobe)
        {
            const auto& result=lobe ? dp:sp; const bool enabled=lobe ? da:sa;
            need(std::memcmp(result.data()+p*8+6,raw.data()+p*4+3,2)==0,"every output alpha bit preserved");
            if (rough>=2 || !enabled) need(std::memcmp(result.data()+p*8,raw.data()+p*4,8)==0,"nonflat and inactive lobe remain bit exact");
            for (uint32_t c=0;c<3;++c)
            {
                uint16_t word;std::memcpy(&word,result.data()+p*8+2*c,2);
                need(std::isfinite(PackedVector::XMConvertHalfToFloat(word)),"finite recovered radiance");
            }
        }
        active += rough<2;
    }
    need(active>0,"synthetic fixture covers low-roughness mask");
    host.reset();
}
void wrapperChecks(Host& host)
{
    RRWrapper wrapper; RRSettings settings; settings.flatAlbedo.enabled=true;
    std::string error; need(wrapper.Configure(settings,error),"flat settings configure");
    Scene scene(host,128,128);
    std::vector<uint32_t> normals(128*128,512u|(512u<<10));
    upload(host,scene,scene.resources.normals,binary(normals),D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
    FrameParameters frame; RRRecordedOutputLease output;
    need(wrapper.PrepareFrame(camera(100),true,frame,error),"wrapper flat frame prepare");
    need(wrapper.RecordOwned(host.list.Get(),scene.resources,frame,output,error),error.c_str());
    auto view=wrapper.GetOwnedOutputSnapshot(output);
    need(view.flatAlbedoActive && !view.flatAlbedoFallback && view.flatAlbedoRoughness==2,"actual wrapper activates flat graph and floor together");
    need(view.providerNormals!=scene.resources.normals && view.selectedSpec!=view.rawSpec && view.selectedDiff!=view.rawDiff,
        "provider geometry and selected outputs are independently owned");
    auto nr=snapshot(host,view.providerNormals,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
    auto source=snapshot(host,scene.resources.normals,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
    host.submit();
    need(packed(source,128,128,4)==binary(normals),"wrapper preserves original geometry");
    for (auto& n:normals) n|=2u<<20;
    need(packed(nr,128,128,4)==binary(normals),"wrapper provider reads the real floor texture");
    host.reset(); output.reset(); view={};
    settings.flatAlbedo.strength=0; need(wrapper.Configure(settings,error),"zero strength configure");
    need(wrapper.PrepareFrame(camera(101),false,frame,error),"zero strength frame prepare");
    need(wrapper.RecordOwned(host.list.Get(),scene.resources,frame,output,error),error.c_str());
    view=wrapper.GetOwnedOutputSnapshot(output);
    need(!view.flatAlbedoActive && !view.flatAlbedoFallback && view.providerNormals==scene.resources.normals &&
        view.selectedSpec==view.rawSpec && view.selectedDiff==view.rawDiff,"zero strength skips floor, allocation and recovery");
    need(FfxApiProxy::lastDispatch.flags&FFX_DENOISER_DISPATCH_RESET,"turning compatibility floor off resets provider history");
    host.submit();host.reset();output.reset();view={};wrapper.DiscardRecordingHistory();
    // Admission failure is decided before any GPU work: unmodified RR continues.
    RRWrapper fallback; auto family=CreateRRRecoveryFamily();
    std::vector<NrdBridgeCaptureBudget::Permit> permits;
    for (uint32_t i=0;i<32;++i) permits.push_back(NrdBridgeCaptureBudget::Permit::TryAcquire(
        std::shared_ptr<NrdBridgeCaptureBudget::Family>(family,&family->budget.slots)));
    settings.flatAlbedo.strength=1;
    need(fallback.Configure(settings,error),"fallback settings");
    fallback.SetRecoveryFamily(family);
    need(fallback.PrepareFrame(camera(102),true,frame,error),"fallback frame prepare");
    need(fallback.RecordOwned(host.list.Get(),scene.resources,frame,output,error),error.c_str());
    view=fallback.GetOwnedOutputSnapshot(output);
    need(!view.flatAlbedoActive && view.flatAlbedoFallback && !view.flatAlbedoError.empty() &&
        view.providerNormals==scene.resources.normals && view.selectedSpec==view.rawSpec,
        "family exhaustion never floors geometry without a retained recovery graph");
    host.submit();host.reset();output.reset();view={};fallback.DiscardRecordingHistory();
}
int main(int argc,char** argv) try
{
    std::cout.setf(std::ios::unitbuf); need(argc==2,"job JSON required");
    const auto data=bytesFrom(Path(argv[1])); const auto job=Json::parse(data);
    Host host;
    helperChecks(host);
    wrapperChecks(host);
    // Repeat the actual wrapper path with the signed provider, including the
    // prepare-failure/zero-strength branches. No native NRD shader is dispatched.
    loadReal(); wrapperChecks(host);
    const auto frames=job.at("frames");
    auto family=MakeOwnedShared<LobeRecovery::Family>(); FlatAlbedoRecovery helper;
    FlatAlbedoSettings settings; settings.enabled=true;
    // Task 24 A/B: the same chain with "NZR on vertical surfaces" enabled, for gate/byte comparisons
    // against the default (0) run. Unset means 0, so the default test path is unchanged.
    if (const char* knob=std::getenv("FSRD24_GLASS_MODE")) settings.verticalMode=uint32_t(std::atoi(knob));
    if (const char* knob=std::getenv("FSRD24_GLASS_STRENGTH")) settings.verticalStrength=float(std::atof(knob));
    const uint32_t w=job.at("width"),h=job.at("height");
    uint32_t count=0;
    for (const auto& row:frames)
    {
        const Path folder=row.at("inputs").get<std::string>(); Scene scene(host,w,h,folder);
        upload(host,scene,scene.spec(),bytesFrom(folder/"rr_specular.bin"),D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
        upload(host,scene,scene.diff(),bytesFrom(folder/"rr_diffuse.bin"),D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
        const LobeRecoveryInputs in {scene.resources.spec,scene.resources.diff,scene.resources.linearDepth,scene.resources.motion,
            scene.resources.normals,scene.spec(),scene.diff(),w,h};
        LobeRecoveryFrame frame; frame.frameIndex=row.at("sdk_frame"); frame.reset=row.at("reset");
        FlatAlbedoRecovery::Prepared prepared; std::string error;
        need(helper.Prepare(host.device.Get(),host.list.Get(),in,frame,settings,family,prepared,error),error.c_str());
        need(ResTrack_Dx12::RetainComputeDispatch(host.device.Get(),host.list.Get(),prepared.owner),"capture helper lease");
        helper.RecordInputs(host.list.Get(),prepared); helper.RecordOutput(host.list.Get(),prepared);
        auto s=snapshot(host,prepared.specular,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
        auto d=snapshot(host,prepared.diffuse,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
        host.submit(); const Path out=row.at("output").get<std::string>();
        std::filesystem::create_directories(out); dump(s,out/"specular.bin",w,h,8);dump(d,out/"diffuse.bin",w,h,8);
        ++count;host.reset();
    }
    hr(host.list->Close()); host.checkDebug();
    std::cout<<"PASS checks="<<checks<<" flat_capture_frames="<<count<<" debug_errors=0 debug_warnings=0\n";
    return 0;
}
catch (const std::exception& e) {std::cerr<<e.what()<<'\n';return 1;}
