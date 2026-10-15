# RR chroma experiment — research only

Bu aday üretime veya menüye bağlı değildir. Geçmişle uyumlu komşulardan destek
alan tekil chroma uç değerlerini RR öncesinde sınar; tüm sonuç ışığı gerçek RR'a
girmelidir. Native hit-distance alpha ve rehberler değişmez. Kalıcı ince renkli
çizgiler CPU testinde bit düzeyinde korunur; yeni beliren gerçek tek renkli nokta
ile aynı örnekleri üreten parazit ayırt edilemez. Bu olumsuz örnek açıkça
raporlanır. GPU/gerçek sağlayıcı kalite ve maliyeti henüz ölçülmedi.

## Contract and proposed native harness seam

`nrd_rr_chroma_condition.hlsl` and `nrd_rr_chroma_condition_fixture.h` are separate
test assets. They do not change production shaders, the RR ABI, SDK defaults,
normal space, motion, hit distance, albedo or final Consumer encoding.

The native helper is included **after** the existing real-wrapper fixture. Its
`Record(Host&, shared_ptr<Kernel>, RawFrame current, RawFrame previous,
RawFrame older, Targets, Parameters)` retains only fixture-owned resources,
complete PSO/root/device/descriptors and both owned outputs in the existing GPU
lease. It must not be used as a production title-resource lifetime adapter.
Source state is NPS; result/evidence state is UAV. After recording, the caller
transitions only the owned result to NPS and substitutes `converted.spec/diff`
for the unchanged real `RRWrapper::Dispatch`. All five guide pointers/bytes and
input alpha words remain identical. No raw radiance is copied after RR.

The baseline must skip construction/recording of this helper entirely. A
shader Mode0 exists only for independent GPU identity checks. Native bindings:

- Root0: 12 unpacked 32-bit constants, exactly the 48-byte `Parameters` POD.
- Root1: SRV t0..t10, current/previous/older signal; corresponding three depths;
  corresponding three packed normals; current/previous RR-ready motion.
- Root2: UAV u0 conditioned RGBA16F and u1 owned RGBA32_UINT gate evidence.
- Root cost14 DWORDs, no sampler. Each thread owns one result/evidence texel;
  every neighboring sample comes from a distinct immutable source resource.

Missing histories bind current/previous owned resources as valid descriptors;
`historyCount` prevents their use as historical evidence. A full ordered raw
history is mandatory. Never seed history with conditioned output. Reset/gap,
size/resource-domain changes and discarded recordings require history removal.
The current source helper does not implement the production history manager.

## Fixed, falsifiable candidates

Candidate0 is unchanged RR. Candidate1 uses one raw frame of temporal support.
Candidate2 requires two, composing the previous motion to reach the older
sample. Same inputs, reference, provider defaults/settings, signal route and
physically fresh context are required for every candidate. Same-frame motion
variants must be compared separately; do not silently repair motion here.

For each active finite center, collect eight neighbors satisfying depth,
octahedral-normal, roughness and material-ID agreement. At least five valid
neighbors are required. An isolated luma feature is an identity path. Compute
componentwise normalized opponent-chroma median and median absolute deviation.
Clamp chroma only if it lies outside `median +/- max(.05, 3*MAD)` and reprojected
raw histories both agree with the same spatial support. History depth is tested
against `currentDepth + motion.B`, never previous visible depth as a predicted
surface position. Disoccluded, out-of-range, nonfinite or incompatible history
is an identity path. Nearest-pixel sampling is explicit, not an assertion about
the provider's private sampling footprint or reflected-object motion.

The exact Consumer-compatible opponent transform is used as internal math:
Y=(R+2G+B)/4, Co=(R-B)/2, Cg=(-R+2G-B)/4. This is unrelated to the live title
output color mode; RR still receives RGB. Before storage, limit chroma along
the gray axis so RGB stays in [0,65504] at the same mathematical Y, then use the
existing explicit IEEE half-RNE helper. Half quantization permits a bounded Y
change; it does not permit a claim of exact stored luma. Alpha has no arithmetic.

## Required actual-provider evidence before adoption

The 15e immutable64-frame oracle has known reflection detail, chroma impulses,
object-depth motion and disocclusion truth. Compare unchanged RR, candidates1/2
and raw noisy input against that independent truth with identical RGB/guides.
Report reveal-age tail error, reprojection-valid chroma error/change, bias and
thin-detail gradients, including worse rows. Native root/table Consumer checks,
opaque alpha, source/guide hashes, two physical RR signals, context retirement,
cancel/failure and strict debug errors/warnings must remain strong. Gate counts
must be reported by motion/disocclusion region so the candidate cannot pass by
disabling during all pans. It must not use the reference image for admission.

Persistent colored point/line/step and an isolated bright line are bit-exact in
the CPU properties. The deliberately adverse first-appearance point changes two
RGB components because it is observationally identical to the chosen impulse.
Thus **no universal true-detail preservation or game-quality gain is claimed**.
Any measured benefit must be weighed against this real ambiguity. Production
gating is not authorized by a CPU property pass.

Two-level raw history would require four RGBA16F radiance textures, four R32/
RGB10A2 depth/normal textures and one RGBA16F previous motion: 56 logical bytes
per pixel. The two conditioned signals add16; test evidence adds32 for two
lobes and should be omitted from a production design. This is a derived lower
bound, excluding resource alignment/metadata, not measured committed memory.
One-level raw history plus outputs is40 logical bytes/pixel. Measure both
1505x847 and2560x1440 GPU cost and warm allocations before any menu proposal.

## Hit/no-hit boundaries and primary sources

AMD1.2 exposes DD, DS, ID, IS, AO, specular occlusion and dominant-light
visibility. The existing bridge's DD|IS remains unchanged. There is no public
reactive/confidence mask, exposure input or normal-space flag. Configuration
keys are normal strength, stability bias, max radiance, radiance clipK, Gaussian
relaxation, disocclusion threshold and debug-depth bounds. The dispatch flags
are RESET and NON_GAMMA_ALBEDO; creation has debugging and validation flags.

The public API labels negative radiance A as inactive. DD uses a nonnegative
activation payload; ID/IS require valid secondary ray distance when active.
The official sample initializes indirect A to65504 and changes it to Euclidean
secondary origin-to-hit distance only after an actual hit. A secondary miss can
carry nonzero environment radiance and65504. Zero, inactive and environment
miss are different cases. Native Recon's weighted source metric and a numeric
zero count do not prove which of those cases the original writer intended.

`fsrd_nrd_rr_signal_contract.py` loads only published, verified Recon u0/u1
images after matching the full shader and canonical root hashes. It records
numeric categories without reclassifying native zero as inactive or miss.
No native temporal sequence, absolute hit unit or Consumer flag is inferred.

Primary sources (read locally first, verified against AMD's official pages):

- [AMD1.2 API header](https://github.com/GPUOpen-LibrariesAndSDKs/FidelityFX-SDK/blob/main/Kits/FidelityFX/denoisers/include/ffx_denoiser.h)
- [AMD1.2 integration contract](https://gpuopen.com/manuals/fsr_sdk/techniques/denoising/)
- [Official ray-tracing sample](https://raw.githubusercontent.com/GPUOpen-LibrariesAndSDKs/FidelityFX-SDK/main/Samples/Denoisers/FidelityFX_Denoiser/dx12/shaders/trace_rays_denoiser.hlsl)
- [RR1.1 albedo-alpha removal](https://gpuopen.com/manuals/fsr_sdk/whats-new/version_2_2_0/)

The current sample stores `material.perceptualRoughness` directly in normal.B;
the integration document calls B linear roughness. This naming difference does
not justify an extra square/root on the attested native B. The sample uses world
normal in its own world-space ray geometry, but that alone does not attest the
title's normal writer. No guessed normal rotation is introduced.
