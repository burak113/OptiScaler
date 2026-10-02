# Independent-lobe holdout for the additive residual prototype

The stain/wave goal remains unresolved. The single-slope additive residual
prototype is rejected by its preregistered derived SPEC diagnostic. This is
an isolated helper experiment, not a game DLL integration or a demonstrated
cause of Cyberpunk's stains. Full specular and diffuse demodulation/remodulation
strengths remain 1. The user also reports that the blur at specular strength 0
persists with a stationary camera; reducing that strength is not an accepted
solution.

## Actual experiment, 2026-10-01

Four observations use independently varying specular and diffuse albedos:
`S=.10-.05*cos(theta)`, `D=.25-.05*sin(theta)`, with separately constructed
illumination coefficients `.3` and `.5` and additive RGB `[.08,.07,.055]`.
Those coefficients and clean lobe references are scoring-only data, never
field inputs. Two clean observations share identical inputs. The other two
use distinct fixed spatial noise seeds of amplitude `2^-10`; this is not
temporal IID noise.

All 20 GPU helper stages completed, with 92 output files (7,208,960 bytes),
80 actual dynamic handoffs, and accepted physical, metadata, and strict
checks. All five clean stage repeats and inactive converter outputs were
bit-identical. The independent POST review rederived all 52 saved score
dictionaries exactly. No native RR workload ran in this experiment.

Total-color gain passed at 1.001053–1.001587. The candidate's derived SPEC
gain failed at 1.548955–1.562634, with phase error 0.168206–0.226383 radians.
The baseline also failed that SPEC reference. The SPEC view uses actual
converter `u0` and matched caller factor `u4` with the declared CPU typed
transport schedule; it is not another measured GPU SPEC UAV or a native
output. Total-color preservation cannot substitute for lobe detail quality.

The candidate's noisy-minus-clean Skip RMS was 0.009617/0.010938, versus
0.000065879/0.000065735 for baseline Skip. Near-zero Pearson correlation
with the seed noise did not imply stability. Stored grid-node validity
changed at 22/29 nodes, whose tent footprints covered 1,024/1,376 pixels.
About 83.24%/85.65% of candidate Skip difference energy occurred where pixel
validity stayed on. Tent interpolation spreads changed node estimates to
neighbors. The buffers do not disclose exact rejection reasons; none are
inferred as measured telemetry.

## Evidence and next work

Local evidence directories are under the alpha worktree's `tools_tmp/`:

- `fsrd_independent_SD_static_noise_helper_preparation_20261001` contains
  the frozen inputs, actual outputs, and CPU analysis.
- Root receipt `fsrd_independent_SD_noise_helpers_root_tool_observations_20261001.json`:
  126,370 bytes, SHA256 `267d057b1cad9722e0b413a8ecabab98d344bcd53e786dbf10fa63ccdae3da93`.
- Independent POST review `fsrd_independent_SD_noise_helpers_postrun_review_20261001/review.json`:
  SHA256 `c1f86b532554c40f377898e7c9ff81a0fa99fc88cda71f82edbb23fc9cf21103`.
- Field noise diagnosis `fsrd_additive_field_gate_noise_diagnosis_20261001/results.json`:
  SHA256 `f237ac900145b7f802de9d3a8dea29219e984905d4cfc0ab2dbbcecfc8e42d0d`.

Immediately after the helper holdout, the cumulative physical helper count
was 1,803, SDK contexts 469, successful RR API calls 25,530, and
queued/completed RR calls 25,522.
The receipt's base helper value is 1,783; its `exact_after` value is 1,803.

## Rank-two CPU feasibility

The separate rank-two allocation candidate completed four observed-only CPU
predictions before references were loaded for scoring. The independent saved
output review reproduced all 28 fixed score dictionaries. Whole-color gain
passed at 1.000276–1.000439, but derived SPEC gain failed at
1.800600–1.801621, with phase error 0.076374–0.076628 radians. This candidate
is also rejected; total-color closure does not establish correct lobe detail.

Each case fitted 270 grid nodes with 2,430 NNLS solves. CLEAN additive support
peaked at 0.007146 and signed allocation correction at 0.000679, so much of
the unresolved energy still followed the original albedo-ratio allocation.
The saved data do not separate conditioning attenuation from intercept
uncertainty. Changing the final guide fade is not supported by this evidence.

The old CPU resource guard monitored launcher PID 12824, while the model
journal recorded PID 26216. Its sampled working set does not establish the
model's memory or descendant-stop coverage. Output integrity passes, but
the model resource-limit claim remains unproved. This run was not repeated.

Evidence: `fsrd_rank2_lobe_allocation_CPU_feasibility_preparation_20261001`
and `fsrd_rank2_CPU_feasibility_postrun_review_20261001`. The independent
review SHA256 is
`1b85850a746bed36ec325063dd6910f7c50a2b692dd5cfc01a4f2e285807ec17`.

## Floor-free volumetric CPU feasibility

A history-and-line-support proposal was tested with full strengths 1 and
Floor OFF. The first launch preflight created no child because free memory
was below 1 GiB. That evidence was preserved. A separate launch folder used
the same model, fixtures, and thresholds with the matching real Python 3.12
interpreter. It completed 100 newly constructed CPU cases, 367 observed
frames, 734 model calls (including 400 warmups), and 100 scoring cases.
There were 100 stored arrays totaling 19,010,009 bytes. No shader, GPU helper,
native SDK context, or game execution was added.

The primary proposal failed 78 registered checks: 68 grain suppression
checks, seven SPEC detail checks, and three uniform-light retention checks.
The identical-observation volume/frozen-noise pair produced identical
support, illustrating that these inputs alone cannot distinguish the two
semantics. It is not an accepted replacement for Floor. Gaussian light
profiles, synthetic erased RR transport, and analytic material allocation
are CPU diagnostics, not measured AMD or game results. Independent saved
output review reproduced all 200 metric dictionaries and preserved all
78 failures. Integrity acceptance does not change the quality rejection.

The new guard directly launched the real interpreter and sampled its child
PID 27808: 14.844 seconds, peak working set 48,087,040 bytes, minimum sampled
system free memory 1,283,526,656 bytes, no termination. The worker did not
record its own PID; that missing runtime evidence remains explicit.

Evidence: `fsrd_floor_free_volumetric_CPU_launch_attempt_real312_20261001`.
The result SHA256 is
`c613da4478d8ef37b2ea6048b4cf159093c2a5c1dc3fb7350360b5b362fb4688`.

The stain/wave goal remains unresolved. Next work separates material-detail
transport from a denoised unmodulated residual and independently tests SDK
guide RGB while preserving original full-strength signals and caller factors.
No production integration or game deployment follows from these results.

## SDK guide diagnostic launch prefix

The original, lower-mean, and upper-mean SDK guide arms preserve original
full-strength native signals and caller factors. The specular guide is already
constant in this fixture; only diffuse guide RGB varies between these arms.
This S-constant fixture is a raw SDK diagnostic and cannot establish SPEC
material sharpness.

The first original-guide context completed 64 native RR frames with no
reported validation or SDK errors/warnings. The Python driver then stopped
because the root launch omitted the matching NumPy PYTHONPATH. The failed
report and first outputs remain unchanged. Subsequent saved-only qualification
confirmed both 5,242,880-byte lobe files contain finite RGB and the 64-frame
physical counts match. No first-context rerun occurred. A separate continuation
completed the remaining 11 fixed cases with the matching NumPy environment
checked before any native child. The failed original report remains unchanged.

Current cumulative counts at this prefix are 470 SDK contexts, 25,594
successful RR API calls, 25,586 queued/completed calls, and 1,803 helpers.
Root prefix receipt SHA256:
`1fdcc173dbdf1016f0e543953fd48b792096a94791212d5bacfa20742184471c`.

The combined 12 unique contexts produced 768 RR API/queued calls and 24
lobe files (125,829,120 bytes). All fixed 66 raw pairs and 132 lobe metric
dictionaries were evaluated once. Each of the 12 registered guide-arm pairs
differs in both native lobes. Five of six same-arm repeat pairs also differ.
For the L carrier, between-guide RMS is 0.00008733–0.00008822 for diffuse
and 0.00008711–0.00008935 for specular; same-arm repeat maxima are
0.00001925/0.00002907. N between-guide ranges are 0.00017765–0.00018711
and 0.00018452–0.00019453; N repeat maxima are 0.00014848/0.00016100.
These are descriptive observations without a significance, game-cause,
sharpness, or solution claim. Only SDK diffuse guide RGB changed.

After all 12 contexts, cumulative counts are 481 SDK contexts, 26,298
successful RR API calls, 26,290 queued/completed calls, and 1,803 helpers.
Root combined receipt SHA256:
`d781d4af4d79719d7c3705d4df8299a4a5d00e9649c3ad635fc66add0d6ac23e`.
Independent saved-output POST review reproduced all 132 dictionaries and
confirmed the physical counts and preserved first-run failure. Its review
SHA256 is `192e783ad617aa20d62ce05d87e8853360af13523e6156f890569f93c64c717c`.

## Next carrier-and-residual source proposal

The next proposal reconstructs material-carried illumination directly from
observed color, natural guides, and geometry, then filters a separate signed
caller residual. Both demodulation/remodulation strengths remain 1. Existing
Skip sanitation clamps negative values, so this requires a new signed writer;
CPU feasibility cannot certify existing or future GPU signed transport.

Independent source review caught and corrected normal normalization, the
original stride-grid phase, and separate exact-remodulated component bounds.
The filter order and signed binary16 stores are explicitly frozen. Filtering
the residual changes whole color by `(H-I)e`; whole-color quality must pass
independently of SPEC detail. Four static observations are prepared for the
first CPU diagnostic. Constant/rank1, quantization, boundaries, moving light,
volume, grain, and temporal controls are required pending coverage.

## Carrier-and-residual CPU result: inactive architecture

The four registered observations completed in one guarded CPU child. All
predictions were saved before scoring references were loaded. Guard and worker
PID both equal 4680; the direct Python executable identity and resource limits
were independently verified. Actual guard elapsed time was 34.671 seconds,
peak working set 59,756,544 bytes, and minimum available memory 4,751,224,832
bytes. The run completed 1,080 fitted nodes and 9,720 NNLS solves. It added no
SDK, helper, GPU, or compiler work.

Every candidate-active mask is false. SPEC, DIFF, and Skip retain the exact
baseline full-RGBA transport. Whole-color gates pass, but true SPEC gain
1.81981444–1.82018125 and phase 0.07861266–0.07875404 fail the unchanged
thresholds. This tests the fallback behavior; it provides no evidence that
the proposed signed-residual architecture works.

Saved telemetry identifies the activation blocker: maximum support mass is
0.102400093, below the fixed 0.25 cutoff, on all four observations. The two
conditioning fades multiply to this low mass. Component masks pass only as
recorded with the rejected-mass safe denominator; those values do not certify
the actual mass-normalized derivative bounds. The sealed cutoff and separate
8/8 component budgets remain unchanged. A distinct constrained reconstruction
row is being designed to satisfy the budgets by construction.

Independent POST review checked all 140 source pins, exact fallback arrays,
typed caller transport, closed execution records, and the 28 saved gain/phase
decisions. It did not reconstruct all moment metrics from scoring references.
Review SHA256:
`93c3379333d4b8f3f26ba2e185c0c76689ba16ad9634e8b2d4f91b7196e4a586`.
All listed negative controls remain pending. The stain/wave goal is unresolved.

The user confirms that setting specular demodulation to zero left the image
blurred even after holding the camera still. This reported observation is not
a new capture or measured alpha result. It prevents treating motion/history
settling as a sufficient explanation and reinforces the requirement to retain
full demodulation/remodulation strengths and test static material detail.

## Distinct certified moment-row source

The next operator constructs guide-only minimum-L2 illumination rows with
separate material moments and a zero constant-intercept moment. Fixed radii
3, 7, and 15 are considered in order; all folds, channels, and both lobes use
one certified radius. Exact caller-remod scale, represented-row moment error,
outward norm bounds, and separate 8/8 real-arithmetic sensitivity budgets
are part of the source law. Typed FP32 and binary16 errors have explicit
additive allowances. These budgets do not certify native sensitivity or
quality. Full-footprint and all-four-node acceptance may leave substantial
border fallback; full-image primary metrics retain those pixels.

No new operator or fixture was evaluated in this source handoff. Root
verified its 16 owned and 19 direct input identities. Handoff SHA256:
`99f7021a20659b4d579a284f87864065efd2f1c566b6c37fe7b3fdde4899ca6c`.
The planned first falsifier retains the exact four observations, unchanged
gain/phase limits, full strengths, and save-before-reference sequence.

The first certified-row CPU diagnostic completed once. V3 corrected outward
rank/guide-division intervals before execution; earlier drafts remain intact.
All four prediction and represented-row files were saved before references.
Actual model PID 2464 equals the guard PID and direct Python identity. Guard
elapsed time was 67.922 seconds, peak working set 117,047,296 bytes, and
minimum available memory 4,692,402,176 bytes. The run completed 18,864 SVD
calls and 35,568 row dots across four observations; no native/helper work
was added. All 115 frozen identities remain unchanged.

This architecture was exercised: each observation has 6,480 active pixels
of 10,240 and 494 certified nodes. Recorded real visible-remod maxima are
5.18047886 SPEC and 7.48446974 DIFF, below the separate 8/8 budgets.
Whole-color gain 0.99940830–1.00009692 and phase 0.00094474–0.00157785
pass, but true SPEC gain 1.16020894–1.16223812 fails the unchanged
0.95–1.05 interval. SPEC phase 0.04206342–0.04214367 passes. Clean
predictions repeat byte-exactly; all four guide-row files are byte-identical.
These saved CPU results still require independent POST verification.

No failure attribution to boundaries or active estimation follows yet.
Saved-only partition diagnosis is underway; no cropped quality acceptance,
strength reduction, or threshold adjustment is authorized by this result.
Root closed-run receipt SHA256:
`2e5432cb9f5fe89e127e375a335b8f81c4ec5ff93f487390414985668e056331`.

Independent saved-only POST now reproduced all 28 complete metric bodies
with maximum difference zero, checked 8,892 unique represented lobe rows,
and verified typed residual/H/fallback transport. Twenty comparisons pass
and eight fail; the four true-SPEC primary gains fail. Root verified all
44 POST identities. Review SHA256:
`c964d407407a56517140e410c1384f3f55a02622b92d3c9788e2ad75b61ebf8b`.
Separate root POST closure SHA256:
`346f61dd64c5a778b35ecac99ba632ba6e7bd10868d40cd121df006465304740`.

Saved-only failure diagnosis localizes active support to x=10..117,
y=10..69. Of 254 invalid nodes, 208 have all radii out of bounds; 46 fail
the radius-3 visible budget and cannot try larger in-bounds radii. Every
fallback lobe/residual byte equals baseline. On the clean observation,
99.96687 percent of true-SPEC squared error lies in fallback pixels;
active/fallback RMS are 0.00047264/0.03408264. These partitions are
descriptive and do not replace full-image acceptance. The signed global
gain-error contributions also identify fallback as the remaining source.
Diagnosis result SHA256:
`f55e1e5a91c0f1ca497de013694f6b255c0f63e22caad7d5e7c81c220414ce93`.

A distinct source-only proposal clips guide support to the available image
domain with a fixed geometry anchor for virtual boundary nodes. It retains
the original lattice, tent interpolation, common 3/7/15 radii, full strengths,
all-four-node rule, and separate 8/8 certificates. No fabricated or reflected
taps are allowed. It has not evaluated new rows or outputs. Cropped ROI
support can differ from full-frame scene support; source/CPU/native controls
remain necessary. Proposal SHA256:
`443b33a5d142520ede30a54f68b8e4d34d3ec1fb65ee64b3e67b74f3bf2319ac`.

## Clipped boundary CPU result: four static primary passes

The distinct boundary packet was reviewed and executed once. Each of the
four observations has all 10,240 pixels active and all 748 nodes certified.
SPEC gain 0.98222840–0.98495275 and phase 0.00004440–0.00010087 pass
the unchanged limits; whole-color gain 0.99919033–0.99997050 and phase
0.00119168–0.00177091 also pass. Strengths remain 1. Recorded real-remod
sensitivities 5.55215184/7.90646792 stay within separate 8/8 budgets.
Clean repeats and the four guide-row files are byte-identical.

Actual worker PID 30280 equals the guard/journal PID; guard elapsed time is
97.172 seconds, peak working set 151,490,560 bytes, and minimum available
memory 1,844,666,368 bytes. All 111 frozen identities are unchanged.
The four predictions precede references; the run completed 28,852 SVD calls
and 53,856 row dots without any SDK/helper/GPU/compiler work.
Root closed-run receipt SHA256:
`b693d6030e58255f8d18e22e2d9adf0d7246c902101c23d69113b5efb57ff994`.

Independent saved-only POST rebuilt all 28 metric bodies and four typed
allowance bodies with zero difference, plus 13,464 unique primal rows.
Root verified all 45 sealed identities. Separate POST root closure SHA256:
`cda796df9d15b208f1851b524a57d4b26ee6c502588ce340542eb2e96ea4fa3d`.
All pixels were active, so fallback byte assertions were vacuous; negative
signed residual storage was also unexercised.

This is a four-static-rank2 CPU result, not a game fix or general Floor
replacement. Broader rank/quantization/edge/light/volume/grain/temporal
controls, native behavior, and signed GPU transport remain separate
requirements. Existing real water RRTrace reports do not establish
local source-albedo rank. A source-only diagnostic is prepared to examine
source albedo, SDK guides, and stored caller Q as distinct texture roles on
the three old Joint water captures; it does not establish alpha quality.

## Old water saved-guide diagnostic

One guarded descriptive decoder completed on the three 256x256 old Joint
water captures. It decoded 18 payloads and evaluated 352,863 three-by-three
Gram eigenproblems in 108 calls, with zero estimator, scorer, native or
compiler calls. Worker PID 22880 matches the guard; elapsed time is 1.203
seconds, peak working set 46,059,520 bytes, minimum available memory
2,647,552,000 bytes, and all 31 frozen source identities remain unchanged.
Result SHA256:
`eb1a51acc8c674c927f0cea067e1d596190d0ab77e804d45e7c38b9c98fd8c4e`.
Root actual receipt SHA256:
`fcf86b2b5033eb409f4018530f007e1dd7738fb8a0b64b9d2c32822b772578f8`.

Source albedo and SDK-guide RGB moments/rank distributions coincide and
show substantial variation; full RGBA payload hashes differ, so no byte
identity is claimed. Every source/SDK global [S,D,1] Gram has rank 3 at the
fixed descriptive 1e-10 threshold. Small patches still lose rank, especially
in blue; larger patches improve this unfiltered statistic.

Stored historical caller factors behave differently. In the first capture,
the global Gram has rank 2 and every tested patch has rank at most 2. Later
captures have global rank 3, but local conditions are often much weaker
than source/SDK guides. These stored Joint factors are not current alpha
full1 factors. This motivates keeping source/SDK guide operands separate
from caller visible-remod factors; it does not prove a stain cause or certify
the candidate. Geometry, folds, center exclusion and visible 8/8 budgets
were not applied in this diagnostic.

Saved-JSON POST checked 54 variation records, 27 global records and 81
patch groups without new payload decoding or eigen reconstruction. The
first caller pair's saved moments give mean(S+D)=0.2509803949393259 and
variance(S+D)=3.47e-18, consistent with a complementary sum at roundoff
scale, without pixelwise identity proof. Separate root POST closure SHA256:
`59e56bd0bd93fdb94f8feac9bf5fefaebf0773c8b7bc0c535e951c2be32da575`.

A narrow lookup found three old Joint CSOs matching capture metadata
hashes. Adjacent historical source explains profile0/e_ref=.25/linear
codec as a shared n=64 byte-unit normalizer budget split into ns and nd.
These stored coefficients are scaled allocation weights, normalized shares
only after division by their shared sum. The source uses a shared normalizer
for both RR signals. This is a matching adjacent-source explanation;
HLSL-to-CSO build lineage and capture-time DLL/CB execution mapping remain
unverified. Later captures use different profiles and are not a causal A/B.
This evidence does not establish current alpha behavior. Source audit SHA256:
`fb3d9cd8324e975674828961c3bd507434ae75b6108db5c3a1f1a6a49f1649e8`.

## Broader controls: historical pre-run source design

The unchanged clipped operator is planned for 12 families / 44 observations:
degenerate and weak quantized guides, material/light and depth/normal edges,
varying illumination, matched volume/frozen-grain observations, IID noise,
and independently moving illumination. Six bounded model children own
their exact consumed guide/geometry/CB caches; planned child-local guide
builds total 10 for eight globally distinct keys. All 44 predictions must
precede the separate scorer. Capacity is unmeasured; partial work is
preserved without retry. Per-frame CPU sequences do not test native history.

The source design and fixed reference roles passed independent review;
the definitive literal CPU baseline schedule, fullCB and branch ABI remain
a pre-execution gate in the uninvoked packet. Qb baseline allocation,
Qg stored solver guide and Qc caller visible-remod factors stay distinct.
Applicable primary thresholds remain gain 0.95–1.05 / phase <=0.05.
Volume/noise descriptions and the byte-identical volume/frozen-grain pair
cannot establish contradictory semantic passes. Negative signed transport
and actual fallback coverage must be counted, not presumed.

Design completion SHA256:
`c4201b3b01052bbfc979b10cf2c071b69784990d041bbb82b797615f8a2e32c2`.
Source review SHA256:
`cafbdf01c3d0906479fec615f4a9cdb8b5a6343caed085739990e36fbb78f356`.
No broader fixture, model, scorer or native run is accepted at this stage.

The current-alpha source audit identified a material format distinction:
production caller factor textures u4/u5 are R8 FORMAT28; the diagnostic
helper may use FORMAT10 half. Production Qc is the half-typed normalized
R8 LOAD after the writer's half(Qb)-to-R8 roundtrip, while internal baseline
remod uses FLOAT Qb. The four completed static tests therefore do not
establish production-format equivalence. The new packet must explicitly
freeze this schedule, use the actual 65500 safe-half clamp, and establish
original-branch depth/emissive/overshoot eligibility before execution.

The operative V4 production-format literal baseline passed independent
SOURCE review; root verified its 12 direct sealed identities. Review SHA256:
`78e83a286d1ffa089ffa9a3ba241cd1feded21ea602460571500a81a434ddfc0`.
Roles now separate raw source materials, actual SDK guide resources Qsdk,
stored normalization Qfactor, half caller LOAD Qc and internal FLOAT Qb.
The new packet explicitly uses Gram columns [QcSPEC,QcDIFF,1] and visible
sensitivity h=Qc^2/max(actualRm,floor,1e-4). This differs from a statement
about SDK-guide rank; the old real-water SDK statistic does not certify it.
The copied old allowance assuming callerQc=half(Qg) is not operative for
productionQc != actualRm; a new explicit-operand allowance is required.

CPU conversion policies are fixed reference assumptions. Ideal FLOAT-to-
UNORM uses clamp, scale, add 0.5 and truncate; Direct3D permits 0.6 integer-
side ULP tolerance. Half/compiler equivalence and actual GPU bytes remain
unmeasured. See Microsoft's [Direct3D conversion specification](https://microsoft.github.io/DirectX-Specs/d3d/archive/D3D11_3_FunctionalSpec.htm).
No broader numerical quality run or GPU acceptance follows from this
source review alone.

## Broader production-format CPU run: component preservation fails

The once-authorized six model children and separate scorer are now CLOSED.
All 44 saved predictions preceded scoring references. Actual work was
44 observations, 10 child-local guide builds, 50,914 model-solver SVD calls and 536,076
row-dot calls. All seven guarded children completed within their registered
limits; 78 frozen source identities stayed unchanged. Root's immutable
physical receipt SHA256 is
`30299bd6a91e627d02a05b1c840039a14f9e54786fe99b37c7c5710fc6e6e164`.
This CPU run made no SDK, helper, GPU or compiler calls.

Count qualification found during the next packet's source review: the
retained fixed-L diagnostic calls NumPy matrix_rank, which uses an internal
SVD. Original scorer rank checks were not separately metered. The 50,914
figure is therefore the model-solver counter, not every numerical-library
SVD operation. The immutable original receipt is preserved; this note
corrects its interpretation without a run or metric change. The new paired
scorer will meter fixed-L rank checks and 2x2 solves separately.

The saved scorer reports whole-color 44 PASS / 0 FAIL / 0 NA, but true
SPEC 25 PASS / 19 FAIL / 0 NA. The unchanged gain gate is 0.95–1.05 and
phase gate <=0.05. Four constant/weak-quantized guide cases use fallback
at all 10,240 pixels and fail component detail. Shared varying illumination
fails despite all pixels being active, with SPEC gain 0.490065. Fourteen
of sixteen independently moving-light frames fail, with SPEC gain ranging
from 0.472208 to 1.419824. Whole-color acceptance therefore hides substantial
component loss; this operator is not accepted as a full-detail solution.

Independent saved-only metric, typed transport and primal-certificate POST
checks are pending. The next source investigation separates degenerate-guide
fallback failures from active illumination-model failures. Demod strengths
remain 1; reducing specular demod is not a solution or an acceptance escape.
Per-frame CPU results do not test native history. Identical saved volume /
frozen-grain arrays and volume descriptors do not establish contradictory
semantic passes or a volume fix. No current-alpha game fix, GPU implementation
or production deployment is accepted.

The user recalls that setting specular demodulation to 0 left the image
blurred even with a stationary camera after waiting. This is a remembered
game observation, not a newly matched capture. It prevents accepting
reduced demod as an apparent motion/history workaround and supports keeping
full demod/remod detail as a required outcome.

The independent saved-output audit is CLOSED: 44 NPZ decodes, 267 preserved
metric-body calls and 842 fixed 2x2 diagnostic solves, with zero SVD,
estimator/model/scorer-entry or native calls. All saved metric/NA gates and
descriptive summaries matched exactly. Candidate rejection is confirmed.
Audit result SHA256:
`38a5cb0cb7aa047deb601344a4e19d8537407c7f0a8ac17019d07a805608769d`.
Root verified the sealed POST's 244 direct identities (13 owned / 231
external), actual worker PID10680 and closed guard. POST review SHA256 is
`48b32c9ca966aae9d9a135486ed79be6ca7afcbadbd326ffc428a8ab861b5a46`;
seal SHA256 is
`2bc20c46295991c41c5a1eb90e4423a60b5d724be2afe39a8d8be7d8e8d81b7d`.
The separate primal/typed POST is also CLOSED and sealed; root verified
its 28 direct identities. It checked 51,372 unique represented lobe rows
over eight guide keys, all 44 stored typed fields and allowance formulas,
six nonvacuous fallback cases and 117 negative Skip words across three
volume repeats. Actual guard covered PID30764 for 155.656s, with no retry.
Review SHA256:
`c3436ead6757c42f8cf0e30b7427414ecc1ad7b959fb2f89454a43f25806a5f3`.
Saved sigma/rank lower bounds remain conditional; no SVD/rejected-fit or
row-dot-C reconstruction was performed. Valid sensitivity bounds and
typed transport do not prove the semantic lobe allocation model.

The POST-only fixed trueSPEC harmonic ledger distinguishes allocation from
residual filtering. In the fully active shared-light case, the modeled SPEC
projection is about 0.49030 and visible SPEC about 0.49038: the substantial
SPEC deficit already exists before half transport and before residual H.
The exact residual projection separately changes from about 0.11852 to
final Skip 0.09416. H acts only on residual/Skip, not visible SPEC/DIFF.
Whole-color agreement can therefore coexist with wrong lobe allocation
and a smaller additional residual-filter detail change. Shared diffuse /
illumination carriers prevent interpreting these projections as isolated
causal transfers of physical SPEC energy.

The modeled-minus-visible ledger delta is a typed-transport diagnostic
only where active modeling covers the evaluated pixels. Dummy zero modeled
arrays in all-fallback cases, and mixed modeled/baseline boundary cases,
must not be labeled half-store losses. This evidence is from synthetic CPU
cases; it does not identify the current-alpha game's stain cause by itself.

The modeled-minus-visible diagnostic also includes deterministic
Qc/max(actualRm,CBfloor,1e-4) transfer and clamp policy. Even in fully active
cases it is not solely a half-rounding measurement; separating store error
requires comparison with the corresponding ideal visible operand. The next
candidate decision targets allocation rather than residual-filter tuning.
The user's four allocation critique points are research suggestions, not
additional acceptance gates.

A separately sealed SOURCE memo proposes RGB material separation with
per-destination varying scalar lobe light and an additive patch RGB term.
Strict unique-B eligibility can reject fixed SPEC color directions; an
independent review is examining whether only a constant brightness gauge
remains, while preserving overlap, transport, native-RR and volume limits.
This has not run as an estimator. Existing old-water metadata provides no
positive evidence of title-provided noisy/denoised SPEC/DIFF resources;
recorded internal lobe inputs/outputs do not establish such availability.

The paired raw-material allocation experiment compares:
three constant-light columns versus seven columns with separate SPEC/DIFF
x/y light slopes. Both arms use the same receiver conversion
a=raw*den/Qc^2 after physical-light interpolation, with
den=max(actualRm,CBfloor,1e-4), the same full1 demod/remod, residual H and
stored quality gates. This distinguishes illumination-model changes from
material/normalization-role compensation. Zero Qc cannot be divided; extra
rank/moment constraints may increase fallback. Source law SHA256 is
`47261b5572e068089e5539624da7dfec38478a3bb2b2586632b4d9be80beb9ba`.
Root verified its eight direct identities. Implementation SOURCE review
passed; root verified 22 review pins plus seven V3 count-addendum pins.
The final packet contains 12 serial model children and one separate scorer,
88 paired predictions, 534 unchanged detail-body calls and 892 retained
fixed-L rank/solve calls on full success. Root verified 105 completion and
103 freeze identities plus 296 absent targets / 13 empty owned TEMPs.
Independent final prelaunch review passed. The one authorized run is now
CLOSED: twelve model children and one scorer completed normally, with 88
predictions sealed before references. Root rechecked all 103 frozen and 176
prediction/telemetry identities, actual worker PIDs/executables and guards.
Actual model work was 20 guide builds, 94,659 model-solver SVD calls and
932,022 row-dot calls. The separate scorer completed 534 metric-body calls
and 892 each of fixed-L coefficient/rank/solve calls. The rank calls can
internally use SVD; these are distinct from the model count, and backend
primitive counts remain unmeasured. Physical receipt SHA256:
`4370d58364efc6070370c3d4e4bbed98f87802098e8ce7df72ad40a781496a11`.

Saved scorer scalars show wholeC 44/44 PASS for each arm, but trueSPEC only
25/44 PASS for RAW3 and 24/44 for RAW7. Shared-varying-light SPEC gain is
about 0.49774 versus 0.58885; the affine arm still fails and uses fallback
at 2,352 of 10,240 pixels. Moving-light frame8 adds a phase failure in RAW7.
Neither arm is an accepted solution. Independent saved-only metric/stage
POST is now CLOSED and sealed: one actual PID27332 decoded 88 NPZs, checked
534 unchanged metrics/NA gates and completed 2,212 determinant/2x2 diagnostics.
All saved metric/paired/family dictionaries matched exactly, with no model,
scorer entry, SVD, SDK/helper/GPU/compiler invocation. Root verified the
24 unique direct seal identities. Closure SHA256:
`2151a87054ae3ddacac58dd954604ef68ebb40ab55fe48746b88f95e894063cf`.
In RAW3's fully active shared-light case, physical raw*I SPEC projection is
0.497968 and actual visible projection 0.497961. Its primary deficiency
precedes storage; the half transport difference is small. RAW7 has mixed
fallback, so its full-ROI stage deltas cannot be called store error.

The separate primal/typed decoder reached 82 per-case assertion log entries
before the 240s guard terminated owned PID12568. Empty stderr and current
105 before-input/source pins were verified, but no final verifier seal or
complete primitive count exists. All 44 RAW7 and the first 38 RAW3 cases
were logged; RAW3 moving-light frames10 through15 were unlogged in that
attempt. The distinct six-case continuation subsequently CLOSED with the
qualified scope recorded in the 2026-10-02 addendum below; the failed
attempt is preserved.
Timeout closure SHA256:
`f109b6dd8ae7429c8fe2c9fd97edd40246fcde8bbfc9d2770bbffa1812f4ec51`.
Floor/Qc0 coverage limitations remain explicit; these CPU checks are not
alpha-game or GPU acceptance.

The separate six-payload raw RGB information screen is now CLOSED. Root's
sole direct worker PID23432 decoded six old Joint source S/D float32 RGBA
dumps (6,291,456 bytes), computed 156,828 small eigenproblems in 48 calls
and made no C/factor/SDK-guide/output decode, model, score or native calls.
Guard elapsed 0.812s; all 22 frozen identities stayed unchanged.
Result SHA256:
`38a0557ffab4110da3f77de6d6f90385a40dfeac8f02ac5c497f665982239fe3`.

The raw material pairs have substantial chromatic separation: 65,391–65,395
of 65,536 pairs have nonzero cross direction in each capture. Global
unit-cross-normal Gram rank is three at every fixed descriptive eigen
cutoff, with condition about 42–43. Local normal systems are considerably
worse: at radius3, condition medians are about 149–157 and 107–116 of
4,356 patch systems have undefined condition. This supports conditional
RGB investigation but establishes neither combined visible cap8 stability
nor alpha/game behavior. No geometry filtering, half emulation, coefficient
fit or true lobe allocation was tested. A bounded independent source/JSON
POST passed; root verified its 15 direct identities. It checked saved
global eigen-triple rank recounts, patch histogram and distribution
consistency, without independently reconstructing pixels or eigensystems.
Review SHA256:
`d9ca8f1857ba348220f0a097ab81ba36df78c75511d5cef2773dcf45a29815ad`.

The conditional RGB follow-up now has a SOURCE operator law and falsifiers:
complete direct-plus-B cross-channel visible cap8, raw-material perturbation
bounds, strict patch rank versus fixed-SPEC-direction gauge, and full1 typed
transport. Rank or a small fit residual cannot certify actual scalar lobe
lighting: colored illumination can fit the material plane perfectly while
allocating the wrong physical lobes. The bounded colored controls therefore
include those violations and varying additive volume. Existing gray44
failures remain controls; no production fix has been accepted.

Current RAW and the RGB copied baseline target natural FORMAT28/R8 guide
factors loaded as half Qc. Historical HALF10-factor experiments are distinct;
dedicated caller factors are required only if a future variant chooses that
target. Raw S/D must remain distinct from quantized SDK/caller guides. Signed
Skip requires a new writer because current production conversion clips its
negative values, although composition can already add signed Skip.

Old-water SOURCE inventory additionally locates raw C at the same 256x256
ROI as S/D in all three captures, alongside source normals/depth. Separate
roughness and exposure provenance are absent. Differing Joint profiles,
camera/jitter and frames do not establish a temporal repeat. A future model
applicability test on these actual inputs must preserve old-Joint versus
current-alpha and captured-F32 versus represented LOAD distinctions; it
cannot establish physical truth or a game fix without stronger evidence.

### 2026-10-02 closure and current-alpha localization addendum

The RAW3 remaining-six saved primal/typed continuation is CLOSED: actual
PID26568 completed six assertions and 13,464 represented lobe rows in
23.047s, with the 105 source/input pins verified. Together with the qualified
82-entry timeout prefix, this supplies per-case assertion coverage for all
88 cases. It does not recover the original run's unknown aggregate counts,
maxima or final seal. All six new cases had 10,240 active pixels; their
fallback/floor/Qc0/saturation checks are therefore vacuous. Frame14 had 39
negative exact residual/first-store words, with no negative final Skip.
No new model, scorer, SVD or native work occurred. Root closure SHA256:
`7ab038f8c8aff0945c7e47cb6109957d621f44b3fd34960b7edc0bf61d004ffd`.

The conditional RGB89 V2 CPU experiment is also CLOSED. Thirty-three model
children and one separate scorer produced 89 predictions (44 unchanged
gray, 45 colored), with 37 guide builds, 6,778 model-solver SVD calls and
694,400 row-dot calls. All predictions preceded clean-reference scoring;
the scorer completed 184 metric bodies (178 primary, six volume alternates).
Root verified 99 frozen and 178 prediction/telemetry pins. Physical receipt
SHA256:
`cc701e0eb22fb84652230008871c57cf6e08d149ee52f369ebbea462735f0eda`.
WholeC passed 89/89, while trueSPEC passed 32/45 colored and 0/44 gray.
Strict clean/shared scalar-light/moving/material-detail controls passed
11/11 with all pixels active. Whole closure is insufficient to establish
physical allocation or detail acceptance.

RGB89's independent saved-only metric/stage POST CLOSED under PID29052 in
9.031s: 89 NPZs, 89 references, 184 metric bodies, 178 H passes and 1,647
fixed-L 2x2 solves, with no model/scorer entry, SVD or native invocation.
Root closure SHA256:
`27820aa5808dda507ec44057093767a78badbfca098e667eb9e644b3d6c4f3b0`.
Physical raw*I, compensated M, ideal remodulation and actual visible output
remain separate stages. The fully active COLORED_DIFF_LIGHT and
IN_PLANE_WRONG_LOBE controls fail trueSPEC before typed transport; the
in-plane control has the same observables/prediction as STRICT_CLEAN but a
different true lobe. Small half/remodulation errors cannot repair that
semantic ambiguity. These physical-stage fields use modeled illumination,
not independently measured native physical radiance.

All 44 gray controls and 11 colored controls use fallback everywhere;
another two colored controls mix active and fallback pixels. Active-only
stage errors cannot be extended to those whole-ROI results. FLOOR_ACTIVE
and SIGNAL_SATURATION have zero active pixels despite positive Qc. Their
aggregate floor/Qc0 counts provide no modeled active-floor or saturation
coverage. Negative first-store/H words occur only in inactive pixels, and
final Skip has no negative words. Active signed transport and a new signed
GPU writer remain untested. The uncertainty law conditions on fixed Qc/Rm;
it does not certify the complete C-dependent guide/quantizer graph.

The actual-water unfiltered RGB V2 observation is CLOSED: three guarded
children decoded nine C/S/D payloads and evaluated six arms (captured F32
and declared half-material LOAD for each capture), totaling 3,072 small
eigen calls and 786,432 eigenproblems. All 44 closing identities held; no
SDK/helper/GPU/compiler work occurred. Physical receipt SHA256:
`230f8b531fed39b2ceb9de480e7eeac596e696e378f993dea19ccc4a44ba2b70`.
Every arm has zero receivers meeting all six point physical channel
caps <=8. SPEC cap medians are about 121–128, DIFF about 21.4. Defined
solutions have negative SPEC coefficients at about 17.8–19.2% and DIFF at
48.6–52.3%; these fitted signs are not negative physical-radiance evidence.
Descriptive chromatic rank and small same-patch residuals do not establish
stable or correct local allocation. Half central statistics remain close,
but changed rank masks and large extreme changes preclude uniform half
stability. These are unfiltered old Joint observations, without current
caller-factor compensation, geometry/roughness qualification, held-out
truth or native history; zero coverage is not a current-alpha fallback
percentage or a proof against all RGB methods.

The next current-alpha localization packet remains SOURCE ONLY. Its
preregistration is
`tools_tmp/fsrd_old_water_SDK_stage_hitAlpha_localization_SOURCE_preparation_20261002/preregistration.md`
(SHA256 `d9a35dd41df9e38f97d7d3b37b097c9b3fd697392c3a289aa822c28ae3b04bca`).
It proposes the already CLOSED frame32732 full1, natural-R8, Flags54,
bias-disabled conversion, with four fresh contexts times eight SDK steps:
original SPEC alpha versus constant1, each under reset-every-step and
continue-after-first-reset schedules. Constant1 changes only eligible
finite half alpha in [0,65504); max-half sentinel65504 and invalid alpha
are preserved. Signal RGB, DIFF alpha, guide RGBA, Qc and captured Skip
stay fixed. The existing af530 camera-delta adapter uses 39 camera fields;
no new conversion helper or compile is proposed. A reviewed byte assembler,
physical freeze, native prelaunch review and distinct root authorization
must precede execution. No actual SDK steps or native authorization are
claimed here.

The planned comparison retains full1 demod/remod and inspects remodulated
SPEC, DIFF, Skip and whole separately against direct input composition.
Eight repeated-packet steps test local early-history dependence; they are
not chronological captures or mature game history. The user's observation
that SPEC demod0 still blurs after a stationary-camera wait remains a
remembered game observation, not a newly matched capture. Static camera
alone does not freeze water, lighting, jitter or provider history. These
controls may localize an SDK alpha/history response, but none of the CPU
closures or this source plan establishes a full1 stain/wave fix or current
alpha quality acceptance.

### 2026-10-02 actual native32 and saved-stage closure addendum

The preceding SOURCE ONLY plan is retained as its prelaunch history. The
first authorized native attempt is CLOSED as a failure: PID23136 entered
D3D device setup, but default `std::quoted` extraction consumed unescaped
Windows path backslashes. Opening the first input failed before provider
loading, any SDK call or any RR dispatch. One helper launched, zero outputs
were created, and the failed packet/logs remain preserved. Failure receipt
SHA256:
`ed817e13b8cf6500dc70cae3f2f7280621185f770b8b31524513cd0dc69827c5`.

A distinct V2 packet repaired job-path serialization with forward slashes;
its parser contract checks preserved input, camera, configuration and
control identities. The existing adapter/provider were reused. Root's
separately authorized V2 execution CLOSED normally: four fresh helpers,
eight native RR dispatches each, 32 completed dispatches, eight lobe output
files and four applied-control files. Ordinary errors/warnings were zero,
and source identities held before/after. These actual totals exclude the
preserved V1 pre-SDK failure. Native physical receipt SHA256:
`860306d3a06107723dbb5251993dbff1b08f55ae2cdd812c394ed381c962d190`.

The separately authorized saved-stage POST CLOSED under PID27280 in 3.203s.
It decoded 13 payloads (8,912,896 bytes), formed 33 endpoints and completed
256 identity plus 256 paired comparison bodies, 128 raw RGB/A coverage
bodies and 66 pre-safe total coverage bodies. It added zero native/SDK/GPU/
compiler calls. POST physical receipt SHA256:
`535d7c1cda342f44ad4710dfb71e594f6cfc1b7c688eed1cfed416507d23189e`.
The author retained all 512 saved comparison rows; independent final review
passed with no blockers. Author interpretation closure SHA256 is
`1cce0c3482ef42e0d82c4b54340073edc9b0e9de12f3e780ccbee4cb6f06d0a4`;
peer final completion SHA256 is
`078814ef7ce58043d6864eab287e4f6697370b94c7764cab80badc661bed5c30`.
This note update reads saved scalars/text only and performs no additional
payload decode or numerical/native rerun.

Original versus constant1 input alpha under RESET gives bit-exact
remodulated SPEC for all eight frames in both windows, with tiny DIFF and
whole differences. Under CONTINUE, SPEC remains exact through frame5 and
differs at frames6/7. At frame7, full-crop whole RGB RMS between alpha arms
is 0.000196809958, versus reset/continue RMS 0.015839194951 for ORIGINAL
and 0.015845939693 for CONSTANT1. In the fixed water ROI, frame7 SPEC
alpha contrast is 0.000074822812, versus ORIGINAL history contrast
0.003823684508. These compare descriptive saved responses in captured
units; they are not percentages of image error explained, significance
claims or a private-weight diagnosis. No same-arm replication distribution
exists, and small cross-context differences remain even under RESET.

All reported raw native RGB/A and pre-safe totals were finite. Reported
native output A minimum, maximum and mean were zero for both lobes in every
context/frame/window. This describes output storage; it neither proves
input A was ignored nor establishes hit-distance semantics. Fixed Skip
comparisons were bit-exact. Native SPEC, DIFF and whole differ from the
assigned-signal direct-composition identity throughout; proximity to that
transport reference is not measured clean-lobe quality. Component changes
that round away in the final whole half store remain in the stage ledger.

Full1 demod/remod, original caller factors and captured Skip were preserved.
The larger history-schedule response is observed before final whole
composition, but repeatedly feeding the same nonzero motion and camera
delta confounds static-history attribution. A distinct coherent static-
transport control is needed to separate that response from repeated
transport. Eight local steps are neither chronological game observations
nor settled provider history. The user's static-camera demod0 blur report
remains an observation requiring matched evidence; this packet establishes
no current-game stain/wave/blur cause, quality improvement or accepted fix.


### 2026-10-02 observed-C closure and stop/defer memory

The six-payload saved POST is CLOSED; author and independent saved-JSON
review PASS. No SDK or conversion reran. Full1 Flags54/bias-disabled
frame32732 final whole RMS against original observed C is 1.581639695e-5
(full crop) and 1.720001269e-5 (water ROI). It is not bit-exact: 3589/1209
RGB half words differ. Pre-safe clipping and nonfinite counts are zero.
Qc0 occurs only in full-crop DIFF: 10 words/6 pixels outside the water ROI.
Root receipt SHA256:
`e08caab2cb90b3a9bf194e843e4b90126bcf8c027229d6a8cc01fc6c8c058054`.
These small transport discrepancies and larger native-versus-assigned-signal
RMS magnitudes use different references; they are not additive error
budgets, clean-lobe truth or quality acceptance.

Stop completed tests. The static32 SOURCE packet is DEFERRED and uninvoked;
no further zero-motion, alpha, defaults or output-A replay follows. Clean
static native response departure and guide bias are already established in
bounded fixtures. The earlier proposed static transport control remains
historical, not the selected repair priority. Read the current
[audit and stop decisions](../tools_tmp/fsrd_stain_wave_duplicate_open_question_SOURCE_audit_20261002/AUDIT.md)
and its CLEAN_STAGE_AMENDMENT.md before proposing more work.

The distinct untested hypothesis is joint mask34 versus independent DIFF2
and SPEC32 contexts, supported by the existing runner with full1 signals,
guides, caller factors and Skip fixed. Its packet is SOURCE only:
`tools_tmp/fsrd_joint_vs_independent_lobes_SOURCE_preparation_20261002`.
CLEAN first: six fresh contexts times 64 steps, fixed joint/split repeats.
If either split fails unchanged detail gates, STOP this candidate. OBSERVED
is conditional on CLEAN passing; accepted quality also requires the actual
composition graph and strict observed-noise nonincrease. No assembly/native
authority or quality fix is claimed by this memory update.

After compaction, read the latest tracked
[clean-stage partition](fsrd_clean_material_response_stage_partition.md),
[default/Configure flow](fsrd_default_vector_and_configure_flow.md) and
[output initialization](fsrd_native_output_initialization.md) before future
tests. Full1 remains required; the user's static demod0 blur is an
observation, not a resolved cause or game fix.


### 2026-10-02 CLEAN joint/split CLOSED_REJECT memory

Read `tools_tmp/fsrd_ACTIVE_PROGRESS_20261002.md` after compaction. Do not
repeat CLOSED assembly/native/POST or earlier alpha/default/output-A tests.

Six fresh CLEAN contexts completed 384 RR dispatches with controls,
active outputs, inactive-empty files and diagnostics physically checked.
Separate public process/context/resource lifetimes and states do not prove
independent hidden provider architecture. Root native receipt SHA256:
`2d893a9052f9123b474fcb9066d243d3e27a76483c1f4792c9ebe60318a1cd60`.
The saved CPU POST CLOSED: 201 binary decodes plus one truth member,
256 literal compositions, 32 metrics/32 retention rows, SDK/GPU0. Both
splits fail absolute gain for both references/all64 frames/allwindows;
phase and relative retention pass, efficacy is false. Author and peer
interpretation PASS. CPU root receipt SHA256:
`846a87ebf4dfc24b4fbb9ac309922964b60d2c589213cdfbf1477b217093f7df`.

The actual fixed frame63 CSO check now CLOSED: two GPU helpers/dispatches,
six outputs and one CPU gain child, RX9070/debug1, ordinary diagnostics0,
SDK0. Split0 gain is q1.241055727/raw1.287719607; joint J0 is
q1.241442800/raw1.288122773. Both exceed the fixed1.05 upper detail bound.
Root therefore rejects this candidate: one failed required per-frame
predicate defeats the all64 requirement. Root physical receipt SHA256:
`6350aeff473d887122a559bc3460a4e5f9e273f07865362ef14cbb815d7efa83`.
Actual endpoint peer interpretation remains pending at this note boundary;
these statements bind root physical evidence and its fixed gain result.

Matched split0 frame63 CPU q gain1.1822373 differs from actual GPU1.2410557.
This establishes an endpoint arithmetic/representation discrepancy in the
current cohort; its cause is UNKNOWN. Do not assign it automatically to
addition association/HLSL half or calibrate with historical cross-cohort
gains. Equal repeated native inputs permit endpoint input equivalence;
omitted GPU traces were not measured. Neither all64 GPU quality nor noise
was measured. No OBSERVED/water/parameter resweep follows CLOSED_REJECT.

Next guide design fb8db934 and opt-in runner source163045a remain SOURCE
only; no production implementation, build or native input packet is claimed.
Float-guide/provider behavior is unproved. Full1 and unchanged detail gates
remain required; no game fix is accepted. Cumulative SDK491, helpers1816,
RR API26714 and queued/completed26706 are distinct counters.


### 2026-10-02 guide identity STOP and saved RGB scope memory

Read the latest `tools_tmp/fsrd_ACTIVE_PROGRESS_20261002.md` after compaction.
Since the prior note, the sole opt-in test-runner compile CLOSED
(cff09a7d; EXE b239b178), and linear CPU input assembly CLOSED (6c88a917).
This is an isolated test executable, not a game DLL build or deployment.
Do not rebuild or rerun assembly.

The first native identity packet STOPPED before F32: one R8 child completed
64 RR dispatches with rc0, identical controls and zero ordinary diagnostics,
but both old/new complete RGBA output identities differ. Driver exit1 is
the registered compatibility STOP, not proof of a provider execution bug.
Root prefix receipt SHA256:
`26afb30425a999e92581cca80cdfc9414d94f4a6c95158ddbb1714a5f85fffe7`.
Independent prefix interpretation59bc34c3 PASS. Preserve the original
packet/no-retry closure; neither F32 nor sqrt ran.

The separate CLOSED saved integer-word comparison narrows the mismatch:
changed RGBA words are DIFF[12090,250,0,0] and SPEC[13026,19380,7,0].
Alpha is exact; RGB differs, ruling out an alpha-only explanation for these
files. First R/G changes at frame48 describe storage, not causation.
No floating magnitude, finite-radiance coverage or quality was measured.
Root saved scope SHA256:
`700f53bbbeeb50d78581cbe9b495ee0f0d2f4efc0fe19fc9c4877cbc2dc678e9`;
independent saved-scope review3744425a PASS. The source audit finds no
changed entered R8 behavior; source compatibility did not produce runtime
identity. Private processing, compiler/layout or other cause remains UNKNOWN.
Do not reopen output-A initialization or determinism sweeps.

A separately registered new-R8 versus F32 format gate is under assessment
only, without execution authority; no continuation of the failed packet is
implied. Frame63 endpoint peer4ea7af confirms the prior joint/split rejection;
the matched CPU/GPU gap cause remains UNKNOWN. No production/game fix exists.
Actual ledger: SDK492/RR491/query1, helpers1817, RR API26778,
queued=completed26770, historical failed-not-queued8. Compiler and CPU
serializer work remain separate from native totals. This note update adds
no payload decode, floating/numerical test, compiler or native work.


### 2026-10-02 same-runner F32 CLOSED_FAIL and contract-audit memory

Read the latest `tools_tmp/fsrd_ACTIVE_PROGRESS_20261002.md` after compaction.
A distinct same-new-runner F32-linear64 identity gate is ACTUALLY CLOSED_FAIL.
Child14852 completed64 with rc0, exact controls and zero ordinary diagnostics;
the driver stopped on RGB identity failure. Author86641442 and independent
POST b8b53e3f PASS interpret this failed experiment, not a runtime repair.
Root physical receipt SHA256:
`f0c276ce251ccac11e61e77ff5b88959785647f17d27d1060fcecb8334869f3a`.

Against the already CLOSED new-R8 outputs, changed RGBA words are
DIFF[38077,1369,0,0] and SPEC[37970,34707,30,0]. Both first RGB changes are
frame37; alpha is exact throughout. No float magnitude, gain, composition,
quality or private-precision cause was measured. Same binary alone does
not isolate format as the cause without same-format replication; cause is
UNKNOWN, and old/default runtime equivalence remains failed. No repeated
R8, guide assembly or build occurred. Do not retry this packet.

Root13-pin check413a39 PASS preceded a separate ancillary wrong guard-path
read. Reading the actual job.guard path corrected metadata only; no child
or payload comparison repeated. Actual cumulative SDK493/RR492/query1,
helpers1818, RR API26842, queued=completed26834, historical failed8.

Conditional sqrt SOURCE3df2ce/peer d2d880 PASS remains UNACTIVATED because
the linear identity prerequisite failed. No alternate sqrt, bank or retry
follows. Existing test-runner build is separate from a game DLL change;
no production/game fix or quality acceptance exists.

Normal/roughness SOURCE audit87fa820 establishes SDK B roughness10 bits and
A material-type2 bits: there is no 2-bit roughness defect. An exact-decoded
F32-normal resource contrast remains unmeasured, low in causal evidence
and DEFERRED; it cannot recover precision already quantized into R10.
Separate SOURCE contract audits of actual CLEAN fixture generation and
production normal/materialA are requested, with no test authorization or
claimed error. Preserve the earlier closed normal/output-A/default controls.
This memory update reads source/saved JSON only and adds no payload decode,
numerical test, compiler or native work.


### 2026-10-02 F32-sqrt bundle NO_CHANGE rejection and SOURCE veto memory

Read the latest `tools_tmp/fsrd_ACTIVE_PROGRESS_20261002.md` after compaction.
The distinct bundle's CPU assembly29d46b0a and native64 run6cdf11b8 are
ACTUALLY CLOSED. Complete DIFF/SPEC RGBA streams equal the old J0/J1
full64 streams exactly. Author1baa27e5 and peer17e21012 PASS prove fixed
frame63's eleven typed SRVs, CB96, CSO/EXE, scorer and references equal.
Thus the prior measured q gain1.2414427995681763/raw1.2881227731704712
failure transfers to this endpoint and rejects the required all64 predicate.
Root NO_CHANGE rejection receipt:
`tools_tmp/fsrd_F32sqrt_bundle_ROOT_REJECTED_equivalence_receipt_20261002.json`.

Prepared CSO jobs stayed UNINVOKED: no new composition, gain, noise or
all64 quality result was measured. Equal current streams/operands do not
establish future determinism or a private cause. Do not rerun this bundle.
The original conditional sqrt remains UNACTIVATED; both preceding identity
FAIL packets retain their distinct closures. Actual cumulative SDK494/RR493/
query1, helpers1819, RR API26906, queued=completed26898, historical failed8;
compiler1 is separate. No production/game fix exists.

SOURCE vetoes require no new tests. CLEAN normal packing already matches
the public channel contract. Prior saved captured conversion evidence has
materialA=0 everywhere, so removing material boundaries is a no-op here;
do not repeat its inventory or native A0. Direct4 was already tried in the
user's Auto/Direct A/B without clear improvement or with worse output.
Guide-A controls are already CLOSED; they do not establish universal SDK
ignore-A behavior. Do not repeat these fields or encoding banks.

Stability SOURCE audits c4b60a85/e70b472f confirm both CLEAN and water32 use
StabilityBias=.5. Water's bias-disabled label concerns converter Flags54,
not SDK StabilityBias. The AMD tuple's trailing0 is Gaussian relaxation,
not stability. There is no alleged operating-point mismatch to repair and
no stability tuning bank is selected.

The user's goal remains ACTIVE and unresolved: preserve full1 demod/remod
while solving stain/wave and static detail. The reported static-camera
demod0 blur persists as an observation, not a resolved cause. Game remains
unavailable; no new capture is requested. This continuity append reads
selected source/saved JSON only and performs no payload/readback recalculation,
numerical/native test, compiler run or production edit.


### 2026-10-02 unit-pair CLOSED_REJECT memory

Read `tools_tmp/fsrd_ACTIVE_PROGRESS_20261002.md` after compaction. The
P/T(P)*B ratio family is known and previously failed general acceptance.
This registered measurement was the bounded distinct matched joint SDK
unit(1,1) pilot with original guides/hitA, not a new ratio law or inverse.

CPU9c34e6 CLOSED unit input assembly changed only signal RGB to half1,
preserving A and the other five inputs. Native067781 CLOSED one joint
unit64 context; the closed old main was reused without a baseline rerun.
Quotient504717 CLOSED four fixed-frame63 slices: exact rational division,
RN32 then RN16 store, original A preserved, atomic fallback0. Corrected
operands differ from the old main. No full64 quotient or quality bank ran.

GPU+score5ab2b4 CLOSED one actual historical-CSO dispatch and one CPU gain
child. Actual frame63 gain is raw1.2539896965026855/q1.2085458040237427,
outside the unchanged [.95,1.05] requirement. One failed required frame
rejects the all64 conjunction; a passing endpoint could not accept it.
Root GPU rejection receipt SHA256:
`aaf945749c56ec6406fdcc57fdfb2c30c92096969ba8465a581c1216fe44143d`.
Author59b4e060 and final independent peer76f8648a PASS close interpretation.
No new all64 quality, noise, phase or repeat result was measured. This
shows the declared constant-unit row-gain correction is insufficient for
this fixture, not a general inverse impossibility or unique private cause.

Stop this unit-ratio candidate/family: no unit0/unit2, basis/amplitude bank,
fit, OBS, window sweep, baseline rerun or production promotion. Existing
representative polynomial smoothing has analytic detail/phase failures;
no exposure-contract mismatch has been established. Neither justifies
reopening smoothing/exposure banks. Actual ledger SDK495/RR494/query1,
helpers1821, RR API26970, queued=completed26962, historical failed8;
compiler1 is separate.

The full1 stain/wave/detail goal remains ACTIVE and unresolved. Game is
unavailable; the reported static-camera demod0 blur persists as an
observation, not a resolved cause. No production/game fix is accepted.
This append reads selected saved JSON/scalars only and adds no payload
decode, quotient math, numerical test, compiler or native work.

## Source frontier after unit-pair rejection — 2026-10-02

The full1 stain/wave/detail goal is unresolved. The user's remembered demod0
blur persists with a static camera; waiting for history or reducing demodulation
is not an accepted repair. No production code, DLL or game deployment changed.

The partial-rank SPEC pair law is conditionally valid but does not establish
physical detail: colored DIFF illumination can exchange spatial detail along
the SPEC direction while preserving all available observations. This is a
specific wrong-lobe ambiguity, not a claim that all future algorithms are
impossible. Its exact graph branch was not previously executed; no new graph
prototype or numerical bank was commissioned. The inter-API albedo audit also
found compatible integrated environment-BRDF semantics, with the actual
title's producer formula still unknown; no second BRDF conversion is justified.

Two further SOURCE audits selected no concrete implementation correction:

- [Composition binding audit](../tools_tmp/fsrd_composition_binding_gap_SOURCE_audit_20261002/FINDINGS.md),
  SHA256 `5421f32328514de6fd37d080ea9dc5b731a163a86659410455e2f956e450f5d9`:
  no slot, CB-layout, stride, coordinate or score-ROI mismatch was found.
  The paired CPU/actual-CSO gain gap remains unexplained. Runtime f16 UNORM
  load words were not observed; this is an unknown, not an identified fault.
  Matching the surrogate to the already failing actual graph would improve
  diagnostics without establishing a repair, so no new shader probe was selected.
- [Native signal-contract audit](../tools_tmp/fsrd_full1_native_signal_contract_SOURCE_frontier_20261002/FINDINGS.md),
  SHA256 `e6cd3adc5b49e78b64340776d72cd05b315d11b5e2d0d65a7f4db8e019af86a4`:
  the public sample supports external demod/remod; no omitted variance,
  radiance encoding or inverse output transform was identified. Filtering
  inverse carrier structure can create material contrast after remodulation,
  but this illustrative mechanism does not identify the provider's cause or
  explain every constant-signal island observation.

Authoritative physical per-lobe radiance provenance, including applied
BRDF/PDF/material factors and correspondence, is still absent. Declared noisy
lobe tag enums do not establish title-provided resources. This information
could diagnose a semantic mismatch; no actual mismatch is established now.
Current-alpha game output is also unavailable, and the user cannot open the
game. No new capture request was made. Neither unknown is repaired by another
bank over the same mixed-Color allocation.

Continuity: no next physical test or accepted repair was selected. This is the
first explicit no-progress audit at this source frontier; the goal stays ACTIVE,
with no blocked/paused/complete status change. Completion would require actual
evidence that the examples are repaired with full1 detail preserved. These
SOURCE reads add zero numeric/native/GPU/compiler work; ledger remains
SDK495/RR494/query1/helpers1821/API26970/queued=completed26962/failed8.


### 2026-10-02 recorded-slot runtime repair: paired RX9070 evidence

This supersedes the SOURCE-frontier no-progress count1: meaningful
runtime repair progress resets it to0. The full1 stain/wave goal stays ACTIVE.

Original V5 compiled (baa589, clPID5700/rc0).
RX run4aa492/PID3840 CLOSED ordinarily with rc1, GPUcompleted1 and device
S_OK. Expected101..107 read back as [0,0,0,0,105,106,107]. Six debug
STATIC-descriptor mutation messages identify three SRV and three UAV cases.
The original frozen GPU_result remains INCONCLUSIVE with unsafe/incomplete
clean-readback status; it must not be relabeled a safe baseline.
[Root baseline receipt](../tools_tmp/fsrd_current_alpha_recorded_slot_regression_20261002/v5/ROOT_actual_baseline_physical_receipt.json)
SHA25671946ca7 pins the completed overwrite observation and preserved result.

Fixed V3 compiled once (57e706, clPID18708/rc0). RX8274a6/PID31140
CLOSED rc0/GPUcompleted1 with all seven readbacks101..107 and debug0.
The real generic lease adapter retained7 dispatches, recorded1 PRE submission
intent and1 successful Reset detach. Actual detour installation tested=0.
[Root fixed receipt](../tools_tmp/fsrd_current_alpha_recorded_slot_regression_20261002/fixed_SOURCE/v3/ROOT_actual_fixed_physical_receipt.json)
SHA256afe2ff68 pins the PASS. GPU_result/stdout/guards are under
`v5/baseline_once/run_rx9070` and `fixed_SOURCE/v3/fixed_once/run_rx9070`
there. Both fixtures retained caller owners through completion; dropped
references were not tested.

SOURCE peer954ac4a9 reviewed ComputeState
b177adf6, RecordedComputeLease66ddf775 and ResTrack3d8e48db. The paired
fixture physically repairs the old ring/STATIC-descriptor corruption through
the generic API. Full1, image math and production HLSL are unchanged.
Real detour installation/dispatch, provider-context generation retirement,
shared-helper retirement, dropped-reference lifetime and resubmission are
not physically proven by this one-submit adapter test. No game stain cause
or quality acceptance follows.

Full-project Release DLL build is still SOURCE preparation at this boundary;
no deployment or commit is claimed. Separate integration counts:
2 cmd setup failures,3 actual cl attempts(1fail/2PASS),2 RX slot runs
(baseline fault/fixed PASS). Historical SDK495/RR494/query1/helpers1821,
RR API26970/queued=completed26962/failed8 remains unchanged. Do not rerun
these paired fixtures for activity. This append performs no compile/GPU,
numerical test or production edit.


Subsequent status: root started full Release MSBuild623d4f/session93149;
the build is RUNNING, awaiting normal closure. The SOURCE-only build status
above records the earlier boundary. No DLL identity, completed build,
deployment or game-fix claim is established yet. This status append performs
no build or runtime work.

### 2026-10-02 DLL integration failure, corrections and SR continuity progress

First full Release build623d4f/session93149 CLOSED0472cd at03:56:04 UTC,
rc1 after3m50s:74warnings/10errors. Four private-access errors plus obsolete
RRTrace CB/heap references and six cascaded errors prevented DLL acceptance.
[First build closure](../tools_tmp/fsrd_recorded_dispatch_release_build_20261002/runtime_once/ROOT_process_closure.json)
pins the failed process; logs/binlog remain preserved. Prior SOURCE
PASS954ac4a9 did not establish complete integration compilation.

Corrected seven-file SOURCE peer d2c2194f passes the bounded integration
review: ResTrack cpp10b8e52a/header8ac40bf2 and Tracea1260e74 repair access
and remove obsolete pre-retains. Actual ComputeStateb177adf6 and lease66ddf775
remain identical; no paired GPU repeat. Exact generic leases retain the
removed CB/heap lifetime duties. Trace Dispatch is void: tracking failure
throws before capture Copy, rather than returning a bool.
[Correction review](../tools_tmp/fsrd_recorded_dispatch_lifetime_independent_SOURCE_20261002/integration_correction_v2/completion_manifest.json).

Distinct SR-gap-only patch55f5534a is APPLIED: Feature header4924249b,
cppb2fbc137; production peer90e4474d. Pending reset starts true; the local
EvaluateInternal guard arms it whenever SR has not succeeded. Pending/title
reset are ORed immediately before SR and cleared only on successful SR.
Missing Color or composition failure can otherwise lose a title Reset pulse
before the next same-object titleReset0 call. Actual game occurrence is
unknown. RR invalidation does not arm it: continuous DenoiserBypass rawColor
SR must not reset every frame.

Source-extracted V2 probe2708dcf0/peerbf632f88 actually CLOSEDa48647,
compile0/probe0, PASS118checks, stderr0. Field/guard/dispatch match the applied
source; SDK calls and early exits are mocked. Renderer/GPU history, outer
postprocess and caller discard remain untested.
[Actual CPU probe](../tools_tmp/fsrd_SR_reset_latch_SOURCE_20261002/implementation_plan/runtime_direct_once/ROOT_actual_result.json)
and adjacent compile/probe logs retain evidence. Root used direct cl with
ENV8c28; unused cmd/vcvars recipe was excluded and never executed.

Build2 actual91422b/session97827 is RUNNING, pending normal closure;
owner91356803/peer410f1a90. Fresh runtime_attempt2 output/log/tmp may reuse
the preserved failed objects. No DLL PASS, deployment, commit or game-quality
acceptance yet. Historical SDK495/RR494/query1/helpers1821/API26970,
queued=completed26962/failed8 stays unchanged. Separate integration now adds
one CPU compile/probe and two full DLL attempts(first failed, second pending).
Full1/image math are unchanged; goal ACTIVE, no-progress counter0.
This memory append performs no production edit, numerical/runtime test or
compile. Await root build closure; do not rerun the paired slot fixture.


### 2026-10-02 Release build2 CLOSED PASS; shared-helper frontier stays SOURCE

Build2 actual91422b/session97827 CLOSED9dc1f2 at04:13:33 UTC, rc0 after
1m16s, source_unchanged=true. Actual logs contain26warnings/0errors; no
matched-baseline or preexisting-warning attribution was measured.
[Root artifact receipt](../tools_tmp/fsrd_recorded_dispatch_release_build_20261002/runtime_attempt2/ROOT_build_artifact_receipt.json)
SHA2560aef6c89 binds source91356803 and peer410f1a90. Validated isolated
DLL is `runtime_attempt2/out/OptiScaler.dll`,26,971,648B,
SHA25611ad9f47aa96f7f45beae25ae78605762f172345b458ab7a8f25ddb8e0a9d20c.
Historical embedded version labels remain from headers; identify this build
by the source receipt and artifact SHA. This compile/link PASS supersedes
the pending status above. No DLL load, deployment or game acceptance is
claimed; real detour installation and prior lifetime exclusions remain.

Distinct [shared-helper SOURCE finding](../tools_tmp/fsrd_shared_shader_pending_slots_SOURCE_20261002/FINDINGS.md)
a45b919d/completion2ad5ab34 identifies RCAS/output scaling reachable after RR:
two heaps share one CB, so a second pending recording can overwrite constants
and a third can overwrite earlier views. Bias is not dispatched by the
current FSRD converter. This is separate from the repaired ComputeState.
Actual game activation, pending-work timing and quality relevance remain
unknown. No helper port or new fixture is selected by this note.

Separate integration now has two closed DLL attempts(first FAIL, second PASS)
and one passed CPU SR probe; historical SDK ledger is unchanged. Full1/math
stay unchanged; goal ACTIVE, no-progress counter0. Root plans to preserve
validated code locally; no PR/push is claimed here. This append performs no
production edit, numeric/runtime work, build or DLL inspection/load.


### 2026-10-02 current detail status and selected shared-helper validation

User asked whether specular-detail tests passed while verifying a synthetic
stain repair. Answer: no joint end-to-end full1 stain-fix/detail PASS exists.
Current bounded passes are converter delayed7 RX correctness, mocked SR
continuity118checks and DLL compile/link. These establish their named scopes,
not a quality/detail acceptance. Earlier CLEAN/detail rejection evidence
remains intact. Static-camera demod0 blur remains the user's observation;
no demodulation reduction or new game/capture request follows.

The complete71,930B doc/adc7e1f5 was locally committed as a9194f8b by root;
the earlier open request returned queued, not confirmed visible. Production
is not committed by this append.

Selected shared-helper production V2
[source receipt](../tools_tmp/fsrd_shared_shader_lease_port_20261002/source_receipt_V2.json)
152d9558 binds12files, pending final independent SOURCE gate at this boundary.
Exact original baseline snapshot66462d27 remains preserved. First actual
standalone OS compile3d9746 CLOSED with clPID9472/rc2: diagnostic pch shim
omitted FrameDescriptorHeap. No GPU ran and no output/detail predicate was
measured.
[Failed driver](../tools_tmp/fsrd_shared_shader_recorded_slots_regression_20261002/baseline_once/compile/driver_result.json)
and adjacent logs/guard remain immutable in baseline_once. Author/peer are
preparing a fresh V2 shim correction; this is harness compilation failure,
not evidence against or acceptance of the helper lifetime repair.

Root alone executes future gated validation. Historical SDK ledger is
unchanged; shared-helper standalone compile is a separate integration
attempt. Goal ACTIVE/full1 unchanged/counter0; no deployment or game fix.
This doc/progress append performs no production edit, numeric/runtime work,
compiler invocation or payload read.


### 2026-10-02 recovered RGB89 PASS history and actual shared-OS repair

The user's recalled numbers are authenticated as RGB89 colored trueSPEC
32PASS/13FAIL out of45, not a32-to13 conversion. WholeC89/89PASS and gray
SPEC0/44 remain the measured record. These earlier passes are valid:
11 fully active intended-model anchors carry SPEC gain about.9992..1.0006
and phase<.0011 through the declared full1 CPU transport. Recent "no joint
end-to-end PASS" statements concern general/native/game acceptance; they do
not erase this conditional synthetic success.
[Closed causal diagnosis](../tools_tmp/fsrd_RGB89_closed_causal_diagnosis_SOURCE_20261002/CAUSAL_DIAGNOSIS.md)
retains the positive result and limitations. Synthetic C included separated
SPEC/DIFF plus colored B; all-active COLORED_DIFF_LIGHT gain.825101 fails,
and same-observation IN_PLANE gain.986174 passes amplitude but phase.097434
fails. Whole-color agreement cannot select the correct physical lobe.
Next actual-water applicability had no arm meeting all cap<=8 conditions,
with SPEC medians121–128. Later native CLEAN split gain1.241055727 and
unitpair1.208545804 exceed1.05 and reject those distinct candidates.
No successful RGB89 row was rerun or reclassified by these failures.

Shared OS V2 baseline compile3a09cf/cl19116 PASS then RX95eb52/PID9524
ordinarily CLOSEDrc1/GPUcompleted:6of7 delayed outputs mismatch serial
golden; changed-word counts[254,256,256,256,256,128,0]. Exactly6STATIC
diagnostics/other0 retain the debug-invalid baseline, not a safe/clean PASS.
[Baseline receipt](../tools_tmp/fsrd_shared_shader_recorded_slots_regression_20261002/v2/ROOT_actual_baseline_physical_receipt.json)
44f294ba binds immutable evidence. Fixed SOURCE07a2d2cb/peer26e52fc3,
compile2623ec/cl29796 PASS then RX6a457b/PID18344 ordinarily CLOSEDrc0,
GPUcompleted, all7 changed-word counts0/debug0/stderr0.
[Fixed receipt](../tools_tmp/fsrd_shared_shader_recorded_slots_regression_20261002/fixed_SOURCE/v2/ROOT_actual_fixed_physical_receipt.json)
b302395b records real generic14retains,8PRE/POST pairs,8Reset detaches and
delayed Reset before gate release. Caller resources and local recording/
submission tokens were held; intermediate was borrowed, timer inert.
Registry-only reclamation, real detours, RCAS SPEC detail and game behavior
are not physically proven by this OS test. Do not repeat either fixture.

Shared production V2 source152d9558/peerb230fc78 binds12files, not yet
committed at this boundary. Full DLL3 actual2234f6/session74428
CLOSED1f2a96/MSBuild27464/rc0 at05:03:37 UTC after4m15.84s,
source unchanged,76warnings/0errors. Warning preexistence was not measured.
[Root artifact receipt](../tools_tmp/fsrd_recorded_dispatch_release_build_20261002/runtime_attempt3/ROOT_build_artifact_receipt.json)
b84e6acb binds DLL26,984,448B,
SHA2561db7f23413ddb10ce2674220fc0bd2ffc615cd61a154283a5fe01e6925eec7fd.
No load/deployment/game acceptance follows. Next RCAS DA/DASDA owned-
intermediate/real-timer/sharpness/detail proposal94f60052 is SOURCE only;
execution requires root's separate peer-gated selection.

Shared integration:3standalone cl attempts(1FAIL/2PASS),2RX runs and1full
DLL build. SDK quality calls0; historical SDK ledger unchanged. Full1/math
unchanged, static demod0 blur observation retained, goal ACTIVE/counter0.
This memory update performs no code edit, commit, numeric/runtime/build work.


### 2026-10-02 four-point mapping, signed Skip and RCAS CLOSED checkpoint

The user's four-point plan maps to RAW3/RAW7, not RGB89. It was implemented
and CLOSED in the CPU packet: raw material roles separated from stored
normalization factors; RAW7 has independent local SPEC/DIFF x/y light fields;
explicit raw*den/Qc^2*I/full1 transport plus signed residual H; exact inactive
fallback and whole-field metrics including fallback. Both arms pass color
44/44; trueSPEC passes25/44 RAW3 and24/44 RAW7. Shared-light gains.49774/
.58885 and RAW7 moving-frame8 phase failure reject them as sufficient.
The earlier32coloredPASS/13FAIL and WholeC89PASS belong to separate RGB89.
Neither the four-point estimator nor signed H was ported into current alpha.
Current alpha retains stored-albedo ratio allocation and optional shared-
slope/intercept AdditiveLightSplit; full1 strengths stay1. Recent production
changes repair lifetimes/SR reset, not the illumination allocation law.

Clarify earlier signed-writer wording: Skip is already
R16G16B16A16_FLOAT (FSRDPreprocessor:60), and Reconstruct adds Skip before
final sanitation (OutputComp:137). Ordinary shares/floor/loss construction
is nonnegative; InputConv:1212 sanitizes negative values. Storage capability
alone is not a novel repair. FloorExcess can require an upstream negative
closure, but FloorOFF Flags54 water excludes that term. Earlier signed-H
CPU evidence already retained117negative words and exposed allocation
failure before half transport/H. Do not rerun a signed-only bank.

RCAS actual compileacd115/cl11896 CLOSEDrc0; EXE348,160B,
SHA25640a73a1d7ff5800ce08877d52a227d5c65e1bf993ae515c2dfb7fdaca351f857.
RXcff18b/PID11300 ordinarily CLOSEDrc2/stderr0, disposition
INCONCLUSIVE_NO_RETRY after six serial goldens, at the unobservable-motion
prerequisite before queued/replay. EXE identity after closure matches compile.
[Root physical receipt](../tools_tmp/fsrd_RCAS_DA_DASDA_detail_lifetime_SOURCE_20261002/root_SOURCE/ROOT_actual_INCONCLUSIVE_physical_receipt.json)
5f05bd54 preserves immutable results. Authorfb7b8297/independent60538360
confirm active motion wiring and no adapter defect: the selected line-center
limiter is invariant under adaptive sharpness. No retuned rerun, owned-
lifetime/timer/reclamation, queued/replay or SPEC-detail PASS follows.

Root locally committed the12 shared production files as fa319a82,
"Preserve RR helper resources across pending GPU dispatches"
(307insertions/48deletions), retaining source152d9558 after OS7exact and DLL
compile/link PASS. This is bounded SOURCE/CB-heap OS GPU/build validation;
real detours, RCAS owned timers/reclamation and game quality remain unproved.
No HLSL/math/demod reduction, DLL load or deployment is claimed.

Separate RCAS integration adds1compilePASS/1RXINCONCLUSIVE, SDK0; historical
SDK ledger unchanged. Next quality-information frontier is SOURCE only,
with no old-bank replay selected. Full1 goal ACTIVE/counter0; static demod0
blur observation retained. This append edits only memory, makes no commit
and invokes no source-code test, numerical/runtime/GPU/build work.

### 2026-10-02 user refocus: full1 image quality before further diagnostics

The user redirected the active goal to stain removal while preserving true
material and illumination detail at demod/remod strength1. New capture is
not a prerequisite. No new native test or agent was started before the
short refocus summary. Pending additive-DC-gauge certificate/assembly work
was interrupted and retained as unexecuted SOURCE preparation. That
diagnostic is deprioritized: its result did not yet select an image repair.

**Quality algorithms.** RGB89 retains WholeC89/89 and colored SPEC32/45
PASS, alongside13 colored failures and44 gray fallback failures. Its
intended-model anchors preserve material and shared/moving scalar-light
detail. Colored diffuse light and identical-observation/different-SPEC
metamers prevent general physical-allocation acceptance. These later
failures do not erase the conditional successes. RAW3/RAW7 preserve whole
Color44/44 each but fail sufficient true-SPEC coverage25/44 and24/44.
Neither proposal has been accepted as an alpha image fix.

**Runtime repairs.** Recorded converter/shared-helper resource ownership
and SR reset-gap changes address concrete execution hazards. The measured
OS queued-dispatch repair and DLL builds validate those bounded claims.
They do not demonstrate reduced stains, improved sharpness, corrected
physical allocation or settled game history.

**Test infrastructure.** Source reviews, serializers, guards and saved-output
checks qualify measurements. Their integrity PASS is separate from image
quality. RCAS motion observability remains INCONCLUSIVE, not a sharpening
quality rejection or success. No newly reduced image defect is claimed in
this refocus. The user's remembered static-camera demod0 blur still stands;
reducing modulation remains excluded as a solution.

#### Exact counterparts of the two original questions

1. **Variable SPEC SDK-guide intervention with original full1 caller factors
   fixed:** the12-context guide-RGB-only packet is not this counterpart.
   Its SPEC guide is spatially constant; only DIFF RGB is flattened to the
   lower/upper mean. Signals and caller factors were fixed, but the requested
   variable SPEC field was not intervened on. The earlier112-case real-RR
   study has variable SPEC guide-only controls, but they are separate-lobe
   direct-output experiments rather than the matched current full1 caller
   graph. R8/F32, gamma/sqrt and coupled caller-factor variants also cannot
   substitute for the one-field intervention. No exact completed counterpart
   is established by these records. Missing coverage alone does not select
   a new run.
2. **Same-joint-flags four radiance arms:** the16-context cross-input packet
   does supply (U,U),(U,0),(0,U),(0,0) for both N/L carriers and repeats.
   Root read the original input5/6 bytes: RGB is exactly identical for each
   carrier; differing hit/validity alpha is preserved within every arm.
   Every job retains DIFF2/SPEC32, both descriptors, other five inputs,
   original guides and applied controls. The independent CLOSED review
   authenticates the actual native runs and all pair/repeat comparisons.
   This is independent evidence from the later joint-versus-split experiment.
   Its stored metrics are unsigned pairwise departures, not a computed
   four-term signed interaction J(U,U)-J(U,0)-J(0,U)+J(0,0), composed-image
   quality, or a proprietary-cause proof. Same-arm variation remains visible;
   do not launch the native four-arm experiment again to fill a POST label.

Sources: guide packet [review](../tools_tmp/fsrd_SDK_guide_RGB_only_native_postrun_review_20261001/review.json),
four-arm [compact evidence](../tools_tmp/fsrd_joint_lobe_cross_input_native_postrun_review_20261001/compact.md)
and [analysis source](../tools_tmp/fsrd_joint_lobe_cross_input_native_preparation_20261001/analyze_raw_cpu.py),
plus [historical separate-lobe study](fsrd_real_rr_albedo_experiment.md).

#### One selected quality hypothesis and its application decision

Hypothesis: spatial variation of the SPEC SDK guide can introduce an
undesired material-shaped illumination response even while full1 caller
division/multiplication remains correct. A separate constant SPEC guide
within a homogeneous diagnostic patch may reduce that response without
removing the original material carrier from caller remodulation.

Evidence is conditional: native guide-shaped departures exist, the DIFF-only
guide intervention affected both lobes, and current clean native response
fails detail gain after a good direct roundtrip. RGB89's intended anchors
show that full1 detail is transportable in their declared CPU model. None
identifies variable SPEC guidance as the actual game-stain cause.

Smallest decision experiment: one known-truth static fixture with genuinely
varying SPEC material, a separate illumination-detail carrier and a fixed
noise-control region. Use an intended shared-light allocation so wrong-lobe
allocation is not introduced as an additional explanation. Reuse existing
typed/native/composition tools. Compare original SDK guide versus one
predeclared constant SPEC RGB guide in the same R8 format; preserve guide
alpha, DIFF guide, both converted signal RGB/A, original caller Qc, Skip,
geometry, roughness, controls and strengths1. The replacement SDK resource
must not overwrite/alias the caller factor used for composition. Include
two fresh repetitions per arm because earlier cohorts varied. Score actual
composed outputs against known material, illumination and whole-color truth,
plus noise retention, across fixed full/startup/mature windows and the
entire field. Do not judge only changed native RGB or selected good pixels.
The proposed new input/metric packet is not yet generated or executed.

Positive decision: both candidate repetitions must reduce the structured
image error while preserving material and illumination detail under the
existing gain[.95,1.05]/phase<=.05 gates and not worsening noise or whole
Color. That selects a bounded experimental SDK-guide/caller-factor
separation path for implementation, rather than another attribution audit.
It accepts only this tested patch/model; actual game quality stays open.
Negative decision: if detail/noise/whole-color fails, retire this constant-
SPEC-guide candidate at the fixed operating point without a mean/dose sweep.
If repeat variation prevents distinguishing the change, retain INCONCLUSIVE
and make no production quality change. Mere output sensitivity is not PASS.

#### Appendix: scope of CLOSED/REJECT statements used in this refocus

- Single-slope additive residual: four independent-S/D static/noise helper
  observations reject that candidate's derived-SPEC and residual stability
  claims; they do not reject every additive-light or residual architecture.
- Rank-two NNLS allocation: four observed-only predictions reject that
  allocation's declared SPEC carrier claim, despite whole-color closure.
- Floor-free volume/history proposal:100 CPU cases/78 failed checks reject
  that filter's grain/detail/uniform-light treatment on its bank, not all
  volume-aware methods. Identical-observation semantics remain ambiguous.
- RAW3/RAW7:44-case paired CPU bank rejects those affine light-field models
  as sufficient full-detail solutions. Their whole-color passes survive.
- RGB89:89 CPU predictions reject general acceptance of its scalar-light/
  patch-B physical allocation;32 colored SPEC passes and89 color passes
  survive. Gray inactive fallback does not test an active gray replacement.
- Old-water RGB cap test:3 captures x2 typed material arms show no receivers
  meeting that law's all-channel cap<=8. It neither measures current-alpha
  fallback coverage nor rejects every RGB method.
- SDK-guide-RGB12: CLOSED integrity/descriptive DIFF-guide result; it does
  not close variable SPEC guide/caller-full1 or SPEC sharpness acceptance.
- Joint four-arm16: CLOSED raw native contrasts/repeats on S-constant
  constructed carriers; no composed-image or true SPEC sharpness acceptance.
- Current CLEAN joint-versus-split: six native contexts and actual-CSO
  frame63 failure reject that split-context candidate's required all-frame
  gain claim. This is not the four-arm radiance experiment or a rejection
  of every independently observed-lobe integration.
- CLEAN unit-pair/coupled precision/format controls: their specific encoded
  paths failed or did not provide an accepted repair. They do not close the
  fixed-signal/fixed-caller variable-SPEC-guide intervention.
- Water hit-alpha32: original versus constant1 under reset/continue closes
  those descriptive contrasts only. Reused captured motion limits history
  attribution; it does not explain the user's settled static-camera blur.
- RCAS DA/DASDA fixture: CLOSED INCONCLUSIVE at an unobservable motion
  predicate before queued/replay. No RCAS image or ownership quality claim.
- Converter/shared-helper/SR integration: bounded source, CPU, OS-GPU and
  build PASS; no measured stain/detail improvement follows.
- Additive-DC-gauge: unexecuted SOURCE plan only, interrupted/deprioritized;
  neither a CLOSED numerical result nor a rejected quality algorithm.

Refocus provenance appendix: root actual tool b74b39 performed only an
existing four-file RGB byte-identity check, not model/metric/native replay.
The existing joint raw analyzer records pairwise RMS, not four-term signed
interaction. Existing pinned receipts retain their hashes/PIDs/counters;
historical SDK/helper totals do not increase during this refocus. This
append preserves the prior document prefix and makes no image-code change.

