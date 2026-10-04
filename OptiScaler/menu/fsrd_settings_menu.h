#pragma once
#include <Config.h>
#include <imgui/imgui.h>
#include "upscalers/fsr31/FSRDSignalPolicy.h"
#include "gpu_time/FSRDStageTimings_Dx12.h"

namespace FSRDMenu
{
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
