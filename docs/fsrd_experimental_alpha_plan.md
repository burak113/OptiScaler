# FFX Denoise Experimental Alpha — modulation/demodulation plan

September 29, 2026. The first additive-light split candidate has been implemented. Technical validation and separate quality results: [Alpha implementation record](fsrd_alpha_additive.md). This first package does not mean that the long-term plan below is complete.

## Decision and scope

We will close the Stage work with its current findings and open issues, and improve
the existing conversion on the `ffx-denoise-experimental` base instead of expanding
Joint. The new work is called **Experimental Alpha**; it is not a new Stage 9.
Stage results will be retained as research and regression references. Closing the
work does not mean treating work without in-game quality acceptance as successful
or resolved.

Implementation branch (the name chosen by the user): `ffxD-experimental-alpha`.

- Reviewed local base: `ffx-denoise-experimental`,
  `56e1af15ee9fd6d57daac12e240159eac1c3df8e`.
- The local `origin/ffx-denoise-experimental` points to the same commit.
- `upstream/ffx-denoise-experimental` differs: `18ac686a`. It is not the base of this plan.
- Stage 8 reference: `395c3182`; 11 commits ahead of the base.
- Origin freshness was verified when implementation began: the base SHA used was
  `56e1af15ee9fd6d57daac12e240159eac1c3df8e`.

Alpha's first goal is a better input/output conversion that reduces albedo-driven
stains, preserves real material detail and color, and does not silently transfer
noise into Skip. Skin and ghosting will be included in regression checks from day
one; the first package will not introduce algorithms specifically for them or a
general solution to denoiser blur.

## Lessons to carry forward from Joint and the Stage work

1. A correct sum with an identity denoiser does not guarantee a good image with the
   real model. Even when division and multiplication match, a spatially varying
   coefficient can carry a pattern into the output.
2. Ignoring all source albedo is not a solution either: real material texture can
   be suppressed by the model when normalization does not separate it out.
3. In Stage 7, the source-sum representation preserved detail in the real material
   scene while increasing error on the false albedo island by approximately 15.4
   times. Every candidate must pass these two opposing examples together.
4. The source guide, the guide presented to the model, signal allocation, and the
   forward/inverse multiplier are separate concepts. A preset that changes them
   all at once is not a causal test.
5. The diffuse/specular paths cannot be treated as independent filters. One input
   can affect the other output; changing the final weight does not test the full effect.
6. Constant M, fixed roughness, lower stability, or continuous resets have not
   been validated as general solutions. Guide–signal interaction and loss of real
   lighting detail will be tracked as issues separate from modulation stains.
7. FP16/UNORM storage, the divisor floor, and Skip ownership are not invisible
   details. Adding positive rounding residuals or floor losses back as raw RGB
   can produce grain and color bias.
8. A single ROI and images from different times do not replace full-frame temporal
   A/B testing. Resets, applied tuning, source/DLL identity, and actual history age
   must be recorded.

## A. Closing the Stage work and separating the Alpha base

**Work**

- Write a short result record for Stages 5–8: the validated mechanism, rejected
  candidate, open in-game defect, and reproducible test. Stage 8's cost and history
  maturation limits will remain open.
- Preserve the sources/results on the Stage branch; do not merge or cherry-pick
  all 11 commits into Alpha. Review the dependencies of each fix to be used separately.
- Create the Alpha branch from the base SHA in a suitable separate checkout,
  without applying checkout/reset to the existing dirty workspace. User changes
  will be preserved.
- Build the base; record the identities of the build, embedded shaders, DLL, and
  default settings. Keep the base image and cost as a frozen comparison.

**Completion:** Alpha's origin and reference are unambiguous; the existing Stage
code has not been lost; the unchanged base can be reproduced. No new Joint feature
is required to close the Stage work.

## B. Carrying over only the necessary correctness and diagnostic infrastructure

The base already has native tests and a real AMD runner. These will be used;
Joint resource management or Stage 8 color history will not be carried over solely
for testing.

Carry-over inventory:

- Include: relevant counterexamples, CPU/GPU identity tests, measurements of
  source/stored coefficients, the necessary RRTrace, and records of applied
  settings/DLL identity.
- Include after review: albedo range/quantization, Skip accounting, reset, and
  capture/fence safety fixes. Each will be validated against the base's contract.
- Exclude from the first Alpha: the JointField runtime path and presets, the
  Stage 6 neutral-field system, Stage 8 StainGuard/DetailRecovery, and new color history.

Code surface: `FSRDInputConv.hlsl`, `FSRDOutputComp.hlsl`, the necessary shared
math helper, `FSRDPreprocessor_Dx12.*`, `FSRDFeature_Dx12.cpp`, and test/trace tools.
Config/menu changes will be limited to genuinely necessary selections and
diagnostics; a new user panel made up of Stage numbers will not be built.

**Completion:** Alpha with the infrastructure added but the candidate disabled
preserves the same image behavior as the base. There is no readback/CPU wait cost
when capture is disabled.

## C. First establish an explicit contract for the existing math

The first implementation package will address conversion correctness, not a new
algorithm. Normal, roughness, hit distance, tuning, and source guide policy will
remain fixed.

Conceptual accounting for a processed pixel:

    C = K + R
    Rd + Rs = R
    Ud = Rd / Dd_stored
    Us = Rs / Ds_stored
    C_identity ≈ K + Dd_stored * Ud_stored + Ds_stored * Us_stored
    C_out = K + Dd_stored * Vd + Ds_stored * Vs

`Rd/Rs` are the estimated allocation of the composite color; they will not be
claimed to be the game's real lobes. `K` owns contributions explicitly bypassed
for physical or implementation reasons. The existing Floor/overshoot/mask paths
are accounted for separately; this simplified equation does not mean that all
special paths have been validated.

Source albedo `A`, the AMD guide `G`, and the conversion multiplier `D` will be
separated conceptually. Division and remultiplication will use **the same
stored/reconstructed D**. The divisor floor will not become a silent noise path
that merely increases the divisor and adds the same loss to raw Skip. Range/overflow
and genuine bypass will be recorded separately; quantization differences will not
be injected as one-sided positive energy.

This separation does not require new full-resolution buffers as the first step.
We will first test whether the same D can be reliably computed from existing
resources; if additional resources are truly necessary, they will be chosen with
their cost explicitly measured.

Black, missing, invalid, and guides that round to zero in storage will be handled
separately. A physical material label will not be invented for an unrepresentative
nonzero-color/black-guide pixel. A positive stored minimum and a fallback contract
will be defined.

**Completion:** CPU/GPU identity, FP16/UNORM, dark/HDR, and mask tests pass; K's
contribution and losses are explained. A real AMD quality test is also required.

## D. Small, controlled modulation candidates

Floor and recovery effects will be isolated first; the unchanged existing paths
will then be re-enabled to test their combined behavior. Measurements with Floor
disabled will not be claimed to represent game defaults. The initial matrix will
include only these candidates:

**C0 — frozen base.** Existing behavior and settings.

**C1 — matched conversion consistent with storage and gain.** Existing allocation
and source guides are preserved; only proven numerical/accounting defects from
section C are corrected. If this candidate wins on its own, a more complex
candidate is unnecessary.

**C2 — limited modulation contrast.** Reducing albedo's division/multiplication
contrast will be tested on the existing lobe conversions with a small, fixed
parameter set. For example, `D = clamp(A_stored^gamma, Dmin, Dmax)` is a research
candidate, not the selected final algorithm. Source-dependent conversion at
`gamma=1` is compared with the unmodulated limit through an explicit unity
control. Zero albedo and the storage minimum are explicitly defined. The existing
`lerp(1,A,strength)` behavior is also retained in the comparison.

These candidates will be tested by separating dark-albedo gain from spatial
coefficient contrast. We will proceed with one-variable experiments rather than
opening diffuse/specular parameters to multidimensional optimization from the
start. Guide, allocation, and tuning will not change together in the same experiment.

**Conditional follow-up research:** If C1/C2 cannot resolve the conflict between
preserving real texture and suppressing false stains, the problem is documented.
Only then is limited adaptation using validated material/structure information
investigated. Generating confidence from raw noisy RGB and building a new
mask/filter/history chain is not the default next step.

If the source/effective guide effect remains unclear, a separate GuideOnly pair
will be run using the same signal and D. Such a research choice does not
automatically become a user feature or evidence that the source albedo is wrong.

**Completion:** A candidate reduces stains while passing real detail, color,
quiet-region noise, and motion checks together. If none pass, Alpha retains the
base; a failed candidate is not made the default under a “more experimental” label.

## E. Acceptance matrix and game validation

Required counterexamples:

- Real albedo texture with compatible lighting.
- A false island/boundary pattern in albedo while the clean color is constant.
- Real fine lighting/wave detail on constant albedo.
- Low/zero/missing albedo, colored metal, high total albedo, and HDR.
- Independent and correlated noise on a quiet surface; grain returning through
  K/recovery.
- Moving materials, disocclusion, camera cuts, and exposure changes.
- Real game: a small Uniform island, a skin close-up, and a ghosting scene.

A validation scene/seed separate from the development scene will be used.
Acceptance thresholds will be set after measuring the base and before tuning
the candidate. Clean synthetic truth will be supplied only to evaluation; it will
not leak into production inputs.

Metrics: error from patterns absent in the source, real detail contrast, RGB/color
deviation, quiet-region noise, temporal error/trail duration, K's energy share,
GPU ms, and peak VRAM. A single RMSE, test count, or sharper screenshot is not acceptance.

The native production shader → real AMD → production composition chain will be
run. The same DLL/tuning, equal warm-up/reset, and the same input sequence will
be used. Stage 7/8 synthetic results will not be assumed to generalize to larger
game resolutions. The final comparison will be base / Alpha C1 / selected
candidate; Joint may be included only as a research reference.

**Game acceptance:** Reduced stains and preserved detail are both visible in
consecutive images of the same scene; skin and ghosting checks do not worsen;
the specified hardware budget is not exceeded. Without this, there is no new
default or general quality claim.

## Delivery packages and stopping points

1. **Base and Stage closure record:** branch origin, build, scene set, open issues.
2. **Correctness package:** necessary diagnostics and C1; disabled-path parity
   and a real AMD test.
3. **Candidate package:** a limited experiment matrix with C2; reasons for
   acceptance/rejection.
4. **Game Alpha package:** the single passing candidate, simple settings, cost,
   before/after, and rollback.

Each package proceeds through separate, reversible commits. There is no large
Stage merge. The initial research budget is limited to these two candidates;
failure does not automatically start another long Stage chain. Wave suppression
or missing real lobes/layers outside the modulation boundary remains a separate
open issue.

After Alpha acceptance, return to the skin, ghosting, and simplification work in
the [general quality roadmap](fsrd_stabilization_roadmap.md). No branch, production
shader, game setting, or distribution was changed while this plan was prepared.

## Research references

- [Stage 7 representation and counterexample results](https://github.com/burak113/OptiScaler/blob/395c3182c71dd4832d5f83a17452030c548a20da/docs/fsrd_stage7.md)
- [Stage 8 quality, history, and cost limits](https://github.com/burak113/OptiScaler/blob/395c3182c71dd4832d5f83a17452030c548a20da/docs/fsrd_stage8.md)
- [Current base checkpoint](fsrd_floor_recovery_release_20260926.md)
- [Modulation isolation experiment](fsrd_modulation_isolation.md)
- [Recovery and gradual modulation controls](fsrd_recovery_controls.md)

## September 29 additional review: Zakrisson-C / fsrd-debug-tools

The reviewed remote branch tip was `12becec2cf036378a8669c4ef81f028f5e65ac7e`.
Commits were fetched through Git; shader changes and relevant source context
were read. This is a code review: the branch was not built, and no in-game/synthetic
quality or performance tests were run. Game observations in commit descriptions
are the author's findings; they are not considered validated results in our game scenes.

### Useful albedo direction: additive-light split

[`b151554d`](https://github.com/Zakrisson-C/OptiScaler/commit/b151554de7cafd17e886a5d61e9983dc78e7cffc)
fits `C ≈ a*(Ad+As)+b` per channel in a 7×7 surface neighborhood. `b`, intended to
represent a contribution not proportional to albedo, increases the specular
share; per-pixel albedo division is retained. The share is accumulated from
history using motion. This differs from increasing the final specular weight:
it changes how the two RGB inputs presented to the model are constructed.

This hypothesis is valuable for Alpha: treating composite color containing
fog/haze or different lighting components as entirely dependent on material
albedo may be wrong. However, the regression intercept is not a physical
fog/SSS/specular decomposition. Local lighting/shadow variation can also produce
an intercept. The assumption that specular albedo is untextured must also be
tested for textured metal, colored specular, and small As. The code's comment
that “there is only share history, so lag cannot cause ghosting” will not be
accepted: lag in the share of differently filtered outputs can also cause
temporal error. The history's 10% depth tolerance, use of raw motion, and
origin/jitter contract must be reviewed against our general integration.

**Plan change:** Before the C2 gamma experiment, add a counterexample with
independent additive light on a surface with an albedo pattern. If the problem
after C1 is dominant in this scene, limited additive decomposition may be
prioritized as the first additional candidate in place of C2. The initial
two-candidate budget is retained; three algorithms will not all be implemented
in production. First test the effect with temporal share disabled, then test the
history contribution separately. If layer information is genuinely provided,
use the validated source before heuristic regression.

### Albedo experiment to exclude: distance-based division fade

The distance-based albedo division change introduced by
[`e480fdb9`](https://github.com/Zakrisson-C/OptiScaler/commit/e480fdb9)
was reverted by
[`6e56a774`](https://github.com/Zakrisson-C/OptiScaler/commit/6e56a7746d7a1bd27deb86a5c5dbd37d0a054b71).
The reason was that distant real textures were also filtered as lighting and
became blurry. This supports our requirement to test the real-texture/false-albedo
pair together; the reverted experiment will not be carried over to Alpha.

### For skin, small diagnostics first, then SSS reconstruction research

[`d977e315`](https://github.com/Zakrisson-C/OptiScaler/commit/d977e31580504af2942b57f077699d3b453be757)
tracks the real `ScreenSpaceSubsurfaceScatteringGuide` input and adds an A/B that
disables Correlation Bias raw blending on pixels where SSS is present. This is
the first idea to adapt: is noise spread by the game's SSS being mistaken for
real structure by recovery and added back? Because our composition/recovery
algorithm differs, the equivalent contribution must be isolated rather than
copying the same menu flag.

[`b59aebc4`](https://github.com/Zakrisson-C/OptiScaler/commit/b59aebc47842091bf30622eacc30bf9a62bd3f99)
interprets the SSS guide as `L(after)-L(before)`, with `L=(R+2G+B)/4`, and separates
it using `DeltaRGB ≈ C * guide/L(C)`; it adds the delta back into Skip with temporal
averaging. It also adds log(albedo)–log(signal) slope visualizations for each
lobe. These texture-leak visualizations are useful diagnostics; because real
light/albedo correlation can also produce a slope, they are neither proof of a
defect nor an automatic correction mask.

[`12becec2`](https://github.com/Zakrisson-C/OptiScaler/commit/12becec2cf036378a8669c4ef81f028f5e65ac7e)
tries to reconstruct SSS using a depth-aware, two-pass Gaussian on denoised color
instead of adding back the previous noisy SSS delta. A world-scale radius is
converted to pixels using depth/projection; a fit metric measures kernel agreement
with the guide. The new option is disabled by default. This is a more meaningful
research candidate than simply averaging the noisy SSS delta over time.

Issues that prevent a direct port:

- Even if the guide really is this luma difference, a single scalar does not
  uniquely determine the RGB before SSS. Reconstruction using composite chroma
  is an approximation, not an exact inverse. Colored light and different
  scattering per channel must be specific counterexamples.
- The condition `guide != 0` is not equivalent to a material mask: a valid SSS
  pixel can have a net luma difference of zero. Mask continuity and transitions
  between frames must be tested.
- The branch's blur/composition code adds the `ColorBeforeParticles` source
  back as if it were a premultiplied particle layer. The local Streamline
  definition identifies it as the color buffer before particles are drawn;
  our current composition also explicitly preserves this distinction. This
  blend will not be carried over without validating the resource contract;
  there is a risk of adding the scene color again.
- The guide's format, sign, exposure domain, subrect/origin, depth world units,
  colored scattering profile, and eye/lip/hair boundaries must be validated.
  Kernel fit residual error is not evidence of final image quality or complete
  SSS reconstruction.

**Order:** First, the presence/meaning of the SSS resource and an A/B of the
raw/recovery contribution; second, colored and moving face references; only
if this mechanism is validated does SSS reconstruction become a separate skin
package. New SSS history and blur passes will not be added to the main modulation package.

The branch's `upscalers/ffx` integration differs from our `upscalers/fsr31` and
shader/CB/resource contracts. Narrow adaptations of validated ideas will be
preferred over cherry-picking ready-made commits. This review did not change
production code or the choice of Alpha base.
