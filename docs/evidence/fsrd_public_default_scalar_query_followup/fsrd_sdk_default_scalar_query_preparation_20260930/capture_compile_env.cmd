@call "F:\VisualStudio\VC\Auxiliary\Build\vcvars64.bat" >nul
@if errorlevel 1 exit /b %errorlevel%
@"F:\OptiRevelations\OptiScaler\tools_tmp\albedo_stage1_venv\Scripts\python.exe" -B "F:\OptiRevelations\OptiScaler-ffxD-alpha\tools_tmp\fsrd_sdk_default_scalar_query_preparation_20260930\capture_compile_env.py"
