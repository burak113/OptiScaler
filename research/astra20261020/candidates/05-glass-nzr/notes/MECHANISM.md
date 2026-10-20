# Native NZR mechanism and intervention boundary

Scope: source inspection by the mechanism investigator on the immutable handoff
commit `5d7839a930106cf8fe1ba8dbbc6750509e7f26a8`. This document describes observed
source behavior and testable hypotheses. It makes no newly executed GPU claim.
Production files remain unchanged. The bounded candidate is not a replacement
implementation of the whole native NZR pipeline.

## Protected settings are a runtime preset, not all source defaults

The task's protected preset is D16/S256, G2/G3 enabled, NZR Temporal disabled,
ReflectionHistory/RRFallback/DiffuseRR enabled, and optional Glass mode 2 at
strength 0.5. `FlatAlbedoSettings` and `Config.h` still have different global
defaults (including Temporal=true). Changing these defaults to match this
experiment would be an unrelated production change and is not part of job 05.

`FSRDRadianceScaleSettings` carries diffuse=16/specular=256 when enabled. The
native bridge's scope restores physical lobe units after provider dispatch and
before recovery/trace/commit. Native flat recovery therefore consumes physical
demodulated lobes, not provider-scaled RGB. G2 is motion-adaptive stability;
G3 is lighting validation. G3 explicitly reads the original `sourceInput.diff`
and `sourceInput.spec`, while a private input anchor, if enabled separately,
can replace `input.diff` and `input.spec` for RR/NZR. This ownership split is
outside the proposed candidate and must remain intact.

Source references at the pinned revision:

- [Settings and config decoding](https://github.com/burak113/OptiScaler/blob/5d7839a930106cf8fe1ba8dbbc6750509e7f26a8/OptiScaler/shaders/fsrd_preprocess/FSRDNrdBridgeRR_Dx12.h), `FlatAlbedoSettings` and `ReadFlatAlbedoSettings`.
- [Radiance units](https://github.com/burak113/OptiScaler/blob/5d7839a930106cf8fe1ba8dbbc6750509e7f26a8/OptiScaler/shaders/fsrd_preprocess/FSRDRadianceScale.h).
- [Native settings mapping](https://github.com/burak113/OptiScaler/blob/5d7839a930106cf8fe1ba8dbbc6750509e7f26a8/OptiScaler/shaders/fsrd_preprocess/FSRDNrdBridge_Dx12.cpp), `ReadRRSettings`.
- [Provider, recovery and source authority](https://github.com/burak113/OptiScaler/blob/5d7839a930106cf8fe1ba8dbbc6750509e7f26a8/OptiScaler/shaders/fsrd_preprocess/FSRDNrdBridgeRR_Dx12.cpp), `RecordOwnedImpl`.

## Reachable shader graph

`FlatAlbedoRecovery::Reflection(s)` is `s.reflectionHistory && !s.temporal`.
Thus Temporal OFF does not disable reflection accumulation. The requested path
uses the following operations:

1. `FSRDNrdFlatPrepare`: copy original normal/roughness into private masks and
   apply the compatibility roughness floor only to the provider normal copy.
   Native negative or nonfinite input hit-distance disables that lobe's mask;
   zero RGB and signed zero hit-distance remain active. Private category 1 is a
   mask encoding, not a rewritten provider material ID.
2. `RecordOutput` copies the RR lobe outputs into private output resources.
   The specular and diffuse outputs are never combined in this helper.
3. For specular, `FSRDFlatDetailClassify` builds the active 8x8 tile list.
4. `FSRDNrdFlatHistory` computes a virtual-reflection running mean and luma
   second moment, with count capped at 16.
5. `FSRDFlatDetailSeed` makes a 5x5 geometry-weighted robust planar reference.
   `FSRDFlatDetailRefine` applies a 3x3 refinement. Both operate on reflection
   history RGB here, rather than raw single-frame RGB.
6. `FSRDFlatDetailBase` computes the reconstructed result. Native flags are
   `SameLighting | ReferenceTrust` even when Temporal is OFF. At strength 1,
   the nonnegative refined-reference alpha implies trust 1, so the final Base
   RGB follows the refined reference after finite/range sanitization. The
   intermediate RR lighting/statistics computations are not evidence that Base
   retains a different result at this setting.
7. `FSRDNrdFlatHybridPrep` restores a fraction of `history_mean - Base` and
   prepares collapse/noise/level inputs. `FSRDNrdFlatHybridBlur` performs
   separable sigma-4 and sigma-2 reductions and emits `(w, k)`.
8. Without optional reflection polish, `FSRDNrdFlatHybridApply` forms
   `S = BaseWithDetail + saturate(w) * (k * rawRR - BaseWithDetail)`.
   This pre-Glass `S` is the narrow independent residual candidate's stage.
9. The existing Glass policy remains afterward. On fully vertical pixels,
   mode 1 gives raw RR and mode 2 gives `lerp(rawRR, S, VerticalStrength)`.
   Strength is the retained NZR fraction. The gate is
   `saturate((0.8 - abs(world_normal.z)) / 0.3)`, and horizontal pixels have
   gate zero. The output alpha is copied from the current RR output.

If `reflectionPolish > 0`, `FSRDNrdFlatPolish` follows virtual reflection
transport with its own RGB history; `FSRDFlatDetailApply` then writes the result
and applies the Glass policy. The proposed job-05 adapter must declare polish
unsupported and abstain unless an explicit separate integration is accepted.

With Temporal ON, the alternate branch uses `FSRDNrdFlatAccumulate` and
`FSRDNrdFlatReferenceFilter`; it does not run the protected reflection path.
With reflection history OFF and RRFallback ON, `SelectPrep/SelectBlur/SelectApply`
select between the robust result and RR. That selector is superseded by the
Hybrid path when reflection history is enabled. With DiffuseRR ON the diffuse
loop is skipped altogether after the initial RR copy, so diffuse's authority is
the provider result. None of these alternative paths is silently retuned.

Primary source entries:

- [Actual allocations, bindings, scheduling and copy/commit boundaries](https://github.com/burak113/OptiScaler/blob/5d7839a930106cf8fe1ba8dbbc6750509e7f26a8/OptiScaler/shaders/fsrd_preprocess/FSRDNrdFlatAlbedoRecovery_Dx12.h), `Create`, `DescribeFrame`, `RecordInputs`, `RecordOutput`.
- [Private-mask preparation](https://github.com/burak113/OptiScaler/blob/5d7839a930106cf8fe1ba8dbbc6750509e7f26a8/OptiScaler/shaders/fsrd_preprocess/precompile/FSRDNrdFlatPrepare.hlsl).
- [Reflection history](https://github.com/burak113/OptiScaler/blob/5d7839a930106cf8fe1ba8dbbc6750509e7f26a8/OptiScaler/shaders/fsrd_preprocess/precompile/FSRDNrdFlatHistory.hlsl).
- [Seed fit](https://github.com/burak113/OptiScaler/blob/5d7839a930106cf8fe1ba8dbbc6750509e7f26a8/OptiScaler/shaders/fsrd_preprocess/precompile/FSRDFlatDetailSeed.hlsl), [refinement](https://github.com/burak113/OptiScaler/blob/5d7839a930106cf8fe1ba8dbbc6750509e7f26a8/OptiScaler/shaders/fsrd_preprocess/precompile/FSRDFlatDetailRefine.hlsl), and [Base](https://github.com/burak113/OptiScaler/blob/5d7839a930106cf8fe1ba8dbbc6750509e7f26a8/OptiScaler/shaders/fsrd_preprocess/precompile/FSRDFlatDetailBase.hlsl).
- [HybridPrep](https://github.com/burak113/OptiScaler/blob/5d7839a930106cf8fe1ba8dbbc6750509e7f26a8/OptiScaler/shaders/fsrd_preprocess/precompile/FSRDNrdFlatHybridPrep.hlsl), [HybridBlur](https://github.com/burak113/OptiScaler/blob/5d7839a930106cf8fe1ba8dbbc6750509e7f26a8/OptiScaler/shaders/fsrd_preprocess/precompile/FSRDNrdFlatHybridBlur.hlsl), and [HybridApply](https://github.com/burak113/OptiScaler/blob/5d7839a930106cf8fe1ba8dbbc6750509e7f26a8/OptiScaler/shaders/fsrd_preprocess/precompile/FSRDNrdFlatHybridApply.hlsl).
- [Shared exact binding/Glass semantics](https://github.com/burak113/OptiScaler/blob/5d7839a930106cf8fe1ba8dbbc6750509e7f26a8/OptiScaler/shaders/fsrd_preprocess/precompile/FSRDFlatDetailBindings.hlsli).

## Competing hypotheses and predictions, fixed before candidate results

| Hypothesis | Source-grounded possibility | Distinguishing experiment | What would falsify the explanation |
| --- | --- | --- | --- |
| H1: fit/support creates speckles | Seed uses noisy center-relative appearance weights followed by Tukey weights; insufficient robust support restores the center. Refine's appearance weights also depend on the current reference. | Keep each independently generated noisy realization, downstream selector `(w,k)`, and clean signal fixed; change fit support/statistics only. Capture Seed support/weight moments and speckle positions. | Speckle locations and tails remain unchanged while support/fit changes substantially, or the same defects already dominate the input at matched detail. |
| H2: selector/gain causes dots and flicker | Hybrid `(w,k)` derives from clipped detail and history-error fields; sigma-2/4 support can mix nearby recovery surfaces. | Three ablations: freeze `w` while retaining current RGB and `k`; freeze `k` while retaining current RGB and `w`; supply confidence from independent truth while retaining both RGB sources. | None changes the specified flicker component, or apparent improvement is entirely stale history/level attenuation. |
| H3: detail residual has insufficient reliable support | HybridPrep uses `(E[Y^2]-E[Y]^2)/count`; neighbour departures are accepted by maturity only. Thin heavy-tailed residuals can be accepted as detail or dark certainty. | Known text/lines plus independent, temporally correlated, and sparse-tail noise; vary true effective support while leaving signal fixed. For the independent correction candidate supply known correction covariance, then deliberately mislabel correlated noise. | Any claimed universal detail/noise separation fails on an identical-observation true-glint versus noise-spike pair; that failure is expected and must bound the claim. |
| H4: reflection transport uses wrong support | History reprojects the view-ray extension at surface distance plus median hit distance. Taps test previous hit distance, not previous normal/depth. HybridPrep and HybridBlur add further support mixing. | Move a reflected feature independently from its supporting surface; sweep pixel phase and glass/opaque coverage, crossed normals and crossed depth. Compare correct virtual transport against deliberately wrong surface transport. | A surface-MV-only fix is credited despite failing the independently moving reflection or geometry-phase test. |

The current handoff cannot perform the source-internal versions of H1 and H2:
the aligned glass data do not contain Seed/Refine/Base, Hybrid decision/gain,
moments/count, or raw input lobe history. Synthetic interventions can establish
discriminating signatures, but cannot identify which production stage caused a
particular recorded dot. H4 requires original hit distance and the actual
virtual transport/support to distinguish geometry from signal motion. Camera
alignment of an exported crop is not that transport.

## Why native history count is not the candidate's uncertainty

At this exact source revision, 16 is more than an arbitrary analytic example:
`HistoryConstants::maxCount` has member initializer 16 and
`DescribeFrame` constructs `HistoryConstants reflection {size}`. The subsequent
assignments change the camera/projection fields and `historyValid`, but never
`maxCount`. `Describe` copies this complete 128-byte structure into the
per-dispatch upload with `std::memcpy`. Thus this tagged host is expected to
upload 16 on the reachable reflection-history path. The Temporal-ON
`AccumulateConstants::maxCount=32` and `FlatAlbedoSettings::historyLength=6`
are different fields; neither overrides reflection `maxCount` here. These
source facts do not attest the user's loaded DLL, live settings, or uploaded
bytes. The local diagnostic request therefore asks for the actual 128-byte
History constants and binary/source provenance before attributing any live
behavior to the analytic `N=16` example.

The running-mean count starts at one and caps at 16. Beyond that cap, the source
uses a fixed-rate 1/16 recurrence. Bilinear or Catmull-Rom reprojection mixes
historical RGB, count and second-moment fields; recurrent input noise need not
be independent. A numeric value of 16 is therefore not a measured number of
independent present-day samples. Even for a stationary independent scalar
sequence a capped EMA and a finite arithmetic mean have different weighting
and uncertainty. An AR-correlated sequence changes that uncertainty again.

An analytic scalar control makes the distinction explicit. For a stationary
independent sequence with variance `sigma^2` and capped EMA length `N`, the
true mean variance is `sigma^2/(2N-1)`, while the expected source proxy is
`(sigma^2 - Var(mean))/N`. At `N=16` the proxy is 1.875 times the true mean
variance. For stationary AR(1) correlation `rho`, with `beta=1-1/N`, the true
mean variance becomes
`sigma^2/(2N-1) * (1+beta*rho)/(1-beta*rho)`. At `rho=0.9`, `N=16` the true
variance is approximately `0.380645 sigma^2`, while the expected source proxy
is approximately `0.038710 sigma^2`, an underestimate by about 9.83 times.
These are analytic models of the capped scalar recurrence, not measurements
of a particular glass crop; geometry mixing and sanitization are excluded.

The independent candidate acts on correction `C = S - R`, not merely `S`.
Its noise covariance is

`Cov(C) = Cov(S) + Cov(R) - Cov(S,R) - Cov(R,S)`.

For one RGB component this reduces to
`Var(C) = Var(S) + Var(R) - 2 Cov(S,R)`. Native raw RR and NZR-selected outputs
are not independent observations of the input. A history luma second moment is
neither per-channel correction variance nor raw-selected covariance. Moreover,
the noise covariance of Haar coefficients depends on cross-pixel covariance.
An independence approximation must be explicit and falsified with correlated
noise; data lacking that provenance must cause local identity.

The existing neighbour clamp in HybridPrep only tests `InHistory[q].a >= MinCount`
and image bounds. It does not require same depth/normal. HybridBlur uses
recovery/maturity normalization, but has no geometry-aware convolution. These
are concrete source properties, not proof that changing them improves the
recorded glass. Geometry alone also cannot separate two reflected signals on
the same physical pane.

## Data actually available to this investigation

The glass fixture has 18 chronological frames 46 through 63, aligned to frame
54, at 192x160. Its immutable common mask has 6,497 pixels after the six-pixel
halo. The separate full-ROI historical receipt has 8,048 pixels and must never
be substituted for this crop's denominator. Raw specular RGB is aligned
float32; selected RGB is exactly reconstructed by uint32 XOR; aligned diffuse
RGB is equal. Original normal/roughness, depth and motion fields are unwarped.
There is no input specular hit distance, albedo, actual internal NZR state,
same-pose clean truth, or final game composite in this subset.

The bottle, foliage and facade clips preserve original typed input/raw/selected
lobes and provider controls; all have partial history and omitted albedos. The
bottle's crop moves and its frozen motion mask includes hand/arm. The foliage
band includes several surfaces. None is a labelled raw mirror capture, and the
301-frame puddle control exists only as a historical receipt in this package.
All NPZ reads use `allow_pickle=False`.

The anchor and colour packages provide unrelated frozen estimator/parity
controls. Anchor grids contain already recalled keys rather than raw history
slices. The colour GPU witness has CPU-warmed prior history followed by one GPU
frame. They constrain contracts and bad-control calibration; they are not
independent glass noise realizations or a cloud-executable AMD RR provider.

## Adapter boundary and deliberately unported pieces

The proposed residual candidate is a bounded independent post-NZR arithmetic
experiment. It may reduce only independently supported high-band correction
energy. The pre-Glass correction low band remains separately represented. It
must copy the supplied pre-Glass selected result exactly on missing/invalid
uncertainty, insufficient support, geometry-crossing blocks, unsupported
transport, extent/crop phase changes without a valid contract, or option OFF.
The subsequent existing Glass policy remains authoritative.

A standalone test shader consumes separate immutable raw RR and pre-Glass NZR
inputs plus versioned support/uncertainty sidecars and writes a distinct output.
It must not read neighbouring `OutColor` pixels while another lane writes them.
It cannot acquire the missing sidecar from the current native graph by renaming
the history count. Job 08 owns admitting/retaining those resources, scheduling,
pointer/SRV choices, exact original masks, and family budget accounting.

Not ported: AMD provider denoising, native title encoding, complete robust
Seed/Refine/Base arithmetic, exact D3D sampler quantization, unseen pre-crop
history, virtual transport, G2/G3, provider radiance scaling, optional polish,
and final remodulation. An exact arithmetic check of the standalone shader
would not certify any of these. Additional pass/resource cost is unknown until
the local adapter is built and measured against the preserved same-mode sham.

## Existing test contracts inspected

`shader_tools/tests/fsrd_nrd_flat_albedo.cpp` checks private normal-floor bits,
original geometry and provider output preservation, all output alpha bits,
nonflat/inactive-lobe identity, finite radiance, owned output pointers, reset
when the floor is turned off, and family-exhaustion fallback. Its optional
`FSRD24_REFLECT` configuration selects reflection history with Temporal OFF and
DiffuseRR ON. The Python driver uses Windows/D3D12, a pinned signed provider,
and local-only captures; its `.py` extension does not make it CPU-portable.

This job's CPU tests can implement the arithmetic/identity subset and new
falsifiers, but must request actual wrapper/CSO execution to verify native
binding, descriptor lifetime, UAV ordering, FP16 stores, alpha bytes and the
matched game visual verdict. The user's established sharp Temporal-OFF result
remains the qualitative calibration requirement.
