# Correlated grain regression and water diagnosis

> Historical experiment/build report. Availability, current behaviour and final
> validation limits are documented in the [2026-09-26 checkpoint](fsrd_floor_recovery_release_20260926.md).
> Claims and measurements below describe that experiment, not a new validation run.

User game feedback rejected the `volume_visibility` candidate: coarse boiling
noise in shadows/reflections and newly revealed regions persisted or increased.
Screenshot 818 is DenoiserBypass; 817 is None, not a Floor on/off pair. The user
separately reports poor water with Floor both off and on.

## Confirmed regression and correction

The candidate's spatial ridge lift and reduced filter uncertainty treated
neighbour agreement as evidence of clean light. Previous tests covered isolated
impulses, 2x2 clusters and independent per-pixel noise, but not broad correlated
patches. That test coverage was insufficient.

`test_fsrd_correlated_grain.py` adds eight-frame independent sequences at three
spatial correlation scales. Clean radiance is constant and known; noisy positive
illumination is generated separately. Production seed and all five filter
dispatches run on the GPU. The metric is positive Floor excess above clean
radiance: even a perfect nonnegative residual RR output cannot subtract this
bypass contribution. This test does not execute the AMD model.

Rejected/current-versus-accepted RMS results before correction:

- Scale 2: 0.027158 versus 0.004940; temporal deviation 0.022969 versus 0.002755.
- Scale 5: 0.039922 versus 0.011397; temporal deviation 0.032419 versus 0.007118.
- Scale 12: 0.049252 versus 0.022004; temporal deviation 0.039263 versus 0.015955.

The repair removes the ridge lift, restores IQR base uncertainty and the accepted
filter support. After correction these fixtures match the accepted baseline's
metrics exactly: 55-82% less excess RMS than the rejected candidate. This is
regression removal, not proof that the accepted baseline has zero grain. Broad
noise can still survive its conservative spatial pedestal.

The five-to-nine-sample smooth surface-support transition and the validated
bilinear screen decision-history footprint remain. They address reproducible
discontinuities but have not eliminated all game disocclusion flicker. No new
temporal radiance buffer, quality setting or resource is added. Selected-screen
Anchor/Correlation Mix/luma/chroma equations are unchanged.

The clean narrow-light retention targets introduced with the rejected feature
are retired explicitly. The fixtures still report retention, bounded radiance
and optional baseline comparisons; the ordinary-volume tests remain mandatory.
We accept losing the rejected candidate's synthetic thin-light gains to avoid
shipping increased grain in real shadows/reflections. Correlated-noise budgets
are now part of the standard validation runner; optional accepted-DXIL comparison
additionally checks no RMS/variation regression.

## Water: evidence versus hypotheses

The captures show smoother wave structure and broader mottling in normal output
than in bypass. They do not isolate RR from conversion, composition and upscaling.
The separate Floor-off observation rules out Floor being the sole source.

Current conversion divides composited radiance into diffuse/specular signals by
albedo reflectance ratio. It cannot recover the game's original, separately
evaluated water reflection/refraction components from that one RGB value.
Automatic specular mode chooses indirect when a validated hit-distance resource
exists; this is a resource-level test, not proof that every water pixel has a
meaningful reflected hit. For indirect input the converter scales ray distance
by roughness tracking and falls back to primary view depth when the ray length
is invalid. These are concrete inspection points, not established causes here.

AMD's [RR input and motion documentation](https://gpuopen.com/manuals/fsr_sdk/techniques/denoising/)
specifies signed depth, motion including depth delta, normals/linear roughness,
albedos, and valid ray distance for active indirect specular. It also recommends
motion coverage for alpha-blended and procedurally animated content. Animated
water and reflected images need not move like their primary geometric surface.
Inadequate guides, mixed signal content and subpixel wave structure are plausible
causes of noise/blur; the screenshots do not establish which applies.

Useful causal game A/B: Floor off, None, Auto versus Direct Specular Signal,
then restore Auto. Direct removes indirect hit-distance tracking from that path;
an improvement would implicate the path, not prove that distance alone is wrong.
The user tried this A/B and reported no clear improvement or a worse result.
Thus indirect hit-distance tracking alone is a weaker explanation; no permanent
signal-mode override is justified by this result.
Next focused captures are InNormals, InputRoughness and SpecularHitDistance at
the same sea view, followed by ReconstructedColor versus CompositionFinal if
the indirect/direct A/B is inconclusive. No global water roughness/albedo override
is introduced without those observations.

Artifacts and logs live under `tools_tmp/coarse_grain`; the rejected shaders are
frozen in `rejected_precompile`. Accepted reference is the prior
`tools_tmp/volume_visibility/baseline/precompile` snapshot, verified in the prior
package to match the accepted screen-only DLL.

Release x64, shader compilation and mirror verification pass, together with
749 GPU checks over 1,721 dispatches under D3D12 validation. Two optional historical
archive suites are explicitly skipped because their packages were not supplied.
The separate accepted-baseline coarse-noise A/B passes all six comparisons.
Package: `tools_tmp/coarse_grain/delivery/dxgi.dll`; its manifest verifies that
the DLL embeds the exact tested shader bytes. In-game grain/disocclusion acceptance
and the water diagnosis remain open; no new performance claim is made here.
