@call "F:\VisualStudio\VC\Auxiliary\Build\vcvars64.bat" >nul
@if errorlevel 1 exit /b %errorlevel%
@cl /nologo /std:c++20 /EHsc /O2 "F:\OptiRevelations\OptiScaler-ffxD-alpha\tools_tmp\fsrd_native_gap_cpu_record_control_20260930\fsrd_rr_gap_control.cpp" /Fe:"F:\OptiRevelations\OptiScaler-ffxD-alpha\tools_tmp\fsrd_native_gap_cpu_record_control_20260930\fsrd_rr_gap_control.exe" /Fo:"F:\OptiRevelations\OptiScaler-ffxD-alpha\tools_tmp\fsrd_native_gap_cpu_record_control_20260930\fsrd_rr_gap_control.obj" /link d3d12.lib dxgi.lib
