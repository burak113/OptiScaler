# Job 01 — Numerical and sampling contracts

## Decision and scope

**Recommendation: keep as research.** This bundle supplies a reusable, tested
NumPy contract for jobs 02–04 and 08, fixed-population CPU calibration, exact
counter arithmetic, explicit uncertainty, and one narrowly scoped finite-depth
adapter. The adapter is proposed for default-off local A/B after actual DXC and
GPU acceptance. It is not applied to production here.

The most useful positive result is an identified output-store mechanism:
applying RTZ at the actual, previously unrounded Anchor Gain store reduces
77,036 combined calibration differences to **17**, and 3,675 native differences
to **0**. The remaining 17 cells are a useful negative result: final-store
rounding alone does not explain the complete recorded GPU output. Separately,
an independently verified cross-fixture overlap recovers real missing low bits
and removes all 13 colour output differences on its fixed observed rectangle.
[Calibration evidence](evidence/calibration.json) and
[independent review](evidence/INDEPENDENT_REVIEW.md).

This work executed CPU code only. Historical GPU grid fields calibrate numerical
models; they are not newly executed shaders. No AMD RR, game observation,
converged ground truth, fresh compiled bytecode, GPU timing or visual-quality
gain was produced. Grain, sparkles and flicker receive no invented score. An
output tolerance is never used to hide a changed branch or missing observation.

## Identity, authority and independent work

The immutable starting tag is `astra-handoff-20261020`, resolving to commit
`5d7839a930106cf8fe1ba8dbbc6750509e7f26a8`. The separately audited production
baseline is `87e8b7ab2a428bd91d3c044decf7d4dbccd8cefd`. The task branch is
`astra/01-numerical-contract`, with PR target `sol/26-integration`. The exact
tested implementation revision, file identities and final executor receipts are
recorded in [RESULT.json](RESULT.json) and [API_MANIFEST.json](API_MANIFEST.json).

The prompt, entry document, common/return protocols, data/finding documents,
portable references and fixture manifests were read before modeling. Source
inspection covered Colour Stats/Track/Apply; combined and native Anchor
StatsRecall/Gain; Anchor Apply; constants; shared sanitization/normal helpers;
host allocations, dispatch and reset; the shader builder and artifact contract.
[source_inventory.json](evidence/source_inventory.json) records actual tag
source/CSO/header/compiler hashes. All eight inspected embedded shader payloads
match their CSOs. Historical build hashes were not substituted.

Three agents had distinct boundaries. The representation owner implemented
storage, arithmetic, encoding, counters and the Gain-store intervention. The
sampling owner implemented coordinate/support/sampler contracts and reviewed
the finite-depth adapter. The independent skeptic first reproduced bad controls
without seeing the candidate claim, then challenged the implementation and
calibration. Its corrections materially strengthened the missing-data witness
and recovered previously overlooked observations.
[Precommitment](evidence/ADVERSARY_PRECOMMITMENT.md),
[representation record](evidence/REPRESENTATION.md), and
[sampling record](evidence/SAMPLING.md) retain their evidence boundaries.

## Data that actually exists

The initial unmodified package check passed **91 frozen file hashes and 141 safe
NPZ arrays**. Its four CPU suites passed before implementation. The outer CPU
runner took **5.180 s** in that initial run; the validator took **0.560 s**.
These are local command wall times, not performance measurements of a denoiser.
The original output and receipt are retained in
[baseline_cpu.log](evidence/baseline_cpu.log),
[baseline_package.log](evidence/baseline_package.log), and
[baseline_runs.json](evidence/baseline_runs.json).

| Dataset | Observations and fixed population | Limits |
|---|---|---|
| Combined Anchor | 133 recorded Gain frames; 416,720 grid cells; stored Stats/Recall/Gain and exact uint32 counters | No recreation of the full upstream GPU history |
| Native Anchor | 7 recorded Gain frames; 26,256 grid cells; stored fields and fixed masks | Original pre-store 16.16 atomic buffers absent |
| Colour `soft2_gpu_87ee63` | Capture 87ee, frame 63; 512×512 ROI at render (496,167); C8 64×64 history grid; previous history CPU-warmed over frames 0–62 | Rejected historical C8 experiment, not production B4 or full GPU temporal execution |
| `bottle_track7` | Frames 180–186; 128×256 moving crop; 1505×847 original render | First frame has no previous fixture history; crop origins change each frame |
| `foliage23` | 87ee frames 43–65; 192×64 crop at (752,423) | Partial history; frame 63 supplies one verified colour overlap |
| `facade16` | f2ef frames 34–49; 96×96 crop at (688,359) | Different capture and frame sequence; cannot fill 87ee frame-63 data |
| Aligned glass subset | 87ee frames 46–63; fixed common mask 6,497 pixels | Historical full-ROI 8,048 count is separate; RGB is aligned to reference 54, not raw frame-63 RGB |

All NPZ loading uses `allow_pickle=False`. The complete dtype, shape, raw byte
hash, extrema/nonfinite inventory, capture UUID, frame/crop provenance and lobe
statistics are in [data_inventory.json](evidence/data_inventory.json). Captured
clip radiance is original little-endian FP16 RGBA with no new exposure or gain;
input alpha carries hit distance. Motion RG is previous-minus-current physical
full-render UV, and B is the corresponding linear-depth delta. Normal/roughness
is packed RGB10A2 with separate field roles. Albedo and converged same-pose truth
are absent.

The chronology is unlooped. Crop support follows the packaged baseline formula:

`q_previous_local = p_current_local + origin_current + motion_uv * original_render_extent - origin_previous`.

The first frame is unsupported for temporal evaluation. In the moving bottle
crop, supported counts on later frames range from 20,436 to 30,723 of 32,768;
movement of the observation window is not itself object/camera motion. Per-frame
fixed mask hashes and all unsupported counts are exported. This job does not
select a new temporal quality mask or treat absent off-crop pixels as clamped
observations.

## Hypotheses and discriminating experiments

Predictions were written in [HYPOTHESES.md](HYPOTHESES.md) and the agent records
before tuning. No denoising parameter was fitted.

| Mechanism | Discriminating prediction | Observed conclusion |
|---|---|---|
| H1: storage boundary | Changing only the actual store should move boundary decisions; increasing arithmetic precision without that store cannot restore it | Supported for the dominant Anchor gap and a complete mean microformula; universal store-only reconstruction rejected by 17 combined cells |
| H2: sampling precision/convention | Errors should move with subpixel phase near hard gates; constants and texel centres should remain invariant; integer Load removes filtering | CPU phase dependence demonstrated; raw historical GPU gate identities remain unavailable |
| H3: guide representation | Old normalized 16-bit payload loses information through FP16, while all audited 11-bit payloads survive | Exhaustively confirmed; audited production already uses the corrected encoding, so no redundant packing patch |
| H4: missing pre-store values | Two admissible pre-store inputs with the same export produce different output | Confirmed outside a verified known overlap; actual recovered low bits remove 13 errors within that overlap |

### 1. The actual Anchor Gain store separates most of the error

The frozen reference rounds Gain to RNE. Applying RTZ to that already rounded
output would be an invalid experiment. The new `anchor_gain_unstored` instead
reconstructs the selected source-shaped float32 expression, retaining numerator,
denominator, coverage, rejection decisions and unrounded gain, then applies one
declared output conversion. Both the source `exp` expression and inspected DXIL
`exp2` lowering are retained. Neither NumPy exponential is asserted to be the
device's transcendental implementation.

| Recorded population | Output store | Different cells | Max absolute error | p99 absolute error | Identity classification differences |
|---|---|---:|---:|---:|---:|
| Combined, 416,720 cells | RNE | 77,036 | 0.00048828125 | 0.00048828125 | 173 |
| Combined, same cells | RTZ | **17** | 0.00048828125 | **0** | **13** |
| Native, 26,256 cells | RNE | 3,675 | 0.00048828125 | 0.00048828125 | 8 |
| Native, same cells | RTZ | **0** | **0** | **0** | **0** |

Both exponential models give the displayed stored-output comparisons. All RNE
differences are above the recorded GPU result. The 17 RTZ combined residuals
are 16 above and 1 below, at most one half step. Their full coordinates, ordered
nine-tap inputs, exact combined counter words, constants, unrounded values and
recorded-value preimages are preserved in
`calibration.json.anchor.gain_store_intervention.rtz_residual_cells`.

A particularly decisive cell is 87ee frame **18**, grid **(5,27)**. Only one
neighborhood tap has positive weight; its current and recalled levels are both
**0.036468505859375**. Coverage and fallback are 1, and no rejection guard fires.
The selected CPU expression produces exactly **1**; RNE and RTZ both preserve
it. The recorded GPU value is **0.99951171875**. Thus the final store alone cannot
produce this witness. Fast division, contraction/reassociation and device
instruction accuracy remain hypotheses. Even an ordinary CPU reciprocal-times-x
check gives 1 here, so the report does not assign the residual to a proved
reciprocal mechanism. The independent reviewer reproduced this as a regression.
[Independent review](evidence/INDEPENDENT_REVIEW.md).

Native exact atomics remain unknown, but the observed Gain result is stronger
than an arbitrary central-estimate match: all seven native frames have identical
Gain and frame-rejection decisions at the endpoint combinations of **both RNE
and RTZ stored-field ratio envelopes**. The native policy uses the ratio only
for the frame-level rejection branch; that branch is stable over those bounds.
This identifies the modeled Gain observable across the declared uncertainty
without recovering the original atomic buffer.

### 2. Colour store and sampler interventions change hard decisions

The frozen `expected_stats`, `expected_history`, `expected_gain`, packed normal
and bilinear output are CPU-reference arrays. They are not raw GPU intermediate
tensors. Reproducing them is an exact reference check, not GPU parity. All five
match exactly under the frozen/source32 weighted sampler. The older
`expected_soft2` has **1,083 / 786,432** differing RGB lanes, maximum
**0.00006103515625**, p99 zero. The mismatch is preserved as a passing diagnostic
of the declared limitation.

| CPU intervention on the same 4,096 history cells | Changed validity decisions versus frozen |
|---|---:|
| Selected float32 weighted sampler, RTZ stores | 0 |
| Float64 sampler only, RTZ stores | 0 |
| Observed-profile nearest-even 1/256 fraction lattice, RTZ stores | 9 |
| RNE stores, selected float32 sampler | 6 |
| RNE stores and 1/256 fraction profile | 11 |

Only the sampler is float64 in the second row; this is not a claim about an
entire float64 Colour estimator. The historical GPU report also names nine gate
disagreements, but its raw gate map is absent. Equal counts do not establish that
these are the same nine decisions. The emitted NPZ retains every profile's
validity and sampled-history arrays, with fixed hashes and coordinates, for a
surgical local comparison. No threshold is widened to force agreement.
[Calibration](evidence/calibration.json).

A separate analytic depth plane uses the same 4,097 UV phases and texels
`[1,1.0625]` in every mode. Source float32 changes zero decisions versus ideal;
the selected fraction-8 profile changes **7**, and the nearest-sampling mutant
changes **737**. This phase-locked behavior distinguishes interpolation from an
output-only numeric error. The complete four-term mean microformula
`(1+2^-11+2^-11+2^-11)*0.25` is **0.2503662109375** in both float32 and float64
without storage, versus **0.250244140625** after RTZ. A fixed intervening
threshold changes decision. The premature-half-after-each-add mutant instead
produces **0.25**. These are analytic staging examples, not a float64 denoiser
or new GPU measurement. [Microcase evidence](evidence/gpu_microcases.json).

### 3. Encoding has a real discontinuous failure mode

Every integer code `qx*32+qy`, `qx=0..63`, `qy=0..31`, survives either FP16 store
exactly: **2,048 / 2,048** payloads pass. Byte pack/unpack closure is distinct
from geometric decode/encode closure: four south-pole codes decode to the same
normal, so re-encoding may canonicalize a direction without preserving its
original code. Fold signs, hemisphere axes and zero-vector rejection are tested.

The old normalized 16-bit control loses **58,367 / 65,536** codes with RNE and
**59,383 / 65,536** with RTZ. The same analytic 256×256 octahedral UV population
also demonstrates why a small scalar payload error is not a small guide error:

| Representation/store | Angular p50 | Angular p99 | Angular maximum | Changed self-surface `dot > 0.9` decisions |
|---|---:|---:|---:|---:|
| Audited 11-bit, either store | 1.894° | 4.638° | 5.661° | 0 |
| Old normalized 16-bit, RNE | 3.590° | 152.308° | 179.774° | 2,325 |
| Old normalized 16-bit, RTZ | 7.116° | 163.095° | 179.358° | 6,199 |

The threshold experiment perturbs one guide: it compares the original decoded
normal with its stored/redecoded version. It does not replay production
`SurfaceWeight` with both centre and tap guides traversing the encoding. The
2,325/6,199 counts are therefore synthetic comparison changes, not observed
production branch changes. The long tails result from lossy packed-code
carry/borrow into the other guide component, not merely uniform angular
quantization. These are synthetic guide metrics, not captured quality scores.
The audited production source already has
the 11-bit representation. [Encoding calibration](evidence/calibration.json)
and [tests](tests/test_encoding.py).

### 4. Missing data is partly recoverable and partly non-identifiable

The reviewer first rejected an overbroad inference from arbitrary float32 bin
endpoints: a captured pre-store sum must also be realizable by two half lobes.
The strengthened construction compares nonnegative half decompositions `(h,0)`
and `(h,delta)`, where delta is a representable half-bin half-step. Both RTZ-store
to the same tensor, yet produce **364** different JBU RGB outputs, maximum
**0.000030517578125**. The generic endpoint diagnostic changes 743 lanes but is
retained separately because it has weaker provenance constraints.

The reviewer then found actual information in `foliage23` frame 63. Its fixed
192×64 rectangle is local x=256..447, y=256..319 in the colour ROI. Capture UUID,
frame, render extent and crop mapping agree. All 36,864 rounded RR sums, all
36,864 rounded input sums, 12,288 depths and 12,288 prepared-normal words match.
The separate original-normal field differs at 23 words, demonstrating why field
roles matter. The actual raw RR D+S sum restores low bits in **28,485** lanes.

Supplying only those observed bits removes **all 13** `expected_soft2` errors
in the rectangle: **36,864 / 36,864** outputs become exact and previous maximum
error 0.00000762939453125 becomes zero. The full output changes only at those
13 channels. This is observation-backed recovery on a geometry-selected 12,288
pixel support, not a fitted tolerance or candidate-selected success subset.

The strongest remaining witness keeps those actual known values in both
candidate inputs and varies admissible half-lobe decompositions only elsewhere.
It still changes **357 / 749,568** unknown-region RGB output lanes, and **zero**
known-region outputs, while preserving the exported rounded tensor. Exact
reconstruction is explicitly rejected by `NonIdentifiableError`. The scope is
the rounded colour tensor plus the verified unwarped foliage overlap; aligned
glass RGB has not been treated as an invertible raw observation. A finite set of
agreeing outputs would not prove global identifiability. The surgical request
excludes the known 12,288 pixels and initially asks for only 16 distinguishing
pixel locations. [Recovery and witnesses](evidence/calibration.json).

## Exact native counters and conditional uncertainty

The native buffer has 32 bytes: current low/high words at 0/4, recalled at 8/12,
count at 16, and padding through 31. Each increment is the source-shaped
`uint(clamp(level,0,16)*65536)` **before** the level's FP16 store. `FrameSums`
models sequential returned-old-value carries exactly; all 32 reset bytes are
tested. A natural 262,145-cell cap-16 case produces total **274,878,955,520**, low
1,048,576 and high 64. The missing-high-word mutant loses 274,877,906,944 units.
The 57,600-cell 1440p synthetic grid and seeded adversarial increments exercise
multiple wraps, order invariance and high-word wrap separately.

For one stored half level 1, the RNE binary32 preimage spans 0.999755859375 to
1.00048828125, whose native increments range **65,520..65,568**. The RTZ
preimage spans 1 to 1.0009764432907104, giving **65,536..65,599**. These are exact
inclusive float32 endpoints, including tie parity, not arbitrary error bars.
Both endpoints reproduce the stored bits while producing different atomics.
`require_exact_totals()` therefore raises. Cap-saturated bins and empty support
can legitimately be singleton cases.

All seven native fixtures yield nonsingleton total bounds under both store
hypotheses. For example, the 22f9 frame-41 RNE ratio envelope is approximately
**0.84256256..0.84358865**. The library separately returns exact integer total
bounds and source float32 reconstructed-ratio bounds. Within the native
cap/count domain total is below 2^52 and high below 2^20; reconstruction remains
monotone across carries, permitting valid endpoint bounds. Nonfinite values
outside the fixed measurement mask are never converted into observations.
Combined Anchor's 1/1024 uint32 accumulator is kept distinct.
[Representation proof/tests](evidence/REPRESENTATION.md) and
[per-frame bounds](evidence/calibration.json).

## Sampling, arithmetic and what the API envelope does not claim

The contract distinguishes ideal mathematical interpolation, selected source
arithmetic, a named observed-device lattice and the documented API envelope.
Microsoft's [D3D11.3 functional specification](https://microsoft.github.io/DirectX-Specs/d3d/archive/D3D11_3_FunctionalSpec.htm)
describes allocation-sized normalized addressing, at least eight fractional bits
and individual tap addressing, while leaving filter arithmetic choices. The
conservative finite envelope does not assert exactly eight bits, one tie rule or
one float32 instruction order on every D3D12 device. The documented
[HLSL Load](https://learn.microsoft.com/en-us/windows/win32/direct3dhlsl/dx-graphics-hlsl-to-load)
out-of-resource zero is different from missing data inside an allocation crop.

Tests cover 1×1 and odd extents, allocation larger than active render, floor
quarter/eighth grids, every edge/corner, integer translations, exact-centre
loads, crop support and inactive padding. All 16 impulses in a Colour 4×4 cell
contribute 1/16. In an Anchor 8×8 cell only 16 selected texels contribute 1/16;
48 contribute zero. Replacing that pattern with a 64-texel box would be a policy
change, so this job only exposes the sampling distinction.

Separately rounded weighted sums reproduce the frozen sampler exactly but may
lose one float32 ULP of constant identity. The named separable lerp preserves
finite constant fields, yet opposite `FLT_MAX` values can overflow its
subtraction. The independent reviewer supplied this case; the API envelope
rejects the out-of-envelope result. Neither source expression is silently
declared the unique hardware filter implementation. Fused arithmetic uses an
exact dyadic oracle; an independent local `fmaf` cross-check matched 8,101 finite
triples, without making that system library a package dependency.

RGB `SanitizeRadiance` is per lane: nonfinite to zero, finite clamp [0,65500].
Depth, normal alpha and motion do not acquire this sanitizer by association.
Native Apply handles diffuse and specular independently with a shared gain and
finite alpha pass-through. Colour Apply's active path writes alpha 1; its
inactive authority path preserves the original. Tests poison unused OFF inputs
to make sure they cannot affect the observable. Canonical model NaNs, denormal
profiles and undefined integer conversions are disclosed, not labeled hardware
payload truth. [API](API.md) and [sampling record](evidence/SAMPLING.md).

## Scoped adapter and acceptance gates

The one proposed production correction addresses a source predicate that can
accept finite history against infinite expected depth because `Inf <= Inf` is
true. It adds `isfinite(history.a) && isfinite(expected)` before the existing
inclusive relative-depth comparison. There is no new denoising policy.
Exhaustive finite-half/probe tests plus seeded interpolated histories contain
**258,048** comparisons with **zero** changed finite-domain decisions. The
actual typed R16 Inf cases reject with the proposal; finite inclusive boundaries
remain accepted. Both finite R16 operands together cannot overflow float32, so
the GPU request does not pretend `FLT_MAX+FLT_MAX` is a reachable finite typed
input pair.

The LF patch has been checked and applied to a clean copy of the recorded
source, producing the exact supplied candidate HLSL. Production remains at the
recorded bytes. Compilation is pending: Colour uses `cs_6_2`, `CSMain`,
`-enable-16bit-types -O3 -Qstrip_debug -Qstrip_reflect`; native Anchor uses
`cs_6_6 -HV 2021`, `CSMain`, `-O3 -enable-16bit-types`. Actual bundled DXC
executable/DLL hashes are recorded, but no Windows compiler was run in Linux.
The artifact contract's **883 checks across 107 generated headers** are useful
consistency evidence with **zero fresh compiles**, not candidate code generation.
[Adapter specification](adapter/ADAPTER_SPEC.md).

## CPU acceptance, negative controls and limits

The single acceptance command is documented in [README.md](README.md). The
final run passed **125 candidate tests** (12.852 s inside unittest; 13.004 s
outer command). All **16 acceptance commands** returned their expected exit
codes; their wall times sum to **35.646 s**. The repeated frozen CPU suites took
5.323 s, and the full numerical calibration took 9.415 s. These are CPU test-run
receipts, not shader or denoising performance measurements.

The authoritative final inventory, exact command arguments, expected/actual exit
codes, elapsed times and logs are in [run_records.json](evidence/run_records.json)
and [RESULT.json](RESULT.json). An earlier authoring preflight stopped because
the report linked to the not-yet-generated run receipt. Its exit-1 log is retained
in [authoring_preflight_runs.json](evidence/authoring_preflight_runs.json). The
receipt was then available and the complete runner passed; that earlier accepted
run is preserved in [pre_metadata_fix_receipt.json](evidence/pre_metadata_fix_receipt.json).
The final runner additionally pins every command to its source revision and API
hash and uses corrected known-data request metadata. It was rerun completely at
`275d8fbe200158d653adb67a2b1ed24e614fa039`. No numerical library/test/adapter
source, threshold or tolerance changed during these receipt improvements.
The runner revalidates the frozen corpus after
candidate development. NumPy is pinned to 2.3.5; generated random seeds and
logical array hashes are recorded. Exhaustive spaces and seeded synthetic
holdouts are independent of captured error fitting; all 140 captured Gain
frames and all published colour cells are evaluated without selecting a tuned
training subset.

Five deliberately wrong models must fail: active-sized UV normalization,
nearest sampling, old normal packing, omitted high word and premature rounding.
The frozen rejected-colour `--quality-gate` must also fail. Their expected
nonzero exit codes are retained; they are not relabeled successful quality
measurements. No failed gate was rewritten as passing by increasing a tolerance.
The final independent review additionally contains 29 adversarial regressions
and a separately repeated nine-test guard review, including the new real Gain
falsifier and the actual overlap recovery.

Remaining local work is concrete. [GPU_REQUEST.json](GPU_REQUEST.json) specifies
typed inputs, input hashes, source expressions, pass bindings/order, reset,
uncertainty or expected bytes, mutants, debug/lifetime checks and capture/device
provenance. Synthetic store, phase, impulse, multiwrap and guard cases need no
game or RR execution. The existing host programs are scaffolding; the requested
diagnostic readbacks require a local harness extension, whose unexecuted command
is explicitly pending. The report does not imply that passing the JSON to an
unchanged harness runs those new cases.

[BLOCKED_DATA_REQUEST.json](BLOCKED_DATA_REQUEST.json) asks for the smallest
remaining observations: pre-store lobe values at 16 colour witness pixels;
actual historical sampled-history/gate bytes and harness provenance; and seven
original native 32-byte atomic buffers, totaling 224 core bytes. A separate
optional Gain microcase already has all its input grid data and requests the
device's pre-store arithmetic. Full raw captures, unseen history and a new
ground-truth dataset are not prerequisites for using the completed CPU API.

The exact remaining risks are machine-readable in `RESULT.json`. They include
typed-store and NaN/denormal behavior by boundary, sampler precision/ties,
compiler contraction/division/transcendentals, finite-guard lowering, original
atomic values, historical gate-map identity, and projection/capture conventions.
Nothing in these CPU checks establishes final RR/game image quality or speed.
