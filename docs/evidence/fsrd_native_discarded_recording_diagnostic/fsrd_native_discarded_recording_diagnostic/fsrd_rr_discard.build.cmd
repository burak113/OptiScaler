@call "F:\VisualStudio\VC\Auxiliary\Build\vcvars64.bat" >nul
@if errorlevel 1 exit /b %errorlevel%
@cl /nologo /std:c++20 /EHsc /O2 "F:\OptiRevelations\OptiScaler-ffxD-alpha\tools_tmp\fsrd_native_discarded_recording_diagnostic_20260930\fsrd_rr_discard.cpp" /Fe:"F:\OptiRevelations\OptiScaler-ffxD-alpha\tools_tmp\fsrd_native_discarded_recording_diagnostic_20260930\fsrd_rr_discard.exe" /Fo:"F:\OptiRevelations\OptiScaler-ffxD-alpha\tools_tmp\fsrd_native_discarded_recording_diagnostic_20260930\fsrd_rr_discard.obj" /link d3d12.lib dxgi.lib
