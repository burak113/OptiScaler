#pragma once
#include <Config.h>
#include <imgui/imgui.h>
#include "upscalers/fsr31/FSRDSignalPolicy.h"
#include "gpu_time/FSRDStageTimings_Dx12.h"
#include <string>

namespace FSRDMenu
{
inline const ImVec4 Red(1.0f, 0.32f, 0.28f, 1.0f), Green(0.3f, 0.9f, 0.45f, 1.0f), Amber(1.0f, 0.72f, 0.25f, 1.0f);
inline void DrawFlatTemporalControls(Config& cfg)
{
    bool enabled = cfg.FfxDenoiserRecoveryFlatTemporal.value_or_default();
    if (ImGui::Checkbox("Temporal detail##RecoveryFlat", &enabled))
        cfg.FfxDenoiserRecoveryFlatTemporal = enabled;
    if (ImGui::IsItemHovered())
        ImGui::SetTooltip("Combines validated original frames to clean screen texture while RR supplies lighting. "
                          "Motion, depth, normals and video changes reject history. Off uses current-frame A4. "
                          "Changing this control clears old history. Default on.");
    ImGui::BeginDisabled(!enabled);
    int length = std::clamp(cfg.FfxDenoiserRecoveryFlatHistoryLength.value_or_default(), 1, 6);
    if (ImGui::SliderInt("History length##RecoveryFlat", &length, 1, 6, "%d frames"))
        cfg.FfxDenoiserRecoveryFlatHistoryLength = length;
    if (ImGui::IsItemHovered())
        ImGui::SetTooltip("Maximum original past frames, 1 to 6. More valid samples reduce grain; rejected samples "
                          "never extend the history. Changing the length clears old history. Default 6.");
    float denoise = std::clamp(cfg.FfxDenoiserRecoveryFlatTemporalDenoise.value_or_default(), 0.0f, 2.0f);
    if (ImGui::SliderFloat("Temporal denoise##RecoveryFlat", &denoise, 0.0f, 2.0f, "%.2f"))
        cfg.FfxDenoiserRecoveryFlatTemporalDenoise = denoise;
    if (ImGui::IsItemHovered())
        ImGui::SetTooltip("How strongly disagreement between the history samples counts as noise. Static texture "
                          "agrees over time, flickering light does not. Where the history is thin (a reflection "
                          "moving over the surface, disocclusion) the noisy single-frame detail also fades out "
                          "to RR. Higher is cleaner and calmer, with slightly softer fine edges; 0 turns it off. "
                          "Default 1.");
    ImGui::EndDisabled();
}

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
        ImGui::SetTooltip("Recovery v2 profiles. All lighting goes through RR in every profile.\n"
                          "Fast: no recovery.\n"
                          "Balanced (default): Specular, Diffuse and Near Zero-Rough recovery, Light history reset.\n"
                          "Quality: the same with the Medium history reset.\n"
                          "Manual edits are saved as Custom. Signal routing and the RR input fixes are separate.");
    return changed;
}

struct DenoiserChoice
{
    bool rebuild = false;
    bool fsrRR = false; // FSR-RR is the selected denoiser; its settings are shown
};
inline DenoiserChoice DrawDenoiser(Config& cfg, const FSRDRuntimeSnapshot& snapshot,
                                   bool ffxActive, bool nvRRActive, bool providerAvailable, bool nativeRRPreferred)
{
    const ImVec4 red = Red, green = Green;
    const bool eligible = ffxActive && nvRRActive && providerAvailable;
    const bool automatic = !cfg.FfxDenoiserEnabled.has_value();
    const bool requested = ffxActive && nvRRActive && cfg.FfxDenoiserEnabled.value_or(!nativeRRPreferred);
    const bool fresh = snapshot.updated.time_since_epoch().count() != 0 &&
        std::chrono::steady_clock::now() - snapshot.updated < std::chrono::seconds(2);
    const bool running = fresh && snapshot.rrValidated;
    const bool retrying = snapshot.recoveryResult == FSRD::RRResult::RetryableInputFailure;
    const char* selected = !nvRRActive ? "Native / NRD (game)"
        : snapshot.gameNativeRequested ? "Native / NRD requested"
        : requested ? (running ? "FSR-RR" : snapshot.failure.empty() ? "Checking FSR-RR"
            : retrying ? "FSR-RR retry pending" : "FSR-RR stopped")
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
                      "and active NV RR input only after the required runtime stages succeed. Temporary input "
                      "failures retry automatically. A persistent context/provider fault uses native fallback "
                      "or requests the game's native denoiser (NRD where the game provides it).");
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
                : retrying ? "automatic retry pending"
                : !snapshot.failure.empty() ? "failed" : "waiting for a complete frame");
        if (requested && retrying)
            ImGui::TextWrapped("Temporary input/configuration failure. Existing context retained; retry in %u frame(s).",
                               snapshot.retryFramesRemaining);
        else if (requested && snapshot.recoveryResult == FSRD::RRResult::NeedsRecreation)
            ImGui::TextWrapped("Context recovery required. Use Retry FSR-RR or recreate the feature.");
        else if (requested && snapshot.recoveryResult == FSRD::RRResult::UnsupportedProvider)
            ImGui::TextWrapped("AMD RR provider is missing or incompatible. Automatic retries are stopped.");
        else if (snapshot.recoveryResult == FSRD::RRResult::DeviceLost)
            ImGui::TextWrapped("D3D12 device lost. RR and native dispatches remain stopped until device recovery.");
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
    return { rebuild, requested };
}

inline void DrawWorkflow(const FSRDRuntimeSnapshot& snapshot)
{
    if (!ImGui::CollapsingHeader("How it works / Live pipeline")) return;
    using R = FSRDRuntimeSnapshot;
    const char* steps[] = {
        "1. Validate color, depth, motion, normals, roughness, albedo and camera transforms.",
        "2. Prepare canonical signed linear depth.",
        "3. Convert guides and split scene color into the selected RR signals.",
        "4. AMD Ray Regeneration denoises the bound diffuse/specular signals.",
        "5. Albedo Bleed Fix builds surface trust from the alternate RR copies.",
        "6. Compose RR lighting, recover ordinary surfaces, then restore Near Zero-Rough detail.",
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
                      "Temporary input/configuration failures keep the context and retry automatically with "
                      "at most 60 skipped frames between attempts. Context, provider or device faults stop FSR-RR "
                      "until Retry or recreation. Native NVIDIA RR + SR is used when available; a persistent "
                      "fault without native fallback requests game-native denoising. "
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

inline std::string DescribePlan(const FSRDSignals::Plan& plan)
{
    using namespace FSRDSignals;
    const auto lobe = [&plan](int direct, int indirect) -> std::string
    {
        const uint32_t bits = plan.mask & (Bit(direct) | Bit(indirect));
        return !bits ? "not denoised" : bits == Bit(direct) ? "Direct" : bits == Bit(indirect) ? "Indirect"
                                                                                            : "Direct + Indirect (split)";
    };
    const int count = Count(plan.mask);
    return "Diffuse " + (plan.albedoFix ? std::string("Direct + fix copy") : lobe(DirectDiffuse, IndirectDiffuse)) +
           " | Specular " +
           (plan.albedoFix ? std::string("Indirect + fix copy") : lobe(DirectSpecular, IndirectSpecular)) + " | " +
           std::to_string(count) + (count == 1 ? " RR signal" : " RR signals");
}

// The plan the current settings ask for, given the guides the running context reported.
inline FSRDSignals::Plan WantedPlan(const Config& cfg, const FSRDSignals::Status& status)
{
    return FSRDSignals::MakePlan(FSRDSignals::RequestFrom(cfg), status.specularGuide, status.diffuseGuide);
}

inline void DrawSignalSummary(const Config& cfg, const FSRDSignals::Status& status)
{
    if (!status.observed)
    {
        ImGui::TextDisabled("RR input: waiting for the first validated frame");
        return;
    }
    ImGui::TextWrapped("RR input: %s", DescribePlan(status.plan).c_str());
    if (ImGui::IsItemHovered())
        ImGui::SetTooltip("What AMD Ray Regeneration receives. The game supplies one combined colour; Direct and "
                          "Indirect are RR paths, and Indirect also uses the game's hit distance.");
    const auto wanted = WantedPlan(cfg, status);
    if (wanted.mask != status.plan.mask || wanted.albedoFix != status.plan.albedoFix)
        ImGui::TextDisabled("Applying: %s", DescribePlan(wanted).c_str());
}

// Advanced per-lobe routing. Returns true when the RR context must be rebuilt.
inline bool DrawRouting(Config& cfg, const FSRDSignals::Status& status)
{
    using namespace FSRDSignals;
    bool rebuild = false;
    const auto request = RequestFrom(cfg);
    const auto plan = WantedPlan(cfg, status);
    const auto route = [&](const char* label, CustomOptional<int>& setting, bool denoised, int direct, int indirect,
                           bool guide, const char* locked)
    {
        const uint32_t bits = plan.mask & (Bit(direct) | Bit(indirect));
        const int current = std::clamp(setting.value_or_default(), int(Auto), int(Split));
        const char* automatic = !status.observed   ? "Auto (waiting for the game)"
                                : bits != Bit(indirect) ? "Auto: Direct (no distance)"
                                : guide                 ? "Auto: Indirect (game distance)"
                                                        : "Auto: Indirect (estimated)";
        const std::string preview = !denoised ? "Off (Debug)"
            : locked                          ? std::string(locked)
            : current == Auto                 ? std::string(automatic)
            : current == Split                ? "Split (INI)"
                                              : std::string(current == Direct ? "Direct" : "Indirect");
        ImGui::BeginDisabled(!denoised || locked);
        if (ImGui::BeginCombo(label, preview.c_str()))
        {
            const char* names[] { "Auto", "Direct", "Indirect", "Split (INI)" };
            for (int value = Auto; value <= Split; ++value)
            {
                // Split has no measured benefit; it stays reachable only from the INI.
                if (value == Split && current != Split)
                    continue;
                if (ImGui::Selectable(names[value], current == value))
                {
                    if (value == Auto) setting.reset();
                    else setting = value;
                    rebuild = true;
                }
            }
            ImGui::EndCombo();
        }
        ImGui::EndDisabled();
        if (ImGui::IsItemHovered(ImGuiHoveredFlags_AllowWhenDisabled))
            ImGui::SetTooltip("%s", locked ? "Set by the Albedo Bleed Fix: each lobe's second RR path carries its "
                                             "unmodulated copy."
                                : !denoised ? "Turned off under Debug."
                                            : "Auto checks this lobe on its own: Indirect when the game "
                                              "supplies its hit distance, otherwise Direct.\nIndirect without a "
                                              "hit distance falls back to Direct. The game's colour is combined "
                                              "either way; this only picks the RR path.");
    };
    route("Diffuse Path", cfg.FfxDenoiserDiffuseRoute, plan.mask & DiffuseBits, DirectDiffuse, IndirectDiffuse,
          status.diffuseGuide, plan.albedoFix ? "Direct + fix copy" : nullptr);
    route("Specular Path", cfg.FfxDenoiserSpecularRoute, plan.mask & SpecularBits, DirectSpecular, IndirectSpecular,
          status.specularGuide, plan.albedoFix ? "Indirect + fix copy" : nullptr);

    if (bool estimate = request.estimate; ImGui::Checkbox("Estimate Missing Hit Distances (experimental)", &estimate))
    {
        cfg.FfxDenoiserEstimateHitDistances = estimate;
        rebuild = true;
    }
    if (ImGui::IsItemHovered())
        ImGui::SetTooltip("Uses primary view depth where the game supplies no valid hit distance, so Indirect paths "
                          "work without a game guide. It cannot reconstruct the real secondary ray and has no "
                          "measured quality gain yet.");
    const auto guide = [&status](bool present)
    { return !status.observed ? "waiting" : present ? "supplied" : "missing"; };
    ImGui::TextDisabled("Game hit distances: specular %s, diffuse %s", guide(status.specularGuide),
                        guide(status.diffuseGuide));
    if (status.observed && (plan.notes & (DiffuseNeedsDistance | SpecularNeedsDistance)))
        ImGui::TextColored(Amber, "%s Indirect needs a hit distance the game does not supply; using Direct.",
                           (plan.notes & DiffuseNeedsDistance) && (plan.notes & SpecularNeedsDistance) ? "Diffuse and specular"
                           : (plan.notes & DiffuseNeedsDistance) ? "Diffuse"
                                                                 : "Specular");
    if (ImGui::Button("Reset Signal Routing"))
    {
        cfg.FfxDenoiserDiffuseRoute.reset();
        cfg.FfxDenoiserSpecularRoute.reset();
        cfg.FfxDenoiserEstimateHitDistances.reset();
        rebuild = true;
    }
    return rebuild;
}

// Debug-only single-lobe denoising. Returns true when the RR context must be rebuilt.
inline bool DrawDenoiseLobes(Config& cfg)
{
    bool rebuild = false;
    bool diffuse = cfg.FfxDenoiserDenoiseDiffuse.value_or_default();
    bool specular = cfg.FfxDenoiserDenoiseSpecular.value_or_default();
    if (ImGui::Checkbox("Denoise Diffuse", &diffuse))
    {
        if (diffuse) cfg.FfxDenoiserDenoiseDiffuse.reset();
        else cfg.FfxDenoiserDenoiseDiffuse = false;
        rebuild = true;
    }
    ImGui::SameLine();
    if (ImGui::Checkbox("Denoise Specular", &specular))
    {
        if (specular) cfg.FfxDenoiserDenoiseSpecular.reset();
        else cfg.FfxDenoiserDenoiseSpecular = false;
        rebuild = true;
    }
    if (ImGui::IsItemHovered())
        ImGui::SetTooltip("A lobe that is off bypasses RR and is composed from its raw signal. Turning both off "
                          "denoises both.");
    return rebuild;
}

// Compare (split) view: shows two pipeline variants side by side in one frame so a feature
// can be judged by eye without a menu toggle and a moving camera between the two images.
inline void DrawCompareView(Config& cfg)
{
    const char* modes[] = { "Off", "RR only vs final", "Recovery v2 off vs on", "Near Zero-Rough off vs on",
                            "Skin re-blur off vs on" };
    int mode = std::clamp(cfg.FfxDenoiserCompareView.value_or_default(), 0, 4);
    if (ImGui::Combo("Compare (split) view", &mode, modes, IM_ARRAYSIZE(modes)))
        cfg.FfxDenoiserCompareView = mode;
    if (ImGui::IsItemHovered())
        ImGui::SetTooltip("Draws two variants of the same frame: left is the feature off / earlier pipeline stage,\n"
                          "right is the feature on / later stage. The split is drawn AFTER the normal upscale, from\n"
                          "same-frame PRE-SR images. Both halves get the same spatial upscale for this debug display,\n"
                          "so it is a pre-SR A/B presentation, not two temporal-SR outputs. The canonical composition\n"
                          "keeps feeding the upscaler and GAME_TRACE; the view never changes a history and costs\n"
                          "nothing while off. Input-side pairs (albedo stabilisation, the colour noise filter, RR\n"
                          "resolution scale) are not offered: they would need RR to run twice.");
    ImGui::BeginDisabled(mode == 0);
    if (float v = std::clamp(cfg.FfxDenoiserCompareSplit.value_or_default(), 0.05f, 0.95f);
        ImGui::SliderFloat("Divider##CompareView", &v, 0.05f, 0.95f, "%.2f of width"))
        cfg.FfxDenoiserCompareSplit = v;
    if (ImGui::IsItemHovered())
        ImGui::SetTooltip("Position of the vertical divider as a fraction of the render width.");
    bool swap = cfg.FfxDenoiserCompareSwap.value_or_default();
    if (ImGui::Checkbox("Swap sides##CompareView", &swap))
        cfg.FfxDenoiserCompareSwap = swap;
    if (ImGui::IsItemHovered())
        ImGui::SetTooltip("Exchanges the two halves without moving the divider.");
    bool hold = cfg.FfxDenoiserCompareHold.value_or_default();
    if (ImGui::Checkbox("Hold frame (freeze)##CompareView", &hold))
        cfg.FfxDenoiserCompareHold = hold;
    if (ImGui::IsItemHovered())
        ImGui::SetTooltip("Freezes the displayed split for close inspection. The hold key toggles this same switch.");
    int holdKey = std::clamp(cfg.FfxDenoiserCompareHoldKey.value_or_default(), 0, 255);
    if (ImGui::SliderInt("Hold key (VK code)##CompareView", &holdKey, 0, 255, holdKey == 0 ? "off" : "%d"))
        cfg.FfxDenoiserCompareHoldKey = holdKey;
    if (ImGui::IsItemHovered())
        ImGui::SetTooltip("Momentary-capable toggle key for Hold frame. 0 disables. Default 120 (F9).");
    ImGui::EndDisabled();
    ImGui::TextDisabled("Cost while active: two render-size snapshot copies plus one output-size combine + present pass; zero when off.");
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
    bool passes = cfg.FfxDenoiserPassTimings.value_or_default();
    if (ImGui::Checkbox("Show pass timings", &passes))
        cfg.FfxDenoiserPassTimings = passes;
    if (ImGui::IsItemHovered())
        ImGui::SetTooltip("Per-pass breakdown inside each stage, with a rolling median and p95 over the last "
                          "samples. Off by default: nothing extra is queried or allocated. 'Log pass timings' "
                          "writes the table to the OptiScaler log on demand.");
    if (!enabled && !passes)
        return;
    const bool stale = timing.validMask &&
        std::chrono::steady_clock::now() - timing.completed > std::chrono::seconds(2);
    const auto milliseconds = [](double value) { return ImGui::Text("%.3f", value); };
    const auto statistic = [&](const FSRDStageTimings::PassStat& value)
    {
        if (value.valid)
            ImGui::Text("%.3f", value.median);
        else
            ImGui::TextDisabled("-");
    };
    const auto statistic95 = [&](const FSRDStageTimings::PassStat& value)
    {
        if (value.valid)
            ImGui::Text("%.3f", value.p95);
        else
            ImGui::TextDisabled("-");
    };
    if (enabled && ImGui::BeginTable("RRStageTimes", 4, ImGuiTableFlags_SizingStretchProp | ImGuiTableFlags_RowBg))
    {
        ImGui::TableSetupColumn("Stage");
        ImGui::TableSetupColumn("Latest");
        ImGui::TableSetupColumn("Median");
        ImGui::TableSetupColumn("p95");
        ImGui::TableHeadersRow();
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
                    ImGui::TextDisabled("%.3f", timing.milliseconds[stage]);
                else
                    milliseconds(timing.milliseconds[stage]);
            }
            else
                ImGui::TextDisabled(timing.sequence ? "Not run" : "Waiting...");
            ImGui::TableNextColumn();
            statistic(timing.rolling.stages[stage]);
            ImGui::TableNextColumn();
            statistic95(timing.rolling.stages[stage]);
        }
        ImGui::EndTable();
    }
    if (!passes)
        return;
    if (ImGui::Button("Log pass timings"))
        LOG_INFO("{}", FSRDStageTimings::FormatReport(timing));
    if (ImGui::IsItemHovered())
        ImGui::SetTooltip("Writes the current rolling per-pass table to the OptiScaler log.");
    ImGui::SameLine();
    ImGui::TextDisabled("window: last %u samples", timing.rolling.samples);
    if (ImGui::BeginTable("RRPassTimes", 4, ImGuiTableFlags_SizingStretchProp | ImGuiTableFlags_RowBg))
    {
        ImGui::TableSetupColumn("Pass");
        ImGui::TableSetupColumn("Latest");
        ImGui::TableSetupColumn("Median");
        ImGui::TableSetupColumn("p95");
        ImGui::TableHeadersRow();
        for (unsigned stage = 0; stage < FSRDStageTimings::Count; ++stage)
        {
            bool wroteStage = false;
            for (unsigned pass = 0; pass < FSRDStageTimings::PassCount; ++pass)
            {
                if (unsigned(FSRDStageTimings::PassStage(FSRDStageTimings::Pass(pass))) != stage)
                    continue;
                if (!wroteStage)
                {
                    // Stage header row: the stage's own measured rolled-up time.
                    wroteStage = true;
                    ImGui::TableNextRow();
                    ImGui::TableNextColumn();
                    ImGui::TextUnformatted(FSRDStageTimings::Names[stage]);
                    ImGui::TableNextColumn();
                    ImGui::TextDisabled("-");
                    ImGui::TableNextColumn();
                    statistic(timing.rolling.stages[stage]);
                    ImGui::TableNextColumn();
                    statistic95(timing.rolling.stages[stage]);
                }
                ImGui::TableNextRow();
                ImGui::TableNextColumn();
                ImGui::Indent();
                ImGui::TextUnformatted(FSRDStageTimings::PassNames[pass]);
                ImGui::Unindent();
                ImGui::TableNextColumn();
                if (!timing.available)
                    ImGui::TextDisabled("Unavailable");
                else if (timing.passValidMask & (1u << pass))
                {
                    if (stale)
                        ImGui::TextDisabled("%.3f", timing.passMilliseconds[pass]);
                    else
                        milliseconds(timing.passMilliseconds[pass]);
                }
                else
                    ImGui::TextDisabled(timing.sequence ? "Not run" : "Waiting...");
                ImGui::TableNextColumn();
                statistic(timing.rolling.passes[pass]);
                ImGui::TableNextColumn();
                statistic95(timing.rolling.passes[pass]);
            }
        }
        // Total of the measured passes in one sample, rolled the same way.
        ImGui::TableNextRow();
        ImGui::TableNextColumn();
        ImGui::TextUnformatted("Total (passes)");
        ImGui::TableNextColumn();
        ImGui::TextDisabled("-");
        ImGui::TableNextColumn();
        statistic(timing.rolling.passTotal);
        ImGui::TableNextColumn();
        statistic95(timing.rolling.passTotal);
        ImGui::EndTable();
    }
}
} // namespace FSRDMenu
