#pragma once
#include <d3d12.h>
#include <wrl/client.h>
#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <functional>
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
        Floor,
        Conversion,
        RayRegeneration,
        AlbedoRecovery,
        Composition,
        SuperResolution,
        Count
    };
    static constexpr const char* Names[] { "Floor",           "Conversion",  "AMD RR / ML",
                                           "Albedo Bleed Fix", "Composition", "Super Resolution" };
    struct Snapshot
    {
        std::array<double, Count> milliseconds {};
        unsigned validMask = 0;
        uint64_t sequence = 0;
        std::chrono::steady_clock::time_point completed {};
        bool available = true;
    };

  private:
    struct Shared
    {
        std::mutex mutex;
        Snapshot snapshot;
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
                D3D12_RANGE range { 0, Count * 2 * sizeof(uint64_t) };
                void* mapped = nullptr;
                if (SUCCEEDED(readback->Map(0, &range, &mapped)))
                {
                    const auto* values = static_cast<const uint64_t*>(mapped);
                    Snapshot sample;
                    sample.sequence = sequence;
                    sample.completed = std::chrono::steady_clock::now();
                    for (unsigned i = 0; i < Count; ++i)
                    {
                        if (!(ended & (1u << i)) || values[2 * i + 1] < values[2 * i])
                            continue;
                        const double ms = double(values[2 * i + 1] - values[2 * i]) * 1000.0 / double(frequency.load());
                        if (std::isfinite(ms))
                        {
                            sample.milliseconds[i] = ms;
                            sample.validMask |= 1u << i;
                        }
                    }
                    D3D12_RANGE written { 0, 0 };
                    readback->Unmap(0, &written);
                    std::lock_guard lock(owner->mutex);
                    if (sample.sequence > owner->snapshot.sequence && owner->generation.load() == generation)
                        owner->snapshot = sample;
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

  public:
    // retain(lease, beforeSubmit) returns false when reliable submission tracking is
    // unavailable. beforeSubmit supplies the actual executing queue's timestamp clock.
    template <class Retain>
    void BeginFrame(ID3D12Device* device, ID3D12GraphicsCommandList* list, bool enabled, Retain retain)
    {
        FinishFrame(false);
        if (enabled != m_enabled)
        {
            m_enabled = enabled;
            ++m_shared->generation;
            std::lock_guard lock(m_shared->mutex);
            m_shared->snapshot = {};
        }
        const uint64_t sequence = ++m_sequence;
        if (!enabled || !device || !list || (sequence - 1) % 16 || m_shared->pending.load() >= 4)
            return;
        auto packet = std::make_shared<Packet>(m_shared);
        packet->device = device;
        packet->sequence = sequence;
        packet->generation = m_shared->generation.load();
        D3D12_QUERY_HEAP_DESC queryDesc { D3D12_QUERY_HEAP_TYPE_TIMESTAMP, Count * 2, 0 };
        D3D12_HEAP_PROPERTIES heap {};
        heap.Type = D3D12_HEAP_TYPE_READBACK;
        D3D12_RESOURCE_DESC desc {};
        desc.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
        desc.Width = Count * 2 * sizeof(uint64_t);
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
};

struct FSRDRuntimeSnapshot
{
    enum Step { Inputs, Floor, Conversion, RayRegeneration, AlbedoRecovery, Composition, SuperResolution, Output, StepCount };
    enum Status { NotRun, Running, Passed, Failed, Disabled };
    static constexpr const char* StepNames[] = { "Input validation", "Floor", "Conversion", "Ray Regeneration",
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
    std::string failure;
    std::chrono::steady_clock::time_point updated {};
    uint32_t signalStatus = 0;
    FSRDStageTimings::Snapshot timings;
    void Begin(Step step) { activeStep = step; steps[step] = Running; }
    void Complete(Step step) { steps[step] = Passed; }
};
