# Sampling and coordinate contract

## Predictions and falsifiers recorded before implementation

1. **Subtexel representation:** changing only the interpolation fractions to an
   explicit 8-bit lattice changes hard depth gates near a threshold. The change
   depends on phase. Constant fields and exact texel loads must not change. A
   wrong branch that persists across all supported fraction profiles falsifies
   sampling precision as its sufficient explanation.
2. **Allocation extent:** normalizing source addresses by active render extent
   instead of each resource's allocation extent samples a different location
   under dynamic resolution. A nonconstant ramp distinguishes the two. Equal
   active/allocation extents must give identical results.
3. **Crop support:** a crop is an observation window, not a smaller physical
   texture. A bilinear footprint crossing its missing interior edge is
   unsupported even with clamp addressing. True allocation-edge clamping and a
   zero-weight unobserved tap must remain supported. A cropped/full-frame
   comparison with common complete support must agree.
4. **Coordinate convention:** Anchor's `ViewPosition` consumes texel-index
   coordinates and adds 0.5; `ProjectToPixels` returns edge-space coordinates.
   An identity round trip therefore returns `pixel + 0.5`. A named transform
   that subtracts 0.5 closes, while silently treating edge coordinates as texel
   indices does not. This is a source-level diagnostic, not yet a production
   fix: captured motion/projection provenance still determines intended usage.
5. **Arithmetic staging:** four-term float32 weighted accumulation can change a
   constant field by one float32 ULP. A separable lerp has exact finite constant
   identity. The frozen weighted sampler must remain reproducible by name; its
   accumulation order must not be declared the unique sampler implementation.

No thresholds are tuned against the captured GPU output. Deterministic tests
use analytic fields, exhaustive small dimensions and fixed random seeds.

## Source mapping

The frozen tag is `5d7839a930106cf8fe1ba8dbbc6750509e7f26a8`.

| Source | Contract |
|---|---|
| `precompile/FSRDColourTrackStats.hlsl`, `SampleBox` / `SampleBoxDepth` | Four linear samples at `(cell*4 + (1,1)/(3,1)/(1,3)/(3,3)) / GetDimensions()`. This covers all 16 texels of a complete 4x4 cell. Motion XY multiplies active full extent after sampling. |
| `precompile/FSRDColourTrackTrack.hlsl` | Integer neighborhood reads clamp to the quarter grid. History UV is `(cell + motion_pixels/4 + 0.5)/quarter_extent`. UV validity is checked independently of the clamped sampler result. |
| `precompile/FSRDColourTrackApply.hlsl` | Full-resolution pixel centres divide by active full extent before sampling the quarter gain allocation. |
| `precompile/FSRD{,Nrd}PostMotionAnchorStatsRecall.hlsl` | Four taps at offsets 2/6 in each 8x8 cell cover 16 selected texels, not a 64-texel mean. Each input has its own queried allocation. Both share `ViewPosition`/`ProjectToPixels` convention. |
| `precompile/FSRD{,Nrd}PostMotionAnchorGain.hlsl` | Integer reads clamp a 3x3 neighborhood to the grid. |
| `precompile/FSRDPostMotionAnchorApply.hlsl` | Full pixel centres multiply a precomputed reciprocal extent to sample the eighth gain field. D/S are separate textures; gain is shared and alpha is passed through. |
| `FSRDPreprocessor_Dx12.cpp`, `EnsureColourTrack` | Quarter textures are `max(1,width/4)` by `max(1,height/4)`, using integer division. |
| `FSRDNrdPostMotionAnchor_Dx12.h`, `Create`, and `FSRDPostMotionAnchorConstants.h`, `SetSize` | Eighth textures are `max(1,width/8)` by `max(1,height/8)`. Odd remainders do not allocate another cell. |

Paths in this table are below `OptiScaler/shaders/fsrd_preprocess/`.

## Evidence classes

- **Ideal mathematical:** float64 coordinates and interpolation, with explicit
  addressing. This is an analytic reference, not a GPU reference.
- **Source arithmetic emulator:** float32 coordinates and a selectable
  interpolation expression. `weighted_sum` reproduces the frozen portable
  accumulation; `separable_lerp` preserves exact finite constant identity.
- **Observed-device emulator:** the same explicit staging plus nearest-even
  1/256 fraction snapping by default. Other bit counts/tie rules are named
  sensitivity controls. This does not establish other devices' behavior.
- **Documented API envelope:** a conservative convex hull of possible addressed
  texels, with explicit address uncertainty; it does not select an exact
  interpolation implementation.

The [Microsoft Direct3D 11.3 specification](https://microsoft.github.io/DirectX-Specs/d3d/archive/D3D11_3_FunctionalSpec.htm),
sections 7.18.7–9 and 7.18.16, maps normalized coordinates through allocation
size, uses at least eight fractional bits, and applies addressing to individual
taps. It requires constant-field identity and min/max bounded filtering. Exact
filter arithmetic is not uniquely specified. The envelope uses a conservative
one-8-bit-step address radius, rather than claiming exactly eight bits on all
devices. It is conditional on finite float32 normalized coordinates and the
specified 2D mip-zero float texture. Nonfinite payloads have no finite envelope.
[Microsoft's HLSL Load documentation](https://learn.microsoft.com/en-us/windows/win32/direct3dhlsl/dx-graphics-hlsl-to-load)
specifies unfiltered integer texel addressing and zero for true resource
out-of-bounds reads. An absent in-allocation crop sample is not such a read.

## Results

Executed by the `sampling_contract` CPU implementation agent under Python
3.12.14 / NumPy 2.3.5, with no GPU execution. From the candidate directory:

```sh
python -B -m unittest discover -s tests -p 'test_sampling.py' -v
python -B -m unittest discover -s tests -p 'test_coordinates.py' -v
```

Final owned-suite run: **24 sampling tests passed in 0.095 s**, **12 coordinate
tests passed in 0.049 s**, both exit 0. The coordinator's combined run is the
authoritative final bundle run. Seeds are `2026102001` through `2026102005`.
The tests lock analytic inputs rather than learning tolerances from captures.

- The frozen weighted sampler agrees exactly on 226 scalar/RGBA locations
  (113 per shape), including out-of-allocation fractional phases.
- Every impulse in a 4x4 cell contributes exactly 1/16 to Colour Stats. In an
  8x8 Anchor cell exactly 16 of 64 impulse locations contribute 1/16 and 48
  contribute zero. The latter is a reproduced sampling limitation.
- A texture allocation 17x11, active extent 13x7, and ramp `T[y,x]=x+10*y`
  samples at texel coordinates `(3,2)` and `(3.25,2.5)` give observed-profile
  results 23 and 28.25. The deliberately wrong active-extent normalization
  gives 38.375 and 46.55078125.
- The crop tests distinguish true physical texture edges, absent in-allocation
  data, exactly zero weights, and observed-but-inactive allocation padding.
  Integer Load retains uint32 values and signed zero; outside resource reads
  return zero, while unobserved interior reads remain unsupported.
- The source-shaped Anchor identity projection returns a half-pixel shift in
  both axes. This is documented without changing production behavior.
- The independent reviewer supplied an opposite-`F32_MAX` challenge. A float32
  `a+(b-a)*t` emulator overflows its subtraction, while the ideal answer is
  zero. The API envelope rejects that emulator result. A convex-hull API
  invariant does **not** prove that arbitrary shader lerp/weighted-sum
  arithmetic is conformant or bit-exact; near-overflow R32 data remains a
  distinct unsupported exact-hardware assumption. Source FP16-bounded
  radiance cannot trigger this particular float32 overflow.

The first author run found a real emulator bug: clipping raw texel coordinates
to the resource before interpolation erased off-edge fractional arithmetic
and prevented exact frozen weighted-sampler reproduction. The implementation
now preserves phases, bounding only enormous coordinates to protect integer
casts. Two test-harness corrections were also necessary: explicitly broadcast
the expected constant shape for NumPy's assertion utility, and compare
algebraically equivalent float64 operation orders within one machine epsilon.
Neither changed a capture tolerance or reclassified a failed measurement.

## Synthetic phase comparison on one fixed population

`microcase_inputs()` defines five input UVs, identical for every mode. The
texture is float32 `[1,1.04]`; the mathematical sample coordinates are near
`x=[.499,.5,.5001,.501,.502]`, with `y=0`. The comparison below uses the explicit
`weighted_sum` expression. Errors are against float64 interpolation of the
same float32 exported texture and UV bytes. The decision is `sample <= 1.02`.

| CPU model | Population | Max absolute error | p50 absolute error | p99 absolute error | Changed decisions |
|---|---:|---:|---:|---:|---:|
| Source float32 | 5 | 5.7258603192167357e-8 | 5.245590273261769e-8 | 5.7163235851476203e-8 | 0 |
| Observed 8-bit fraction profile | 5 | 7.616527557274821e-5 | 3.999706268587033e-5 | 7.471864242461379e-5 | 2 |

Ideal/source decisions are `[true,true,false,false,false]`; the 8-bit profile
gives `[true,true,true,true,false]`. These are synthetic CPU results, not new
measured GPU branch decisions and not a quality improvement.

## Reusable API and deterministic examples

`SAMPLING_CONTRACT_VERSION = "1.0.0"`. The coordinator records the combined
library version/hash. At this owned-suite handoff, SHA-256:

| File | SHA-256 |
|---|---|
| `numerical_contract/sampling.py` | `60614472a8563099e939714f8271d5bae3fb700df977f755010cbacc4fba1431` |
| `numerical_contract/coordinates.py` | `1e22c8ab15b77101f548d8db706fe8f75e400b5b789f2e74076df16c1019bc44` |

```python
import numpy as np
from numerical_contract.sampling import (
    TextureDomain, bilinear_texel, sample_bilinear,
    documented_bilinear_envelope, microcase_inputs,
)

# Exact frozen arithmetic adapter (normal finite fixture domain).
def frozen_bilinear(v, x, y):
    return bilinear_texel(v, np.stack((x, y), axis=-1), mode="source",
                          interpolation="weighted_sum").require_supported()

# A crop observes only a subregion of a larger physical allocation.
domain = TextureDomain((17, 11), active_extent=(13, 7), crop_origin=(3, 2))
crop = np.ones((3, 3), np.float32)
result = bilinear_texel(crop, np.array([[5, 4], [5.2, 4]]), domain=domain)
assert result.supported.tolist() == [True, False]

# The API envelope is not substituted for a single claimed GPU answer.
inputs = microcase_inputs()
observed = sample_bilinear(inputs["phase_texture"], inputs["phase_uv"],
                          mode="observed", interpolation="weighted_sum")
bounds = documented_bilinear_envelope(inputs["phase_texture"], inputs["phase_uv"])
```

`microcase_inputs()` returns synthetic C-order float32 arrays. Hash these as
`hashlib.sha256(array.astype("<f4").tobytes()).hexdigest()`; shapes, roles and
the little-endian dtype are part of the interface, not implied by the hash.

| Array | Shape | SHA-256 |
|---|---|---|
| `phase_texture` | 1x2 | `52c7169ead1df59dcc8202446f51ab691c0888d00726762d908788939048b6dd` |
| `phase_uv` | 5x2 | `1c4c0e546d3d3036d59cee4b8a36df33c05f60c801327ea8045717558302b85d` |
| `ramp_texture` | 11x17 | `9b32b92e8d27b2b4ea7dd7db4653df35763460a3585a0bcd51d6ccab71f2f9df` |
| `ramp_uv` | 2x2 | `290427c10b86f3134159fc64672a92d4d4f1a170beb1241068984de2dbc438ef` |
| `wrong_active_extent_uv` | 2x2 | `ec4c4355323906f0ed592f07c4e87676b47bfbe5caaecf542c3396291a7cd232` |
| `quarter_impulses` | 16x4x4 | `c2e2500526f9786142a6f24db63779d6b26c8821da4c9e3d79da0118077fd7fd` |
| `eighth_impulses` | 64x8x8 | `818fe6091b008bdd9b0a0bddc98edc6055abeab9f7643888c7a3e7622094dc59` |

## Surgical GPU microcases for the coordinator's GPU_REQUEST

These inputs total 18,236 logical bytes, excluding D3D12 row/heap alignment.
Use the deterministic arrays above, one frame per input case, no history warmup,
no AMD RR, and no game DLL. Outputs are raw sampled float32 bits and uint gate
bits; do not round to an FP16 output in the sampler-isolation pass.

1. **Fraction/gate case.** Upload `phase_texture` to mip-zero
   `DXGI_FORMAT_R32_FLOAT` (2x1); upload `phase_uv` to a
   `StructuredBuffer<float2>` with 8-byte stride. The scalar sample is
   `Texture2D<float>.SampleLevel(linear_clamp, uv[i], 0)`. Also export the
   shader's UV, `uv*GetDimensions()-0.5`, sampled depth via `asuint`, and the
   actual float32 hard-gate result. Expected source weighted-sum sample uint32
   bits are `[1065520652,1065520988,1065521022,1065521324,1065521659]`; expected
   observed-profile bits are
   `[1065520988,1065520988,1065520988,1065520988,1065522298]`.
   These are model predictions to distinguish, not universal GPU assertions.
   The documented conservative finite envelope is `[1, float32(1.04)]` for
   each sample; an answer within it may falsify both exact emulator profiles.
   Mutants: use point instead of linear sampling, or remove the half-texel
   offset when synthesizing UVs. Record sampler state, GPU/driver, compiler,
   target/flags and output bits to identify the profile actually used.
2. **Allocation/active case.** Upload `ramp_texture` as mip-zero R32_FLOAT,
   allocation 17x11, active 13x7. `ramp_uv` addresses texel centres/fractions
   `(3,2)` and `(3.25,2.5)` using the allocation dimensions. Export raw sampled
   float32 and both dimension constants. Expected nearest-8-bit profile:
   `[23,28.25]`, exactly representable in float32. Mutant uses
   `wrong_active_extent_uv` and predicts `[38.375,46.55078125]`. Compare
   float32 bits first; use the documented envelope to classify other device
   precision rather than widening a single output tolerance until it passes.
3. **Source Stats impulse coverage.** For each chronological synthetic impulse,
   upload the single 4x4 or 8x8 R32_FLOAT texture from the corresponding leading
   array index; run the exact source four `SampleLevel` locations then sum*0.25.
   Expected 4x4 outputs: all 16 cases are exactly 0.0625 (`0x3d800000`). Expected
   8x8 outputs: 16 selected positions are 0.0625, 48 positions zero. The selected
   texel axes are `{1,2,5,6}` in both dimensions. Mutant uses four point samples
   or offsets `+.5`; it fails at least one impulse weight. A full 64-sample box
   mean is a different estimator and must not be introduced as a numerical fix.

Host order for each microcase: upload/copy inputs, transition them to
`NON_PIXEL_SHADER_RESOURCE`, clear the output UAV, dispatch with bounds checking,
issue a UAV barrier, transition output to `COPY_SOURCE`, copy to a readback
buffer, wait for the associated fence, then export every output byte. D3D12
row pitch/alignment comes from `GetCopyableFootprints`; input logical strides
remain explicit. Resource/output UAV sizes, descriptor bindings and dispatch
coverage must be checked by the debug layer. Request the same dispatch order
for baseline and each negative mutant. No performance, lifetime or sampler
conformance result has been measured in this CPU handoff.
