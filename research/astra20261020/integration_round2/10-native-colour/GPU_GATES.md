# Local commands and remaining native acceptance gates

Current status: **CPU mechanics pass; all studied colour variants rejected;
Windows compilation, GPU execution and game acceptance pending.** The historical
RX9070 five-case packing receipt is not a receipt for these sources.

## Reproduce current CPU evidence

From the repository root, in the repository's Python/NumPy environment:

```sh
python -B research/astra20261020/audit_round2/run_cpu.py --output /tmp/astra10-frozen-cpu
python -B research/astra20261020/integration_round2/10-native-colour/run_checks.py --output /tmp/astra10-checks
python -B research/astra20261020/integration_round2/10-native-colour/quality/run_quality.py --output /tmp/astra10-quality --quality-gate
```

The first two commands return 0 when their mechanical checks pass. The last
returns **1 for the expected, explicitly recorded quality rejection**, with
`mechanical_experiment_execution_pass=true`, `quality_accepted=false` and an
`execution.json`. A crash or missing receipt is not that expected verdict.
`run_checks.py` verifies the delivered fresh frozen/quality receipts and hashes;
it does not claim to rerun them unless `--with-frozen --with-quality` is supplied.

Regenerate the supplied deterministic input/CPU-expected archive:

```sh
python -B research/astra20261020/integration_round2/10-native-colour/portable/package_fixtures.py --output /tmp/native-fixtures.zip --manifest /tmp/native-fixtures-manifest.json
```

The archive uses fixed ZIP timestamps/modes and no compression. The manifest
binds every file. The 15 cases include log D16, log S256, linear D16, OFF,
unacknowledged, zero strength, reset/resize, unknown global authority/support,
wrong source stage, stale recording, invalid samples, signed depth and unknown
per-pixel sidecars. Active extent is 13×9; source/raw/selected allocations are
19×13, 17×11, 23×15, with independent pitches/offsets and larger guide allocations.
The expected outputs are CPU model results, not fabricated GPU readbacks.

## Two independent Windows paths

Use the repository's existing Windows toolchain setup and its existing shared
`gpu_lock.py` provider. Set `$env:FSRD_GPU_LOCK_ROOT` to the directory containing
that provider, or pass `--gpu-lock-root <existing-directory>`. These runners
require it for execution and do not create a private bypass lock.

First compile the actual new shader and generic packed transport harness:

```powershell
python -B research/astra20261020/integration_round2/10-native-colour/portable/gpu_shader.py --output F:/FSRD/tmp/astra10-shader-build --compile-only
python -B research/astra20261020/integration_round2/10-native-colour/review/run_native_smoke.py --output F:/FSRD/tmp/astra10-class-build --compile-only
```

Then execute each distinct path under the debug layer:

```powershell
python -B research/astra20261020/integration_round2/10-native-colour/portable/gpu_shader.py --output F:/FSRD/tmp/astra10-shader --gpu-lock-root $env:FSRD_GPU_LOCK_ROOT
python -B research/astra20261020/integration_round2/10-native-colour/review/run_native_smoke.py --output F:/FSRD/tmp/astra10-class --gpu-lock-root $env:FSRD_GPU_LOCK_ROOT
```

The shader path dispatches the delivered HLSL through the existing chain runner
and checks full packed buffers against the independent CPU invariants. Host
rejection fixtures deliberately dispatch with `Control.x=0` **only to test the
shader's defensive copy behavior**; this is not evidence of host OFF dispatch.
Protected/invalid/alpha/padding words are exact; eligible finite RGB has a maximum
one-half-ULP tolerance, and ON fixtures must change RGB. Eligibility/support
diagnostics and zero debug-layer warnings/errors are required.
The last two diagnostic channels (confidence/effective sample count) are retained
in readback, but this runner does not assert their numerical agreement. Their
measured CPU/GPU parity is an additional numerical acceptance check; it is not
implied by the exact first-two-channel masks.

The direct-class path includes the actual `NativeColourPass_Dx12.cpp` in a unity
test translation unit and invokes `Prepare/CanRecord/Record`. Do not link that
implementation a second time. It supplies 22 rejection cases and two active
cases, full allocation readback/canaries, immutable input bytes, alpha payloads,
raw==selected, recording identity and retained budget ownership. It is not a
mock implementation of the class. `--warp` is a separate software-adapter smoke
option, never a substitute for target-adapter evidence. Neither Windows command
has been compiled or executed in the current Linux environment; Linux returns
2 with an honest pending receipt.

DXC flags are `-T cs_6_2 -E CSMain -HV 2021 -Ges -Gis -O3`, with no native-16-bit
arithmetic switch. Save the current shader/DXIL/compiler/harness hashes, adapter
and driver, debug counters, complete input/output bytes and command logs. A
strict compile failure or a half-ULP failure requires investigation, not a
relaxed gate or reusing the historical CSO.

## Acceptance sequence after these mechanical runs

| Gate | Required evidence | Current status |
|---|---|---|
| Native compiler | Fresh MSVC build of actual class and combined job09+10 host; strict DXC build of current HLSL | Pending |
| Shader transport | All 15 fixtures; complete allocations/padding, alpha, reserved codes, invalid samples, nonvacuous ON, debug layer clean | Supplied, unexecuted |
| Actual class | Both active cases and 22 rejects; byte/state/owner/budget checks; actual class receives no commands/allocations for OFF and invalid admission | Supplied, unexecuted |
| Fault/lifetime | Inject each allocation/PSO/descriptor/map/retention failure; delayed and multiple submissions, repeated execution, stale generation, reset/resize and pool pressure; retain/release exact owners | Pending; supplied smoke covers a subset |
| Physical native route | Distinct pre-provider source, canonical raw and final selected; prove actual D16/S256 inputs/restoration/alpha, including saturation and signed-zero cases | CPU numeric domain only |
| Producer contract | Real source-copy owner retained even on request rejection; real authority/support evidence covers complete donor footprint and exact frame/crop/version | No production producer |
| Host publication | Same recording/generation/identity, pair-atomic selected pointers plus S,D commit SRVs, protected selection survives every fallback | Unapplied proposal only |
| Captured quality | Blind native captures with independent truth, equal achieved dose, frozen masks; low-contrast material/light boundaries, tails, correlated errors, glints, true steps, thin detail and moving crop | Synthetic inherited-model variants rejected |
| Memory/time | Full native graph and retained recordings, real allocation breakdown, driver/descriptor overhead, GPU timing under shared test policy | Logical/resource budget only |
| Game observation | Fresh native replay and final game behavior under unchanged quality thresholds, with traceable capture/config/device evidence | Pending |

The half-word scale model is deliberately separate from shader transport. It
shows D16 exact through half value 4094, failing first at 4096 after clipping;
S256 exact through 255.875, failing first at 256. It does not prove typed alpha
preservation, provider execution or the native graph. These limits are why the
new pass requires a pre-provider physical snapshot instead of undoing clipping.

Mechanical acceptance alone never enables the rejected colour estimator.
Unknown support remains identity; identity is not credited as improvement.
No merge, deployment or default enablement is part of this delivery.

## D3D12 references used for the byte/state contract

- [GetCopyableFootprints](https://learn.microsoft.com/en-us/windows/win32/api/d3d12/nf-d3d12-id3d12device-getcopyablefootprints): unpadded row size and row pitch are different; validate the complete allocation.
- [CopyTextureRegion](https://learn.microsoft.com/en-us/windows/win32/api/d3d12/nf-d3d12-id3d12graphicscommandlist-copytextureregion): compatible formats, source/destination states and bounds.
- [Texture upload/readback](https://learn.microsoft.com/en-us/windows/win32/direct3d12/upload-and-readback-of-texture-data): placed footprints and copy alignment.

The implementation uses conventional 256-byte pitches and 512-byte footprint
offset alignment without depending on optional relaxed-copy features.
