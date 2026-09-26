# RR distance versus processing scale experiment

> Historical experiment/build report. Availability, current behaviour and final
> validation limits are documented in the [2026-09-26 checkpoint](fsrd_floor_recovery_release_20260926.md).
> Claims and measurements below describe that experiment, not a new validation run.

Date: 2026-09-23. Research only; production shaders and DLL were not modified by this experiment.

## Result

Making the same screen-space signal geometrically nearer did not reproduce the large quality improvement observed in-game. Processing an enlarged signal preserved more structure, but could retain substantially more temporal noise. This is not yet a production denoising solution.

The primary suite used 120 conditions, 48 frames per condition (5,760 actual AMD RR dispatches), on AMD Radeon RX 9070. An initial 192-dispatch pilot and 16 identity-control dispatches were separate. D3D12 debug layer and SDK validation reported zero errors and warnings. Effect DLL file version: 1.2.0.2740; product version: 1.2.0.0. SHA256: `48f1e5888ba6a0a3d59a98b9751e37c392b0f7b8c223d0082d5c1f40642879d3`.

## Controlled inputs

- Baseline: 192x128 full-frame plane at z=20, reflection hit distance 20, constant albedo 128/255, roughness 0.1, fixed perspective camera, zero jitter and geometric motion.
- Near scaled: z=2 and hit distance 2. The world dimensions of the plane implicitly shrink with distance to retain exactly the same screen footprint and RGB input.
- Near depth only: z=2 with reflection hit distance still 20. This isolates primary depth from reflection distance. Static camera provides no reprojection motion to stress this distinction.
- Enlarged: 384x256 bilinear or nearest-neighbor resampling of exactly the baseline noisy frames; same FOV/aspect/depth. Final output is area-downsampled to 192x128.
- Native high control: independently generated 384x256 clean pattern and independent noise samples, then RR and area downsampling. Four samples per final pixel; this additional information is unavailable from simply enlarging an existing frame.
- Direct diffuse and indirect specular were tested separately. No Floor, handover, upscaler, frame generation or production signal split participates.
- Noise sigma 0.035 in linear RGB. Fine noise is independent Gaussian. Coarse noise uses a variance-preserving 3x3 filter. Two seeds for noisy conditions; one for clean controls.
- Scenes: static text/1-, 2-, 4-pixel stripes; untracked scrolling pattern; static clustered noise; noise-free static and scrolling controls; smooth lamp and purple reflection stripe resembling a blank TV.

Only the final 24 frames contribute metrics. Scrolling output is aligned to clean truth before error measurement. Total error is linear RGB RMSE, excluding a four-pixel border. Quiet-region temporal noise is the RMS of per-pixel error standard deviations. Contrast is regression gain against clean truth; 1 means correct contrast, not a percentage of pixels correct.

## Findings

Percentages below are paired changes against baseline, averaged over the two noise seeds where applicable.

1. **Geometric near substitution:** indirect-specular total RMSE changes were approximately -0.01% on static fine noise, -0.15% on untracked fine noise, +0.02% on clustered noise and -0.43% on smooth reflections. There is no useful large near-distance benefit in this fixture.
2. **2x bilinear processing:** total RMSE decreased 19.01% (specular) / 20.50% (diffuse) for static fine noise, 29.16% / 31.37% for untracked fine noise, and 48.71% / 45.73% for smooth reflections. Visual inspection agrees that structure and broad reflection contrast are better preserved.
3. **Remaining noise prevents acceptance:** quiet-region temporal standard deviation increased 194.03% (2.94x) on clustered specular noise and 677.70% (7.78x) on clustered diffuse noise. On untracked fine noise it increased 31.67% / 72.22%. These ratios compare already-denoised small residuals; they are not claims of equal absolute visible severity in-game.
4. **Smooth TV is promising but signal-dependent:** enlarged indirect-specular quiet temporal noise decreased 11.78%, while direct-diffuse noise increased 89.11%, despite both having lower total error. Our production conversion mixes these paths, so an isolated specular win cannot be called a production win.
5. **Sharpness remains incomplete:** static fine-noise specular text contrast gain rose from 0.286 to 0.446, still far below the ideal 1. One-pixel stripes were not faithfully recovered. Clean inputs also blurred, so the lost detail cannot be attributed only to removal of injected noise.
6. **Independent high-resolution samples are different:** static fine-noise specular quiet temporal standard deviation decreased 52.46% in the native-high control. Upsampling does not reproduce the independent sample count. Native-high uses fine white noise even in the coarse scene and must not be interpreted as a matched coarse-noise comparison.

## Verification and limits

Two documented depth-passthrough controls verified signal packing and remodulation independently of the denoiser: max absolute reconstruction error 0.000245095 for both diffuse and specular, consistent with half storage. All primary metrics are finite and outputs nonnegative.

This does not establish the cause of Cyberpunk's near/far behavior. It does not test camera motion, disocclusion, changing ROI coordinates, jitter, varying roughness, mixed-material boundaries, or actual title noise. The high-resolution experiment covers the whole viewport with unchanged projection; a cropped production ROI would additionally need adjusted projection, UV/motion mapping, context/history management and boundary support. No GPU performance acceptance claim is made.

Decision: do not add fake near depth or ship unconditional 2x processing. Retain the scale experiment as evidence that RR's processing footprint matters. Any production follow-up must evaluate noise retention and temporal behavior as well as detail, using the actual diffuse/specular composition.

## Files and reproduction

Test driver: `OptiScaler/shaders/shader_tools/tests/probe_fsrd_rr_distance_scale.py`.
Summary and image generator: `OptiScaler/shaders/shader_tools/tests/summarize_fsrd_rr_distance_scale.py`.
Both use the existing `fsrd_rr_runner.cpp` and actual signed AMD DLL. All generated files remain on F:.

Run with the local Python runtime and `PYTHONDONTWRITEBYTECODE=1`; keep TEMP/TMP on F:, and use new output directories:

```text
probe_fsrd_rr_distance_scale.py --output F:/.../full --frames 48
probe_fsrd_rr_distance_scale.py --output F:/.../smooth --frames 48 --scenes smooth_fine
summarize_fsrd_rr_distance_scale.py F:/.../
```

Results for this run: `tools_tmp/rr_distance_scale/full/results.json`, `smooth/results.json`, `summary.json`, and `verification.json`. Each condition retains its job descriptor, runner log and numerical preview. Large generated binary input/output files are removed after measurement and can be regenerated from the seeds. Input script hashes reflect the executed revision: smooth-scene support was added after the full suite finished, without changing its existing scene generation or metrics.

Visual comparisons: `static_fine_comparison.png`, `untracked_fine_comparison.png`, `static_clean_comparison.png`, `smooth_fine_comparison.png` in `tools_tmp/rr_distance_scale`. Top row shows the last frame with gamma 2.2 for display; bottom row shows signed RGB error at a fixed 4x scale. Display magnification uses nearest sampling and does not change measurement data.
