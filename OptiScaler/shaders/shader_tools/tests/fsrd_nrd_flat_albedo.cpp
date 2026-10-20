// Run actual production RRWrapper and Flat Albedo Recovery, sharing only the
// existing fixture's D3D12 host, explicit lease registry and provider seam.
#define main OriginalRRFixtureMain
#include "nrd_bridge_rr_fixture.cpp"
#undef main
#include <json.hpp>
#include <cstdlib>
#include <chrono>
#include "shaders/fsrd_preprocess/FSRDPostFlickConstants.h"
#include "shaders/fsrd_preprocess/precompile/FSRDPostFlickApply_Shader.h"
#include "shaders/fsrd_preprocess/precompile/FSRDPostFlickPrepare_Shader.h"
#include <algorithm>
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
// Task 24: the vertical-surface option adds no pass, no dispatch and no resource; it only changes the arithmetic
// inside the existing apply pass. Measure the whole NZR chain with the option off and on at the user's render
// resolution (1505x847) and at 2560x1440: wall clock around submit(), which waits on a GPU fence.
void timingChecks(Host& host)
{
    const std::pair<uint32_t,uint32_t> sizes[] = {{1505u,847u},{2560u,1440u}};
    for (const auto& [w,h] : sizes)
    {
        for (uint32_t mode : {0u,1u})
        {
            auto family = MakeOwnedShared<LobeRecovery::Family>(); FlatAlbedoRecovery helper;
            FlatAlbedoSettings settings; settings.enabled = true;
            settings.verticalMode = mode; settings.verticalStrength = mode ? 0.5f : 0.0f;
            Scene scene(host,w,h);
            std::vector<double> samples;
            for (uint32_t i = 0;i < 24;++i)
            {
                const LobeRecoveryInputs in {scene.resources.spec,scene.resources.diff,scene.resources.linearDepth,
                    scene.resources.motion,scene.resources.normals,scene.spec(),scene.diff(),w,h};
                LobeRecoveryFrame frame; frame.frameIndex = 100 + i; frame.reset = (i == 0);
                FlatAlbedoRecovery::Prepared prepared; std::string error;
                need(helper.Prepare(host.device.Get(),host.list.Get(),in,frame,settings,family,prepared,error),error.c_str());
                need(ResTrack_Dx12::RetainComputeDispatch(host.device.Get(),host.list.Get(),prepared.owner),"timing lease");
                helper.RecordInputs(host.list.Get(),prepared); helper.RecordOutput(host.list.Get(),prepared);
                const auto start = std::chrono::steady_clock::now();
                host.submit();
                samples.push_back(std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count());
                host.reset();
            }
            std::sort(samples.begin(),samples.end());
            std::cout << "timing " << w << "x" << h << " vertical mode " << mode << ": median "
                      << samples[samples.size()/2] << " ms, p10 " << samples[samples.size()/10]
                      << " ms over " << samples.size() << " frames" << std::endl;
            checks += 0;
        }
    }
}

// Task 24 T2 c) verification: the post-flick blotch fix pass pair, driven through the same camera and constant
// math the preprocessor uses (FSRDPostFlickConstants.h) instead of a hand-written identity matrix.
//   A) the shared state machine on the CPU: the first frame refreshes the keyframe, a turning camera never does, and
//      the keyframe is only refreshed after the camera has been still for kSettledFramesNeeded frames. That lock is
//      what stops the flick's own blotchy frames from overwriting the good reference, and it is exactly where the
//      audit found the shipped pass inert after a flick.
//   B) a frame without history returns the input byte-identically (GPU).
//   C) a real translation camera pair: a synthetic spike in the keyframe band has to come back at the reprojected
//      pixel. A transposed matrix or a wrong projection element cannot produce that (GPU).
//   D) the cost of the pass pair at the user's resolution.
void postFlickChecks(Host& host)
{
    // The user's render size is the default; FSRD24_PF_RES=2560x1440 repeats the same checks (and the cost
    // measurement) at 1440p, so the 1440p number is reproducible instead of hand-edited.
    uint32_t W = 1505, H = 847;
    if (const char* knob = std::getenv("FSRD24_PF_RES"))
    {
        const std::string value(knob);
        const auto split = value.find('x');
        need(split != std::string::npos, "post-flick resolution knob is WxH");
        W = uint32_t(std::atoi(value.substr(0, split).c_str()));
        H = uint32_t(std::atoi(value.substr(split + 1).c_str()));
    }
    const uint32_t HW = W / 2, HH = H / 2;
    const auto matrix = [](std::initializer_list<float> values) {
        DirectX::XMFLOAT4X4 m {};
        std::memcpy(&m.m[0][0], values.begin(), sizeof(float) * 16);
        return m;
    };
    // Column-vector (HLSL) form, the form the composition desc carries.
    const DirectX::XMFLOAT4X4 identity = matrix({1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1});
    const DirectX::XMFLOAT4X4 turned = matrix({0.8660254f,0,-0.5f,0, 0,1,0,0, 0.5f,0,0.8660254f,0, 0,0,0,1});
    const DirectX::XMFLOAT4X4 moved = matrix({1,0,0,-0.5f, 0,1,0,0, 0,0,1,0, 0,0,0,1});
    const DirectX::XMFLOAT4X4 projection = matrix({1,0,0,0, 0,1,0,0, 0,0,1,1, 0,0,-1,0});
    // The composition desc stores the transpose of the matrix HLSL sees (StoreHlslColumnVectorMatrix writes
    // XMMatrixTranspose and a column-major cbuffer read turns it back), so the fixture feeds the desc form exactly
    // like FSRDFeature_Dx12.cpp does. The semantic matrices above stay in the column-vector form.
    const auto descForm = [](const DirectX::XMFLOAT4X4& m) {
        DirectX::XMFLOAT4X4 out {};
        DirectX::XMStoreFloat4x4(&out, DirectX::XMMatrixTranspose(DirectX::XMLoadFloat4x4(&m)));
        return out;
    };
    {
        // A) the state machine the preprocessor runs every frame.
        PostFlickMath::KeyState state;
        PostFlickMath::Outputs outputs;
        PostFlickMath::BuildFrame(state, W, H, false, 1.0f, descForm(identity), descForm(projection), descForm(identity), outputs);
        need(outputs.Refresh && outputs.Prepare[6] == 1.0f && outputs.Prepare[7] == 0.0f,
            "post-flick: the first frame refreshes the keyframe and reports no history");
        PostFlickMath::BuildFrame(state, W, H, true, 1.0f, descForm(turned), descForm(projection), descForm(identity), outputs);
        need(!outputs.Refresh, "post-flick: a turning camera never refreshes the keyframe");
        // Rotation in every axis, not just pitch: CP77 is Z-up, so the `turned` matrix above is a pitch, which even
        // a transposed load sees. A 30 degree yaw between two horizontal cameras is invisible to the transposed
        // load (it read the world-up axis in camera coordinates) and was measured as a pitch-only detector on the
        // 2405/0512 captures, so this assertion is the regression test for that bug.
        const DirectX::XMFLOAT4X4 horizontal = matrix({-1,0,0,0, 0,0,1,0, 0,1,0,0, 0,0,0,1});
        const DirectX::XMFLOAT4X4 yawed = matrix({-0.8660254f,-0.5f,0,0, 0,0,1,0, -0.5f,0.8660254f,0,0, 0,0,0,1});
        PostFlickMath::KeyState yawState;
        PostFlickMath::Outputs yawOutputs;
        PostFlickMath::BuildFrame(yawState, W, H, true, 1.0f, descForm(horizontal), descForm(projection),
            descForm(horizontal), yawOutputs);
        need(!PostFlickMath::BuildFrame(yawState, W, H, true, 1.0f, descForm(yawed), descForm(projection),
                descForm(horizontal), yawOutputs),
            "post-flick: a 30 degree yaw counts as camera motion, not only pitch");
        for (uint32_t i = 0; i + 1 < PostFlickMath::kSettledFramesNeeded; ++i)
        {
            PostFlickMath::BuildFrame(state, W, H, true, 1.0f, descForm(identity), descForm(projection), descForm(identity), outputs);
            need(!outputs.Refresh, "post-flick: the first still frames must not overwrite the recalled keyframe");
        }
        // The hold (SA12/SA13): a refresh after six still frames made the keyframe track the current frame and the
        // correction an identity, which measured +1..+15 % blotch p90 on the windows the prototype won on. The
        // keyframe must survive the whole post-flick window instead.
        while (state.FramesSinceFlick + 1 < PostFlickMath::kHoldFrames)
        {
            PostFlickMath::BuildFrame(state, W, H, true, 1.0f, descForm(identity), descForm(projection), descForm(identity), outputs);
            need(!outputs.Refresh, "post-flick: the keyframe stays held until the post-flick window is over");
        }
        PostFlickMath::BuildFrame(state, W, H, true, 1.0f, descForm(identity), descForm(projection), descForm(identity), outputs);
        need(outputs.Refresh, "post-flick: the keyframe refreshes once the hold has expired");
        need(state.FramesSinceFlick >= PostFlickMath::kHoldFrames && state.SettledFrames >= PostFlickMath::kSettledFramesNeeded,
            "post-flick: the hold expired only after the still-frame counter filled");
        need(outputs.Prepare[7] == 1.0f, "post-flick: valid history is reported to the age recursion");
        // The angle gate: with the keyframe 30 degrees away the correction is switched off, not applied.
        PostFlickMath::KeyState gateState;
        PostFlickMath::Outputs gateOutputs;
        PostFlickMath::BuildFrame(gateState, W, H, true, 1.0f, descForm(identity), descForm(projection), descForm(identity), gateOutputs);
        PostFlickMath::BuildFrame(gateState, W, H, true, 1.0f, descForm(turned), descForm(projection), descForm(identity), gateOutputs);
        need(gateOutputs.Apply[33] == 0.0f,
            "post-flick: a key-to-current angle past the gate switches the correction off");
        PostFlickMath::BuildFrame(state, W, H, true, 4.0f, descForm(identity), descForm(projection), descForm(identity), outputs);
        need(outputs.Apply[33] == 1.0f, "post-flick: the strength is clamped into the constants");
        // The uploaded relative matrix must move the recall by the analytic shift: with P00 = 1 and P32 = -1 at a
        // depth of 10, a camera moved by +0.5 in world x shifts the recall by 0.5/10 NDC = 37.6 px at this width.
        PostFlickMath::KeyState translated;
        PostFlickMath::Outputs shift;
        PostFlickMath::BuildFrame(translated, W, H, true, 1.0f, descForm(identity), descForm(projection), descForm(identity), shift);
        PostFlickMath::BuildFrame(translated, W, H, true, 1.0f, descForm(moved), descForm(projection), descForm(identity), shift);
        const float* row0 = &shift.Apply[4];
        const float* row3 = &shift.Apply[16];
        const float viewZ = shift.Apply[24] < 0.0f ? -10.0f : 10.0f;
        const auto keyNdc = [&](float viewX) {
            return (row0[0] * viewX + row0[3]) / (row3[0] * viewX + row3[2] * viewZ + row3[3]);
        };
        const auto currentNdc = [&](float viewX) {
            return (viewX * shift.Apply[20] + shift.Apply[22] * viewZ) / (shift.Apply[24] * viewZ);
        };
        const float shiftNdc = keyNdc(10.0f) - currentNdc(10.0f);
        need(std::abs(shiftNdc - 0.05f) < 1e-5f,
            "post-flick: the relative matrix shifts the recall by the analytic 0.05 NDC");
        std::cout << "post-flick relative shift: " << shiftNdc * float(W) * 0.5f << " px at " << W << " wide ("
                  << shiftNdc << " NDC, analytic 0.05)" << std::endl;
        // The production fill, not a hand-written matrix: the conversion desc carries the HLSL column-vector form of
        // the inverses (FSRDFeature_Dx12.cpp transposes on upload and the shipped skin HLSL consumes desc.InvViewMatrix
        // as mul(Matrix, vector)), so FillFromConversion has to return the HLSL forward matrices. The feature calls
        // exactly this function, so a transposed matrix or a wrong projection element fails here, not only in game.
        const DirectX::XMFLOAT4X4 inverseViewHlsl = matrix({1,0,0,0.5f, 0,1,0,0, 0,0,1,0, 0,0,0,1});
        const DirectX::XMFLOAT4X4 inverseProjectionHlsl = matrix({1,0,0,0, 0,1,0,0, 0,0,0,-1, 0,0,1,1});
        DirectX::XMFLOAT4X4 filledView {}, filledProjection {}, filledPrevious {};
        PostFlickMath::FillFromConversion(filledView, filledProjection, filledPrevious,
            {descForm(inverseViewHlsl), descForm(inverseProjectionHlsl), descForm(identity)});
        const auto closeTo = [](const DirectX::XMFLOAT4X4& a, const DirectX::XMFLOAT4X4& b) {
            float worst = 0.0f;
            for (int i = 0; i < 16; ++i)
                worst = std::max(worst, std::abs((&a.m[0][0])[i] - (&b.m[0][0])[i]));
            return worst;
        };
        const auto backToSemantic = [](const DirectX::XMFLOAT4X4& m) {
            DirectX::XMFLOAT4X4 out {};
            DirectX::XMStoreFloat4x4(&out, DirectX::XMMatrixTranspose(DirectX::XMLoadFloat4x4(&m)));
            return out;
        };
        need(closeTo(backToSemantic(filledView), moved) < 1e-6f,
            "post-flick: the conversion fill yields the forward view for a camera at +0.5 world x");
        need(closeTo(backToSemantic(filledProjection), projection) < 1e-6f,
            "post-flick: the conversion fill inverts the projection back to the forward form");
        need(closeTo(filledView, descForm(moved)) < 1e-6f,
            "post-flick: the fill output stays in the desc form the passes load");
        need(closeTo(filledPrevious, descForm(identity)) < 1e-6f,
            "post-flick: the previous view is copied through unchanged");
        PostFlickMath::KeyState filled;
        PostFlickMath::Outputs filledShift;
        PostFlickMath::BuildFrame(filled, W, H, true, 1.0f, descForm(identity), descForm(projection), descForm(identity), filledShift);
        PostFlickMath::BuildFrame(filled, W, H, true, 1.0f, filledView, filledProjection, filledPrevious, filledShift);
        const float* filledRow0 = &filledShift.Apply[4];
        const float* filledRow3 = &filledShift.Apply[16];
        const float filledZ = filledShift.Apply[24] < 0.0f ? -10.0f : 10.0f;
        const auto filledKeyNdc = [&](float viewX) {
            return (filledRow0[0] * viewX + filledRow0[3]) / (filledRow3[0] * viewX + filledRow3[2] * filledZ + filledRow3[3]);
        };
        const auto filledCurrentNdc = [&](float viewX) {
            return (viewX * filledShift.Apply[20] + filledShift.Apply[22] * filledZ) / (filledShift.Apply[24] * filledZ);
        };
        need(std::abs((filledKeyNdc(10.0f) - filledCurrentNdc(10.0f)) - 0.05f) < 1e-5f,
            "post-flick: the conversion fill plus BuildFrame keeps the analytic 0.05 NDC shift");
        std::cout << "post-flick conversion fill: analytic shift ok, forward view matches the HLSL form" << std::endl;
    }
    ComPtr<ID3D12Resource> color, motion, depth, aux[2], key[2], keyAux[2], band, out;
    const auto texture = [&](ComPtr<ID3D12Resource>& target, DXGI_FORMAT format, uint32_t w, uint32_t h, const wchar_t* name) {
        D3D12_RESOURCE_DESC desc {};
        desc.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D; desc.Width = w; desc.Height = h;
        desc.DepthOrArraySize = desc.MipLevels = 1; desc.SampleDesc.Count = 1; desc.Format = format;
        desc.Flags = D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
        D3D12_HEAP_PROPERTIES heap {}; heap.Type = D3D12_HEAP_TYPE_DEFAULT;
        hr(host.device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &desc,
            D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE, nullptr, IID_PPV_ARGS(&target)));
        target->SetName(name);
    };
    texture(color, DXGI_FORMAT_R16G16B16A16_FLOAT, W, H, L"postflick color");
    texture(motion, DXGI_FORMAT_R16G16B16A16_FLOAT, W, H, L"postflick motion");
    texture(depth, DXGI_FORMAT_R32_FLOAT, W, H, L"postflick depth");
    texture(band, DXGI_FORMAT_R16G16B16A16_FLOAT, HW, HH, L"postflick band");
    texture(out, DXGI_FORMAT_R16G16B16A16_FLOAT, W, H, L"postflick output");
    for (uint32_t i = 0; i < 2; ++i)
    {
        texture(aux[i], DXGI_FORMAT_R16G16_FLOAT, HW, HH, L"postflick aux");
        texture(key[i], DXGI_FORMAT_R16G16B16A16_FLOAT, HW, HH, L"postflick key");
        texture(keyAux[i], DXGI_FORMAT_R16G16_FLOAT, HW, HH, L"postflick keyaux");
    }
    Scene dummy(host, 128, 128);
    std::vector<uint16_t> colorData(size_t(W) * H * 4, 0), motionData(size_t(W) * H * 4, 0);
    std::vector<float> depthData(size_t(W) * H, 10.0f);
    for (uint32_t y = 0; y < H; ++y)
        for (uint32_t x = 0; x < W; ++x)
        {
            const size_t p = size_t(y) * W + x;
            const float level = 0.02f + 0.01f * std::sin(x / 37.0f) * std::cos(y / 29.0f);
            colorData[p * 4 + 0] = PackedVector::XMConvertFloatToHalf(level);
            colorData[p * 4 + 1] = PackedVector::XMConvertFloatToHalf(level * 0.9f);
            colorData[p * 4 + 2] = PackedVector::XMConvertFloatToHalf(level * 0.8f);
            colorData[p * 4 + 3] = PackedVector::XMConvertFloatToHalf(1.0f);
            motionData[p * 4 + 3] = PackedVector::XMConvertFloatToHalf(1.0f);
        }
    upload(host, dummy, color.Get(), binary(colorData), D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
    upload(host, dummy, depth.Get(), binary(depthData), D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
    ComPtr<ID3D12RootSignature> prepareRoot, applyRoot;
    ComPtr<ID3D12PipelineState> preparePso, applyPso;
    hr(host.device->CreateRootSignature(0, FSRDPostFlickPrepare_cso, sizeof(FSRDPostFlickPrepare_cso), IID_PPV_ARGS(&prepareRoot)));
    hr(host.device->CreateRootSignature(0, FSRDPostFlickApply_cso, sizeof(FSRDPostFlickApply_cso), IID_PPV_ARGS(&applyRoot)));
    D3D12_COMPUTE_PIPELINE_STATE_DESC pipeline {};
    pipeline.pRootSignature = prepareRoot.Get();
    pipeline.CS = {FSRDPostFlickPrepare_cso, sizeof(FSRDPostFlickPrepare_cso)};
    hr(host.device->CreateComputePipelineState(&pipeline, IID_PPV_ARGS(&preparePso)));
    pipeline.pRootSignature = applyRoot.Get();
    pipeline.CS = {FSRDPostFlickApply_cso, sizeof(FSRDPostFlickApply_cso)};
    hr(host.device->CreateComputePipelineState(&pipeline, IID_PPV_ARGS(&applyPso)));
    // One heap per recorded frame, kept alive until the check ends: a descriptor bound to a command list is never
    // rewritten while that list is in flight, and no heap dies before its submission completes.
    D3D12_DESCRIPTOR_HEAP_DESC heapDesc {};
    heapDesc.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV; heapDesc.NumDescriptors = 16;
    heapDesc.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
    std::vector<ComPtr<ID3D12DescriptorHeap>> heaps;
    const UINT stride = host.device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
    const auto srv = [&](ID3D12Resource* resource, DXGI_FORMAT format, D3D12_CPU_DESCRIPTOR_HANDLE handle) {
        D3D12_SHADER_RESOURCE_VIEW_DESC view {};
        view.Format = format; view.ViewDimension = D3D12_SRV_DIMENSION_TEXTURE2D; view.Texture2D.MipLevels = 1;
        view.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
        host.device->CreateShaderResourceView(resource, &view, handle);
    };
    const auto uav = [&](ID3D12Resource* resource, DXGI_FORMAT format, D3D12_CPU_DESCRIPTOR_HANDLE handle) {
        D3D12_UNORDERED_ACCESS_VIEW_DESC view {};
        view.Format = format; view.ViewDimension = D3D12_UAV_DIMENSION_TEXTURE2D;
        host.device->CreateUnorderedAccessView(resource, nullptr, &view, handle);
    };
    const auto transition = [&](ID3D12Resource* resource, D3D12_RESOURCE_STATES before, D3D12_RESOURCE_STATES after) {
        D3D12_RESOURCE_BARRIER b {};
        b.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        b.Transition = {resource, D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES, before, after};
        host.list->ResourceBarrier(1, &b);
    };
    // The motion only changes when the flick flag changes, so it is uploaded once per configuration instead of
    // per frame (a 29 MB staging upload would otherwise dominate the measurement).
    const auto uploadMotion = [&](bool flick) {
        for (size_t p = 0; p < size_t(W) * H; ++p)
            motionData[p * 4 + 2] = PackedVector::XMConvertFloatToHalf(flick ? 5.0f : 0.0f);
        upload(host, dummy, motion.Get(), binary(motionData), D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
    };
    uploadMotion(false);
    uint32_t parity = 0;
    const auto frame = [&](const PostFlickMath::Outputs& outputs) {
        ComPtr<ID3D12DescriptorHeap> heap;
        hr(host.device->CreateDescriptorHeap(&heapDesc, IID_PPV_ARGS(&heap)));
        heaps.push_back(heap);
        ID3D12DescriptorHeap* bound[] {heap.Get()};
        host.list->SetDescriptorHeaps(1, bound);
        // Everything written below starts the frame readable; declare that before the UAV writes.
        for (auto* resource : {band.Get(), key[parity ^ 1u].Get(), aux[parity ^ 1u].Get(), keyAux[parity ^ 1u].Get()})
            transition(resource, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE, D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
        auto cpu = heap->GetCPUDescriptorHandleForHeapStart();
        auto gpu = heap->GetGPUDescriptorHandleForHeapStart();
        host.list->SetPipelineState(preparePso.Get()); host.list->SetComputeRootSignature(prepareRoot.Get());
        srv(color.Get(), DXGI_FORMAT_R16G16B16A16_FLOAT, cpu); cpu.ptr += stride;
        srv(motion.Get(), DXGI_FORMAT_R16G16B16A16_FLOAT, cpu); cpu.ptr += stride;
        srv(depth.Get(), DXGI_FORMAT_R32_FLOAT, cpu); cpu.ptr += stride;
        srv(aux[parity].Get(), DXGI_FORMAT_R16G16_FLOAT, cpu); cpu.ptr += stride;
        srv(key[parity].Get(), DXGI_FORMAT_R16G16B16A16_FLOAT, cpu); cpu.ptr += stride;
        srv(keyAux[parity].Get(), DXGI_FORMAT_R16G16_FLOAT, cpu); cpu.ptr += stride;
        uav(band.Get(), DXGI_FORMAT_R16G16B16A16_FLOAT, cpu); cpu.ptr += stride;
        uav(key[parity ^ 1u].Get(), DXGI_FORMAT_R16G16B16A16_FLOAT, cpu); cpu.ptr += stride;
        uav(aux[parity ^ 1u].Get(), DXGI_FORMAT_R16G16_FLOAT, cpu); cpu.ptr += stride;
        uav(keyAux[parity ^ 1u].Get(), DXGI_FORMAT_R16G16_FLOAT, cpu);
        host.list->SetComputeRootDescriptorTable(1, gpu);
        D3D12_GPU_DESCRIPTOR_HANDLE uavTable = gpu; uavTable.ptr += uint64_t(6) * stride;
        host.list->SetComputeRootDescriptorTable(2, uavTable);
        host.list->SetComputeRoot32BitConstants(0, 8, outputs.Prepare, 0);
        host.list->Dispatch((HW + 7) / 8, (HH + 7) / 8, 1);
        transition(band.Get(), D3D12_RESOURCE_STATE_UNORDERED_ACCESS, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
        transition(key[parity ^ 1u].Get(), D3D12_RESOURCE_STATE_UNORDERED_ACCESS, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
        transition(aux[parity ^ 1u].Get(), D3D12_RESOURCE_STATE_UNORDERED_ACCESS, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
        transition(keyAux[parity ^ 1u].Get(), D3D12_RESOURCE_STATE_UNORDERED_ACCESS, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
        host.list->SetPipelineState(applyPso.Get()); host.list->SetComputeRootSignature(applyRoot.Get());
        cpu = heap->GetCPUDescriptorHandleForHeapStart(); cpu.ptr += uint64_t(10) * stride;
        gpu = heap->GetGPUDescriptorHandleForHeapStart(); gpu.ptr += uint64_t(10) * stride;
        srv(color.Get(), DXGI_FORMAT_R16G16B16A16_FLOAT, cpu); cpu.ptr += stride;
        srv(aux[parity ^ 1u].Get(), DXGI_FORMAT_R16G16_FLOAT, cpu); cpu.ptr += stride;
        srv(band.Get(), DXGI_FORMAT_R16G16B16A16_FLOAT, cpu); cpu.ptr += stride;
        srv(key[parity ^ 1u].Get(), DXGI_FORMAT_R16G16B16A16_FLOAT, cpu); cpu.ptr += stride;
        srv(keyAux[parity ^ 1u].Get(), DXGI_FORMAT_R16G16_FLOAT, cpu); cpu.ptr += stride;
        transition(out.Get(), D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE, D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
        uav(out.Get(), DXGI_FORMAT_R16G16B16A16_FLOAT, cpu);
        host.list->SetComputeRootDescriptorTable(1, gpu);
        uavTable = gpu; uavTable.ptr += uint64_t(5) * stride;
        host.list->SetComputeRootDescriptorTable(2, uavTable);
        host.list->SetComputeRoot32BitConstants(0, 36, outputs.Apply, 0);
        host.list->Dispatch((W + 7) / 8, (H + 7) / 8, 1);
        transition(out.Get(), D3D12_RESOURCE_STATE_UNORDERED_ACCESS, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
        parity ^= 1u;
    };
    const auto halfAt = [](const uint8_t* p, int c) {
        const uint16_t word = uint16_t(p[2 * c] | (p[2 * c + 1] << 8));
        return DirectX::PackedVector::XMConvertHalfToFloat(word);
    };
    // B) a frame without history returns the input byte-identically.
    PostFlickMath::KeyState state;
    PostFlickMath::Outputs outputs;
    PostFlickMath::BuildFrame(state, W, H, false, 1.0f, descForm(identity), descForm(projection), descForm(identity), outputs);
    frame(outputs);
    auto first = snapshot(host, out.Get(), D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
    host.submit();
    need(packed(first, W, H, 8) == binary(colorData),
        "post-flick: a frame without history returns the input byte-identically");
    std::cout << "post-flick frame 0 identical: ok" << std::endl;
    host.reset();
    // C) the reprojection: the keyframe band gets a spike, the camera then moves, and the spike has to come back
    // where the matrix says. The second frame does not refresh the keyframe (only two settled frames have passed).
    {
        const uint32_t spikeX = 200, spikeY = 300;
        std::vector<uint16_t> keyData(size_t(HW) * HH * 4, 0), keyAuxData(size_t(HW) * HH * 2, 0);
        for (size_t p = 0; p < size_t(HW) * HH; ++p)
        {
            keyData[p * 4 + 0] = PackedVector::XMConvertFloatToHalf(0.02f);
            keyData[p * 4 + 1] = PackedVector::XMConvertFloatToHalf(0.018f);
            keyData[p * 4 + 2] = PackedVector::XMConvertFloatToHalf(0.016f);
            keyData[p * 4 + 3] = PackedVector::XMConvertFloatToHalf(0.02f);
            keyAuxData[p * 2 + 0] = PackedVector::XMConvertFloatToHalf(10.0f);
            keyAuxData[p * 2 + 1] = PackedVector::XMConvertFloatToHalf(1.0f);
        }
        for (int dy = -1; dy <= 1; ++dy)
            for (int dx = -1; dx <= 1; ++dx)
            {
                const size_t p = size_t(int(spikeY) + dy) * HW + size_t(int(spikeX) + dx);
                keyData[p * 4 + 0] = PackedVector::XMConvertFloatToHalf(0.52f);
                keyData[p * 4 + 1] = PackedVector::XMConvertFloatToHalf(0.51f);
                keyData[p * 4 + 2] = PackedVector::XMConvertFloatToHalf(0.50f);
            }
        upload(host, dummy, key[parity].Get(), binary(keyData), D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
        upload(host, dummy, keyAux[parity].Get(), binary(keyAuxData), D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
        host.submit(); host.reset();
        PostFlickMath::Outputs recall;
        PostFlickMath::BuildFrame(state, W, H, true, 1.0f, descForm(moved), descForm(projection), descForm(identity), recall);
        need(!recall.Refresh, "post-flick: the recall frame keeps the keyframe it was given");
        frame(recall);
        auto readback = snapshot(host, out.Get(), D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
        host.submit();
        const auto data = packed(readback, W, H, 8);
        host.reset();
        const float* row0 = &recall.Apply[4];
        const float* row3 = &recall.Apply[16];
        const float viewZ = recall.Apply[24] < 0.0f ? -10.0f : 10.0f;
        const auto keyNdc = [&](float viewX) {
            return (row0[0] * viewX + row0[3]) / (row3[0] * viewX + row3[2] * viewZ + row3[3]);
        };
        const auto currentNdc = [&](float viewX) {
            return (viewX * recall.Apply[20] + recall.Apply[22] * viewZ) / (recall.Apply[24] * viewZ);
        };
        const float shiftPixels = (keyNdc(10.0f) - currentNdc(10.0f)) * float(W) * 0.5f;
        const float spikeFullX = float(spikeX) * 2.0f + 1.0f, spikeFullY = float(spikeY) * 2.0f + 1.0f;
        const float expectedX = spikeFullX - shiftPixels, expectedY = spikeFullY;
        float best = -1.0f; int bestX = -1, bestY = -1;
        for (uint32_t y = 0; y < H; ++y)
            for (uint32_t x = 0; x < W; ++x)
            {
                const uint8_t* p = data.data() + (size_t(y) * W + x) * 8;
                const uint8_t* q = reinterpret_cast<const uint8_t*>(colorData.data()) + (size_t(y) * W + x) * 8;
                const float deviation = std::abs(halfAt(p, 0) - halfAt(q, 0)) + std::abs(halfAt(p, 1) - halfAt(q, 1)) +
                    std::abs(halfAt(p, 2) - halfAt(q, 2));
                if (deviation > best) { best = deviation; bestX = int(x); bestY = int(y); }
            }
        std::cout << "post-flick recall spike at " << bestX << "," << bestY << " deviation " << best
                  << " (expected " << expectedX << "," << expectedY << ", shift " << shiftPixels << " px)" << std::endl;
        need(best > 0.2f, "post-flick: the recalled band shows up in the output");
        need(std::abs(float(bestX) - expectedX) <= 2.0f && std::abs(float(bestY) - expectedY) <= 2.0f,
            "post-flick: the recalled spike lands at the reprojected pixel");
        need(std::abs(float(bestX) - spikeFullX) > 5.0f, "post-flick: the recall is reprojected, not sampled in place");
    }
    // D) the cost of the real pass pair at the user's resolution.
    std::vector<double> samples;
    PostFlickMath::Outputs cost;
    PostFlickMath::BuildFrame(state, W, H, true, 1.0f, descForm(identity), descForm(projection), descForm(identity), cost);
    for (uint32_t batch = 0; batch < 12; ++batch)
    {
        for (uint32_t repetition = 0; repetition < 8; ++repetition) frame(cost);
        const auto start = std::chrono::steady_clock::now();
        host.submit();
        samples.push_back(std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - start).count() / 8.0);
        host.reset();
    }
    std::sort(samples.begin(), samples.end());
    std::cout << "post-flick cost at " << W << "x" << H << ": median " << samples[samples.size() / 2]
              << " ms per frame (prepare + apply), p10 " << samples[samples.size() / 10] << " ms" << std::endl;
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
    postFlickChecks(host);
    timingChecks(host);
    const auto frames=job.at("frames");
    auto family=MakeOwnedShared<LobeRecovery::Family>(); FlatAlbedoRecovery helper;
    FlatAlbedoSettings settings; settings.enabled=true;
    // Task 24 A/B: the same chain with "NZR on vertical surfaces" enabled, for gate/byte comparisons
    // against the default (0) run. Unset means 0, so the default test path is unchanged.
    if (const char* knob=std::getenv("FSRD24_GLASS_MODE")) settings.verticalMode=uint32_t(std::atoi(knob));
    if (const char* knob=std::getenv("FSRD24_GLASS_STRENGTH")) settings.verticalStrength=float(std::atof(knob));
    // Task 24 fixture-only: a strength above 1 asks the pass for its diagnostic dump (age/gate/motion).
    // Task 24 A/B: reproduce the user's bridge configuration (Reflection history, Temporal off, diffuse from RR)
    // so the recorded post-RR path (and mode 3, which rides the polish pass) can be replayed with real cameras.
    if (const char* knob=std::getenv("FSRD24_REFLECT"))
    {
        settings.reflectionHistory=std::atoi(knob)!=0;
        settings.temporal=!settings.reflectionHistory;
        settings.diffuseRR=settings.reflectionHistory;
    }
    if (const char* knob=std::getenv("FSRD24_POLISH")) settings.reflectionPolish=float(std::atof(knob));
    if (const char* knob=std::getenv("FSRD24_GLASS_DEBUG")) if(std::atoi(knob)) settings.verticalStrength=1.5f;
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
        // Optional camera for the reflection-history path (identity matrices keep the plain path unchanged).
        if (row.contains("view") && row.contains("projection"))
        {
            const auto view=row.at("view").get<std::vector<double>>(), projection=row.at("projection").get<std::vector<double>>();
            need(view.size()==16 && projection.size()==16,"camera matrices are 4x4");
            for (int i=0;i<16;++i) { frame.view[i]=view[i]; frame.projection[i]=projection[i]; }
            frame.camera=row.value("camera",true);
        }
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
