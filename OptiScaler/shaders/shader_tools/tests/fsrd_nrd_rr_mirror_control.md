# V4 exact-mirror control

This is a new synthetic control, not an edit or retrospective relabeling of V1
or V2. The old64-frame camera table is reused byte-exactly, but all primary and
secondary geometry/radiance/reference/motion/reveal payloads are rebuilt. No
production shader, SDK setting, Config key or signal mode is changed.

The actual R10 oct(512,512) normal is decoded and used for both primary planes,
the rectangle's tangent basis and the reflected ray. Normal.B is exactly0 in
the mirror case. Every secondary ray picks the nearest positive intersection
among the infinite background plane, finite translating rectangle, and fixed
emitter plane worldZ+3. The primary surface selfhit is excluded. The rectangle's
front is a primary mirror; its rear emits a declared warm spatial pattern,
providing physically defined one-bounce light when a background reflection hits
it before the distant environment. Environment emission is static; rectangle
emission is stable in object-local coordinates.

The specular reference is exact point-sampled perfect-mirror, unit-reflectance
one-bounce emitted radiance. Diffuse is a separate analytic point-light lobe
with cosine, inverse-square falloff and full shadow visibility. White guides
are fixed per-lobe normalization; this is not a claim that adding both unit
lobes is an energy-conserving material. No rough-GGX integral or finite-area
pixel-filtering ground truth is claimed. The source seed and independent
mean-one noise distribution match V1; no truth/annotation influences admission.

Views:

- `mirror-r0`: decoded-normal geometry, exact zero roughness, actual nearest
  reflected distance, valid primary-surface motion.
- `negative-r012`: only normal.B changes to123/1023. The lighting remains the
  exact mirror sample, so this is an intentional model-mismatch negative,
  never advertised as a rough-GGX quality reference.
- `diagnostic-reflected-mv`: roughness0, but previous reflected-feature UV/Z is
  supplied only where exact previous mirror and secondary visibility agree;
  primary motion is retained elsewhere. This intentionally departs from the
  SDK primary-surface MV contract. It is an isolated diagnostic, not a
  production candidate or proof of the private SDK virtual-hit formula.

All candidates have identical noisy RGB, A, normal.RG/material.A, depth,
albedos, camera, references and noise. The first view uses SDK-required
primary-material previous-current XY+jitter once and signed viewZ delta.
References, visibility, moving-object correspondence, age0..32 reveal cohorts
and stale-light references are rebuilt with the new exact geometry. Specular A
is the positive finite nearest reflected-ray length. DD A is a positive actual
point-light distance, allowed as its active metric. No0/negative/65504 remapping
or invented native-hit interpretation occurs.

`test_fsrd_nrd_rr_mirror_oracle.py` checks the integer-ratio normal and tangent
basis, scalar plane/rectangle nearest hit, selfhit exclusion, reflection law,
camera projection, exact half hit length, and400 independent scalar moving-pose
cases. Dataset validation hashes every source payload and every view, checks
the exact paired words, real nearer-rectangle support, reveal and reflected
correspondence support, and the frozen original camera table. Old tests and
tolerances are untouched.

CPU preparation:

```
python fsrd_nrd_rr_mirror_oracle.py --output F:/FSRD/sol_batch/15c-rr/mirror-v4
python test_fsrd_nrd_rr_mirror_oracle.py
python test_fsrd_nrd_rr_mirror_oracle.py --prepared F:/FSRD/sol_batch/15c-rr/mirror-v4
```

`fsrd_nrd_rr_mirror_compare.py` validates by default. Its optional`--run` needs a
lead-granted GPU slot inside lead_ops/run_task_test.py, explicit prebuilt EXE
and SHA, and a fresh output under this task's Fscratch. It invokes no compiler
and preserves the original real-wrapper/Consumer/finite/input/guide/alpha/
context/first-reset/warm-pool/deferred destruction/zero-debug assertions. One
disposable default probe precedes three physically fresh full histories with
bit-identical effective settings. Both noisy lighting lobes always enter RR.
The comparator keeps all candidates and reports spec/diff RMSE, chroma,
reveal/stale cohorts, original gradients and same-surface/secondary-surface
adjacent-pair detail. First reset, static jitter, moving camera+object,
camera-only and settled tail are also separated. It has no improvement assert.

Primary contract: [AMD RR1.2 integration](https://gpuopen.com/manuals/fsr_sdk/techniques/denoising/),
local pinned denoising.md2.5.10,4.1,5.1,5.2 and5.3. The SDK says low-roughness
virtual-hit debug information can validate camera and ray length; it does not
publish the proprietary reprojection implementation. A reflection-motion
diagnostic cannot justify a new production field by itself.
