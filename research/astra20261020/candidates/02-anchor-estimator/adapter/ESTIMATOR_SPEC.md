# Job 02 exact adapter specification — diagnostic v1

## Recommendation and boundary

Keep as research. This adapter is an **exact integration specification**, not an
applied production patch. No changed production file, CSO, DLL, generated shader
header, default setting, native routing or resource lifetime is included.
`estimator.py` is runnable; `AnchorDiagnostic.pseudo.hlsl` is explicitly
source-shaped pseudocode. No HLSL compiler or GPU ran for this proposal.

The accepted application field is identity. The other field is a provisional
one-sided comparison experiment and must never be connected to RR/NZR on the
strength of this CPU result. A future adapter cannot merely add a boolean
“excess confirmed”: the missing independent observation needs a versioned
physical-domain and validity contract, local causal intervention, and acceptance.

## Input domain

Each call consumes one chronological frame of already recalled **native**
`H x W x 4` Stats and Recalled grids, interpreted as stored FP16 values:

| Input | Components | Meaning |
|---|---|---|
| Stats | x, y, z, w | physical D+S luminance, depth, static flag, unused |
| Recalled | x, y, z, w | recalled physical D+S luminance, valid flag, ring slice, static flag |
| Frame interval | lo, hi, coverage | possible native recalled/current atomic ratios and original valid/static support share |
| State | k, active, reset, strength | motion-window age, explicitly armed input, explicit reset, comparison dose |

Luminance is `dot(D.rgb, (0.2126,0.7152,0.0722)) + dot(S.rgb, weights)` in
physical units **before** D16/S256/provider scaling. This diagnostic derives one
shared D+S gain; it makes no assertion that a diffuse-only or specular-only
estimator is equivalent. The existing Stats pass samples four bilinear locations
per 8x8 cell; those are not a full 64-texel average. Raw ring keys and exact
native pre-store atomics are missing from the package.

Only strictly greater than `.5` support flags qualify. Finite, nonnegative RGB
level is separate from positive bounded log usability. A missing centre's own
recall always makes that centre ineligible even when surrounding recall exists.
Negative/nonfinite observations do not silently leave a global atomic denominator
and become “better support.” A supported invalid level makes the frame interval
unavailable and hence fails closed.

## Fixed constants

`minimumUniquePairs=5`, `tapStep=3`, `dispersionMultiplier=1`, `gainLow=.80`,
`bandA=.18`, `tau=10`, `capExtra=.05`, `capHard=.30`, `rejectMult=1.8`,
`rejectAbs=.30`, `frameMinimumCoverage=.15`, physical cap16 and atomic scale65536.
These were fixed before held-out numerical fixture access. Sensitivity probes
must be reported separately and cannot silently replace this configuration.

The inherited decay/cap/large-change rejection are retained as bounded comparison
controls, not claimed as illumination classifiers. Genuine 1.1/1.25/1.4 changes
remain accepted by this provisional gain in coherent, fully supported scenes.

## Rounding and strict branches

For a finite nonnegative stored half value `q`, let `p` and `n` be its adjacent
half values. The conservative pre-store interval is
`[max((p+q)/2,0), n]`: a closed union of round-to-nearest-even and
round-towards-zero preimages. The zero lower endpoint is0. A half maximum finite
value with infinite successor is unsupported. This union is deliberately wider
than assuming an undocumented half UAV conversion mode. It does not assert
those are the only imaginable conversion modes; a different local mode requires
a new numerical contract before acceptance.

For each originally supported cell, bound the unchanged native atomic increment
with `floor(clamp(level,0,16)*65536)` at each interval endpoint. Sum in uint64.
The buffer ABI remains32 bytes: current low/high0/4, recalled low/high8/12,
count16, padding20..31. Never scale input textures to improve atomics.

Ratio bounds are `refLo/currentHi` and `refHi/currentLo`, expanded by8 float32
epsilons for split-word conversion/addition/division. Zero lower denominator
makes the upper bound unavailable (`null` in JSON), even if the central stored
estimate has a nonzero denominator. The central value is **not** native exact.
Intervals crossing the strict `1-ratio > threshold` branch abstain. Caller
interval overrides cannot overwrite invalid-input status. Coverage must be finite
and in `[0,1]`; malformed configuration is rejected rather than generating NaNs.

For local logs, compute each bounded pair as
`L=log(current/recalled)`, `Llo=log(currentLo/recalledHi)`,
`Lhi=log(currentHi/recalledLo)`. Enumerate the original step3 3x3 footprint and
clamp coordinates, then remove duplicates by physical coordinate. Remaining
coordinates may still be spatially correlated. They are **not**9 independent
samples, and effective sample size is not inferred from their count.

The lower order median is sorted index `floor((n-1)/2)`; zero observations yield0
with an invalid-support flag. Let `m=median(L)` and `MAD=median(abs(L-m))`.
Return the deterministic dispersion envelope
`[median(Llo)-MAD, median(Lhi)+MAD]`. This is not a calibrated statistical CI;
coherent noise can shift every pair without increasing MAD. It estimates typical
log change, not global energy: a small number of high-energy cells can move the
energy ratio in the opposite direction.

Numerical eligibility needs positive centre support and at least5 unique pairs.
Any used pair's upper endpoint reaching physical16 abstains because the global
ratio can be censored. Test both interval endpoints against the inherited strict
large-change guard. Either branch ambiguity or a fully rejected interval
abstains. The provisional correction also requires `logLower > 0`.

The comparison gain is `max(exp(-logLower), .80, 1-cap)`, blended towards1 by
strength and explicitly rounded to FP16 round-to-nearest. The deployment gain is
exactly1 for **every** case because a numerical interval cannot identify cause.

## Proposed job 08 diagnostic wiring, conditional on local approval

1. Keep the native `FSRDNrdPostMotionAnchor_Dx12.h` ownership, private D/S copies,
   original G3 inputs, RR/NZR routing, host active/refresh schedule, six physical
   key slots, reset lifetimes and family budget unchanged.
2. If a diagnostic capture is approved, add a separately selected, default-off
   diagnostic Gain variant after the existing native Stats/Recall and UAV
   ordering barrier. Keep actual native sums available in the capture to replace
   package-only interval estimates with measured atomics for parity evaluation.
3. Preserve any existing refresh writes to key textures even when gain is
   identity; early exits must not skip key refresh. This pseudocode specifies
   estimation only, not key maintenance or host transport (job04).
4. Export identity application, provisional gain, median/MAD/envelope, pair count,
   original support mask, reason bitfield and energy-concentration diagnostics.
   Never bind provisional gain as native Apply input. The v1 integration can
   therefore have a diagnostic cost but no claimed denoising benefit.
5. Do not alter shared bilinear Apply. Exact grid-centre identity does not prove
   full-resolution dynamic-pixel identity for a nonidentity neighboring gain.
   Transport repair belongs to job04. With the actual v1 identity field,
   interpolation remains identity.
6. Preserve alpha/hit-distance bits. The CPU Apply model copies alpha storage
   bits, uses ideal bilinear clamp for RGB, and models existing finite0..65500
   sanitization. D3D sampler fractions and UAV half conversion require separate
   local parity; this model is not an exact GPU result.

## Compiler and local gates

If converted to a real shader, use a new diagnostic entry point `CSMain`,
profile `cs_6_2`, `-O3 -HV 2021`, the project's pinned DXC1.8 toolchain, and no
`-enable-16bit-types` unless a separate native16 review adds it. Those are proposed
settings, not an executed build. Compile fresh bytecode/header together; compare
float32 intermediate diagnostics and final half gains against the CPU within
documented tolerances, inspecting branch agreement near every strict threshold.
FP16 gains should initially allow one-half-ULP numerical difference only away
from branch boundaries; branch ambiguity itself must abstain. Require the native
Config-to-provider canary, actual native Stats/Gain/Apply, D3D debug and lifetime
checks, physical input witnesses and fresh AMD RR before any application claim.
