# Six supported caller settings; no new repair selected

SOURCE_ONLY_UNEXECUTED. Read-only source/history audit, no payload/numerical/runtime work or production edits.

The exact Fork defaults, in the runner's sidecar order, are:

1. key6 `DISOCCLUSION_THRESHOLD`:0.1; alpha `FfxDenoiserDisocThreshold`.
2. key1 `CROSS_BILATERAL_NORMAL_STRENGTH`:0.5; alpha `FfxDenoiserCrossBlNormStr`.
3. key2 `STABILITY_BIAS`:0.5; alpha `FfxDenoiserStabilityBias`.
4. key3 `MAX_RADIANCE`:40000; alpha `FfxDenoiserMaxRadiance`.
5. key4 `RADIANCE_CLIP_STD_K`:40; alpha `FfxDenoiserRadianceClip`.
6. key5 `GAUSSIAN_KERNEL_RELAXATION`:0.5; alpha `FfxDenoiserGaussKernRelax`.

`OptiScaler/Config.h:542–547` declares these defaults. The frozen af530 runner source, `tools_tmp/fsrd_native_camera_delta_override_adapter_preparation_20261001/frozen_runner/source/source_reference.cpp:138–145`, reads exactly six finite float32 values/24bytes and makes six count-one Configure calls in the above order. The new quality packets reuse the pinned oldJ0 sidecar, not fitted values. Alpha `FSRDFeature_Dx12.cpp:3903–3944` selects queried AMD values or configured Fork values, updates only changed settings, and restores its prior cache on failure so a later frame can retry. `:4201–4215` sends the same count-one public key-value descriptor. User overrides and `UseAmdDefaults` can change production's selected tuple; source defaults do not prove an arbitrary game's active INI.

The primary header `external/FidelityFX-SDK-v2/Kits/FidelityFX/denoisers/include/ffx_denoiser.h:522–541` defines the following limited effects:

- StabilityBias explicitly biases **temporal accumulation toward more stable but less responsive** behavior. This is a documented temporal-quality control. No public formula, response-time/gain guarantee, neutral value or proof that zero removes history is supplied here.
- DisocclusionThreshold explicitly affects **depth comparisons during temporal reprojection**. It is a correspondence/rejection control, not a documented illumination-detail restoration factor.
- CrossBilateralNormalStrength explicitly controls the **cross-bilateral normal term**. No additional spatial-support, frequency-response or detail-preservation claim follows.
- MaxRadiance overrides the **maximum radiance value**. It is not documented as exposure/pre-exposure normalization or a supplied noise estimate.
- RadianceClipStdK sets the **standard-deviation K used for radiance clipping**. The public sentence does not identify its private spatial/temporal stage or turn K into supplied per-pixel noise confidence.
- GaussianKernelRelaxation overrides the **Gaussian kernel relaxation factor**. The public contract does not specify kernel radius, sign/direction of sharpness change or a strength-to-detail-response mapping. Calling it a guaranteed spatial-sharpness fix would infer more than the declaration.

The SDK integration guide repeats these definitions at `denoising.md:619–627`;912–919 states collectively that settings can balance stability/sharpness/noise and recommends starting from queried defaults. This is support for configuring the keys, not evidence that one particular untested setting satisfies the full1 detail/noise conjunction. None of these six is a supplied radiance-variance/noise-confidence resource. The documented reprojected-confidence debug view is not such an input. Key7 is debug-depth-view normalization, outside these six quality settings.

## Closed precedent and decision

`docs/fsrd_default_vector_and_configure_flow.md:11–42` records the matched Fork `[.1,.5,.5,40000,40,.5]` versus queried-provider `[.01,1,1,65504,50,0]` vector experiment. `:44–82` records actual composition and unchanged absolute detail failures for both vectors; the AMD bundle increases dark bias/temporal variation in that fixture. `:84–119` records explicit queried values versus no scalar calls, with between-policy variation at the same scale as repeats and no isolated scalar-call effect. These are bundle/policy results, not individual-key rejection certificates.

`docs/fsrd_additive_residual_independent_lobe_holdout.md:968–972` already closes the alleged stability mismatch: CLEAN and water32 both use0.5; water's bias-disabled label refers to converter Flags54; the AMD tuple's trailing0 is Gaussian relaxation, not StabilityBias. No new mismatch or unwired API was identified.

All six controls are already implemented in alpha. An individually isolated key response remains unmeasured by the bundle controls, but absence of that attribution does not select an operating-point repair. No additional supplied-noise confidence or guaranteed detail-preserving lever was found. There is therefore **no new supported implementation decision or specific untouched candidate selected by this audit**; inventing a value/range/neutral setting would be the prohibited parameter exercise. No defaults, stability, camera, geometry, lifetime or scalar-call control is reopened, and no discriminator/test is proposed. The full1 stain/detail objective remains unresolved.
