@call "F:\VisualStudio\VC\Auxiliary\Build\vcvars64.bat" >nul
@if errorlevel 1 exit /b %errorlevel%
@cl /nologo /std:c++20 /EHsc /O2 "F:\OptiRevelations\OptiScaler-ffxD-alpha\OptiScaler\shaders\shader_tools\tests\fsrd_gpu_runner.cpp" /Fe:"F:\OptiRevelations\OptiScaler-ffxD-alpha\tools_tmp\rotating_camera_gpu_capture_20260930\evidence\fsrd_gpu_runner.exe" /Fo:"F:\OptiRevelations\OptiScaler-ffxD-alpha\tools_tmp\rotating_camera_gpu_capture_20260930\evidence\fsrd_gpu_runner.obj" /link d3d12.lib dxgi.lib
