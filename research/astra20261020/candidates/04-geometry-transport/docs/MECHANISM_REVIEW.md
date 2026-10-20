# Mechanism review and integration obligations

Author role: mechanism/representation investigator. This review was prepared
independently of candidate threshold tuning. Source scope and coordinates are in
[COORDINATE_LEDGER.md](COORDINATE_LEDGER.md); measured CPU results belong in the
task's report/evidence, not in unexecuted predictions below.

## Competing explanations and separating experiments

| Hypothesis | Distinct prediction | Cheapest discriminating experiment | What would not establish it |
|---|---|---|---|
| H1: coordinate convention error | A noiseless rigid plane exhibits signed position error independent of radiance noise. Identity can fail before occlusion or statistics exist. | Round-trip an exact point through current/key perspective transforms; compare physical sparse-cell centre, frozen shader expression, and actual sampled key coordinates. Test missing/double jitter, matrix transpose, UV scale, handedness and odd extents individually. | A changed final luma ratio after also replacing the estimator. |
| H2: mixed geometric measurement | Boundary error depends on subcell phase and coverage, while a homogeneous plane remains correct. Mean depth can describe neither surface. | Hold exact transforms fixed; move a1-pixel foreground strip through all phases of an8-pixel cell, then rotate the boundary. Compare exact per-pixel support with sparse16-texel statistics and all-pixel geometric certificate. | Passing a coarse average-depth threshold or reducing its tolerance on one axis-aligned example. |
| H3: reconstruction crosses support | A centre-cell gain1 check passes while protected full-resolution pixels receive gain<1 from neighbours. | Give exact gains and support to reconstruction only; compare ordinary bilinear, hard identity, recipient-only gating and certified-donor+recipient gating at matched correction dose. | A safer coarse gain table inspected without evaluating Apply output. |
| H4: virtual reflection transport differs | Under camera translation a reflected feature's correct motion differs from surface motion; valid reflection distance predicts the virtual location. Under pure rotation the distinction contracts. | Static planar mirror with analytic virtual object; known current/previous cameras, surface depth and reflection distance. Compare surface and virtual projections, missing-hit fallback, motion/roughness reset control. | Better blur/grain scores after resetting history or increasing roughness. |

All four explanations may coexist. A coordinate repair does not establish a
lighting-estimator repair; a perfect support oracle does not establish a usable
production certificate. Native RGBA input alpha is not modified by this task.

## Mechanisms established by source inspection

### A. Half-pixel composition is internally inconsistent

The sparse BoxCell physical taps are at pixel-edge positions2 and6, symmetric
about4. `centre=8*c+4` is passed to a helper that adds0.5. Projection then returns
edge coordinates directly. For identity transforms, algebra gives
`project(unproject(centre,z))=centre+0.5`. This is independent of normal, noise,
depth tolerance and gain. The native/combined Stats implementations share it.

The4-pixel static gate allows the0.7071-pixel two-axis discrepancy, so a passing
static mask is not a test of exact camera agreement. The decisive local witness
must export the view position, clip, q, uv, each sampled key depth and the chosen
slice, not merely the final accepted mask. A proposed fix must choose one
coordinate convention end-to-end; subtracting half a pixel from only one metric
does not fix key-grid mapping or odd-extents stretching.

### B. Averaged depth does not identify an averaged surface

At a mixed cell, `(mean radiance, mean depth, mean MV)` is a joint sample from
different surfaces, not one physical surface observation. Four bilinear taps
cover only16 of64 texels. A thin foreground strip can be entirely absent from
those16 texels yet be hit by full-resolution Apply. Conversely mean depth from
two surfaces may agree with an unrelated key's bilinear average and accept the
wrong surface. A normal average has the same information-loss problem.

The9 gain donors are sparse cells24pixels apart by default; support can be
contaminated even when the recipient's own8×8 footprint is pure. Certifying the
full measurement support is necessary before interpreting that scalar gain as
belonging to the recipient surface. Full-source exact support in synthetic
tests is an oracle; a proposed production plane/normal/motion certificate must
report where it cannot resolve the geometry or where the stronger check loses
correction coverage.

### C. Native identity fallback is only a coarse guarantee

Native Gain's extra guard tests centre `cell.z` and neighbourhood coverage. It
does not require that centre's recall bit, and even a stored gain exactly1 is
interpolated with neighbour gains by shared Apply. Thus a clean centre identity
test does not protect every moving or disoccluded pixel. The frozen Apply's only
SRV is coarse gain; it cannot make any per-pixel geometric decision. No threshold
adjustment in Gain can create the missing recipient data in Apply.

### D. Absolute native depth must not be regressed

Native Gain explicitly writes `abs(cell.y)` into R32F key depth while both Stats
recall paths compare against positive `abs(clip.w/keyP32)`. Combined Gain writes
signed `cell.y`. A right-handed negative-depth combined path can therefore fail
recall systematically, whereas native absolute key depth is correct for its
declared storage contract. The harness must exercise both handedness signs and
the deliberately wrong signed-key mutant. Do not silently port the combined
store into native or rename absolute depth as linear signed viewZ.

### E. Native motion W is not confidence

Bridge motion conversion writes W=1. B's provenance can be native same-surface,
camera-only, unknown, or legacy visible-depth rollback, but this distinction is
not encoded in W. Unknown B=0 is numerically indistinguishable from true zero
depth delta. Geometry confidence must come from a new explicit source contract,
not an interpretation of existing alpha. Replacing unknown depth motion with
the previously visible depth would be circular: the wrong occluder would then
satisfy its own depth comparison.

### F. Virtual-history support is weaker than a visibility certificate

`FSRDNrdFlatHistory` uses current surface depth to construct a virtual point and
the3×3 median positive hit to extend the ray. Its previous taps require recovery
hit compatibility, not previous surface depth/normal agreement. A median can mix
reflectors and hit-distance agreement alone cannot reject every occlusion.
This source finding motivates a controlled visibility test; it does not prove
that the supplied captures' reflection trails have that cause. The original
raw/spec selected inputs and stored RR outputs are not converged ground truth.

## Minimal implementable reconstruction proposal

The safe boundary candidate should operate on a correction field only after
stating its support. The sufficient contracts are:

- Separate full-resolution recipient eligibility from donor validity. A moving,
  disoccluded, unknown, invalid-guide or unobserved pixel has identity fallback.
- Require donor gains to declare complete estimator support and its compatible
  geometric certificate. Reconstructed depth or colour cannot replace the
  original guide used to certify correspondence.
- Interpolate only compatible certified donors. Export retained weight and
  correction dose. No support means identity; low support must follow a fixed,
  documented policy rather than being silently normalized into full confidence.
- A canonical fixed8-pixel cell layout must be explicit. Do not map it as a
  uniform `floor(W/8)` texture spanning W when W is not divisible by8. Tail cells
  and crop edges require separately known support or identity fallback.
- Include exact-gain/exact-support ablations before a real-guide certificate.
  These show where reconstruction is identifiable; they do not authorize an
  estimator claim about unavailable capture ring keys.

A complete block-level plane certificate would need all relevant original
depth, normal and motion samples, including the gain estimator's donor footprint.
A coarse normal/depth output alone cannot recover missing1-pixel geometry.
Coplanar but statistically different material/lighting remains outside pure
geometric certification. Rejecting all boundary cells is safer but loses dose;
that trade-off must stay visible. A relative plane tolerance of `1e-4` cannot
certify separation of parallel surfaces closer than `1e-4*depthscale`; exact
coplanar object/material identity remains unavailable even with perfect depth.
Report oracle-versus-real-certificate failures for those cases explicitly.

Alpha preservation is an arithmetic obligation, followed by a measured raw16-bit
check on legal finite nonnegative native hit distances. It is not a guarantee
that typed FP16 loads/stores preserve every NaN payload. OFF/unsupported paths
that skip writes must preserve all RGBA bytes; adversarial signed-zero,
subnormal and NaN probes are reported separately.

## Concrete production adapter context for job08

This task supplies a candidate and an exact adapter specification. No frozen
production source is patched in place. Required integration points are:

| Site | Current contract | Needed integration change |
|---|---|---|
| `NativePostMotionAnchor::Prepare`, pass2 `Describe` at280–282 | `t0=InGain`; `u0=providerDiff`, `u1=providerSpec`; Apply CB is16bytes | Bind explicit recipient eligibility and donor certificate resources if the proposed Apply consumes them. Do not reuse radiance alpha. |
| `NativePostMotionAnchor::Acquire` at169–171 | Shader-visible heap18descriptors = Stats9 + Gain6 + Apply3 | Recompute descriptor count from the final bindings, including any certificate construction pass. Constants offsets must stay non-overlapping and aligned. |
| `NativePostMotionAnchor::Create` at124–149 | Exact active private D/S; coarse floor-grid Stats/recalled/gain; six key arrays | Allocate new support resources only for default-off experiment; charge shared family budget and retain generation lifetime. |
| `ConvertedResources`/Prepare inputs | Depth/MV available; normals/validity exist in the input struct but current Anchor does not bind them | Bind original guide authority explicitly; missing validity/normal resource must have conservative fallback. Native D/S extent check remains unchanged. |
| `RecordInputs` at292–332 | Stats→UAV barrier→Gain/key write→transitions→private copies→Apply | Add required certificate dependencies/barriers. Keep state publication tied to the existing recorded/submitted-generation discipline. |
| Combined path | Same shared Apply, different native/combined Gain policies and depth store | Validate as a separate labelled route. Do not infer native improvement from combined-only execution. |
| Shader build | Native Stats/Gain are `cs_6_6`, `-HV 2021`; shared Apply is `cs_6_2` | Compile candidate Apply with declared flags and matching DXC1.8 for comparable artifacts; preserve native baseline profiles. |

Exact production build commands come from `build_fsrd_shader.py:100–109`:

```
native Stats/Gain: dxc -T cs_6_6 -HV 2021 -E CSMain -O3 -enable-16bit-types ...
shared/candidate Apply: dxc -T cs_6_2 -E CSMain -enable-16bit-types -O3 -Qstrip_debug -Qstrip_reflect ...
```

Record all include paths/defines, source/include hashes, compiler version, fresh
CSO hash, output disassembly and generated header linkage. This cloud work does
not compile or execute those shaders. Never reuse stale CSO/header bytes as
evidence that a proposed binding ABI was built.

## Surgical missing observations

1. **Raw six-key native ring plus camera/jitter/slot metadata:** existing Anchor
   fixtures already contain the result of recall. New selectors or a corrected
   q cannot be evaluated against absent original key texels. Six full coarse
   slices are small enough to export intact and preserve exact sampling support.
2. **Actual sampler witnesses:** colour provenance documents9/4096 hard-depth
   decisions affected by hardware fractional quantization. Export actual sample
   values, q/uv and neighbour texels at near-threshold cases. An ideal NumPy
   warp cannot certify the D3D threshold boundary.
3. **Native route and fresh rendered controls:** separate actual native private
   inputs, provider inputs, post-RR pair and post-NZR/final output. A pass-only
   harness or mock provider cannot demonstrate AMD RR/game quality.
4. **Reflection-distance provenance:** preserve raw specular alpha and its
   native signal-role interpretation; provide current/previous geometric
   witnesses for a short translated planar-reflector sequence. A generic
   roughness/reset experiment cannot identify correct virtual motion.

Detailed exact dimensions, byte budgets, frames, units, and competing outcomes
are in `GPU_REQUEST.json` and `BLOCKED_DATA_REQUEST.json` at the candidate root.
Until those gates pass the defensible recommendation is **keep as research**.
No amount of synthetic support purity turns this into a native game-quality or
performance claim.
