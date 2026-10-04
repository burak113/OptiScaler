#pragma once
#include <Config.h>
#include <imgui/imgui.h>
#include "upscalers/fsr31/FSRDSignalPolicy.h"
#include "gpu_time/FSRDStageTimings_Dx12.h"

namespace FSRDMenu
{
inline bool DrawProfile(Config& cfg)
{
    const char* names[] = { "Fast", "Balanced", "Quality" };
    const int profile = cfg.GetFfxDenoiserProfile();
    bool changed = false;
    if (ImGui::BeginCombo("Profile", profile >= 0 ? names[profile] : "Custom"))
    {
        for (int i = 0; i < 3; ++i)
            if (ImGui::Selectable(names[i], profile == i))
            {
                cfg.ApplyFfxDenoiserProfile(i);
                changed = true;
            }
        ImGui::EndCombo();
    }
    if (ImGui::IsItemHovered())
        ImGui::SetTooltip("Fast: Floor and recovery off.\n"
                          "Balanced (default): Fast Floor, Full Anchor flat/zero-rough recovery, Light Anchor Mix specular.\n"
                          "Quality: normal Floor, Full Anchor flat/zero-rough, Light Anchor Mix specular + diffuse, "
                          "and Unsupported Albedo recovery.\nManual edits are saved as Custom.");
    return changed;
}

inline bool DrawDenoiser(Config& cfg, const FSRDRuntimeSnapshot& snapshot,
                         bool ffxActive, bool nvRRActive, bool providerAvailable, bool nativeRRPreferred)
{
    const ImVec4 red(1.0f, 0.32f, 0.28f, 1.0f), green(0.3f, 0.9f, 0.45f, 1.0f);
    const bool eligible = ffxActive && nvRRActive && providerAvailable;
    const bool automatic = !cfg.FfxDenoiserEnabled.has_value();
    const bool requested = ffxActive && nvRRActive && cfg.FfxDenoiserEnabled.value_or(!nativeRRPreferred);
    const bool fresh = snapshot.updated.time_since_epoch().count() != 0 &&
        std::chrono::steady_clock::now() - snapshot.updated < std::chrono::seconds(2);
    const bool running = fresh && snapshot.rrValidated;
    const char* selected = !nvRRActive ? "Native / NRD (game)"
        : snapshot.gameNativeRequested ? "Native / NRD requested"
        : requested ? (running ? "FSR-RR" : snapshot.failure.empty() ? "Checking FSR-RR" : "FSR-RR stopped")
        : nativeRRPreferred ? "NVIDIA RR + SR" : "Native / NRD (game)";
    const std::string preview = (automatic ? "Auto: " : "") + std::string(selected);
    bool rebuild = false;
    if (ImGui::BeginCombo("Denoiser", preview.c_str()))
    {
        if (ImGui::Selectable("Auto (GPU default)", automatic))
        {
            cfg.FfxDenoiserEnabled.reset();
            rebuild = ffxActive && nvRRActive;
        }
        const bool nativeAvailable = !nativeRRPreferred || !nvRRActive || snapshot.nativeAvailable || !ffxActive;
        ImGui::BeginDisabled(!nativeAvailable);
        if (ImGui::Selectable(nativeRRPreferred ? "NVIDIA RR + SR" : "Native / NRD (game)", !automatic && !requested))
        {
            if (nvRRActive && ffxActive) cfg.FfxDenoiserEnabled = false;
            else cfg.FfxDenoiserEnabled.reset();
        }
        ImGui::EndDisabled();
        if (!nativeAvailable && ImGui::IsItemHovered(ImGuiHoveredFlags_AllowWhenDisabled))
            ImGui::SetTooltip("The NVIDIA RR provider did not initialize. Disable NV Ray Reconstruction in the game "
                              "to restore its own denoiser.");
        ImGui::BeginDisabled(!eligible);
        if (ImGui::Selectable("FSR-RR", !automatic && requested))
        {
            cfg.FfxDenoiserEnabled = true;
            rebuild = !requested || !snapshot.failure.empty();
        }
        ImGui::EndDisabled();
        ImGui::EndCombo();
    }
    ImGui::TextWrapped("Auto: supported NVIDIA GPUs use NVIDIA RR + SR. AMD GPUs use FSR-RR with FSR/FFX "
                      "and active NV RR input only after the required runtime stages succeed. A failed check "
                      "requests the game's native denoiser (NRD where the game provides it).");
    if (!eligible)
    {
        ImGui::PushStyleColor(ImGuiCol_Text, red);
        ImGui::TextWrapped("FSR-RR unavailable: %s", !ffxActive ? "select the FSR (FFX) upscaler."
            : !nvRRActive ? "enable NV Ray Reconstruction in the game."
                          : "the AMD Ray Regeneration provider is missing or incompatible.");
        ImGui::PopStyleColor();
    }
    if (snapshot.rayReconstruction)
    {
        ImGui::TextColored(running ? green : red, "FSR-RR: %s", running ? "running" : "not running");
        if (requested)
            ImGui::TextColored(running ? green : red, "Runtime gate: %s", running ? "passed"
                : !snapshot.failure.empty() ? "failed" : "waiting for a complete frame");
        if (snapshot.nativeActive && fresh && snapshot.success)
            ImGui::TextColored(green, "NVIDIA RR + SR: %s", snapshot.fallback ? "fallback active" : "active");
        if (snapshot.gameNativeRequested)
            ImGui::TextColored(red, "Native / NRD: waiting for the game to switch; not confirmed active");
        if (!snapshot.failure.empty())
        {
            ImGui::PushStyleColor(ImGuiCol_Text, red);
            ImGui::TextWrapped("%s", snapshot.failure.c_str());
            ImGui::PopStyleColor();
        }
        if (eligible && !snapshot.failure.empty() && ImGui::Button("Retry FSR-RR"))
        {
            cfg.FfxDenoiserEnabled = true;
            rebuild = true;
        }
    }
    else if (nvRRActive)
        ImGui::TextWrapped("NVIDIA RR + SR is selected. FSR-RR remains available with the FSR/FFX upscaler "
                          "as an explicit denoiser choice.");
    else
        ImGui::TextWrapped("NV Ray Reconstruction is off: denoising belongs to the game. "
                          "NGX does not report whether its internal denoiser is NRD.");
    return rebuild;
}

inline void DrawWorkflow(const FSRDRuntimeSnapshot& snapshot)
{
    if (!ImGui::CollapsingHeader("How it works / Live pipeline")) return;
    using R = FSRDRuntimeSnapshot;
    const char* steps[] = {
        "1. Validate color, depth, motion, normals, roughness, albedo and camera transforms.",
        "2. Floor filters stable scene lighting and prepares the detail reference.",
        "3. Convert guides and split scene color into the selected RR signals.",
        "4. AMD Ray Regeneration denoises the bound diffuse/specular signals.",
        "5. Unsupported Albedo recovery builds surface trust from alternate specular.",
        "6. Compose denoised light, restore material color and apply enabled recovery.",
        "7. FSR Super Resolution upscales the composed image.",
        "8. Finish sharpening/output scaling and return the final output to the game."
    };
    const char* status[] = { "not run", "in progress", "completed", "FAILED", "off / bypassed" };
    const bool fresh = snapshot.updated.time_since_epoch().count() != 0 &&
        std::chrono::steady_clock::now() - snapshot.updated < std::chrono::seconds(2);
    for (int i = 0; i < R::StepCount; ++i)
    {
        const auto value = fresh ? snapshot.steps[i] : R::NotRun;
        ImGui::PushStyleColor(ImGuiCol_Text, value == R::Passed ? ImVec4(0.3f, 0.9f, 0.45f, 1.0f)
                                                             : ImVec4(1.0f, 0.32f, 0.28f, 1.0f));
        ImGui::TextWrapped("%s [%s]", steps[i], status[value]);
        ImGui::PopStyleColor();
    }
    ImGui::TextWrapped("Green means validation/command recording succeeded in the latest evaluation; "
                      "it is not a GPU completion check. Red also marks deliberately disabled or bypassed stages. "
                      "A failed stage stops FSR-RR until Retry or context recreation. Native NVIDIA RR + SR is used "
                      "when available; otherwise an unsupported-feature result requests game-native denoising. "
                      "If the game does not switch automatically, disable NV RR in its settings.");
}

inline void DrawInputs(const FSRDRuntimeSnapshot& snapshot)
{
    if (!ImGui::CollapsingHeader("Live inputs / What RR receives")) return;
    using R = FSRDRuntimeSnapshot;
    const bool fresh = snapshot.updated.time_since_epoch().count() != 0 &&
        std::chrono::steady_clock::now() - snapshot.updated < std::chrono::seconds(2);
    if (ImGui::BeginTable("RRInputs", 4, ImGuiTableFlags_BordersInnerH | ImGuiTableFlags_SizingStretchProp))
    {
        ImGui::TableSetupColumn("Input");
        ImGui::TableSetupColumn("Received");
        ImGui::TableSetupColumn("Preprocess");
        ImGui::TableSetupColumn("Bound to RR");
        ImGui::TableHeadersRow();
        for (int i = 0; i < R::InputCount; ++i)
        {
            ImGui::TableNextRow();
            ImGui::TableSetColumnIndex(0);
            ImGui::TextUnformatted(R::InputNames[i]);
            const bool values[] = { (snapshot.received & (1u << i)) != 0,
                                    (snapshot.prepared & (1u << i)) != 0,
                                    snapshot.rrDispatched && (snapshot.submitted & (1u << i)) != 0 };
            for (int j = 0; j < 3; ++j)
            {
                ImGui::TableSetColumnIndex(j + 1);
                const bool yes = fresh && values[j];
                ImGui::TextColored(yes ? ImVec4(0.3f, 0.9f, 0.45f, 1.0f) : ImVec4(1.0f, 0.32f, 0.28f, 1.0f),
                                   "%s", yes ? "Yes" : "No");
            }
        }
        ImGui::EndTable();
    }
    ImGui::TextWrapped("Received: NGX resources or validated Streamline tags (roughness may be packed in normals). "
                      "Preprocess: selected, validated source guides. Bound to RR: converted guides/signals in an "
                      "accepted AMD dispatch, not direct copies of the game textures. Color becomes radiance; "
                      "normals include roughness; ray distances use signal alpha. A generated ray estimate may be "
                      "bound without a received source. Bias, emissive and responsivity affect preprocessing only; "
                      "title linear depth contributes to converted Depth. View/projection and jitter are constants. "
                      "Exposure is an SR input, not an RR guide. "
                      "The provider does not expose which inputs its model reads internally.");
}

inline FSRDSignals::Layout RequestedLayout(const Config& cfg, uint32_t status)
{
    if (cfg.FfxDenoiserSignalCount.has_value())
        return FSRDSignals::Resolve(
            cfg.FfxDenoiserSignalCount.value_or_default(),
            { cfg.FfxDenoiserSignal1.value_or_default(), cfg.FfxDenoiserSignal2.value_or_default(),
              cfg.FfxDenoiserSignal3.value_or_default(), cfg.FfxDenoiserSignal4.value_or_default() });
    FSRDSignals::Layout result;
    const uint32_t mask = (status >> 8) & 15u;
    if (!mask)
        return FSRDSignals::Resolve(2, { FSRDSignals::DirectDiffuse, FSRDSignals::DirectSpecular, -1, -1 });
    for (int signal : FSRDSignals::Preferred)
        if (mask & FSRDSignals::Bit(signal))
            result.slots[result.count++] = signal;
    result.mask = mask;
    return result;
}
inline void StoreLayout(Config& cfg, const FSRDSignals::Layout& layout)
{
    cfg.FfxDenoiserSignalCount = layout.count;
    cfg.FfxDenoiserSignal1 = layout.slots[0];
    cfg.FfxDenoiserSignal2 = layout.slots[1];
    cfg.FfxDenoiserSignal3 = layout.slots[2];
    cfg.FfxDenoiserSignal4 = layout.slots[3];
}
inline bool DrawSignals(Config& cfg, uint32_t status)
{
    bool rebuild = false;
    const bool legacyOverrides = cfg.FfxDenoiserDiffuseSignalType.has_value() ||
                                 cfg.FfxDenoiserSpecularSignalType.has_value() ||
                                 !cfg.FfxDenoiserDenoiseDiffuse.value_or_default() ||
                                 !cfg.FfxDenoiserDenoiseSpecular.value_or_default();
    bool automatic = !cfg.FfxDenoiserSignalCount.has_value() && !legacyOverrides;
    if (ImGui::Checkbox("Automatic Signal Layout", &automatic))
    {
        if (automatic)
        {
            cfg.FfxDenoiserSignalCount.reset();
            cfg.FfxDenoiserDiffuseSignalType.reset();
            cfg.FfxDenoiserSpecularSignalType.reset();
            cfg.FfxDenoiserDenoiseDiffuse.reset();
            cfg.FfxDenoiserDenoiseSpecular.reset();
        }
        else
            StoreLayout(cfg, RequestedLayout(cfg, status));
        rebuild = true;
    }
    if (ImGui::IsItemHovered())
        ImGui::SetTooltip("Selects one diffuse and one specular signal from the game's validated inputs. "
                          "Editing a signal below switches to a custom layout.");
    bool approxSpec = cfg.FfxDenoiserApproximateSpecHitDistance.value_or_default();
    bool approxRay = cfg.FfxDenoiserApproximateRayHitDistance.value_or_default();
    const bool observed = (status & 4u) != 0, nativeSpec = observed && (status & 1u),
               nativeRay = observed && (status & 2u);
    if (observed)
    {
        std::string active;
        for (int signal : FSRDSignals::Preferred)
            if ((status >> 8) & FSRDSignals::Bit(signal))
            {
                if (!active.empty()) active += " + ";
                active += FSRDSignals::Names[signal];
            }
        ImGui::TextWrapped("Active RR signals: %s", active.empty() ? "None" : active.c_str());
    }
    const auto source = [&](bool native, bool approximate)
    {
        return native        ? "Game input"
               : approximate ? "Approximate (view depth)"
               : observed    ? "Not supplied"
                             : "Waiting for game input";
    };
    ImGui::Text("Spec hit distance: %s", source(nativeSpec, approxSpec));
    ImGui::Text("Ray hit distance (diffuse): %s", source(nativeRay, approxRay));
    if (ImGui::Checkbox("Approximate Spec Hit Distance", &approxSpec))
    {
        cfg.FfxDenoiserApproximateSpecHitDistance = approxSpec;
        rebuild = true;
    }
    if (ImGui::IsItemHovered())
        ImGui::SetTooltip(
            "Uses primary view depth only when the specular ray length is missing or invalid. This is an experimental "
            "estimate of secondary distance; native valid hits and environment misses take priority.");
    if (ImGui::Checkbox("Approximate Ray Hit Distance", &approxRay))
    {
        cfg.FfxDenoiserApproximateRayHitDistance = approxRay;
        rebuild = true;
    }
    if (ImGui::IsItemHovered())
        ImGui::SetTooltip("Uses primary view depth when diffuse ray hit distance is missing or invalid. Enables "
                          "Indirect Diffuse without a native guide. It cannot reconstruct the real secondary ray.");
    const uint32_t available = FSRDSignals::Available(nativeSpec, nativeRay, approxSpec, approxRay);
    auto layout = RequestedLayout(cfg, status);
    const char* counts[] { "1 signal", "2 signals", "3 signals", "4 signals" };
    if (ImGui::BeginCombo("Signal Count", counts[layout.count - 1]))
    {
        for (int count = 1; count <= 4; ++count)
        {
            const bool supported = count <= FSRDSignals::Count(available);
            ImGui::BeginDisabled(!supported);
            if (ImGui::Selectable(counts[count - 1], layout.count == count))
            {
                layout = FSRDSignals::Resolve(count, layout.slots, available);
                StoreLayout(cfg, layout);
                rebuild = true;
            }
            ImGui::EndDisabled();
            if (!supported && ImGui::IsItemHovered(ImGuiHoveredFlags_AllowWhenDisabled))
                ImGui::SetTooltip("Needs more indirect-signal guides. Supply the corresponding game hit distance or "
                                  "enable its approximation above.");
        }
        ImGui::EndCombo();
    }
    for (int slot = 0; slot < layout.count; ++slot)
    {
        ImGui::PushID(slot);
        const std::string label = "Signal " + std::to_string(slot + 1);
        if (ImGui::BeginCombo(label.c_str(), FSRDSignals::Names[layout.slots[slot]]))
        {
            for (int signal = 0; signal < 4; ++signal)
            {
                const bool selected = layout.slots[slot] == signal;
                const bool duplicate = !selected && (layout.mask & FSRDSignals::Bit(signal));
                const bool missing = !(available & FSRDSignals::Bit(signal));
                ImGui::BeginDisabled(duplicate || missing);
                if (ImGui::Selectable(FSRDSignals::Names[signal], selected))
                {
                    layout.slots[slot] = signal;
                    layout = FSRDSignals::Resolve(layout.count, layout.slots);
                    StoreLayout(cfg, layout);
                    rebuild = true;
                }
                ImGui::EndDisabled();
                if ((duplicate || missing) && ImGui::IsItemHovered(ImGuiHoveredFlags_AllowWhenDisabled))
                    ImGui::SetTooltip(
                        "%s",
                        duplicate
                            ? "Already assigned to another slot."
                            : "Required hit distance is missing. Enable its approximation or use a supplied signal.");
            }
            ImGui::EndCombo();
        }
        ImGui::PopID();
    }
    if (!cfg.FfxDenoiserSignalCount.has_value())
        ImGui::TextDisabled("%s", automatic
            ? "Automatic game classification; editing a slot saves a fixed layout."
            : "Legacy signal overrides active; enable Automatic or edit a slot to replace them.");
    if (observed && ((layout.mask & available) != layout.mask))
    {
        if (cfg.FfxDenoiserSignalCount.has_value() && (((status >> 8) & 15u & ~available) == 0))
            ImGui::TextWrapped(
                "A saved assignment is unavailable. RR uses %d supported signals until its guide returns.",
                FSRDSignals::Count((status >> 8) & 15u));
        else
            ImGui::TextWrapped("A selected indirect signal has no distance guide. Choose a supported assignment or "
                               "enable its approximation.");
    }
    if ((layout.mask & 5u) == 5u || (layout.mask & 10u) == 10u)
        ImGui::TextWrapped("Experimental: the game supplies combined lighting. Selecting both Direct and Indirect "
                           "splits that lobe 50/50, then combines the denoised outputs. Unsupported Albedo uses Direct "
                           "Specular as its alternate reconstruction instead.");
    if (ImGui::Button("Reset Signal Modes"))
    {
        cfg.FfxDenoiserSignalCount.reset();
        cfg.FfxDenoiserSignal1.reset();
        cfg.FfxDenoiserSignal2.reset();
        cfg.FfxDenoiserSignal3.reset();
        cfg.FfxDenoiserSignal4.reset();
        cfg.FfxDenoiserDiffuseSignalType.reset();
        cfg.FfxDenoiserSpecularSignalType.reset();
        cfg.FfxDenoiserDenoiseDiffuse.reset();
        cfg.FfxDenoiserDenoiseSpecular.reset();
        cfg.FfxDenoiserApproximateSpecHitDistance.reset();
        cfg.FfxDenoiserApproximateRayHitDistance.reset();
        rebuild = true;
    }
    return rebuild;
}
inline void DrawUnsupportedAlbedo(Config& cfg, uint32_t status)
{
    const auto layout = RequestedLayout(cfg, status);
    const bool compatible = FSRDSignals::SupportsUnsupportedAlbedo(layout.mask) &&
                            FSRDSignals::SupportsUnsupportedAlbedo((status >> 8) & 15u) &&
                            cfg.FfxDenoiserSpecularAlbedoDemodulation.value_or_default() == 1.0f &&
                            cfg.FfxDenoiserDiffuseAlbedoModulation.value_or_default() == 1.0f &&
                            cfg.FfxDenoiserAdditiveLightSplit.value_or_default() == 0.0f;
    bool enabled = cfg.FfxDenoiserUnsupportedAlbedoRecovery.value_or_default();
    ImGui::BeginDisabled(!compatible && !enabled);
    if (ImGui::Checkbox("Unsupported Albedo", &enabled))
        cfg.FfxDenoiserUnsupportedAlbedoRecovery = enabled;
    ImGui::EndDisabled();
    if (ImGui::IsItemHovered(ImGuiHoveredFlags_AllowWhenDisabled))
        ImGui::SetTooltip(
            "Uses the selected Direct Specular slot for an unmodulated alternate. Same-surface evidence replaces the "
            "specular reconstruction where lighting does not support the albedo pattern (for example water over a "
            "visible sea floor). Adds seven recovery passes. Off by default; validate per game.");
    if (!compatible)
        ImGui::TextWrapped("%sRequires Direct Specular + Indirect Specular + a diffuse signal, both modulation "
                           "strengths at 1, and Additive Light Split at 0.",
                           enabled ? "Paused. " : "");
}
inline void DrawTimings(Config& cfg, const FSRDStageTimings::Snapshot& timing)
{
    bool enabled = cfg.FfxDenoiserGpuTimings.value_or_default();
    if (ImGui::Checkbox("Stage GPU Timings", &enabled))
        cfg.FfxDenoiserGpuTimings = enabled;
    if (ImGui::IsItemHovered())
        ImGui::SetTooltip("GPU timestamps sampled every 16 evaluations. Results appear only after the recording and "
                          "all GPU submissions retire; no CPU wait. AMD RR / ML measures the complete AMD denoiser "
                          "dispatch, including its internal preparation.");
    if (!enabled)
        return;
    const bool stale =
        timing.validMask && std::chrono::steady_clock::now() - timing.completed > std::chrono::seconds(2);
    if (ImGui::BeginTable("RRStageTimes", 2, ImGuiTableFlags_SizingStretchProp))
    {
        for (unsigned stage = 0; stage < FSRDStageTimings::Count; ++stage)
        {
            ImGui::TableNextRow();
            ImGui::TableNextColumn();
            ImGui::TextUnformatted(FSRDStageTimings::Names[stage]);
            ImGui::TableNextColumn();
            if (!timing.available)
                ImGui::TextDisabled("Unavailable");
            else if (timing.validMask & (1u << stage))
            {
                if (stale)
                    ImGui::TextDisabled("%.3f ms (last sample)", timing.milliseconds[stage]);
                else
                    ImGui::Text("%.3f ms", timing.milliseconds[stage]);
            }
            else
                ImGui::TextDisabled(timing.sequence ? "Not run" : "Waiting...");
        }
        ImGui::EndTable();
    }
}
} // namespace FSRDMenu
