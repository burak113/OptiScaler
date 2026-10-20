# Independent numerical-contract review

Reviewer: `independent_skeptic`. Starting revision:
`5d7839a930106cf8fe1ba8dbbc6750509e7f26a8` (`astra-handoff-20261020`).
This reviewer neither selected candidate parameters nor changed the production
source. Findings were sent to the implementation owners; independent regression
tests and the observation-recovery diagnostic are maintained separately.

## Independence and evidence boundary

Before inspecting candidate code or hearing its claimed improvement, the reviewer
read the prompt/protocols, production ColourTrack/Anchor shaders and frozen
portable packages. `ADVERSARY_PRECOMMITMENT.md` records the fixed boundary cases.
The first independently executed controls reproduced old payload corruption,
missing-high-word failure, premature-rounding bias and non-identifiability from
two identical half exports. Passing these diagnostics means the known wrong
models were detected; it does not approve the historical soft2 denoiser.

All execution reported here used CPU/NumPy in this session. Stored shader/GPU
results remain historical calibration witnesses. This review executed no GPU,
DXC rebuild, AMD RR, game, full native host integration or performance test.

## Substantive findings and resolution

### 1. A generic half preimage is weaker than a possible captured lobe sum

The first proposed real-data witness used arbitrary binary32 interval endpoints
that RTZ-store to the same exported half tensor. That proves storage-level
non-identifiability, but the provenance additionally says the pre-store value was
a sum of two captured FP16 lobes. An arbitrary endpoint just below the next half
does not automatically satisfy that representability constraint.

The reviewer required a stronger construction: a half value `h` plus another
half-exact nonnegative value `delta`, compared with `h + 0`. `delta` is half the
distance to the next half when representable as a half subnormal or normal;
otherwise it is zero. Both sums RTZ-store to `h`. On the frozen colour input this
construction changes **364 / 786,432** JBU output channels, with maximum
`3.0517578125e-5`. The earlier **743**-channel endpoint diagnostic remains a
separate, less constrained storage experiment. Neither construction recovers the
original unknown lobe decomposition.

### 2. Some supposedly missing pre-store bits are actually present elsewhere

The reviewer checked cross-fixture identity using capture UUID, original frame,
render size, per-frame crop origin and actual field comparisons before examining
the expected output. `foliage23` frame 63 covers a **192x64** rectangle starting at
render `(752,423)`, or local `(256,256)` in the colour fixture. It is the same
`87ee1fba-b8bc-4660-aa3f-d06db7bf863f` capture.

The following independent comparisons were exact on the full, fixed rectangle:

| Observation | Compared population | Differences |
| --- | ---: | ---: |
| RTZ of raw RR diffuse+specular versus colour `rr_rgb` | 36,864 RGB channels | 0 |
| RTZ of input diffuse+specular versus colour `input_rgb` | 36,864 RGB channels | 0 |
| Original source depth | 12,288 pixels | 0 |
| Prepared packed normal/roughness | 12,288 words | 0 |

The separate *original* normal array differs at 23 words, reinforcing that field
role cannot be inferred from similar names. The raw RR lobe sum reveals extra
bits at **28,485** channels. Supplying these actual bits eliminates all **13**
previous `expected_soft2` errors in that rectangle: maximum error
`7.62939453125e-6` becomes **0**, and all 36,864 output channels become exact.
The full output changes at exactly those 13 channels.

This is a direct observation-backed mechanism test, not tolerance relaxation.
The fixed 12,288-pixel support is selected by capture geometry, not candidate
output. The data request and non-identifiability claim must exclude this proven
known subset. Preserving its actual pre-store values in both hypothetical lobe
witnesses still leaves **357** different output channels elsewhere and **0**
differences on the observed rectangle.

`facade16` has a different capture UUID and no frame 63, so it cannot supply those
bits merely because its ROI origin matches. The glass package has the same
capture, but its RGB arrays are bilinearly reprojected to reference 54; only its
geometry arrays are unwarped. Directly copying that RGB into frame 63 would invent
an observation. Constraints from aligned glass are retained as a limitation; no
inverse reconstruction or claim of matching all derived artifacts was made.

### 3. A source-shaped interpolation expression can leave the API envelope

For arbitrary R32 values `(+FLT_MAX,-FLT_MAX)`, separately rounded float32
`a+(b-a)*t` can overflow at `t=.5`, while the exact convex result is zero.
The sampler owner retained this diagnosable arithmetic behavior, explicitly
documented that its expression is not established hardware SampleLevel
arithmetic, and added a test demonstrating rejection by the finite convex
envelope. Finite FP16 radiance values cannot trigger this particular overflow.

### 4. Nonfinite depth is not automatically rejected by the existing predicate

The source-shaped expression accepts a finite history depth when expected depth
is infinity because both error and tolerance become infinity. NaN comparisons
reject. This behavior is now an independent diagnostic; the CPU model does not
silently insert a missing finite guard. A finite-guard adapter requires its own
local GPU acceptance and must preserve the original finite-input behavior.
Because actual Stats.a/Motion.z resources are R16F, two finite stored values
cannot overflow binary32 when added. An actual typed-resource microcase must use
R16 infinity rather than treating a `FLT_MAX+FLT_MAX` toy as stored shader input.

The reviewer inspected the delivered `adapter/PRODUCTION.patch`: only the final
predicate gains `isfinite(history.a) && isfinite(expected)`. The history-enabled,
viewport, nonzero-depth and inclusive tolerance conditions are unchanged.
`git apply --check` succeeds against the frozen working tree without applying
the patch. Its generated bytecode has not been rebuilt or run. The reviewer
independently executed the sampling agent's nine guard tests: **9 passed in
0.078 s**, including 253,952 finite-half/probe comparisons, 4,096 seeded cases,
actual typed infinity cases and signed inclusive boundaries. No finite-domain
decision changed in these fixed CPU populations. This supports a scoped
default-off GPU A/B proposal; it is not a DXC or device acceptance.

### 5. Final-store rounding explains the dominant Gain gap, but not every cell

The reviewer independently reran `anchor_gain.replay_calibration()` over every
bundled recorded Gain frame. The population contains all grid cells, including
identity cells, with no candidate-derived mask or new tolerance. Rounding is
applied once to the retained float32 Gain result at the actual output-store
boundary. Applying RTZ to an already RNE-rounded frozen result would not test
the mechanism.

| Recorded policy | Frames | Compared cells | RNE differences | RTZ differences |
| --- | ---: | ---: | ---: | ---: |
| Combined | 133 | 416,720 | 77,036 | 17 |
| Native policy fixture | 7 | 26,256 | 3,675 | 0 |

Both the float32 source `exp` model and float32 DXIL-shaped `exp2` model produce
these counts. Every RNE disagreement is above the recorded GPU value. Under
RTZ, the combined residual contains 16 predictions above and one below, with
maximum absolute difference `0.00048828125`, one half step. There are 13
identity/nonidentity classification differences. The remaining **17 combined
cells falsify the universal final-store-only explanation**, even though the
RTZ p99 absolute error is zero. Native ratios remain conditional estimates from
stored fields because original native atomics are absent; the implemented
endpoint checks establish unchanged native Gain across the modeled RNE/RTZ
field-rounding ratio bounds, not recovery of the actual missing counters.

A concrete independent regression preserves capture `87ee1fba`, frame 18, grid
`(x=5,y=27)`. Exactly one of its nine taps has nonzero weight. That tap has
identical current and recalled levels `0.036468505859375`, so the separately
rounded model numerator and denominator are equal, coverage is 1, fallback is
1 and neither rejection guard fires. Both named CPU arithmetic profiles produce
exactly 1; neither RNE nor RTZ can store exact 1 as the recorded
`0.99951171875`. The latter's RTZ binary32 preimage is
`[0.99951171875, 0.9999999403953552]`, which excludes 1.

The formula review compared both production Gain HLSL files, including tap order,
global-before-local rejection, combined fallback, native static-centre behavior,
unused fields, cap and strength ordering. No policy mismatch was found in the
declared finite input domain. A separate independent boundary test proves that
native centre static exactly `.5` is allowed when a neighbor supplies recall,
while the previous representable half is blocked. The distinct key-capture
`cell.z > .5` predicate must not be substituted for the Gain gate's `< .5` test.

Pinned DXIL contains `fdiv fast`, `fmul fast` and `fadd fast` instructions.
Device division/reciprocal lowering and contraction remain possible causes of
the residual; neither was executed or inferred as a proven explanation. A new
GPU run must export intermediate binary32 values for the residual cells before
attributing the remaining difference to compiler or hardware arithmetic.

## Independently reproduced contract checks

The independently maintained suite contains 29 meaningful tests at this review
checkpoint. It ran successfully in 1.622 s of unittest time. Its fixed inputs cover:

- All 63,488 finite half payloads: both RTZ/RNE preimage endpoints reproduce the
  payload through an independent conversion oracle, and the adjacent binary32
  values outside both endpoints do not.
- Literal signed zeros, subnormals, halfway ties, finite overflow and separate
  radiance sanitization; 65,536 seeded raw binary32 patterns exercise RTZ.
- All 2,048 new payloads and all 65,536 legacy payloads. The legacy RTZ control
  corrupts 59,383 codes, with maximum code error 32. Four distinct south-pole codes
  are retained even though they decode to the same direction.
- A natural 262,145-cell cap16 sequence causes 64 low-word wraps and has exact
  total 274,878,955,520. Full 64-bit wrap, support-count wrap, byte round-trip and
  clearing all 32 bytes are separate tests.
- Exact discrete atomic bounds for the half 1/.5 case; the exact-reconstruction
  API raises on distinct compatible totals. NaN/Inf outside fixed support are
  never converted into observations.
- Allocation/active extent separation; integer-load uint32 payload preservation;
  point-versus-bilinear and incorrect-UV mutants; odd extents; integer translation;
  original-render motion scaling and moving crop origins.
- Partial crops: zero-weight missing neighbors do not destroy exact-centre
  identity, while any positive-weight unavailable tap fails support. An 8-bit
  fraction can legitimately snap a tiny missing tap to zero, so comparing modes
  must retain common support rather than reward a candidate-dependent mask.
- The source's sparse native 8x8 pattern is distinguished from a full 64-texel
  mean. All 16 quarter-cell texels participate equally in the Colour pattern.
- Independent lobe handling, alpha bits, OFF identity, unused poisoned values,
  inclusive depth thresholds, true viewport exit and explicit non-identifiability
  exceptions; the exact native static-centre boundary and the recorded Gain
  counterexample described above.

An additional independent environment check compared the exact dyadic fused-MAD
oracle against `libm.so.6`'s `fmaf` on 8,101 finite random triples (seed `0xF32F`),
with 0 differing binary32 words. This is a local CPU cross-check, not a portable
dependency or a DXC/GPU claim.

## Calibration claim check

The reviewer independently reproduced 0 changed gates for ideal64 sampling,
9/4096 for the 8-bit fraction model and 6/4096 for the RNE-store intervention.
The raw GPU gate map is absent, so matching historical count 9 cannot establish
that the same 9 GPU decisions were reproduced. The 64-bit experiment concerns
sampler precision; it cannot establish that an entirely float64 estimator would
behave the same. Both limitations were sent to the coordinator before delivery.

## Reproduction commands

From repository root:

```sh
python -B research/astra20261020/candidates/01-numerical-contract/adversary_controls.py
python -B research/astra20261020/candidates/01-numerical-contract/adversary_controls.py --recover-overlap
python -B -m unittest discover -s research/astra20261020/candidates/01-numerical-contract/tests -p test_independent_adversary.py -v
python -B -m unittest discover -s research/astra20261020/candidates/01-numerical-contract/tests -p test_guard_adapter.py -v
git apply --check research/astra20261020/candidates/01-numerical-contract/adapter/PRODUCTION.patch
cd research/astra20261020/candidates/01-numerical-contract
python -B -m numerical_contract.anchor_gain
```

`overlap_recovery(return_arrays=True)` returns summary, the fixed known mask and
a full colour array containing actual pre-store values only on that mask. Values
outside the mask remain rounded baseline inputs. Reusable output records identify
the implementation owner separately from the calling process; the enclosing run
record owns executor attribution.

## Review position

The reviewed library is useful reproducible research infrastructure. The review
supports **keep as research**, with any scoped finite-depth adapter remaining
default-off until source-shaped GPU microcases and the integration owner accept
it. There is no basis here for claiming improved grain, sparkles, flicker, RR
quality, throughput or game output. Whole-frame exact reconstruction and universal
hardware equivalence remain rejected claims. The supplied CPU contract and its
honestly retained failures are ready for integration as research; the adapter
requires the separately requested compiler/device checks before production
acceptance.
