# Job 07 mechanism and source audit

## Decision supported by this audit

The source and packaged observations support an **observable-only guide diagnostic**, kept as research. They do not justify changing normals, material categories, roughness, hit distances, or the protected working denoiser settings. A scalar uncertainty field may identify inconsistent observations; it cannot establish that a pixel is foliage or that its observed dominant guide is wrong. The candidate's CPU experiments and independent review must establish the useful and failure cases separately from this source audit.

This document was produced by the mechanism investigator, independently of candidate tuning. It describes code inspection and CPU inspection of frozen input words; **no GPU, AMD RR, build, or game execution** is attributed to this investigator. The immutable handoff commit is `5d7839a930106cf8fe1ba8dbbc6750509e7f26a8`; the separately audited production source commit is `87e8b7ab2a428bd91d3c044decf7d4dbccd8cefd`. Exact inspected-source and fixture hashes are in [source_audit.json](evidence/source_audit.json).

## 1. What the native pipeline actually carries

### Guide encoding and material categories

The bridge binds normals as `R10G10B10A2_UNORM`. In the exact packed word, bits 0–9 and 10–19 are octahedral normal coordinates, bits 20–29 are **linear roughness**, and bits 30–31 are a two-bit categorical code. The normal is in world space. Decode each ten-bit coordinate by dividing by 1023, transform `uv` to `2*(uv-.5)`, construct `(x,y,1-|x|-|y|)`, unfold the negative hemisphere by adding `-t` to nonnegative x/y and `+t` to negative x/y with `t=max(-z,0)`, then normalize. This follows the actual helper used by the bridge. A temporal observer of these world normals must not apply another view-space rotation. [S1][S2][S3]

Native categorical A is an equality code used by the title's spatial/temporal taps. `preserveNativeMaterialIDs` is an independent, default-false experiment; `CameraReserved.x` selects preserving A or emitting zero. This is a source-proven branch, not evidence of foliage or glass semantics. Source category 3 has a special white-material fallback because a later compositor branch can replace base colour using unavailable constants. The fact that categories 0–2 are admitted by `NrdNativeMaterialKnown` does not assign vegetation semantics to any of them. [S2][S4][S5]

Optional native material capture reads the same-writer base-colour and parameter bindings under state/generation/birth proofs. Base RGB is squared, metallic is parameter R, and the newer two-output capture also copies roughness G. Half values are explicitly rounded to nearest even before the typed FLOAT store. The bridge generates diffuse material guide `baseRGB*(1-metallic)` and a documented GGX approximation for specular albedo. Only this approximate specular guide squares linear roughness to its GGX alpha. The source material guide may use a .04 floor on separately captured raw material roughness while preserving the provider normal's B component. Albedo outputs are RGBA8_UNORM. None of this capture reads or divides the physical noisy D/S. [S4][S6][S7][S8]

Consequently job07 must not introduce a material tag, normal flattening, a roughness class, or a hidden alpha channel as a carrier for uncertainty. Changing categorical A also changes the bridge's history policy: material-option changes reset bridge histories. [S5]

### Geometry transport is separated from validity

The geometry-only entry points are wrappers around `FSRDNrdBridgeGeometry.hlsl`; the material and material-parameter variants simply add compile-time feature defines. This geometry pass reads native normal/depth, writes positive native ViewZ and signed near/far-clamped RR depth, then defers motion until the current native Temporal binding is proven. It does not read lighting. [S2][S8]

There is already a separate raw-depth validity texture: HLSL declares `RWTexture2D<uint> OutValidity`, and the host allocates it as **R8_UINT**. Its low two bits distinguish finite in-range, below-near, above-far and nonfinite source depth; bit 2 records an originally negative signed value. This is useful precedent for an independent diagnostic resource, but it is not spare storage for job07. The clip package omits this native raw-depth class and positive ViewZ. Recomputing validity from already clamped RR depth cannot reconstruct whether the original sample was clamped. [S2][S8]

Captured motion RG is full-render UV displacement toward the previous frame, not pixels and not crop-relative UV. B is a signed previous-minus-current linear-depth quantity. The correct previous local coordinate is:

```text
q = current_local + current_crop_origin
    + motion_RG * original_render_extent - previous_crop_origin
```

All bilinear taps must exist in the preceding crop; first frame and outside-crop history are unsupported. Published clips require finite `0 <= qx < width-1` and `0 <= qy < height-1`. Clamping or looping fabricates observations. [S3]

### Original input, provider input and recovery are distinct

`RRWrapper::RecordOwnedImpl` copies `sourceInput` into a working `input`. Native Anchor can replace only working D/S with leased private physical-unit textures. The RR provider and lobe recovery/NZR then receive those private physical inputs. In contrast, G3 `LightingGuard.Before` explicitly receives **sourceInput.diff/spec**, preserving its original-input evidence. A diagnostic must not move that reader onto a candidate-corrected signal. [S9]

The actual denoiser dispatch binds depth, motion, normal/roughness, diffuse albedo and specular albedo, plus the D/S signals through their signal descriptors. There is no separate guide-uncertainty resource in this examined dispatch ABI. G3 is not an uncertainty input: its light-change pass can deliberately replace motion B with a bounded finite sentinel to reject history after its own confirmation logic. Copying this intervention for normal variability would conflate lighting, geometry and support assumptions. A sidecar can be recorded for job04/job08 without changing the AMD dispatch. Any later intervention needs a separate local acceptance result. [S9][S10]

The trace records actual provider normals and motion. When Flat Albedo Recovery changes the provider guide, it exports `recovery_original_normal_roughness` separately. Here “original” means the owned bridge input before Flat Albedo Recovery, not a per-sample native GBuffer dump: bridge conversion may already have zeroed categorical A when preservation was disabled. It also records Anchor's optional mixed-extent gain witness without renumbering existing trace roles. This is the model for a future separate job07 trace role with explicit extent, frame/context, and source authority. [S11]

## 2. Package inventory and measured word-level facts

The three clips contain original typed **tensors**, not rendered videos or final game frames. Each has ten image roles: depth, motion, provider packed guide, original packed guide, physical D/S inputs, raw RR D/S, selected RR D/S. Additional arrays preserve capture-frame indices, original provider controls, crop provenance, render extent, camera matrices and positions. The selected RR result is old recovery output, not converged truth. The package has no semantic segmentation, per-sample coverage, per-layer material/motion, albedos, random-seed/sampling witness, or complete pre-start history. [S3]

| Clip | Capture frames | Width × height | Global crop origin | Original render |
|---|---|---|---|---|
| `foliage23` | 43–65 | 192 × 64 | (752,423), fixed | 1505 × 847 |
| `facade16` | 34–49 | 96 × 96 | (688,359), fixed | 1505 × 847 |
| `bottle_track7` | 180–186 | 128 × 256 | x=688; y=160,176,208,272,384,480,560 | 1505 × 847 |

These are source-selected crop names, not per-pixel semantic labels. The bottle mask also includes hand/arm; the foliage band contains multiple layers; the facade tile is not the earlier whole-ROI facade calibration mask. Changing the bottle crop is not itself camera or object motion. [S3]

CPU inspection of every supplied original and provider guide word gives:

| Clip | Fixed denominator | Changed normal bits 0–19 | Changed roughness bits 20–29 | Changed category bits 30–31 |
|---|---:|---:|---:|---:|
| Foliage | 282,624 | 0 | 526 | 0 |
| Facade | 147,456 | 0 | 1,090 | 0 |
| Bottle | 229,376 | 0 | 152 | 0 |

All original category codes **within these three exported tiles** are zero. The manifest separately attests all published 2405/87ee categories are zero; no whole-capture category statement is made for f2ef. These measurements are in [source_audit.json](evidence/source_audit.json). The lower-30-bit differences are entirely roughness differences. They must not be described as evidence that the bridge modified or misdecoded normals. Conversely, bit identity does not prove the original native writer's physical normal was correct; both copies may preserve the same wrongly interpreted source.

Provider controls retain 46 uint32 words of the native ABI suffix. Words 40/41 decode near/far as approximately .02 and 65504, words 42/43 are render extent, word 44 is the SDK frame counter, and word 45 is flags. All three windows have flag 2 (NON_GAMMA_ALBEDO), no recorded RESET. SDK counters are consecutive but differ from capture indices: foliage 34893–34915, facade 15103–15118, bottle 20946–20952. No missing history can be inferred from a first exported capture frame. The source trace supports QPC metadata, but these NPZs omit timestamps and frame durations, so temporal metrics are per frame rather than per second. [S11]

Observed input_motion.w is 1 throughout all three tiles; no motion-B absolute value of 65504 is present. Nevertheless, the exported role is provider motion, and the package does not give a separate pre-G3 raw motion array. No claim about that missing source should be based only on the absence of the known sentinel. [S9][S11]

### Glass and portable calibration

The glass fixture covers 87ee frames 46–63, a 192×160 crop at source-ROI coordinates [50,180,242,340], with **6,497** fixed common-mask pixels. It stores camera-aligned raw specular RGB, bit-preserving XOR reconstruction of aligned selected specular RGB, and aligned equal diffuse RGB. Depth, packed guides and motion remain **unwarped**. In particular, the glass manifest maps `original_normal_roughness_u32` to `frames/*/input_normal_roughness`: it contains provider/prepared guides, **not** pre-Flat `recovery_original_normal_roughness`. “Original” in this glass array name means the unwarped stored crop, not original guide authority. A guide-only glass control must label this prepared-guide limitation and use an unwarped fixed rectangle/geometry mask, never the aligned common mask. Pairing original unwarped guides directly with aligned RGB would misregister evidence. There are no physical noisy D/S inputs or input hit-distance alpha in this glass subset. The separate historical full-ROI mask has 8,048 pixels and must not replace the small fixture's denominator. Its alignment is reference-depth camera reprojection without dynamic-motion or source-depth occlusion compensation. [S12]

`portable/anchor` contains frozen estimator code, recalled—not raw ring—keys, stats/gain/masks and recorded actual shader grids. Those fields can calibrate the packaged estimator but cannot test a new foliage guide transport. `portable/colour` has a single captured frame 63 whose preceding history was CPU-warmed; it also has useful synthetic edge, quantization and rejected-soft2 controls. Neither is a chronological raw foliage-guide dataset or a new GPU execution. [S13][S14]

## 3. Competing causal hypotheses and separating experiments

Each row is a falsifiable family, not an asserted explanation of the recorded foliage.

| Hypothesis | Prediction under controlled intervention | Falsifier or competing outcome | Extra observation needed locally |
|---|---|---|---|
| H1: changing coverage chooses a different dominant guide while light integrates layers | With fixed per-layer geometry/light, varying subpixel phase or stochastic coverage changes the observed guide and its disagreement with aggregate light. A layered oracle remains interpretable while one guide does not. | At fixed lighting statistics, eliminating coverage changes fails to reduce the effect; or the same error occurs on homogeneous known-normal patches. | Same-view phase-controlled sequence; raw writer normal/depth and coverage/alpha-test witness where accessible, plus per-layer or known-geometry control. |
| H2: decode or quantization is wrong | Known homogeneous normals produce systematic angular error, including oct fold/hemisphere cases, independent of coverage and noise. | Exact shader/CPU decode agrees within the established storage bound across known normal controls; coverage-dependent disagreement remains. This rejects that tested decoder, not every native-writer hypothesis. | Native writer/output bit witness, actual bound format and preservation mode, known normal/depth/roughness controls and shader identity. |
| H3: guides are valid; sparse, heavy-tailed or temporally correlated lighting dominates | Hold guides fixed and vary only the distribution/temporal correlation of noisy D/S. Grain/sparkle/flicker changes despite an invariant guide sidecar. | A guide-specific action removes the effect at controlled lighting statistics while preserving light response and detail in every boundary control. | Unmodified physical D/S separated by lobe, history/sample metadata if available, and fixed geometry/light versus controlled light-change sequences. |
| H4: a single MV transports one layer but not their composite | With exact per-layer motion, the layers align separately while a composite single-MV warp leaks or invents support. Failure increases with relative motion or visibility changes. | The same error persists after fully controlling correspondence and visibility, or scales only with noise statistics rather than layer-relative motion. | A known-motion thin foreground over static textured background, original pre-G3 MV plus provider MV, camera/jitter convention and visibility truth. |
| H5: the apparent gain is detail destruction | Flattened/EMA-smoothed normals or blur can reduce a coarse flicker score while decreasing rigid-facade normal/edge transfer and fine texture contrast. | A proposed action improves fixed-support grain/sparkles/flicker without losing phase/orientation worst-case detail, coverage edges or true-light response. | Exact historical facade/text control BASE/candidate native outputs and matched videos; synthetic known texture permits a cheaper initial rejection. |

Freeze geometry/coverage masks and every error denominator from BASE or synthetic truth before examining the candidate. Report support loss explicitly; pixels removed from candidate support stay in evaluation. Surface category equality is useful as a compatibility check but, with every observed code zero, does not establish layer equality.

The minimum discriminating synthetic experiment needs two independently movable thin layers over a textured rigid facade. Hold the diffuse/specular mean fixed while changing one family at a time: phase, thickness, orientation, overlap, normal quantization, inter-layer motion, or noise correlation. Include a known-normal homogeneous plane, textured windows, sky gaps and near/far boundaries. Analyze truth light/coverage separately from its single-guide observation. A perfect-guide/per-layer-motion oracle is an ablation, not a production input.

## 4. Why a useful sidecar still cannot classify the cause

The suggested observable is a bounded local angular-dispersion statistic together with motion-compensated angular innovation, an explicit valid-support count/flag, and source provenance. Spatially varying normals alone are also produced by valid facade geometry or bump maps. Temporal innovation also occurs when a single-layer correspondence is wrong. Lighting can flicker with perfectly stable guides. No scalar built from these observations is therefore a probability of foliage or a universal denoising confidence.

An identifiability witness makes the limit concrete. A fully covered front-facing surface and a majority front-facing layer over a minority differently oriented layer can emit exactly the same dominant normal, depth, category and motion. Their radiance can also agree under chosen per-layer material/light values. If the minority layer is unobserved, an observer of those aggregate inputs must emit the same result for both worlds. Even a perfectly implemented sidecar cannot recover the hidden mixture fraction or its correct per-layer history. A generator should include this pair, not only favourable edge cases where changing normals reveal the answer.

Unknown support must not be serialized as a confident zero: return an explicit unsupported flag and force **unchanged consumer behavior**. Keep current spatial support separate from temporal history support. Use the original guide lineage for the observation; if any provider-prepared variant is also reported, label it as such. Job04 may transport the sidecar only with the same frame/context/crop and its validity; job08 may consume it only through an explicit, versioned adapter. There is no justified production mapping into native category A, roughness B, signal alpha or motion B/W.

## 5. Surgical remaining data and local gate

The existing clips are useful and should not be requested again as if absent. The missing facts fall into three smaller requests:

1. **Provenance supplement for the existing foliage crop.** For 87ee source frames 43–65 at global origin (752,423), 192×64 within 1505×847, export both original pre-G3 and provider motion, actual provider albedos, native raw depth/validity if available, and optional native base-metal/raw-material-roughness witnesses. Retain each original format, original controls/settings and frame SDK/capture mapping, source SHA256 and bytes before any conversion. Add crop halo only if a subsequent observer needs it. Existing guide/D/S/RR arrays should be referenced by their hashes, not silently replaced. These additions distinguish guide preparation, G3 history rejection and missing material modulation from guide mixture. At 31 extra bytes/pixel for MV8 + albedos8 + raw-depth4 + validity1 + base-metal8 + raw-material-roughness2, 23×192×64 costs approximately **8.36 MiB** before compression, plus small metadata. Unavailable roles must remain null.
2. **Known-normal and known-motion control.** A small 64×64 calibration can cover homogeneous world normals across oct folds and a thin alpha-tested card moving over a textured rigid background. Use a chronological 16-frame sequence per control, explicit current/previous camera matrices, jitter, render extent, original/native guide bytes, original and provider MV, physical D/S and actual raw/selected RR. Preserve RESET/startup flags. At 84 bytes/pixel for two packed guides (8), signed depth (4), original/provider motion (16), provider albedos (8), physical D/S (16), and raw/selected RR D/S (32), each 16-frame 64×64 sequence is about **5.25 MiB**; exact bytes should follow actual included roles. If the game cannot expose per-layer/coverage truth, record that impossibility and do not claim this resolves H1/H4 completely.
3. **Actual native A/B with the historical facade/text failure.** The diagnostic itself should first execute with identity/OFF and ON behavior that leaves all original provider inputs bitwise unchanged, while producing a separate observation. Use the original frozen masks and chronological context, preserving D16/S256, G2/G3 and NZR settings. Request per-pass GPU timing/memory scope, D3D lifetime/debug results, and matched final-view video. A later intervention must run as a separate candidate against the same actual native path and fail on new sparkle, worse fine flicker, lost facade/text contrast, sky leakage, layer trails or delayed 1.1/1.25× true-light response.

The source audit does not nominate the diagnostic as a foliage fix. Its purpose is to preserve valid geometry while exposing where the available evidence is inconsistent or absent. A successful CPU benchmark is evidence about that modeled construction; the local GPU/game gate remains open.

## Source references at the immutable handoff

[S1]: https://github.com/burak113/OptiScaler/blob/5d7839a930106cf8fe1ba8dbbc6750509e7f26a8/OptiScaler/shaders/fsrd_preprocess/precompile/FSRDPreprocessCommon.hlsli#L32-L58
[S2]: https://github.com/burak113/OptiScaler/blob/5d7839a930106cf8fe1ba8dbbc6750509e7f26a8/OptiScaler/shaders/fsrd_preprocess/precompile/FSRDNrdBridgeGeometry.hlsl
[S3]: https://github.com/burak113/OptiScaler/blob/5d7839a930106cf8fe1ba8dbbc6750509e7f26a8/research/astra20261020/fixtures/clips/README.md
[S4]: https://github.com/burak113/OptiScaler/blob/5d7839a930106cf8fe1ba8dbbc6750509e7f26a8/OptiScaler/shaders/fsrd_preprocess/precompile/FSRDNrdMaterialGuides.hlsli
[S5]: https://github.com/burak113/OptiScaler/blob/5d7839a930106cf8fe1ba8dbbc6750509e7f26a8/OptiScaler/shaders/fsrd_preprocess/FSRDNrdBridge_Dx12.cpp
[S6]: https://github.com/burak113/OptiScaler/blob/5d7839a930106cf8fe1ba8dbbc6750509e7f26a8/OptiScaler/shaders/fsrd_preprocess/precompile/FSRDNrdNativeMaterialParamsCapture.hlsl
[S7]: https://github.com/burak113/OptiScaler/blob/5d7839a930106cf8fe1ba8dbbc6750509e7f26a8/OptiScaler/shaders/fsrd_preprocess/precompile/FSRDNrdMaterialQuantization.hlsli
[S8]: https://github.com/burak113/OptiScaler/blob/5d7839a930106cf8fe1ba8dbbc6750509e7f26a8/OptiScaler/shaders/fsrd_preprocess/FSRDNrdBridgePass_Dx12.cpp
[S9]: https://github.com/burak113/OptiScaler/blob/5d7839a930106cf8fe1ba8dbbc6750509e7f26a8/OptiScaler/shaders/fsrd_preprocess/FSRDNrdBridgeRR_Dx12.cpp
[S10]: https://github.com/burak113/OptiScaler/blob/5d7839a930106cf8fe1ba8dbbc6750509e7f26a8/OptiScaler/shaders/fsrd_preprocess/precompile/FSRDNrdLightingGuardApply.hlsl
[S11]: https://github.com/burak113/OptiScaler/blob/5d7839a930106cf8fe1ba8dbbc6750509e7f26a8/OptiScaler/shaders/fsrd_preprocess/FSRDGameTraceSession.cpp
[S12]: https://github.com/burak113/OptiScaler/blob/5d7839a930106cf8fe1ba8dbbc6750509e7f26a8/research/astra20261020/fixtures/glass/README.md
[S13]: https://github.com/burak113/OptiScaler/blob/5d7839a930106cf8fe1ba8dbbc6750509e7f26a8/research/astra20261020/portable/anchor/README.md
[S14]: https://github.com/burak113/OptiScaler/blob/5d7839a930106cf8fe1ba8dbbc6750509e7f26a8/research/astra20261020/portable/colour/README.md
