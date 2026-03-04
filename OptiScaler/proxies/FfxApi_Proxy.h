#pragma once

#include "SysUtils.h"
#include "Util.h"
#include "Config.h"
#include "Logger.h"

#include <proxies/Ntdll_Proxy.h>
#include <proxies/KernelBase_Proxy.h>

#include <inputs/FfxApi_Dx12.h>
#include <inputs/FfxApi_Vk.h>

#include <fsr4/FSR4ModelSelection.h>

#include <ffx_api.h>
#include <detours/detours.h>
#include <ffx_framegeneration.h>
#include <ffx_upscale.h>
#include <fsr-rr/ffx_denoiser.h>

#include <magic_enum.hpp>

// A mess to be able to import both
#define FFX_API_CONFIGURE_FG_SWAPCHAIN_KEY_WAITCALLBACK FFX_API_CONFIGURE_FG_SWAPCHAIN_KEY_WAITCALLBACK_DX12
#define FFX_API_CONFIGURE_FG_SWAPCHAIN_KEY_FRAMEPACINGTUNING FFX_API_CONFIGURE_FG_SWAPCHAIN_KEY_FRAMEPACINGTUNING_DX12

#include <dx12/ffx_api_dx12.h>
#include "DllNames.h"

#undef FFX_API_CONFIGURE_FG_SWAPCHAIN_KEY_WAITCALLBACK
#undef FFX_API_CONFIGURE_FG_SWAPCHAIN_KEY_FRAMEPACINGTUNING

#define FFX_API_CONFIGURE_FG_SWAPCHAIN_KEY_WAITCALLBACK FFX_API_CONFIGURE_FG_SWAPCHAIN_KEY_WAITCALLBACK_VK
#define FFX_API_CONFIGURE_FG_SWAPCHAIN_KEY_FRAMEPACINGTUNING FFX_API_CONFIGURE_FG_SWAPCHAIN_KEY_FRAMEPACINGTUNING_VK

#include <vk/ffx_api_vk.h>

#undef FFX_API_CONFIGURE_FG_SWAPCHAIN_KEY_WAITCALLBACK
#undef FFX_API_CONFIGURE_FG_SWAPCHAIN_KEY_FRAMEPACINGTUNING

enum class FFXStructType
{
    General,
    Upscaling,
    FG,
    SwapchainDX12,
    SwapchainVulkan,
    Denoiser,
    RadianceCache,
    Unknown,
};

struct FfxModule
{
    HMODULE dll = nullptr;
    feature_version version { 0, 0, 0 };

    bool skipCreateCalls = false;
    bool skipConfigureCalls = false;
    bool skipQueryCalls = false;
    bool skipDispatchCalls = false;

    bool isLoader = false;

    PfnFfxCreateContext CreateContext = nullptr;
    PfnFfxDestroyContext DestroyContext = nullptr;
    PfnFfxConfigure Configure = nullptr;
    PfnFfxQuery Query = nullptr;
    PfnFfxDispatch Dispatch = nullptr;
};

class FfxApiProxy
{
  private:
    inline static FfxModule main_dx12;
    inline static FfxModule upscaling_dx12;
    inline static FfxModule fg_dx12;
    inline static FfxModule rrDenoiser_dx12;

    inline static FfxModule main_vk;

    inline static ankerl::unordered_dense::map<ffxContext*, FFXStructType> contextToType;

    inline static bool _skipDestroyCalls = false;

    static inline void ParseVersion(const char* version_str, feature_version* _version)
    {
        const char* p = version_str;

        // Skip non-digits at front
        while (*p)
        {
            if (isdigit((unsigned char) p[0]))
            {
                if (sscanf(p, "%u.%u.%u", &_version->major, &_version->minor, &_version->patch) == 3)
                    return;
            }
            ++p;
        }

        LOG_WARN("can't parse {0}", version_str);
    }

    static bool IsLoader(std::wstring_view filePath)
    {
        auto size = std::filesystem::file_size(filePath);

        // < 1 MB
        return size < 1048576;
    }

    static bool LoadFfxModuleDx12(FfxModule& proxyModule, const std::span<const std::wstring> dllNames,
                                  HMODULE module = nullptr, void (*loadCallback)(HMODULE) = nullptr)
    {
        // Early exit if already loaded
        if (proxyModule.dll != nullptr && proxyModule.CreateContext != nullptr)
            return true;

        if (module != nullptr)
            proxyModule.dll = module;

        // If null, attempt to load the library by name
        if (proxyModule.dll == nullptr)
        {
            // Try new api first
            for (const std::wstring& name : dllNames)
            {
                WLOG_DEBUG(L"Trying to load {}", name);

                if (proxyModule.dll == nullptr)
                {
                    proxyModule.dll = NtdllProxy::LoadLibraryExW_Ldr(name.c_str(), NULL, 0);

                    if (proxyModule.dll != nullptr)
                    {
                        WLOG_INFO(L"{} loaded from exe folder", name);

                        if (loadCallback != nullptr)
                            loadCallback(proxyModule.dll);

                        break;
                    }
                }
            }
        }

        TryInstallFfxModuleHooksDx12(proxyModule);

        bool loadResult = proxyModule.CreateContext != nullptr;

        LOG_INFO("LoadResult: {}", loadResult);

        if (!loadResult)
            proxyModule.dll = nullptr;

        return loadResult;
    }

    static void TryInstallFfxModuleHooksDx12(FfxModule& proxyModule)
    {
        if (proxyModule.dll != nullptr && proxyModule.Configure == nullptr)
        {
            // Get addresses of module functions
            proxyModule.Configure =
                (PfnFfxConfigure) KernelBaseProxy::GetProcAddress_()(proxyModule.dll, "ffxConfigure");
            proxyModule.CreateContext =
                (PfnFfxCreateContext) KernelBaseProxy::GetProcAddress_()(proxyModule.dll, "ffxCreateContext");
            proxyModule.DestroyContext =
                (PfnFfxDestroyContext) KernelBaseProxy::GetProcAddress_()(proxyModule.dll, "ffxDestroyContext");
            proxyModule.Dispatch = (PfnFfxDispatch) KernelBaseProxy::GetProcAddress_()(proxyModule.dll, "ffxDispatch");
            proxyModule.Query = (PfnFfxQuery) KernelBaseProxy::GetProcAddress_()(proxyModule.dll, "ffxQuery");

            if (Config::Instance()->EnableFfxInputs.value_or_default() && proxyModule.CreateContext != nullptr)
            {
                DetourTransactionBegin();
                DetourUpdateThread(GetCurrentThread());

                // Detour module functions to FfxApi_Proxy switchboard
                if (proxyModule.Configure != nullptr)
                    DetourAttach(&(PVOID&) proxyModule.Configure, ffxConfigure_Dx12);

                if (proxyModule.CreateContext != nullptr)
                    DetourAttach(&(PVOID&) proxyModule.CreateContext, ffxCreateContext_Dx12);

                if (proxyModule.DestroyContext != nullptr)
                    DetourAttach(&(PVOID&) proxyModule.DestroyContext, ffxDestroyContext_Dx12);

                if (proxyModule.Dispatch != nullptr)
                    DetourAttach(&(PVOID&) proxyModule.Dispatch, ffxDispatch_Dx12);

                if (proxyModule.Query != nullptr)
                    DetourAttach(&(PVOID&) proxyModule.Query, ffxQuery_Dx12);

                State::Instance().fsrHooks = true;

                DetourTransactionCommit();
            }
        }
    }

    static void UpdateFeatureVersionDx12(FfxModule& module, uint64_t type, const char* label)
    {
        if (module.version.major != 0 || module.Query == nullptr)
            return;

        ffxQueryDescGetVersions versionQuery {};
        versionQuery.header.type = FFX_API_QUERY_DESC_TYPE_GET_VERSIONS;
        versionQuery.createDescType = type;

        // Newer effects like FSR Ray Regen seem to require a D3D12 device if an ffxContext 
        // hasn't already been created. Depending on init/hook order, this can be slightly 
        // inconvenient, as features like NVSDK_NGX_D3D12_GetFeatureRequirements() run before
        // the device is created/captured.
        versionQuery.device = State::Instance().currentD3D12Device;
        uint64_t versionCount = 0;
        versionQuery.outputCount = &versionCount;

        auto queryResult = module.Query(nullptr, &versionQuery.header);

        if (queryResult == FFX_API_RETURN_OK && versionCount > 0)
        {
            std::vector<uint64_t> versionIds(versionCount);
            std::vector<const char*> versionNames(versionCount);
            versionQuery.versionIds = versionIds.data();
            versionQuery.versionNames = versionNames.data();

            queryResult = module.Query(nullptr, &versionQuery.header);

            if (queryResult == FFX_API_RETURN_OK)
            {
                ParseVersion(versionNames[0], &module.version);
                LOG_INFO("FfxApi Dx12 {} version: {}.{}.{}", label, module.version.major, module.version.minor,
                         module.version.patch);
                return;
            }
        }

        LOG_WARN("{} Query failed result: {}", label, (UINT) queryResult);
    }

  public:
    static HMODULE Dx12Module() { return main_dx12.dll; }
    static HMODULE Dx12Module_SR() { return upscaling_dx12.dll; }
    static HMODULE Dx12Module_FG() { return fg_dx12.dll; }
    static HMODULE Dx12Module_RR() { return rrDenoiser_dx12.dll; }

    // Returns true if the FFX framegen module is loaded
    static bool IsFGReady() { return (main_dx12.dll && !main_dx12.isLoader) || fg_dx12.dll != nullptr; }
    // Returns true if the FSR upscaler module is loaded
    static bool IsSRReady() { return (main_dx12.dll && !main_dx12.isLoader) || upscaling_dx12.dll != nullptr; }
    // Returns true if the FSR Ray Regen module is loaded
    static bool IsRRReady() { return IsSRReady() && rrDenoiser_dx12.dll != nullptr; }

    static FFXStructType GetType(ffxStructType_t type)
    {
        switch (type & FFX_API_EFFECT_MASK) // type without the specific effect
        {
        case FFX_API_EFFECT_ID_GENERAL:
            return FFXStructType::General;

        case FFX_API_EFFECT_ID_UPSCALE:
            return FFXStructType::Upscaling;

        case FFX_API_EFFECT_ID_FRAMEGENERATION:
            return FFXStructType::FG;

        case FFX_API_EFFECT_ID_FRAMEGENERATIONSWAPCHAIN_DX12:
            return FFXStructType::SwapchainDX12;

        case FFX_API_EFFECT_ID_FGSC_VK:
            return FFXStructType::SwapchainVulkan;

        case 0x00050000u:
            return FFXStructType::Denoiser;

        case 0x00060000u:
            return FFXStructType::RadianceCache;

        default:
            return FFXStructType::Unknown;
        }
    }

    // Can't directly check for type when query is used
    // might apply to FFX_API_DESC_TYPE_OVERRIDE_VERSION as well
    static FFXStructType GetIndirectType(ffxQueryDescHeader* header)
    {
        ffxStructType_t type = header->type;

        if (header->type == FFX_API_QUERY_DESC_TYPE_GET_VERSIONS ||
            header->type == FFX_API_QUERY_DESC_TYPE_GET_PROVIDER_VERSION)
        {
            type = header[1].type;
        }

        return GetType(type);
    }

    static bool InitFfxDx12(HMODULE module = nullptr)
    {
        // if dll already loaded
        if (main_dx12.dll != nullptr && main_dx12.CreateContext != nullptr)
            return true;

        spdlog::info("");

        // Check if loader if not null
        if (module != nullptr)
        {
            wchar_t path[MAX_PATH];
            DWORD len = GetModuleFileNameW(module, path, MAX_PATH);

            main_dx12.isLoader = IsLoader(path);
            main_dx12.dll = module;
        }

        if (main_dx12.dll == nullptr)
        {
            const auto& cfg = *Config::Instance();
            // Try new api first

            for (const std::wstring& name : ffxDx12NamesW)
            {
                WLOG_DEBUG(L"Trying to load {}", name);

                // Search config directory
                if (main_dx12.dll == nullptr && cfg.FfxDx12Path.has_value())
                {
                    std::filesystem::path libPath(cfg.FfxDx12Path.value());
                    std::wstring fileName;

                    if (libPath.has_filename())
                        fileName = libPath.wstring();
                    else
                        fileName = (libPath / name).wstring();

                    main_dx12.dll = NtdllProxy::LoadLibraryExW_Ldr(fileName.c_str(), NULL, 0);

                    if (main_dx12.dll != nullptr)
                    {
                        WLOG_INFO(L"{} loaded from {}", name, cfg.FfxDx12Path.value());

                        // hacky but works for now
                        main_dx12.isLoader = IsLoader(fileName);
                        break;
                    }
                }

                // Search parent directory
                if (main_dx12.dll == nullptr)
                {
                    std::filesystem::path filePath = (Util::DllPath().parent_path() / name);
                    main_dx12.dll = NtdllProxy::LoadLibraryExW_Ldr(filePath.c_str(), NULL, 0);

                    if (main_dx12.dll != nullptr)
                    {
                        WLOG_INFO(L"{} loaded from exe folder", name);

                        // hacky but works for now
                        main_dx12.isLoader = IsLoader(filePath.c_str());
                        break;
                    }
                }
            }
        }

        TryInstallFfxModuleHooksDx12(main_dx12);
        InitFfxDx12_SR();
        InitFfxDx12_FG();
        InitFfxDx12_RR();

        bool loadResult = main_dx12.CreateContext != nullptr || upscaling_dx12.CreateContext != nullptr ||
                          fg_dx12.CreateContext != nullptr;

        LOG_INFO("LoadResult: {}", loadResult);

        if (!loadResult)
            main_dx12.dll = nullptr;

        return loadResult;
    }

    static bool InitFfxDx12_SR(HMODULE module = nullptr)
    {
        return LoadFfxModuleDx12(upscaling_dx12, ffxDx12UpscalerNamesW, module,
                                 [](HMODULE hMod) { FSR4ModelSelection::Hook(hMod, FSR4Source::SDK); });
    }

    static bool InitFfxDx12_FG(HMODULE module = nullptr) { return LoadFfxModuleDx12(fg_dx12, ffxDx12FGNamesW, module); }

    static bool InitFfxDx12_RR(HMODULE module = nullptr)
    {
        return LoadFfxModuleDx12(rrDenoiser_dx12, ffxDx12RRNamesW, module);
    }

    static feature_version VersionDx12()
    {
        // Try to update main first
        UpdateFeatureVersionDx12(main_dx12, FFX_API_CREATE_CONTEXT_DESC_TYPE_UPSCALE, "Main");

        // Fallbacks if main is still invalid
        if (main_dx12.version.major == 0)
        {
            if (upscaling_dx12.Query != nullptr)
                main_dx12.version = VersionDx12_SR();
            if (main_dx12.version.major == 0 && fg_dx12.Query != nullptr)
                main_dx12.version = VersionDx12_FG();
        }

        return main_dx12.version;
    }

    static feature_version VersionDx12_SR()
    {
        if (upscaling_dx12.Query == nullptr)
            return VersionDx12();

        UpdateFeatureVersionDx12(upscaling_dx12, FFX_API_CREATE_CONTEXT_DESC_TYPE_UPSCALE, "SR");
        return upscaling_dx12.version;
    }

    static feature_version VersionDx12_FG()
    {
        if (fg_dx12.Query == nullptr)
            return VersionDx12();

        UpdateFeatureVersionDx12(fg_dx12, FFX_API_CREATE_CONTEXT_DESC_TYPE_FRAMEGENERATION, "FG");
        return fg_dx12.version;
    }

    static feature_version VersionDx12_RR()
    {
        if (rrDenoiser_dx12.Query == nullptr)
            return VersionDx12();

        UpdateFeatureVersionDx12(rrDenoiser_dx12, FFX_API_CREATE_CONTEXT_DESC_TYPE_DENOISER, "RR");
        return rrDenoiser_dx12.version;
    }

    static ffxReturnCode_t D3D12_CreateContext(ffxContext* context, ffxCreateContextDescHeader* desc,
                                               const ffxAllocationCallbacks* memCb)
    {
        const FFXStructType type = GetType(desc->type);
        contextToType[context] = type;
        FfxModule* pModule = nullptr;

        // Module routing
        switch (type)
        {
        case FFXStructType::FG:
        case FFXStructType::SwapchainDX12:
            pModule = &fg_dx12;

            if (fg_dx12.dll == nullptr)
                break;

            LOG_DEBUG("Creating with fg_dx12");
            return fg_dx12.CreateContext(context, desc, memCb);

        case FFXStructType::Denoiser:
            pModule = &rrDenoiser_dx12;

            if (rrDenoiser_dx12.dll == nullptr)
                break;

            LOG_DEBUG("Creating with rrDenoiser_dx12");
            return rrDenoiser_dx12.CreateContext(context, desc, memCb);

        case FFXStructType::Upscaling:
        default:
            // General/Unknown types default to the Upscaling module first
            pModule = &upscaling_dx12;

            if (upscaling_dx12.dll == nullptr)
                break;

            LOG_DEBUG("Creating with upscaling_dx12");
            return upscaling_dx12.CreateContext(context, desc, memCb);
        }

        // Reentry guard (Fallback to Main)
        if (main_dx12.dll != nullptr && !pModule->skipCreateCalls)
        {
            LOG_DEBUG("Creating with main_dx12");

            pModule->skipCreateCalls = true;
            ffxReturnCode_t result = main_dx12.CreateContext(context, desc, memCb);
            pModule->skipCreateCalls = false;

            return result;
        }

        return FFX_API_RETURN_NO_PROVIDER;
    }

    static ffxReturnCode_t D3D12_DestroyContext(ffxContext* context, const ffxAllocationCallbacks* memCb)
    {
        ffxReturnCode_t result = FFX_API_RETURN_ERROR;
        auto type = FFXStructType::Unknown;

        if (contextToType.contains(context))
        {
            LOG_DEBUG("Found context type mapping: {}", magic_enum::enum_name(type));
            type = contextToType[context];
            contextToType.erase(context);
        }
        else
        {
            LOG_DEBUG("No context type mapping found, defaulting to Unknown");
        }

        // Normal destructor routing
        switch (type)
        {
        case FFXStructType::General:
            LOG_DEBUG("Destroying with main_dx12");
            if (main_dx12.dll != nullptr)
                result = main_dx12.DestroyContext(context, memCb);
            break;

        case FFXStructType::Upscaling:
            LOG_DEBUG("Destroying with upscaling_dx12");
            if (upscaling_dx12.dll != nullptr)
                result = upscaling_dx12.DestroyContext(context, memCb);
            break;

        case FFXStructType::Denoiser:
            LOG_DEBUG("Destroying with rrDenoiser_dx12");
            if (rrDenoiser_dx12.dll != nullptr)
                result = rrDenoiser_dx12.DestroyContext(context, memCb);
            break;

        case FFXStructType::FG:
        case FFXStructType::SwapchainDX12:
            LOG_DEBUG("Destroying with fg_dx12");
            if (fg_dx12.dll != nullptr)
                result = fg_dx12.DestroyContext(context, memCb);
            break;

        default:
            break;
        }

        // Destroyed normally
        if (result == FFX_API_RETURN_OK)
        {
            LOG_DEBUG("Destroyed with mapped module");
            return result;
        }

        // Very much not normal object destruction routing
        if (upscaling_dx12.dll != nullptr)
        {
            LOG_DEBUG("Destroying with upscaling_dx12");
            result = upscaling_dx12.DestroyContext(context, memCb);
        }

        if (result == FFX_API_RETURN_OK)
        {
            LOG_DEBUG("Destroyed with upscaling_dx12");
            return result;
        }

        if (result == FFX_API_RETURN_OK)
        {
            LOG_DEBUG("Destroyed with rrDenoiser_dx12");
            return result;
        }

        if (fg_dx12.dll != nullptr)
        {
            LOG_DEBUG("Destroying with fg_dx12");
            result = fg_dx12.DestroyContext(context, memCb);
        }

        if (result == FFX_API_RETURN_OK)
        {
            LOG_DEBUG("Destroyed with fg_dx12");
            return result;
        }

        if (main_dx12.dll != nullptr && !_skipDestroyCalls)
        {
            LOG_DEBUG("Destroying with main_dx12");
            _skipDestroyCalls = true;
            result = main_dx12.DestroyContext(context, memCb);
            _skipDestroyCalls = false;
        }

        if (result == FFX_API_RETURN_OK)
        {
            LOG_DEBUG("Destroyed with main_dx12");
            return result;
        }

        LOG_ERROR("Failed to destroy context in any module");
        return FFX_API_RETURN_NO_PROVIDER;
    }

    static ffxReturnCode_t D3D12_Configure(ffxContext* context, const ffxConfigureDescHeader* desc)
    {
        FFXStructType type = GetType(desc->type);
        FfxModule* pModule = nullptr;

        switch (type)
        {
        case FFXStructType::FG:
        case FFXStructType::SwapchainDX12:
            pModule = &fg_dx12;

            if (fg_dx12.dll != nullptr)
                return fg_dx12.Configure(context, desc);
            break;

        case FFXStructType::Denoiser:
            pModule = &rrDenoiser_dx12;

            if (rrDenoiser_dx12.dll != nullptr)
                return rrDenoiser_dx12.Configure(context, desc);
            break;

        case FFXStructType::Upscaling:
        default:
            pModule = &upscaling_dx12;

            if (upscaling_dx12.dll != nullptr)
                return upscaling_dx12.Configure(context, desc);
            break;
        }

        // Reentry guard (Fallback to Main)
        if (pModule == nullptr)
            pModule = &main_dx12;

        if (main_dx12.dll != nullptr && !pModule->skipConfigureCalls)
        {
            pModule->skipConfigureCalls = true;
            ffxReturnCode_t result = main_dx12.Configure(context, desc);
            pModule->skipConfigureCalls = false;

            return result;
        }

        return FFX_API_RETURN_NO_PROVIDER;
    }

    static ffxReturnCode_t D3D12_Query(ffxContext* context, ffxQueryDescHeader* desc)
    {
        FFXStructType type = GetIndirectType(desc);
        FfxModule* pModule = nullptr;

        switch (type)
        {
        case FFXStructType::FG:
        case FFXStructType::SwapchainDX12:
            pModule = &fg_dx12;

            if (fg_dx12.dll != nullptr)
                return fg_dx12.Query(context, desc);
            break;

        case FFXStructType::Denoiser:
            pModule = &rrDenoiser_dx12;

            if (rrDenoiser_dx12.dll != nullptr)
                return rrDenoiser_dx12.Query(context, desc);
            break;

        case FFXStructType::Upscaling:
        default:
            // Fallback to Upscaling module for General/Unknown
            pModule = &upscaling_dx12;

            if (upscaling_dx12.dll != nullptr)
                return upscaling_dx12.Query(context, desc);
            break;
        }

        if (pModule == nullptr)
            pModule = &main_dx12;

        if (main_dx12.dll != nullptr && !pModule->skipQueryCalls)
        {
            pModule->skipQueryCalls = true;
            ffxReturnCode_t result = main_dx12.Query(context, desc);
            pModule->skipQueryCalls = false;

            return result;
        }

        return FFX_API_RETURN_NO_PROVIDER;
    }

    static ffxReturnCode_t D3D12_Dispatch(ffxContext* context, const ffxDispatchDescHeader* desc)
    {
        FFXStructType type = GetType(desc->type);
        FfxModule* pModule = nullptr;

        switch (type)
        {
        case FFXStructType::FG:
        case FFXStructType::SwapchainDX12:
            pModule = &fg_dx12;

            if (fg_dx12.dll != nullptr)
                return fg_dx12.Dispatch(context, desc);
            break;

        case FFXStructType::Denoiser:
            pModule = &rrDenoiser_dx12;

            if (rrDenoiser_dx12.dll != nullptr)
                return rrDenoiser_dx12.Dispatch(context, desc);
            break;

        case FFXStructType::Upscaling:
        default:
            // Fallback to Upscaling module for General/Unknown
            pModule = &upscaling_dx12;

            if (upscaling_dx12.dll != nullptr)
                return upscaling_dx12.Dispatch(context, desc);
            break;
        }

        if (pModule == nullptr)
            pModule = &main_dx12;

        if (main_dx12.dll != nullptr && !pModule->skipDispatchCalls)
        {
            pModule->skipDispatchCalls = true;
            ffxReturnCode_t result = main_dx12.Dispatch(context, desc);
            pModule->skipDispatchCalls = false;

            return result;
        }

        return FFX_API_RETURN_NO_PROVIDER;
    }

    static HMODULE VkModule() { return main_vk.dll; }

    static bool InitFfxVk(HMODULE module = nullptr)
    {
        // if dll already loaded
        if (main_vk.dll != nullptr && main_vk.CreateContext != nullptr)
            return true;

        spdlog::info("");

        LOG_DEBUG("Loading amd_fidelityfx_vk.dll methods");

        if (module != nullptr)
            main_vk.dll = module;

        if (main_vk.dll == nullptr && Config::Instance()->FfxVkPath.has_value())
        {
            std::filesystem::path libPath(Config::Instance()->FfxVkPath.value().c_str());

            if (libPath.has_filename())
                main_vk.dll = NtdllProxy::LoadLibraryExW_Ldr(libPath.c_str(), NULL, 0);
            else
                main_vk.dll = NtdllProxy::LoadLibraryExW_Ldr((libPath / L"amd_fidelityfx_vk.dll").c_str(), NULL, 0);

            if (main_vk.dll != nullptr)
            {
                WLOG_INFO(L"amd_fidelityfx_vk.dll loaded from {0}", Config::Instance()->FfxVkPath.value());
            }
        }

        if (main_vk.dll == nullptr)
        {
            main_vk.dll = NtdllProxy::LoadLibraryExW_Ldr(L"amd_fidelityfx_vk.dll", NULL, 0);

            if (main_vk.dll != nullptr)
                LOG_INFO("amd_fidelityfx_vk.dll loaded from exe folder");
        }

        if (main_vk.dll != nullptr && main_vk.CreateContext == nullptr)
        {
            main_vk.Configure = (PfnFfxConfigure) KernelBaseProxy::GetProcAddress_()(main_vk.dll, "ffxConfigure");
            main_vk.CreateContext =
                (PfnFfxCreateContext) KernelBaseProxy::GetProcAddress_()(main_vk.dll, "ffxCreateContext");
            main_vk.DestroyContext =
                (PfnFfxDestroyContext) KernelBaseProxy::GetProcAddress_()(main_vk.dll, "ffxDestroyContext");
            main_vk.Dispatch = (PfnFfxDispatch) KernelBaseProxy::GetProcAddress_()(main_vk.dll, "ffxDispatch");
            main_vk.Query = (PfnFfxQuery) KernelBaseProxy::GetProcAddress_()(main_vk.dll, "ffxQuery");

            if (Config::Instance()->EnableFfxInputs.value_or_default() && main_vk.CreateContext != nullptr)
            {
                DetourTransactionBegin();
                DetourUpdateThread(GetCurrentThread());

                if (main_vk.Configure != nullptr)
                    DetourAttach(&(PVOID&) main_vk.Configure, ffxConfigure_Vk);

                if (main_vk.CreateContext != nullptr)
                    DetourAttach(&(PVOID&) main_vk.CreateContext, ffxCreateContext_Vk);

                if (main_vk.DestroyContext != nullptr)
                    DetourAttach(&(PVOID&) main_vk.DestroyContext, ffxDestroyContext_Vk);

                if (main_vk.Dispatch != nullptr)
                    DetourAttach(&(PVOID&) main_vk.Dispatch, ffxDispatch_Vk);

                if (main_vk.Query != nullptr)
                    DetourAttach(&(PVOID&) main_vk.Query, ffxQuery_Vk);

                State::Instance().fsrHooks = true;

                DetourTransactionCommit();
            }
        }

        bool loadResult = main_vk.CreateContext != nullptr;

        LOG_INFO("LoadResult: {}", loadResult);

        if (loadResult)
            VersionVk();
        else
            main_vk.dll = nullptr;

        return loadResult;
    }

    static feature_version VersionVk()
    {
        if (main_vk.version.major == 0 && main_vk.Query != nullptr)
        {
            ffxQueryDescGetVersions versionQuery {};
            versionQuery.header.type = FFX_API_QUERY_DESC_TYPE_GET_VERSIONS;
            versionQuery.createDescType = FFX_API_CREATE_CONTEXT_DESC_TYPE_UPSCALE;
            uint64_t versionCount = 0;
            versionQuery.outputCount = &versionCount;

            auto queryResult = main_vk.Query(nullptr, &versionQuery.header);

            // get number of versions for allocation
            if (versionCount > 0 && queryResult == FFX_API_RETURN_OK)
            {

                std::vector<uint64_t> versionIds;
                std::vector<const char*> versionNames;
                versionIds.resize(versionCount);
                versionNames.resize(versionCount);
                versionQuery.versionIds = versionIds.data();
                versionQuery.versionNames = versionNames.data();

                queryResult = main_vk.Query(nullptr, &versionQuery.header);

                if (queryResult == FFX_API_RETURN_OK)
                {
                    ParseVersion(versionNames[0], &main_vk.version);
                    LOG_INFO("FfxApi Vulkan version: {}.{}.{}", main_vk.version.major, main_vk.version.minor,
                             main_vk.version.patch);
                }
                else
                {
                    LOG_WARN("main_vk.Query 2 result: {}", (UINT) queryResult);
                }
            }
            else
            {
                LOG_WARN("main_vk.Query result: {}", (UINT) queryResult);
            }
        }

        return main_vk.version;
    }

    static PfnFfxCreateContext VULKAN_CreateContext() { return main_vk.CreateContext; }
    static PfnFfxDestroyContext VULKAN_DestroyContext() { return main_vk.DestroyContext; }
    static PfnFfxConfigure VULKAN_Configure() { return main_vk.Configure; }
    static PfnFfxQuery VULKAN_Query() { return main_vk.Query; }
    static PfnFfxDispatch VULKAN_Dispatch() { return main_vk.Dispatch; }

    static std::string ReturnCodeToString(ffxReturnCode_t result)
    {
        switch (result)
        {
        case FFX_API_RETURN_OK:
            return "The operation was successful.";
        case FFX_API_RETURN_ERROR:
            return "An error occurred that is not further specified.";
        case FFX_API_RETURN_ERROR_UNKNOWN_DESCTYPE:
            return "The structure type given was not recognized for the function or context with which it was used. "
                   "This is likely a programming error.";
        case FFX_API_RETURN_ERROR_RUNTIME_ERROR:
            return "The underlying runtime (e.g. D3D12, Vulkan) or effect returned an error code.";
        case FFX_API_RETURN_NO_PROVIDER:
            return "No provider was found for the given structure type. This is likely a programming error.";
        case FFX_API_RETURN_ERROR_MEMORY:
            return "A memory allocation failed.";
        case FFX_API_RETURN_ERROR_PARAMETER:
            return "A parameter was invalid, e.g. a null pointer, empty resource or out-of-bounds enum value.";
        default:
            return "Unknown";
        }
    }
};
