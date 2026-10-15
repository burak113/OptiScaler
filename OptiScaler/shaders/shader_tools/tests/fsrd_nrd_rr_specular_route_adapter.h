#pragma once
// Research-only real-export adapter. RRWrapper and its public-facing assertions
// remain unchanged. The DS experiment deliberately routes indirect GGX radiance
// as direct specular to isolate the provider's route/virtual-hit model; it is
// not an assertion that these physical signals are direct illumination.
#include "nrd_bridge_rr_test_support.h"
#include <stdexcept>

namespace SpecularRouteResearch
{
inline bool direct = false;
inline PfnFfxCreateContext createExport = nullptr;
inline PfnFfxDispatch dispatchExport = nullptr;
inline unsigned checks = 0, creates = 0, dispatches = 0;
inline uint32_t actualSignals = 0;
inline uint64_t actualSpecularType = 0;
inline void Check(bool value, const char* message)
{ ++checks; if (!value) throw std::runtime_error(message); }

inline ffxReturnCode_t Create(ffxContext* context, ffxCreateContextDescHeader* header,
                             const ffxAllocationCallbacks* callbacks)
{
    Check(header && header->type == FFX_API_CREATE_CONTEXT_DESC_TYPE_DENOISER, "research adapter receives real denoiser create ABI");
    auto& create = *reinterpret_cast<ffxCreateContextDescDenoiser*>(header);
    Check(create.signalFlags == (FFX_DENOISER_SIGNAL_DIRECT_DIFFUSE | FFX_DENOISER_SIGNAL_INDIRECT_SPECULAR),
          "wrapper still produces the unchanged DD|IS context contract");
    // This is the wrapper-owned persistent create descriptor. Keep the selected
    // provider flag in it until deferred destruction, honoring descriptor life.
    if (direct) create.signalFlags = (create.signalFlags & ~FFX_DENOISER_SIGNAL_INDIRECT_SPECULAR) | FFX_DENOISER_SIGNAL_DIRECT_SPECULAR;
    actualSignals = create.signalFlags;
    Check(actualSignals == (direct ? 0x06u : 0x22u), "actual provider receives exactly DD|DS or DD|IS");
    ++creates;
    return createExport(context, header, callbacks);
}

inline ffxReturnCode_t Dispatch(ffxContext* context, const ffxDispatchDescHeader* header)
{
    Check(header && header->type == FFX_API_DISPATCH_DESC_TYPE_DENOISER, "research adapter receives real denoiser dispatch ABI");
    const auto& dispatch = *reinterpret_cast<const ffxDispatchDescDenoiser*>(header);
    const auto& diffuse = *reinterpret_cast<const ffxDispatchDescDenoiserDirectDiffuse*>(header->pNext);
    const auto& indirect = *reinterpret_cast<const ffxDispatchDescDenoiserIndirectSpecular*>(diffuse.header.pNext);
    Check(diffuse.header.type == FFX_API_DISPATCH_DESC_TYPE_DENOISER_DIRECT_DIFFUSE &&
          indirect.header.type == FFX_API_DISPATCH_DESC_TYPE_DENOISER_INDIRECT_SPECULAR && !indirect.header.pNext,
          "production wrapper still supplies ordered DD then IS without hidden debug");
    ++dispatches;
    if (!direct)
    {
        actualSpecularType = indirect.header.type;
        return dispatchExport(context, header);
    }
    static_assert(sizeof(ffxDispatchDescDenoiserDirectSpecular) == sizeof(ffxDispatchDescDenoiserIndirectSpecular));
    static_assert(offsetof(ffxDispatchDescDenoiserDirectSpecular, signal) == offsetof(ffxDispatchDescDenoiserIndirectSpecular, signal));
    ffxDispatchDescDenoiser forwarded = dispatch;
    ffxDispatchDescDenoiserDirectDiffuse diffuseCopy = diffuse;
    ffxDispatchDescDenoiserDirectSpecular specular{};
    specular.header.type = FFX_API_DISPATCH_DESC_TYPE_DENOISER_DIRECT_SPECULAR;
    specular.signal = indirect.signal;
    diffuseCopy.header.pNext = &specular.header;
    forwarded.header.pNext = &diffuseCopy.header;
    Check(std::memcmp(&specular.signal, &indirect.signal, sizeof(indirect.signal)) == 0,
          "DS adapter preserves all actual noisy RGB/A resource descriptors, rectangles and states");
    Check(specular.signal.input.state == FFX_API_RESOURCE_STATE_COMPUTE_READ &&
          specular.signal.output.state == FFX_API_RESOURCE_STATE_UNORDERED_ACCESS,
          "DS provider sees exact COMPUTE_READ input and owned UAV output");
    actualSpecularType = specular.header.type;
    return dispatchExport(context, &forwarded.header);
}

inline void Install()
{
    Check(FfxApiProxy::real && FfxApiProxy::createFunction && FfxApiProxy::dispatchFunction,
          "test-only route adapter requires actual signed exports");
    createExport = FfxApiProxy::createFunction;
    dispatchExport = FfxApiProxy::dispatchFunction;
    FfxApiProxy::createFunction = &Create;
    FfxApiProxy::dispatchFunction = &Dispatch;
}
}
