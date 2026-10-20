# Job 06 mechanism and representation audit

## Scope and conclusion

This is a source and fixture audit of immutable handoff commit
`5d7839a930106cf8fe1ba8dbbc6750509e7f26a8`, whose production baseline is
`87e8b7ab2a428bd91d3c044decf7d4dbccd8cefd`. It is not an AMD RR execution.
The strongest supported candidate is a read-only support/transport tracer with
explicit abstention when observations cannot identify a cause. No new motion
scaling, roughness floor, history reset, or image filter is justified by this
audit. The actual candidate decision and executed measurements are in the main
report and result file.

Source references below use repository-relative paths and line spans at the
recorded handoff. `SOURCE_AUDIT.json` binds those paths to SHA256 hashes and lists
the individual claims. Source comments are evidence of the implemented model,
not empirical proof of its correctness.

## Native signal route

### 1. Geometry and current noisy input have separate provenance

`FSRDNrdBridge_Dx12.cpp:1778–1828` prepares owned native geometry. At the late
Consumer, `2161–2179` decodes the current owned raw snapshot and records RR;
the decoded snapshot must match command list, Streamline frame and bridge
frame. It does not import native denoised RGB as a reference. The native target
pair is verified again before commit (`2100–2160`, `2240–2293`). Internal staging
order is **specular, diffuse**; title consumer bindings are **diffuse, specular**.
Do not infer lobe order from descriptor index without the call-site mapping.

`precompile/FSRDNrdRawDecode.hlsl:14–35` reverses the captured native RGB/YCoCg
encoding, sanitizes RGB and rounds to nearest-even FP16. It retains finite
native alpha. The comment explicitly rejects treating Recon's intermediate
1000 sample weight as an alpha-unit conversion. `FSRDNrdRawPrePassDecode.hlsl`
additionally fills proven untraced checkerboard pixels using geometric
neighbours. Its reconstructed alpha is a neighbour-hit reconstruction, not an
independently observed current secondary-ray hit. The clip export omits native
checkerboard mode/header provenance, so the current crops cannot distinguish
all upstream estimator mechanisms.

`precompile/FSRDNrdBridgeGeometry.hlsl:66–102` exports signed, near/far-clamped
linear view Z separately from the native positive ViewZ, tracks invalid/clamped
depth in a separate validity resource, carries packed world-space normal and
linear roughness, and generates material albedo guides when available. The
normal's category bits are not a semantic object classifier. Original and
provider normal/roughness are separate observations when a roughness floor is
active. The packaged clips retain both packed guides, but omit albedo and the
depth-validity resource.

### 2. Surface XY, depth transport and provider history controls differ

`FSRDNrdBridgeRR_Dx12.cpp:1136–1208` validates the Streamline motion convention:
2D motion, camera motion included, perspective projection, finite nonzero scale,
and finite jitter. It resets logical history on explicit reset, missing history,
frame gaps or convention changes. It does not certify the title's per-object
motion as ground truth.

`precompile/FSRDNrdMotionCommon.hlsli:17–61` forms surface RG as native motion
times the declared scale plus the necessary jitter delta. A crop consumer must
not add that jitter again. Channel B is the signed previous-minus-current
view-depth prediction. It may come from native current-surface reconstruction,
camera-only prediction, unknown zero, or an explicit legacy rollback.
Camera-only depth prediction cannot describe independently moving geometry.
`FSRDNrdBridgeMotion.hlsl:43–66` prefers the native depth delta only when the
required native operands are valid. The clip does not retain the per-pixel
provenance distinguishing these cases.

G3/lighting validation reads **original** `sourceInput.diff/spec`, not a possible
Anchor-darkened pair (`FSRDNrdBridgeRR_Dx12.cpp:1553–1575`). Its apply shader
copies RG/A and may replace **B only** with a finite signed 65504 sentinel after
a confirmed lighting event (`FSRDNrdLightingGuardApply.hlsl:45–60`). Such a value
is a deliberate history rejection signal, not object velocity or a real depth
change. The fixture's `input_motion` is the actual finalized provider resource;
its XY convention remains usable, but B must not automatically be treated as an
unmodified geometric witness. A read-only spot check found no absolute-B 65504
sentinel in the seven bottle crops; this does not prove G3 was disabled outside
the crop or in unseen prior frames.

### 3. Radiance scales surround the provider only

Native Anchor, if enabled, supplies private physical-unit D/S inputs to both RR
and lobe recovery (`FSRDNrdBridgeRR_Dx12.cpp:1297–1356`). It remains OFF in the
protected working configuration. Optional turn processing follows. The actual
AMD descriptor chain is **DirectDiffuse 0x44 then IndirectSpecular 0x48**
(`1511–1521`), even though internal resources are stored specular-first.

The shared radiance scaler assigns factors by descriptor type; its input and
output RGB scaling does not scale alpha (`FSRDRadianceScale_Dx12.h:61–86`,
`145–178`; `precompile/FSRDRadianceScale.hlsl:16–35`). The RAII restoration occurs
before recovery or trace reads (`FSRDNrdBridgeRR_Dx12.cpp:1595–1640`). Thus the
packaged `input_*`, `raw_rr_*` and `selected_rr_*` must be compared in the
restored native signal domain, not with an extra D16/S256 multiplication. The
protected configuration remains D16/S256; the 46 dispatch words do not encode
those scaler settings, so full per-frame settings metadata is required to
attest them in a new capture.

The phrase “physical native units” means the bridge's scale has been restored.
`FSRDGameTraceBridgeMetadata.h:123–138` explicitly records
`material_modulation_contract_verified=false` and upstream exposure as not
separately attested. It is therefore not a calibrated assertion about final
game light energy or final display appearance.

### 4. Raw RR and selected RR are different observation points

RR writes owned raw D/S textures; lobe recovery can replace the selected pair;
Flat Albedo Recovery can then produce the final selected pair. See
`FSRDNrdBridgeRR_Dx12.cpp:1333–1457,1638–1649,1676–1690` and
`FSRDNrdFlatAlbedoRecovery_Dx12.h:605–633`. The raw pair remains available.
An `input → raw_rr → selected_rr` comparison can localize where an **additional
observable difference** first appears. It cannot expose the provider's hidden
history or prove that an unchanged stage did no internal work.

Crucially, NZR **Temporal OFF does not mean all NZR history is off**.
`Reflection(s)` is `s.reflectionHistory && !s.temporal`
(`FSRDNrdFlatAlbedoRecovery_Dx12.h:120–123`). The working configuration retains
Reflection History, RR Fallback and Diffuse RR. Diffuse RR bypasses diffuse
recovery for its branch (`442–447`); reflection history is specular-only.

`precompile/FSRDNrdFlatHistory.hlsl` constructs a virtual point by extending the
view ray by the specular hit distance, projects it with the previous camera,
and accepts previous taps using hit-distance similarity. The source explicitly
assumes a static planar reflector. It reads no surface MV. A translating or
rotating reflector and a moving reflected object are legitimate counterexamples
to that assumption. This makes a different specular correspondence a plausible
hypothesis, not a demonstrated explanation of the bottle clip. AMD's internal
virtual-motion mechanism is a separate opaque state and must not be equated
with this NZR shader.

### 5. Encoded commit still precedes the game's composition

`precompile/FSRDNrdBridgePureCommit.hlsl:21–30` encodes selected staged RGB and
preserves **the title destination alpha**, not the staged alpha.
`FSRDNrdSignalEncoding.hlsli:27–40` implements the native YCoCg inverse pair;
Consumer factor64/specular exposure is explicitly not folded into that encode.
The trace's encoded-commit stage is before the original Consumer
(`FSRDGameTraceSession.cpp:1775,2310–2334`). It is not final game output.
Clips omit encoded commit, final composition, final upscaler output and video.

## What these fixtures can and cannot observe

The bottle has source frames 180–186, a 128×256 crop inside render 1505×847,
source ROI origin (688,0) and per-frame source-local Y origins
160,176,208,272,384,480,560. Its historical motion mask is speed >12 full-render
pixels/frame, followed by a 5×5 erosion. That mask includes bottle **and hand/arm**;
it is not an independently labelled bottle silhouette. Freeze it before all
candidate and wrong-convention comparisons.

Both input lobe alphas, provider MVs, depth, original/provider packed guides,
raw and selected D/S, original camera words and 46 provider words exist. These
must not be requested again as if absent. What is absent is longer chronology,
pre-crop support, per-stage causal lineage/settings, original pre-G3 motion,
albedo/remodulation, internal provider/NZR state, independent object/reflector
trajectories and final display. Input alpha alone does not identify which
virtual reflection correspondence is correct.

The main fixture analysis should report equality with its exact denominator.
An independent read-only check found raw versus selected D/S word equality on
all 55,452 moving-mask pixel observations over the seven frames. The entire
diffuse crop was equal. Whole-crop specular was not equal: differing FP16 words
by frame were 210,144,90,0,12,0,0. Therefore “selected NZR first introduces the
bottle-tail difference inside this fixed moving support” is unsupported in
these observations; “NZR is always identical or irrelevant” would be false.
No same-pose converged or independently labelled silhouette truth is included.

Foliage frames43–65 and facade frames34–49 provide control windows, not alternate
views of the bottle. The aligned glass fixture's radiance fields and unwarped
geometry have different coordinate histories; use its documented mask and
loader, not the bottle warp on every array. The 6497-pixel fixture mask is not
the historical 8048-pixel full-ROI mask.

## Competing hypotheses: distinct falsifiable predictions

| Hypothesis | Unique positive prediction | Expected counterexample / confound | Minimum separating observation |
|---|---|---|---|
| H1: delayed or sparse source estimator support | At correct geometry transport, source-stage occupancy already falls behind or intermittently misses independently known object support; source-only delay persists under oracle MV. | A correct but sparse stochastic sample can have dark gaps without delayed occupancy. A real dimming can reduce thresholded area with no displacement. | Current native D/S and hit data, an independent trajectory/support witness, at least one preceding image and identical exposure; oracle-source intervention only in synthetic scenes. |
| H2: surface MV / jitter / coordinate error | Lighting-independent geometry correspondence fails along with lobe transport; opaque constant-colour control fails; changing only MV to oracle removes transport error while current source shape remains correct. | Reprojection across disocclusion is invalid even for correct MV. A rotating curved normal field changes even with correct geometry. A radiance self-match can prefer incorrect motion when support is delayed. | Declared UV/sign/jitter/render/crop conventions; current and previous depth/normal or labelled geometry; known full-render trajectory in synthetic scenes, or independently attested object pose in real scenes. |
| H3: specular virtual correspondence mismatch | Diffuse/silhouette follows surface motion but reflected detail follows a different trajectory; virtual-hit reprojection changes that prediction without changing the surface witness. | Static planar reflector can satisfy camera-only virtual projection. No/short/invalid hit, curved/dynamic reflector, or moving reflected object makes ray-extension prediction insufficient. | Specular A plus actual camera/projection, roughness/original normal, explicit reflector/reflected-feature correspondence; provider internal support or NZR reflection mean/moment snapshots to name the faulty stage. |
| H4a: AMD internal history retains support | Source is correct and geometric transport passes, but tail first appears in raw RR; selected may equal raw. | Correct accumulation of sparse but valid input can form continuous support. A reset lowering brightness or detail does not establish better shape. | Synchronized current native source and raw RR with real unlooped prehistory, current-only diagnostic reference, independent shape witness, and recorded reset/no-reset metadata. |
| H4b: selected NZR history adds support | Raw RR has correct support but selected first contains the extra tail; selected identity observation removes only this difference. | Raw and selected can be equal on the moving object while differing elsewhere; a crop-wide statistic can misattribute a static glass change to bottle motion. | Same-frame raw/selected pair, original/provider guides and per-stage state/selector metadata, fixed object support; optional NZR intermediate snapshots. |
| H5: composition/exposure creates apparent lag | Pre-remod stage geometry is stable, but encoded/final composition has a systematic displaced or lobe-dependent footprint. | A multiplicative exposure drop makes a thresholded ghost look shorter without changing its geometry. Unmatched frame timing can imitate lag. | Same-frame encoded commit, actual Consumer modulation/exposure metadata and final same-crop image/video keyed to provider/Streamline frames. |

No single “ghosting score” distinguishes these rows. In particular, the pair
“correct motion with delayed source support” and “clean source with wrong
motion” requires a geometry witness independent of the suspect lobe. Smooth
static normals are weak witnesses; sparse radiance is a poor motion oracle.
For the real crop, uncertainty must remain explicit when witnesses disagree.

## Diagnostic contract and non-identifiability

Support is an observation, not object segmentation. Thresholds are declared
using baseline inputs and then frozen. Display occupancy, signed tail mass,
brightness and normalized structure separately. On synthetic data an analytic
shape gives truth; on real data depth/normal/motion masks are only proxies.
Report their pixel counts and support exclusions. Candidate-derived masks
would invalidate the denominator.

The implemented tracer's surface coordinate contract is the existing fixture
contract, documented in `adapter/ADAPTER_SPEC.md`. Job04's proposed interface
has not been obtained or tested in this independent job; compatibility is an
explicit handoff requirement, not claimed cross-chat coordination. A future
job04 import must satisfy the shared invariants before replacing the packaged
loader reference.

Outside-crop history is unknown, not zero and not edge-clamped. The first
fixture frame is startup without previous image. Stored RR already contains
unseen pre-fixture history; replaying the seven frames or looping them cannot
recover it. Any filter that simply gates history where current source is dark
is especially unsafe: sparse 1spp support and a true disocclusion can present
the same current observation but require opposite treatment. This is the
reason for conservative diagnostic abstention rather than a proposed repair.

## Smallest useful next local observation

Preserve D16/S256, G2/G3, RR Fallback, Diffuse RR, Reflection History and Temporal
OFF. Record a bounded unlooped approach/motion/settle window with the existing
owned-stage trace and retain full per-frame metadata instead of only crops and
46 words. Keep original/provider geometry and motion distinguishable. Obtain
same-frame final output separately; the native bridge trace cannot silently
be relabelled final game output. Add internal snapshots only after the basic
stage localization points to the provider or NZR branch. A controlled reset
is a labelled diagnostic branch with the same warmup and chronology, never the
candidate and never proof of improved shape by itself.

The exact bounded request, formats, payload cap and acceptance rules are in
the task's `BLOCKED_DATA_REQUEST.json` and `GPU_REQUEST.json`. Missing frames
and internal state remain unknown; this audit does not invent them.
