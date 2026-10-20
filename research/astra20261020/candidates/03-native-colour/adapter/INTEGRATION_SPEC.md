# Job 08 adapter specification: native post-selection colour

Status: **research interface only; the frozen candidate fails quality acceptance**.
This exact specification is the task prompt's permitted alternative to an
executable `PRODUCTION.patch`. No production code, public setting, generated
bytecode or host hook is changed by job 03. Job 08 must not promote this candidate
on the strength of its bit-preservation tests or clean large-contrast edges.

## Immutable reference and safe location

The reviewed source revision is `5d7839a930106cf8fe1ba8dbbc6750509e7f26a8`, tag
`astra-handoff-20261020`; frozen production revision is
`87e8b7ab2a428bd91d3c044decf7d4dbccd8cefd`. The relevant source is
`OptiScaler/shaders/fsrd_preprocess/FSRDNrdBridgeRR_Dx12.cpp`.

Two distinct insertion phases are required in `RRWrapper::RecordOwnedImpl`:

1. **Prepare** after both recovery/flat-recovery output pointers are selected
   (the `if (flatPrepared) { committedSpec=...; committedDiff=...;
   SetCommitInputs(...); }` block), and before `RRRecordedOutput` allocation,
   `ResTrack_Dx12::RetainComputeDispatch`, or any provider commands. Prepare all
   owned output textures, staging buffers, constants, descriptor heaps, debug
   UAVs and budget charges. Keep the original `committedSpec/Diff` pair and their
   owners. Preparation failure leaves that pair and descriptors unchanged.
2. **Record** after the provider scope and its normalization-restoration RAII
   destructors have completed successfully, after `recovery->Record`, and after
   `flatAlbedo->RecordOutput`, immediately before `flatWasActive` and the recorded
   output diagnostics are published. Record the packed copies/compute/output
   copies here. Then update the selected resource pointers **and** the commit
   SRV descriptors before publishing `output = std::move(recorded)`.

Do not put this work inside the provider's normalization scope or after
`CommitOwned` has encoded/written title output. `RestoreSignals` and the shared
`FSRDRadianceScaleDx12::Scope` must have restored physical units first. The
candidate must never read one lobe at D16 scale and the other at S256 scale.

The production `FSRDColourTrackApply.hlsl` cannot be reused as this native apply:
it interprets target alpha `<0.5` as authority and writes alpha `1`. Native alpha
is opaque signal/hit-distance data. This proposal uses an explicit authority
mask and retains each original alpha word.

## Small per-lobe interface

| Input/output | Contract |
|---|---|
| Physical noisy input | Actual restored provider-physical D or S source, RGB in physical linear pre-remod units; original half RGBA words |
| Raw RR | Canonical `lease->slot->diff/spec`, restored physical RGB, before any selection |
| Original selected RR | Existing post-recovery/FlatAlbedo result, immutable during this pass |
| Depth | Original signed float32 linear depth; zero/nonfinite invalid |
| Normal/roughness | Corresponding original native R10G10B10A2 guide, oct RG and linear roughness B; material A is not a semantic class |
| Authority | Explicit validated boolean policy; never native alpha, candidate output or a rounded comparison |
| Eligibility | Original selected **RGBA storage words** equal original raw RR words, AND authority and active extent |
| Writable output | Private same-format RGBA16F resource, initialized as an exact selected copy |
| Alpha | Every original selected alpha word preserved, including zero, signed zero and payload bits |
| Protected pixels | All four original selected words preserved if selected differs from raw, even only in alpha/one ULP |
| Extents | Allocation/max W,H distinct from active W,H; padded inactive pixels preserve selected bytes |
| History | None. No temporal state, reprojection, frame replay, previous crop or reset warmup |

Use the physical source pair selected by the input-anchor ownership path when
that path is active; do not accidentally use a provider-scaled temporary or a
stale source. Preserve the existing G3 original-input domain. Initial local
tests should keep all older optional prefilters off, matching the protected
preset. Any support for a concurrent turn-colour input copy must separately
prove which restored source is the intended target; until then fail closed for
that combination.

Provider/selected data must have matching frame ID, context generation, device,
recording ID, dimensions, formats, source crop and lifetime. No implicit lobe
sum or normalization by native alpha is allowed. The CPU supports FP32 only for
contracts/diagnostics; the proposed shader accepts original native FP16 only.

## Ownership, descriptors and commit consistency

Add a prepared-colour owner to the already retained `DispatchLease`, following
the existing recovery `Prepared` lifetime shape. It owns every buffer, output
texture, descriptor heap, constant allocation, diagnostic texture and budget
reservation. The old selected owners remain retained because the pass reads
them after their own output recordings. No resource can be recycled until the
exact command list/recording fence completes; another in-flight frame must
not overwrite its constants or descriptors.

The following is **host pseudocode**, not disconnected compilable integration:

```cpp
// EARLY: all fallible work, before any provider commands or publication.
const SelectedPair originalSelected{committedSpec, committedDiff};
lease->nativeColour = PrepareNativeColourDefaultOff(
    physicalProviderInputs, rawSlotPair, originalSelected,
    originalGeometry, explicitAuthority, activeExtent, allocationExtent,
    familyBudget, frameAndRecordingIdentity);

// LATE: after successful provider restore -> recovery -> flat output.
if (lease->nativeColour.valid) {
    RecordPackedColourCopiesAndDispatch(list, lease->nativeColour);
    committedSpec = lease->nativeColour.specular;
    committedDiff = lease->nativeColour.diffuse;
    recorded->selectedSpec = committedSpec;
    recorded->selectedDiff = committedDiff;
    lease->context->SetCommitInputs(*lease->slot, committedSpec, committedDiff);
}
// Publish this recording only after pointers AND descriptors agree.
```

`GetOwnedOutputSnapshot` must consequently return the new selected pair while
its raw pair remains the canonical raw slot. `CommitOwned` uses both selected
resources in its alias checks/transitions and the SRVs established through
`Context::SetCommitInputs`; changing only either side is incorrect. The latter
builds SRVs in **specular then diffuse** order. Match that ordering even when
public diagnostics list diffuse first.

Retain the early lease in the existing recorded-compute registry, without an
ownership cycle involving `RRRecordedOutput`. Preserve existing stale generation,
source-list/recording identity and ticket checks. The guarded title commit must
contain no new allocation or failure point. Invalid preparation/unsupported
format/debug constraint/no budget means pass-through to original selected.

## Packed-word command and memory contract

Follow `../shaders/README.md`: three texture-to-buffer bit copies, a separate
selected-buffer initialization copy, one compute dispatch, then one
buffer-to-owned-output-texture copy **per lobe**. Use valid
`GetCopyableFootprints` row pitches and 512-byte footprint offsets. Validate the
full buffer span and all uint32 byte-address arithmetic before recording.
Selected/output footprint layouts must match for initialization. Preserve
allocation pixel bytes; unused row padding carries no radiometric meaning.

Transition every copied texture/buffer between its exact previous state and
COPY_SOURCE/COPY_DEST, then shader SRV/UAV states as appropriate. Insert a UAV
barrier after compute before copying its output. Leave private selected output
textures in the UAV state expected by the existing commit path; restore input,
raw and prior-selected resource states expected by other readers. Descriptor
rebinding must use this recording's retained heap.

Analytic incremental unaliased layout, excluding descriptors, padding and
retained-flight duplicates: 80 bytes/allocated pixel for D+S, or 112 with the
proposed FP32 diagnostics. At 2560×1440 these are **281.25 MiB** and **393.75 MiB**
respectively before alignment. These are arithmetic estimates, not measured
allocation/residency. There are two 49-tap compute dispatches and ten copy
operations for the diagnostic D+S path. This deliberately conservative vehicle
is expensive; any later zero-copy rewrite needs its own typed-view/word-parity
proof and budget accounting. No GPU time is available.

## Default and acceptance

The CPU configuration defaults to `enabled=False`; no host feature is added.
The integration proposal would also remain default-off, with zero extra work
and allocations when off. Preserve the user's D16/S256, G2/G3, RR Fallback,
Diffuse RR and Reflection History settings; NZR Temporal remains off.

The native ON canary must demonstrate an actual selected-pointer/SRV change,
nonzero eligible correction even with native alpha0, and word-identical NZR
protection. It must kill a forced-OFF and broken-selection mutant. Then run
all-phase boundaries, the additional low-contrast counterexample, shader parity,
fresh unlooped AMD RR and a calibrated same-crop final-game observation. The
current failed quality verdict is not waived by passing this integration test.
