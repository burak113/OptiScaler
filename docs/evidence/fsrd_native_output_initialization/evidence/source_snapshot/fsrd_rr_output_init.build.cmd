@call "F:\VisualStudio\VC\Auxiliary\Build\vcvars64.bat" >nul
@if errorlevel 1 exit /b %errorlevel%
@cl /nologo /std:c++20 /EHsc /O2 "F:\OptiRevelations\OptiScaler-ffxD-alpha\tools_tmp\native_output_initialization_diagnostic_20260930\fsrd_rr_output_init.cpp" /Fe:"F:\OptiRevelations\OptiScaler-ffxD-alpha\tools_tmp\native_output_initialization_diagnostic_20260930\fsrd_rr_output_init.exe" /Fo:"F:\OptiRevelations\OptiScaler-ffxD-alpha\tools_tmp\native_output_initialization_diagnostic_20260930\fsrd_rr_output_init.obj" /link d3d12.lib dxgi.lib
