# Spatial + Temporal coarse radiance noise

> Historical experiment/build report. Availability, current behaviour and final
> validation limits are documented in the [2026-09-26 checkpoint](fsrd_floor_recovery_release_20260926.md).
> Claims and measurements below describe that experiment, not a new validation run.

The former 3x3 Wiener filter used the Floor seed's fine-noise estimate for both
detail retention and temporal content validation. Correlated patches could have
small fine derivatives but large radiance excursions: spatial recovery retained
them as detail, while history rejection/clipping repeatedly admitted the current
patch. A fixed history weight also over-weighted the first noisy sample.

The composition shader now adds eight sparse samples (four opposing pairs at
radius three). Same-surface depth, normal, diffuse-albedo and routing checks bound
the footprint. The quietest supported directional second difference extends
uncertainty without requiring the full Anchor covariance/correlation pipeline.
Local filtering still handles fine detail; the wider contribution is bounded.

Temporal colour accumulation starts at one sample and grows to sixteen. The
previously unused high byte in packed albedo metadata stores age; resource sizes,
dispatch count, original albedo RGB and Anchor decision channels are unchanged.
History remains a filtered reference, never a final composite or a recursively
amplified recovery correction. All geometric/content rejection gates remain.
History clipping accounts for estimated coarse uncertainty.

After rejection/disocclusion, only the correction associated with coarse
uncertainty ramps over four accepted frames. This deliberately allows less
recovery immediately after exposure of a noisy region instead of copying a large
single-frame excursion. The unattenuated filtered reference is stored separately
from that output gain. Exactly zero estimated noise bypasses colour accumulation
to avoid adding recursive packed-history quantization error to a clean reference.

This is an estimator, not a guarantee that low-frequency lighting noise can be
distinguished perfectly from animation. Highly correlated noise, incorrect game
motion, continuously rejected history and subtle animation remain limitations.
The four-frame ramp can temporarily leave more of RR's original soft result.

## Validation

Frozen prior composition DXIL:
`c2c771f6c9cb1b9360c6dee479db4a8bac22d873f1cfdfc39d4df160f7934c8e`.
New composition DXIL:
`6cc176049107688dc7936f268fedaf451c14223ff2c9fd5fb69f4836c977881d`.

Actual production DXIL executed on an RX 9070 with the D3D12 debug layer.
Known synthetic truth and independently supplied RR outputs were used; these
tests do not execute AMD's denoiser or validate Cyberpunk's sea visually.

- Correlated-noise reconstruction MSE decreased 47–51% versus the prior shader
  across static, integer/subpixel pan, depth reveal and real Floor-seed cases.
- Mean squared frame-to-frame reconstruction error decreased 65–72%.
- The actual Floor-seed fixture decreased MSE from 0.002328 to 0.001215, and
  frame-to-frame error from 0.003525 to 0.000973. Noise is reduced, not eliminated.
- Clean broad correction and sharp colour boundaries are retained. The stable
  broad-error fixture improved settled MSE from 0.00002187 to 0.00002036.
- The earlier independent fine-grain fixture is essentially unchanged:
  0.00035473 previously versus 0.00035853 now (about 1.1% higher MSE). Residual
  injection into an already sharp RR result is lower, 0.00002871 versus 0.00008817.
- Recovery controls, geometric rejection, motion/jitter mapping, Anchor decision
  history, luma/chroma recovery and volumetric visibility suites pass.

Timing is composition-only at 1505x847, full-frame synthetic coverage. Reverse
A/B order confirmed the cost; recovery-disabled runs used 1000 repetitions to
avoid GPU clock transients in very short workloads.

- ST without history: 0.612 ms before, 0.941 ms now.
- ST with accepted history: 0.847 ms before, 1.181 ms now.
- Full Anchor: 2.903 ms before, 2.895 ms now; benchmark output bit-identical.
- Recovery disabled: 0.0608 ms before, 0.0607 ms now; output bit-identical.
- Mixed full-frame Anchor plus ST: 3.368 ms before, 3.912 ms now.

No performance equivalence is claimed for ST: the extra coarse-noise work costs
about 0.33 ms in the ST-only fixture. It remains substantially cheaper than
running full Anchor everywhere. Total game Floor/RR time can differ.

Reports and DLL: `tools_tmp/st_coarse_noise/delivery/`.
Quality A/B: `tools_tmp/st_coarse_noise/final_coarse/results.json`.
Retained-feature validation: `tools_tmp/st_coarse_noise/final_validation/summary.json`.
Timing: `tools_tmp/st_coarse_noise/benchmark_confirm/results.json`.

In-game A/B should keep recovery enables, modulation, resolution and master gain
fixed. Compare stationary water, a slow camera pan, newly visible regions and
moving screen content. Check both residual large patches and possible trails;
synthetic improvements alone cannot establish that those are resolved in-game.
