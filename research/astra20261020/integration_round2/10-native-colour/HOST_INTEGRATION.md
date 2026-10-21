# Host integration proposal and narrow request ABI

This proposal is based exactly on `astra-audit-20261020`, commit
`5fe436dd9a21cb9cc69dec371521a055c9af049d`. It is deliberately **not applied** to
the production files. Job09 owns the bridge observations; job11 must combine
those changes with this proposal and revalidate the resulting code.

## What the patch changes

[`host/integration.patch`](host/integration.patch) changes three frozen files:
`FSRDNrdBridgeRR_Dx12.h`, `FSRDNrdBridgeRR_Dx12.cpp` and `OptiScaler.vcxproj`.
It adds a one-shot `SetNativeColourResearchRequest`, retains prepared colour
passes in the existing `DispatchLease`, and exposes whether the pair was
actually selected. The project addition compiles the new standalone C++ file
without the production precompiled header. No CSO is embedded, no setting is
enabled, and there is no production request/certificate producer.

[`patch_manifest.json`](host/patch_manifest.json) binds the exact original and
proposed file bytes, base commit and patch. `make_patch.py` reads original blobs
with `git show`; it writes only the patch and manifest. `verify_patch.py` runs
`git apply --check` and applies the patch to a temporary copy of those three
blobs, validates resulting hashes and project XML, and checks placement relative
to provider recording. That check is **not a Windows C++ build**.

```sh
python -B research/astra20261020/integration_round2/10-native-colour/host/verify_patch.py --output /tmp/astra10-host-patch.json
```

## Request, authority and source ownership

[`host/NativeColourBridgeRequest.h`](host/NativeColourBridgeRequest.h) is the
entire new input seam. Its `Config` has two false defaults: `enabled` and
`acknowledgeRejectedResearch`. An absent request has `Decision::Off`, including
an empty public snapshot. The host consumes a request on the next record attempt,
including early failure, so it cannot leak into a later frame.

| Input | Required meaning |
|---|---|
| `convertedOwner` and four converted pointers | A real producer/pool owner for the exact native S, D, linear-depth and packed normal/roughness inputs; COM references alone are insufficient |
| `streamlineFrame` | Exact bridge frame identifier for the attempt |
| `lobes[0]`, `lobes[1]` | Diffuse, specular order; each has independently owned source, authority and support textures plus evidence |
| Source | Physical RGBA16F snapshot copied **before** provider scaling/writes, from a separately owned resource; its declared state must be valid when colour Record runs |
| Authority/support | Original R32_UINT sidecars; exactly `1` grants the declared evidence, every reserved code abstains; synthetic evidence is for controlled tests only |
| Evidence identity | Context generation, frame, command-list recording ID, crop/render/active extents, lobe and D16/S256 route; same on all inputs |
| Evidence version/radius | Binds the complete clipped donor footprint to this estimator and a nonzero producer version |
| Shader | Immutable bytes freshly compiled from the delivered HLSL with the documented strict flags; Prepare creates the PSO while the blob is held |

Raw RR is taken from the canonical bridge slot, selected from the actual final
recovery/flat selection, and their owners are retained separately. The source
must not alias either converted lobe, either raw lobe or either selected lobe.
Ordinary `rawRR == selected` is legal and has deduplicated transitions. There is
no inference of support from alpha, noisy chroma, geometry or pointer equality.

The support contract is stronger than a centre-pixel label: it certifies the
**entire clipped radius-square donor footprint before guide rejection**, with
compatible causal material/illumination response. The new native shader also
requires exact authority/support admission at each donor. No real producer has
been shown to supply this evidence. Its absence leaves the pass off/identity.
A trusted caller can lie about metadata; the structure is an explicit contract,
not proof that a producer satisfies it. Job09 observations are not certificates.

### The producer's independent lifetime obligation

Source/sidecar/converted copy commands can already be on the command list before
optional colour admission runs. **The producer must independently retain every
owner for those earlier commands through actual GPU completion and permitted
list re-execution, even if the colour request is OFF, rejected or fails.** The
temporary request is consumed and released on those paths. A recording ID from
`RecordedComputeLease::Capture` only proves an existing tracked recording; it
does not prove admission or lifetime of these particular producer resources.

An admitted colour pass retains its own input owners in `Prepared`, and that
owner is retained by the bridge `DispatchLease`. This supplements, but cannot
replace, the producer's original command lease. Passing the enclosing
`DispatchLease` as an input owner would create a cycle and is forbidden.

## Placement in the actual bridge

1. Resolve existing recovery/flat selection pointers as the frozen bridge does.
2. Prepare both lobes before public RR owner allocation, compute-lease retention
   and provider dispatch. All resource allocation, PSO/descriptors, complete
   uploads and budget admission happen here; Prepare records no GPU commands.
3. Retain both `Prepared` owners in that exact `DispatchLease`. If either fails,
   release both and retain the original selected outputs.
4. Let provider normalization guards restore the physical domain. Complete
   recovery and flat output selection in the original order.
5. Confirm the same recording object/ID, then `CanRecord` both lobes before
   recording either. The serialized caller guarantees no concurrent list use.
6. Record both passes and publish both selected pointers together. Rewrite the
   existing commit SRVs in their actual **specular, diffuse** order. Raw pointers
   remain canonical raw RR; generation/recording/ticket/commit checks remain.

`nativeColourActive=true` means this pair replaced the selected pair. Individual
`nativeColourDecision` values are preparation decisions in **D,S order**; Ready
for one lobe alone is not proof of dispatch/publication. A later recording veto
leaves the original pair selected. There are no allocations after provider
recording inside the colour path.

The supported proposal is deliberately narrow: explicitly enabled native D16/S256,
no post-motion-anchor input mutation, no turn-colour/turn-brightness route and no
debug-output context. Reset/recreate is exact identity. Unsupported routes remain
unmodified. The provider may still perform its existing scale round trip; this
pass never attempts to reconstruct a lost source from the restored input.

## Budget and outstanding integration evidence

The proposal uses the existing retained recovery family, its `graphBytes`,
`retainedPeakBytes` and `slots.allocatedSlots` atomics, and its byte/slot limits.
Each lobe is one slot. All seven committed resources and upload prefill bytes are
charged before allocation; a separately labelled 128 KiB descriptor policy
reservation is added. `graphBytes` includes the colour resources; any existing
per-kind `slotBytes` observation must not be presented as the complete new family
breakdown. Job11 must merge its observations and preserve that distinction.
PSO/driver metadata is not measured by this resource accounting.

At equal allocations the logical payload is approximately 64 B/pixel/lobe,
128 B/pixel for D+S, before alignment and multiple retained recordings. No GPU
timing, total residency or production budget suitability has been established.

The proposal must be compiled with job09, exercised through actual bridge
selection/commit, and subjected to allocation/fault/lifetime tests. Standalone
class tests cannot establish that the host producer, command-list registry,
reset semantics and commit descriptors are correct in the combined graph. See
[`GPU_GATES.md`](GPU_GATES.md) for the remaining acceptance sequence.
