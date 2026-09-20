# FSRD development checkpoint validation

This checkpoint preserves the V11 image algorithm. It is an experimental development
baseline, not a game-quality or performance acceptance result. The test runner executes
the production DXIL on D3D12; synthetic RR estimates replace the AMD model.

## Prerequisites

- Windows x64, a D3D12 adapter supporting shader model 6.2 and native 16-bit shader operations.
  The checkpoint was tested on an RX 9070.
- Visual Studio 2022 C++ tools (v143) and a Windows 10/11 SDK. Tested MSVC tools:
  `14.44.35207`; SDK `10.0.26100.0`; DXC `1.8.2502.11 (239921522)`.
- Windows Graphics Tools / D3D12 debug layer. Validation fails if the GPU runner cannot enable it.
- Python 3.12 and the pinned NumPy requirement below.
- The repository's pinned submodules. Libraries already tracked by this repository are
  used directly. No old Floor DLLs, ignored SDK copies or local `external/fakenvapi` file
  should be copied into a fresh checkout.

From a new checkout, in PowerShell:

```powershell
git submodule update --init --recursive
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r OptiScaler/shaders/shader_tools/tests/requirements.txt
.venv/Scripts/python.exe OptiScaler/shaders/shader_tools/validate_fsrd.py --build
```

Keep the checkout and output on the intended build drive. The validation entry point
places compiler temporary files under its output directory. Build paths without spaces
are recommended because the existing solution's packaging commands are not all quoted.

The entry point discovers Visual Studio through `vswhere` with the x64 C++ component
requirement. DXC resolution is explicit `--dxc`, `FSRD_DXC`, PATH, then the newest installed
SDK. Optional overrides: `FSRD_VS_ROOT`, `--msbuild` / `FSRD_MSBUILD`.
To reproduce the checked-in artifacts, select the tested SDK's DXC if several are installed.

## What the command verifies

1. C++/HLSL constant layouts, flag values, resource ordering and descriptor counts.
2. All four production shaders rebuild with the existing `cs_6_2`, native 16-bit, `-O3`
   flags. Both the CSO and generated header must match their pre-build hashes. A mismatch
   fails validation instead of silently blessing a different compiler/source combination.
3. Current-only GPU contracts: constant/HDR/black fields, fireflies and sparse rays,
   thin lettering, colour structure, animated/stale-RR fixtures, surface boundaries,
   volume survival, actual Floor/conversion/Skip routing, detail/Floor controls, subrects
   and odd extents. Anchor and Correlation Mix effects remain mandatory tests.
4. Real SimpleIni save/reload of the retired/new/unrelated keys, and reference-package
   integrity handling (missing, partial, wrong shader, wrong source layout).
5. With `--build`, Release x64 and inclusion of all four tested shader byte arrays in the DLL.

Logs and machine-readable `summary.json` go to a new timestamped directory under
`tools_tmp/fsrd_validation/`. Use `--output F:/some/new/directory` to choose another location.
Existing nonempty output directories are rejected to prevent stale results being counted.
The summary records compiler versions, adapter, hashes, assertion/dispatch counts,
failures and skipped historical comparisons. A failure returns a nonzero exit status.

The full solution's existing post-build packaging places the DLL at
`x64/Release/a/OptiScaler.dll`. Its timestamp/commit resource means DLL hashes are not
expected to match across builds. Shader hashes are expected to match.

To intentionally regenerate shaders after a reviewed image-code change:

```powershell
python OptiScaler/shaders/shader_tools/build_fsrd_shader.py all
python OptiScaler/shaders/shader_tools/validate_fsrd.py --build
```

Commit source, generated CSO and generated headers together. A compiler change also
requires reviewing regenerated artifacts; it must not silently alter a checkpoint.

## Optional historical A/B

No script implicitly searches `tools_tmp` for old binaries. The former development
archives are optional local data, not dependencies of current correctness tests.
The historical comparisons are retained for reproducible research:

- `baseline`: original Floor handover / rank comparisons.
- `spatial_v2`, `spatial_v3`, `zero_rough_v7`: sparse-ray diagnosis measurements.
- `zero_rough_v8`: patch/Anchor/Mix improvement comparisons.
- `zero_rough_v9`: small coloured screens versus the user-accepted V9.
- `zero_rough_v10`: joint colour Anchor comparisons.
- `spatial_v1`: optional synthetic benchmark only.

Supply a directory containing `<version>/precompile/`. Each package needs the four
HLSL sources and four corresponding CSOs; `tests/reference_hashes.json` pins their SHA-256
hashes, including the sources used to construct the old constant buffers. No DLL is needed.
These private development snapshots have no automatic download location. Never substitute
current shaders for a missing baseline or overwrite the manifest to make a mismatch pass.

```powershell
python OptiScaler/shaders/shader_tools/validate_fsrd.py --references F:/FloorReferences --require-references
```

Without references, the V9/V10 relative-quality suites are **SKIPPED**. Their independent
HDR/material/routing/palette-boundary contracts also live in the mandatory current-only
suite. The mixed volume, patch and sparse-ray suites still run current correctness checks;
only their historical comparisons are skipped. Skips are not counted as passes.
`--require-references` turns any such skip into a validation failure. A present package with
missing or altered files always fails, with or without that flag.

Individual test scripts and `benchmark_fsrd_gpu.py` accept `FSRD_REFERENCE_ROOT` and
`FSRD_GPU_TEST_OUTPUT` environment variables. The main entry point uses only its explicit
`--references` argument, clearing inherited reference selection for archive-free runs.
The benchmark reports synthetic stage times and does not execute AMD RR. It is not part
of the mandatory suite or evidence that the in-game performance budget passed.

## Scope of the evidence

Synthetic results cannot certify animated content motion, ghosting, halo behaviour,
volumetric appearance or the title's runtime resource/barrier integration. A clean clone
proves that the checkpoint builds and its executable tests need no hidden local archive.
007 First Light and Cyberpunk 2077 game acceptance remains the user's separate test step.
No custom temporal history is introduced in this checkpoint.

## Checkpoint verification performed — 20 September 2026

- A/B run with the pinned historical packages: **257 GPU assertions, 727 production
  shader dispatches**, plus INI and reference-integrity checks; passed.
- Separate checkout on F:, using only the staged checkpoint and the pinned Git
  submodule revisions, with no old build archives: **188 GPU assertions, 481 dispatches**,
  plus INI and reference-integrity checks; passed. Historical comparisons were explicitly
  skipped. No untracked `external/fakenvapi` or ignored SDK tree was copied.
- All four shaders rebuilt byte-identically to V11. D3D12 debug validation was enabled
  on the RX 9070 for both runs. Generated headers also matched after applying the committed
  LF rule; the initial patch application had exposed a Windows line-ending mismatch.
- Release x64 succeeded in the separate checkout, and its DLL contained all four validated
  shader blobs. Existing C4244/C4250/C4744/LNK4098 warnings remain. The solution also has an
  existing post-build FidelityFX v1 license-copy destination mismatch (`a/OptiScaler/Licenses`
  versus the created `a/Licenses`); distribution-package completeness is not certified by
  this DLL build. This belongs to the release packaging gate.

These counts include the additional current-only colour contracts introduced while making
the tests portable. They do not represent new image-algorithm changes or additional game
quality evidence. Build archives and full logs remain local under ignored `tools_tmp` paths.
