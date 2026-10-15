#pragma once
// Typed, padding-free capture metadata. No GPU work, title reads or SDK queries.
#include "FSRDNrdBridgeRR_Dx12.h"
#include <bit>
#include <cstring>
#include <json.hpp>

namespace FSRDGameTraceBridgeMetadata
{
using Json = nlohmann::json;
inline uint32_t Bits(float value) noexcept { return std::bit_cast<uint32_t>(value); }
template<class T> inline Json FloatWords(const T& value)
{
    static_assert(sizeof(T) % sizeof(float) == 0);
    std::array<uint32_t,sizeof(T)/sizeof(float)> words {};
    memcpy(words.data(),&value,sizeof(value));
    return words;
}
inline Json MatrixWords(const DirectX::XMMATRIX& value)
{
    DirectX::XMFLOAT4X4 rows;
    DirectX::XMStoreFloat4x4(&rows,value);
    return FloatWords(rows);
}
inline Json Frame(const NrdBridge::FrameParameters& p, const sl::Constants& c, uint32_t slFrame, uint32_t slViewport)
{
    return {{"float_encoding","ieee754_binary32_uint32_words"},
        {"camera",{{"matrix_convention","bridge_column_vectors; stored_row_major_words"},
            {"view",MatrixWords(p.camera.view)},{"inverse_view",MatrixWords(p.camera.inverseView)},
            {"projection",MatrixWords(p.camera.projection)},{"view_source",uint32_t(p.camera.viewSource)},
            {"projection_source",uint32_t(p.camera.projectionSource)},{"right_handed",p.camera.isRightHanded}}},
        {"near_plane",Bits(p.nearPlane)},{"far_plane",Bits(p.farPlane)},{"depth_sign",Bits(p.depthSign)},
        {"motion_scale",FloatWords(p.motionScale)},{"jitter",FloatWords(p.jitter)},
        {"previous_jitter",FloatWords(p.previousJitter)},{"camera_position",FloatWords(p.cameraPosition)},
        {"previous_camera_position",FloatWords(p.previousCameraPosition)},
        {"streamline_frame",p.streamlineFrame},{"frame_index",p.frameIndex},
        {"motion_vectors_jittered",p.motionVectorsJittered},{"motion_vectors_3d",p.motionVectors3D},
        {"requested_reset",p.reset},{"previous_valid",p.previousValid},
        {"native_material_guides",p.nativeMaterialGuides},{"native_temporal_motion",p.nativeTemporalMotion},
        {"camera_projected_depth_delta",p.cameraProjectedDepthDelta},
        {"legacy_motion_depth",p.legacyMotionDepth},
        {"preserve_native_material_ids",p.preserveNativeMaterialIDs},
        {"fallback_output_encoding",uint32_t(p.outputEncoding)},
        {"streamline",{{"frame",slFrame},{"viewport",slViewport},
            {"matrix_convention","Streamline_row_vectors_row_major_words"},
            {"camera_view_to_clip",FloatWords(c.cameraViewToClip)},
            {"clip_to_camera_view",FloatWords(c.clipToCameraView)},
            {"clip_to_lens_clip",FloatWords(c.clipToLensClip)},
            {"clip_to_previous_clip",FloatWords(c.clipToPrevClip)},
            {"previous_clip_to_clip",FloatWords(c.prevClipToClip)},
            {"jitter",FloatWords(c.jitterOffset)},{"motion_scale",FloatWords(c.mvecScale)},
            {"camera_pinhole_offset",FloatWords(c.cameraPinholeOffset)},
            {"camera_position",FloatWords(c.cameraPos)},{"camera_up",FloatWords(c.cameraUp)},
            {"camera_right",FloatWords(c.cameraRight)},{"camera_forward",FloatWords(c.cameraFwd)},
            {"near_plane",Bits(c.cameraNear)},{"far_plane",Bits(c.cameraFar)},
            {"fov",Bits(c.cameraFOV)},{"aspect_ratio",Bits(c.cameraAspectRatio)},
            {"motion_invalid_value",Bits(c.motionVectorsInvalidValue)},
            {"depth_inverted",uint32_t(c.depthInverted)},{"camera_motion_included",uint32_t(c.cameraMotionIncluded)},
            {"motion_vectors_3d",uint32_t(c.motionVectors3D)},{"reset",uint32_t(c.reset)},
            {"orthographic",uint32_t(c.orthographicProjection)},{"motion_dilated",uint32_t(c.motionVectorsDilated)},
            {"motion_jittered",uint32_t(c.motionVectorsJittered)},
            {"minimum_relative_linear_depth_separation",Bits(c.minRelativeLinearDepthObjectSeparation)}}}};
}
inline Json Settings(const NrdBridge::RRSettingsState& s)
{
    const auto& p = s.requested;
    return {{"float_encoding","ieee754_binary32_uint32_words"},{"defaults_ready",s.ready},
        {"override_mask",p.overrideMask},{"requested_values",FloatWords(p.values)},
        {"provider_defaults",FloatWords(s.defaults)},{"provider_effective",FloatWords(s.effective)},
        {"native_debug_view",p.nativeDebugView},{"native_debug_viewport",p.nativeDebugViewport},
        {"preserve_native_material_ids",p.preserveNativeMaterialIDs},{"native_temporal_motion",p.nativeTemporalMotion},
        {"legacy_motion_depth",p.legacyMotionDepth},
        {"native_material_guides",p.nativeMaterialGuides},{"lobe_recovery",p.lobeRecovery},
        {"recovery_specular",Bits(p.recoverySpecular)},{"recovery_diffuse",Bits(p.recoveryDiffuse)},
        {"native_nrd_output_used",false}};
}
inline Json Contract()
{
    return {{"lighting_source","separate_current_native_noisy_NRD_domain_signals; bridge_treats_RGB_as_demodulated"},
        {"material_modulation_contract_verified",false},
        {"upstream_exposure_scale","not_separately_attested; actual_owned_signal_words_are_preserved"},
        {"native_nrd_denoised_reference",false},{"native_nrd_denoised_correction",false},
        {"rr_inputs",{{"specular","linear_demodulated_RGB; A_hit_distance"},
            {"diffuse","linear_demodulated_RGB; A_hit_distance"},
            {"linear_depth","signed_linear_view_Z"},{"motion","actual_finalized_RR_MV; inspect_provider_scale_and_frame_bits"},
            {"normals","R10G10B10A2_UNORM; RG_octahedral_normal; B_linear_roughness; A_category"},
            {"specular_albedo","RGBA8; actual_Qs_RGB"},{"diffuse_albedo","RGBA8; actual_Qd_RGB"}}},
        {"raw_rr","owned_linear_demodulated_RGBA16; before_optional_recovery"},
        {"selected_rr","owned_linear_demodulated_RGBA16; recovery_or_alias_of_raw"},
        {"encoded_commit","bridge_commit_result_before_original_Consumer; not_native_NRD_output"},
        {"geometry_guide","actual_owned_normal_depth_MV_payloads; no_guide_reconstruction"},
        {"history","ordinary_capture_does_not_request_reset; explicit_USER_reset_intent_is_separately_recorded; prior_hidden_SDK_history_is_unavailable"}};
}
}
