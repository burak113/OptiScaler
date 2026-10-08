#pragma once

#include <d3d12.h>
#include <dxgi1_4.h>
#include <wrl/client.h>
#include <ffx_api.h>
#include <dx12/ffx_api_dx12.h>
#include <fsr-rr/ffx_denoiser.h>
#include <json.hpp>
#include <array>
#include <atomic>
#include <cmath>
#include <cstddef>
#include <cstring>
#include <functional>
#include <limits>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>
#include "proxies/FfxApi_Proxy.h"
#include "misc/FfxContextOwner.h"
#include "misc/SkipSpoof.h"
#include "resource_tracking/ResTrack_Dx12.h"
#include "shaders/fsrd_preprocess/FSRDGameTraceSession.h"
#include "shaders/fsrd_preprocess/RRTraceAdditiveIO.h"
#include "gpu_time/FSRDStageTimings_Dx12.h"

namespace FSRD::FullContextReference
{
// These are the original native control bytes, including their float bit patterns.
// Resource bindings and linked header pointers are deliberately outside this segment.
inline constexpr size_t ControlOffset = offsetof(ffxDispatchDescDenoiser, motionVectorScale);
inline constexpr size_t ControlBytes = sizeof(ffxDispatchDescDenoiser) - ControlOffset;
inline constexpr size_t FlagsOffset = offsetof(ffxDispatchDescDenoiser, flags) - ControlOffset;
static_assert(sizeof(ffxDispatchDescDenoiser) == 448 && ControlOffset == 264);
static_assert(ControlBytes == 184 && FlagsOffset == 180);

inline bool OnlyResetControlChanged(const ffxDispatchDescDenoiser& original,
                                   const ffxDispatchDescDenoiser& reference) noexcept
{
    const auto* a = reinterpret_cast<const unsigned char*>(&original) + ControlOffset;
    const auto* b = reinterpret_cast<const unsigned char*>(&reference) + ControlOffset;
    return std::memcmp(a, b, FlagsOffset) == 0 &&
           reference.flags == (original.flags | FFX_DENOISER_DISPATCH_RESET);
}

inline bool ValidMemoryCounters(uint64_t total, uint64_t aliasable) noexcept
{
    // RETURN_OK alone does not make a counter usable. In particular, an SDK
    // signed-underflow bit pattern must not become plausible exabytes in JSON.
    return total != 0 && total <= uint64_t(INT64_MAX) && aliasable <= total;
}

inline std::string ControlWordsHex(const ffxDispatchDescDenoiser& desc)
{
    constexpr char hex[] = "0123456789abcdef";
    const auto* bytes = reinterpret_cast<const unsigned char*>(&desc) + ControlOffset;
    std::string result(ControlBytes * 2, '0');
    for (size_t i = 0; i < ControlBytes; ++i)
    {
        result[2 * i] = hex[bytes[i] >> 4];
        result[2 * i + 1] = hex[bytes[i] & 15];
    }
    return result;
}

inline bool SameNativeDescription(const D3D12_RESOURCE_DESC& a, const D3D12_RESOURCE_DESC& b) noexcept
{
    return a.Dimension == b.Dimension && a.Alignment == b.Alignment && a.Width == b.Width &&
           a.Height == b.Height && a.DepthOrArraySize == b.DepthOrArraySize &&
           a.MipLevels == b.MipLevels && a.Format == b.Format &&
           a.SampleDesc.Count == b.SampleDesc.Count && a.SampleDesc.Quality == b.SampleDesc.Quality &&
           a.Layout == b.Layout && a.Flags == b.Flags;
}

inline nlohmann::json NativeDescription(const D3D12_RESOURCE_DESC& d)
{
    return {{"dimension", uint32_t(d.Dimension)}, {"alignment", d.Alignment}, {"width", d.Width},
            {"height", d.Height}, {"depth_or_array_size", d.DepthOrArraySize}, {"mip_levels", d.MipLevels},
            {"format", uint32_t(d.Format)}, {"sample_count", d.SampleDesc.Count},
            {"sample_quality", d.SampleDesc.Quality}, {"layout", uint32_t(d.Layout)}, {"flags", uint32_t(d.Flags)}};
}

inline nlohmann::json FfxDescription(const FfxApiResourceDescription& d)
{
    return {{"type", d.type}, {"format", d.format}, {"width_or_size", d.width},
            {"height_or_stride", d.height}, {"depth_or_alignment", d.depth},
            {"mip_count", d.mipCount}, {"flags", d.flags}, {"usage", d.usage}};
}

inline void RebuildResetDispatch(const ffxDispatchDescDenoiser& original,
                                const ffxDispatchDescDenoiserDirectDiffuse& originalDiffuse,
                                const ffxDispatchDescDenoiserIndirectSpecular& originalSpecular,
                                const std::array<ID3D12Resource*, 7>& inputs,
                                ID3D12Resource* diffuseOutput, ID3D12Resource* specularOutput,
                                ffxDispatchDescDenoiser& reference,
                                ffxDispatchDescDenoiserDirectDiffuse& diffuse,
                                ffxDispatchDescDenoiserIndirectSpecular& specular) noexcept
{
    reference = original;
    diffuse = originalDiffuse;
    specular = originalSpecular;
    reference.header.pNext = &diffuse.header;
    diffuse.header.pNext = &specular.header;
    specular.header.pNext = nullptr;
    reference.linearDepth.resource = inputs[0];
    reference.motionVectors.resource = inputs[1];
    reference.normals.resource = inputs[2];
    reference.specularAlbedo.resource = inputs[3];
    reference.diffuseAlbedo.resource = inputs[4];
    diffuse.signal.input.resource = inputs[5];
    specular.signal.input.resource = inputs[6];
    diffuse.signal.output.resource = diffuseOutput;
    specular.signal.output.resource = specularOutput;
    reference.flags |= FFX_DENOISER_DISPATCH_RESET;
}

// Native copy primitive kept separate for a focused source-extracted WARP test.
// The caller validates descriptors/identity and admits complete leases first.
inline void RecordFullInputSnapshot(ID3D12GraphicsCommandList* list,
                                    const std::array<ID3D12Resource*, 7>& sources,
                                    const std::array<ID3D12Resource*, 7>& clones) noexcept
{
    constexpr D3D12_RESOURCE_STATES read = D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE |
                                          D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE;
    std::array<D3D12_RESOURCE_BARRIER, 14> barriers {};
    for (size_t i = 0; i < sources.size(); ++i)
    {
        barriers[2 * i].Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        barriers[2 * i].Transition = {sources[i], 0, read, D3D12_RESOURCE_STATE_COPY_SOURCE};
        barriers[2 * i + 1].Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        barriers[2 * i + 1].Transition = {clones[i], 0, read, D3D12_RESOURCE_STATE_COPY_DEST};
    }
    list->ResourceBarrier(UINT(barriers.size()), barriers.data());
    for (size_t i = 0; i < sources.size(); ++i)
    {
        D3D12_TEXTURE_COPY_LOCATION src {}, dst {};
        src.pResource = sources[i]; src.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        dst.pResource = clones[i]; dst.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        // Full mip0 words, independent of readback ROI and logical render extent.
        list->CopyTextureRegion(&dst, 0, 0, 0, &src, nullptr);
    }
    for (auto& barrier : barriers)
        std::swap(barrier.Transition.StateBefore, barrier.Transition.StateAfter);
    list->ResourceBarrier(UINT(barriers.size()), barriers.data());
}
}

// Diagnostic only: this context never supplies a texture or a history decision to
// the primary renderer. A source admission, clone, route, or SDK failure closes the
// capture; it cannot request a primary reset/recreation or turn on a workaround.
class FSRDFullContextReferenceDx12
{
  public:
    using Json = nlohmann::json;
    using Resource = Microsoft::WRL::ComPtr<ID3D12Resource>;
    struct Configuration
    {
        ffxContext primaryContext = nullptr;
        uint64_t primaryContextGeneration = 0;
        ffxCreateContextDescDenoiser acceptedCreate {};
        uint64_t providerId = 0;
        Json createContract;
        std::array<float, 6> tuning {};
        FfxApiFloatBounds debugDepthBounds {};
        std::string captureId;
    };
    struct DiagnosticResult
    {
        std::array<FSRDGameTraceSession::DiagnosticSource, 2> outputs;
        std::string boundaryJson;
    };
    using Adopt = std::function<std::shared_ptr<FfxContextOwner>(ffxContext)>;
    using Retain = std::function<bool(const std::shared_ptr<FfxContextOwner>&)>;

    bool PrepareSnapshot(ID3D12Device* device, ID3D12GraphicsCommandList* list,
                         const Configuration& config, const ffxDispatchDescDenoiser& primary,
                         uint64_t primaryEvaluation, const std::string& primaryBoundary,
                         Adopt adopt, Retain retain) noexcept
    {
        try
        {
            m_prepared = m_executed = false;
            m_failure.clear();
            ValidateConfiguration(device, list, config, primary);
            const auto& originalDiffuse = *reinterpret_cast<const ffxDispatchDescDenoiserDirectDiffuse*>(primary.header.pNext);
            const auto& originalSpecular = *reinterpret_cast<const ffxDispatchDescDenoiserIndirectSpecular*>(originalDiffuse.header.pNext);
            const std::array<FfxApiResource, 7> sourceBindings {{primary.linearDepth, primary.motionVectors,
                primary.normals, primary.specularAlbedo, primary.diffuseAlbedo,
                originalDiffuse.signal.input, originalSpecular.signal.input}};
            const std::array<FfxApiResource, 2> outputBindings {{originalDiffuse.signal.output, originalSpecular.signal.output}};
            ValidateBindings(device, config, sourceBindings, outputBindings);
            const auto primaryRoute = Attestation(config.primaryContext);
            CheckObserved(primaryRoute, "configure", false);

            if (!m_storage || m_captureId != config.captureId ||
                m_primaryGeneration != config.primaryContextGeneration)
            {
                // Older recordings/submissions retain the old storage independently.
                m_storage.reset();
                m_context = nullptr;
                m_invocations = 0;
                CreateStorage(device, config, sourceBindings, outputBindings, primaryRoute, adopt);
                m_captureId = config.captureId;
                m_primaryGeneration = config.primaryContextGeneration;
                m_config = config;
            }
            else if (m_config.createContract != config.createContract)
                throw std::runtime_error("Accepted RR create contract changed during full-context reference capture");

            Configure(config);
            const auto referenceRoute = Attestation(m_context);
            CheckSameImplementation(primaryRoute, referenceRoute);
            CheckObserved(referenceRoute, "configure", true);
            if (!retain || !retain(m_storage->owner))
                throw std::runtime_error("Full-context reference provider lease could not be admitted");

            m_primary = primary;
            m_primary.header.pNext = nullptr; // Never retain a pointer to the caller's local chain.
            m_primaryEvaluation = primaryEvaluation;
            m_primaryBoundary = Json::parse(primaryBoundary);
            if (m_primaryBoundary.at("evaluation_id") != primaryEvaluation ||
                m_primaryBoundary.at("native_frame_index") != primary.frameIndex)
                throw std::runtime_error("Full-context snapshot does not belong to the actual primary SDK boundary");
            std::array<ID3D12Resource*, 7> cloned {};
            for (size_t i = 0; i < cloned.size(); ++i) cloned[i] = m_storage->inputs[i].Get();
            FSRD::FullContextReference::RebuildResetDispatch(primary, originalDiffuse, originalSpecular,
                cloned, m_storage->outputs[0].Get(), m_storage->outputs[1].Get(), m_dispatch, m_diffuse, m_specular);
            if (!FSRD::FullContextReference::OnlyResetControlChanged(primary, m_dispatch))
                throw std::runtime_error("Full-context reference changed original control bytes beyond RESET");
            m_primaryControlWords = FSRD::FullContextReference::ControlWordsHex(m_primary);
            m_referenceControlWords = FSRD::FullContextReference::ControlWordsHex(m_dispatch);

            // Every throwing validation/allocation/serialization precedes source transitions.
            m_clones = Json::array();
            auto frameLease = std::make_shared<FrameLease>();
            frameLease->storage = m_storage;
            constexpr const char* roles[] {"linear_depth", "motion_vectors", "normals", "specular_albedo",
                "diffuse_albedo", "DirectDiffuse.input", "IndirectSpecular.input"};
            std::array<ID3D12Resource*, 7> originalResources {};
            for (size_t i = 0; i < sourceBindings.size(); ++i)
            {
                auto* original = static_cast<ID3D12Resource*>(sourceBindings[i].resource);
                const auto sourceDesc = original->GetDesc();
                const auto cloneDesc = m_storage->inputs[i]->GetDesc();
                if (!FSRD::FullContextReference::SameNativeDescription(sourceDesc, cloneDesc))
                    throw std::runtime_error("Full-context input native descriptor changed after resource preflight");
                frameLease->sources[i] = original;
                originalResources[i] = original;
                const auto info = device->GetResourceAllocationInfo(0, 1, &cloneDesc);
                m_clones.push_back({{"role", roles[i]},
                    {"original_resource_address_process_local", Address(original)},
                    {"clone_resource_address_process_local", Address(m_storage->inputs[i].Get())},
                    {"source_native_description", FSRD::FullContextReference::NativeDescription(sourceDesc)},
                    {"clone_native_description", FSRD::FullContextReference::NativeDescription(cloneDesc)},
                    {"ffx_description", FSRD::FullContextReference::FfxDescription(sourceBindings[i].description)},
                    {"ffx_declared_state", sourceBindings[i].state}, {"source_state", uint32_t(ReadState)},
                    {"clone_entry_exit_state", uint32_t(ReadState)}, {"copy_subresource", 0}, {"copy_mip", 0},
                    {"copy_array_slice", 0}, {"copy_plane", 0}, {"copy_extent", {sourceDesc.Width, sourceDesc.Height}},
                    {"allocation_size_bytes", info.SizeInBytes}, {"allocation_alignment_bytes", info.Alignment}});
            }
            if (!ResTrack_Dx12::RetainComputeDispatch(device, list, frameLease))
                throw std::runtime_error("Full-context input/texture lifetime lease could not be admitted");
            m_timing.BeginFrame(device, list, true, [device, list](const auto& lease, auto beforeSubmit) {
                return ResTrack_Dx12::RetainComputeDispatch(device, list, lease, std::move(beforeSubmit));
            });
            {
                FSRDStageTimings::Scope copyTiming(&m_timing, FSRDStageTimings::Conversion);
                FSRD::FullContextReference::RecordFullInputSnapshot(list, originalResources, cloned);
            }
            // All persistent resources have the SAME entry/exit state. A discarded,
            // reset, or repeatedly submitted list cannot advance speculative member state.
            m_prepared = true;
            return true;
        }
        catch (const std::exception& error) { Fail(error.what()); }
        catch (...) { Fail("Full-context reference preparation failed"); }
        return false;
    }

    bool ExecuteResetReference(ID3D12GraphicsCommandList* list, ffxContext primaryContext) noexcept
    {
        try
        {
            if (!m_prepared || m_executed || !m_storage || list != m_dispatch.commandList ||
                primaryContext != m_config.primaryContext)
                throw std::runtime_error("Full-context reference lacks this evaluation's immutable input snapshot");
            const auto primaryRoute = Attestation(primaryContext);
            const auto referenceBefore = Attestation(m_context);
            CheckSameImplementation(primaryRoute, referenceBefore);
            CheckObserved(primaryRoute, "dispatch", true);
            CheckObserved(referenceBefore, "configure", true);
            if (!FSRD::FullContextReference::OnlyResetControlChanged(m_primary, m_dispatch))
                throw std::runtime_error("Full-context RESET reference control witness changed before SDK dispatch");

            // Deliberately serialized in the primary DIRECT list after composition.
            // This barrier also orders possible SDK UAV scratch shared between contexts;
            // it does not assert imported resource states or eliminate observer effects.
            D3D12_RESOURCE_BARRIER uav {}; uav.Type = D3D12_RESOURCE_BARRIER_TYPE_UAV;
            list->ResourceBarrier(1, &uav);
            ffxReturnCode_t result;
            {
                FSRDStageTimings::Scope dispatchTiming(&m_timing, FSRDStageTimings::RayRegeneration);
                result = FfxApiProxy::D3D12_Dispatch(&m_context, &m_dispatch.header);
            }
            if (result != FFX_API_RETURN_OK)
                throw std::runtime_error("Full-context RESET reference SDK dispatch failed");
            ++m_invocations;
            auto referenceAfter = Attestation(m_context);
            CheckSameImplementation(primaryRoute, referenceAfter);
            CheckObserved(referenceAfter, "dispatch", true);
            if (m_invocations == 1)
            {
                m_memory["actual_after_first_dispatch"] = QueryMemory(m_storage->device.Get(), m_context, &m_context, m_config);
                referenceAfter = Attestation(m_context);
                CheckSameImplementation(primaryRoute, referenceAfter);
                CheckObserved(referenceAfter, "query", true);
                const auto budget = VideoBudget(m_storage->device.Get());
                m_memory["local_budget_after_first_dispatch_bytes"] = budget.Budget;
                m_memory["local_current_usage_after_first_dispatch_bytes"] = budget.CurrentUsage;
                if (budget.CurrentUsage > budget.Budget || budget.Budget - budget.CurrentUsage < PrimaryBudgetHeadroom)
                    throw std::runtime_error("Full-context reference first dispatch exhausted reserved primary local-memory headroom");
            }
            m_timing.FinishFrame(true);

            auto controls = [&](const auto& object) { return Json::parse(RRTraceAdditiveIO::FloatArray(object)); };
            const auto priorTiming = m_timing.GetSnapshot();
            Json boundary {
                {"evaluation_id", m_primaryEvaluation}, {"reference_evaluation_id", m_invocations},
                {"frame_index", m_primary.frameIndex}, {"primary_dispatch_flags", m_primary.flags},
                {"dispatch_flags", m_primary.flags | FFX_DENOISER_DISPATCH_RESET},
                {"render_size", {m_primary.renderSize.width, m_primary.renderSize.height}},
                {"context_generation", m_generation}, {"primary_context_generation", m_primaryGeneration},
                {"context_address_process_local", Address(m_context)},
                {"command_list_address_process_local", Address(list)}, {"command_list_type", uint32_t(list->GetType())},
                {"controls", {{"view", controls(m_primary.view)}, {"projection", controls(m_primary.projection)},
                    {"jitter", controls(m_primary.jitterOffsets)}, {"camera_delta", controls(m_primary.cameraPositionDelta)},
                    {"motion_vector_scale", controls(m_primary.motionVectorScale)},
                    {"depth_bounds", controls(m_primary.linearDepthBounds)},
                    {"render_size", {m_primary.renderSize.width, m_primary.renderSize.height}}}},
                {"control_copy_scope", "exact_native_struct_fields_only_reset_or"},
                {"wireformat", "ffxDispatchDescDenoiser_native_ABI_suffix_264_184"},
                {"native_dispatch_bytes", sizeof(ffxDispatchDescDenoiser)},
                {"controls_byte_count", FSRD::FullContextReference::ControlBytes},
                {"controls_offset_in_dispatch", FSRD::FullContextReference::ControlOffset},
                {"controls_flags_offset_in_segment", FSRD::FullContextReference::FlagsOffset},
                {"primary_control_words_hex", m_primaryControlWords},
                {"diagnostic_control_words_hex", m_referenceControlWords},
                {"control_witness_stage", "frozen_pre_SDK_original_native_bytes_not_post_call_descriptors"},
                {"create_contract", m_config.createContract}, {"sdk_tuning", m_config.tuning},
                {"sdk_debug_depth_bounds", controls(m_config.debugDepthBounds)},
                {"clones", m_clones}, {"memory", m_memory}, {"context_provider_query", m_providerQuery},
                {"primary_library_route", primaryRoute}, {"reference_library_route", referenceAfter},
                {"primary_pre_sdk_boundary", m_primaryBoundary},
                {"opaque_primary_history_imported", false}, {"opaque_SDK_global_state_independence_proven", false},
                {"cross_evaluation_actual_queue_stability_proven", false},
                {"cross_evaluation_queue_requirement", "published_submission_tickets_must_attest_one_actual_DIRECT_queue_no_cross_queue_serialization_is_added"},
                {"primary_184_control_bytes_changed", false}, {"primary_history_or_reset_changed", false},
                {"library_module_lease", "actual_HMODULE_pinned_from_attested_module_base_retained_with_reference_context_owner"},
                {"output_entry_exit_state_contract", uint32_t(D3D12_RESOURCE_STATE_UNORDERED_ACCESS)},
                {"state_provenance", "owned_converter_and_private_resource_API_contract_not_GPU_observed"},
                {"output_initial_contents", "fresh_uncleared_committed_UAV_RGB_SDK_result_alpha_not_comparison_target"},
                {"observer_effect", "extra_full_native_copies_global_UAV_barrier_and_serial_RR_dispatch_change_frame_cost_and_order"},
                {"timing", {{"sample_scope", "previous_retired_diagnostic_sample_not_current_frame"},
                    {"sample_sequence", priorTiming.sequence}, {"valid_mask", priorTiming.validMask},
                    {"clone_ms", priorTiming.milliseconds[FSRDStageTimings::Conversion]},
                    {"reference_RR_ms", priorTiming.milliseconds[FSRDStageTimings::RayRegeneration]},
                    {"primary_RR_scope_includes_diagnostic_clone_commands", true}}}
            };
            m_result.boundaryJson = boundary.dump();
            constexpr const char* names[] {"rr_full_context_reset_specular", "rr_full_context_reset_diffuse"};
            for (size_t i = 0; i < m_result.outputs.size(); ++i)
            {
                Json metadata {{"mode", "full_native_reset_each_not_solution"},
                    {"role", "diagnostic_sdk_reset_each_lobe"}, {"stage", "post_diagnostic_sdk_pre_sr_capture"},
                    {"lobe", i == 0 ? "specular" : "diffuse"}, {"reference_boundary", boundary}};
                m_result.outputs[i] = {};
                m_result.outputs[i].name = names[i];
                m_result.outputs[i].image = {m_storage->outputs[i == 0 ? 1 : 0].Get(), D3D12_RESOURCE_STATE_UNORDERED_ACCESS};
                m_result.outputs[i].required = true;
                m_result.outputs[i].metadataJson = metadata.dump();
            }
            m_prepared = false;
            m_executed = true;
            return true;
        }
        catch (const std::exception& error) { Fail(error.what()); }
        catch (...) { Fail("Full-context RESET reference execution failed"); }
        return false;
    }

    const DiagnosticResult& Result() const noexcept { return m_result; }
    const std::string& Failure() const noexcept { return m_failure; }

  private:
    static constexpr D3D12_RESOURCE_STATES ReadState = D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE |
                                                       D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE;
    static constexpr uint64_t PrimaryBudgetHeadroom = 64ull << 20;
    struct Storage
    {
        Microsoft::WRL::ComPtr<ID3D12Device> device;
        std::shared_ptr<FfxContextOwner> owner;
        std::array<Resource, 7> inputs;
        std::array<Resource, 2> outputs;
    };
    struct ContextLifetime
    {
        HMODULE module = nullptr;
        std::shared_ptr<FfxContextOwner> owner;
        ~ContextLifetime()
        {
            // Every aliased context lease keeps this pin alive through DestroyContext.
            owner.reset();
            if (module) FreeLibrary(module);
        }
    };
    struct FrameLease
    {
        std::shared_ptr<Storage> storage;
        std::array<Resource, 7> sources;
    };
    std::shared_ptr<Storage> m_storage;
    ffxContext m_context = nullptr;
    Configuration m_config;
    std::string m_captureId, m_failure, m_primaryControlWords, m_referenceControlWords;
    uint64_t m_primaryGeneration = 0, m_generation = 0, m_invocations = 0, m_primaryEvaluation = 0;
    ffxDispatchDescDenoiser m_primary {}, m_dispatch {};
    ffxDispatchDescDenoiserDirectDiffuse m_diffuse {};
    ffxDispatchDescDenoiserIndirectSpecular m_specular {};
    Json m_primaryBoundary, m_clones, m_memory, m_providerQuery;
    DiagnosticResult m_result;
    FSRDStageTimings m_timing;
    bool m_prepared = false, m_executed = false, m_configured = false;
    std::array<float, 6> m_appliedTuning {};
    FfxApiFloatBounds m_appliedDebugDepthBounds {};
    inline static std::atomic<uint64_t> s_generation {0};

    static uint64_t Address(const void* p) noexcept { return uint64_t(reinterpret_cast<uintptr_t>(p)); }
    void Fail(const char* reason) noexcept
    {
        m_prepared = m_executed = false;
        m_timing.FinishFrame(false);
        try { m_failure = reason; } catch (...) { m_failure.clear(); }
        // Contexts/textures already recorded are retained by their native leases.
        m_storage.reset();
        m_context = nullptr;
    }
    static void ValidateConfiguration(ID3D12Device* device, ID3D12GraphicsCommandList* list,
                                      const Configuration& c, const ffxDispatchDescDenoiser& primary)
    {
        if (!device || !list || primary.commandList != list || list->GetType() != D3D12_COMMAND_LIST_TYPE_DIRECT ||
            device->GetNodeCount() != 1 || !c.primaryContext || !c.primaryContextGeneration || c.captureId.empty())
            throw std::runtime_error("Full-context reference requires the admitted primary DIRECT-list/device boundary");
        if (c.acceptedCreate.version != FFX_DENOISER_VERSION || c.acceptedCreate.signalFlags != 34 ||
            c.acceptedCreate.checkerboardSignalFlags != 0 ||
            (c.acceptedCreate.flags & FFX_DENOISER_ENABLE_DEBUGGING) != 0 || !c.providerId ||
            !primary.renderSize.width || !primary.renderSize.height ||
            primary.renderSize.width > c.acceptedCreate.maxRenderSize.width ||
            primary.renderSize.height > c.acceptedCreate.maxRenderSize.height ||
            primary.header.type != FFX_API_DISPATCH_DESC_TYPE_DENOISER || !primary.header.pNext ||
            primary.header.pNext->type != FFX_API_DISPATCH_DESC_TYPE_DENOISER_DIRECT_DIFFUSE ||
            !primary.header.pNext->pNext ||
            primary.header.pNext->pNext->type != FFX_API_DISPATCH_DESC_TYPE_DENOISER_INDIRECT_SPECULAR ||
            primary.header.pNext->pNext->pNext)
            throw std::runtime_error("Full-context reference supports only the accepted non-debug DirectDiffuse + IndirectSpecular chain");
        if (!c.createContract.is_object() || c.createContract.empty())
            throw std::runtime_error("Full-context reference accepted primary creation metadata is unavailable");
        for (const auto value : c.tuning)
            if (!std::isfinite(value)) throw std::runtime_error("Full-context reference tuning is nonfinite");
        if (!std::isfinite(c.debugDepthBounds.min) || !std::isfinite(c.debugDepthBounds.max))
            throw std::runtime_error("Full-context reference debug depth bounds are nonfinite");
    }
    static void ValidateBindings(ID3D12Device* device, const Configuration& c, const std::array<FfxApiResource, 7>& inputs,
                                 const std::array<FfxApiResource, 2>& outputs)
    {
        constexpr DXGI_FORMAT formats[] {DXGI_FORMAT_R32_FLOAT, DXGI_FORMAT_R16G16B16A16_FLOAT,
            DXGI_FORMAT_R10G10B10A2_UNORM, DXGI_FORMAT_R8G8B8A8_UNORM, DXGI_FORMAT_R8G8B8A8_UNORM,
            DXGI_FORMAT_R16G16B16A16_FLOAT, DXGI_FORMAT_R16G16B16A16_FLOAT,
            DXGI_FORMAT_R16G16B16A16_FLOAT, DXGI_FORMAT_R16G16B16A16_FLOAT};
        std::array<void*, 9> addresses {};
        Microsoft::WRL::ComPtr<IUnknown> expectedDeviceIdentity;
        if (FAILED(device->QueryInterface(IID_PPV_ARGS(&expectedDeviceIdentity))))
            throw std::runtime_error("Full-context reference source device identity unavailable");
        for (size_t i = 0; i < addresses.size(); ++i)
        {
            const auto& binding = i < inputs.size() ? inputs[i] : outputs[i - inputs.size()];
            auto* resource = static_cast<ID3D12Resource*>(binding.resource);
            if (!resource) throw std::runtime_error("Full-context reference requires all seven canonical inputs and both primary outputs");
            addresses[i] = resource;
            for (size_t j = 0; j < i; ++j)
                if (addresses[j] == addresses[i])
                    throw std::runtime_error("Full-context reference refuses an aliased original RR binding contract");
            const auto d = resource->GetDesc();
            const auto& f = binding.description;
            Microsoft::WRL::ComPtr<IUnknown> actualDeviceIdentity;
            if (FAILED(resource->GetDevice(IID_PPV_ARGS(&actualDeviceIdentity))) ||
                actualDeviceIdentity.Get() != expectedDeviceIdentity.Get())
                throw std::runtime_error("Full-context reference resource belongs to a different native device");
            if (d.Dimension != D3D12_RESOURCE_DIMENSION_TEXTURE2D || d.DepthOrArraySize != 1 || d.MipLevels != 1 ||
                d.SampleDesc.Count != 1 || d.SampleDesc.Quality || d.Layout != D3D12_TEXTURE_LAYOUT_UNKNOWN ||
                d.Flags != D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS || d.Format != formats[i] ||
                d.Width != c.acceptedCreate.maxRenderSize.width || d.Height != c.acceptedCreate.maxRenderSize.height ||
                f.type != FFX_API_RESOURCE_TYPE_TEXTURE2D || f.width != d.Width || f.height != d.Height ||
                f.depth != 1 || f.mipCount != 1 || f.flags != 0 || f.usage != FFX_API_RESOURCE_USAGE_UAV ||
                f.format != ffxApiGetSurfaceFormatDX12(d.Format) ||
                binding.state != (i < inputs.size() ? FFX_API_RESOURCE_STATE_PIXEL_COMPUTE_READ : FFX_API_RESOURCE_STATE_UNORDERED_ACCESS))
                throw std::runtime_error("Full-context reference canonical resource description/state is unsupported");
        }
    }
    static Json Attestation(ffxContext context)
    {
        const auto result = Json::parse(FfxApiProxy::DenoiserRouteAttestationDx12(context));
        if (!result.value("attested", false))
            throw std::runtime_error("Actual accepted primary/reference library route could not be attested");
        return result;
    }
    static void CheckSameImplementation(const Json& a, const Json& b)
    {
        const auto& ca = a.at("creation"); const auto& cb = b.at("creation");
        if (ca.at("route") != cb.at("route") || ca.at("implementation_identity") != cb.at("implementation_identity") ||
            ca.at("targets") != cb.at("targets"))
            throw std::runtime_error("Full-context reference actual library route/module/targets differ from primary");
    }
    static void CheckObserved(const Json& a, const char* operation, bool required)
    {
        const auto& observed = a.at("observed");
        if (!observed.contains(operation) || observed.at(operation).is_null())
        {
            if (required) throw std::runtime_error("Full-context reference required actual route operation is unavailable");
            return;
        }
        const auto& entry = observed.at(operation); const auto& creation = a.at("creation");
        if (entry.at("route") != creation.at("route") ||
            entry.at("target") != creation.at("targets").at(std::string_view(operation) == "null_query" ? "query" : operation))
            throw std::runtime_error("Actual RR operation escaped its frozen accepted library route");
    }
    static Json QueryMemory(ID3D12Device* device, ffxContext routeContext, ffxContext* queryContext, const Configuration& c)
    {
        FfxApiEffectMemoryUsage usage {};
        ffxQueryDescDenoiserGetGPUMemoryUsage query {};
        query.header.type = FFX_API_QUERY_DESC_TYPE_DENOISER_GPU_MEMORY_USAGE;
        query.device = device;
        query.maxRenderSize = c.acceptedCreate.maxRenderSize;
        query.signalFlags = c.acceptedCreate.signalFlags;
        query.checkerboardSignalFlags = c.acceptedCreate.checkerboardSignalFlags;
        query.flags = c.acceptedCreate.flags;
        query.gpuMemoryUsage = &usage;
        return QueryMemoryWithDevice(routeContext, queryContext, query, usage);
    }
    static Json QueryMemoryWithDevice(ffxContext routeContext, ffxContext* queryContext,
                                     ffxQueryDescDenoiserGetGPUMemoryUsage& query, FfxApiEffectMemoryUsage& usage)
    {
        const auto result = FfxApiProxy::QueryDenoiserAttestedRouteDx12(routeContext, queryContext, &query.header);
        const auto* version = query.header.pNext && query.header.pNext->type == FFX_API_DESC_TYPE_OVERRIDE_VERSION
            ? reinterpret_cast<const ffxOverrideVersion*>(query.header.pNext) : nullptr;
        const bool valid = result == FFX_API_RETURN_OK &&
            FSRD::FullContextReference::ValidMemoryCounters(usage.totalUsageInBytes, usage.aliasableUsageInBytes);
        const char* reason = result != FFX_API_RETURN_OK ? "SDK_return_code_not_OK" :
            !usage.totalUsageInBytes ? "zero_total_unavailable" :
            usage.totalUsageInBytes > uint64_t(INT64_MAX) ? "invalid_total_high_bit_or_unsigned_underflow_signature" :
            usage.aliasableUsageInBytes > usage.totalUsageInBytes ? "invalid_aliasable_exceeds_total" : "valid_unsigned_counters";
        return {{"query_kind", queryContext ? "actual_nonnull_context" : "expected_null_context"},
            {"return_code", uint32_t(result)}, {"available", valid}, {"validation_reason", reason},
            {"raw_reported_total_usage_bytes", usage.totalUsageInBytes},
            {"raw_reported_aliasable_usage_bytes", usage.aliasableUsageInBytes},
            {"provider_override", version ? Json(version->versionId) : Json(nullptr)},
            {"device_address_process_local", Address(query.device)},
            {"max_render_size", {query.maxRenderSize.width, query.maxRenderSize.height}},
            {"signal_flags", query.signalFlags}, {"checkerboard_signal_flags", query.checkerboardSignalFlags},
            {"create_flags", query.flags},
            {"total_usage_bytes", valid ? Json(usage.totalUsageInBytes) : Json(nullptr)},
            {"aliasable_usage_bytes", valid ? Json(usage.aliasableUsageInBytes) : Json(nullptr)},
            {"provenance", "typed_SDK_query_on_frozen_accepted_module_route_not_GPU_observed_allocation"}};
    }
    static DXGI_QUERY_VIDEO_MEMORY_INFO VideoBudget(ID3D12Device* device)
    {
        Microsoft::WRL::ComPtr<IDXGIFactory4> factory;
        Microsoft::WRL::ComPtr<IDXGIAdapter3> adapter;
        DXGI_QUERY_VIDEO_MEMORY_INFO budget {};
        if (FAILED(CreateDXGIFactory1(IID_PPV_ARGS(&factory))) ||
            FAILED(factory->EnumAdapterByLuid(device->GetAdapterLuid(), IID_PPV_ARGS(&adapter))) ||
            FAILED(adapter->QueryVideoMemoryInfo(0, DXGI_MEMORY_SEGMENT_GROUP_LOCAL, &budget)))
            throw std::runtime_error("Full-context reference native local video-memory budget is unavailable");
        return budget;
    }
    void CreateStorage(ID3D12Device* device, const Configuration& c, const std::array<FfxApiResource, 7>& inputs,
                       const std::array<FfxApiResource, 2>& outputs, const Json& primaryRoute, const Adopt& adopt)
    {
        ScopedSkipHeapCapture skipHeapCapture {};
        auto storage = std::make_shared<Storage>(); storage->device = device;
        std::array<D3D12_RESOURCE_DESC, 9> descs {};
        Json allocations = Json::array();
        uint64_t nativeBytes = 0;
        for (size_t i = 0; i < descs.size(); ++i)
        {
            descs[i] = static_cast<ID3D12Resource*>((i < inputs.size() ? inputs[i] : outputs[i - inputs.size()]).resource)->GetDesc();
            const auto info = device->GetResourceAllocationInfo(0, 1, &descs[i]);
            if (info.SizeInBytes == UINT64_MAX || !info.SizeInBytes || UINT64_MAX - nativeBytes < info.SizeInBytes)
                throw std::runtime_error("Full-context reference native allocation preflight is invalid");
            nativeBytes += info.SizeInBytes;
            allocations.push_back({{"resource_index", i}, {"size_bytes", info.SizeInBytes}, {"alignment_bytes", info.Alignment}});
        }
        FfxApiEffectMemoryUsage usage {};
        ffxQueryDescDenoiserGetGPUMemoryUsage query {};
        query.header.type = FFX_API_QUERY_DESC_TYPE_DENOISER_GPU_MEMORY_USAGE;
        query.device = device; query.maxRenderSize = c.acceptedCreate.maxRenderSize;
        query.signalFlags = c.acceptedCreate.signalFlags; query.checkerboardSignalFlags = c.acceptedCreate.checkerboardSignalFlags;
        query.flags = c.acceptedCreate.flags; query.gpuMemoryUsage = &usage;
        ffxOverrideVersion plannedVersion {};
        plannedVersion.header.type = FFX_API_DESC_TYPE_OVERRIDE_VERSION;
        plannedVersion.versionId = c.providerId;
        // A null-context query selects a provider from this query chain. The
        // accepted context's override is not inherited merely by routing its DLL.
        query.header.pNext = &plannedVersion.header;
        const auto expected = QueryMemoryWithDevice(c.primaryContext, nullptr, query, usage);
        query.header.pNext = nullptr; // Non-null context queries use that actual context.
        CheckObserved(Attestation(c.primaryContext), "null_query", true);
        if (!expected.at("available").get<bool>())
            throw std::runtime_error(std::string("Full-context reference expected SDK memory usage unavailable; refusing an unbounded allocation: ") + expected.dump());
        const auto budget = VideoBudget(device);
        const uint64_t available = budget.Budget > budget.CurrentUsage ? budget.Budget - budget.CurrentUsage : 0;
        if (usage.totalUsageInBytes > UINT64_MAX - nativeBytes - PrimaryBudgetHeadroom ||
            available < nativeBytes + usage.totalUsageInBytes + PrimaryBudgetHeadroom)
            throw std::runtime_error("Full-context reference allocation exceeds local budget with reserved primary headroom");
        m_memory = {{"native_allocations", allocations}, {"native_allocation_bytes", nativeBytes}, {"expected", expected},
            {"primary_headroom_bytes", PrimaryBudgetHeadroom}, {"local_budget_bytes", budget.Budget},
            {"local_current_usage_bytes", budget.CurrentUsage}, {"local_available_budget_bytes", available},
            {"budget_scope", "diagnostic_native_committed_allocations_plus_SDK_expected_total_aliasable_not_added_twice"}};

        auto lifetime = std::make_shared<ContextLifetime>();
        const auto moduleBase = primaryRoute.at("creation").at("implementation_identity").at("module_base").get<std::string>();
        const auto moduleAddress = static_cast<uintptr_t>(std::stoull(moduleBase, nullptr, 16));
        if (!moduleAddress || !GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS,
                reinterpret_cast<LPCWSTR>(moduleAddress), &lifetime->module) ||
            reinterpret_cast<uintptr_t>(lifetime->module) != moduleAddress)
            throw std::runtime_error("Full-context reference actual routed module could not be pinned for its context lifetime");

        ffxOverrideVersion version {}; version.header.type = FFX_API_DESC_TYPE_OVERRIDE_VERSION; version.versionId = c.providerId;
        ffxCreateBackendDX12Desc backend {}; backend.header.type = FFX_API_CREATE_CONTEXT_DESC_TYPE_BACKEND_DX12;
        backend.header.pNext = &version.header; backend.device = device;
        auto create = c.acceptedCreate;
        create.header.type = FFX_API_CREATE_CONTEXT_DESC_TYPE_DENOISER;
        create.header.pNext = &backend.header; // Rebuild the creation-local chain; no borrowed stack pointers.
        ffxContext context = nullptr;
        const auto result = FfxApiProxy::D3D12_CreateContext(&context, &create.header, nullptr);
        if (result != FFX_API_RETURN_OK || !context)
            throw std::runtime_error("Full-context reference context creation failed");
        try
        {
            lifetime->owner = adopt ? adopt(context) : nullptr;
            if (!lifetime->owner) throw std::runtime_error("Full-context reference context ownership unavailable");
        }
        catch (...)
        {
            if (!lifetime->owner) FfxApiProxy::D3D12_DestroyContext(&context, nullptr);
            throw;
        }
        // Aliasing is essential: RetainProviderContext retains the module pin too,
        // including when a later frame-resource lease fails before any GPU command.
        storage->owner = std::shared_ptr<FfxContextOwner>(lifetime, lifetime->owner.get());
        m_context = context;
        CheckSameImplementation(primaryRoute, Attestation(context));
        CheckObserved(Attestation(context), "create", true);
        D3D12_HEAP_PROPERTIES heap {}; heap.Type = D3D12_HEAP_TYPE_DEFAULT;
        for (size_t i = 0; i < descs.size(); ++i)
        {
            auto& target = i < inputs.size() ? storage->inputs[i] : storage->outputs[i - inputs.size()];
            const auto initial = i < inputs.size() ? ReadState : D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
            if (FAILED(device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &descs[i], initial,
                                                       nullptr, IID_PPV_ARGS(&target))))
                throw std::runtime_error("Full-context reference private native texture allocation failed");
            if (!FSRD::FullContextReference::SameNativeDescription(descs[i], target->GetDesc()))
                throw std::runtime_error("Full-context reference private native texture does not preserve GetDesc");
        }
        // A valid provider-version query may be unavailable; the accepted override
        // and actual library identity are separate evidence and remain explicit.
        ffxQueryGetProviderVersion provider {}; provider.header.type = FFX_API_QUERY_DESC_TYPE_GET_PROVIDER_VERSION;
        const auto providerCode = FfxApiProxy::QueryDenoiserAttestedRouteDx12(context, &context, &provider.header);
        const bool providerAvailable = providerCode == FFX_API_RETURN_OK && provider.versionId && provider.versionName && *provider.versionName;
        m_providerQuery = {{"return_code", uint32_t(providerCode)}, {"available", providerAvailable},
            {"version_id", providerAvailable ? Json(provider.versionId) : Json(nullptr)},
            {"name", providerAvailable ? Json(provider.versionName) : Json(nullptr)},
            {"provenance", "query_on_actual_frozen_module_target_accepted_override_is_separate"}};
        if (providerAvailable && provider.versionId != c.providerId)
            throw std::runtime_error("Full-context reference reported provider differs from accepted primary override");
        if (providerAvailable && Json(provider.versionName) != c.createContract.at("provider_name"))
            throw std::runtime_error("Full-context reference reported provider name differs from accepted primary selection");
        m_storage = std::move(storage);
        m_generation = s_generation.fetch_add(1, std::memory_order_relaxed) + 1;
        m_configured = false;
        query.gpuMemoryUsage = &usage; usage = {};
        m_memory["actual_after_creation"] = QueryMemoryWithDevice(context, &m_context, query, usage);
        const auto after = VideoBudget(device);
        m_memory["local_budget_after_creation_bytes"] = after.Budget;
        m_memory["local_current_usage_after_creation_bytes"] = after.CurrentUsage;
        if (after.CurrentUsage > after.Budget || after.Budget - after.CurrentUsage < PrimaryBudgetHeadroom)
            throw std::runtime_error("Full-context reference creation exhausted reserved primary local-memory headroom");
    }
    void Configure(const Configuration& c)
    {
        for (size_t i = 0; i < c.tuning.size(); ++i)
        {
            if (m_configured && std::memcmp(&m_appliedTuning[i], &c.tuning[i], sizeof(float)) == 0) continue;
            ffxConfigureDescDenoiserKeyValue desc {};
            desc.header.type = FFX_API_CONFIGURE_DESC_TYPE_DENOISER_KEYVALUE;
            desc.key = i + 1; desc.count = 1; desc.data = &c.tuning[i];
            if (FfxApiProxy::D3D12_Configure(&m_context, &desc.header) != FFX_API_RETURN_OK)
                throw std::runtime_error("Full-context reference scalar configuration failed");
        }
        if (!m_configured || std::memcmp(&m_appliedDebugDepthBounds, &c.debugDepthBounds, sizeof(c.debugDepthBounds)))
        {
            ffxConfigureDescDenoiserKeyValue desc {};
            desc.header.type = FFX_API_CONFIGURE_DESC_TYPE_DENOISER_KEYVALUE;
            desc.key = FFX_API_CONFIGURE_DENOISER_KEY_DEBUG_VIEW_LINEAR_DEPTH_BOUNDS;
            desc.count = 1; desc.data = &c.debugDepthBounds;
            if (FfxApiProxy::D3D12_Configure(&m_context, &desc.header) != FFX_API_RETURN_OK)
                throw std::runtime_error("Full-context reference depth-bound configuration failed");
        }
        m_appliedTuning = c.tuning;
        m_appliedDebugDepthBounds = c.debugDepthBounds;
        m_configured = true;
        m_config.tuning = c.tuning;
        m_config.debugDepthBounds = c.debugDepthBounds;
    }
};
