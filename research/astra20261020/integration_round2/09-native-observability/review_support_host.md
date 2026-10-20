# Independent support and native-host review

Review scope: the working-tree job09 change based on immutable tag commit
`5fe436dd9a21cb9cc69dec371521a055c9af049d`. The host findings below are **source
inspection**, not a Windows DLL build, GPU execution, debug-layer result, image
identity result, or performance measurement. The separate portable support
checks do execute the actual C++ support header.

## Host verdict

No blocking source defect was found in the reviewed opt-in linkage, recording
lifetime, source-state restoration, or authority/support handling. The principal
native execution gate remains a Windows build and real command-list/fence test.
The separate WARP fixture and extracted serializer validation are owned by other
job09 workstreams; this review does not claim their results.

### Default-off linkage and observation timing

- `Request::nativeObservations`, the transient menu checkbox, and the atomic
  request gate default to false. `CommitNativeTransaction` supplies the optional
  callback only for the active selected native bridge signal. Other `RecordOwned`
  callers retain their existing behavior through the default empty request.
- `RecordOwnedImpl` calls the observer after `inputAnchor.RecordInputs` and before
  turn filtering and provider scale conversion. Thus the separately timed
  original/effective copies can preserve that stage's words. The metadata says
  **before turn filtering**; it does not claim these are the subsequent filtered
  provider input words.
- With the option disabled, the new path performs no diagnostic allocation,
  descriptor creation, resource query, copy, barrier, or telemetry operation.
  Ordinary frozen selection/reset bookkeeping still exists on RR records.
- This observation hook covers the owned native transaction capture route. The
  separate early/legacy `FinalizeMotion` RR call does not pass it and does not
  call `RecordBridgeOwned`; its observation coverage must not be implied.

### Lifetime, allocation failure, and publication

- The early observation frame starts discarded and enters the existing retained
  ledger before its readback allocations or GPU copies. The RR output keeps a
  weak reference, avoiding the cycle through frame, dispatch lease, and output.
- The early callback preflights a conservative complete-frame byte charge,
  arms the existing submission ticket, allocates all early readbacks, and retains
  their sources before recording copies. The later capture adopts only the
  matching session, command list, recording ID, frame, reset epoch, context,
  extents, crop, and original/effective resource pointers.
- An early-only frame never enters the CPU snapshot queue. Later failure leaves
  it discarded and bounded by the existing byte/ticket ledger until the real
  completion/reset proof permits release. This is preferable to treating a
  recorded command as publication evidence or freeing referenced resources.
- `FrameGraveyard` and the local frame are declared before the control lock, so
  their COM-containing destruction occurs after unlocking. The existing fence
  ticket remains the source retention and submission/completion boundary.
- `CopyCpuWords` runs under the protected completed snapshot and copies original
  rows after removing only readback pitch padding. Equality/authority metadata
  is completed afterward from the immutable CPU payload; no JSON work is added
  inside the protected Map/memcpy section.

There is one bounded efficiency limitation: the early callback can copy inputs
for a fourth pending frame before the later `RecordBridgeOwned` pending-count
check stops capture. The resulting discarded orphan remains charged and retained
under the existing limits. It does not become a published frame or permit early
release. No duplicate pending counter was added for this case.

### Resource states and byte semantics

- The original/effective physical surfaces are copied while the anchor/owned
  decode contract places them in `NON_PIXEL_SHADER_RESOURCE`; each copy restores
  the declared state. Gain likewise ends in that state.
- The exposed accumulator is a borrowed pointer owned by the anchor prepared
  graph. `RecordInputs` restores its 32-byte buffer to `COMMON`; capture uses
  `CopyBufferRegion` for all 32 bytes and restores `COMMON`. Both low/high atomic
  words and counts remain available. It does not reinterpret the buffer as a
  texture or as a short floating-point statistics array.
- The exported payload uses tight row pitch, while the original padded D3D copy
  footprint remains separate metadata. The native texture's physical pitch is
  explicitly unknown. Original allocation, active, captured, and crop extents
  are distinct.
- Converted bridge normal/depth/motion and provider stages are labeled as such.
  The title's pre-conversion normal alpha, raw depth, raw motion and native crop
  origin remain explicitly unavailable. Converted geometry is not used to
  invent the missing original words or coordinate mapping.

### Authority and support

- Per-lobe selection paths freeze the host's actual resource assignment. A
  recovery/flat-albedo output remains protected even if its bytes equal raw RR.
  Raw/selected identity is derived from same-time resource aliasing, and word
  equality is only an additional guard after the protected snapshot.
- Capturing complete sums or an identity gain does not certify donor lineage.
  The native serializer calls `InvalidNativeSupport`, emits reason mask 3
  (missing actual donor footprint and recalled-key correspondence), and keeps
  `raw_edit_eligible=false` for both lobes. No native support producer has been
  invented.
- The metadata helpers use the portable surface/selection validators rather
  than duplicating the authority policy. JSON contains named fields and original
  numeric words, not raw compiler-dependent C++ object layouts.

## Portable defects found and repaired

Independent review exposed two additional structural/numeric holes in the new
support contract; both were fixed in its actual implementation and exercised:

1. A deserialized certificate with a matching valid crop that excludes its
   recipient could pass the consumer. `Accepts` now requires the full recipient
   8x8 cell to lie inside the observed crop.
2. Finite pixel coordinates can produce infinite subtraction and a NaN dot
   residual. An ordered comparison alone then fails to reject the pixel.
   `CertifyCell` now validates intermediate deltas, normal agreement, and plane
   residuals. `Compatible` also explicitly rejects nonfinite plane dot products.

Earlier review repairs covered the D3D12 device-removal fence sentinel,
submission/completion timeline identity, contained crop coordinates, and exact
policy binding. A valid geometric certificate remains narrower than material,
object, layer, or causal identity.

Executed after these repairs:

```text
python research/astra20261020/integration_round2/09-native-observability/support_run_checks.py --output /tmp/astra09_support
```

The actual production header compiled with GCC/C++17 and warning-as-error flags;
**56 deterministic checks passed**. The deliberately current-cell-only producer
failed **27 assertions** and exited 1 as expected. Three frozen native-policy
fixtures were read once in chronology with their original masks and file hashes
unchanged. The execution receipt records commands, statuses, platform, and source
and executable hashes. These are CPU results, not fresh native GPU support.

Focused `git diff --check` for the seven reviewed host/menu files also passed.
This is a whitespace check only.

## Reviewed file snapshot

SHA-256 values below bind the review to the local source snapshot; later edits
require reassessing affected findings.

| Source | SHA-256 |
| --- | --- |
| `OptiScaler/shaders/fsrd_preprocess/FSRDGameTraceSession.cpp` | `07fe20f1acc3b6eec37efb54f688fda3886c42e24def9f4fbc418bd62156e313` |
| `OptiScaler/shaders/fsrd_preprocess/FSRDGameTraceSession.h` | `7646d02b6d136a79340d33f411f22b64db3bb8a67209da87cb9a26da937436e9` |
| `OptiScaler/shaders/fsrd_preprocess/FSRDNrdBridgeRR_Dx12.cpp` | `0833aa3d9974ee925dc31256e30545b0fd97bc7ed564cea5dce5162fc4f2a48e` |
| `OptiScaler/shaders/fsrd_preprocess/FSRDNrdBridgeRR_Dx12.h` | `e8727e472a3dd854fa1e044d0e4df0aab72fbe92670bdda075103f582ac9c64b` |
| `OptiScaler/shaders/fsrd_preprocess/FSRDNrdBridge_Dx12.cpp` | `02aa98acac89d7f44ba94059761293586b46974873fdfa82b6108d9d7c35207e` |
| `OptiScaler/shaders/fsrd_preprocess/FSRDNrdPostMotionAnchor_Dx12.h` | `3f9993dc7c5f7285160ac40eb3b471eca49df8de4762c591830dc513fc2e5917` |
| `OptiScaler/menu/menu_common.cpp` | `acea55f0c0b56a5edb0d60afacbb014962280f29a441e9af10f6cbce017557ac` |
| `OptiScaler/shaders/fsrd_preprocess/FSRDNrdSupportContract.h` | `0c280107c31c3186ecb36cca5af67b2f85de6d2ac35b3379e5a8375dc976deaa` |
| `research/astra20261020/integration_round2/09-native-observability/support_contract_test.cpp` | `f31ba3e95c87f28c28507b0a3eec52d3c51d279f7dcadfd873ddbd3e41ce6945` |
