@call "F:\VisualStudio\VC\Auxiliary\Build\vcvars64.bat" >nul
@if errorlevel 1 exit /b %errorlevel%
@cl /nologo /std:c++20 /EHsc /O2 "F:\OptiRevelations\OptiScaler-ffxD-alpha\tools_tmp\gpu_based_validation_20260930\evidence\gpu_validation_runner.cpp" /Fe:"F:\OptiRevelations\OptiScaler-ffxD-alpha\tools_tmp\gpu_based_validation_20260930\evidence\gpu_validation_runner.exe" /Fo:"F:\OptiRevelations\OptiScaler-ffxD-alpha\tools_tmp\gpu_based_validation_20260930\evidence\gpu_validation_runner.obj" /link d3d12.lib dxgi.lib
