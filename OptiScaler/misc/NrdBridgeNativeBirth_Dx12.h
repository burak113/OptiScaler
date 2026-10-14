#pragma once
#include "NrdBridgeBirth_Dx12.h"
#include "NrdBridgeLifetime_Dx12.h"
#include <d3d12.h>
#include <dxgi.h>
#include <bcrypt.h>
#include <array>
#include <atomic>
#include <cstdint>
#include <type_traits>
#pragma comment(lib, "bcrypt.lib")

namespace FrameSurvey { void MetadataHookFailed(const char*) noexcept; void FlushMetadataFailure() noexcept; bool OwnedRelease() noexcept; }

// Identity is native byte data, never a COM reference. The title caller must
// own a valid object while Prepare/Receiver invokes its private-data methods.
namespace NrdBridgeNativeBirth
{
// Production implementation delegates to the bounded native Release installer.
bool ObserveReleaseCoverage(IUnknown*) noexcept;
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
struct CacheEntry { void* address = nullptr; NrdBridgeBirth::Token birth; bool releaseCovered = false; };
inline thread_local std::array<CacheEntry,4> receiverCache;
inline thread_local unsigned nextReceiver = 0;
inline thread_local const char* pendingFailure = nullptr;
inline thread_local IUnknown* temporaryRelease = nullptr;
inline thread_local std::array<IUnknown*,8> recoveringAddresses {};
inline thread_local unsigned recoveryDepth = 0;
inline void FlushFailure() noexcept
{
    if (NrdBridgeBirth::InMetadataScope()) return;
    if (pendingFailure)
    {
        const char* reason = pendingFailure; pendingFailure = nullptr;
        FrameSurvey::MetadataHookFailed(reason);
    }
    FrameSurvey::FlushMetadataFailure();
}
inline void Fail(const char* reason) noexcept
{
    try { NrdBridgeBirth::ProcessRegistry().Fail(); } catch (...) {}
    if (!pendingFailure) pendingFailure = reason;
    FlushFailure();
}
// A queried interface owns one transient reference. Mark its exact Release
// solely to prevent a missing-ticket recovery loop; no lifetime gate is bypassed.
class InterfaceReference
{
    IUnknown* object_ = nullptr;
  public:
    InterfaceReference() noexcept = default;
    ~InterfaceReference()
    {
        if (!object_) return;
        if (NrdBridgeBirth::InMetadataScope())
        { Fail("strong native interface released under metadata lock"); return; } // Pin on invalid lexical lifetime.
        auto* previous = temporaryRelease; temporaryRelease = object_;
        object_->Release(); temporaryRelease = previous;
    }
    InterfaceReference(const InterfaceReference&) = delete;
    InterfaceReference& operator=(const InterfaceReference&) = delete;
    IUnknown* Get() const noexcept { return object_; }
    IUnknown** Put() noexcept { return &object_; }
};
inline bool StrongCanonical(IUnknown* object,InterfaceReference& canonical) noexcept
{
    if (!object || NrdBridgeBirth::InMetadataScope())
    { Fail("canonical native identity requested under metadata lock"); return false; }
    if (!ObserveReleaseCoverage(object))
    { Fail("typed native Release implementation is unsupported"); return false; }
    const auto result = object->QueryInterface(__uuidof(IUnknown),reinterpret_cast<void**>(canonical.Put()));
    if (FAILED(result) || !canonical.Get())
    { Fail("native object has no supported canonical IUnknown identity"); return false; }
    if (!ObserveReleaseCoverage(canonical.Get()))
    { Fail("canonical IUnknown Release implementation is unsupported"); return false; }
    return true;
}
// Forwarded native releases may have another This address. A repeated cold
// recovery of the same active address stops, while its full native Release still
// runs. Unrelated nested aliases may recover; this POD stack never allocates.
class RecoveryScope
{
    bool active_ = false;
  public:
    explicit RecoveryScope(IUnknown* object) noexcept
    {
        for (unsigned i=0;i<recoveryDepth;++i) if (recoveringAddresses[i] == object) return;
        if (recoveryDepth == recoveringAddresses.size())
        { Fail("native alias recovery exceeded bounded nesting"); return; }
        recoveringAddresses[recoveryDepth++] = object; active_ = true;
    }
    ~RecoveryScope() { if (active_) recoveringAddresses[--recoveryDepth] = nullptr; }
    bool Entered() const noexcept { return active_; }
    RecoveryScope(const RecoveryScope&) = delete;
    RecoveryScope& operator=(const RecoveryScope&) = delete;
};
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

inline bool Ready() noexcept { return Detail::configured.load(std::memory_order_acquire) == 2; }
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

namespace Detail
{
struct ReceiverVerification
{
    // Only COM Prepare calls this after both native Release coverage checks and
    // the reserved GUID Get/Set proof. No native call runs inside this guard.
    static void Mark(const NrdBridgeBirth::Token& token, void* address, uint64_t stamp) noexcept
    {
        if (!token || !address || !stamp || token->Address() != address || token->InstanceStamp() != stamp ||
            NrdBridgeBirth::InMetadataScope()) return;
        NrdBridgeBirth::CurrentGuard current(token);
        if (current.AdmitsBorrow()) token->nativeReceiverVerified_.store(true,std::memory_order_release);
        // A pending/in-flight/current-change race is a safe unverified result.
    }
};
}
// Link the exact typed address while keeping canonical initialization state.
// Existing strong creators may publish a pending token, but weak/native readers
// cannot borrow it until the canonical writer succeeds.
inline NrdBridgeBirth::Token TypedAlias(const NrdBridgeBirth::Token& canonical,void* address) noexcept
{
    if (!canonical || !address) return {};
    if (canonical->Address() == address) return canonical;
    auto& registry = NrdBridgeBirth::ProcessRegistry(); const auto actions = registry.Actions();
    auto typed = registry.ObserveInstance(address,canonical->InstanceStamp(),actions.detachOld,
        actions.publish,actions.state,true,canonical->Initializing());
    // If the writer's snapshot preceded this alias insertion, finish it here.
    if (!typed) { Detail::Fail("exact typed native alias publication failed"); return {}; }
    if (typed->Initializing() && canonical->Ready() && !canonical->Failed()) registry.Finalize(typed,true);
    return typed;
}
inline bool FinishPendingAliases(const NrdBridgeBirth::Token& canonical) noexcept
{
    if (!canonical || canonical->Initializing() || canonical->Failed()) return bool(canonical);
    NrdBridgeBirth::AliasSnapshot snapshot;
    if (!NrdBridgeBirth::CaptureProvenAliasesForFinalZero(canonical,snapshot) || !snapshot.complete)
    { Detail::Fail("native initializing alias snapshot failed"); return false; }
    // Snapshot releases its bounded physical index before any addressed guard.
    for (size_t i=0;i<snapshot.count;++i)
        if (snapshot.tokens[i]->Initializing()) NrdBridgeBirth::Finalize(snapshot.tokens[i],true);
    return NrdBridgeBirth::Healthy();
}
// Cold receiver/bootstrap. Capture the initializing state BEFORE the native
// getter. A stale zero read cannot elect a second writer after another writer
// finishes. Native getter/setter, factory and effect drain hold no Birth lock.
template <class NativeObject> NrdBridgeBirth::Token Prepare(NativeObject* object, bool enabled = true) noexcept
{
    if (!enabled || !object) return {};
    if constexpr (std::is_convertible_v<NativeObject*,IUnknown*>)
    {
        if (FrameSurvey::OwnedRelease()) return {};
        if (NrdBridgeLifetime::Detail::borrowDepth && !NrdBridgeLifetime::ConcurrentReleasesEnabled())
        { Detail::Fail("cold canonical native bootstrap must precede legacy Borrow"); return {}; }
    }
    if (NrdBridgeBirth::InMetadataScope())
    { Detail::Fail("native instance getter entered under metadata lock"); return {}; }
    FlushFailure();
    if (!NrdBridgeBirth::Healthy()) return {};
    RetirementScope retirement;
    if (!retirement.Valid()) return {};
    Detail::InterfaceReference canonical;
    void* electionAddress = object;
    if constexpr (std::is_convertible_v<NativeObject*,IUnknown*>)
    {
        if (!Detail::StrongCanonical(static_cast<IUnknown*>(object),canonical)) return {};
        electionAddress = canonical.Get();
    }
    const uint64_t nonce = Detail::ProcessNonce();
    if (!nonce) { Detail::Fail("native instance process nonce creation failed"); return {}; }
    try
    {
        for (unsigned attempt = 0; attempt != 8; ++attempt)
        {
            const auto old = NrdBridgeBirth::Capture(electionAddress);
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
                    const auto current = NrdBridgeBirth::ObserveInstance(electionAddress,native.instanceStamp);
                    if (!current || !FinishPendingAliases(current))
                    { Detail::Fail("native instance observation failed"); return {}; }
                    auto typed = TypedAlias(current,object);
                    if constexpr (std::is_convertible_v<NativeObject*,IUnknown*>)
                    {
                        Detail::ReceiverVerification::Mark(current,electionAddress,native.instanceStamp);
                        Detail::ReceiverVerification::Mark(typed,object,native.instanceStamp);
                    }
                    return typed;
                }
            }
            else if (result != DXGI_ERROR_NOT_FOUND)
            { Detail::Fail("native instance GUID read failed"); return {}; }
            if (wasInitializing)
            {
                if (NrdBridgeBirth::ObserveInitializing(old,wasInitializing)) return TypedAlias(old,object);
                if (!NrdBridgeBirth::Healthy()) return {};
                continue;
            }
            const auto stamp = NrdBridgeBirth::AllocateInstanceStamp();
            if (!stamp) { Detail::Fail("native instance stamp allocator exhausted"); return {}; }
            const auto elected = NrdBridgeBirth::ComparePublish(electionAddress,old,stamp);
            if (!elected)
            {
                if (!NrdBridgeBirth::Healthy()) return {};
                continue; // Lost exact-token election, including expected == nil.
            }
            native = {nonce,stamp};
            const auto written = object->SetPrivateData(InstanceGuid,sizeof(native),&native);
            const bool success = SUCCEEDED(written);
            if (NrdBridgeBirth::Finalize(elected,success))
            {
                if (!FinishPendingAliases(elected)) return {};
                auto typed = TypedAlias(elected,object);
                if constexpr (std::is_convertible_v<NativeObject*,IUnknown*>)
                {
                    Detail::ReceiverVerification::Mark(elected,electionAddress,native.instanceStamp);
                    Detail::ReceiverVerification::Mark(typed,object,native.instanceStamp);
                }
                return typed;
            }
            if (!success) { Detail::Fail("native instance GUID write failed"); return {}; }
            if (!NrdBridgeBirth::Healthy()) return {};
            // An exact metadata pre-retirement can race with an interned live
            // native object. Re-observe its already written physical stamp.
        }
    }
    catch (...) { Detail::Fail("native instance protocol raised an exception"); return {}; }
    Detail::Fail("native instance election exceeded bounded retries"); return {};
}

// Only a completed COM proof for this exact current address can bypass cold
// work on a TLS miss. Capture is forbidden beneath any metadata guard.
template <class NativeObject> NrdBridgeBirth::Token GloballyVerifiedReceiver(NativeObject* object) noexcept
{
    if constexpr (!std::is_convertible_v<NativeObject*,IUnknown*>) return {};
    else
    {
        if (!object || !Ready() || FrameSurvey::OwnedRelease() || NrdBridgeBirth::InMetadataScope()) return {};
        auto birth = NrdBridgeBirth::Capture(object);
        return birth && birth->Address() == object && birth->InstanceStamp() &&
            birth->NativeReceiverVerified() && NrdBridgeBirth::CacheAdmissible(birth) ? birth : NrdBridgeBirth::Token{};
    }
}
// Cover each physical receiver once before caching it. Plain metadata users
// can populate an uncovered cache entry without bypassing this native hook seam.
template <class NativeObject, class Coverage>
NrdBridgeBirth::Token ReceiverWithReleaseCoverage(NativeObject* object, Coverage coverage, bool enabled = true) noexcept
{
    if (!enabled || !object) return {};
    if constexpr (std::is_convertible_v<NativeObject*,IUnknown*>) if (FrameSurvey::OwnedRelease()) return {};
    FlushFailure();
    try
    {
        for (auto& entry : Detail::receiverCache)
        {
            if (entry.address != object || !NrdBridgeBirth::CacheAdmissible(entry.birth)) continue;
            if (entry.releaseCovered) return entry.birth;
            if (NrdBridgeBirth::InMetadataScope())
            { Detail::Fail("native release coverage entered under metadata lock"); return {}; }
            if (!coverage(object)) return {};
            if (!NrdBridgeBirth::CacheAdmissible(entry.birth)) break;
            entry.releaseCovered = true;
            return entry.birth;
        }
        if (auto verified = GloballyVerifiedReceiver(object); verified && NrdBridgeBirth::CacheAdmissible(verified))
        {
            Detail::receiverCache[Detail::nextReceiver++ % Detail::receiverCache.size()] = {object,verified,true};
            return verified;
        }
        if (NrdBridgeBirth::InMetadataScope())
        { Detail::Fail("native release coverage entered under metadata lock"); return {}; }
        if (!coverage(object)) return {};
        auto birth = Prepare(object);
        if (birth) Detail::receiverCache[Detail::nextReceiver++ % Detail::receiverCache.size()] = {object,birth,true};
        return birth;
    }
    catch (...) { Detail::Fail("native release coverage raised an exception"); return {}; }
}

// Only metadata nodes are cached. Every in-flight Release forces a native read
// so an allocation reused before an old post-zero callback cannot inherit it.
template <class NativeObject> NrdBridgeBirth::Token Receiver(NativeObject* object, bool enabled = true) noexcept
{
    if (!enabled || !object) return {};
    if constexpr (std::is_convertible_v<NativeObject*,IUnknown*>) if (FrameSurvey::OwnedRelease()) return {};
    FlushFailure();
    for (auto& entry : Detail::receiverCache)
        if (entry.address == object && NrdBridgeBirth::CacheAdmissible(entry.birth)) return entry.birth;
    if (auto verified = GloballyVerifiedReceiver(object); verified && NrdBridgeBirth::CacheAdmissible(verified))
    {
        Detail::receiverCache[Detail::nextReceiver++ % Detail::receiverCache.size()] = {object,verified,true};
        return verified;
    }
    auto birth = Prepare(object);
    if (birth) Detail::receiverCache[Detail::nextReceiver++ % Detail::receiverCache.size()] = {object,birth,std::is_convertible_v<NativeObject*,IUnknown*>};
    return birth;
}
struct ReleaseIdentity
{
    NrdBridgeBirth::Token ticket;
    void* recordingIdentity = nullptr; // Canonical ledger address, never a retained COM pointer.
};
inline ReleaseIdentity RecoverReleaseIdentity(IUnknown* object) noexcept
{
    ReleaseIdentity recovered;
    if (!object || Detail::temporaryRelease == object || !Ready() || FrameSurvey::OwnedRelease() ||
        NrdBridgeBirth::InMetadataScope() || !NrdBridgeBirth::Healthy()) return recovered;
    Detail::RecoveryScope recovery(object);
    if (!recovery.Entered()) return recovered;
    try
    {
        Detail::InterfaceReference typed,canonical;
        const auto queried = object->QueryInterface(__uuidof(ID3D12Object),reinterpret_cast<void**>(typed.Put()));
        if (FAILED(queried) || !typed.Get()) return recovered; // An unobserved non-D3D object has no birth to recover.
        auto* native = static_cast<ID3D12Object*>(typed.Get());
        NativeStamp stamp; UINT bytes = sizeof(stamp);
        const auto read = native->GetPrivateData(InstanceGuid,&bytes,&stamp);
        if (read == DXGI_ERROR_NOT_FOUND) return recovered;
        if (FAILED(read) || bytes != sizeof(stamp))
        { Detail::Fail("existing native instance GUID recovery failed"); return recovered; }
        if (!stamp.instanceStamp || stamp.processNonce != Detail::ProcessNonce()) return recovered;
        if (!Detail::StrongCanonical(native,canonical)) return recovered;
        auto known = NrdBridgeBirth::Capture(native);
        if (!known || known->InstanceStamp() != stamp.instanceStamp || !known->Live())
            known = NrdBridgeBirth::Capture(canonical.Get());
        if (!known || known->InstanceStamp() != stamp.instanceStamp || !known->Live() ||
            !NrdBridgeBirth::ObserveExisting(known)) return recovered;
        if (!ObserveReleaseCoverage(object))
        { Detail::Fail("recovered native alias Release implementation is unsupported"); return recovered; }
        RetirementScope effects;
        if (!effects.Valid()) return recovered;
        const auto canon = TypedAlias(known,canonical.Get());
        recovered.ticket = TypedAlias(known,object);
        if (!canon || !recovered.ticket)
        { Detail::Fail("existing native physical alias recovery failed"); recovered.ticket.reset(); return recovered; }
        recovered.recordingIdentity = canonical.Get();
        return recovered;
    }
    catch (...) { Detail::Fail("strong native alias recovery raised an exception"); return recovered; }
}

}
