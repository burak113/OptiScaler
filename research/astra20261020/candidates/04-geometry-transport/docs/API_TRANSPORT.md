# Portable coordinate and support API

This API is a CPU mathematical reference for jobs 02, 03, 06 and 07. It uses
Python 3.11+ and NumPy, imports no Windows modules and executes no GPU work.
Import `transport.py` and `history.py` from this candidate directory. The API is
independent of every other candidate's uncommitted files.

## Coordinate convention

All public sample coordinates use **pixel-edge coordinates**: the centre of
texel `(i,j)` is `(i+0.5,j+0.5)`. The left and upper render edges are `(0,0)`;
Y increases downward. Full active-render UV is `pixel_xy / active_extent`.
An array extent is always `(width,height)` although array shape is `(height,width)`.

Matrices named `view_col` and `projection_col` perform column-vector mathematics:

```text
view_h = view_col @ world_h
clip_h = projection_col @ view_h
```

NumPy C-order versus Fortran-order storage does not alter this equation. For an
external row-vector mathematical transform `p_row @ M_row`, convert the equation
using `M_col = M_row.T`. Do not transpose solely because bytes are row-major.
The source `Desc` convention and its native wrapper transpose belong at that
specific ABI boundary; they must not be copied blindly into this API.

`Camera.raster_shift_px` has one explicit sign: a positive value moves the
projected raster sample in the positive screen axis. Projection **adds** it and
unprojection **subtracts** it. If a consumer calls the camera's *sampling offset*
"jitter" with the opposite sign, pass `raster_shift_px = -sampling_offset_px`.
Do not pass a raster shift here when it is already embedded in the projection
matrix. Actual native camera/motion jitter parity remains a requested GPU witness.

`perspective_col` generates a perspective projection with D3D device depth
`[0,1]`. This device depth is distinct from the signed linear view Z accepted by
`unproject_pixels`: LH uses positive forward Z; RH uses negative forward Z.
The constructor accepts physical pixel aspect independently of raster W/H.

## Types and executable entry points

| Symbol | Inputs | Return and support contract |
|---|---|---|
| `RasterDomain(active_extent, allocation_extent=None, crop_origin=(0,0), crop_extent=None)` | Original full active render, original texture allocation, observed integer crop | Validates positive sizes and crop within active render; allocation is never substituted for active extent |
| `Camera(view_col, projection_col, active_extent, handedness="LH", raster_shift_px=(0,0))` | Finite 4x4 column transforms, full render W/H | Owns immutable copies of matrices; projection meaning is explicit |
| `pixel_centres(extent)` | W/H | H×W×2 float64 edge coordinates |
| `project_world(world_xyz, camera)` | …×3 world points | `ProjectionResult(pixel_xy, view_depth, valid)`; validity means finite front-facing geometry, **not** active viewport/ROI visibility |
| `unproject_pixels(pixel_xy, signed_view_depth, camera)` | …×2 full render coordinates, broadcast signed view Z | `(world_xyz, valid)`; zero/nonfinite/wrong-sign depths are invalid and output payload is zero |
| `surface_motion(current_world, previous_world, current_camera, previous_camera)` | Corresponding world points; moving objects require different positions | `(motion_uv, valid)`; UV is previous active UV minus current active UV, including raster shift |
| `motion_to_previous(local_xy, motion_uv, current_domain, previous_domain, current_raster_shift_px=(0,0), previous_raster_shift_px=(0,0), motion_includes_raster_shift=True)` | Current local crop coordinates and full render UV displacement | Previous **local** crop coordinates; does not invent support |
| `bilinear_sample(image, local_edge_xy, known_mask=None)` | H×W or H×W×C, …×2 local coordinates, optional H×W boolean mask | `SampleResult(values, valid, coverage)`; every nonzero tap must be inside and known, otherwise `valid=False` and value zero |
| `correspondence_support(expected_depth_abs, sampled_depth_abs, current_normal, previous_normal, known, depth_relative=.02, normal_cosine=.95)` | Positive absolute depths, normals in the **same** space, boolean support | Boolean geometry match; invalid normals/depths reject; no colour argument exists |
| `visibility_order(expected_depth_abs, observed_depth_abs, known, relative_tolerance=.02)` | Positive depths and boolean known mask | uint8: 0 unknown; 1 same depth; 2 previous geometry is nearer/occludes correspondence; 3 query point is in front of previous depth |
| `native_key_depth(signed_view_depth)` | Signed cell-average view Z | Absolute stored native key depth, matching native Gain capture |
| `native_recall_depth_match(stored_abs, clip_w, key_p32, relative_tolerance=.02)` | Actual stored key, transformed clip W, key projection P32 | Native absolute expected depth comparison; no claimed raw-key replay |
| `native_shader_view_position(pixel_argument, stored_depth, projection_col, extent)` | Exact StatsRecall `centre=8*cell+4` argument | Frozen source arithmetic, including extra `+0.5`; deliberately separate from clean unprojection |
| `construct_virtual_point(surface_world, virtual_direction_world, hit_distance, observation_role=...)` | Physically justified virtual direction and distance | `(point, valid)`; only role `reflection_distance` is accepted |
| `mirror_virtual_point(real_point, plane_normal, plane_point)` | Analytic planar mirror geometry | Reflected virtual image point; used as independent analytic truth |
| `Plane(normal, offset, surface_id, lower=(-inf,...), upper=(inf,...))` | Plane `normal·world + offset = 0`, optional finite bounds | Analytic plane or strip specification |
| `render_planes(camera, planes, pixel_xy=None)` | Camera and independent world geometry | World position, signed depth, world normal, surface ID and known mask from explicit ray/plane intersection and nearest-hit selection |

The unprojection implementation explicitly supports non-sheared perspective
`clip.w = P32 * view.z`, including P02/P12 lens offsets. Unsupported orthographic
or skewed clip-W conventions raise an error rather than receiving an approximate
inverse. Projection validity must always be combined with the destination's
observation support. `visibility_order == 3` alone is not proof of disocclusion:
current/previous object identity and the actual visibility sequence are needed.

All known/support masks must be boolean. Numeric masks, including NaN values,
raise `ValueError`; a floating NaN must never silently become true. Geometric
tolerances must be finite and nonnegative. A guide containing zero or nonfinite
depth or a zero/nonfinite normal has no correspondence support. Sky is unknown
for this finite-surface model. Missing hit distance is not a zero-distance valid
reflection. Normal sign/space comes from the guide producer, not corrected RGB.
These strict support rules describe the generic API; the explicitly named
frozen-native arithmetic witness below intentionally preserves its source
tolerance-floor corner case rather than silently hardening baseline semantics.

## Crops, allocation and dynamic resolution

For the frozen clips, motion is previous-minus-current **full-render UV**. At a
fixed render extent the implementation gives exactly:

```text
previous_local = current_local + current_crop_origin
               + motion_uv * render_extent - previous_crop_origin
```

For an explicitly endpoint-normalized DRS contract:

```text
current_uv = (current_local + current_crop_origin) / current_active_extent
previous_local = (current_uv + motion_uv) * previous_active_extent
                 - previous_crop_origin
```

This generalization is a declared API convention; it is not evidence that a
particular capture encoded motion that way during DRS. The fixture provenance
and camera witnesses take precedence. `RasterDomain.allocation_uv` is only for
addressing the original SRV, never for normalizing motion. The physical cropped
NPZ array is addressed with local coordinates and its own array shape.

When motion excludes raster shift, `motion_to_previous` first subtracts current
shift, applies the endpoint equation, and adds previous shift once. Canonical
bridge motion that already includes jitter must use the default
`motion_includes_raster_shift=True`.

## Strict observation support

An observed texel centre at `(0.5,0.5)` is valid even though the mathematical
four-tap construction includes zero-weight neighbours outside the crop. A query
at `(0.1,0.5)` is invalid because one **nonzero** weight is outside. A query beyond
the crop is never clamped back to its nearest observed texel. The index clipping
inside `bilinear_sample` exists solely to prevent an illegal NumPy load; the raw
inside mask controls weights and validity.

`coverage` is the sum of observed bilinear weight, useful for diagnosis. A partial
weight does not silently become a full sample through renormalization. Consumers
that intentionally accept partial weighting must define a separate estimator
and evaluation denominator. Neither this helper nor a matching average depth
proves that a coarse cell was homogeneous. Jobs using coarse values must carry
their own independently justified coverage/purity evidence.

The sampler uses ideal float64 arithmetic. It does not model the hardware's
fraction quantization. Near a hard gate, an actual D3D sampled-value witness is
required; CPU equality is not GPU sampler parity.

## Source-level native witnesses

At the frozen baseline, StatsRecall uses four box taps at edge coordinates
`8*cell + {2,6}` and calls `ViewPosition` with their mean `8*cell+4`. That function
adds `0.5` again while `ProjectToPixels` returns edge coordinates. The executable
identity-camera witness consequently projects the argument to `(x+0.5,y+0.5)`.
The clean public coordinate API returns `(x,y)`. This is a deterministic source
arithmetic distinction, separate from jitter, noise and estimator quality. It
is **not** an executed GPU quality result or a production patch.

Native Gain stores `abs(cell.depth)`; native recall compares with
`abs(clip.w/keyP32)`. RH signed key storage is a deliberately failing control.
The frozen comparison's tolerance floor is `.02*max(expected,.001)`. It can
therefore accept stored depth zero for an extremely small positive expected
depth, for example `clip.w=1.1e-6, keyP32=1`; the witness preserves this corner
case. The generic correspondence API rejects zero depth. Native recall matching
by itself also does not establish near/far frustum or complete ROI support.
Combined Gain's different signed capture behavior must not be described as the
native rule. The supplied fixtures contain already-recalled fields, not the raw
six-slice keys needed to measure a changed key selector on captured history.

## Surface versus virtual reflection transport

`surface_motion` follows a surface point and its actual previous object position.
A reflected feature on a planar mirror instead follows the virtual image of the
reflected object. The included analytic test constructs a mirror at Z=5 and a
reflected point with virtual depth Z=8. With camera translation, the same surface
point's parallax is `8/5` times virtual-point parallax. This separates the two
mechanisms without a noisy colour alignment score.

The test can reconstruct the virtual point by continuing the camera-to-surface
ray behind the mirror by the physical reflection distance. This construction
is justified for that analytic planar-mirror scene. It is not asserted for every
rough/specular/transparent input. The captured alpha role and any virtual ray
direction must be documented before reuse; diffuse hit distance or a generic
surface property is rejected by the public constructor.

## History publication contract

`HistoryModel` is a small executable **conservative** model, not a replacement for
native host ownership or a claim that the current host was tested. The six slots
refer to one physical resource bank. Methods are:

```python
model.begin_frame(frame, (width, height), enabled=True,
                  previous_camera_valid=True, explicit_reset=False, camera_cut=False)
token = model.schedule_capture({"camera": immutable_camera_metadata, "frame": frame})
model.submit(token, fence)
model.complete(observed_completed_fence)
model.publish(token)
```

The required publication condition is:

```text
published(token) implies submitted(token)
                     and completed_fence >= token.fence
                     and token.epoch == current_epoch
                     and token is the newest physical owner of token.slot
```

Scheduling reserves a slot and retires its old logical key conservatively, but
does not publish new camera metadata. Submitted and completed remain separate
states. `valid_keys()` returns copies with physical slot, frame, epoch and camera
payload from the **same capture**, sorted by capture frame rather than slot order.
This preserves correspondence after the six-slot ring wraps.

Explicit reset, camera cut, invalid previous camera, frame gap, active-extent
change, option toggle, or unsubmitted/discarded recording invalidates the logical
generation. Old GPU completion cannot resurrect old metadata. Crucially, a
logical reset does **not** free physical ownership: a slot whose prior fence has
not completed cannot be scheduled again, even from an old generation. If the
native integration allocates a new resource bank after reset, it must retain both
banks and their owners until each relevant fence completes; that separate-bank
optimization is outside this model.

An actual integration may safely let ordered GPU consumers read a key before the
CPU observes completion only if it proves the relevant queue order/UAV barrier
or explicit fence wait. That proof must accompany the key metadata and resource
identity. CPU command-list recording alone provides no publication proof.
Job08 owns the actual D3D12 lifetime implementation.

## Verification

From the repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s research/astra20261020/candidates/04-geometry-transport/tests -p 'test_transport.py' -v
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s research/astra20261020/candidates/04-geometry-transport/tests -p 'test_history.py' -v
PYTHONDONTWRITEBYTECODE=1 python research/astra20261020/candidates/04-geometry-transport/transport_experiment.py
```

Independent mutation tests are supplied separately by the skeptical reviewer.
The owned geometry tests cover signed LH/RH roundtrips; odd/one-pixel/aspect
extents; analytic translation and rotation; constant, sloped and intersecting
planes; a moving one-pixel strip and disocclusion; moving/partial crops; explicit
DRS and allocation separation; invalid guide support; virtual reflection motion;
native half-pixel and absolute-depth witnesses. The chronological history tests
cover submission states, physical ring wrap, gap/reset/cut/DRS/toggle, unsubmitted
graphs, stale completion, and late publication over a newer slot owner.

`transport_experiment.run(output_directory)` writes `transport_metrics.json`.
It records 2,464 geometric correspondences against an independent scalar-component
camera-pose oracle, 4,096 subpixel-phase roundtrips, the exact-support one-pixel
disocclusion experiment, native arithmetic witnesses and virtual reflection
parallax. Its chronological event receipt distinguishes each scheduling,
submission, completion and publication step through reset, gap, DRS, toggle,
camera-cut, invalid-camera and discarded/unsubmitted-graph cases. These are
deterministic generated analytic measurements; no recorded key textures, actual
fences, AMD RR or game frames are executed by this script.
