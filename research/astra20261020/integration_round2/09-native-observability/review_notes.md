# Independent review scope and evidence

This review was executed against `astra-audit-20261020` commit
`5fe436dd9a21cb9cc69dec371521a055c9af049d` and the new job09 working changes.
It is Linux CPU execution and source review. It is not a Windows DLL build,
D3D12 validation run, GPU replay, game experiment, or a quality acceptance.

## Fresh aggregate baseline

The exact requested command completed with exit 0:

```text
python research/astra20261020/audit_round2/run_cpu.py --output /tmp/astra09
```

All 21 stages passed their declared statuses, including assertion failures from
the six deliberately broken numerical/glass controls. All 559 imported files
retained their intake hashes. The fresh receipt records Python 3.12.14 on
Linux; it does not reuse the incoming Windows receipts as execution evidence.
See `review_baseline.json` for commands, statuses, and SHA-256 hashes.

The first attempt stopped at `portable_adapters` because the shallow checkout
lacked the older Git object needed by `git show`. Its receipt was preserved in
`/tmp/astra09_first_shallow`. Fetching the exact historical object with
`git fetch --depth 1 origin 5d7839a930106cf8fe1ba8dbbc6750509e7f26a8`
resolved this environment limitation; no frozen source or test was changed.

## Reused lifetime contract: executed CPU falsification

```text
python research/astra20261020/integration_round2/09-native-observability/review_run_lifecycle.py --output /tmp/astra09_lifecycle
```

The runner compiles the **actual production** `RRTraceFenceState.h` with the
small new `review_lifecycle_test.cpp`, executes 22 assertions, then deliberately
replaces its release decision with the wrong rule “the fence completed”.
The production state passed; the wrong release rule exited 1 with six concrete
assertion failures. These cover executable command-list resubmission, an
unsealed early observation, ambiguous repeated submission, failed signal,
device-removal sentinel, and untracked submission.

The CPU state machine alone cannot validate real COM ownership, actual resource
states, queue hooks, descriptor restoration, or whether the native host passes
the right object to that state machine. Those remain native execution gates.

## Native source audit findings used by the implementation

| Observation | Actual source point / limitation |
| --- | --- |
| Physical input | `RRWrapper::RecordOwnedImpl` receives `sourceInput`; an optional input anchor substitutes another physical pair before the provider. The pre-anchor and effective pair are different roles. |
| Timing | `Context::ScaleSignals` mutates the input pair in place, clips overflow and uses a typed alpha load/store. Post-restore words cannot certify the original pre-scale words. The new early capture must precede scaling. |
| Raw RR | Owned `slot.spec` / `slot.diff` after provider restoration, before optional recovery selection. This role does not mean native NRD filtered output or truth. |
| Selected output | `committedSpec` / `committedDiff` is assigned by the actual raw, lobe-recovery, or flat-albedo branch. This assignment is the authority source; value equality alone is not. |
| Scale | Legacy provider scale is D256/S256. The opt-in shared scale has defaults D16/S256. Capture actual per-frame per-lobe values, not a global assumed D16. |
| Normals | Converted input is R10G10B10A2. Native geometry conversion preserves RGB components but can clear category A; FlatAlbedo can further change roughness. Neither provider nor pre-flat guide is necessarily the original title word. |
| Depth | Converted depth is signed, clamped/sanitized. `ConvertedResources.validity` is an optional R8_UINT witness of original classification. It is not raw original depth. |
| Motion | Converted XY is previous-minus-current full-render UV with the declared jitter delta. G3 can replace the provider copy. Converted pre-G3 motion and provider motion must remain separate observations. The native-motion setting does not prove every pixel took successful native Z reconstruction. |
| Origin | Native geometry loads at `p + asint(NativeGeometry[28].zw)`. The origin is GPU-owned control data. A CPU zero default cannot attest that original native coordinate mapping. |
| Alpha | Texture copy plus byte export preserves the observed word. No observed alpha is automatically a usable ray distance, confidence, or material property. |

## Capture/lifetime constraints reviewed

The existing `FSRDGameTraceSession` preflights readback allocations, retains
owned sources through an `RRTraceFence` ticket, copies with source-state restore,
and freezes bytes only under `WithCompletedSnapshot`. Tight exported rows are
distinct from their recorded D3D12 copy footprints. Native tiled texture row
pitch is not independently available.

An early frame must stay unpublished unless adopted by the exact same active
session, command recording, frame, resource generation and crop, then completed
by the exact late title commit. An abandoned early frame may still have native
GPU work recorded: it cannot free readbacks merely because RR preparation failed.
No extra queue, synchronous wait, descriptor heap or filter is needed for copies.

The early token must not create `Frame -> output lease -> Frame` strong ownership.
The global retained-frame ledger can hold the strong lifetime while the output
keeps a weak token. Combined allocation preflight must count existing early
readbacks once. Retired frames/COM objects must be destroyed after releasing the
global trace mutex, preserving the existing graveyard-before-lock ordering.

## Final working-diff source review

The implementation now makes the source/effective early copies after the owned
recording and input-anchor initialization, before the turn filters and either
scale path. Early and late stages share one ticket. The late recorder validates
the session, command list, recording ID, Streamline/SDK frames, reset/context
epochs, crop and source identities before adopting the frame. The early frame
remains discarded and unsealed until adoption; no strong output-to-frame cycle
is introduced. Original early readbacks are neither recopied nor reallocated.

One concrete allocation-failure defect was found in the working diff and fixed:
registering a new ordinary Frame in `control.retained` before a throwing
`pending.push_back` could leave it neither frozen nor discarded, so the retained
ledger could never reap it. Newly created ordinary frames now begin discarded,
as early observation frames already did, and become live only after pending
registration, all readback allocations and resource retention succeed. Source
inspection confirms this closes the identified ledger predicate failure.

Independent ABI review also led to rejection of role/format mismatches and
unknown numeric observation roles, explicit R8 validity encoding, rejection of
device-removal fence sentinels and unrelated fence timelines, complete crop/cell
containment in both support producer and consumer, and finite checks on computed
plane residuals. The support owner added deterministic tests for these cases.
Those owner-run tests are recorded separately; this review does not count them
as a second independent execution.

The host uses the actual selected-resource branch to report raw/recovery/flat
authority. Post-fence word equality is a separate guard. Native geometric
support remains invalid with reason bits 3, and `raw_edit_eligible` remains
false even when raw authority is valid. Original title normal/depth/motion,
GPU-owned title origin, material/layer identity and exposure/modulation remain
explicitly unavailable; converted guides are not relabeled as those originals.

The new `review_capture_gpu.cpp` / `review_run_capture_gpu.py` fixture is
prepared, not compiled or executed natively, on this Linux host. It reuses the
existing WARP resource/queue Host and real production recorder, checks timed
physical word canaries and protected equality, and invokes the new offline
reader on actual published folders when run on Windows. See
`review_windows_recipe.md` for the existing machine-local serialization wrapper
interface and the exact current execution boundary.

## Required native acceptance boundary

Run the local Windows/D3D12 recipe after integration: opt-out identity and zero
new capture work; opt-in physical word canaries including alpha payloads;
separate D16/S256 and legacy scale traces; nonzero ROI and odd allocation;
anchor/recovery/flat-selection paths; source-state restoration; abandoned and
unsubmitted recording; actual reset and resize; late commit failure; stop/restart;
device loss and queue-signal failure. Report exact build/debug-layer results.
No passing CPU result in this review resolves those gates.
