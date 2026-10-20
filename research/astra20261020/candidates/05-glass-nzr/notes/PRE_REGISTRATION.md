# Frozen questions and decision rules

This file was written before the candidate experiment and holdout results. The
independent reviewer first reproduced the rejected colour control (expected
quality-gate exit 1), the captured Glass Blend trade-off, spatial blur and frozen
specular controls without seeing the candidate. There is no target quality score
and no scene-specific parameter search.

## Competing explanations

| Hypothesis | Distinguishing intervention | What the package can establish |
| --- | --- | --- |
| H1: robust reference fitting/support creates speckles | Fix noisy observations and downstream selector; vary fit/support only. Speckle placement changes while analytic mean/truth remains fixed. | A source-shaped synthetic fit diagnostic is possible. Captured refined reference, fit weights and support are absent, so native causality is unresolved. |
| H2: selector or gain uncertainty causes dots/flicker | Keep current RGB; independently freeze selector, freeze gain, or replace confidence. Compare their temporal signatures including a true light step. | Synthetic algebra separates these causes. Raw and selected output alone do not recover the hidden selector/gain. |
| H3: detail restoration amplifies low-count, heavy-tailed residual noise | Separate known sign/line signal from independent noise; change effective support and covariance at fixed signal. Test independent and correlated realizations. | A bounded, conditional correction estimator can be falsified; count is not automatically effective independent support. |
| H4: virtual reflection transport crosses wrong support | Move a reflected feature across fixed surface geometry and vary coverage/phase. Compare true reflection correspondence with ordinary surface correspondence. | Analytic counterexamples distinguish transport. Camera-aligned glass output and surface MV do not prove reflected-feature correspondence. |

The user's sharp Temporal-OFF preference is a hard qualitative calibration
requirement. A smoother image, lower temporal CV, or larger identity fraction
alone cannot satisfy it. Captured raw RR and old NZR-selected are controls, not
converged truth.

## Independent candidate boundary

The candidate is a stateless, vector-valued 2x2 Haar high-band shrinkage of the
current pre-Glass correction `NZR-selected - raw RR`. The low-band coefficient
is kept separately. A validated per-lobe sidecar must supply the uncertainty of
that correction, including raw/selected covariance, effective support and
geometry/phase provenance. Missing evidence means exact local identity. The
candidate is not a port of AMD RR, native reflection transport, robust Base, or
the final remodulation. It does not establish why the captured noise exists.

The unchanged Glass policy is applied after this correction. The main protected
comparison is candidate + Glass mode 2 / strength 0.5 against the same existing
Blend.5. An unblended candidate comparison is separately labelled diagnostic.

## Frozen numerical design

- Noise scale: 1.0, subtract one expected vector high-band noise energy with a
  nonnegative gain; use one gain per RGB vector to avoid channelwise colour gates.
- Minimum effective support: 8; a disclosed research guard, not a measured
  native count threshold or proof of sufficient variance accuracy.
- Variance units: sum of RGB variances in current physical lobe radiance squared.
  Orthonormal high-band coefficient variance is one quarter of the four pixel
  traces only when cross-pixel residual covariance is certified absent.
- Preserve the block's low band in float32 within recorded roundoff. Do not claim
  bitwise energy conservation after FP16 storage or unknown final remodulation.
- Abstain on any unsupported tap, incompatible geometry, partial block, invalid
  evidence, or reconstructed negative/nonfinite/out-of-half-range component.
- No temporal buffer, looped history or silently reused noise realization.
- Development seeds: 1000 through 1015. Held-out seeds: 2000 through 2047.
  Each scenario uses `SeedSequence([seed, scenario_id])`; 32 chronological frames,
  40 by 56 pixels. Holdout is evaluated once after implementation is fixed.

Sensitivity at scales 0.5 and 2.0, if reported, is diagnostic and cannot replace
the frozen scale-1 candidate. Bug corrections must be disclosed with their
reason; no quality threshold may be chosen from held-out winners.

## Required comparisons and rejection conditions

Compare raw RR, captured/modelled NZR, existing Blend.5 and Blend.75, candidate,
candidate + Blend.5, blur, frozen history and reduced correction strength.
Report noise RMSE/tails, sparkle errors and temporal flicker separately from
thin-sign/glint contrast, spatial detail, low-band level and current-light/motion
response. Use immutable BASE/truth masks and denominators, and separately count
the actual NZR-changed RGB subset, protected diffuse/alpha and boundary support.

Noise-score wins with lost sign/glint detail, stale response, invalid support,
unproven covariance or stronger bias are not accepted native quality wins.
Report Pareto comparisons against strength/blur controls at comparable detail
and response. Isolated real glints at the noise scale and correlated noise are
explicit falsifiers of unconditional shrinkage. If their label/support is
unobservable, retain research status and request the smallest missing data.

The local gate requires actual native NZR + Glass under D16/S256, G2/G3,
TemporalOFF, RRFallback, DiffuseRR and ReflectionHistory, plus matched final-game
A/B. CPU time is never reported as full-game GPU cost or resident memory.
