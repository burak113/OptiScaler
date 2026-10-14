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
void RecordTestProviderWrites(ID3D12GraphicsCommandList*, ID3D12Resource* spec, ID3D12Resource* diff);
void RecordTestProviderDebugWrites(ID3D12GraphicsCommandList*, ID3D12Resource*, uint32_t width, uint32_t height);
struct FfxApiProxy
{
    static inline bool real = false, initAvailable = true, rejectDispatch = false;
    static inline bool recordPartialWrites = false;
    static inline uint64_t rejectConfigureKey = 0;
    static inline std::array<float,4> mockSpec {2.5f,3.75f,4.25f,5.5f}, mockDiff {6.5f,7.75f,8.25f,9.5f};
    static inline std::array<float,4> mockDebug {.1875f,.625f,.8125f,1.f};
    static inline uint64_t providerCount = 1;
    static inline const char* providerName = "AMD FSR Denoiser v1.2.0";
    static inline unsigned creates = 0, destroys = 0, dispatches = 0, defaults = 0, configures = 0;
    static inline unsigned badDefaults = 0;
    static inline unsigned badConfigureLayouts = 0, nativeDebugDispatches = 0;
    static inline unsigned badCreateChains = 0;
    static inline ffxCreateContextDescDenoiser lastCreate {};
    static inline ffxDispatchDescDenoiser lastDispatch {};
    static inline ffxDispatchDescDenoiserDirectDiffuse lastDiffuse {};
    static inline ffxDispatchDescDenoiserIndirectSpecular lastSpecular {};
    static inline ffxDispatchDescDenoiserDebugView lastDebug {};
    static inline uint64_t lastOverride = 0;
    static inline std::unordered_map<ffxContext, uint32_t> live;
    static inline std::unordered_map<ffxContext, const ffxCreateContextDescDenoiser*> createChains;
    static inline std::unordered_map<ffxContext, std::array<float, 8>> queried;
    static inline std::unordered_map<ffxContext, uint32_t> initializedKeys;
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
            initializedKeys.erase(key);
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
        if (header->type != FFX_API_CONFIGURE_DESC_TYPE_DENOISER_KEYVALUE ||
            apply.key < 1 || apply.key > 7 || apply.count != 1 || !values)
        { ++badConfigureLayouts; return FFX_API_RETURN_ERROR_PARAMETER; }
        const uint32_t bit = 1u << uint32_t(apply.key - 1u);
        // Keep the original unchanged-default assertion strict for all seven
        // first applications. Later calls intentionally exercise runtime tuning.
        if (!(initializedKeys[*context] & bit) && (values[0] != queried[*context][apply.key - 1] ||
            (apply.key == 7 && values[1] != queried[*context][7]))) ++badDefaults;
        if (rejectConfigureKey == apply.key) return FFX_API_RETURN_ERROR_RUNTIME_ERROR;
        const auto result = real ? configureFunction(context, header) : FFX_API_RETURN_OK;
        if (result == FFX_API_RETURN_OK) { ++configures; initializedKeys[*context] |= bit; }
        return result;
    }
    static ffxReturnCode_t D3D12_Dispatch(ffxContext* context, const ffxDispatchDescHeader* header)
    {
        lastDispatch = *reinterpret_cast<const ffxDispatchDescDenoiser*>(header);
        lastDiffuse = *reinterpret_cast<const ffxDispatchDescDenoiserDirectDiffuse*>(header->pNext);
        lastSpecular = *reinterpret_cast<const ffxDispatchDescDenoiserIndirectSpecular*>(lastDiffuse.header.pNext);
        lastDebug = {};
        if (lastSpecular.header.pNext)
        {
            lastDebug = *reinterpret_cast<const ffxDispatchDescDenoiserDebugView*>(lastSpecular.header.pNext);
            ++nativeDebugDispatches;
            if (!real) RecordTestProviderDebugWrites(static_cast<ID3D12GraphicsCommandList*>(lastDispatch.commandList),
                static_cast<ID3D12Resource*>(lastDebug.output.resource), lastDebug.outputSize.width, lastDebug.outputSize.height);
        }
        ++dispatches;
        if (recordPartialWrites) RecordTestProviderWrites(static_cast<ID3D12GraphicsCommandList*>(lastDispatch.commandList),
            static_cast<ID3D12Resource*>(lastSpecular.signal.output.resource), static_cast<ID3D12Resource*>(lastDiffuse.signal.output.resource));
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
