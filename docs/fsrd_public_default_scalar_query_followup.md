# Public default scalar query followup — 2026-10-01

A fresh context returned six public default scalar values successfully from
the pinned AMD denoiser provider. This completes the query-only followup to
the [clean material stage partition](fsrd_clean_material_response_stage_partition.md).
It changes the measured-settings provenance, not the image-quality result.

In public-key order `[6, 1, 2, 3, 4, 5]`, the actual float32 returns are:

- Disocclusion threshold: 0.009999999776482582, bits `0x3c23d70a`.
- Cross-bilateral normal strength: 1, bits `0x3f800000`.
- Stability bias: 1, bits `0x3f800000`.
- Maximum radiance: 65504, bits `0x477fe000`.
- Radiance clipping standard-deviation K: 50, bits `0x42480000`.
- Gaussian-kernel relaxation: 0, bits `0x00000000`.

All six differ in float32 bits from the clean B342 fixture's explicit fork
default vector `[0.1, 0.5, 0.5, 40000, 40, 0.5]`. That fixture makes six
one-time scalar Configure calls, one per key; its global-debug Configure is
separate. The current query probe makes no Configure calls and applies none
of these returned settings. A matched default-vector RR image-response test
remains unmeasured; no gain, noise, stain or wave improvement follows from
the queried numbers alone.

Actual work is one successful CreateContext, six Query entries/returns with
public return code zero, and one successful explicit DestroyContext. Caller
RR Dispatch, Configure and Execute counts are all zero. The 24-byte raw
float file matches all six child returns bit for bit. The separate independent
[postrun review](evidence/fsrd_public_default_scalar_query_followup/fsrd_sdk_default_scalar_query_postrun_review_20261001/review.json)
passed with no blocking findings. It pins the source lifecycle, terminal
and prefix accounting, actual guard, stdout/stderr and before/after identities.

The context used render size 128 × 80 and the authenticated provider DLL
with SHA256 `48f1e5888ba6a0a3d59a98b9751e37c392b0f7b8c223d0082d5c1f40642879d3`.
The actual probe EXE SHA256 is
`cb1db4d103665c49d1e956222d69b9c407903d2290e25928593d2e95bb259b27`.
Ordinary D3D errors/warnings and child stderr bytes are zero. SDK private
callback warning counts remain unavailable because no global-debug Configure
callback was installed. Provider-internal GPU initialization, private shader
dispatches and queue behavior are unknown; successful public DestroyContext
is not a private GPU-quiescence proof.

Cumulative completed SDK contexts are now 415: 414 RR-workload contexts and
one query-only context. Successful RR API recordings stay 22,074 and
queued/completed RR recordings stay 22,066; eight recorded-only discards
and four no-API omissions remain separate. Clean-stage helper calls and
explicit helper shader Dispatch calls stay 516. No private SDK shader count
is inferred.

The original stage archive's zero-query statement describes its historical
freeze boundary. Its 334 files and seals remain byte-identical. The
[pre-followup stage document](evidence/fsrd_public_default_scalar_query_followup/historical_stage_document_before_query_followup.md)
preserves its original SHA256 `9cf05417b76e5138c0fa543b5903f4147f2fd099fd88feebfc278aacc5a3e74a`.
The current stage document corrects the scalar Configure count and links this
later measurement; old snapshots and results were not rewritten.

The separate [followup archive manifest](evidence/fsrd_public_default_scalar_query_followup/manifest.json)
preserves the query source, protocols, actual logs/guard/raw returns and
independent review. Binaries and larger source/CPU pin tables retain verified
[external identities](evidence/fsrd_public_default_scalar_query_followup/external_references.json).
This documentation/copy operation executes no SDK, GPU, build or scorer,
and changes no runtime settings. The game-quality objective remains open.
