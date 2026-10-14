#pragma once
#include "NrdBridgeLifetime_Dx12.h"
#include "NrdBridgeNativeBirth_Dx12.h"
#include "RecordedComputeLease_Dx12.h"

// The native caller owns its reference throughout the temporary probe. No
// metadata lock is held across AddRef/Release, including nested native releases.
namespace NrdBridgeRelease
{
inline void RetireExact(const NrdBridgeBirth::Token& ticket) noexcept
{
    if (!ticket) return;
    NrdBridgeNativeBirth::RetirementScope retirement;
    if (!retirement.Valid()) return;
    NrdBridgeBirth::CurrentGuard current(ticket);
    current.Retire();
}
inline void RetirePhysical(const NrdBridgeBirth::Token& ticket) noexcept
{
    if (!ticket) return;
    NrdBridgeNativeBirth::RetirementScope retirement;
    if (!retirement.Valid()) return;
    // Match the native instance even when an interned object was re-observed
    // with a new logical sequence after the temporary final-reference probe.
    NrdBridgeBirth::RetireCurrentInstance(ticket);
}
template <class NativeObject, class Original>
ULONG Title(NativeObject* object, Original original) noexcept
{
    NrdBridgeLifetime::ScopedRelease physical(true);
    const auto ticket = NrdBridgeBirth::Capture(object);
    NrdBridgeBirth::ScopedRelease pending(ticket);
    auto recording = RecordedComputeLease::BeginRelease(object);
    object->AddRef();
    const ULONG probe = original(object);
    if (probe <= 1) RetireExact(ticket);
    const ULONG result = original(object);
    // Concurrent probes can both observe 2, then the second caller destroys the
    // object. This post-zero retirement is required even when the probe missed.
    if (!result) RetirePhysical(ticket);
    RecordedComputeLease::EndRelease(recording, result == 0);
    NrdBridgeNativeBirth::FlushFailure();
    return result;
}
}
