# Native SDK call-presence control — 2026-09-30

The stain/wave objective remains open. Eight matched native contexts isolate
whether sourceframe24 is successfully recorded by the SDK before its command
list is discarded. Both arms execute the same63 GPU sourceframes0..23 and
25..63. Their seven input buffers and queued184-byte controls match when
the same explicit-reset setting is used. Every submitted frame completes
its fence before the next recording. No production or game changes are
included in this diagnostic.

There are four conditions, each twice with balanced reverse ordering:
successful record24 then discard, no API call24, and each of those with
explicit RESET25. The no-API branch consumes source24 input/control data,
closes and discards its recording, restores nine external resource shadow
states and records a separate omission marker. It does not call the SDK,
write an applied API packet or append a successful-record index for24.
The record/discard branch really succeeds in api.Dispatch24 and retains
that index/packet. Both store zero output presence for24 and no raw output
for it. SDK source indices25..63 remain absolute.

Actual work is8 contexts/508 successful API RR recordings/504 queued RR,
four recorded-only SDK discards and four no-API omissions. An omission is
not an RR recording or a recorded-only discard. All contexts finish with
zero ordinary D3D12 errors/warnings and zero SDK errors. Two actual SDK
warnings are retained, one in each no-API arm without explicit RESET25:
`Frame index jump detected. Resetting...`. Explicit-reset and record/discard
arms have zero SDK warnings. The warning does not carry a frame number;
association with the post-gap dispatch follows from the registered sequence
and is an inference, not a directly timestamped internal SDK state readout.

All four within-condition repeats are RGB/RGBA bit-exact for both lobes.
All prefixes0..23 match. Without explicit reset, record/discard and no-API
outputs first differ at source25 and remain different through63. Their
39-frame diffuse RGB RMS difference is0.011663659528164845 and specular is
0.010781625112976822. The no-API tail exactly matches the earlier fresh25
and explicit RESET25 controls, despite its applied25 flags being2 rather
than3. Explicit RESET25 makes the record/discard tail match too. Thus this
fixture's SDK-call-presence intervention changes output alongside measured
gap-reset notification; matching application controls alone does not establish
matching effective SDK history. These are descriptive raw differences, not
error against truth or a noise/quality improvement.

The original eight-case executor required zero SDK warnings. It completed
the first two contexts, accepted metadata for the first, and stopped at the
second context's warning. Its original failed report, accepted count1,
raw outputs, console and preparation are unchanged. Actual work had already
been checkpointed before diagnostic acceptance:2 contexts/127 API/126
queued/one discard/one omission. A separate CPU inspection authenticates
the second context's controls and outputs while retaining that rejection.

After observing this warning, a separate V2 amendment permits zero or one
exact retained gap-reset message in no-API arms, with all other diagnostics
zero; record/discard arms still require zero SDK warnings. This changes
diagnostic admissibility, not a quality gate. Independent review seals the
amendment before a fresh root authorization. Only the six unattempted
original cases run, adding6 contexts/381 API/378 queued/three discards/three
omissions. No first-stage context is rerun or counted again. The original
stage accepts1/2 and the continuation accepts6/6 under its own rule; those
histories are not rewritten as an original eight-case pass.

The combined frozen CPU analyzer and independent audit retain all28 pairs,
both source-frame and submission-ordinal alignments and both lobes. Every
pair uses the same63 observed source IDs, so those alignments coincide here.
RESET/fresh reference comparisons retain the source25 flag difference when
present. Prior H2 contexts are references and add no new native work.

[AMD's dispatch documentation](https://gpuopen.com/manuals/fsr_sdk/techniques/denoising/)
defines RESET as resetting history accumulation. The checked dispatch table
does not establish discarded-record rollback or the observed binary's
frame-jump notification as a universal contract. Fresh-tail bit identity is
measured only for this pinned provider, wave cohort and controls. Camera and
jitter are static here. The title's actual submission/discard behavior and
the visible stain's cause remain unmeasured.

The [compact archive](evidence/fsrd_native_gap_call_presence/manifest.json)
preserves both stages, the post-observation amendment, preparation and
accounting simulations, root authorizations, source/controls/logs, original
failure, independent reviews and actual audits. Large buffers and executable
payloads remain at SHA256/size-pinned F-drive paths. The source failure-policy
review identifies two FSRD false exits after native history commit—composition
and upscale failure—where the existing invalidation helper can request a
conservative next-dispatch reset. Optional postprocessing retains its current
outer success contract; it does not justify a broader API change. The policy
is not implemented in this diagnostic.

Completed native totals become398 contexts/21,050 successful API RR
recordings:21,042 queued and eight recorded-only discards. Four separate
no-API omissions are not included in RR work. The40 prior identity-fixture
shader dispatches are not native RR calls. There is still no current-alpha
game capture or accepted stain/wave solution.
