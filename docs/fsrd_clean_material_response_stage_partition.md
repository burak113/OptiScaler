# Clean material response: measured stage partition — 2026-09-30 / 2026-10-01

The stain/wave goal remains unresolved. This record isolates a gain and DC
departure in one constructed weak-material fixture; it does not establish a
game fix, an oracle response, or a private SDK defect. All quality acceptance
flags remain false. The fixture is a static 128 × 80 Nyquist material signal,
with authenticated source data, controls and actual converter/native/composition
payloads. Its clean reference is the constructed radiance signal, not an SDK
clean response. Genuine clean SDK calls were added separately.

## Direct conversion/composition control

The actual converter's clean diffuse and specular buffers were fed directly
into the original composition graph, without native RR. Two fresh helper
observations, R0 and R1, produced bit-identical results in all three output
buffers. Their RGB equals the actual encoded raw input `q` bit for bit:
RMSE, maximum error, DC and coefficient departure from `q` are zero; gain is
one. Relative to unquantized constructed truth, gain is 1.0376001596, solely
the measured raw-input quantization departure in this control.

This is two observations of one static graph, not 64 measured roundtrip
frames. Comparisons to a 64-frame SDK trace use the static R0 reference only
after all three R0/R1 buffers match. See the
[roundtrip review](evidence/fsrd_clean_response_stage_partition/fsrd_weak_material_clean_roundtrip_postrun_review_20260930/compact.json).

An actual-CSO control then changed only the diffuse input alpha from FP16
65504 to positive zero. RGB, the other ten SRVs and the 96-byte composition
constant buffer were unchanged. RZ0, RZ1, R0 and R1 match bit for bit in all
three buffers across all six pairs. Thus this alpha field does not explain
the RGB departure for this static graph. Auxiliary output equality does not
prove writes where history writing is disabled. This result is narrower than
a general alpha-invariance or SDK correctness claim. See the
[diffuse-alpha control](evidence/fsrd_clean_response_stage_partition/fsrd_clean_roundtrip_diffuse_alpha_zero_postrun_review_20260930/compact.json).

## Genuine clean response

The measured clean converter outputs supplied native input 5 (diffuse,
converter output 1) and input 6 (specular, converter output 0). The other
five full RGBA SDK inputs, ray-hit alpha, camera and 64 × 184-byte controls
were authenticated against the original fixture. Two fresh 64-frame SDK
contexts, C0 and C1, have bit-identical raw lobe outputs. They are genuine
`T(clean)` controls; the earlier pilot and null contexts were not.

Their original composition graph was measured after each observed-control
replay matched all three original outputs exactly. Mature luma gain is
1.2881504893 against raw constructed truth and 1.2414694726 against `q`.
All 64 frames fail the absolute detail-gain gate against both references;
phase passes do not repair this gain failure. Mature temporal STD is
1.1508861e-6, about 0.0160553 of the original observed baseline. Low noise
therefore does not constitute detail acceptance. Signed DC bias is negative
in each RGB channel. See the
[clean-response composition review](evidence/fsrd_clean_response_stage_partition/fsrd_weak_material_clean_composition_postrun_review_20260930/compact.json).

The direct `R=q` control and genuine clean-response departure partition the
observed effect across native RR plus its downstream composed graph under
these fixed inputs and settings. They do not isolate an intrinsic SDK RGB
mechanism, prove all production paths equivalent, or identify the cause of
the game's stains. The actual-CSO alpha control closes one specific static
composition confound.

## Specular hit-alpha contrast and three actual composed traces

Four fresh native contexts used specular input alpha 0 / 10 / 10 / 0, each
for 64 frames. Only input 6 alpha changed; all other payload fields and
applied controls match. Positive 10 is a view-depth proxy, not an authenticated
secondary-ray distance. The two alpha-10 raw traces are bit-identical. The
two alpha-zero traces first differ at source frame 39: diffuse RGB RMS is
6.3709442e-5, specular RMS is 9.0399070e-5, and maximum difference is
0.00048828125. Between-dose differences have comparable scale. Within-dose
variation prevents attributing these differences to alpha alone. Native
output alpha being zero is an observation, not proof of a write/preservation
mechanism. See the
[raw native review](evidence/fsrd_clean_response_stage_partition/fsrd_clean_specular_hit_alpha_contrast_postrun_review_20260930/compact.json).

Exactly three traces were then composed: A0r0, A10r0 and A0r1, totaling
192 fresh helpers and 576 retained outputs. A10r1 was omitted only because
its full 64-frame raw RGBA lobes equal A10r0; it is not a fourth measured
composition trace. No new observed replay or SDK call occurred in this step.

- Mature gain against raw truth is 1.28803319, 1.28815049 and 1.28808583;
  against `q` it is 1.24135633, 1.24146947 and 1.24140789.
- All three fail absolute gain in all 64 frames and in the full, mature,
  startup and activation windows. Phase passes are reported separately.
- Mature STD / old observed baseline is 0.01895233, 0.01605531 and
  0.01688034. All three retain negative RGB DC bias.
- Pairwise color RGB RMS is about 1.51e-5 to 1.59e-5. Output alpha and the
  other two buffers match. A10r0 matches both prior C0/C1 composition traces
  bit for bit in all three buffers.

These are separately measured process/history cohorts. They neither establish
an alpha cause nor correct the gain. The
[final independent review](evidence/fsrd_clean_response_stage_partition/fsrd_clean_specular_hit_alpha_composition_postrun_review_20260930/compact.json)
reproduces all nine scored values × two references × four windows, signed
rank-one coefficients/DC, actual STD, three trace pairs and six prior-trace
comparisons. FP32 scorer means and independent FP64 interior DC reductions
are labeled separately.

## Settings and source boundaries

The six native override values `[0.1, 0.5, 0.5, 40000, 40, 0.5]` map, in
public-key order `[6, 1, 2, 3, 4, 5]`, to disocclusion threshold,
cross-bilateral normal strength, stability bias, maximum radiance, radiance
clip standard-deviation K and Gaussian-kernel relaxation. They exactly match
this fork's defaults with `UseAmdDefaults=false` and no INI/menu overrides.
At this clean-fixture audit's freeze boundary, numeric AMD defaults had not
been measured by its query followup.
Stability bias is a temporal stability/responsiveness control; clip K and
maximum radiance are not documented multiplicative-gain controls. Matching
six scalar values does not equate the fixture's six one-time scalar Configure
calls, one per key, to the
production query/cache/per-frame change and failure-retry path. See the
[bounded tuning audit](evidence/fsrd_clean_response_stage_partition/fsrd_clean_fixture_tuning_equivalence_audit_20260930/audit.json).
The global-debug Configure call is separate from these scalar calls.

The composition graph fixes flags 8, detail strength 0, history valid 0 and
history writing 0. Historical EXE/CSO bytes are authenticated; retained source
references describe their contracts without claiming a new source-to-binary
compile proof. Query design/source-compile preparation contributed zero
query contexts and no measured values at the original archive freeze.
The subsequent [public-default query followup](fsrd_public_default_scalar_query_followup.md)
completed one query-only context and six successful queries: key order
`[6, 1, 2, 3, 4, 5]` returned approximately
`[0.01, 1, 1, 65504, 50, 0]`, with exact float32 bits pinned separately.
No settings were applied and no image response was measured. A future
default-vector RR test remains unmeasured.

The earlier [failure-reset policy](fsrd_failure_reset_policy.md), commit
`3b5b0b4b`, is separate: two checked failure returns invalidate history.
Its Release/x64 build passed with zero errors and 76 warnings. That build
does not establish runtime recovery or visual acceptance and is not rerun
or counted by this archive.

## Evidence and accounting

The compact archive preserves byte-exact protocols, source references,
independent reviews, source attempt errata and representative actual helper
logs/guards. The composition V1 analyzer's prior-manifest lookup key was
corrected in a one-line V2 metadata supplement before any GPU execution or
score analysis; V1 is retained. Reviewer preparation mistakes and their
corrections are retained separately, without changing producer results or
thresholds. Historical pending-result drafts are excluded from publication.

At this experiment boundary the cumulative native totals are 414 contexts,
22,074 successful API RR recordings and 22,066 queued/completed recordings;
eight recorded-only discards and four no-API omissions are separate. This
clean-stage pipeline has 516 helper calls and 516 explicit shader Dispatch
calls. Opaque SDK internal shader counts are unknown. Future planned probes
are not counted. This documentation/archive operation launches nothing.
The subsequent query-only context raises total completed SDK contexts to
415 (414 RR-workload contexts plus one query-only context); RR counts and
the 516 clean-stage helper Dispatch calls are unchanged.

[Archive manifest](evidence/fsrd_clean_response_stage_partition/manifest.json)
records every copied source/target size and SHA256, verifies originals again
after copying, and excludes its own entry. Large raw buffers, NPZ sequences,
binaries, full metric dictionaries and expanded manifests remain pinned at
their immutable original paths in
[external references](evidence/fsrd_clean_response_stage_partition/external_references.json).
They are required for full reproduction; the compact archive alone is not
a portable complete replay package. Original folder names and freeze-time
dates remain unchanged. No production/runtime/settings change, new model,
quality acceptance, or resolved game objective is claimed.
The original archive seal retains the pre-query document identity. Its
byte-exact [historical document snapshot](evidence/fsrd_public_default_scalar_query_followup/historical_stage_document_before_query_followup.md)
is preserved in the separate followup archive; prior archive bytes were not
changed by this clarification.
