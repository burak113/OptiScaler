# 09 — Implement native observations and support provenance

Work in https://github.com/burak113/OptiScaler from tag `astra-audit-20261020`.
Read `research/astra20261020/audit_round2/NEXT.md` and AUDIT.md first. Inspect
current code rather than trusting reports, authorship labels, or memory. Use a
small number of focused subagents for code review and independent falsification;
work thoroughly until there is a reviewable implementation, not only a plan.

Your deliverable is production-compatible, default-off native diagnostic capture
and explicit support/authority contracts. Own new observation/support classes,
tests and host instrumentation in FSRDNrdBridgeRR_Dx12.* and its capture plumbing.
Job10 owns the new colour pass and supplies an unapplied host adapter. Coordinate
through documented interfaces; do not overwrite its work. Put new research under
`research/astra20261020/integration_round2/09-native-observability/`.

Read original jobs01,04,06,07, their executable models, blocked-data requests and
the actual native resource lifecycle. Trace exactly where physical source,
raw RR, selected output, D/S scale, native normal/roughness, depth, motion and alpha
are available. Implement an observation packet that preserves original words,
format/row pitch, active/allocation extent, crop origin, frame/reset epoch,
motion coordinate convention, selected/raw provenance and authority. Authority
must come from the actual selection path; equality is an additional guard, not a
manufactured ownership certificate. Alpha is opaque. Missing observations must
remain explicit unknowns. Never turn diagnostic correlation into cause or truth.

Job04's support certificate must describe the actual nonzero donor footprint,
including recalled key validity and the estimator's +/-3-cell support. A current
cell geometry tag cannot certify an already mixed gain. Implement the support
producer/consumer ABI and minimal conservative producer where evidence supports
it; otherwise emit invalid support with a reason. Reject NaN/Inf/depth sign errors,
thin surface mixing, crop/grid phase mismatches and unavailable correspondence.
Do not add a filtering algorithm or change the protected native defaults.

Design the smallest deterministic CPU tests that falsify wrong origin, stale
epoch, wrong lobe/scale, incorrect packed normal, missing carry, synthesized
authority and contaminated donor support. Include at least one intentionally
broken implementation the tests reject. Reuse original fixtures without editing
them; preserve chronological single-pass sequences and baseline masks. Keep
all allocations/copies/telemetry absent when disabled. Audit device reset, resize,
resource states, descriptors and failure cleanup. Compile what your environment
actually supports; never call a source inspection a Windows build or GPU test.

Run `python research/astra20261020/audit_round2/run_cpu.py --output /tmp/astra09`
plus new tests. Return a PR targeting `sol/astra-audit-20261020` or a complete
patch ZIP, exact commands/statuses/source hashes, ABI documentation, resource and
memory cost accounting, and a small local GPU acceptance recipe. No game install,
default changes, automatic merge, invented quality win or deletion of old evidence.
Final answer in Turkish, concise, with concrete artifact links and remaining gates.
