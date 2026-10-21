# Independent mechanical and evidence review

## Disposition

**Retain the implementation as default-off research infrastructure. The colour
algorithm remains rejected.** This review found and helped close a source-role
alias hazard; it does not turn source inspection or portable tests into a
Windows build, GPU run, native routing proof, or image-quality acceptance.

The frozen base is `5fe436dd9a21cb9cc69dec371521a055c9af049d`
(`astra-audit-20261020`). Review covered the actual
`FSRDNrdBridgeRR_Dx12.cpp` prepare/provider/restore/recovery/commit route,
`FSRDRadianceScale.hlsl`, original jobs02/03/05 and the local audit/GPU receipts,
the new native class/shader/contracts, the unapplied host patch, and the quality
metrology and results. Old candidate/evidence files were read without editing.

## Concrete review findings and resolution

| Finding | Consequence | Disposition |
|---|---|---|
| Raw and selected may legitimately be the same texture when recovery does not replace raw RR. | Rejecting every read alias would make the normal ON route vacuous; duplicate transitions would be invalid. | Allow raw/selected alias and deduplicate transitions. The direct harness contains this case. |
| A pre-provider source snapshot cannot alias raw or selected, which provider/selection commands write after `Prepare`. It also cannot alias the converted S/D textures scaled in place. | Such an alias silently changes the source from original physical input into a later observation before `Record` reads it. | Native `Prepare` rejects source/raw and source/selected aliases. Host adapter additionally excludes both converted, raw and selected lobe pairs. Direct harness has two negative source-alias cases. |
| A texture copy initializes texel bytes, not the whole placed footprint. | Last-row padding, prefix and suffix bytes could be undefined despite correct visible pixels. | The class allocates the full pitched span and explicitly uploads `0xCD` across each staging buffer; it copies the complete selected buffer into output. Direct harness reads the entire packed output, including guards. |
| CPU doubles may be finite while their uploaded float32 constants become zero, subnormal or infinite. | Division by zero/overflow can occur despite an apparently valid high-level Config. | Validate actual float32 constants and squared divisors before any allocation/dispatch; portable/native tests include these cases. |
| The existing shared radiance-scale shader clamps multiplied RGB at 65504. | Power-of-two scaling does not prove a lossless round trip over every finite half value or preservation of pre-provider source words. | The pass does no scaling; it requires an original physical snapshot. The separate exhaustive arithmetic test below records the precise unsaturated boundary. |
| Authority and support cannot be inferred from native alpha or raw/selected equality. | Opaque hit-distance/alpha bits or coincidental equality would become fabricated selection/support authority. | Host evidence is explicit and versioned; only exact mask code 1 is admitted. Reserved codes and missing evidence abstain. No production certificate producer is delivered. |
| A no-leak matched-dose subset can exclude the very cases that fail. | Reporting narrow support as universally safe from its 0/96 result would be misleading. | The quality report keeps all 144 full-dose cases, all 48 smallest-gap failures and unmatched cases, and discloses paired intersections. No variant is promoted. |

The original optional source-alias allowance was corrected before delivery.
Source equality as a physical measurement is different from equality of
resource pointers across a staged write lifetime. The current C++ source keeps
the latter distinction explicit.

## Native host and ownership checks

The new class allocates its private resources, descriptors, root signature, PSO,
constant upload and budget reservation during `Prepare`. `Record` uses fixed
arrays and retained objects; no new resource allocation or fallible device call
is added after provider dispatch. The class requires serialized caller access,
as does the native command list. Its recording ID is a caller-supplied contract;
the host adapter additionally checks the actual tracked recording object.

The host patch prepares both lobes before retaining the dispatch lease and
publishes the new selected pair only after provider restoration, recovery and
flat-selection recording. It changes both selected pointers and commit SRVs in
the actual **specular then diffuse** descriptor order. Raw output remains the
canonical raw slot. Preparation/recording failure leaves original selection
published. The patch is supplied for job11, not applied to production files.

Each prepared recording owns input COM references **and** producer/pool owners,
its own descriptor heaps and constant upload, output resources and budget charge.
It must stay retained until the exact GPU recording completes. The direct
smoke harness keeps a second owner reference across submission and verifies
that budget retirement waits for its release after the fence.

The external observation producer has an additional independent obligation:
source/sidecar copies may already have been recorded before colour `Prepare`.
Their lifetime must be admitted by the producer itself even if this optional
colour request is rejected or disabled. Keeping those owners only in a transient
`BridgeRequest` does not establish that lifetime. This is part of the job11
producer/integration acceptance gate.

The final source review also checked the added upload GPU-address checks
(nonzero base, checked offset addition and 256-byte CBV alignment), rejection
when live and peak budget counters alias, and `Decision::Off` initialization
for empty public output snapshots. The direct harness includes the budget
alias rejection and both mutable-source alias cases. These are source review
and delivered tests; their Windows execution remains pending below.

## Fresh exhaustive scale-domain evidence

Executed here:

```sh
python -B research/astra20261020/integration_round2/10-native-colour/review/check_scale_domain.py --output research/astra20261020/integration_round2/10-native-colour/review/evidence/scale_domain.json
```

The independent arithmetic/storage model tests every nonnegative finite half
word plus negative zero: **31,745 words per lobe**. It applies the actual frozen
shader's multiply-and-clamp operation followed by the inverse factor.

| Scale | Exact round-trip words, including both zeros | Saturated words that do not round trip | Largest exact positive input | First failing positive input |
|---|---:|---:|---:|---:|
| D16 | 27,649 | 4,096 | 4094 | 4096 |
| S256 | 23,553 | 8,192 | 255.875 | 256 |

All unsaturated words round trip in this CPU storage model. The deliberately
wrong claim that all finite inputs do so is rejected; swapped per-lobe inverse
factors are also rejected. These results are saved with script and frozen-shader
hashes in [scale_domain.json](evidence/scale_domain.json).

This is **not** a fresh native GPU scaling-path test. It does not prove typed
FP16 alpha NaN-payload preservation or final provider behavior. The new pass
preserves opaque alpha through integer-word packing; that is a separate
contract and has separate CPU/GPU tests.

## Actual-class Windows test delivered, execution pending

[native_pass_smoke.cpp](native_pass_smoke.cpp) includes and calls the actual
new native class. It is separate from the root's generic shader-chain replay.
The harness requires the D3D12 debug layer and makes failures fatal. It supplies:

- 22 native admission/rejection cases, including default OFF, strength zero,
  missing research acknowledgement, NaN/subnormal Config, reset/resize,
  unknown authority/support, stale provenance, source aliasing, missing graph
  owners, invalid format/state, conflicting alias states, aliased budget
  counters and shared-budget rejection.
- Two non-vacuous active cases: log with separate selected output and linear
  with raw/selected sharing a resource.
- Unequal source/raw/selected/guide allocations, active 13×9 inside larger
  allocations. The separate-selected case uses source 35×14, raw 19×13 and
  selected 69×12 and asserts actual native pitches of 512/256/768 bytes;
  unequal widths that all rounded to 256 bytes would not test pitch binding.
  Every admitted active pixel in the constant-chroma fixture must change, so
  correcting only the first row cannot hide a misbound input pitch.
  Inputs carry original alpha NaN payloads and signed zero, RGB one-ULP and
  alpha-only selection differences, invalid source/raw/depth samples and
  reserved authority/support values.
- Full packed-buffer readback: output padding, prefix/suffix, inactive texels,
  protected pixels and all alpha bytes must equal the known prefill/selected
  bytes. The owned texture must match that complete packed image.
- Input readback from each declared restored resource state, byte immutability,
  inactive diagnostic initialization, wrong/repeated recording rejection,
  reuse-of-live-Prepared rejection and exact retained budget charge/retirement.

`run_native_smoke.py` uses the repository's Windows DXC/MSVC discovery and the
existing local `gpu_lock.py` provider. It captures commands, hashes, logs and
actual execution status. It refuses to run native GPU work without that lock.

From repository root, on the Windows machine with the existing local lock:

```powershell
python -B research/astra20261020/integration_round2/10-native-colour/review/run_native_smoke.py --output F:/FSRD/tmp/astra10-direct --gpu-lock-root F:/FSRD/sol_batch
```

For compilation without GPU execution, add `--compile-only` and omit the lock
argument. Optional `--warp` selects the software adapter and cannot be used as
hardware performance evidence. The original GPU recipe still needs its normal
hardware run and separate shader/CPU parity check.

Here the runner returned **exit 2** with
`status=pending_windows_d3d12_msvc_dxc`; see
[the pending receipt](evidence/windows_pending/execution.json). Neither MSVC nor
D3D12 ran in this Linux environment. The harness is source for a concrete local
acceptance test, not a passed Windows test receipt.

## Quality review boundary

The quality experiments reproduce the unchanged candidate's actual diffuse
step rejection and all 32 original low-contrast counterexamples. They run the
**frozen Python algorithm** and causal ablations, not the new HLSL class or a
production native-support producer. The new shader's additional donor
authority/support admission is tested separately by the packed model.

The response experiment distinguishes a stateless amplitude reduction from
temporal lag. Removing the sample prior increases full achieved correction;
attenuating it back to the original response produces the same interior half
words in the reported case. Therefore that apparent step fix is not credited
as a new estimator at equal dose.

The 144-case boundary sweep does not count material/illumination labels as
independent numeric cases. Narrow support has 0/96 leaks only on the common
matched-dose subset at gaps 0.06/0.12; its 48 gap-0.02 cases still leak at full
output and the specified matching procedure does not reach the fixed
0.8±0.003 target after half storage. For example,
a diffuse case has full dose 0.910136 but its closest found stored dose is
0.792970. These are disclosed quantization exclusions, not successful low-dose
outputs. Full-dose rejection remains decisive.

The noise summary discloses paired seed counts and unmatched seeds and does
not pool the two dependent lobe scales as independent samples. The bootstrap
is uncertainty for the declared seeded experiments, not a guarantee over
games. Truth is used for evaluation-only scalar dose matching; it is never an
input to the candidate's runtime support.

## Remaining gates

Before calling this native integration validated, compile the current class
and shader on Windows, run both the direct-class and shader-chain tests on the
target GPU with debug validation, inject allocation/descriptor/device failures,
exercise reset/resize with multiple live recordings and fenced ownership,
validate the actual source/authority/support producer and host S/D pointer/SRV
publication, separately verify the real D16/S256 route, replay fresh unlooped
native captures, and measure complete allocation/residency and timing.

Before any visual adoption, a candidate must also survive the unchanged
quality gates, blind boundaries at equal achieved correction, real lighting
changes and thin/glint detail, then same-crop game observation. None of the
current rejected variants is approved by this review.
