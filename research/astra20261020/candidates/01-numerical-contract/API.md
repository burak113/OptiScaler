# Reusable contract API, version 0.1.0

Jobs 02–04 and 08 can use this library immediately. Record both `__version__`
and `API_MANIFEST.json.aggregate_sha256` in downstream results. The aggregate is
SHA-256 of sorted lines `relative_path + NUL + file_sha256 + LF` for every
`numerical_contract/*.py`; it does not depend on timestamps, Python caches or
the manifest's own contents. Sampling also exposes its component version
`SAMPLING_CONTRACT_VERSION = "1.0.0"`.

Add the candidate directory to the import path. The library is NumPy-only;
`anchor_gain.replay_calibration` and the separate calibration scripts additionally
read the immutable repository fixtures. Public numerical operations do not read
those fixtures or monkeypatch the frozen references.

## Evidence and dtype rules

Every operation must name the model that gives its result. `ideal` sampling uses
float64 on the supplied bytes. `source` uses selected float32 staging.
`observed` adds an explicit fraction lattice, default nearest-even 8 bits.
`documented_bilinear_envelope` gives a conservative API addressing/tap envelope;
it does not select any one of these arithmetic implementations. RNE and RTZ
stores are numerical models, not a blanket assertion about a graphics device.

Arrays use `[..., channel]`. Spatial arrays use `[y,x,...]`, extents/origins/UV
use `(x,y)`. Returned stored values are binary16-expanded float32, except APIs
whose name explicitly requests integer bits. FP16 preimages are inclusive sets
of **binary32 inputs**, not real-valued intervals with unspecified endpoints.
Integer loads retain integer payloads. Nonfinite/undefined domains are rejected
where the source has no established portable interpretation. RGB sanitization,
FP16 storage, integer conversion and alpha handling are separate operations.

## Operation map

| Module / operation | Contract and useful failure behavior |
|---|---|
| `storage.fp16_bits`, `store_fp16` | `rounding='rne'/'rtz'`, explicit finite overflow and subnormal models; signed zero retained; canonical model NaNs |
| `storage.sanitize_radiance` | Per-lane nonfinite to zero, finite clamp to `[0,65500]`, followed by a separately selected store |
| `storage.fp16_preimage_f32` | Exact inclusive binary32 endpoints for each stored half; `contains` respects signed zero |
| `arithmetic.f32_add/sub/mul/div`, `dot_f32` | Named binary32 staging, without silently inserting half stores |
| `arithmetic.mad_separate`, `mad_fused` | Separate rounding or an exact dyadic fused result; float64 is not used as a substitute for exact FMA |
| `arithmetic.to_uint32`, `to_int32` | Truncating conversion only in the defined finite representable domain |
| `arithmetic.apply_anchor_lobes` | Separate D/S, per-RGB-lane sanitizer, shared gain, finite alpha bits, OFF ignores unused input; enabled nonfinite alpha is unsupported |
| `encoding.pack_normal11`, `unpack_normal11` | `qx*32+qy`, `qx=0..63`, `qy=0..31`; exact 2,048-code half closure |
| `encoding.octahedral_encode/decode` | Source fold signs and float32 normalization; zero/nonfinite encode is rejected or explicitly marked NaN |
| `encoding.pack_normal16_old` | Deliberately broken normalized legacy control; never use as the new encoding |
| `sampling.TextureDomain` | Allocation, active extent/origin and observation crop are independent |
| `sampling.load`, `sample_point`, `sample_bilinear`, `bilinear_texel` | Explicit addressing/profile; `SampleResult` separates observed support, active support and true allocation bounds |
| `sampling.documented_bilinear_envelope` | Conservative finite mip-zero 2D filter bounds; unsupported crop taps remain unsupported |
| `coordinates.grid_extent`, coordinate/projection helpers | Floor quarter/eighth grids with minimum 1; texel-centre, edge-space and motion conventions remain named |
| `fixedpoint.FrameSums` | Exact native low/high atomic words, cap-16 physical units, count, all 32 reset bytes |
| `fixedpoint.frame_sum_bounds` | Conditional totals/ratio intervals from stored half cells and a fixed mask; exact request raises for nonsingleton totals |
| `anchor_gain.anchor_gain_unstored` | Selected source-shaped current Gain expression before output storage, plus numerator/denominator/coverage/branch intermediates |
| `anchor_gain.anchor_gain` | Exactly one declared output store applied to the unrounded Gain |
| `guards.colour_history_valid` | Frozen source-shaped inclusive signed-depth predicate, including the diagnosed infinity behavior |
| `guards.colour_history_valid_finite` | Separate proposed adapter predicate; not silently substituted into the frozen reference |
| `guards.require_unique_observable` | Different admissible witnesses raise `NonIdentifiableError`; agreement of a finite sample does not prove global uniqueness |

## Storage boundary and impossible exact reconstruction

```python
import numpy as np
from numerical_contract.storage import (
    store_fp16, fp16_preimage_f32, sanitize_radiance, NonIdentifiableError,
)
from numerical_contract.fixedpoint import FrameSums, frame_sum_bounds

x = np.float32(1 + 2**-11)
assert store_fp16(x, rounding="rne") == np.float32(1)
assert store_fp16(x, rounding="rtz") == np.float32(1)
# A different halfway has odd lower mantissa: RNE goes up, RTZ goes down.
y = np.float32(1 + 3 * 2**-11)
assert store_fp16(y, rounding="rne") != store_fp16(y, rounding="rtz")
assert sanitize_radiance(np.array([np.inf, -1, 70000], np.float32)).tolist() == [0, 0, 65500]

preimage = fp16_preimage_f32(np.float32(1), rounding="rtz")
assert preimage.contains(preimage.lower)
assert preimage.contains(preimage.upper)
assert preimage.upper > preimage.lower

current = np.ones((1, 1), np.float32)
recalled = np.full((1, 1), .5, np.float32)
mask = np.ones((1, 1), bool)  # Fix from baseline evidence before modifying data.
bounds = frame_sum_bounds(current, recalled, mask, rounding="rtz")
try:
    bounds.require_exact_totals()
except NonIdentifiableError:
    pass  # Expected: identical exported cells allow different atomic totals.
else:
    raise AssertionError("an impossible exact request was accepted")

sums = FrameSums()
sums.add(current, recalled, support=mask)
assert len(sums.to_bytes()) == 32
sums.reset()
assert sums.to_bytes() == bytes(32)
```

When the actual GPU buffer is available, use `FrameSums.from_bytes(raw32)`.
Never replace that observation by `FrameSums.add(stored_stats, stored_recall)`
and label the latter exact pre-store totals. Native 16.16 totals and the combined
path's 1/1024 uint32 totals are different source contracts.

## Crop support and allocation-sized UV

```python
import numpy as np
from numerical_contract.sampling import TextureDomain, bilinear_texel

domain = TextureDomain((17, 11), active_extent=(13, 7), crop_origin=(3, 2))
crop = np.ones((3, 3), np.float32)  # Observes x=3..5, y=2..4.
sample = bilinear_texel(crop, np.array([[5, 4], [5.2, 4]]), domain=domain)
assert sample.supported.tolist() == [True, False]
```

The second footprint needs an unobserved positive-weight texel inside the
allocation. Texture clamp addressing cannot turn that missing observation into
valid history. Modes may snap a tiny missing weight to zero differently; compare
them on an immutable common support, not each candidate's newly convenient mask.

To reproduce the frozen Colour sampler's selected operation order:

```python
def frozen_bilinear(values, x, y):
    return bilinear_texel(values, np.stack((x, y), axis=-1), mode="source",
                          interpolation="weighted_sum").require_supported()
```

Use `interpolation='separable_lerp'` for the separately named constant-preserving
source expression. Opposite extreme R32 values can overflow that expression;
its result is not a universal implementation of the documented filter envelope.

For cropped motion history the mapping is:

`previous_local = current_local + current_crop_origin + motion_uv * original_render_extent - previous_crop_origin`.

There is no previous fixture frame at the beginning of a clip. Anchor's current
source `ViewPosition`/`ProjectToPixels` round trip returns index `p+0.5`; the
library names this distinction and supplies explicit transforms. It does not
invent the missing capture convention needed to justify a production offset.

## Gain before the actual output store

```python
from numerical_contract.anchor_gain import anchor_gain_unstored

# stats/recalled are actual stored HxWx4 fields; count/measured/ratio must have
# their own observed or explicitly bounded provenance.
def two_gain_store_predictions(stats, recalled, k, ratio, count, measured):
    model = anchor_gain_unstored(stats, recalled, k, ratio,
        frame_count=count, frame_measured=measured, policy="native")
    return model.stored("rne"), model.stored("rtz"), model
```

This models the current Gain observable and its branch intermediates. It does
not reconstruct key-ring writes, missing recall history, native atomics, DXC
contraction or GPU reciprocal/transcendental instructions. Both source `exp`
and the inspected DXIL `exp2` lowering are selectable models. Preserve unresolved
branch intervals before interpreting an apparently exact final image.

The examples are small usage illustrations; the acceptance runner exercises the
much broader exhaustive, property, fixture and independent adversarial tests.
