#pragma once
#include <d3d12.h>
#include "../upscalers/fsr31/FSRDRetryPolicy.h"
#include <wrl/client.h>
#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <functional>
#include <limits>
#include <memory>
#include <mutex>
#include <string>

// One immutable query allocation per sampled evaluation. The caller's recording /
// submission lease must retain it through command-list Reset and GPU fence completion.
// This deliberately never reuses a readback ring based only on a CPU frame index.
class FSRDStageTimings
{
  public:
    enum Stage : unsigned
    {
        Geometry,
        Conversion,
        RayRegeneration,
        AlbedoRecovery,
        Composition,
        SuperResolution,
        SkinPrepare,
        SkinPrefilter,
        SkinReblur,
        InputInventory,
        ReferenceAccumulation,
        TextureLeak,
        AlbedoStabilisation,
        FogGuides,
        Recovery,
        FlatDetail,
        Count
    };
    static constexpr const char* Names[] { "Geometry",           "Conversion",  "AMD RR / ML",
                                           "Albedo Bleed Fix", "Composition", "Super Resolution",
                                           "SSS input", "Skin diffuse prefilter", "SSS re-blur",
                                           "Input inventory", "Reference accumulation", "Texture leak",
                                           "Albedo stabilisation", "Fog guides", "Recovery v2", "Flat Detail" };

    // Finer breakdown of a stage: one id per full-screen dispatch (or gather) a stage issues.
    // A pass belongs to exactly one stage (PassStage); a stage with untimed work can be a
    // little larger than the sum of its passes. Prefixing keeps the enumerators distinct from
    // the Stage enum, which shares this class scope.
    enum Pass : unsigned
    {
        PassGeometryDepth,          // Geometry
        PassConversionPack,         // Conversion: skin-fused, skin or plain packing dispatch
        PassRrMotionCopy,           // Conversion: RR jitter-delta motion copy
        PassAlbedoStabilise,        // Albedo stabilisation
        PassFogStats,               // Fog guides
        PassFogKappa,
        PassFogRank,
        PassFogSmooth,
        PassFogRoute,
        PassTextureLeak,            // Texture leak lobe
        PassSkinPrepare,            // SSS input
        PassSkinPrefilterBounds,    // Skin diffuse prefilter
        PassSkinPrefilterH,
        PassSkinPrefilterV,
        PassAlbedoTrustEvidence,    // Albedo bleed fix
        PassAlbedoTrustPropagate,
        PassCompositionMain,        // Output composition
        PassRecoveryAccumulate,     // Recovery v2
        PassRecoveryDown,
        PassRecoveryBand,
        PassSkinReblurKernel,       // SSS re-blur
        PassSkinReblurH,
        PassSkinReblurV,
        PassFlatClassify,           // Flat Detail
        PassFlatSeed,
        PassFlatRefine,
        PassFlatBase,
        PassFlatApply,
        PassFlatTemporalResolve,
        PassFlatTemporalStore,
        PassRrDenoise,              // AMD RR / ML
        PassSuperResolution,        // FSR super resolution
        PassCount
    };
    static constexpr const char* PassNames[] {
        "Geometry depth", "Packing / conversion", "RR motion jitter copy", "Albedo stabilisation",
        "Fog stats", "Fog kappa", "Fog kappa rank", "Fog kappa smooth", "Fog route",
        "Texture leak", "SSS input", "Skin bounds", "Skin prefilter H", "Skin prefilter V",
        "Albedo trust evidence", "Albedo trust propagate", "Composition",
        "Recovery accumulate", "Recovery down", "Recovery band",
        "SSS kernel", "SSS re-blur H", "SSS re-blur V",
        "Flat classify", "Flat seed", "Flat refine", "Flat base", "Flat apply",
        "Flat temporal LP + resolve", "Flat temporal store", "AMD RR / ML", "Super resolution" };
    static constexpr Stage PassStage(Pass pass)
    {
        // Indexed by Pass; must stay in lockstep with the Pass enum above.
        constexpr Stage stages[PassCount] = {
            Geometry, Conversion, Conversion,
            AlbedoStabilisation, FogGuides, FogGuides, FogGuides, FogGuides, FogGuides, TextureLeak,
            SkinPrepare, SkinPrefilter, SkinPrefilter, SkinPrefilter,
            AlbedoRecovery, AlbedoRecovery, Composition,
            Recovery, Recovery, Recovery, SkinReblur, SkinReblur, SkinReblur,
            FlatDetail, FlatDetail, FlatDetail, FlatDetail, FlatDetail, FlatDetail, FlatDetail,
            RayRegeneration, SuperResolution
        };
        return stages[unsigned(pass)];
    }
    static_assert(sizeof(PassNames) / sizeof(PassNames[0]) == unsigned(PassCount),
                  "PassNames must describe every pass");
    static_assert(sizeof(Names) / sizeof(Names[0]) == unsigned(Count), "Names must describe every stage");

    struct PassStat
    {
        double median = 0.0;
        double p95 = 0.0;
        bool valid = false;
    };
    struct RollingStats
    {
        std::array<PassStat, Count> stages {};
        std::array<PassStat, PassCount> passes {};
        // Per-sample sum over the passes (stages) recorded in that sample. The pass total is the
        // measured FSRD dispatch time; the stage total can double count nested stages.
        PassStat passTotal {};
        unsigned samples = 0; // samples in the rolling window
    };
    struct Snapshot
    {
        std::array<double, Count> milliseconds {};
        std::array<double, PassCount> passMilliseconds {};
        unsigned validMask = 0;
        unsigned passValidMask = 0;
        uint64_t sequence = 0;
        std::chrono::steady_clock::time_point completed {};
        bool available = true;
        RollingStats rolling {};
    };

  private:
    static_assert(unsigned(PassCount) <= 32, "the pass validity mask is 32-bit");

    // Fixed-size rolling window of published samples. An entry that was not recorded is NaN
    // and is skipped by the statistics; the window is only touched while publishing a sample
    // (at most once every 16 evaluations), so it costs nothing on the render path.
    struct History
    {
        static constexpr unsigned kDepth = 32;
        std::array<std::array<double, kDepth>, Count> stages {};
        std::array<std::array<double, kDepth>, PassCount> passes {};
        std::array<double, kDepth> passTotal {};
        unsigned count = 0, head = 0;

        static PassStat Stat(const double* values, unsigned samples)
        {
            double buffer[kDepth];
            unsigned kept = 0;
            for (unsigned i = 0; i < samples; ++i)
                if (std::isfinite(values[i]))
                    buffer[kept++] = values[i];
            PassStat result;
            if (!kept)
                return result;
            std::sort(buffer, buffer + kept);
            result.median = (kept & 1u) ? buffer[kept / 2] : 0.5 * (buffer[kept / 2 - 1] + buffer[kept / 2]);
            unsigned rank = unsigned(std::ceil(0.95 * double(kept)));
            if (rank < 1u)
                rank = 1u;
            if (rank > kept)
                rank = kept;
            result.p95 = buffer[rank - 1];
            result.valid = true;
            return result;
        }
        void Push(const Snapshot& sample)
        {
            const double none = std::numeric_limits<double>::quiet_NaN();
            for (unsigned i = 0; i < Count; ++i)
                stages[i][head] = (sample.validMask & (1u << i)) ? sample.milliseconds[i] : none;
            for (unsigned p = 0; p < PassCount; ++p)
                passes[p][head] = (sample.passValidMask & (1u << p)) ? sample.passMilliseconds[p] : none;
            double total = 0.0;
            bool any = false;
            for (unsigned p = 0; p < PassCount; ++p)
                if (sample.passValidMask & (1u << p)) { total += sample.passMilliseconds[p]; any = true; }
            passTotal[head] = any ? total : none;
            if (count < kDepth)
                ++count;
            head = (head + 1u) % kDepth;
        }
        RollingStats Compute() const
        {
            RollingStats stats;
            for (unsigned i = 0; i < Count; ++i)
                stats.stages[i] = Stat(stages[i].data(), count);
            for (unsigned p = 0; p < PassCount; ++p)
                stats.passes[p] = Stat(passes[p].data(), count);
            stats.passTotal = Stat(passTotal.data(), count);
            stats.samples = count;
            return stats;
        }
    };
    struct Shared
    {
        std::mutex mutex;
        Snapshot snapshot;
        History history;
        std::atomic<unsigned> pending { 0 };
        std::atomic<uint64_t> generation { 0 };
    };
    struct Packet
    {
        std::shared_ptr<Shared> owner;
        Microsoft::WRL::ComPtr<ID3D12Device> device;
        Microsoft::WRL::ComPtr<ID3D12QueryHeap> queries;
        Microsoft::WRL::ComPtr<ID3D12Resource> readback;
        std::atomic<uint64_t> frequency { 0 };
        std::atomic<unsigned> submissions { 0 };
        uint64_t sequence = 0, generation = 0;
        unsigned started = 0, ended = 0;
        uint64_t passStarted = 0, passEnded = 0;
        unsigned slots = 0;
        bool successful = false;

        explicit Packet(std::shared_ptr<Shared> state) : owner(std::move(state)) { ++owner->pending; }
        ~Packet()
        {
            // Called only after every recording/submission lease retires. Unsubmitted,
            // resubmitted, failed or removed-device samples never become plausible ms.
            if (successful && ended && submissions.load() == 1 && frequency.load() &&
                owner->generation.load() == generation && device && readback &&
                SUCCEEDED(device->GetDeviceRemovedReason()))
            {
                D3D12_RANGE range { 0, slots * 2 * sizeof(uint64_t) };
                void* mapped = nullptr;
                if (SUCCEEDED(readback->Map(0, &range, &mapped)))
                {
                    const auto* values = static_cast<const uint64_t*>(mapped);
                    Snapshot sample;
                    sample.sequence = sequence;
                    sample.completed = std::chrono::steady_clock::now();
                    const double ticksToMs = 1000.0 / double(frequency.load());
                    for (unsigned i = 0; i < Count; ++i)
                    {
                        if (!(ended & (1u << i)) || values[2 * i + 1] < values[2 * i])
                            continue;
                        const double ms = double(values[2 * i + 1] - values[2 * i]) * ticksToMs;
                        if (std::isfinite(ms))
                        {
                            sample.milliseconds[i] = ms;
                            sample.validMask |= 1u << i;
                        }
                    }
                    for (unsigned p = 0; p < PassCount; ++p)
                    {
                        const unsigned slot = unsigned(Count) + p;
                        if (!(passEnded & (uint64_t(1) << p)) || values[2 * slot + 1] < values[2 * slot])
                            continue;
                        const double ms = double(values[2 * slot + 1] - values[2 * slot]) * ticksToMs;
                        if (std::isfinite(ms))
                        {
                            sample.passMilliseconds[p] = ms;
                            sample.passValidMask |= 1u << p;
                        }
                    }
                    D3D12_RANGE written { 0, 0 };
                    readback->Unmap(0, &written);
                    std::lock_guard lock(owner->mutex);
                    if (sample.sequence > owner->snapshot.sequence && owner->generation.load() == generation)
                    {
                        owner->history.Push(sample);
                        sample.rolling = owner->history.Compute();
                        owner->snapshot = sample;
                    }
                }
            }
            --owner->pending;
        }
    };
    std::shared_ptr<Shared> m_shared = std::make_shared<Shared>();
    std::shared_ptr<Packet> m_active;
    ID3D12GraphicsCommandList* m_list = nullptr;
    uint64_t m_sequence = 0;
    bool m_enabled = false;
    bool m_passEnabled = false;

  public:
    // retain(lease, beforeSubmit) returns false when reliable submission tracking is
    // unavailable. beforeSubmit supplies the actual executing queue's timestamp clock.
    // passEnabled adds one query pair per pass; while it is false no pass query is created.
    template <class Retain>
    void BeginFrame(ID3D12Device* device, ID3D12GraphicsCommandList* list, bool enabled, Retain retain,
                    bool passEnabled = false)
    {
        FinishFrame(false);
        if (enabled != m_enabled || passEnabled != m_passEnabled)
        {
            m_enabled = enabled;
            m_passEnabled = passEnabled;
            ++m_shared->generation;
            std::lock_guard lock(m_shared->mutex);
            m_shared->snapshot = {};
            m_shared->history = {};
        }
        const uint64_t sequence = ++m_sequence;
        if (!enabled || !device || !list || (sequence - 1) % 16 || m_shared->pending.load() >= 4)
            return;
        const unsigned slots = passEnabled ? unsigned(Count + PassCount) : unsigned(Count);
        auto packet = std::make_shared<Packet>(m_shared);
        packet->device = device;
        packet->sequence = sequence;
        packet->generation = m_shared->generation.load();
        packet->slots = slots;
        D3D12_QUERY_HEAP_DESC queryDesc { D3D12_QUERY_HEAP_TYPE_TIMESTAMP, slots * 2, 0 };
        D3D12_HEAP_PROPERTIES heap {};
        heap.Type = D3D12_HEAP_TYPE_READBACK;
        D3D12_RESOURCE_DESC desc {};
        desc.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
        desc.Width = slots * 2 * sizeof(uint64_t);
        desc.Height = desc.DepthOrArraySize = desc.MipLevels = 1;
        desc.SampleDesc.Count = 1;
        desc.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        Packet* raw = packet.get();
        if (FAILED(device->CreateQueryHeap(&queryDesc, IID_PPV_ARGS(&packet->queries))) ||
            FAILED(device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &desc, D3D12_RESOURCE_STATE_COPY_DEST,
                                                   nullptr, IID_PPV_ARGS(&packet->readback))) ||
            !retain(packet,
                    [raw](ID3D12CommandQueue* queue)
                    {
                        ++raw->submissions;
                        uint64_t frequency = 0;
                        if (queue && SUCCEEDED(queue->GetTimestampFrequency(&frequency)))
                            raw->frequency.store(frequency);
                    }))
        {
            std::lock_guard lock(m_shared->mutex);
            m_shared->snapshot.available = false;
            return;
        }
        m_list = list;
        m_active = std::move(packet);
    }
    bool Begin(Stage stage)
    {
        if (!m_active || (m_active->started & (1u << stage)))
            return false;
        m_list->EndQuery(m_active->queries.Get(), D3D12_QUERY_TYPE_TIMESTAMP, 2 * stage);
        m_active->started |= 1u << stage;
        return true;
    }
    void End(Stage stage)
    {
        if (!m_active || !(m_active->started & (1u << stage)))
            return;
        m_list->EndQuery(m_active->queries.Get(), D3D12_QUERY_TYPE_TIMESTAMP, 2 * stage + 1);
        m_list->ResolveQueryData(m_active->queries.Get(), D3D12_QUERY_TYPE_TIMESTAMP, 2 * stage, 2,
                                 m_active->readback.Get(), 2 * stage * sizeof(uint64_t));
        m_active->ended |= 1u << stage;
    }
    bool BeginPass(Pass pass)
    {
        if (!m_active || !m_passEnabled || (m_active->passStarted & (uint64_t(1) << pass)))
            return false;
        m_list->EndQuery(m_active->queries.Get(), D3D12_QUERY_TYPE_TIMESTAMP, 2 * (Count + unsigned(pass)));
        m_active->passStarted |= uint64_t(1) << pass;
        return true;
    }
    void EndPass(Pass pass)
    {
        if (!m_active || !(m_active->passStarted & (uint64_t(1) << pass)))
            return;
        const unsigned slot = unsigned(Count) + unsigned(pass);
        m_list->EndQuery(m_active->queries.Get(), D3D12_QUERY_TYPE_TIMESTAMP, 2 * slot + 1);
        m_list->ResolveQueryData(m_active->queries.Get(), D3D12_QUERY_TYPE_TIMESTAMP, 2 * slot, 2,
                                 m_active->readback.Get(), 2 * slot * sizeof(uint64_t));
        m_active->passEnded |= uint64_t(1) << pass;
    }
    void FinishFrame(bool successful)
    {
        if (m_active)
            m_active->successful = successful;
        m_active.reset();
        m_list = nullptr;
    }
    Snapshot GetSnapshot() const
    {
        std::lock_guard lock(m_shared->mutex);
        return m_shared->snapshot;
    }
    struct Scope
    {
        FSRDStageTimings* timer;
        Stage stage;
        bool started;
        Scope(FSRDStageTimings* owner, Stage value) : timer(owner), stage(value), started(owner && owner->Begin(value))
        {
        }
        ~Scope()
        {
            if (started)
                timer->End(stage);
        }
        Scope(const Scope&) = delete;
        Scope& operator=(const Scope&) = delete;
    };
    struct PassScope
    {
        FSRDStageTimings* timer;
        Pass pass;
        bool started;
        PassScope(FSRDStageTimings* owner, Pass value) : timer(owner), pass(value), started(owner && owner->BeginPass(value))
        {
        }
        ~PassScope()
        {
            if (started)
                timer->EndPass(pass);
        }
        PassScope(const PassScope&) = delete;
        PassScope& operator=(const PassScope&) = delete;
    };

    // Human-readable rolling report for the on-demand log dump. The header stays free of the
    // host logger; the caller decides where the text goes.
    static std::string FormatReport(const Snapshot& sample)
    {
        std::string out;
        out.reserve(4096);
        char line[192];
        if (!sample.available)
        {
            out = "[FSRD_PROFILE] GPU timings unavailable (reliable submission tracking failed)\n";
            return out;
        }
        if (!sample.rolling.samples)
        {
            out = "[FSRD_PROFILE] no GPU timing sample published yet\n";
            return out;
        }
        std::snprintf(line, sizeof(line), "[FSRD_PROFILE] window=%u samples\n", sample.rolling.samples);
        out += line;
        if (sample.rolling.passTotal.valid)
        {
            std::snprintf(line, sizeof(line), "[FSRD_PROFILE] total(passes) median=%.3f p95=%.3f\n",
                          sample.rolling.passTotal.median, sample.rolling.passTotal.p95);
            out += line;
        }
        for (unsigned stage = 0; stage < Count; ++stage)
        {
            const PassStat& stat = sample.rolling.stages[stage];
            if (!stat.valid)
                continue;
            std::snprintf(line, sizeof(line), "[FSRD_PROFILE] stage %-22s median=%.3f p95=%.3f\n",
                          Names[stage], stat.median, stat.p95);
            out += line;
        }
        for (unsigned pass = 0; pass < PassCount; ++pass)
        {
            const PassStat& stat = sample.rolling.passes[pass];
            if (!stat.valid)
                continue;
            std::snprintf(line, sizeof(line), "[FSRD_PROFILE] pass  %-22s (%s) median=%.3f p95=%.3f\n",
                          PassNames[pass], Names[PassStage(Pass(pass))], stat.median, stat.p95);
            out += line;
        }
        return out;
    }
};

struct FSRDRuntimeSnapshot
{
    enum Step { Inputs, Geometry, Conversion, RayRegeneration, AlbedoRecovery, Composition, SuperResolution, Output, StepCount };
    enum Status { NotRun, Running, Passed, Failed, Disabled };
    static constexpr const char* StepNames[] = { "Input validation", "Geometry", "Conversion", "Ray Regeneration",
        "Albedo Bleed Fix", "Composition", "FSR Super Resolution", "Output" };
    enum Input { Color, Depth, Motion, Normals, Roughness, DiffuseAlbedo, SpecularAlbedo,
                 SpecularDistance, DiffuseDistance, Bias, Emissive, LinearDepth, Responsivity,
                 AmbientOcclusion, Exposure, InputCount };
    static constexpr const char* InputNames[] = { "Color / radiance", "Depth", "Motion vectors", "Normals",
        "Roughness", "Diffuse albedo", "Specular albedo", "Specular hit distance", "Diffuse hit distance",
        "Current-color bias", "Emissive", "Title linear depth", "Responsivity", "Ambient occlusion", "Exposure" };
    static constexpr uint32_t Bit(Input input) { return 1u << input; }
    std::array<Status, StepCount> steps {};
    Step activeStep = Inputs;
    uint32_t received = 0, prepared = 0, submitted = 0;
    bool rayReconstruction = false, nativeAvailable = false, nativeActive = false, fallback = false;
    bool nativeRRPreferred = false, gameNativeRequested = false, rrValidated = false;
    bool rrDispatched = false, success = false;
    uint64_t frame = 0;
    FSRD::RRResult recoveryResult = FSRD::RRResult::Success;
    uint32_t retryFramesRemaining = 0;
    std::string failure;
    std::chrono::steady_clock::time_point updated {};
    uint32_t signalStatus = 0;
    FSRDStageTimings::Snapshot timings;
    void Begin(Step step) { activeStep = step; steps[step] = Running; }
    void Complete(Step step) { steps[step] = Passed; }
};
