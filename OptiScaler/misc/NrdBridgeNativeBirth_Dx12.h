#pragma once
#include "NrdBridgeBirth_Dx12.h"
#include <d3d12.h>
#include <dxgi.h>
#include <bcrypt.h>
#include <array>
#include <atomic>
#include <cstdint>
#pragma comment(lib, "bcrypt.lib")

namespace FrameSurvey { void MetadataHookFailed(const char*) noexcept; }

// Identity is native byte data, never a COM reference. The title caller must
// own a valid object while Prepare/Receiver invokes its private-data methods.
namespace NrdBridgeNativeBirth
{
using Factory = void* (*)() noexcept;
using Notify = void (*)(void*) noexcept; // Drains effects and destroys the payload.
inline constexpr GUID InstanceGuid = {0x72304b13,0x1a2e,0x46be,{0xae,0xdc,0x22,0x50,0x50,0x4d,0xc9,0x64}};
struct NativeStamp { uint64_t processNonce = 0, instanceStamp = 0; };
static_assert(sizeof(NativeStamp) == 16);

namespace Detail
{
struct Callbacks { Factory factory = nullptr; NrdBridgeBirth::MetadataAction detach = nullptr; Notify notify = nullptr; };
inline Callbacks callbacks;
inline std::atomic<unsigned> configured {0}; // 0 unset, 1 configuring, 2 ready, 3 failed.
inline thread_local void* retirementPayload = nullptr;
struct CacheEntry { void* address = nullptr; NrdBridgeBirth::Token birth; };
inline thread_local std::array<CacheEntry,4> receiverCache;
inline thread_local unsigned nextReceiver = 0;
inline thread_local const char* pendingFailure = nullptr;
inline void FlushFailure() noexcept
{
    if (NrdBridgeBirth::InMetadataScope() || !pendingFailure) return;
    const char* reason = pendingFailure; pendingFailure = nullptr;
    FrameSurvey::MetadataHookFailed(reason);
}
inline void Fail(const char* reason) noexcept
{
    try { NrdBridgeBirth::ProcessRegistry().Fail(); } catch (...) {}
    if (!pendingFailure) pendingFailure = reason;
    FlushFailure();
}
inline bool Detach(void*, const NrdBridgeBirth::Token& old) noexcept
{
    if (!retirementPayload || configured.load(std::memory_order_acquire) != 2 || !callbacks.detach)
    { Fail("native birth retirement has no caller-owned payload"); return false; }
    const bool detached = callbacks.detach(retirementPayload, old);
    if (!detached) Fail("native birth retirement metadata detach failed");
    return detached;
}
inline bool PublishIdentity(void*, const NrdBridgeBirth::Token&) noexcept { return true; }
inline uint64_t ProcessNonce() noexcept
{
    // One cold RNG call. No timestamp, pointer, TTL or shader hash identifies a
    // native instance; a new DLL session also cannot reuse the previous stamps.
    static const uint64_t nonce = []() noexcept {
        uint64_t value = 0;
        return BCryptGenRandom(nullptr,reinterpret_cast<PUCHAR>(&value),sizeof(value),
                               BCRYPT_USE_SYSTEM_PREFERRED_RNG) >= 0 ? value : uint64_t(0);
    }();
    return nonce;
}
}

inline void FlushFailure() noexcept { Detail::FlushFailure(); }

inline bool ConfigureRetirement(Factory factory, NrdBridgeBirth::MetadataAction detach, Notify notify) noexcept
{
    if (!factory || !detach || !notify || NrdBridgeBirth::InMetadataScope())
    { Detail::Fail("invalid native birth retirement dispatcher"); return false; }
    unsigned expected = 0;
    if (!Detail::configured.compare_exchange_strong(expected,1,std::memory_order_acq_rel))
        return expected == 2 && Detail::callbacks.factory == factory &&
            Detail::callbacks.detach == detach && Detail::callbacks.notify == notify;
    Detail::callbacks = {factory,detach,notify};
    if (!NrdBridgeBirth::ConfigureActions({Detail::Detach,Detail::PublishIdentity,nullptr}))
    {
        Detail::configured.store(3,std::memory_order_release);
        Detail::Fail("native birth registry dispatcher registration failed"); return false;
    }
    Detail::configured.store(2,std::memory_order_release);
    return true;
}

class RetirementScope
{
    void* payload_ = nullptr;
    void* previous_ = nullptr;
  public:
    explicit RetirementScope(bool enabled = true) noexcept
    {
        if (!enabled) return;
        if (NrdBridgeBirth::InMetadataScope() || Detail::configured.load(std::memory_order_acquire) != 2)
        { Detail::Fail("native birth retirement scope must begin outside metadata locks"); return; }
        payload_ = Detail::callbacks.factory(); // Allocation and empty owner construction outside Birth locks.
        if (!payload_) { Detail::Fail("native birth retirement payload allocation failed"); return; }
        previous_ = Detail::retirementPayload;
        Detail::retirementPayload = payload_;
    }
    ~RetirementScope()
    {
        if (!payload_) return;
        Detail::retirementPayload = previous_;
        // A wrong lexical lifetime fails closed and pins detached effects rather
        // than invoking callbacks or COM destruction while a Birth lock is held.
        if (NrdBridgeBirth::InMetadataScope())
        { Detail::Fail("native birth retirement drained under a metadata lock"); return; }
        Detail::callbacks.notify(payload_);
        FlushFailure();
    }
    RetirementScope(const RetirementScope&) = delete;
    RetirementScope& operator=(const RetirementScope&) = delete;
    bool Valid() const noexcept { return payload_ != nullptr; }
};

// Cold receiver/bootstrap. Capture the initializing state BEFORE the native
// getter. A stale zero read cannot elect a second writer after another writer
// finishes. Native getter/setter, factory and effect drain hold no Birth lock.
template <class NativeObject> NrdBridgeBirth::Token Prepare(NativeObject* object, bool enabled = true) noexcept
{
    if (!enabled || !object) return {};
    if (NrdBridgeBirth::InMetadataScope())
    { Detail::Fail("native instance getter entered under metadata lock"); return {}; }
    FlushFailure();
    if (!NrdBridgeBirth::Healthy()) return {};
    RetirementScope retirement;
    if (!retirement.Valid()) return {};
    const uint64_t nonce = Detail::ProcessNonce();
    if (!nonce) { Detail::Fail("native instance process nonce creation failed"); return {}; }
    try
    {
        for (unsigned attempt = 0; attempt != 8; ++attempt)
        {
            const auto old = NrdBridgeBirth::Capture(object);
            const bool wasInitializing = old && old->Initializing();
            NativeStamp native;
            UINT bytes = sizeof(native);
            const auto result = object->GetPrivateData(InstanceGuid,&bytes,&native);
            if (SUCCEEDED(result))
            {
                if (bytes != sizeof(native))
                { Detail::Fail("native instance GUID payload has an invalid size"); return {}; }
                if (native.processNonce == nonce && native.instanceStamp)
                {
                    const auto current = NrdBridgeBirth::ObserveInstance(object,native.instanceStamp);
                    if (!current) Detail::Fail("native instance observation failed");
                    return current;
                }
            }
            else if (result != DXGI_ERROR_NOT_FOUND)
            { Detail::Fail("native instance GUID read failed"); return {}; }
            if (wasInitializing)
            {
                if (NrdBridgeBirth::ObserveInitializing(old,wasInitializing)) return old;
                if (!NrdBridgeBirth::Healthy()) return {};
                continue;
            }
            const auto stamp = NrdBridgeBirth::AllocateInstanceStamp();
            if (!stamp) { Detail::Fail("native instance stamp allocator exhausted"); return {}; }
            const auto elected = NrdBridgeBirth::ComparePublish(object,old,stamp);
            if (!elected)
            {
                if (!NrdBridgeBirth::Healthy()) return {};
                continue; // Lost exact-token election, including expected == nil.
            }
            native = {nonce,stamp};
            const auto written = object->SetPrivateData(InstanceGuid,sizeof(native),&native);
            const bool success = SUCCEEDED(written);
            if (NrdBridgeBirth::Finalize(elected,success)) return elected;
            if (!success) { Detail::Fail("native instance GUID write failed"); return {}; }
            if (!NrdBridgeBirth::Healthy()) return {};
            // An exact metadata pre-retirement can race with an interned live
            // native object. Re-observe its already written physical stamp.
        }
    }
    catch (...) { Detail::Fail("native instance protocol raised an exception"); return {}; }
    Detail::Fail("native instance election exceeded bounded retries"); return {};
}

// Only metadata nodes are cached. Every in-flight Release forces a native read
// so an allocation reused before an old post-zero callback cannot inherit it.
template <class NativeObject> NrdBridgeBirth::Token Receiver(NativeObject* object, bool enabled = true) noexcept
{
    if (!enabled || !object) return {};
    for (auto& entry : Detail::receiverCache)
        if (entry.address == object && NrdBridgeBirth::CacheAdmissible(entry.birth)) return entry.birth;
    auto birth = Prepare(object);
    if (birth) Detail::receiverCache[Detail::nextReceiver++ % Detail::receiverCache.size()] = {object,birth};
    return birth;
}
}
