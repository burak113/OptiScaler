Json ObservationStamp(const FSRDNrdObservation::Stamp& stamp)
{
    return {{"stream_id",stamp.streamId},{"frame",stamp.frame},{"reset_epoch",stamp.resetEpoch},
        {"resource_epoch",stamp.resourceEpoch},{"known",stamp.known == 1}};
}
const char* ObservationPathName(FSRDNrdObservation::SelectionPath path) noexcept
{
    using Path = FSRDNrdObservation::SelectionPath;
    switch (path)
    {
    case Path::RawRR: return "raw_rr";
    case Path::LobeRecovery: return "lobe_recovery";
    case Path::FlatAlbedo: return "flat_albedo";
    case Path::ProtectedNative: return "protected_native";
    default: return "unknown";
    }
}
FSRDNrdObservation::Surface ObservationSurface(const Frame& f, const Session& s, size_t slot,
    FSRDNrdObservation::Role role, FSRDNrdObservation::Lobe lobe, float providerScale = 0)
{
    using namespace FSRDNrdObservation;
    const auto& image = f.surveyImages.at(slot);
    Surface value; value.availability = Availability::Present; value.unavailableReason = Reason::None;
    value.role = role; value.lobe = lobe; value.stamp = f.observations->stamp;
    value.resourceId = slot+1; // Frame-local alias ID; never a persistent GPU address.
    auto& layout = value.layout; layout.dxgiFormat = image.format;
    layout.allocation = {image.sourceWidth,image.sourceHeight}; layout.active = {s.rw,s.rh};
    layout.captured = {image.width,image.height}; layout.cropOrigin = {image.cropX,image.cropY};
    // The exported payload is tight. The actual padded D3D footprint remains
    // alongside it as copy_footprint and must not be used to index the disk file.
    layout.rowBytes = layout.rowPitch = uint64_t(image.width)*image.bpp;
    layout.payloadBytes = layout.rowBytes*image.height;
    switch (image.format)
    {
    case DXGI_FORMAT_R16G16B16A16_FLOAT: layout.encoding = Encoding::Rgba16FloatWords; break;
    case DXGI_FORMAT_R10G10B10A2_UNORM: layout.encoding = Encoding::R10G10B10A2UnormWords; break;
    case DXGI_FORMAT_R32_FLOAT: layout.encoding = Encoding::R32FloatWords; break;
    case DXGI_FORMAT_R8_UINT: layout.encoding = Encoding::R8UintWords; break;
    default: layout.encoding = Encoding::Unknown; break;
    }
    if (role == Role::AnchorSums)
    {
        layout.encoding = Encoding::NativeAnchorSums32;
        layout.allocation = layout.active = layout.captured = {8,1}; layout.cropOrigin = {};
    }
    if (IsRadiance(role))
    {
        if (!std::isfinite(providerScale) || providerScale < 1 || providerScale > 4096 ||
            std::floor(providerScale) != providerScale)
            throw std::runtime_error("Native observation has an unknown per-lobe provider scale");
        value.scale = {1,uint32_t(providerScale),1};
    }
    if (ValidateSurface(value) != Reason::None)
        throw std::runtime_error("Native observation surface failed its portable ABI validation");
    return value;
}
Json ObservationSurfaceMetadata(const FSRDNrdObservation::Surface& surface, const Frame& f, size_t slot,
    const char* stage)
{
    const auto& p = surface.layout;
    return {{"availability","present"},{"role",uint32_t(surface.role)},{"lobe",uint32_t(surface.lobe)},
        {"stamp",ObservationStamp(surface.stamp)},{"resource_id",surface.resourceId},
        {"image",f.surveyKeys.at(slot)},{"stage",stage},{"dxgi_format",p.dxgiFormat},{"encoding",uint32_t(p.encoding)},
        {"allocation_extent",{p.allocation.width,p.allocation.height}},{"active_extent",{p.active.width,p.active.height}},
        {"captured_extent",{p.captured.width,p.captured.height}},{"crop_origin",{p.cropOrigin.x,p.cropOrigin.y}},
        {"coordinate_space","bridge_render_pixels; title_native_source_mapping_not_inferred"},
        {"payload_layout",{{"byte_offset",p.byteOffset},{"row_pitch",p.rowPitch},{"row_bytes",p.rowBytes},{"bytes",p.payloadBytes}}},
        {"copy_footprint",CopyFootprintMetadata(f.surveyImages.at(slot))},
        {"native_texture_row_pitch",nullptr},{"native_texture_row_pitch_reason","D3D12 texture layout is opaque; copy footprint is separately observed"},
        {"scale",{{"known",surface.scale.known == 1},{"provider_multiplier",surface.scale.providerMultiplier},
            {"stored_multiplier",surface.scale.storedMultiplier}}}};
}
Json NativeObservationMetadata(Frame& f, const Session& s, const NrdBridge::RRRecordedOutputSnapshot& output,
    const NrdBridge::FrameParameters& parameters, size_t originalNormalSlot, size_t originalMotionSlot,
    size_t validitySlot, size_t anchorSumsSlot)
{
    using namespace FSRDNrdObservation;
    auto& o = *f.observations;
    Json surfaces = Json::object(), authority = Json::object();
    const auto add = [&](const char* name, size_t slot, Role role, Lobe lobe, const char* stage, float scale = 0) {
        auto value = ObservationSurface(f,s,slot,role,lobe,scale);
        surfaces[name] = ObservationSurfaceMetadata(value,f,slot,stage); return value;
    };
    for (size_t i=0; i<2; ++i)
    {
        const bool specular = i == 0;
        const auto lobe = specular ? Lobe::Specular : Lobe::Diffuse;
        const auto scale = specular ? output.providerSpecularRadianceScale : output.providerDiffuseRadianceScale;
        add(specular ? "physical_source_specular" : "physical_source_diffuse",o.physicalRoles[i],Role::PhysicalSource,lobe,
            "decoded_native_physical_before_anchor_turn_filters_and_scale",scale);
        add(specular ? "physical_pre_scale_specular" : "physical_pre_scale_diffuse",o.physicalRoles[2+i],Role::EffectivePhysical,lobe,
            "after_anchor_before_turn_filters_and_scale; exact_early_words",scale);
        o.raw[i] = add(specular ? "raw_rr_specular" : "raw_rr_diffuse",f.bridgeRoles[7+i],Role::RawRR,lobe,
            "after_provider_and_inverse_radiance_scale_before_recovery",scale);
        o.selected[i] = add(specular ? "selected_rr_specular" : "selected_rr_diffuse",f.bridgeRoles[9+i],Role::SelectedOutput,lobe,
            "actual_selected_resource_after_optional_recovery_before_native_commit",scale);
        o.selection[i] = {specular ? output.specularSelection : output.diffuseSelection,o.stamp,lobe,
            o.raw[i].resourceId,o.selected[i].resourceId};
        const auto& selection = o.selection[i];
        authority[specular ? "specular" : "diffuse"] = {{"selection_path",ObservationPathName(selection.path)},
            {"selection_path_value",uint32_t(selection.path)},{"selection_authority",uint32_t(SelectionAuthority(selection))},
            {"raw_resource_id",selection.rawResourceId},{"selected_resource_id",selection.selectedResourceId},
            {"equality_guard",uint32_t(EqualityGuard::Unknown)},{"raw_authority_valid",false},{"raw_edit_eligible",false},
            {"equality_status","pending_protected_fence_snapshot"},
            {"scope","whole_lobe_host_selection; recovery_outputs_protected_even_when_equal"}};
    }
    add("provider_normal_roughness",f.bridgeRoles[4],Role::ProviderNormalRoughness,Lobe::None,
        "actual_RR_packed_guide_after_optional_flat_floor");
    add("bridge_normal_before_flat",originalNormalSlot == SIZE_MAX ? f.bridgeRoles[4] : originalNormalSlot,
        Role::ProviderNormalRoughness,Lobe::None,"converted_native_RGB_packing; category_may_have_been_cleared; not_original_title_words");
    add("provider_depth",f.bridgeRoles[2],Role::ProviderDepth,Lobe::None,"converted_signed_linear_depth; raw_nonfinite_and_clamp_history_not_reconstructed");
    add("provider_motion",f.bridgeRoles[3],Role::ProviderMotion,Lobe::None,"actual_finalized_provider_motion_after_optional_lighting_guard");
    add("bridge_motion_before_lighting_guard",originalMotionSlot == SIZE_MAX ? f.bridgeRoles[3] : originalMotionSlot,
        Role::ProviderMotion,Lobe::None,"finalized_bridge_motion_before_lighting_guard; not_original_title_MV_words");
    if (validitySlot != SIZE_MAX)
        add("depth_validity",validitySlot,Role::GeometryValidity,Lobe::None,"geometry_writer_original_depth_classification");
    else surfaces["depth_validity"] = {{"availability","missing"},{"reason","conversion path did not publish validity"}};
    if (anchorSumsSlot != SIZE_MAX)
        add("anchor_sums",anchorSumsSlot,Role::AnchorSums,Lobe::None,"complete_native_32_byte_atomic_low_high_count_buffer_after_anchor");
    else surfaces["anchor_sums"] = {{"availability","missing"},{"reason","no active native anchor accumulator"}};
    const auto support = NrdBridge::SupportContract::InvalidNativeSupport(o.stamp.resetEpoch,o.stamp.frame);
    return {{"schema","fsrd-native-observation-v1"},{"abi_version",AbiVersion},{"capture_id",s.status.captureId},
        {"stamp",ObservationStamp(o.stamp)},
        {"recording_id",o.recordingId},{"streamline_frame",o.frameSL},{"actual_reset",o.actualReset},
        {"surfaces",std::move(surfaces)},{"authority",std::move(authority)},
        {"support",{{"version",support.version},{"valid",false},{"reason_bits",support.reasons},
            {"reasons",{"unavailable_actual_nonzero_donor_footprint","unavailable_recalled_key_correspondence"}},
            {"scope","no_native_support_certificate; current_cell_gain_sums_and_correlation_cannot_certify_mixed_donors"}}},
        {"motion_convention",{{"units","full_render_uv"},{"direction","previous_minus_current"},
            {"jitter","already_encoded_no_extra_delta"},{"z","signed_previous_minus_current_depth_delta; per_pixel_path_unobserved"},
            {"per_pixel_correspondence","unknown"}}},
        {"provider_depth_sign_float32_bits",FSRDGameTraceBridgeMetadata::Bits(parameters.depthSign)},
        {"alpha_policy","opaque_original_words_at_each_observed_stage; no_float_conversion_or_semantic_validation"},
        {"unknown",{{"title_native_normal_roughness","not_captured_before_geometry_conversion; RGB_is_native_packing_but_A_may_be_cleared"},
            {"title_raw_depth","not_captured_before_abs_clamp_and_sign_conversion"},
            {"title_raw_motion","not_captured_before_finalization"},
            {"title_crop_origin","GPU_native_geometry_constants_not_observed_here; zero_is_not_assumed"},
            {"material_or_layer_identity","not_observable_from_normal_roughness_or_correlation"},
            {"upstream_exposure_and_modulation","not_attested"}}},
        {"capture_semantics","observations_only; no_causal_truth_or_quality_claim"}};
}
void CompleteNativeObservationMetadata(const Frame& f, CpuFrame& packet)
{
    if (!f.observations) return;
    using namespace FSRDNrdObservation;
    const auto& o = *f.observations;
    const auto payloadFor = [&](size_t slot) -> const std::vector<uint8_t>* {
        const auto filename = f.surveyKeys.at(slot)+".bin";
        const auto it = std::find_if(packet.payloads.begin(),packet.payloads.end(),
            [&](const CpuPayload& payload) { return payload.kind == 0 && payload.filename == filename; });
        return it == packet.payloads.end() ? nullptr : &it->bytes;
    };
    for (size_t i=0; i<2; ++i)
    {
        const auto* raw = payloadFor(f.bridgeRoles[7+i]);
        const auto* selected = payloadFor(f.bridgeRoles[9+i]);
        EqualityGuard equality = EqualityGuard::Unknown;
        if (raw && selected)
            equality = raw->size() == selected->size() && EqualWords(raw->data(),selected->data(),raw->size()) ?
                EqualityGuard::EqualWords : EqualityGuard::DifferentWords;
        const auto reason = ValidateRawAuthority(o.selection[i],o.raw[i],o.selected[i],equality);
        auto& metadata = packet.row["native_observations"]["authority"][i == 0 ? "specular" : "diffuse"];
        metadata["equality_guard"] = uint32_t(equality);
        metadata["equality_status"] = "original_words_compared_after_protected_fence_snapshot";
        metadata["raw_authority_valid"] = reason == Reason::None;
        metadata["authority_validation_reason"] = uint32_t(reason);
        // Authority and geometric support are independent requirements. Native
        // donor lineage remains unavailable, so this packet permits no edit.
        metadata["raw_edit_eligible"] = false;
    }
}

