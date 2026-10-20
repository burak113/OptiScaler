# Per-lobe correction uncertainty, version 1

This document describes the public CPU interface in `glass_candidate.py`. It is
an independent, stateless diagnostic candidate. It does not reproduce the
native robust fit, NZR selection, virtual reflection history, AMD RR, or final
game remodulation. The current handoff cannot populate this interface from its
recorded glass RGB alone. Missing evidence means exact local identity.

## RGB and ownership

`shrink_specular(raw_rgb, selected_rgb, eligible, uncertainty, config)` accepts
current-frame `float32[H,W,3]` linear radiance. `raw_rgb` is this lobe's raw RR
output; `selected_rgb` is this lobe's NZR output **before** Glass policy. They
must have the same extent, exposure, units, frame identity, coordinate system,
and native stage. The routine returns a new selected RGB array and diagnostic
support maps. It reads no previous frame, motion vector, material ID, alpha,
diffuse lobe, or history resource.

`apply_specular` is a convenience formula for source-shaped Glass modes 0, 1
and 2 only. Mode 2 retains the existing meaning of strength: it is the NZR
fraction in `raw + strength * (selected - raw)`. The transformation precedes
that policy; the default comparison uses strength 0.5. Mode 3 and wider service
routing are not modeled. The supplied orientation gate remains authoritative.
Alpha is copied from current/raw output. Diffuse is outside this API.

## Sidecar fields

Every field has shape `[H,W]` and belongs only to the specular lobe:

| Field | Representation | Required meaning |
| --- | --- | --- |
| `noise_trace` | float32, radiance squared | Sum over RGB of `Var(NZR - raw RR)`. Include the covariance between these outputs. |
| `effective_count` | float32 | Independent observations supporting that uncertainty estimate. Native history count is not a substitute. |
| `valid` | boolean | Current, compatible frame/extent/stage provenance and an identified uncertainty estimate. |
| `independent_spatial` | boolean | The four correction-noise samples in this particular 2×2 block are independent. |
| `surface_id` | integer | Support group established by validated current geometry. Equal values mean the four taps share eligible surface support. This is not a semantic material ID. |

Noise trace equals

`sum_RGB(var_selected + var_raw - 2 * covariance_selected_raw)`.

A provider's temporal sample count or input-lobe second moment does not supply
the selected-output covariance. Two outputs may be strongly dependent because
they use the same noisy inputs, guides and histories. The contract rejects
unknown spatial correlation instead of pretending diagonal variances describe
it. A later version could carry covariance, but this version does not.

Metadata accompanying a real sidecar must name the formula, estimator support,
native stage, lobe, frame index, extent, crop origin, units/exposure, provenance
hashes, and resets that invalidated it. A per-pixel `valid=true` is not itself
evidence. Newly visible surfaces, changed extent, stale frame IDs, unsupported
uncertainty, and missing geometry should make it false before dispatch.

## Arithmetic and fixed research settings

The preregistered settings are `noise_scale=1` and `min_effective_count=8`.
Subtracting expected high-band noise energy once is the positive-part Wiener
heuristic under the stated additive-noise model. Eight observations is a
conservative lifecycle abstention gate; even an ideal Gaussian sample variance
at that count has relative standard deviation `sqrt(2/7) ≈ 0.535`. The gate is
not a guarantee for sparse heavy tails, and it was not tuned against scenes.

For correction samples `a,b,c,d` in a 2×2 block, transform with:

```
LL = 0.5 * (a + b + c + d)
H  = 0.5 * (a - b + c - d)
V  = 0.5 * (a + b - c - d)
D  = 0.5 * (a - b - c + d)
```

Each coefficient is an RGB vector. With independent spatial correction noise,
its noise-energy expectation is `0.25 * sum(noise_trace[all four taps])`.
For each of H, V and D, use a common RGB gain
`max(0, 1 - noise_energy / max(dot(coefficient, coefficient), 1e-30))`.
Keep LL unchanged and reconstruct with the inverse orthonormal transform.

All four taps must be eligible, finite, within `[0,65504]`, currently supported,
above the effective-count gate, have valid nonnegative finite variance, and
share one nonnegative surface ID. Partial blocks at odd extents abstain. So does
a reconstructed block with any negative, nonfinite or out-of-range channel;
per-channel clipping would violate the low-band constraint. Zero variance or
constant correction bypasses the transform to avoid needless rounding edits.

Low-band preservation is a real-arithmetic block identity with float32 rounding
error in the implementation. It does not prove final-composite brightness
preservation after later sanitization, half stores or remodulation. OFF and
unsupported paths copy the selected RGB bytes exactly. CPU tests cover both
properties separately. The 2×2 origin is global `(0,0)`; crop-local parity is
not interchangeable with the native full-frame parity.

## What the synthetic suite assumes

The analytic raw-RR surrogate is softened current truth plus mild shared noise.
The selected surrogate is sharp current truth plus the same noise and an extra
noise term. Therefore its correction-noise variance is known analytically.
That is a deliberately favorable supplied sidecar, not a variance estimator
recovered from game data. Synthetic support counts test startup/reset policy;
they are generated evidence fields, not claims that a 64-sample native history
was captured.

The routine distinguishes spatial detail from independent noise only to the
extent that coefficient magnitude and the declared uncertainty allow it.
An isolated true glint and an identically shaped random impulse with identical
sidecars are observationally indistinguishable. Any attenuation helps one and
damages the other. Strong correlated noise can also imitate a line. The suite
and independent review preserve these counterexamples; passing numerical
contracts does not accept the candidate's image quality.
