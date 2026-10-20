# Native observation packet reader

`observation_capture_reader.py` reads the `fsrd-native-observation-v1` packet
emitted by `FSRDGameTraceSession.cpp`. It accepts a complete capture or a stable
published prefix from a partial capture. It never reads private pending frames,
writes into the capture, or promotes a partial prefix to complete.

From the repository root:

```sh
python research/astra20261020/integration_round2/09-native-observability/observation_capture_reader.py /path/to/capture --output /path/outside/capture/validation.json
python research/astra20261020/integration_round2/09-native-observability/observation_capture_reader_tests.py --output /tmp/astra09-reader
```

The reader exits 0 for a consistent published packet and 1 for a rejected
packet. Without `--output`, it prints the JSON report. The test runner writes
`observation_capture_reader_execution.json` and
`observation_capture_reader_tests.txt`, including source hashes and process
status. It uses only the Python standard library.

## What is checked

- The capture UUID, supported schema and ABI, explicit default-off observation
  request, published ordinal prefix, and complete/partial counts agree.
- Each published `frame.json` equals its manifest row. Each advertised payload
  has the declared byte count and SHA-256. Paths remain inside the capture and
  inside their own frame; traversal and external symlinks are rejected. Duplicate
  JSON keys, nonfinite JSON constants, malformed structures, and boolean numeric
  authority enums are rejected.
- The recorded fence/snapshot proof is complete, and the original provider
  control words agree with frame, render extent, reset, and motion convention.
  Consecutive frame and Streamline indices, recording identity, reset epoch,
  stream, and resource epoch agree within the published prefix.
- Every observation role is explicit. Radiance lobe and provider scale, packed
  normal representation, active/allocation/captured extents, crop origin, and
  surface/image aliases agree. The disk payload is tightly packed; the separately
  recorded D3D12 copy footprint includes its real offset, padded pitch, and CPU
  crop. Anchor sums, when present, include all eight original 32-bit words,
  including high carry words. Missing validity or anchor sums require a reason.
- Raw and selected payloads are compared as original bytes, including opaque
  alpha words. Equality never supplies the host route. Raw authority requires
  the recorded raw route and resource alias; recovery and flat-albedo selections
  remain protected even when their bytes equal raw RR. Native support remains
  invalid with both missing-footprint and missing-correspondence reasons;
  `raw_edit_eligible` therefore remains false even when `raw_authority_valid`
  is true.
- Unobserved title normal/depth/motion, title crop origin, material identity, and
  exposure/modulation remain explicitly unknown. The manifest is rehashed at
  completion so an update during inspection causes rejection and a retry on a
  stable snapshot.

## Evidence limits

The producer has no separately advertised hash for `frame.json`; the reader
compares it to the embedded manifest row and records the file's measured hash.
Payload hashes establish consistency with that manifest. They do not authenticate
the capture's origin or prove that a GPU executed it. A caller can generate a
self-consistent synthetic packet, as the tests explicitly do.

A successful report is byte and metadata consistency, not a native support
certificate, causal reference, image quality result, or Windows/GPU execution
claim. The report records those limits as false fields. It performs no float
conversion of image words and does not assign alpha a radiance, validity, or
hit-distance meaning.

The focused CPU tests cover valid complete and partial packets, equal protected
recovery, unknown authority, and corruption of crop origin, surface and sequence
epochs, scale, lobe, carry payload length, required observations, native support
reasons, edit permission, disk/copy pitches, hashes, frame publication identity,
provider control words, paths, JSON structure, and capture UUID. Test packets
are created in temporary directories and labelled synthetic; they are not real
game captures or replacements for frozen research fixtures.
