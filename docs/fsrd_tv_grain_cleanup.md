> Historical experiment: this filter was removed on 2026-09-23 at the user's request. See [removal and alternatives](fsrd_noise_suppression_retirement.md).

> Historical experiment/build report. Availability, current behaviour and final
> validation limits are documented in the [2026-09-26 checkpoint](fsrd_floor_recovery_release_20260926.md).
> Claims and measurements below describe that experiment, not a new validation run.

# TV residual grain cleanup

The Floor RR Routing selection and Floor Zero Noise experiment are retired.
Normal Floor, surface selection, Anchor and Correlation Mix remain. Original
albedo is still used as a guide; there is no virtual albedo or new history.

## Problem and change

The existing non-local filter cleans the detail reference. Its correlation gate
can correctly reject noisy detail while the reconstructed RR + Skip signal
still contains fine grain. Increasing reference smoothing does not remove that
remaining grain.

Composition now applies a noise-limited correction in selected screen regions
whose current RGB reference is consistent with a locally smooth surface:

- Require all 25 samples in a 5x5 window to be in bounds, valid, and strongly
  consistent in depth, normal and original albedo. The 0.95 surface threshold
  allows the self-dot error of FP16 stored normals.
- Compare reference variance after removing an RGB plane with measured noise.
  Reject structure not explained by that noise, rather than treating RR's blur
  as evidence that the original texture was flat.
- Estimate remaining RR + Skip grain from the median of nine mixed derivatives.
  This annihilates constants, ramps and axis-aligned straight edges. It is an
  estimate of fine stochastic grain, not a perfect reflection/content split.
- Fit RR with a separable quadratic-preserving 5-tap kernel. Its negative
  coefficients preserve curvature better than a Gaussian, but do not by
  themselves guarantee no ringing. Bound the change to twice the measured
  grain sigma and retain the existing supported colour range clamp.
- Scale by Noise Suppression and the selected-surface detail strength. Zero
  Noise Suppression, zero Detail Preservation, invalid references and ordinary
  materials keep the previous behavior. This requires no new menu control,
  texture, frame history or render pass.

The correction is included in DetailCorrection, CompositionBeforeClamp and
CompositionFinal. DetailReference/DetailAnchored still display their named
reference stages; ReconstructedColor shows RR + Skip before the correction.
ScreenGrainCorrection displays only the signed grain correction, encoded as
`saturate(0.5 + correction / max(reconstructed luminance, 0.001))`; neutral grey
means zero correction. As with the existing signed diagnostics, extreme values
can saturate the display.

## Evidence and limitations

`test_fsrd_tv_grain.py` runs production DXIL with independently specified clean
targets and controlled noisy/clean RR images, including moving smooth lights,
ramps, fine RGB texture, clean lines/corners and surface boundaries. Its optional
`--baseline` compares the frozen pre-change composition shader. It does not
execute the AMD model.

`probe_fsrd_smooth_surface_rr.py --routes current --composition-baseline <path>`
also runs the actual Floor conversion and AMD RR. It compares both compositions
against identical RR readbacks, including real Skip. These small synthetic
sequences are not Cyberpunk captures and do not establish in-game acceptance.

Initial paired TV fixture: RMSE 0.0043842 to 0.0024462; motion error 0.0061931
to 0.0034430 (about 44% reduction). The actual AMD RR smooth-light fixture,
24 frames with the second half measured, gives RMSE 0.0054987 to 0.0046019
(16.3%) and temporal error 0.0054761 to 0.0034940 (36.2%). Already-clean smooth
RR and clean thin patterns are separately checked to avoid crediting blur as
noise removal. Dense moving textures remain imperfect in the existing handover;
this targeted correction does not claim to solve them.

Reports and frozen shaders are under `tools_tmp/tv_grain_fix/`. Final validation
and the delivered DLL hash are recorded with the delivery, not inferred from
these initial measurements. A fresh in-game comparison of Screenshot (810)'s
TV under slight camera motion remains necessary. No universal zero-noise or
zero-blur guarantee, temporal improvement percentage in-game, or performance
budget claim is made.
