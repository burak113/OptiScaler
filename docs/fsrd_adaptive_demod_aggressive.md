# Retired: Adaptive Specular Demodulation experiment

> Historical experiment/build report. Availability, current behaviour and final
> validation limits are documented in the [2026-09-26 checkpoint](fsrd_floor_recovery_release_20260926.md).
> Claims and measurements below describe that experiment, not a new validation run.

## Retirement on 2026-09-26

The user continued to observe white flashes with adaptive mode enabled and
reported their disappearance when it was disabled. The mask and the final
radiance guard were not accepted as a fix. The entire adaptive runtime path,
option, effective albedo resource, histories and guard were removed at the user's
request. Its INI key is ignored and deleted on save. DemodRisk remains a read-only
diagnostic; DemodProtection is removed. Global albedo controls remain.

The text below records the attempted implementation and its limited local
measurements. It does not describe the current build. The standalone adaptive
stability fixture is retired with the feature. Synthetic or controlled AMD RR
results below did not establish acceptable behaviour in the real game.

## Historical implementation (removed)

Advanced > Input Compatibility contains an opt-in `Adaptive Specular Demodulation`
checkbox. The CP2077 test installation enables it in its INI; the application-wide
default is false. Disabling it restores the previous global modulation path.

The full-strength, original-input DemodRisk classifier supplies seeds >= 0.12.
It never consumes the protected result or local/global modulation strength.
A bounded Euclidean distance transform gives the closest seed distance in render
pixels. Spatial protection is 1.25 * (1 - smoothstep(5,12,distance)); the applied
protection is clamped to [0,1]. Local specular demodulation is exactly zero within
at least 5 render pixels, with a gradual return to the global slider by 12 pixels.
The over-one reserve widens the initial zero core slightly and holds it during dropouts.
At distance >= 12 current evidence contributes no protection. Radii are in render
pixels and do not compensate for resolution scaling. The diffuse slider is unchanged.

Three extra dispatches precede conversion: baseline risk, horizontal squared
distance, and vertical distance plus temporal protection. Each distance axis has
25 taps. Conversion now loads the completed protection field once.
Separate ComputeStates preserve independent constant-buffer/descriptor rings;
scratch outputs transition from UAV to SRV between dispatches. Scratch textures
are distinct from RR output, Floor reference, and temporal histories. Allocation
is lazy and resets with max render-size changes. Two dedicated RGBA16F histories
store protection, signed depth, and an octahedral world normal. History is
reprojected with canonical motion and the render-pixel jitter delta. Four bilinear
taps must have at least 75% valid weight, compatible previous-camera depth (2%,
minimum 0.02 units), and normal dot >= 0.85. No max-neighbour history sampling or
recursive dilation is used. Protection increases immediately and releases by
0.04 per rendered frame: a full core holds six missing frames, then fades,
and disappears completely after about 32 missing frames. This duration is frame
based, not time based. Disocclusions and invalid/out-of-frame motion reject history.

The effective RGB multiplier is quantized once to 8-bit UNORM before any division and
written into a dedicated RGBA8_UNORM output, as required by RR 1.2 (alpha holds local strength). This same
RGB is used as RR specular albedo and by all composition reconstruction and
recovery reference comparisons. Original quantized specular albedo remains in
the original resource for recovery weighting, classification, and history metadata.
Conversion writes and composition reads the effective multiplier in FP32, avoiding
an additional FP16 rounding step on the decoded UNORM values. The initial RGBA16F
allocation was rejected by ValidateRequiredRRResources before every RR dispatch;
the allocation now shares the existing SpecAlbedo format constant.
Original diffuse/specular split weights are not modified. Local strength also
drives the existing bypassed-Floor routing, so the zero region follows the current
zero-slider signal routing rather than reintroducing the removed specular share
through Floor. Existing reconstruction remainder handling is retained.

Enabled-mode RR guides now follow the effective multiplier (including at partial
global slider values). Disabled mode retains the historical original-guide
behavior. This is an intentional experimental change, not just a display mask.
Toggling the option resets RR, Floor and protection history. Render-size, source
layout and interpretation changes also reset protection. DemodRisk/DemodProtection
use their own saved camera and jitter so skipping RR in those debug views does
not disable mask stabilization. Explicit title resets still clear that history.
Spatial expansion has no geometry veto, so its current-frame region may cross
an object silhouette; temporal reprojection does validate geometry. The classifier
is heuristic and stable false positives can retain protection until its bounded release.

`DemodRisk` still displays the baseline classifier. `DemodProtection` displays
the applied protection fraction: white is zero local demodulation, gray is the
transition, black is the unmodified global strength. With the global slider at
zero the protection debug view is black because the entire image already uses
zero strength. `None` displays the actual rendered result.

Validation: test_fsrd_demod_stability.py executes production DXIL on the RX 9070.
It checks weak seeds, exact-zero core, fade bounds, flicker/dropout sequences,
camera movement/translation, subpixel movement, jitter, disocclusion, invalid
motion, unity UNORM guide, identity reconstruction and the disabled path. These
are synthetic fixtures, not AMD RR or Cyberpunk image-quality acceptance.
The mirror checker covers constants, resource order/counts and flags. The GPU
harness now binds the optional slots: conversion 18 SRVs/9 UAVs; composition
13 SRVs/3 UAVs. Constant-buffer layouts are unchanged. The protection pass reuses
t10 for its private history input and u0 for its private output; normal conversion
restores the resource inspector binding and uses its original production UAVs.

## Adaptive radiance flash guard (2026-09-26)

Mask stability and matched current-frame division/remodulation do not remove RR's
internal history in the previous divisor scale. A controlled RX 9070 test using
the bundled AMD denoiser DLL, constant 0.15 radiance, and a divisor change from
5/255 to 1 produced a remodulated peak of 2.115234375. A 1.15x-per-frame divisor
ramp still peaked at 0.332536787. This establishes a temporal scale-change failure
in the controlled case, not a complete diagnosis of every Cyberpunk artifact.

Composition now also reads the existing pre-RR specular signal (t12). At pixels
where adaptive protection lowers local strength below the global slider, it
remodulates current raw samples with their own effective RGB divisor. A 3x3
depth-compatible neighbourhood supplies maximum luminance and maximum RGB
component, each with 5% headroom and a 1e-5 numerical allowance. Denoised specular
is uniformly scaled down only when it exceeds either ceiling. This preserves
hue, never increases RR radiance, and never blends raw noise into the output.
The peak-component ceiling matters because a luminance-only bound can retain
large coloured channel excursions. No fixed HDR ceiling or spatial colour
average is applied. Diffuse and skip are added after this guard.

The guard is shared by reconstruction and recovery comparisons, so recovery
does not use the unbounded stale specular value as its base. Disabled adaptive
mode and pixels with unchanged strength retain the previous arithmetic.
Unremodulated denoiser debug outputs remain unguarded. One extra dispatch reuses
the RGBA16F risk scratch texture after conversion has consumed it; no new texture
or history is allocated. The guard scales the demodulated RR value directly,
preserving untouched texels exactly, before composition performs remodulation.
Recovery reads this prepared result rather than repeating the neighbourhood
bounds for every recovery tap. Dedicated descriptor/constant-buffer state and
SRV/UAV transitions separate the guard and composition dispatches. Existing
RGBA8_UNORM RR guide validation remains intact.

Limitations: neighbourhood maxima are conservative and can admit noisy bright
samples. Conversely, a valid historical highlight unsupported by any current
3x3 sample can be reduced. This is a targeted anti-flash guard, not a general
specular denoiser or a repair of RR's private history. The real game scene still
needs visual acceptance under camera motion.

Reproduction and checks are in tools_tmp/demod_flash_20260926: probe.py records
actual AMD RR sequences; check_guard.py replays them through old and new
production DXIL on the GPU, and tests narrow coloured HDR peaks, hue, geometry
separation, inactive-path equality, and all recovery/noise-removal selections.
The controlled peak after the guard is 0.157470703125 (target 0.15).

At 1505x847 on the RX 9070, 50-dispatch synthetic timing runs measured combined
guard + composition overhead of roughly 0.11-0.17 ms for a sparse protected
strip, and 0.24-0.26 ms with every pixel protected. Adaptive-off timing stayed
within run-to-run variation of the prior shader. These are dispatch measurements,
not a promise about full-game frame time. The earlier inline candidate repeated
the bounds in recovery taps and cost about 1.9 ms in the fully protected light
recovery fixture; that candidate was not installed.
