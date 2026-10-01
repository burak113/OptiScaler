# Fork defaults and Configure-flow controls — 2026-10-01

The stain/wave objective remains unresolved. The completed six-value contrast
changes the measured response of one constructed clean fixture, but the queried
provider tuple does not remove its contrast departure and produces a larger dark
bias and temporal variation. A second raw-lobe contrast does not isolate an effect
of making six scalar Configure calls versus making none. Neither result is a game
fix, a private SDK defect, an individual-key attribution or quality acceptance.

## Measured values and matched vector contrast

The earlier [public-default query](fsrd_public_default_scalar_query_followup.md)
completed one fresh query-only context and six successful public scalar Queries.
In key order `[6,1,2,3,4,5]`, the observed float32 tuple is approximately
`[0.01,1,1,65504,50,0]`: disocclusion threshold, cross-bilateral normal strength,
stability bias, maximum radiance, radiance clip standard-deviation K and
Gaussian-kernel relaxation. Its exact bits and 24-byte result remain pinned.
This is the measured tuple for the authenticated provider and created context,
not an assumption about every provider or production context. The fork's shipping
vector with `UseAmdDefaults=false` and no overrides is
`[0.1,0.5,0.5,40000,40,0.5]`; all six bit patterns differ.

Four fresh 64-frame contexts ran in fixed order Fork_r0, AMD_r0, AMD_r1, Fork_r1.
They share the signed provider, new common runner, seven actual clean inputs,
formats, static upload counts, camera, 64×184-byte controls and output policy.
Specular input hit-alpha remains zero. Only the six-float sidecar varies; each
context makes six count-one scalar Configure calls. The original hardcoded values
declaration was replaced by a finite, exact-24-byte sidecar read. Inverse one-hunk
substitution reproduced the original source SHA, and one isolated CPU compilation
produced the common EXE. The original parameter-pointer scope, resource lifecycle
and output-initialization limits remain unchanged; no private pointer-retention
mechanism is inferred. See the [source whitelist](evidence/fsrd_default_vector_and_configure_flow/native_preparation/source_whitelist.json).

The [independent native review](evidence/fsrd_default_vector_and_configure_flow/native_postreview/review.json)
confirms four created/destroyed/completed contexts and256 successful RR API,
queued Execute, Signal/event/wait, completed and readback stages. Fork repeats are
full64 RGBA exact. AMD repeats first differ at diffuse frame15 and specular17;
between-vector RGB differences occur on all64 frames. All native output alpha is
positive zero, without inferring a private write mechanism. Current Fork differs
slightly from historical A0 traces; changed source/EXE/process/time cohorts qualify
that comparison. Within-vector differences remain part of the evidence.

## Actual composed response

Three full traces were composed: Fork_r0, AMD_r0 and AMD_r1, totaling192 fresh
helpers,192 explicit helper shader Dispatch calls and576 retained buffers.
Fork_r1 was omitted only under the preregistered full64 diffuse-and-specular RGBA
byte-equality rule. Its composed result inherits exact-input equivalence with
Fork_r0; it is not a fourth measured GPU series. All four frozen windows—full0–63,
mature48–63, startup0–7 and activation8–15—use unchanged functions, thresholds and
references. The [independent composition review](evidence/fsrd_default_vector_and_configure_flow/composition_postreview/review.json)
reproduces the saved metrics and comparisons exactly.

Projected contrast gain is signed output relative to reference:
`g=(a·b)/(b·b)`, where `a` is output luma centered by its interior-ROI mean and
`b` is reference luma centered by its own mean. The ROI excludes five pixels at
each edge. Values above one mean amplified projected output contrast. This is
neither an inverse ratio nor an absolute-value transform; even the historical
`absolute_gain_*` summary names retain the signed gains. The frozen
[score source](evidence/fsrd_default_vector_and_configure_flow/metric_sources/score_source.py)
lines77–78 and [summary source](evidence/fsrd_default_vector_and_configure_flow/metric_sources/moments_source.py)
lines64–67 define these quantities.

- Fork mature projected gain is1.288150489 against raw constructed truth and
  1.241469473 against quantized encoded raw `q`. RGB bias is about−0.00083;
  temporal STD/old observed baseline is0.01605531.
- AMD_r0 gives1.218670897/1.174508005 against those same two references;
  AMD_r1 gives1.217763506/1.173633516. Their RGB biases are about−0.00665 and
  STD/old baseline is3.38591655/3.29807652.
- All three fail the frozen mature and full absolute-detail criterion against
  both references. Phase passing is separate and does not repair the gain failure.

The [compact material result](evidence/fsrd_default_vector_and_configure_flow/composition_postreview/material_result.json)
retains exact values for both repeats. These bias values are the frozen scorer's
error means; separately saved FP64 interior DC/beta reductions remain labeled.
No average across repeats or output-selected window is substituted. The smaller
AMD gain departure does not remove it, and dark bias/STD worsen this fixture.
The direct roundtrip `R=q` control remains two observations of one static graph,
not64 measured roundtrip frames. This128×80 Nyquist material carrier and constructed
clean reference do not establish a general physical-detail or SDK-oracle response.

## Six scalar calls versus no scalar calls

Four further fresh contexts used ExplicitAMD_r0, NoScalar_r0, NoScalar_r1,
ExplicitAMD_r1, with the exact same EXE and queried-AMD sidecar. Only the job's
tuning Boolean1/0 changes. The source `if(tuning)` encloses both sidecar reading
and the six scalar Configure calls: NoScalar does not read its sidecar or make
those calls. Its active internal settings remain unknown.

The [independent NoScalar postreview](evidence/fsrd_default_vector_and_configure_flow/no_scalar_postreview/review.json)
confirms four created/destroyed/completed contexts and256 successful source-qualified
RR API/queued/completed/readback stages. All64 applied controls match across arms,
with dispatch flags3 at frame0 and2 thereafter. Twelve scalar Configure calls
occur across the two explicit arms. All four contexts retain one global-debug
Configure and one informational provider-version Query per context. The four
version Queries return rc6, with zero successful version Queries; these are
separate from the earlier six successful default-scalar Queries. No new
public default-scalar Query occurs in either native contrast.

All six current pairs and16 historical pairs reproduce44 raw-lobe metric
dictionaries. All current full64 RGB/RGBA pairs are nonexact, with exact
positive-zero alpha. Explicit-repeat RGB RMS is0.000190534168 diffuse and
0.000186705953 specular; NoScalar-repeat RMS is0.000172881278/0.000189098331.
Between-policy RMS spans0.000158709669–0.000211684193, the same observed scale
as repeats. This cohort does not isolate a scalar-Configure policy effect or
prove equal internal settings. No current full64 lobe matches a historical one.
These runs have no new composition or quality score; previous AMD composition
cannot be inherited by these nonexact traces.

Production additionally queries key7, selects through its proxy/cache flow,
compares requested values per frame and restores the prior cached value on
Configure failure so the next frame can retry. Its Release create flags0 differ
from the standalone validation create flag2. These create flags are distinct
from dispatch flags3/2. Consequently this is not the complete fresh production
`UseAmdDefaults=true` path. The [source context](evidence/fsrd_default_vector_and_configure_flow/source_context_notes.json)
pins the exact production source and lines. The fork's numeric defaults are
inherited historical edits, not a fit to this fixture; the narrow introducing
commit review did not establish an isolated numeric rationale for stability.5
or Gaussian relaxation.5. No setting is selected or changed by this record.

## Evidence boundary

Each native contrast completed4 contexts/256 RR recordings. Together they add8
RR contexts and512 successful/queued recordings; the vector composition adds192
helpers. At the NoScalar boundary, cumulative totals are423 SDK contexts
(422 RR-workload contexts plus1 query-only),22586 successful RR API recordings
and22578 queued/completed recordings. Eight recorded-only discards and four
separate no-API omissions remain separate. Six successful default-scalar Queries
and708 clean-pipeline explicit helper Dispatch calls are distinct counters.
Opaque SDK-private shader Dispatch counts are unknown.

A subsequent separately reviewed frequency-converter control adds4 actual
singleton helper observations, bringing the helper counter to712 while SDK/RR
counts stay unchanged. N repeats match all8 historical outputs; L repeats are
all8 exact. No native response, composed quality or64-frame temporal series was
measured in that stage. Its separate postgate is pinned externally; future native
frequency work is unmeasured by this document.

The compact archive preserves exact protocols, source authorities, laws,
readiness and independent gates, results, actual native controls/logs/guards and
nine fixed representative composition jobs. CPU metadata/reviewer failures and
corrections remain separate from native failures or retries. Root tool receipts
are documentary observations, not fabricated raw child logs. Original pending
freeze/receipt statuses and their source SHAs remain historical; later passed
postreviews do not rewrite them. This publication performs no SDK/GPU/build/scorer
work, production change, game run or quality acceptance.

[Manifest](evidence/fsrd_default_vector_and_configure_flow/manifest.json) verifies
source-copy pairs and originals before/after copying and excludes itself.
[External references](evidence/fsrd_default_vector_and_configure_flow/external_references.json)
retain exact original paths, sizes and SHA256 for raw buffers, binaries, NPZ
sequences, full metrics and inherited closure manifests. Those originals are
required for full reproduction; this archive is not a portable complete replay
package. Earlier stage/query documents and sealed archives are unchanged.
