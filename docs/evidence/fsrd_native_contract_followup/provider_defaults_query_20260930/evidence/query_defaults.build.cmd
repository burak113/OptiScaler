@call "F:\VisualStudio\VC\Auxiliary\Build\vcvars64.bat" >nul
@if errorlevel 1 exit /b %errorlevel%
@cl /nologo /std:c++20 /EHsc /O2 "F:\OptiRevelations\OptiScaler-ffxD-alpha\tools_tmp\provider_defaults_query_20260930\evidence\query_defaults.cpp" /Fe:"F:\OptiRevelations\OptiScaler-ffxD-alpha\tools_tmp\provider_defaults_query_20260930\evidence\query_defaults.exe" /Fo:"F:\OptiRevelations\OptiScaler-ffxD-alpha\tools_tmp\provider_defaults_query_20260930\evidence\query_defaults.obj" /link d3d12.lib dxgi.lib
