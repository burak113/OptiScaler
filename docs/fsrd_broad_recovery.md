# Broad Spatial+Temporal recovery regression

> Historical experiment/build report. Availability, current behaviour and final
> validation limits are documented in the [2026-09-26 checkpoint](fsrd_floor_recovery_release_20260926.md).
> Claims and measurements below describe that experiment, not a new validation run.

The fine-detail noise guard also suppressed broad radiance corrections. A weakly
textured reference cannot correlate strongly with a broad blotch in RR. The later
independent temporal-detail evidence compared temporal variance with spatial
detail variance, so it did not reliably restore this missing low-frequency path.

The new path estimates the reference neighbourhood mean minus the RR local mean.
Its confidence is separate from fine-detail correlation. It requires accepted
history, a mature history age, adequate same-surface neighbourhood support, and a
correction larger than the measured temporal/spatial uncertainty. Confidence
ramps between squared signal-to-uncertainty ratios of 4 and 16. A separate
stability factor suppresses the correction when the current neighbourhood mean
changes relative to accepted filtered history; it reaches zero at a change of
half the correction amplitude. It contributes
only the portion not already covered by normal recovery confidence, preventing
duplicate correction. Existing recovery lobe weights and master strength apply.

There is no added texture, pass, allocation or sample. The path reuses the
existing reference neighbourhood, filtered history, RR mean and raw temporal
moments. Anchor-only recovery and the albedo conversion pipeline are unchanged.
Mixed Anchor/ST on the same pixel retains its prior behaviour because the shared
history stores Anchor decisions rather than independent ST moments there.

Geometry/content rejection still discards history. The independent broad path
starts after three accepted history frames and matures at eight. This trades
some recovery speed after disocclusion for protection against fresh noise.
Small corrections below uncertainty remain suppressed. Persistent biased input
can still be indistinguishable from real signal; this is not a water detector.

## Reproduction and acceptance

Frozen previous shader: `tools_tmp/recovery_sea_bias/baseline`.
Old strong, noisy recovery: `tools_tmp/st_coarse_noise/baseline`.
Initial comparisons: `tools_tmp/recovery_sea_bias/compare_candidate2/results.json`.
Final candidate: `tools_tmp/recovery_sea_bias/candidate4`.
Release validation: `tools_tmp/recovery_sea_bias/final_validation/summary.json`.

On the weak-detail broad-damage fixture, previous/new MSE is:

- Smooth region: 0.003545 / 0.000372.
- Animated weak waves: 0.003447 / 0.000543.
- Fractional camera pan: 0.002659 / 0.000329.
- Depth reveal, including history warm-up: 0.003457 / 0.001335.

The old noisy shader's MSE was approximately 0.00016–0.00018. The new path does
not claim to restore all of that correction strength. It recovers most broad
damage while retaining stricter uncertainty and disocclusion protection.

`test_fsrd_broad_recovery.py` adds dark and bright broad damage, animated weak
texture, changing roughness, fractional motion, depth rejection, valid-history
coarse noise and common-mode temporal noise. It uses an 80% specular share.
The existing absolute noise-return and detail suites remain required.

The new accepted-history coarse-noise fixture initially used the older
rejected-history fixture's 2.5e-5 MSE ceiling. The frozen previous shader itself
fails that ceiling (5.14405e-5 MSE; 8.85395e-5 flicker). For this new fixture,
the calibrated absolute limits are 6e-5 / 1e-4 and the release A/B also requires
MSE and flicker within 4% of the frozen previous shader. None of the existing
noise-suite thresholds were relaxed. Final candidate MSE is 5.29541e-5 (+2.94%)
and flicker 9.08773e-5 (+2.64%); RMS noise rises about 1.46%. This is a small
regression, not zero noise cost. The common-mode-noise result is effectively
unchanged. The first candidate's coarse-noise MSE increased about 10% and was
rejected; stricter amplitude-only gating sacrificed more broad recovery.

All figures concern known synthetic truth through production composition DXIL.
They do not execute AMD RR or establish that Cyberpunk's particular sea material
has been fixed. In-game acceptance must compare the same scene, albedo controls,
Specular Recovery algorithm and Floor Recovery strength.

## Release validation and cost

Release x64 embeds the validated production shaders. Ten GPU suites passed
346 checks across 1832 dispatches with the D3D12 debug layer enabled and no
validation errors. Full suite records are in `final_validation/summary.json`;
delivery bundles the records in `delivery/validation.json`.

Two order-reversed RX 9070 composition benchmarks at 1505x847 measured:

- ST, accepted history: previous 1.498–1.499 ms; new 1.526–1.528 ms.
- ST, no history: previous 1.156–1.160 ms; new 1.130 ms.
- Full-screen mixed Anchor/ST: previous 4.008–4.024 ms; new 4.141 ms.
- Anchor-only: previous 2.902–2.915 ms; new 2.940–2.977 ms, identical pixels.
- Recovery disabled: approximately 0.060 ms in both, identical pixels.

The arithmetic is not free even without additional texture reads. Mixed-path
cost rises approximately 0.12–0.13 ms; these timings do not promise game FPS.
