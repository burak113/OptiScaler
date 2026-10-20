# Representation investigation: predictions fixed before implementation

Base tag: `astra-handoff-20261020`, resolved commit
`5d7839a930106cf8fe1ba8dbbc6750509e7f26a8`.

Owner: representation/implementation subagent. The coordinator captured the
unchanged packaged baseline before authorizing these files. This document records
the predictions before candidate tests or calibration are tuned.

## Competing mechanisms and falsifiers

1. **Storage boundaries change decisions.** A float32 value on one side of a
   threshold can land on its other side after a typed FP16 store. Increasing the
   arithmetic precision without inserting that store cannot repair this. Compare
   RNE, RTZ and unrounded arithmetic on the same inputs. A branch mismatch outside
   every declared storage envelope falsifies a storage-only explanation.
2. **The guide payload loses information.** Every integer payload of the audited
   `qx*32+qy`, `qx=0..63`, `qy=0..31`, must survive both FP16 roundings and satisfy
   `pack(unpack(code)) == code`. Any failed code falsifies that contract. The old
   normalized 16-bit payload must lose codes and can perturb angular guide gates.
   Distinct octahedral boundary codes may decode to the same normal; geometric
   decode/encode closure is therefore not byte closure.
3. **Exported half cells cannot identify pre-store atomics.** Two float32 inputs
   from one half preimage can generate distinct 16.16 increments. A request for
   exact totals must reject a non-singleton interval. This is not repairable by a
   larger output tolerance. A singleton proven over the whole bin would falsify
   non-identifiability for that particular observable.
4. **Carry and reset are part of the contract.** Sequential low-word atomics plus
   the returned-old-value carry must equal a Python integer total modulo 2^64,
   including several natural/adversarial low-word wraps. Dropping the high word
   must fail this comparison. Reset must clear all 32 bytes including padding.

## Source boundaries read before modeling

- `FSRDColourTrackStats.hlsl`: all accumulators are `float`/`float4`, not `half`.
  `OutStats.rgb` and `OutTarget.rgb` call `SanitizeRadiance`; their depth/normal
  alpha and `OutMotion` do not call it. The audited payload already uses 11 bits.
- `FSRDColourTrackTrack.hlsl`: integer texture loads feed float32-shaped sums;
  `OutHist` and `OutGain` are actual stores. There is no source mandate to round
  every multiply/add to half.
- `FSRDFlatDetailCommon.hlsli`: `SanitizeRadiance` maps each nonfinite RGB lane to
  zero and clamps finite RGB to [0,65500]. `FlatPack` is a separate explicit
  `f32tof16` boundary clamped to [-65504,65504]; it is not called by these passes.
- `FSRDPreprocessCommon.hlsli`: oct encode uses `x>0`, whereas the decode fold
  uses `x>=0`. Encoding the zero vector divides by zero; the library reports
  unsupported input instead of inventing a normal.
- Native `StatsRecall`: raw `level` is stored to FP16, while the atomic increment
  is computed from the pre-store float as `uint(clamp(level,0,16)*65536)`.
  Nonfinite levels have no explicit source guard. The validated conversion
  helper deliberately rejects that unestablished integer-conversion domain.
- Native `Gain`: reconstructs each sum as float(low)+float(high)*2^32; the final
  ratio is float32-shaped, bounded above by4, and requires positive level/count.
- `FSRDNrdPostMotionAnchor_Dx12.h`: the sum buffer is 32 bytes; current low/high
  are at 0/4, recalled at 8/12, count at 16; host reset copies all 32 bytes. Stats,
  recalled, gain, key-level and provider copies use R16G16B16A16_FLOAT; key depth
  uses R32_FLOAT.
- Combined Anchor is deliberately different: 1/1024 uint32 totals, no lower
  clamp in its increment expression, and different fallback policy. The native
  16.16 helper must not be silently substituted for the combined estimator.

## Explicit model limits

RNE and RTZ in this library name numerical conversion models, not a claim that
all DXC casts and every device's typed stores use one rule. NaN conversion uses a
canonical quiet payload only to make the model executable; hardware payloads,
min/max signed-zero tie behavior, intermediate denormal handling and contraction
remain unestablished. Fused and separately rounded arithmetic are separate
functions. No source or generated shader bytes are changed by this workstream.

## Implementation and fresh CPU results

The following commands were executed by the representation subagent from the
repository root. Every command exited 0; no failed measurement was reclassified.

```sh
python -B -m unittest discover -s research/astra20261020/candidates/01-numerical-contract/tests -p 'test_storage.py' -v
python -B -m unittest discover -s research/astra20261020/candidates/01-numerical-contract/tests -p 'test_arithmetic.py' -v
python -B -m unittest discover -s research/astra20261020/candidates/01-numerical-contract/tests -p 'test_encoding.py' -v
python -B -m unittest discover -s research/astra20261020/candidates/01-numerical-contract/tests -p 'test_fixedpoint.py' -v
```

| Suite | Checks | Test-runner elapsed seconds |
|---|---:|---:|
| Storage | 9 | 0.087 |
| Arithmetic, final local run | 7 | 0.051 |
| Encoding | 6 | 0.075 |
| Fixed point, final local run | 12 | 0.190 |

Elapsed times are CPU unittest observations in this environment, not GPU pass
timings. The coordinator's final integrated test receipt supersedes this local
development receipt if code or test inventory changes.

The storage suite enumerates every one of 63,488 finite binary16 payloads and
checks both inclusive float32 preimage endpoints plus the immediately adjacent
outside values under both rounding modes. It also checks 50,000 seeded random
float32 bit patterns after excluding nonfinite inputs. Halfway parity, signed
zero, half subnormals, finite overflow, source sanitizer, and explicit flush
models are independently observable operations.

All 2,048 audited normal payloads survive RNE and RTZ stores exactly and retain
`pack(unpack(code))` closure. The old normalized 16-bit control loses 58,367 of
65,536 codes in RNE and 59,383 in RTZ. The four octahedral south-pole corners
decode to the same normal but remain distinct valid code payloads; decoding and
re-encoding canonicalizes three of them. This does not falsify byte closure.

The native 1440p synthetic grid uses 57,600 cells at physical current level 16
and recalled level 12. Integer totals are 60,397,977,600 and 45,298,483,200, with
multiple low-word carries and a source ratio of 0.75. Ignoring the high word
fails the exact total. Seeded adversarial uint32 increments test order invariance
and high-word wrapping separately from physically capped increments. Invalid raw
increments are rejected before any accumulator byte is changed.

For the same stored half value 1, exact finite float32 preimages demonstrate why
native atomics are not recoverable from stored cells:

| Rounding model | Lower float32 input | Upper float32 input | Lower 16.16 increment | Upper 16.16 increment |
|---|---:|---:|---:|---:|
| RNE | 0.999755859375 | 1.00048828125 | 65,520 | 65,568 |
| RTZ | 1.0 | 1.0009764432907104 | 65,536 | 65,599 |

Both endpoints in each row produce identical stored FP16 bits. Asking
`FrameSumBounds.require_exact_totals()` for these bins raises
`NonIdentifiableError`. Saturated physical levels whose complete bins exceed
the cap, or an empty measurement population, do permit provably exact totals.

Float32 sum reconstruction is monotone on the native cap/count domain. Since
count <= 2^32-1 and each increment <= 2^20, total < 2^52 and high < 2^20.
The high word and high*2^32 are exactly representable as float32. At a low-word
carry, rounding 0xffffffff to float32 gives 2^32, so the old rounded endpoint
equals the next high-word origin. Endpoint ratio envelopes therefore remain
valid across carry boundaries; tests cover these boundaries and exponent changes.

The independent skeptical reviewer reported agreement with a separate RTZ oracle
and all finite-half preimage endpoints before receiving these development test
results. Its additional glibc `fmaf` comparison of 8,101 seeded finite triples
matched the exact-integer fused reference bitwise. This is attributed to that
reviewer and remains an environment-specific extra check, not a new dependency
or evidence of DXC/device contraction.

The pointwise native Apply model checks diffuse/specular independence, RGB-lane
independence, finite alpha bytes, source RGB sanitization, and OFF ignoring unused
invalid gain/rounding values. Enabled nonfinite alpha payloads are explicitly
unsupported because device NaN payload preservation has not been witnessed.

## Recommendation from this workstream

Keep the contract library as CPU research and integration-test infrastructure.
The audited 11-bit production encoding is already corrected; do not propose the
same fix again. There is no justified new denoising policy or production shader
change here. Native exact atomics and device-specific store/sampler/arithmetic
microcases remain local GPU gates. The coordinator owns calibration of the
packaged recorded GPU witnesses and the final reusable API version/hash.

## Additional Gain-boundary falsifier, recorded before implementation

The coordinator requested one further discriminating experiment: reconstruct the
Anchor Gain expression up to its actual typed output store, then separately
apply RNE and RTZ to that same unrounded result. The frozen reference currently
rounds its result to RNE, so applying RTZ to that already stored output is not a
valid experiment.

Prediction: if the remaining one-half-ULP calibration residual is caused solely
by the gain output store, selecting the recorded device's rule must remove every
mismatch on the fixed 133 combined and 7 native frame populations. If residuals
remain with the correct directional rounding, the store-only hypothesis is
falsified at those cells; float32 staging, compiler contraction, transcendental
accuracy and the native frame-atomic uncertainty remain competing explanations.
No output tolerance or denoising policy will be tuned. Native frame ratios remain
labeled bounded estimates; the combined counters support source-shaped float
division from their exact exported words. Every comparison reports nonzero count,
sign, max and percentiles, including identity cells in its fixed denominator.

### Implemented Gain API and source arithmetic order

`numerical_contract/anchor_gain.py` adds:

- `GainParameters`: the source band, cap, strength, tap, coverage, reject and
  native-local-gate constants. The old `fallback_a_unused` field is explicitly
  ignored. Combined and native fallbacks remain different as in production.
- `anchor_gain_unstored(stats, recalled, k, frame_ratio, *, frame_count,
  frame_measured, policy='native', params=None, exp_mode='source_exp_f32')`:
  returns `GainResult` containing unrounded gain, local numerator/denominator,
  coverage, model/reject scalars, global rejection and local branch masks.
- `GainResult.stored(rounding)` and `anchor_gain(..., rounding='rne'|'rtz')`:
  round only at the actual gain output boundary. No earlier RNE gain is reused.
- `replay_calibration(anchor_root=None)`: compares every recorded frame with
  both stores and both exponential models; returns JSON-compatible summaries,
  per-frame records, all 17 RTZ residual cells and exact source operands.

The input arrays must represent the complete grid of the producing dispatch,
including its actual texture edges. They cannot be an undisclosed partial crop:
in that situation absent taps require the separate crop/support contract. These
fixtures are documented whole-grid ROI replays; the full replay grid is the fixed
population. Input depth/slice lanes unused by the Gain observable are not read.
The source pass's key-ring capture side effect is outside this current-Gain API.

All ordinary local multiply/add/divide operations have explicit float32 staging
in source loop order (dy, then dx), with the source integer clamp and tap step.
`source_exp_f32` evaluates the HLSL formula with NumPy float32 exp.
`dxil_exp2_f32` follows the inspected pinned headers' lowering of exp(x) to
Exp(x*log2(e)): both headers use `0x3FF7154760000000` then DXIL unary opcode 21.
That lowering does not certify device Exp accuracy. The source's `fast` arithmetic
still permits driver contraction, reassociation and reciprocal lowering. Native
compilation uses cs_6_6/HV2021 and combined uses cs_6_2, both with the recorded
O3/native-16-bit compiler flags; this does not turn these float expressions into
half arithmetic. No shader was rebuilt or modified.

### Fresh Gain calibration on unchanged recorded fields

| Policy and fixed population | Output store | Nonzero cells | CPU above GPU | CPU below GPU | p99 absolute error | Maximum absolute error |
|---|---|---:|---:|---:|---:|---:|
| Combined: 133 frames, 416,720 cells | RNE | 77,036 | 77,036 | 0 | 0.00048828125 | 0.00048828125 |
| Combined: same cells | RTZ | 17 | 16 | 1 | 0 | 0.00048828125 |
| Native: 7 frames, 26,256 cells | RNE | 3,675 | 3,675 | 0 | 0.00048828125 | 0.00048828125 |
| Native: same cells | RTZ | 0 | 0 | 0 | 0 | 0 |

Both exponential models produce the same stored comparisons in this table.
Combined exact exported 1/1024 words are converted to float32 before source
division. Native totals are still absent: the replay verifies equal global guard
decisions and equal unrounded output across the complete ratio envelopes under
both RNE and RTZ input-field storage hypotheses. The native output match therefore
does not rely on selecting one favorable central ratio within those envelopes.
It still does not identify the exact absent native atomic words.

The dominant final-store hypothesis is strongly supported on these recorded
fields. A universal store-only explanation is **rejected** because 17 combined
cells still differ. Thirteen of those involve identity classification; maximum
error remains one half step even though p99 is zero. No remaining discrepancy is
silently accepted as exact parity.

One surgical counterexample is combined capture `87ee1fba`, frame 18, grid cell
`(x=5,y=27)`. The modeled local numerator and denominator are both
`0.036468505859375`, coverage is 1, and the CPU unrounded gain is 1. The recorded
GPU gain is `0.99951171875`; under RTZ its valid pre-store float32 interval ends
at `0.9999999403953552`. More accurate CPU division gives exactly 1 and does not
resolve that discrepancy. Even multiplying by the normally rounded CPU reciprocal
gives 1 in this scalar check. Device approximate division or other expression
lowering remains a hypothesis, not an identified cause. The replay preserves all
17 cells' nine input taps and exact counters so a local dynamic-input shader
microcase can distinguish those explanations without a large recapture.

The extra test command is:

```sh
python -B -m unittest discover -s research/astra20261020/candidates/01-numerical-contract/tests -p 'test_anchor_gain.py' -v
```

Eight additional tests passed, including direct-vs-double-store mutation,
policy/unused-constant invariants, the known moderate-light rejection failure,
all recorded frame populations, both native ratio envelopes, and preservation
of the 17 remaining counterexamples. The exact fixed-fixture mismatch counts are
diagnostic assertions, not widened error tolerances. The coordinator retains the
full final command receipt and integrated calibration JSON. All results above
are fresh CPU executions against stored historical GPU fields, not new GPU runs.
