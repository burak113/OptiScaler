# Native observation contract, version 1

Implementation: `OptiScaler/shaders/fsrd_preprocess/FSRDNrdObservationContract.h`.
This is portable C++ metadata and byte handling used by the opt-in host capture
path. It performs no allocation, GPU work, logging, filter operation or history
update. The structs are an in-process interface; write their named fields to
the packet, never `sizeof(struct)` bytes. C++ padding is not a file ABI.

## What is observed

An observation is the resource's original copied words at the stated recording
point. It is not a reconstruction from decoded/sanitized data, a material label,
a clean lighting reference, or a causal explanation. In particular, the
bridge-owned physical lobe inputs are already converted native signals. Their
pre-anchor/pre-scale words can be captured exactly without establishing the
unobserved title's upstream exposure or material modulation contract.

The native host must distinguish the following roles explicitly:

| `Role` | Required word representation | Meaning |
|---|---|---|
| `PhysicalSource` | RGBA binary16 | Owned physical signal before input-anchor and provider scaling. |
| `EffectivePhysical` | RGBA binary16 | Effective input after optional anchor, before turn/scaling. It is the exact provider lighting only when subsequent input filters are inactive. |
| `RawRR` | RGBA binary16 | Provider output after documented scale restoration, before selection/recovery. |
| `SelectedOutput` | RGBA binary16 | Actual host-selected resource; selection authority is separate metadata. |
| `NativeNormalRoughness` | R10G10B10A2 UNORM words | Original title packed guide, only if actually captured. The converted guide must not be relabelled this way. |
| `ProviderNormalRoughness` | R10G10B10A2 UNORM words | A bridge-owned converted/possibly modified guide, with observation phase named separately. |
| `RawDepth` / `ProviderDepth` | R32 binary32 words | Original unmodified depth / actual converted depth, respectively. A finite sanitized provider sample cannot prove native validity. |
| `NativeMotion` / `ProviderMotion` | RG16, RGBA16 or RGBA32 binary float words | Distinct native/converted/final provider observation, with explicit coordinate convention. |
| `AnchorSums` | Eight little-endian uint32 words | Original 32-byte pre-reset sum buffer, including both carry words and padding. |
| `EncodingFlag` | R32 uint word | Original flag word only; not inferred from signal appearance. |
| `GeometryValidity` | R8 uint or R32 uint words | Existing raw validity classification, without changing depth values. |

Missing title-native guides, original depth, original motion conventions,
native crop offsets, original atomics or recalled keys must remain missing or
unknown. A converted texture, recomputed sum, or observed equality cannot fill
that gap. `Availability` distinguishes `Unknown`, `Present`, `Missing`, and
`Invalid`; `unavailableReason` preserves why a role is unavailable. `ValidateSurface`
rejects an absent/unknown/invalid role for any consumer expecting usable data.

## Layout and domains

Each `Surface` names its role, lobe, recording-local `resourceId`, `Layout`,
`Scale`, and `Stamp`.

`Layout` retains the numerical DXGI format; a separate `Encoding` declares how
to interpret its words. These must agree. `allocation` is the underlying source
texture's allocation extent, `active` is the logical render extent, `captured`
is the captured rectangle's extent, and `cropOrigin` is the rectangle's integer
origin in that active render coordinate system. Native-title source-coordinate
origins need their own observed provenance; zero is not an unknown marker.

`byteOffset` is the first pixel's offset in the mapped/captured buffer,
`rowPitch` is its physical stride, `rowBytes` is the logical copied pixel width,
and `payloadBytes` is the available backing buffer length. The validator uses
division-based bounds checks to prevent unsigned overflow. It accepts distinct
allocations and row pitches for corresponding surfaces, while requiring their
active/captured extents and crop origins to agree. Production D3D copy alignment
requirements are checked by the host, not substituted by this portable parser.

If a file writer stores tightly packed rows, its stored-payload layout must
describe that packed file and retain the original GPU copy footprint separately.
Do not label packed exported bytes with the GPU readback pitch or offset.
`CopyWords` and `ReadPixelWords` never decode float values. The full payload or
the exact selected pixel words, including arbitrary alpha NaNs and negative
zero, are preserved without float conversion. Padding can be retained in the
readback representation; it is not asserted to be initialized texture content.

`Stamp` contains `{streamId, frame, resetEpoch, resourceEpoch, known}`. Frame zero
is legal. The explicit `known == 1` and nonzero stream identity are required.
`CompareStamp` rejects a different stream, frame, reset epoch or resource epoch;
equal frame numbers across contexts are not interchangeable. The host owns epoch
generation, freezes the actual reset decision, and increments resource generation
on the relevant recreated context. Resource IDs are opaque recording-local
identities; a reused pointer address is not persistent lineage.

## D/S scale and alpha

`Lobe::Diffuse` and `Lobe::Specular` are not inferred from array order.
`Scale::providerMultiplier` records the actual selected dispatch multiplier,
including diffuse 16 and specular 256 when that configuration is in force.
`storedMultiplier` records the multiplier still present in the observed words.
Post-restore physical-unit observations use one. Both must be known validated
powers of two in the native host's existing range 1..4096. Comparing two
radiance observations with different lobes or multipliers fails closed.

The existing host scales inputs in place and divides again on restoration.
That round trip can lose original half bits. Therefore original physical input
observations must be copied **before scaling**, and cannot be replaced by the
restored input snapshot merely because its nominal units match. The ABI does
not assert numerical round-trip identity. Radiance alpha is opaque storage in
all operations; no finite test, normalization, hit-distance inference or RGBA
arithmetic is performed on it.

## Selection authority

`SelectionWitness` is frozen by the host at the actual selected-resource
assignment. It contains the exact `SelectionPath`, stamp, lobe, raw resource
identity and selected resource identity. `SelectionPath` distinguishes `RawRR`,
`LobeRecovery`, `FlatAlbedo`, `ProtectedNative`, and `Unknown`.

`SelectionAuthority` returns raw authority only for an explicit `RawRR` route
whose actual resource identities alias. Recovery/flat/native routes are protected
for the whole lobe because the current host does not expose a complete per-pixel
selection map. A recovery pass that happened to write identical words still owns
that selected result. Unknown route/identity/stamp remains unknown.

`ValidateRawAuthority` is the consumer check: it additionally requires a valid
raw/selected pair, matching stamp/domain/lobe/scale, the recorded resource IDs,
and a separately supplied `EqualityGuard::EqualWords`. Equality is an extra
guard after authority; it can never create authority. The guard must compare
all relevant words, including opaque alpha, or a stricter full-payload identity
where appropriate. `Unknown` equality denies the consumer.

This is a trusted host ABI, not a cryptographic proof. A caller could lie in a
public struct. The reviewed host integration must create the witness exclusively
from its real selection branches. The deliberately broken CPU implementation
that creates authority from equality is rejected by these tests.

## Diagnostic interpretation

`DecodeNormalRoughness` uses the original packed RG 10-bit octahedral channels,
B 10-bit roughness, and A two-bit category. The category is an observed numeric
code, not proof of vegetation or a semantic material class. `UnpackNormal11`
separately decodes the native cell-history integer 6+5-bit payload 0..2047; a
normalized legacy 8+8-bit payload cannot substitute for it.

`ReadAnchorSums` requires exactly eight original little-endian uint32 words.
`ComposeCarryWords` combines low and high words using integer shifts; FP16 grid
values cannot recover missing high/low sum words. A missing original sum buffer
stays missing. `ValidateDepth` requires finite, nonzero depth of the explicitly
declared sign; zero/NaN/Inf is not sanitized into support.

`PreviousPixel` supports only the frozen fixture convention: full-render UV,
previous-minus-current, integer pixel-centre indexing, and already-encoded
jitter with no extra delta. It computes:

```text
previous_local = current_local + current_crop_origin - previous_crop_origin
                 + motion_uv * full_render_extent
```

`Reason::None` means only that this arithmetic has a supported convention and
finite input. It does **not** establish previous-crop availability, chronological
history, or actual surface correspondence. A history/support consumer must check
all those independently; the support ABI is a separate fail-closed interface.

## Executed CPU falsification

```text
python research/astra20261020/integration_round2/09-native-observability/observation_checks.py --output /tmp/astra09-observation
```

The runner compiles the actual production header with C++20 and
`-Wall -Wextra -Werror -pedantic -O2`, then runs deterministic cases and four
deliberately broken implementations. The observed local run has **204 checks,
zero failures** for the real implementation. Each broken authority/origin/carry/
packed-normal implementation exits 1 with explicit assertion failures. That is
a successful detection of incorrect implementations, not a failing candidate.

The test selects one immutable BASE-mask probe per original chronological frame:
bottle frames 180..186 and foliage frames 43..65. It uses the original clip loader
and original job07 decoder, reads NPZ files with `allow_pickle=False`, preserves
all inputs, and verifies original file hashes afterward. No new history is
invented for the first frame; original missing host-selection authority stays
unknown even when raw/selected captured values happen to match. The emitted
receipt records exact compiler command, platform, source/fixture hashes and all
statuses. This is portable CPU compilation and execution, not a Windows host
build, D3D validation run, GPU capture or image-quality acceptance.
