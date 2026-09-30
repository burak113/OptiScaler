# Conversion-only rotating-camera conformance

No GPU was used. `analyze.py` ran CPU closure assertions for both roughness values
and writes the immutable `results.json` plus four authenticated fixture NPZs.
Current world-to-view is identity; previous world-to-view is row-vector Y rotation
by +0.02 radians, around the same camera origin. The world surface is an infinite
plane Z=10. The constant unit shading normal `[.2,.1,-sqrt(.95)]` represents a
constant material normal map; it does not define the plane's geometric slope.
No shader reconstructs material normals from depth in this fixture.

Matrices are first rounded to float32 and the analytic reference uses those
consumed values. Native perspective and HLSL inverse projection have compatible
row-major bytes / default HLSL column-major interpretation. The small inverse
closure error, below 5e-7 world units, is recorded rather than treated as exact.

For the proposed root GPU experiment, authenticate the NPZ and source hashes in
`results.json`, then call `fsrd_alpha_common.convert` with the saved arrays and
saved overrides, current production `directory=t.PRE`, and `kernel='auto'`.
Run only roughness .1, matrices matched/identity, strengths 0/1: four conversion
dispatches. Actual source selection chooses `FSRDInputConv` at strength0 and
`FSRDInputConvAdditive` at strength1. Record selected shader identity per call.
Do not force `kernel='original'` for the strength1 factorial arm.

```python
# Specification only; this package itself does not call GPU utilities.
f = np.load(payload_path)
row = next(v for v in report['payloads'] if v['path'] == str(payload_path))
packed = convert(f['raw'], f['diff'], f['spec'], strength,
                 depth=f['depth'], normals=f['normals'],
                 roughness=f['roughness'], motion=f['motion'],
                 overrides=row['overrides'], kernel='auto', directory=t.PRE)
```

Every pixel in packed[2] has primary MV XY equal to PreviousUV-CurrentUV.
Expected physical MVZ is `(current_world_point @ previous_view).z - current_z`.
The supplied MVXY is identical in both matrix arms; only inverse projection is
changed. Matched MVZ spans [-.1852962,.1812967]; identity inverse projection
produces [-.3988483,.3948488]. Identity MVZ error RMS is .1242614, maximum .2135521.
Use the all-pixel FP16 tolerance recorded in `results.json`; validity alpha is
exactly1. Some correspondences lie outside the previous viewport but still have
finite valid motion. This is not a disocclusion or game-history experiment.

Current normals must remain unchanged by previous-camera rotation. With current
View=identity, the view-space-normal flag does **not** independently validate a
nonidentity current-view normal transform. Low/high roughness must have identical
primary motion; indirect specular alpha is10 at .1 and0 at .55 because of the
shader's specularTracking gate. Direct diffuse alpha is65504 in both.

This counterexample establishes a moving-camera input-contract sensitivity. It
does not explain earlier static same-input native context divergence, establish
native RR behavior, or demonstrate a game stain/wave solution.
