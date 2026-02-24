#pragma once
#include "SysUtils.h"
#include "DllNames.h"

class LibraryLoadHooks
{
  private:
    inline static bool _overlayMethodsCalled = false;

    static void CheckModulesInMemory();
    static bool StartsWithInsensitive(std::wstring_view str, std::wstring_view prefix);

  public:
    static HMODULE LoadLibraryCheckA(std::string libName, LPCSTR lpLibFullPath);
    static HMODULE LoadLibraryCheckW(std::wstring libName, LPCWSTR lpLibFullPath);
    static std::optional<NTSTATUS> FreeLibrary(PVOID library);

    static HMODULE LoadNvApi();
    static HMODULE LoadFfxapiVk(std::wstring originalPath);
    static HMODULE LoadFfxapiDx12(std::wstring originalPath);
    static HMODULE LoadLibxessDx11(std::wstring originalPath);
    static HMODULE LoadLibxess(std::wstring originalPath);
    static HMODULE LoadNvngxDlss(std::wstring originalPath);

    static bool IsApiSetName(const std::wstring_view& n);
    static bool EndsWithInsensitive(std::wstring_view text, std::wstring_view suffix);
    static bool EndsWithInsensitive(const UNICODE_STRING& text, std::wstring_view suffix);
};

/**
 * @brief Attempts to find a previously loaded module and initialize its hooks using 
 * a function pointer.
 * @return The module handle if its found. Null on failure.
 */
template <typename FuncT, typename... Args>
    requires std::invocable<FuncT, HMODULE, Args...>
static inline HMODULE TryHookModule(std::span<const std::wstring> names, FuncT initFunc, Args&&... args)
{
    if (HMODULE hMod = GetDllModule(names); hMod != nullptr)
    {
        char path[MAX_PATH];
        DWORD len = GetModuleFileNameA(hMod, path, MAX_PATH);
        std::string_view logName { path, len };

        if (auto pos = logName.find_last_of("\\/"); pos != std::string_view::npos)
            logName.remove_prefix(pos + 1);

        LOG_DEBUG("{} already in memory", logName);

        std::invoke(initFunc, hMod, std::forward<Args>(args)...);
        return hMod;
    }

    return nullptr;
}