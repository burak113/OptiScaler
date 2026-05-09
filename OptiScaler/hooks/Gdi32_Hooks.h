#pragma once
#include "SysUtils.h"
#include "Config.h"
#include "detours/detours.h"

#include "Hook_Utils.h"

typedef decltype(&D3DKMTQueryAdapterInfo) PFN_D3DKMTQueryAdapterInfo;
typedef decltype(&D3DKMTEnumAdapters2) PFN_D3DKMTEnumAdapters2;

static PFN_D3DKMTQueryAdapterInfo o_D3DKMTQueryAdapterInfo = nullptr;

VALIDATE_HOOK(hkD3DKMTQueryAdapterInfo, PFN_D3DKMTQueryAdapterInfo)
static NTSTATUS hkD3DKMTQueryAdapterInfo(const D3DKMT_QUERYADAPTERINFO* data)
{
    auto result = o_D3DKMTQueryAdapterInfo(data);

    // LOG_INFO("Adapter into type: {}", (uint32_t)data->Type);
    if (data->Type == KMTQAITYPE_WDDM_2_7_CAPS)
    {
        LOG_INFO("Spoofing HAGS 2.7");

        if (data->pPrivateDriverData == nullptr)
        {
            LOG_ERROR("HAGS data nullptr");
            return 0xFFFFFFFF;
        }

        auto d3dkmt_wddm_2_7_caps = static_cast<D3DKMT_WDDM_2_7_CAPS*>(data->pPrivateDriverData);
        d3dkmt_wddm_2_7_caps->HwSchSupported = 1;
        d3dkmt_wddm_2_7_caps->HwSchEnabled = 1;
        d3dkmt_wddm_2_7_caps->HwSchEnabledByDefault = 0;

        return 0;
    }
    else if (data->Type == KMTQAITYPE_WDDM_2_9_CAPS)
    {
        LOG_INFO("Spoofing HAGS 2.9");

        if (data->pPrivateDriverData == nullptr)
        {
            LOG_ERROR("HAGS data nullptr");
            return 0xFFFFFFFF;
        }

        auto d3dkmt_wddm_2_9_caps = static_cast<D3DKMT_WDDM_2_9_CAPS*>(data->pPrivateDriverData);
        d3dkmt_wddm_2_9_caps->HwSchSupportState = DXGK_FEATURE_SUPPORT_STABLE;
        d3dkmt_wddm_2_9_caps->HwSchEnabled = 1;
        return 0;
    }

    return result;
}

// for spoofing HAGS, call early
static void hookGdi32()
{
    LOG_FUNC();

    if (Config::Instance()->SpoofHAGS.value_or_default())
    {
        o_D3DKMTQueryAdapterInfo =
            reinterpret_cast<PFN_D3DKMTQueryAdapterInfo>(DetourFindFunction("gdi32.dll", "D3DKMTQueryAdapterInfo"));

        if (o_D3DKMTQueryAdapterInfo != nullptr)
        {
            DetourTransactionBegin();
            DetourUpdateThread(GetCurrentThread());

            DetourAttach(&(PVOID&) o_D3DKMTQueryAdapterInfo, hkD3DKMTQueryAdapterInfo);

            DetourTransactionCommit();
        }
    }
}

static void unhookGdi32()
{
    if (o_D3DKMTQueryAdapterInfo != nullptr)
    {
        DetourTransactionBegin();
        DetourUpdateThread(GetCurrentThread());

        DetourDetach(&(PVOID&) o_D3DKMTQueryAdapterInfo, hkD3DKMTQueryAdapterInfo);
        o_D3DKMTQueryAdapterInfo = nullptr;

        DetourTransactionCommit();
    }
}
