# Native material reader capture (2026-10-21)

The user's 88b22c2cc game run still produced white guides: the last status sample
had 955 material capture attempts, zero snapshots and zero applications. Both
source-state witnesses said `recording_invalidated`; binding failures were zero.
The previous alias fix did not solve the observed game problem.

## Evidence and mechanism

In survey `bb22daa989a8e892ee4470e3cd9a8a14`, list 1 contains an earlier material
reader at pass 435 and the material/normal guide writer at pass 491. Both bind
base resource 62149 (R10G10B10A2) and parameter resource 62151 (RGBA8), with root
signature SHA-256 `bcb5f3454f596992f694f54ddb53e0f6b0ac7a9d976e8a49d1fc9ddab6a6eb70`.
The recorded state witnesses for those sources occur in separate prolog lists
26 and 17. Preserving local state across unrelated aliases cannot manufacture
missing same-recording state evidence.

Full title shader hashes, independently extracted from the local game cache and
disassembled with DXC:

- Reader: `88c255d29535f9153f7101c32be4f58682675fb8391c94efc135fd6959875e6d`.
  Actual TextureLoad instructions consume both t7 and t9 (three sites each).
- Guide writer: `3e09f2e0d948f77869a0628524c14463e1fdb06fcfb78aa60fc102c78fb0d5ed`.
  Actual TextureLoad consumes t9, with no t7 load. Binding t7 here is insufficient
  evidence that it is compute-readable.

The survey has no bound writes to these sources between the two passes. This is
not proof that all intervening commands are harmless: the survey records bound
views, and the runtime must invalidate an early copy when its provenance changes.
Do not infer a descriptor-table base from the smallest captured descriptor index;
the survey may omit earlier slots. Runtime binding resolution validates the root
layout and exact register-to-offset mapping.

## Change

Recognize only the full reader hash. Next to that legal title compute read, copy
t7/t9 into the existing private material snapshot, without any source barriers
or inferred full state mask. The existing GPU recording lease retains this work
even if a later rejection discards its CPU-side candidate.

At the guide writer, consume the copy once only if both resource pointers, native
Birth identities, metadata generations, subresources, recording and cancellation
serial match. Reject source transitions, direct/global/uncertain aliases, opaque
recording invalidation, Close/Reset, changed bindings and canceled settings. An
unrelated activation may survive only with live, distinct private-heap evidence.
Keep the existing state-witness capture as a fallback. Unknown shaders do not
inherit the new read permission. The option remains default off.

`[NRD_MATERIAL]` now includes reader attempts, snapshots, writer handoffs and the
last reader rejection. `reader_applied` counts the handoff to the guide writer;
the existing `applied` counter still reports admission to RR conversion. A
successful new handoff reports `last_capture=captured_from_reader`.

## Validation and limits

- `test_fsrd_nrd_material_reader.py`: 19 GPU cases / 321 native checks, actual
  signed AMD RR, zero D3D12 errors/warnings. Read back the exact guide resources
  supplied to the provider; accepted cases contain nonwhite diffuse values.
  Sources remain byte-exact, original reader/writer bindings remain correct,
  and the capture emits zero borrowed-source transitions. Combined read states
  are tested with transitions in a separate completed prolog recording.
- `FSRD_READER_DISABLED_CONTROL=1` disables only the new injection in a generated
  coordinator copy. The same executable test then fails at
  `reader_no_local_barriers` with `source_state_unknown`, as expected.
- Existing 8-frame native material suite, 7-case native transaction suite and
  49-case state-witness CPU suite pass after the change.

The GPU fixture uses synthetic title PSOs and explicit readiness/role adapters.
The title-bytecode evidence comes from a real capture/cache, but the new DLL has
not yet been validated in the game. Neither guide readback nor these tests prove
improved image quality, motion behavior, or arbitrary game-version support.

Local evidence and deliverable directory: `E:/FSRD/sol_batch/30-native-albedo-reader/`.
GPU outputs: `F:/FSRD/sol_batch/30-native-albedo-reader/tests/`.
Title binaries/disassembly remain local and are not redistributed.
