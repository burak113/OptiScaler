#pragma once

#include "SysUtils.h"

#include <proxies/KernelBase_Proxy.h>

#include <cwctype> // for std::towlower

#define DEFINE_NAME_VECTORS(varName, ...)                                                                              \
    inline const std::vector<std::string> varName##Names = []                                                          \
    {                                                                                                                  \
        std::vector<std::string> v;                                                                                    \
        const char* libs[] = { __VA_ARGS__ };                                                                          \
        for (auto lib : libs)                                                                                          \
        {                                                                                                              \
            v.emplace_back(std::string(lib) + ".dll");                                                                 \
            v.emplace_back(std::string(lib));                                                                          \
        }                                                                                                              \
        return v;                                                                                                      \
    }();                                                                                                               \
    inline const std::vector<std::wstring> varName##NamesW = []                                                        \
    {                                                                                                                  \
        std::vector<std::wstring> v;                                                                                   \
        const char* libs[] = { __VA_ARGS__ };                                                                          \
        for (auto lib : libs)                                                                                          \
        {                                                                                                              \
            std::string narrow(lib);                                                                                   \
            std::wstring wide(narrow.begin(), narrow.end());                                                           \
            v.emplace_back(wide + L".dll");                                                                            \
            v.emplace_back(wide);                                                                                      \
        }                                                                                                              \
        return v;                                                                                                      \
    }();

inline std::vector<std::string> dllNames;
inline std::vector<std::wstring> dllNamesW;

//"rtsshooks64.dll", "rtsshooks64", "rtsshooks.dll", "rtsshooks",

inline const std::vector<std::string> overlayNames = { "eosovh-win32-shipping.dll",
                                                       "eosovh-win32-shipping",
                                                       "eosovh-win64-shipping.dll",
                                                       "eosovh-win64-shipping", // Epic
                                                       "gameoverlayrenderer64",
                                                       "gameoverlayrenderer64.dll",
                                                       "gameoverlayrenderer",
                                                       "gameoverlayrenderer.dll", // Steam
                                                       "socialclubd3d12renderer",
                                                       "socialclubd3d12renderer.dll", // Rockstar
                                                       "owutils.dll",
                                                       "owutils", // Overwolf
                                                       "galaxy.dll",
                                                       "galaxy",
                                                       "galaxy64.dll",
                                                       "galaxy64", // GOG Galaxy
                                                       "discordoverlay.dll",
                                                       "discordoverlay",
                                                       "discordoverlay64.dll",
                                                       "discordoverlay64", // Discord
                                                       "overlay64",
                                                       "overlay64.dll",
                                                       "overlay",
                                                       "overlay.dll" }; // Ubisoft

inline const std::vector<std::wstring> overlayNamesW = { L"eosovh-win32-shipping.dll",
                                                         L"eosovh-win32-shipping",
                                                         L"eosovh-win64-shipping.dll",
                                                         L"eosovh-win64-shipping",
                                                         L"gameoverlayrenderer64",
                                                         L"gameoverlayrenderer64.dll",
                                                         L"gameoverlayrenderer",
                                                         L"gameoverlayrenderer.dll",
                                                         L"socialclubd3d12renderer",
                                                         L"socialclubd3d12renderer.dll",
                                                         L"owutils.dll",
                                                         L"owutils",
                                                         L"galaxy.dll",
                                                         L"galaxy",
                                                         L"galaxy64.dll",
                                                         L"galaxy64",
                                                         L"discordoverlay.dll",
                                                         L"discordoverlay",
                                                         L"discordoverlay64.dll",
                                                         L"discordoverlay64",
                                                         L"overlay64",
                                                         L"overlay64.dll",
                                                         L"overlay",
                                                         L"overlay.dll" };

inline const std::vector<std::string> blockOverlayNames = { "eosovh-win32-shipping.dll",
                                                            "eosovh-win32-shipping",
                                                            "eosovh-win64-shipping.dll",
                                                            "eosovh-win64-shipping",
                                                            "gameoverlayrenderer64",
                                                            "gameoverlayrenderer64.dll",
                                                            "gameoverlayrenderer",
                                                            "gameoverlayrenderer.dll",
                                                            "owclient.dll",
                                                            "owclient"
                                                            "galaxy.dll",
                                                            "galaxy",
                                                            "galaxy64.dll",
                                                            "galaxy64",
                                                            "discordoverlay.dll",
                                                            "discordoverlay",
                                                            "discordoverlay64.dll",
                                                            "discordoverlay64",
                                                            "overlay64",
                                                            "overlay64.dll",
                                                            "overlay",
                                                            "overlay.dll" };

inline std::vector<std::wstring> blockedDllNamesW = { L"windhawk.dll", L"mactype.dll", L"mactype64.dll" };

inline std::vector<std::wstring> blockOverlayNamesW = { L"eosovh-win32-shipping.dll",
                                                        L"eosovh-win32-shipping",
                                                        L"eosovh-win64-shipping.dll",
                                                        L"eosovh-win64-shipping",
                                                        L"gameoverlayrenderer64",
                                                        L"gameoverlayrenderer64.dll",
                                                        L"gameoverlayrenderer",
                                                        L"gameoverlayrenderer.dll",
                                                        L"owclient.dll",
                                                        L"owclient",
                                                        L"galaxy.dll",
                                                        L"galaxy",
                                                        L"galaxy64.dll",
                                                        L"galaxy64",
                                                        L"discordoverlay.dll",
                                                        L"discordoverlay",
                                                        L"discordoverlay64.dll",
                                                        L"discordoverlay64",
                                                        L"overlay64",
                                                        L"overlay64.dll",
                                                        L"overlay",
                                                        L"overlay.dll" };

inline const std::vector<std::string> skipDxgiWrappingNames = { "eosovh-win32-shipping.dll",
                                                                "eosovh-win64-shipping.dll",
                                                                "gameoverlayrenderer64",
                                                                "gameoverlayrenderer64.dll",
                                                                "gameoverlayrenderer.dll",
                                                                "socialclubd3d12renderer.dll",
                                                                "owutils.dll",
                                                                "galaxy.dll",
                                                                "galaxy64.dll",
                                                                "discordoverlay.dll",
                                                                "discordoverlay64.dll",
                                                                "overlay64.dll",
                                                                "overlay.dll", // Overlays ended
                                                                "d3d11.dll",
                                                                "d3d12.dll",
                                                                "d3d12core.dll" }; // directx ended
/*
                                                          "fakenvapi.dll", // fakenvapi
                                                          "libxell.dll",
                                                          "libxess.dll",
                                                          "libxess_dx11.dll",
                                                          "igxess.dll",
                                                          "igxess2.dll",
                                                          "libxess_fg.dll",
                                                          "igxess_fg.dll", // xess ended
                                                          "intelcontrollib.dll",
                                                          "igdext64.dll",
                                                          "igdgmm64.dll", // intel drivers ended
                                                          "ffx_fsr2_api_x64.dll",
                                                          "ffx_fsr2_api_dx12_x64.dll",
                                                          "ffx_fsr3upscaler_x64.dll",
                                                          "ffx_backend_dx12_x64.dll",
                                                          "amd_fidelityfx_dx12.dll",
                                                          "amd_fidelityfx_loader_dx12.dll",
                                                          "amd_fidelityfx_upscaler_dx12.dll",
                                                          "amd_fidelityfx_framegeneration_dx12.dll", // fsr ended
                                                          "nvcamera64.dll",                          // nvcamera?
*/

DEFINE_NAME_VECTORS(dx11, "d3d11");
DEFINE_NAME_VECTORS(dx12, "d3d12");
DEFINE_NAME_VECTORS(dx12agility, "d3d12core");
DEFINE_NAME_VECTORS(dxgi, "dxgi");
DEFINE_NAME_VECTORS(vk, "vulkan-1");

DEFINE_NAME_VECTORS(nvngx, "nvngx", "_nvngx");
DEFINE_NAME_VECTORS(nvngxDlss, "nvngx_dlss");
DEFINE_NAME_VECTORS(nvapi, "nvapi64");
DEFINE_NAME_VECTORS(slInterposer, "sl.interposer");
DEFINE_NAME_VECTORS(slDlss, "sl.dlss");
DEFINE_NAME_VECTORS(slDlssg, "sl.dlss_g");
DEFINE_NAME_VECTORS(slReflex, "sl.reflex");
DEFINE_NAME_VECTORS(slPcl, "sl.pcl");
DEFINE_NAME_VECTORS(slCommon, "sl.common");

DEFINE_NAME_VECTORS(xess, "libxess");
DEFINE_NAME_VECTORS(xessDx11, "libxess_dx11");

DEFINE_NAME_VECTORS(fsr2, "ffx_fsr2_api_x64");
DEFINE_NAME_VECTORS(fsr2BE, "ffx_fsr2_api_dx12_x64");

DEFINE_NAME_VECTORS(fsr3, "ffx_fsr3upscaler_x64");
DEFINE_NAME_VECTORS(fsr3BE, "ffx_backend_dx12_x64");

DEFINE_NAME_VECTORS(ffxDx12, "amd_fidelityfx_dx12", "amd_fidelityfx_loader_dx12");
DEFINE_NAME_VECTORS(ffxDx12Upscaler, "amd_fidelityfx_upscaler_dx12");
DEFINE_NAME_VECTORS(ffxDx12FG, "amd_fidelityfx_framegeneration_dx12");
DEFINE_NAME_VECTORS(ffxDx12RR, "amd_fidelityfx_denoiser_dx12");

DEFINE_NAME_VECTORS(ffxVk, "amd_fidelityfx_vk");

/**
 * @brief Returns true if the given string ends with the given suffix.
 * Case insensitive.
 */
template <typename CharT>
[[nodiscard]] inline static bool CompareFileName(std::basic_string_view<CharT> str,
                                                 std::basic_string_view<CharT> suffix)
{
    if (str.size() < suffix.size())
        return false;

    auto fileNameSuffix = str.substr(str.size() - suffix.size());

    return std::ranges::equal(fileNameSuffix, suffix,
                              [](CharT a, CharT b)
                              {
                                  if constexpr (std::is_same_v<CharT, wchar_t>)
                                      return std::towlower(a) == std::towlower(b);
                                  else
                                      return std::tolower(static_cast<unsigned char>(a)) ==
                                             std::tolower(static_cast<unsigned char>(b));
                              });
}

/**
 * @brief Returns true if the given dllName ends with any of the names in the
 * name list. Case insensitive.
 */
[[nodiscard]] inline static bool CheckDllName(std::string_view dllName, std::span<const std::string> namesList)
{
    return std::ranges::any_of(namesList,
                               [&](const auto& candidate) { return CompareFileName<char>(dllName, candidate); });
}

/**
 * @brief Returns true if the given dllName ends with any of the names in the
 * name list. Case insensitive.
 */
[[nodiscard]] inline static bool CheckDllName(std::wstring_view dllName, std::span<const std::wstring> namesList)
{
    return std::ranges::any_of(namesList,
                               [&](const auto& candidate) { return CompareFileName<wchar_t>(dllName, candidate); });
}

/**
 * @brief Iterates through namesList and returns a handle to the first name that
 * matches a currently loaded module. Returns nullptr if none of the names are found.
 */
[[nodiscard]] inline static HMODULE GetDllModule(std::span<const std::string> namesList)
{
    for (const auto& name : namesList)
    {
        if (HMODULE hMod = KernelBaseProxy::GetModuleHandleA_()(name.c_str()))
            return hMod;
    }
    return nullptr;
}

/**
 * @brief Iterates through namesList and returns a handle to the first name that
 * matches a currently loaded module. Returns nullptr if none of the names are found.
 */
[[nodiscard]] inline static HMODULE GetDllModule(std::span<const std::wstring> namesList)
{
    for (const auto& name : namesList)
    {
        if (HMODULE hMod = KernelBaseProxy::GetModuleHandleW_()(name.c_str()))
            return hMod;
    }
    return nullptr;
}
