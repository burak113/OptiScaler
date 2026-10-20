# Native observation capture: host integration and cost

Base: `astra-audit-20261020`, commit
`5fe436dd9a21cb9cc69dec371521a055c9af049d`. This is an additive diagnostic,
initially disabled. The colour pass and its unapplied adapter belong to job10.

## Activation and exact observation points

The existing NRD bridge GAME_TRACE UI has a transient **Native observations
(exact pre-scale words)** checkbox. `Request::nativeObservations` defaults to
false and rejects non-bridge capture. The native A/B transaction supplies the
optional `RRNativeObservationRequest` only while the capture and selected signal
gates are active. No INI setting or protected filter default changes.

`RRWrapper::RecordOwnedImpl` freezes selection at the assignments to
`committedSpec` and `committedDiff`: initial raw resources, successful lobe
recovery, or successful flat-albedo selection. It retains the recording lease,
records the optional input anchor, then invokes the diagnostic callback before
turn filtering or provider scale/restore. This timing is necessary: the existing
half-float scale/restore can lose original words, including alpha.

| Packet surface | Observed stage |
| --- | --- |
| `physical_source_specular/diffuse` | Original bridge-owned decoded physical pair, before anchor changes and provider scale. The anchor reads, without modifying, this source pair. |
| `physical_pre_scale_specular/diffuse` | After optional input anchor, before turn filters and provider scale. This is the exact provider lighting only if subsequent input filters are inactive. |
| `raw_rr_specular/diffuse` | Provider output after inverse scaling, before optional recovery selection. |
| `selected_rr_specular/diffuse` | Actual selected resources before native commit. A recovery/flat result remains protected even if equal to raw words. |
| `provider_normal_roughness` | Actual packed provider guide after any flat roughness floor. |
| `bridge_normal_before_flat` | Converted guide before that floor; category bits may already have been cleared by conversion. |
| `provider_depth` / `depth_validity` | Signed converted depth and, when exposed, original classification from the geometry writer. Sanitized depth is not raw title depth. |
| `provider_motion` / `bridge_motion_before_lighting_guard` | Final provider motion and converted motion before optional lighting validation. |
| `anchor_sums` | When active, all eight uint32 words of the existing 32-byte native accumulator, including low/high carry and count. |

The existing trace still carries albedos, encoded commit outputs, optional native
encoding/control words, provider controls, settings, binaries, and anchor gain.
Those roles are not renumbered. New original-source copies are separate from the
late restored-input snapshots, even when they use the same resource address.
Same-time original/effective aliases share one early copy; raw/selected aliases
share one late copy. No alias is inferred from value equality.

Original title packed guides/depth/motion, GPU-native crop offset, per-pixel
motion correspondence, material/layer identity and upstream exposure/modulation
are explicit `unknown` fields. Bridge render ROI origin is observed and is a
different coordinate fact from the unobserved native-title offset. Native tiled
texture row pitch is unknown. The exported tight-file pitch and the actual D3D12
copy footprint are both recorded and must not be interchanged.

## Packet identity and consumer boundary

`capture.json` and each published `frame.json` carry
`native_observations.schema = fsrd-native-observation-v1`. The named-field wire
format includes the capture ID and a `{stream_id, frame, reset_epoch,
resource_epoch, known}` stamp. Resource IDs are frame-local alias IDs, not stable
GPU pointers. The reset epoch increments at an actual reset recording attempt;
context recreation increments resource generation. Failed recordings are never
published as observations. Gaps in epoch numbering do not prove a submitted
reset. The actual dispatch reset flag is separately checked on early adoption.

Every present surface has role/lobe, source allocation, active/captured extent,
ROI origin, format/encoding, tight payload layout, actual copy footprint, and
per-lobe provider/stored scale. D16/S256 is recorded when selected; the legacy
D256/S256 path is not silently relabelled D16. Observed alpha is opaque bytes.

After a protected completed-fence snapshot, the writer compares complete raw
and selected byte payloads and evaluates `ValidateRawAuthority` against the
actual selection witness. `raw_authority_valid` may become true for a raw route.
`raw_edit_eligible` is always false: native donor/key lineage is unavailable and
the support result is `valid=false, reason_bits=3`. Equality, gain and frame sums
cannot turn this into valid geometric support.

The [offline reader](observation_capture_reader.py) validates published prefixes,
payload hashes and lengths, frame/manifest agreement, ROI/format/scale/stamps,
provider control words, selection authority and required unknown declarations.
It does not authenticate a malicious producer or turn a capture into causal or
quality evidence. Output must be outside the capture directory.

```text
python research/astra20261020/integration_round2/09-native-observability/observation_capture_reader.py <capture-folder> --output <scratch-report.json>
```

## Ownership, resource states and failure paths

The early callback plans the full later packet conservatively before its first
copy and uses the existing global readback ledger and `RRTraceFence`. It retains
all readbacks and owned sources before recording copies. The recorded output
holds a **weak** early-frame token, avoiding a `Frame -> output lease -> Frame`
cycle. The late recorder adopts only an unsubmitted token from the same session,
command list, recording, frame/SL index, reset/resource epoch, ROI and sources.
It allocates only missing later readbacks and charges early readbacks once.

Early and newly created ordinary frames stay `discarded=true` until successful
admission. This also covers a vector-allocation failure between global-ledger
registration and pending-list registration. Unadopted frames are unpublished but
remain charged/retained until the existing fence/reset contract proves release
safe. A completed fence alone cannot release an executable recording that may
be resubmitted. Graveyard objects are destroyed after the trace lock is released.

Physical input, converted guides, validity and anchor gain copies transition
from `NON_PIXEL_SHADER_RESOURCE` to `COPY_SOURCE` and back. Raw/selected outputs
use their existing `UNORDERED_ACCESS` copy contract. The anchor sums buffer is
`COMMON` after `RecordInputs` and is restored to `COMMON` after its buffer copy.
The new copy path does not set descriptor heaps/root tables, dispatch a shader,
create a queue, or wait synchronously for a fence. Declared source states are
contract metadata, not independently observed GPU states.

The existing publication path requires a matched late commit and seals the
same ticket. CPU byte copying happens only under `WithCompletedSnapshot`; JSON,
equality, hashing and disk work happen outside that submission gate. Repeated
submission, stale identity, reset/resize/context changes, stop/cancel, failed
commit, signal failure and device loss use existing lineage invalidation and
retention rules. Native execution is still required to verify actual hooks,
COM lifetimes and driver state tracking.

The first late call claims/initializes a session. Its missing early token is
allowed only before the capture is bound; the next eligible frame starts the
observation. After binding, a missing token terminates capture. Initialization,
delay and an explicit reset request cannot fabricate pre-scale words.

One bounded inefficiency remains: early input copies can occur before the late
recorder sees the fourth pending frame and stops for backlog. This orphan stays
in the same byte ledger and is never published. No second pending counter or
unbounded queue was introduced.

## Resource and memory accounting

With `nativeObservations=false`, incremental observation GPU allocations,
readback copies, descriptors, shader dispatches and emitted observation
telemetry are **zero**. The RR output contains a small fixed CPU stamp/selection
and weak-token addition; no observation object is allocated. Existing ordinary
GAME_TRACE costs are unchanged except for failure-safe admission bookkeeping.

Let `P = ROI_width * ROI_height`, and let `A(w,h,b)` be the device-reported
committed READBACK allocation size for the actual D3D12 copy footprint of a
`w x h` image with `b` bytes/pixel. Charging uses
`GetResourceAllocationInfo`, not tight payload bytes or a guessed 64 KiB rule.

| Increment over the existing bridge capture | Extra tight payload/frame | Extra committed readback/frame |
| --- | --- | --- |
| Original physical S/D | `16P` | `2 A(w,h,8)` |
| Distinct after-anchor S/D, if present | `16P` | `2 A(w,h,8)` |
| Original motion distinct from provider motion | `8P` | `A(w,h,8)` |
| Original depth validity, if available | `P` | `A(w,h,1)` |
| Active anchor sums | `32` bytes | Device allocation for a 32-byte buffer |

The pre-flat normal and anchor gain were already optional trace witnesses.
Their costs remain in the shared whole-frame budget. No new GPU texture,
descriptor, compute shader or auxiliary queue is introduced.

For a 128x128 ROI on a device using ordinary 64 KiB buffer allocation alignment,
each RGBA16 readback is 128 KiB and the R8/sums readbacks are 64 KiB each. The
increment is 256 KiB for two early physical copies, 320 KiB including validity,
and at most 768 KiB with four early copies, distinct motion, validity and sums.
These are allocation calculations, not measured GPU consumption or timings.
Tight payload increment ranges from 256 KiB to 656 KiB + 32 bytes. Retained
frames and immutable CPU snapshots can coexist and are bounded separately.

Before any early copy, conservative admission includes all 14 ordinary roles
without alias savings, both potential original guides, validity, the full anchor
gain grid, sums and provider controls. Its tight-payload envelope is
`(117..133)P + 8G + 256`, where
`G=max(render_width/8,1)*max(render_height/8,1)` uses native floor division and
the range reflects two versus four unique early physical sources. Actual
allocation/payload charges use only present, unique observations. This bound
can refuse an oversized capture that would fit after alias elimination.

Existing limits are unchanged: 256 MiB committed readback per frame, 512 MiB
retained GPU readbacks, 512 MiB CPU queue, three pending frames, 320 MiB default
payload quota and 128 GiB extended hard limit. Disk preflight includes its
existing allowance/reserve. Adding observations can therefore refuse a previously
fitting ROI; it never silently drops channels or changes quotas. Packet metadata
and JSON have ordinary CPU object overhead in addition to byte-vector budgets;
no Windows object-size or performance measurement is claimed.
