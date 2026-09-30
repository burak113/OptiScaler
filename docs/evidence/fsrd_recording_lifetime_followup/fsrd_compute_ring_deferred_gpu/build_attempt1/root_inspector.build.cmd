@call "F:\VisualStudio\VC\Auxiliary\Build\vcvars64.bat" >nul
@if errorlevel 1 exit /b %errorlevel%
@cl /nologo /std:c++20 /EHsc /O2 "F:\OptiRevelations\OptiScaler-ffxD-alpha\tools_tmp\fsrd_compute_ring_deferred_gpu_20260930\root_inspector.cpp" /Fe:"F:\OptiRevelations\OptiScaler-ffxD-alpha\tools_tmp\fsrd_compute_ring_deferred_gpu_20260930\root_inspector.exe" /Fo:"F:\OptiRevelations\OptiScaler-ffxD-alpha\tools_tmp\fsrd_compute_ring_deferred_gpu_20260930\root_inspector.obj" /link d3d12.lib
