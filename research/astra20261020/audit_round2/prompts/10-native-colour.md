# 10 — Implement a testable native colour pass and fix its actual failure mechanism

Work in https://github.com/burak113/OptiScaler from tag `astra-audit-20261020`.
Read audit_round2/NEXT.md, AUDIT.md, local GPU results and original jobs02,03,05.
Use focused subagents for numerical analysis and independent review. Produce
code and measured evidence, not just a discussion. Keep original candidate files
and receipts immutable; new work goes in integration_round2/10-native-colour.

Own a new standalone native per-lobe pass/class, shaders and portable model/tests.
Do not directly edit FSRDNrdBridgeRR_Dx12.*: job09 owns host observations. Supply an
explicit host integration patch against the frozen base and a documented narrow
input ABI; job11 will combine it with job09. Inspect the actual resource/lifetime
code before designing this patch. Preserve D16/S256 and native alpha words. Native
source, raw RR and selected output are separate resources with explicit authority;
an existing combined/quarter-resolution pass does not prove native integration.

The returned log-colour candidate is REJECTED for visual adoption. Local RX9070
proved five small synthetic packing/transport cases, not image quality, native
routing, full allocation safety, real capture replay or performance. Its actual
CPU step-response failure and 32 low-contrast boundary counterexamples remain.
Anchor job02 abstains with gain=1; glass Haar shrinkage is rejected. Do not rename
identity as improvement, lower the rejection threshold or simply enable any of
these methods. Keep competing causal hypotheses and predictions; first reproduce
the existing failures at equal achieved correction strength. Examine why noisy RR
chroma cannot reliably distinguish a low-contrast true boundary from estimation
noise. Change representation/support only when an experiment distinguishes it.

Implement a default-off native pass with exact passthrough for OFF, strength0,
unknown authority/support, reset/resize and invalid samples. Preserve selection,
alpha payloads/signed zero, padding, real step response and thin detail. Use the
provided packed shader/CPU model only as a starting point. Make constants, formats,
copy footprints, failure handling and resource state transitions reviewable.
Host code must validate constants and buffer sizes and prefill the complete output.
Invalid Config must not reach the shader. Do not claim a per-lobe scale conversion
is correct until its round trip and native contract are tested separately.

Falsify with blind low-contrast material/light boundaries, sparse/heavy-tailed
source, correlated noise, glints, true illumination steps, moving crops, unequal
allocation and boundary phase. Freeze masks from baseline inputs and measure
correction dose, grain/flicker, contamination and detail independently. Report
ablations and uncertainty; do not promote a lower-gain apparent win. If no better
algorithm survives, deliver the safe pass/test infrastructure and a rejected
candidate with an explicit measured boundary, not a fictitious success.

Run the aggregate CPU command and new meaningful tests, include known-bad
controls, compile only what your environment actually supports, and prepare
deterministic native GPU input/output fixtures and local commands. Return a PR
to `sol/astra-audit-20261020` or patch ZIP with hashes, separate mechanical and
quality verdicts, and precise remaining GPU/game acceptance gates. No default
enablement, automatic merge or game deployment. Final summary in Turkish.
