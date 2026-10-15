// Frozen production control from b6a7e180; generator renames this body only.
// Full ResTrack source SHA256: 1fb1dd55312eda1bfd0fc5355bbebd929214389811dfea15fce05fc26f1bb8b4
// Normalized hook SHA256: 7d47125b9b643b73bc1db8ac921663d84ded20da444e93561cbb1b0b9aa318eb
void ResTrack_Dx12::hkCopyDescriptorsSimple(ID3D12Device* This, UINT NumDescriptors,
                                            D3D12_CPU_DESCRIPTOR_HANDLE DestDescriptorRangeStart,
                                            D3D12_CPU_DESCRIPTOR_HANDLE SrcDescriptorRangeStart,
                                            D3D12_DESCRIPTOR_HEAP_TYPE DescriptorHeapsType)
{
    o_CopyDescriptorsSimple(This, NumDescriptors, DestDescriptorRangeStart, SrcDescriptorRangeStart,
                            DescriptorHeapsType);

    if (DescriptorHeapsType != D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV &&
        DescriptorHeapsType != D3D12_DESCRIPTOR_HEAP_TYPE_RTV)
        return;

    auto size = This->GetDescriptorHandleIncrementSize(DescriptorHeapsType);

    if (!Config::Instance()->FGAlwaysTrackHeaps.value_or_default() && !IsHudFixActive())
    {
        bool containsScalarCandidate = false;
        auto srcHeap = GetHeapByCpuHandle(SrcDescriptorRangeStart.ptr);
        auto dstHeap = GetHeapByCpuHandle(DestDescriptorRangeStart.ptr);
        for (UINT descriptor = 0; descriptor < NumDescriptors && !containsScalarCandidate; ++descriptor)
        {
            const SIZE_T srcHandle = SrcDescriptorRangeStart.ptr + static_cast<SIZE_T>(descriptor) * size;
            const SIZE_T dstHandle = DestDescriptorRangeStart.ptr + static_cast<SIZE_T>(descriptor) * size;
            ResourceInfo srcInfo {};
            ResourceInfo dstInfo {};
            const bool hasSrc = srcHeap != nullptr && srcHeap->GetByCpuHandle(srcHandle, srcInfo);
            const bool hasDst = dstHeap != nullptr && dstHeap->GetByCpuHandle(dstHandle, dstInfo);
            containsScalarCandidate =
                (hasSrc && srcInfo.buffer != nullptr && IsRRScalarCandidateFormat(srcInfo.format)) ||
                (hasDst && dstInfo.buffer != nullptr && IsRRScalarCandidateFormat(dstInfo.format));
        }

        if (!containsScalarCandidate)
            return;
    }

    for (size_t i = 0; i < NumDescriptors; i++)
    {
        std::shared_ptr<HeapInfo> srcHeap;
        SIZE_T srcHandle = 0;

        // source
        if (SrcDescriptorRangeStart.ptr != 0)
        {
            srcHandle = SrcDescriptorRangeStart.ptr + i * size;
            srcHeap = GetHeapByCpuHandle(srcHandle);
        }

        auto destHandle = DestDescriptorRangeStart.ptr + i * size;
        auto dstHeap = GetHeapByCpuHandle(destHandle);

        // destination
        if (dstHeap == nullptr)
            continue;

        if (srcHeap == nullptr)
        {
            dstHeap->ClearByCpuHandle(destHandle);
            continue;
        }

        ResourceInfo buffer {};
        if (!srcHeap->GetByCpuHandle(srcHandle, buffer))
        {
            dstHeap->ClearByCpuHandle(destHandle);
            continue;
        }

        dstHeap->SetByCpuHandle(destHandle, buffer);
    }
}

// BEGIN_FROZEN_PARTICIPANTS
// Original header SHA256: 6bd840c41bb087ef0056f97cc65e749942167936ed9f7268af3d6970ea115249
struct HeapInfo;

struct TrackedResourceSlot
{
    std::weak_ptr<HeapInfo> heap;
    uint64_t heapVersion = 0;
    UINT index = 0;
};

inline ankerl::unordered_dense::map<ID3D12Resource*, std::vector<TrackedResourceSlot>> _trackedResources;
struct HeapInfo : public std::enable_shared_from_this<HeapInfo>
{
    // Avoiding one lock object per descriptor
    static constexpr size_t DESCRIPTOR_LOCK_STRIPE_COUNT = 256;
    static_assert((DESCRIPTOR_LOCK_STRIPE_COUNT & (DESCRIPTOR_LOCK_STRIPE_COUNT - 1)) == 0);

    mutable std::array<std::shared_mutex, DESCRIPTOR_LOCK_STRIPE_COUNT> descriptorLocks;

    ID3D12DescriptorHeap* heap = nullptr;
    NrdBridgeBirth::Token birth;
    SIZE_T cpuStart = 0;
    SIZE_T cpuEnd = 0;
    SIZE_T gpuStart = 0;
    SIZE_T gpuEnd = 0;
    UINT numDescriptors = 0;
    UINT increment = 0;
    UINT type = 0;
    std::shared_ptr<ResourceInfo[]> info;
    // Mutations take descriptor stripe -> tracked resources -> occupied slots.
    std::mutex occupiedSlotsMutex;
    std::unordered_set<UINT> occupiedSlots;
    UINT lastOffset = 0;
    std::atomic<bool> active { true };
    std::atomic<uint64_t> version { 0 };

    HeapInfo(ID3D12DescriptorHeap* heap, SIZE_T cpuStart, SIZE_T cpuEnd, SIZE_T gpuStart, SIZE_T gpuEnd,
             UINT numResources, UINT increment, UINT type)
        : heap(heap), cpuStart(cpuStart), cpuEnd(cpuEnd), gpuStart(gpuStart), gpuEnd(gpuEnd),
          numDescriptors(numResources), increment(increment), type(type), info(new ResourceInfo[numResources])
    {
        static std::atomic<uint64_t> globalHeapVersion { 1 };
        version.store(globalHeapVersion.fetch_add(1, std::memory_order_relaxed), std::memory_order_relaxed);
        // ResourceInfo initializes every buffer to nullptr.
    }

    bool GetCpuIndex(SIZE_T cpuHandle, UINT& index) const
    {
        if (increment == 0 || cpuHandle < cpuStart || cpuHandle >= cpuEnd)
            return false;

        auto calculated = (cpuHandle - cpuStart) / increment;
        if (calculated >= numDescriptors)
            return false;

        index = static_cast<UINT>(calculated);
        return true;
    }

    bool GetGpuIndex(SIZE_T gpuHandle, UINT& index) const
    {
        if (increment == 0 || gpuHandle < gpuStart || gpuHandle >= gpuEnd)
            return false;

        auto calculated = (gpuHandle - gpuStart) / increment;
        if (calculated >= numDescriptors)
            return false;

        index = static_cast<UINT>(calculated);
        return true;
    }

    // Caller must hold the descriptor stripe exclusively.
    void DetachFromOldResourceLocked(UINT index)
    {
        auto* oldResource = info[index].buffer;
        if (oldResource == nullptr)
            return;

        std::scoped_lock lock(_trackedResourcesMutex);
        {
            std::scoped_lock occupiedLock(occupiedSlotsMutex);
            occupiedSlots.erase(index);
        }
        LOG_TRACK("Heap: {:X}, Index: {}, Resource: {:X}, Res: {}x{}, Format: {}", (size_t) this, index,
                  (size_t) oldResource, info[index].width, info[index].height, (UINT) info[index].format);

        auto it = _trackedResources.find(oldResource);
        if (it == _trackedResources.end())
            return;

        const auto currentVersion = version.load(std::memory_order_relaxed);
        auto& vec = it->second;
        vec.erase(std::remove_if(vec.begin(), vec.end(), [currentVersion, index](const TrackedResourceSlot& slot)
                                 { return slot.heapVersion == currentVersion && slot.index == index; }),
                  vec.end());
        if (vec.empty())
            _trackedResources.erase(it);
    }

    void AttachToNewResourceLocked(UINT index)
    {
        auto* newResource = info[index].buffer;
        if (newResource == nullptr)
            return;

        std::scoped_lock lock(_trackedResourcesMutex);
        LOG_TRACK("Heap: {:X}, Index: {}, Resource: {:X}, Res: {}x{}, Format: {}", (size_t) this, index,
                  (size_t) newResource, info[index].width, info[index].height, (UINT) info[index].format);

        try
        {
            const auto currentVersion = version.load(std::memory_order_relaxed);
            auto& vec = _trackedResources[newResource];
            {
                std::scoped_lock occupiedLock(occupiedSlotsMutex);
                occupiedSlots.insert(index);
            }
            auto found = std::find_if(vec.begin(), vec.end(), [currentVersion, index](const TrackedResourceSlot& slot)
                                     { return slot.heapVersion == currentVersion && slot.index == index; });
            if (found == vec.end())
                vec.push_back({ shared_from_this(), currentVersion, index });
        }
        catch (...)
        {
            // Never publish a raw resource without both reverse indexes.
            {
                std::scoped_lock occupiedLock(occupiedSlotsMutex);
                occupiedSlots.erase(index);
            }
            if (auto found = _trackedResources.find(newResource); found != _trackedResources.end() && found->second.empty())
                _trackedResources.erase(found);
            info[index].buffer = nullptr;
            info[index].lastUsedFrame = 0;
            FrameSurvey::MetadataHookFailed("Descriptor participant index allocation failed");
        }
    }

    bool GetByCpuHandle(SIZE_T cpuHandle, ResourceInfo& outInfo) const
    {
        if (!active.load(std::memory_order_acquire))
            return false;

        UINT index = 0;
        if (!GetCpuIndex(cpuHandle, index))
            return false;

        std::shared_lock lock(GetDescriptorLock(index));
        if (!active.load(std::memory_order_acquire) || info[index].buffer == nullptr ||
            (NrdBridgeNativeBirth::Ready() && !NrdBridgeBirth::CacheAdmissible(info[index].birth)))
            return false;

        outInfo = info[index];

#ifdef DEBUG_TRACKING
        TestResource(&outInfo);
#endif

        return true;
    }

    bool GetByGpuHandle(SIZE_T gpuHandle, ResourceInfo& outInfo) const
    {
        if (!active.load(std::memory_order_acquire))
            return false;

        UINT index = 0;
        if (!GetGpuIndex(gpuHandle, index))
            return false;

        std::shared_lock lock(GetDescriptorLock(index));
        if (!active.load(std::memory_order_acquire) || info[index].buffer == nullptr ||
            (NrdBridgeNativeBirth::Ready() && !NrdBridgeBirth::CacheAdmissible(info[index].birth)))
            return false;

        outInfo = info[index];

#ifdef DEBUG_TRACKING
        TestResource(&outInfo);
#endif

        return true;
    }

    void SetByCpuHandle(SIZE_T cpuHandle, const ResourceInfo& setInfo)
    {
        const bool born = NrdBridgeNativeBirth::Ready();
        NrdBridgeBirth::CurrentGuard current(setInfo.birth,born && setInfo.buffer);
        if (born && setInfo.buffer && !current.MatchesCurrent()) return;
        if (!active.load(std::memory_order_acquire))
            return;

        UINT index = 0;
        if (!GetCpuIndex(cpuHandle, index))
            return;

        std::unique_lock lock(GetDescriptorLock(index));
        if (!active.load(std::memory_order_acquire))
            return;

#ifdef DEBUG_TRACKING
        TestResource(&setInfo);
#endif

        if (info[index].buffer != setInfo.buffer || info[index].birth != setInfo.birth)
        {
            DetachFromOldResourceLocked(index);
            info[index] = setInfo;
            AttachToNewResourceLocked(index);
        }
        else
        {
            info[index] = setInfo;
        }
    }

    void SetByGpuHandle(SIZE_T gpuHandle, const ResourceInfo& setInfo)
    {
        const bool born = NrdBridgeNativeBirth::Ready();
        NrdBridgeBirth::CurrentGuard current(setInfo.birth,born && setInfo.buffer);
        if (born && setInfo.buffer && !current.MatchesCurrent()) return;
        if (!active.load(std::memory_order_acquire))
            return;

        UINT index = 0;
        if (!GetGpuIndex(gpuHandle, index))
            return;

        std::unique_lock lock(GetDescriptorLock(index));
        if (!active.load(std::memory_order_acquire))
            return;

#ifdef DEBUG_TRACKING
        TestResource(&setInfo);
#endif

        if (info[index].buffer != setInfo.buffer || info[index].birth != setInfo.birth)
        {
            DetachFromOldResourceLocked(index);
            info[index] = setInfo;
            AttachToNewResourceLocked(index);
        }
        else
        {
            info[index] = setInfo;
        }
    }

    void ClearByCpuHandle(SIZE_T cpuHandle)
    {
        if (!active.load(std::memory_order_acquire))
            return;

        UINT index = 0;
        if (!GetCpuIndex(cpuHandle, index))
            return;

        std::unique_lock lock(GetDescriptorLock(index));
        if (!active.load(std::memory_order_acquire))
            return;

        ClearSlotLocked(index, true);
    }

    void ClearByGpuHandle(SIZE_T gpuHandle)
    {
        if (!active.load(std::memory_order_acquire))
            return;

        UINT index = 0;
        if (!GetGpuIndex(gpuHandle, index))
            return;

        std::unique_lock lock(GetDescriptorLock(index));
        if (!active.load(std::memory_order_acquire))
            return;

        ClearSlotLocked(index, true);
    }

    void ClearSlotIfMatches(UINT index, ID3D12Resource* resource, const NrdBridgeBirth::Token& retired = {})
    {
        if (!active.load(std::memory_order_acquire) || index >= numDescriptors)
            return;

        std::unique_lock lock(GetDescriptorLock(index));
        if (!active.load(std::memory_order_acquire) || info[index].buffer != resource ||
            (retired && info[index].birth != retired))
            return;

        info[index].buffer = nullptr;
        info[index].birth.reset();
        info[index].lastUsedFrame = 0;
        {
            std::scoped_lock occupiedLock(occupiedSlotsMutex);
            occupiedSlots.erase(index);
        }
    }

    bool DeactivateAndClear()
    {
        if (!active.exchange(false, std::memory_order_acq_rel))
            return false;

        std::array<std::unique_lock<std::shared_mutex>, DESCRIPTOR_LOCK_STRIPE_COUNT> locks;
        const auto stripeCount = std::min<size_t>(numDescriptors, DESCRIPTOR_LOCK_STRIPE_COUNT);
        for (size_t i = 0; i < stripeCount; ++i)
            locks[i] = std::unique_lock<std::shared_mutex>(descriptorLocks[i]);

        decltype(info) retired;
        {
            std::scoped_lock trackedLock(_trackedResourcesMutex);
            std::scoped_lock occupiedLock(occupiedSlotsMutex);
            for (const UINT index : occupiedSlots)
            {
                auto* resource = info[index].buffer;
                if (auto it = _trackedResources.find(resource); it != _trackedResources.end())
                {
                    const auto currentVersion = version.load(std::memory_order_relaxed);
                    auto& vec = it->second;
                    vec.erase(std::remove_if(vec.begin(), vec.end(),
                                             [currentVersion, index](const TrackedResourceSlot& slot)
                                             { return slot.heapVersion == currentVersion && slot.index == index; }),
                              vec.end());
                    if (vec.empty())
                        _trackedResources.erase(it);
                }
                info[index].buffer = nullptr;
                info[index].lastUsedFrame = 0;
            }
            occupiedSlots.clear();
            retired = std::move(info);
        }
        // Bulk descriptor storage destruction is outside the resource/index lock.
        return true;
    }

  private:
    std::shared_mutex& GetDescriptorLock(UINT index) const
    {
        return descriptorLocks[index & (DESCRIPTOR_LOCK_STRIPE_COUNT - 1)];
    }

    void ClearSlotLocked(UINT index, bool detach)
    {
        if (info[index].buffer != nullptr)
        {
            LOG_TRACK("Resource: {:X}, Res: {}x{}, Format: {}", (size_t) info[index].buffer, info[index].width,
                      info[index].height, (UINT) info[index].format);

            if (detach)
                DetachFromOldResourceLocked(index);
        }

        info[index].buffer = nullptr;
        info[index].lastUsedFrame = 0;
        {
            std::scoped_lock occupiedLock(occupiedSlotsMutex);
            occupiedSlots.erase(index);
        }
    }
};
// END_FROZEN_PARTICIPANTS
