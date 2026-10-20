#pragma once
#include "FSRDNrdBridge_Types.h"
#include "resource_tracking/FrameSurvey_Dx12.h"
#include <array>
#include <span>
#include <string_view>

namespace NrdBridge
{
// Shared by the live coordinator and the offline capture replay. No COM calls, retention,
// GPU commands, shader-prefix matching, or fixed iteration counts belong in this state machine.
struct ShaderRole
{
    std::string_view sha256;
    Role role;
};
inline constexpr std::array<ShaderRole,12> ShaderRoles {{
    {"88c255d29535f9153f7101c32be4f58682675fb8391c94efc135fd6959875e6d",Role::MaterialRead},
    {"3e09f2e0d948f77869a0628524c14463e1fdb06fcfb78aa60fc102c78fb0d5ed",Role::MaterialGuide},
    {"87d570aa46a3823e9c4468b0ba2c7050364d95cec8c4f9a04eb282dfa0240f80",Role::PrepLast},
    {"ec37e0d8a2672d515a807ce0712737c1b186adfebf5530dd260d2b624877771e",Role::Recon},
    {"442e2282fcde781030081198a587d168d46b5ab9f89f79d6d6abcbf163b24d9e",Role::PrePass},
    {"bedaacc6ed20e5e58466cc0554fa76c75af77c4eeae8365bc125a00e74cc84e7",Role::Temporal},
    {"ae32cf5bc74700974705f663564a25852ead4e868a68ac99129e0c48c22c27e4",Role::Chain3},
    {"3481ae50aabac2df8db729e5c85ef3475e2a9b3674977b19bb1742711ae90272",Role::HistSave},
    {"fae82770bc4908c4af70d3d7e59c708d5b452ffb304acaac6583deee6aa4d1d1",Role::HistFix},
    {"6697417c7af7a68327926b219a00375f40444aede296bf70eeae6a28b40c6c68",Role::Clamp},
    {"4ea298c92031469159006a452627df72ef4fd2694f80222c6339832cd791b3dc",Role::ATrous},
    {"c3f6fb8ea6fa6c4caab252b8b33ff5b7c5fba4273a1b62444f38b7a91b1f19d0",Role::Consumer}
}};
inline Role IdentifyRole(std::string_view hash) noexcept
{
    for (const auto& entry : ShaderRoles) if (hash == entry.sha256) return entry.role;
    return Role::None;
}
inline bool SameResources(const Resources& a, const Resources& b) noexcept
{
    return a.inputSpec == b.inputSpec && a.inputDiff == b.inputDiff && a.normals == b.normals &&
        a.viewDepth == b.viewDepth && a.reconSpec == b.reconSpec && a.reconDiff == b.reconDiff &&
        a.motion == b.motion && a.outputSpec == b.outputSpec && a.outputDiff == b.outputDiff &&
        a.width == b.width && a.height == b.height;
}
// Temporal identity belongs to the lighting signals/output profile. Recon guides
// may use different live textures each frame; their exact type/extent is checked
// by that recording's ChainDiscovery, and conversion uses those current guides.
inline bool SameSignalProfile(const Resources& a, const Resources& b) noexcept
{
    return a.inputSpec == b.inputSpec && a.inputDiff == b.inputDiff &&
        a.reconSpec == b.reconSpec && a.reconDiff == b.reconDiff && a.motion == b.motion &&
        a.outputSpec == b.outputSpec && a.outputDiff == b.outputDiff && a.width == b.width && a.height == b.height;
}
inline bool UsesResource(const Resources& resources, const void* object) noexcept
{
    return object && (resources.inputSpec == object || resources.inputDiff == object ||
        resources.normals == object || resources.viewDepth == object || resources.reconSpec == object ||
        resources.reconDiff == object || resources.motion == object || resources.outputSpec == object ||
        resources.outputDiff == object);
}

class ChainDiscovery
{
    using Bound = FrameSurvey::BoundResource;
    enum class Stage { Empty, ChainA, ChainB, Complete, Invalid };
    Stage stage_ = Stage::Empty;
    Resources resources_ {};
    std::array<Bound,9> bindings_ {};
    Bound lastSpec_ {}, lastDiff_ {};
    bool temporal_ = false, atrous_ = false;
    uint32_t atrousCount_ = 0;
    static const Bound* At(std::span<const Bound> table, uint32_t offset,
                          D3D12_DESCRIPTOR_RANGE_TYPE kind) noexcept
    {
        const Bound* result = nullptr;
        for (const auto& view : table)
            if (view.descriptorOffset == offset && view.kind == kind)
            { if (result) return nullptr; result = &view; }
        return result;
    }
    bool Fail(std::string& error, const char* reason)
    {
        stage_ = Stage::Invalid; error = reason; return false;
    }
    bool Texture(const Bound* view, DXGI_FORMAT format, const char* reason, std::string& error)
    {
        if (!view || !view->resource || view->viewFormat != format || view->description.Format != format ||
            view->description.Dimension != D3D12_RESOURCE_DIMENSION_TEXTURE2D ||
            view->description.DepthOrArraySize != 1 || view->description.SampleDesc.Count != 1 ||
            view->subresource != 0 || !view->description.Width || view->description.Width > UINT32_MAX ||
            !view->description.Height || (resources_.width &&
                (view->description.Width != resources_.width || view->description.Height != resources_.height)))
            return Fail(error,reason);
        return true;
    }
  public:
    bool Begin(std::span<const Bound> srv, std::span<const Bound> uav, std::string& error)
    {
        *this = {};
        const auto inputSpec = At(srv,0,D3D12_DESCRIPTOR_RANGE_TYPE_SRV);
        if (!Texture(inputSpec,DXGI_FORMAT_R16G16B16A16_FLOAT,"Recon p1 +0: invalid specular signal",error)) return false;
        resources_.width = uint32_t(inputSpec->description.Width); resources_.height = inputSpec->description.Height;
        const std::array<const Bound*,6> views {inputSpec,At(srv,1,D3D12_DESCRIPTOR_RANGE_TYPE_SRV),
            At(srv,2,D3D12_DESCRIPTOR_RANGE_TYPE_SRV),At(srv,3,D3D12_DESCRIPTOR_RANGE_TYPE_SRV),
            At(uav,0,D3D12_DESCRIPTOR_RANGE_TYPE_UAV),At(uav,1,D3D12_DESCRIPTOR_RANGE_TYPE_UAV)};
        constexpr std::array<DXGI_FORMAT,6> formats {DXGI_FORMAT_R16G16B16A16_FLOAT,DXGI_FORMAT_R16G16B16A16_FLOAT,
            DXGI_FORMAT_R10G10B10A2_UNORM,DXGI_FORMAT_R32_FLOAT,DXGI_FORMAT_R16G16B16A16_FLOAT,DXGI_FORMAT_R16G16B16A16_FLOAT};
        constexpr std::array<const char*,6> reasons {"Recon p1 +0: invalid specular signal","Recon p1 +1: invalid diffuse signal",
            "Recon p1 +2: invalid normal/roughness","Recon p1 +3: invalid positive view depth",
            "Recon p5 +0: invalid reconstructed specular signal","Recon p5 +1: invalid reconstructed diffuse signal"};
        for (size_t i=0;i<views.size();++i)
        {
            if (!Texture(views[i],formats[i],reasons[i],error)) return false;
            bindings_[i] = *views[i];
        }
        if (views[0]->resource == views[1]->resource || views[4]->resource == views[5]->resource)
            return Fail(error,"Recon specular and diffuse resources alias");
        if (!(views[4]->description.Flags & D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS) ||
            !(views[5]->description.Flags & D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS))
            return Fail(error,"Recon outputs do not allow UAV access");
        resources_.inputSpec = views[0]->resource; resources_.inputDiff = views[1]->resource;
        resources_.normals = views[2]->resource; resources_.viewDepth = views[3]->resource;
        resources_.reconSpec = views[4]->resource; resources_.reconDiff = views[5]->resource;
        stage_ = Stage::ChainA; return true;
    }
    bool Observe(Role role, std::span<const Bound> srv, std::span<const Bound> uav,
                 ID3D12Resource* knownMotion, std::string& error)
    {
        if (stage_ == Stage::Empty || stage_ == Stage::Invalid || stage_ == Stage::Complete) return false;
        if (role == Role::PrePass && stage_ == Stage::ChainA && atrous_)
            stage_ = Stage::ChainB; // The first PrePass after chain A's final ATrous starts chain B.
        if (role == Role::Temporal && stage_ == Stage::ChainA && !temporal_)
        {
            const auto motion = At(srv,2,D3D12_DESCRIPTOR_RANGE_TYPE_SRV);
            if (!Texture(motion,DXGI_FORMAT_R16G16B16A16_FLOAT,"Temporal p1 +2: invalid motion vectors",error)) return false;
            if (knownMotion && motion->resource != knownMotion) return Fail(error,"Temporal motion differs from Streamline MotionVectors tag");
            resources_.motion = motion->resource; bindings_[6] = *motion; temporal_ = true;
        }
        if (role == Role::ATrous && stage_ == Stage::ChainA)
        {
            if (!temporal_) return Fail(error,"Chain A ATrous arrived without its Temporal motion binding");
            const auto spec = At(uav,0,D3D12_DESCRIPTOR_RANGE_TYPE_UAV), diff = At(uav,1,D3D12_DESCRIPTOR_RANGE_TYPE_UAV);
            if (!Texture(spec,DXGI_FORMAT_R16G16B16A16_FLOAT,"ATrous p5 +0: invalid specular output",error) ||
                !Texture(diff,DXGI_FORMAT_R16G16B16A16_FLOAT,"ATrous p5 +1: invalid diffuse output",error)) return false;
            lastSpec_ = *spec; lastDiff_ = *diff; atrous_ = true; ++atrousCount_;
        }
        if (role != Role::Consumer) return true;
        if (!temporal_ || !atrous_) return Fail(error,"Consumer arrived before chain A Temporal/ATrous");
        const auto diff = At(uav,0,D3D12_DESCRIPTOR_RANGE_TYPE_UAV), spec = At(uav,1,D3D12_DESCRIPTOR_RANGE_TYPE_UAV);
        if (!Texture(diff,DXGI_FORMAT_R16G16B16A16_FLOAT,"Consumer p5 +0: invalid diffuse output",error) ||
            !Texture(spec,DXGI_FORMAT_R16G16B16A16_FLOAT,"Consumer p5 +1: invalid specular output",error)) return false;
        if (diff->resource != lastDiff_.resource || spec->resource != lastSpec_.resource)
            return Fail(error,"Consumer pair differs from reversed last chain A ATrous pair");
        if (diff->resource == spec->resource || UsesResource(resources_,diff->resource) || UsesResource(resources_,spec->resource))
            return Fail(error,"Consumer outputs alias a discovered input or each other");
        const auto outputFlags = D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS | D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET;
        if ((diff->description.Flags & outputFlags) != outputFlags || (spec->description.Flags & outputFlags) != outputFlags)
            return Fail(error,"Consumer output textures do not allow RT/UAV access");
        resources_.outputDiff = diff->resource; resources_.outputSpec = spec->resource;
        bindings_[7] = *spec; bindings_[8] = *diff; stage_ = Stage::Complete; return true;
    }
    bool Released(const void* object) noexcept
    {
        if (UsesResource(resources_,object) || lastSpec_.resource == object || lastDiff_.resource == object)
        { stage_ = Stage::Invalid; return true; }
        return false;
    }
    bool Valid() const noexcept { return stage_ != Stage::Empty && stage_ != Stage::Invalid; }
    bool Complete() const noexcept { return stage_ == Stage::Complete; }
    const Resources& Get() const noexcept { return resources_; }
    std::array<ID3D12Resource*,11> ReferencedResources() const noexcept
    {
        return {resources_.inputSpec,resources_.inputDiff,resources_.normals,resources_.viewDepth,
            resources_.reconSpec,resources_.reconDiff,resources_.motion,resources_.outputSpec,resources_.outputDiff,
            lastSpec_.resource,lastDiff_.resource};
    }
    std::array<NrdBridgeBirth::Token,11> ReferencedResourceBirths() const noexcept
    {
        return {bindings_[0].resourceBirth,bindings_[1].resourceBirth,bindings_[2].resourceBirth,bindings_[3].resourceBirth,
            bindings_[4].resourceBirth,bindings_[5].resourceBirth,bindings_[6].resourceBirth,bindings_[7].resourceBirth,bindings_[8].resourceBirth,
            lastSpec_.resourceBirth,lastDiff_.resourceBirth};
    }
    const std::array<Bound,9>& Bindings() const noexcept { return bindings_; }
    uint32_t ChainAIterations() const noexcept { return atrousCount_; } // Diagnostics only.
};

class DiscoveryCache
{
    Resources resources_ {};
    bool valid_ = false;
    uint32_t missingRecon_ = 0;
    uint64_t generation_ = 0;
  public:
    bool Publish(const ChainDiscovery& chain) noexcept
    {
        if (!chain.Complete()) return false;
        const bool changed = !valid_ || !SameSignalProfile(resources_,chain.Get());
        resources_ = chain.Get(); valid_ = true; missingRecon_ = 0;
        if (changed) ++generation_;
        return changed;
    }
    void Invalidate() noexcept { resources_ = {}; valid_ = false; missingRecon_ = 0; ++generation_; }
    bool Released(const void* object) noexcept
    {
        if (!valid_ || !UsesResource(resources_,object)) return false;
        Invalidate(); return true;
    }
    bool Frame(bool observedRecon) noexcept
    {
        if (observedRecon) missingRecon_ = 0;
        else if (valid_ && ++missingRecon_ >= 30) { Invalidate(); return true; }
        return false;
    }
    bool Valid() const noexcept { return valid_; }
    uint64_t Generation() const noexcept { return generation_; }
    const Resources& Get() const noexcept { return resources_; }
};
}
