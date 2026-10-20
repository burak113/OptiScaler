# Native support contract, version 1

Implementation: `OptiScaler/shaders/fsrd_preprocess/FSRDNrdSupportContract.h`.
Namespace: `NrdBridge::SupportContract`. This is a portable C++17, allocation-free
producer/consumer contract, with no filtering, D3D descriptors, shader dispatches,
pixel writes, or changes to protected defaults.

## What the native integration can certify today

The production diagnostic calls `InvalidNativeSupport(resetEpoch, frame)`.
It emits `version=1`, `valid=0`, `scope=0` and both reasons
`UnavailableDonorFootprint | UnavailableKeyCorrespondence` (numeric mask **3**).
Unknown support is not replaced by current-cell geometry, an identity gain,
raw/selected equality, a material word, or an observed frame sum.

The diagnostic may capture gain and the full 32-byte low/high/count accumulator;
those observations still omit the actual full donor/key lineage and original key
geometry. They do not enable valid support. There is no native GPU producer of a
complete certificate in this change. Any future colour/reconstruction consumer
must preserve the selected words whenever support is unknown; it must not treat
this CPU implementation's analytic fixtures as native support evidence.

## Source trace and the missing observation

At base `5fe436dd9a21cb9cc69dec371521a055c9af049d`:

- `FSRDNrdPostMotionAnchorStatsRecall.hlsl::BoxCell` uses four bilinear samples
  at cell-local `(2,2),(6,2),(2,6),(6,6)` in an 8x8 cell. These samples cover
  sixteen source texels, not all 64. Sparse measurements can miss a thin surface.
- Its recall searches physical key slices, samples both key level and positive
  absolute key depth, and emits already-recalled RGBA values. That RGBA does not
  preserve original key pixels, per-sample weights, or slot publication lineage.
- `FSRDNrdPostMotionAnchorGain.hlsl` evaluates nine taps with
  `q=clamp(p+(dx,dy)*step,0,grid-1)`, `dx,dy=-1..1`, and
  `step=int(clamp(Params2.z,1,4)+0.5)`. The protected default step is three cells.
  The weight is `recalled.y*recalled.w`. Edge-clamped duplicate taps still count.
  A pure current cell cannot certify a gain contaminated by a far donor.
- The same Gain shader reads the 16.16 low/high accumulator and a frame-count
  based **identity veto**. The support contract requires an explicit observation
  of that veto. Its geometric scope is the nonzero local correction donors; it
  does not claim that frame sums or ratios identify the cause of a change.
- `NativePostMotionAnchor::Create` uses `max(activeWidth/8,1)` and the same
  height expression. The executable native geometry uses floor division, whereas
  the older job04 CPU reconstruction reference constructs a ceil grid with
  invalid partial edge cells. This ABI describes the actual native floor grid.

These claims are source inspection. The original job04 executable models and
their immutable results remain unchanged. No Windows build or GPU execution is
implied by the trace above.

## Producer inputs

| Type / function | Required evidence |
| --- | --- |
| `Domain` | Full active render extent, original texture allocation, observed crop origin/extent, native grid origin/extent, original signed-depth convention, common geometric basis ID, reset epoch and frame. |
| `Pixel` | Original observed position, normal and signed depth in the declared basis, plus separate observed/correspondence-known flags. These flags may not come from candidate output. |
| `CertifyCell` | Exactly 64 pixels for the complete 8x8 cell, all inside the observed crop. It checks finite geometry, original depth sign, normalized normal compatibility and symmetric downstream plane compatibility. |
| `DonorTap` | Original current cell certificate, the actual observed estimator weight including explicit zeros, and the corresponding key-recall witness. Nine taps are always supplied in native loop order. |
| `RecallWitness` | Actual selected physical slot, key frame/reset epoch, matching selected/captured slot generation, original key-valid flag, submitted/completed fence values and matching timeline identity, and the actual quantized key-sampler coordinate. |
| `KeyTap` | All four bilinear taps in `(0,0),(1,0),(0,1),(1,1)` order, their exact actual binary weights, and full-cell original geometry certificates for each nonzero tap. |
| `Produce` | Recipient, exact quantized native step, all nine donor records, and separately observed global-veto state. It returns invalid support with reasons on any missing or inconsistent evidence. |

`Domain.activeWidth/Height` always means the **full active render**; it is not
the cropped file's row extent. `allocationWidth/Height` belongs to the original
texture, not a packed NPZ. `cropX/Y` and `cropWidth/Height` describe observation
coverage inside the full active rectangle. The native grid is anchored at
full-render `(0,0)`. This minimal producer rejects off-phase crop origins and
requires complete cells in the observed crop. A moving crop is never motion.
Coordinates, basis, allocation, crop and phase must agree between current and
recalled witnesses. Missing remapping evidence is not reconstructed by clamping.

The consumer distinguishes original positive and negative view-Z conventions.
Only key storage uses absolute depth. The producer never repairs a depth-sign
mismatch by applying `abs` to the original observation.

The key-sampler coordinate must contain **observed quantized fractions**.
Recomputing an ideal sampler result from UV is insufficient. All four supplied
weights must exactly match those binary fractions; deleting a tiny nonzero donor
cannot manufacture a pure certificate. Out-of-domain nonzero key taps remain
unknown even if the native hardware sampler would clamp them.

`completedFence=UINT64_MAX` is rejected as the D3D12 device-removal sentinel.
Scheduled/recorded work, zero submission fences, incomplete fences, invalidated
keys, future key frames, overwritten generations and sentinel slot 6 are invalid.
Submission and completion must refer to the same nonzero observed fence timeline;
a numerically higher value from an unrelated fence cannot publish a key.
No raw pointer or resource address is a key identity or publication proof.

## Certificate and consumer ABI

The C++ `Certificate` has these semantic fields. It is an **in-process ABI**;
never dump its compiler padding as a cross-platform wire format. Diagnostic
serialization uses named fields, with 64-bit values represented losslessly.

| Field | Meaning |
| --- | --- |
| `version` | Exactly 1. Unknown versions reject. |
| `valid` | Exactly 1 only after successful production. |
| `reasons` | `uint64_t` bit mask. Every nonzero value rejects. |
| `scope` | 0 = unknown; 1 = compatibility of local native anchor donor geometry. Never material, leaf, object, causal or converged-colour truth. |
| `policy` | Exact plane absolute/relative tolerances and normal cosine. Cell certificates, producer and consumer must use the same policy. |
| `domain` | Original full/crop/grid coordinates, signed-depth basis and frame/reset identity. |
| `step` | Actual quantized native radius spacing, 1 through 4. |
| `observedTapMask` | All nine actual estimator taps observed: `0x1ff`. |
| `nonzeroDonors` | Number of positive estimator tap contributions, including edge duplicates. |
| `nonzeroKeyDonors` | Number of positive bilinear key tap contributions. |
| `recipientX/Y` | Actual recipient cell, not a nearby cell with convenient geometry. |

`Accepts(certificate, expectedDomain, expectedStep, recipientX, recipientY,
requiredPolicy={})` validates the complete binding. A consumer may not reuse a
certificate across epochs, frames, coordinates, tolerances, radii or recipients.
The recipient's complete 8x8 cell must lie inside the observed crop even when
the certificate and expected domain have matching serialized values. Finite
source coordinates alone are insufficient: intermediate plane differences and
dot products must also be finite before any tolerance comparison.
This API is an evidence contract between components, not cryptographic protection
against a producer intentionally inventing observations. The intentionally broken
current-cell-only producer in the tests shows why such fabrication is invalid.

Reason bits are stable in version 1:

| Bit | Reason | Bit | Reason |
| --- | --- | --- | --- |
| 0 | UnavailableDonorFootprint | 10 | InvalidPolicy |
| 1 | UnavailableKeyCorrespondence | 11 | WrongFootprint |
| 2 | InvalidDomain | 12 | InvalidWeight |
| 3 | CropGridMismatch | 13 | UnpublishedKey |
| 4 | StaleEpoch | 14 | StaleKey |
| 5 | NonFinite | 15 | InvalidKeySlot |
| 6 | DepthSign | 16 | NoNonzeroDonors |
| 7 | IncompleteCell | 17 | UnobservedGlobalVeto |
| 8 | UnobservedSample | 18 | InvalidCertificate (reserved) |
| 9 | ThinOrMixedSurface | 19 | UnavailableCorrespondence |

## Scope limits and cost

Normals/depth/position cannot distinguish exactly coplanar materials or surfaces
within the chosen geometric tolerance. `scope=1` never makes that claim. Independent
correspondence/eligibility evidence is mandatory; missing evidence stays invalid.
The all-64-pixel cell test is deliberately stricter than native sparse Stats and
can reject some otherwise valid sparse measurements. It never repairs a mixed gain.

The header has zero heap allocations, zero descriptors, zero GPU copies, and zero
telemetry. `InvalidNativeSupport` only builds scalar CPU metadata. The optional
portable complete producer processes nine donor records and at most 36 key-cell
certificates. Constructing a full cell certificate inspects 64 pixels twice;
certificates can be reused for duplicate taps. Native capture costs belong to the
host capture ledger, not this helper. These are algorithmic cost counts, not GPU
timings or Windows object-size measurements.

## Reproduce the executable falsification

From repository root, with the frozen NumPy requirement and a C++17 compiler:

```text
python research/astra20261020/integration_round2/09-native-observability/support_run_checks.py --output /tmp/astra09_support
```

The runner compiles the **actual production header** with
`g++ -std=c++17 -O2 -Wall -Wextra -Werror -pedantic`, runs deterministic checks,
then runs the same checks against `--mutant-current-cell-only`. The mutant must
exit 1 with actual failed support assertions. Receipts record exact commands,
statuses, source/executable SHA-256 and runtime platform.

Three frozen native-policy NPZs are read once in original chronological order;
their original `fixed_mask` bytes and file hashes remain unchanged. They retain
cases where the gain changes despite absent own-cell recall, directly showing
why an own-cell tag is not sufficient provenance. The stored fields omit raw
keys/full geometry/publication witnesses, so they are recorded as invalid native
support; no synthetic geometry is filled in. This is CPU inspection of retained
arrays, not fresh native GPU execution or a quality result.
