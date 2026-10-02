# Current Correlation Mix applicability — SOURCE only

Correlation Mix is an existing **post-native total-radiance recovery gate**. It can retain the SDK's quieter result by rejecting correlated reference transfer. It does not alter SDK guides, demodulated SDK signals, or the full1 caller factors. This is source applicability, not a measured quality result or proof of game stain causation.

## Operands and destination

`FSRDOutputComp.hlsl:129–141` reconstructs `R = FloorRadiance(Qs*Rs + Qd*Rd + Skip)`, with `Qs/Qd = lerp(1, original albedo RGB, saturate(strength))`; full1 uses those original factors. `FSRDPreprocessor_Dx12.cpp:1631–1653` binds SDK outputs (or raw signals for disabled lobes), original specular/diffuse albedos, Skip, reference, normal/depth/motion and decision history. Mix acts on this reconstructed whole RGB; output is `FloorRadiance(R + correction)` (`FSRDOutputComp.hlsl:1295`), subsequently stored as half4. Skip is included once in R, not added again to the correction.

The reference is the current floor-seed detail reference, not clean truth: the seed keeps supported current color, selectively rejects impulses, and writes estimated noise sigma in A, or −1 for insufficient surface support (`FSRDFloorSeed.hlsl:397–421`). The converter further disables detail by setting A=−1 on bias/current-color or specular routing, floor-disabled, or detail-disabled pixels (`FSRDInputConv.hlsl:1216–1219`). A is a reference validity/noise field here, distinct from hit-distance and albedo-guide alpha.

## Exact correlation law

For accepted weighted reference P and reconstructed R samples, use luminance means `mr,mp`, centered variances `vr,vp`, covariance `cov`, and corresponding centered chroma moments `vcr,vcp,ccp` (chroma is RGB minus luminance). The common agreement is:

`Kl = saturate((2cov+.001)/(vr+vp+.001) * (2mr*mp+.01)/(mr²+mp²+.01))`

`T=max(4*patchNoise²,1e-6); Kc=saturate((2ccp+T)/max(vcr+vcp+T,1e-6)); E=vcr/(vcr+vr+T); K=lerp(Kl,min(Kl,Kc),E)`.

This is bounded SSIM-like agreement, **not Pearson correlation, a probability, or certified signal/noise confidence**. The absolute stabilizers also preclude an exact general exposure-invariance claim. Source: `FSRDOutputComp.hlsl:566–578,1135–1154`.

In method 0 (Anchor/Correlation/Chroma/Luma), local 5×5 comparison moments combine with broader 9×9 structure/error estimates and estimated reference noise. A surface-weighted 3×3 blurred-reference probe only supplies blur evidence: sufficient fit beyond noise allowances reduces K, opening recovery (`1155–1167`); its colors are not the transferred reference. Validated motion/depth/normal/material/reference-change history stabilizes **scalar decisions**, with reuse≤.5 and previous decision clamped within current±.125; it cannot open a currently rejected decision (`279–342,1169`). Base correction is exactly `strength*S*(1-A)*(1-m*K)*(graft-R)` (`1174–1176`), where S is estimated structural support, A is noise-explained RR agreement, m is saturated Mix, and graft is the anchored current reference.

Method 1 (Light Anchor Mix) uses surface-weighted 3×3 moments. Its contrast-attenuation stand-in multiplies K by `saturate(vr/max(vp-2*.75*patchNoise²,1e-6))`. Its measured-clean opt-out instead sets `mixGate=1`; otherwise `mixGate=1-m*K`. Base confidence is `S*(1-A)*mixGate`, and its delta has an additional noise-support shrink (`345–351,494–540,579–590`). It does not read temporal color or decision history. Thus Mix=1 does not universally close recovery.

In both methods, **m*K also funds supported luma/chroma contrast restoration**, constrained along rays toward the anchored reference and within local RR/reference ranges (`612–642,1203,1257–1273`). Increasing Mix suppresses the base reference blend where K is high but can increase these additional branches. It is not a single monotonic noise-removal strength.

## Material, light and current controls

Recovery eligibility uses flat material-type A, or estimated per-channel `spec/(spec+diff)` shares; flat takes precedence (`146–171`). These weights allocate whole-color correction, not independently measured specular/diffuse illumination. Material detail and lighting can produce the same local statistics; correlation alone cannot establish semantic lobe allocation. Full1 factor law remains intact, but the final corrective blend can still attenuate or replace genuine illumination/detail through noise, structure, anchor and range gates.

Mix defaults to 1 and is finite-clamped to [0,1]; changes invalidate denoiser history. It is forwarded only in composition constants (`Config.h:514–530`; `FSRDFeature_Dx12.cpp:3494–3535,1950–1962`; `FSRDPreprocessor_Dx12.cpp:1607–1612`). Defaults enable flat recovery method 0, with specular/diffuse recovery disabled; enabling those selects method 1 by default. Recovery/detail disabled takes the pure reconstruction fast path (`FSRDOutputComp.hlsl:675–687`), so a quality result from that path cannot qualify current Mix recovery.

The human observation is consistent with the implemented mechanism: Mix can suppress grain that would otherwise return through reference recovery while preserving full1 factors. Source alone cannot establish the necessary clean-light/noisy-error tradeoff. Any parent-selected fixed quality decision must exercise the actual eligible reference/noise and method path and retain the existing hard detail/error gates. This memo authorizes no execution, guide change, strength reduction or parameter scan. `docs/fsrd_pipeline_contract.md:198–316` supports this selective-reconstruction interpretation; historical outcomes in `docs/fsrd_light_anchor_mix.md` are not new measurements of current operands.
