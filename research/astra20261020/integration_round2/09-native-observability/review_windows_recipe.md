# Windows recorder fixture recipe and execution boundary

`review_run_capture_gpu.py` derives a new fixture under job09 from the existing
`test_fsrd_nrd_game_trace_bridge.py` source-preparation entry point. It preserves
the existing WARP Host and owned resources, then appends
`review_capture_gpu.cpp` in place of the old `main`. It does not edit or weaken
the original fixture.

## Current evidence

The following was executed on Linux with exit 0:

```text
python research/astra20261020/integration_round2/09-native-observability/review_run_capture_gpu.py --output /tmp/astra09_gpu_prepare --prepare-only
```

It creates `prepared-source-manifest.json`, generated C++ and stubs, and
`review-capture-execution.json`. Its status is
`SOURCE_PREPARED_NATIVE_PENDING`, with compiler, native, SDK, scale round trip,
and quality acceptance all false. It is not a Windows compilation or WARP run.

## Existing machine-wide serialization wrapper

The repository references the machine-local wrapper
`F:/FSRD/sol_batch/lead_ops/run_task_test.py`. Its documented interface uses
`--task`, `--name`, and `--script`; native GPU tests omit `--cpu`. This interface
is present in `OptiScaler/shaders/shader_tools/tests/test_fsrd_postflick_order.py`
and historical command arrays in `research/astra20261020/evidence/tests.json`.
The historical index records a 1750-byte wrapper with SHA-256
`f3a6ad7389965e219f578c1210bc82223e33fa77f7db91a5f26c05dc1088e42d`.
That is historical provenance, not a current verification of the local wrapper.

Neither that wrapper nor `gpu_lock.py` is included in this checkout or Linux
workspace. An operator on the existing Windows test host must verify that the
wrapper is installed and still owns the shared GPU/build lock. No replacement
lock name or unverified wrapper argument is invented here.

From a PowerShell session whose current directory is the OptiScaler checkout,
use the documented wrapper interface:

```powershell
$reviewScript = Join-Path (Get-Location) 'research/astra20261020/integration_round2/09-native-observability/review_run_capture_gpu.py'
python F:/FSRD/sol_batch/lead_ops/run_task_test.py --task 09-native-observability --name native_observation_capture --script $reviewScript
```

The wrapper supplies `FSRD_GPU_TEST_OUTPUT`; the new runner uses it as its
output directory. It requires Windows and the wrapper-provided environment
before attempting a native run. Setting this variable alone is not proof that
the lock is held. MSVC x64 C++ tools and the Windows SDK/D3D12 debug layer are
required by the reused fixture. The runner disables compiler caching for an
unambiguous build receipt, records compiler/native stdout, stderr, exit codes,
and executable/source hashes, then invokes the offline reader on both actual
published capture folders.

## What a future passing run establishes

The real production `FSRDGameTraceSession` implementation, readback copies,
submission-fence protection, Map and immutable publication execute on WARP.
The new fixture checks:

- OFF returns before allocation or native resource access.
- Original physical words are copied early, before a later synthetic overwrite
  of the same input resource. Half alpha canaries include NaN payloads, signed
  zero and a subnormal; the check compares original integer words.
- A nonzero crop `(7,1)` of `128x128` comes from an odd `137x131` allocation.
  Tight payload layout, copy footprint and the unknown native tiled pitch are
  recorded separately.
- Same-time source/effective aliases share their early image; adoption reuses
  the same Frame/ticket and charges each committed readback once.
- Equal words under the raw path have raw authority. Equal words under a
  protected recovery selection have no raw authority. Neither becomes editable
  while geometric support is unavailable.
- A stale reset epoch prevents early-frame adoption/publication.
- Both real published folders pass `observation_capture_reader.validate_capture`
  as well as the independent physical-word canary checks.

The provider outputs, host selection paths and D16/S256 scale metadata are
explicit controlled adapters. No AMD SDK dispatch, actual scale round trip,
native title hook, original title geometry/origin, or image-quality oracle is
exercised. A future passing result must retain those limits. Actual provider
dispatch/scale, game-state restoration, active anchor/flat paths, resize,
device loss, queue-signal failure and game image judgement remain separate
acceptance gates.
