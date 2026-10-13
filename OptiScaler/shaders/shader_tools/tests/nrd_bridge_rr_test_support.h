#pragma once
// Production RRWrapper is compiled unchanged below this seam. Only the application's
// proxy/hook adapters are replaced; real mode forwards directly to signed AMD exports.
#define NOMINMAX
#include <windows.h>
#include <d3d12.h>
#include <dxgi1_6.h>
#include <wrl/client.h>
#include <ffx_api.h>
#include <dx12/ffx_api_dx12.h>
#include <fsr-rr/ffx_denoiser.h>
#include <sl_consts.h>
#include <array>
#include <cstring>
#include <cstdio>
#include <functional>
#include <memory>
#include <string>
#include <unordered_map>
#include "../../../misc/RecordedComputeLease_Dx12.h"

#define LOG_ERROR(...) ((void)0)
#define LOG_INFO(...) ((void)0)
struct ScopedSkipSpoofingGlobal {};
struct ScopedSkipHeapCapture {};
struct SLConstantsSnapshot
{
    sl::Constants constants {};
    uint32_t frameIndex = UINT32_MAX, viewport = UINT32_MAX;
};
struct FfxApiProxy
{
    static inline bool real = false, initAvailable = true, rejectDispatch = false;
    static inline uint64_t providerCount = 1;
    static inline const char* providerName = "AMD FSR Denoiser v1.2.0";
    static inline unsigned creates = 0, destroys = 0, dispatches = 0, defaults = 0, configures = 0;
    static inline unsigned badDefaults = 0;
    static inline unsigned badCreateChains = 0;
    static inline ffxCreateContextDescDenoiser lastCreate {};
    static inline ffxDispatchDescDenoiser lastDispatch {};
    static inline ffxDispatchDescDenoiserDirectDiffuse lastDiffuse {};
    static inline ffxDispatchDescDenoiserIndirectSpecular lastSpecular {};
    static inline uint64_t lastOverride = 0;
    static inline std::unordered_map<ffxContext, uint32_t> live;
    static inline std::unordered_map<ffxContext, const ffxCreateContextDescDenoiser*> createChains;
    static inline std::unordered_map<ffxContext, std::array<float, 8>> queried;
    static inline PfnFfxCreateContext createFunction = nullptr;
    static inline PfnFfxDestroyContext destroyFunction = nullptr;
    static inline PfnFfxConfigure configureFunction = nullptr;
    static inline PfnFfxQuery queryFunction = nullptr;
    static inline PfnFfxDispatch dispatchFunction = nullptr;
    static bool InitFfxDx12_Denoiser() { return initAvailable; }
    static ffxReturnCode_t D3D12_CreateContext(ffxContext* context, ffxCreateContextDescHeader* header,
                                             const ffxAllocationCallbacks* callbacks)
    {
        lastCreate = *reinterpret_cast<ffxCreateContextDescDenoiser*>(header);
        auto* backend = reinterpret_cast<ffxCreateBackendDX12Desc*>(header->pNext);
        lastOverride = reinterpret_cast<ffxOverrideVersion*>(backend->header.pNext)->versionId;
        if (real) std::fprintf(stderr,"real create begin %ux%u provider=%llu\n",lastCreate.maxRenderSize.width,
            lastCreate.maxRenderSize.height,static_cast<unsigned long long>(lastOverride));
        const auto result = real ? createFunction(context, header, callbacks) : FFX_API_RETURN_OK;
        if (real) std::fprintf(stderr,"real create end code=%u\n",unsigned(result));
        if (result == FFX_API_RETURN_OK)
        {
            ++creates;
            if (!real) *context = reinterpret_cast<ffxContext>(uintptr_t(creates));
            live[*context] = lastCreate.maxRenderSize.width;
            createChains[*context] = reinterpret_cast<const ffxCreateContextDescDenoiser*>(header);
        }
        return result;
    }
    static ffxReturnCode_t D3D12_DestroyContext(ffxContext* context, const ffxAllocationCallbacks* callbacks)
    {
        const auto key = *context;
        const auto* create = createChains.at(key);
        const auto* backend = reinterpret_cast<const ffxCreateBackendDX12Desc*>(create->header.pNext);
        const auto* version = reinterpret_cast<const ffxOverrideVersion*>(backend->header.pNext);
        if (create->header.type != FFX_API_CREATE_CONTEXT_DESC_TYPE_DENOISER || create->version != FFX_DENOISER_VERSION ||
            create->maxRenderSize.width != live.at(key) || backend->header.type != FFX_API_CREATE_CONTEXT_DESC_TYPE_BACKEND_DX12 ||
            !backend->device || version->header.type != FFX_API_DESC_TYPE_OVERRIDE_VERSION) ++badCreateChains;
        if (real) std::fprintf(stderr,"real destroy begin\n");
        const auto result = real ? destroyFunction(context, callbacks) : FFX_API_RETURN_OK;
        if (real) std::fprintf(stderr,"real destroy end code=%u\n",unsigned(result));
        if (result == FFX_API_RETURN_OK)
        {
            ++destroys;
            live.erase(key);
            createChains.erase(key);
            queried.erase(key);
            *context = nullptr;
        }
        return result;
    }
    static ffxReturnCode_t D3D12_Query(ffxContext* context, ffxQueryDescHeader* header)
    {
        ffxReturnCode_t result = FFX_API_RETURN_OK;
        if (real) result = queryFunction(context, header);
        else if (header->type == FFX_API_QUERY_DESC_TYPE_GET_VERSIONS)
        {
            auto& query = *reinterpret_cast<ffxQueryDescGetVersions*>(header);
            *query.outputCount = providerCount;
            if (providerCount == 1 && query.versionIds)
            {
                query.versionIds[0] = 0x120;
                query.versionNames[0] = providerName;
            }
        }
        else if (header->type == FFX_API_QUERY_DESC_TYPE_DENOISER_GET_DEFAULT_KEYVALUE)
        {
            auto& query = *reinterpret_cast<ffxQueryDescDenoiserGetDefaultKeyValue*>(header);
            auto* values = static_cast<float*>(query.data);
            values[0] = float(query.key) / 10.0f;
            if (query.key == 7) values[1] = 65504.0f;
        }
        if (result == FFX_API_RETURN_OK && header->type == FFX_API_QUERY_DESC_TYPE_DENOISER_GET_DEFAULT_KEYVALUE)
        {
            const auto& query = *reinterpret_cast<ffxQueryDescDenoiserGetDefaultKeyValue*>(header);
            ++defaults;
            const auto* values = static_cast<const float*>(query.data);
            queried[*context][query.key - 1] = values[0];
            if (query.key == 7) queried[*context][7] = values[1];
        }
        return result;
    }
    static ffxReturnCode_t D3D12_Configure(ffxContext* context, const ffxConfigureDescHeader* header)
    {
        const auto& apply = *reinterpret_cast<const ffxConfigureDescDenoiserKeyValue*>(header);
        const auto* values = static_cast<const float*>(apply.data);
        if (values[0] != queried[*context][apply.key - 1] ||
            (apply.key == 7 && values[1] != queried[*context][7])) ++badDefaults;
        const auto result = real ? configureFunction(context, header) : FFX_API_RETURN_OK;
        if (result == FFX_API_RETURN_OK) ++configures;
        return result;
    }
    static ffxReturnCode_t D3D12_Dispatch(ffxContext* context, const ffxDispatchDescHeader* header)
    {
        lastDispatch = *reinterpret_cast<const ffxDispatchDescDenoiser*>(header);
        lastDiffuse = *reinterpret_cast<const ffxDispatchDescDenoiserDirectDiffuse*>(header->pNext);
        lastSpecular = *reinterpret_cast<const ffxDispatchDescDenoiserIndirectSpecular*>(lastDiffuse.header.pNext);
        ++dispatches;
        if (rejectDispatch) return FFX_API_RETURN_ERROR_RUNTIME_ERROR;
        if (real && dispatches < 4) std::fprintf(stderr,"real dispatch begin attempt=%u\n",dispatches);
        const auto result = real ? dispatchFunction(context, header) : FFX_API_RETURN_OK;
        if (real && dispatches < 4) std::fprintf(stderr,"real dispatch end code=%u\n",unsigned(result));
        return result;
    }
};
struct ResTrack_Dx12
{
    static bool RetainComputeDispatch(ID3D12Device* device, ID3D12GraphicsCommandList* list,
                                     const std::shared_ptr<void>& lease)
    {
        if (!device || !list || !lease || !RecordedComputeLease::Available()) return false;
        Microsoft::WRL::ComPtr<ID3D12Device> listDevice;
        Microsoft::WRL::ComPtr<IUnknown> first, second, identity;
        if (FAILED(list->GetDevice(IID_PPV_ARGS(&listDevice))) ||
            FAILED(device->QueryInterface(IID_PPV_ARGS(&first))) || FAILED(listDevice.As(&second)) ||
            first.Get() != second.Get() || FAILED(list->QueryInterface(IID_PPV_ARGS(&identity)))) return false;
        return RecordedComputeLease::Track(identity.Get(), {list, identity.Get()}, lease);
    }
};
