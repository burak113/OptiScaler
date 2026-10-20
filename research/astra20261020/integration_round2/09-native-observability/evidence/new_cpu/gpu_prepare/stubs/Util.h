#pragma once
#include <filesystem>
inline std::filesystem::path g_dllPath;
namespace Util { inline std::filesystem::path DllPath() { return g_dllPath; } }
