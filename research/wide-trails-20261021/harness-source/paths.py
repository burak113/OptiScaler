"""Fixed locations used by RR Lab."""
from pathlib import Path

LAB = Path('E:/FSRD/rrlab')
GAME_TRACE = Path('F:/Ultra Yedek 2/overwrite/bin/x64/GAME_TRACE')
CACHE = LAB / 'cache'
REPORTS = LAB / 'reports'
TMP = Path('F:/FSRD/tmp/rrlab')   # per-run input staging (~0.5 GB, deleted after each run): keep it on the NVMe SSD
PATCHES = LAB / 'patches'
RUNNER = LAB / 'runner' / 'rrlab_runner.exe'
LOADER_DLL = LAB / 'runner' / 'bin' / 'amd_fidelityfx_loader_dx12.dll'
DENOISER_DLL = LAB / 'runner' / 'bin' / 'amd_fidelityfx_denoiser_dx12.dll'
DENOISER_SHA256 = '48f1e5888ba6a0a3d59a98b9751e37c392b0f7b8c223d0082d5c1f40642879d3'
SHADER_INVENTORY = Path('F:/FSRD/amd_rr_reverse_20261018/shader_inventory.json')
GPU_LOCK_DIR = Path('F:/FSRD/sol_batch')
CACHE_LIMIT_GB = 40.0

for p in (CACHE, REPORTS, TMP, PATCHES):
    p.mkdir(parents=True, exist_ok=True)
