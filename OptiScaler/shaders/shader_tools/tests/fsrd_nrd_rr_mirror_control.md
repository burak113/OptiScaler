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

## Signed result

The complete V4 run passed:193dispatches (one probe plus three64-frame fresh
histories),24853 retained native checks, four creates/four deferred destroys,
strict zero D3D12 errors and warnings, and bit-identical eight default/effective
configuration words. No compiler was invoked. Comparison checks3605 and sealed
payload checks7721 are recorded separately. The lead_ops GPU-lock job took
14.137s; outer bounded elapsed14.5585s. Native peak resident89923584B, driver
45477888B; stable owned staging1048576B plus auxiliary327680B.

The coherent rough0 case preserves more ideal-mirror detail than the deliberate
rough.12 mismatch: original-crop projection .1925248 versus .00278717, and
same-primary/secondary-surface pairs .1930307 versus .00271502. This proves a
large model-conditioning effect in this synthetic control. It does not justify
overriding the title's real roughness. Rough0 still blurs detail and retains
colored residuals: specular RMSE .0348224/chroma .0265212, age9..16 positive
stale energy .00288866 compared with raw noisy .00112806. The mismatched
rough.12 result has lower RMSE .0312561/chroma .0103567 while nearly removing
the pattern; lower error alone is not a detail solution.

The reflected-motion diagnostic only raises projection to .2027498, with worse
first-reveal RMSE .0653571 versus .0632816 for valid primary motion. It also
worsens diffuse full-history RMSE .0239343 versus .0230203. There is no case for
silently replacing the valid SDK primary field. All worse rows remain present.

At the first reset, the rough0 specular output equals all49152 raw input RGB
half words exactly; the real SDK was called and received every noisy signal.
This is observed provider behavior for this fixture, not an integration bypass
or a general SDK guarantee. Later it reduces noise but retains only .2292685
gradient projection during static jitter and .1636097 in the settled tail.
The reference remains an instantaneous point sample rather than pixel-area
filtered truth; subpixel reflection detail should not be called a measured game
quality defect solely from this experiment.

All64 GPU timestamp samples per history are in runs.json. They measure128x128
RR plus the normal RGB-only commit, including first reset: mean/medianms
rough0 .37407/.36520, mismatch .39476375/.41110, diagnostic .404708125/.39280.
No1505x847/2560x1440 cost or game FPS was measured for this test-only control.

`analyze_fsrd_nrd_rr_mirror_quality.py` validates actual output hashes and makes
fixed-exposure spec/diff previews at the predetermined2/17/33/49/65samples.
It is CPU only and reports raw first-reset RGB bit identity rather than guessing
passthrough from a screenshot. Its62 integrity checks passed. The remaining
detail/chroma/stale tradeoff motivates a separately noise-gated recovery test;
the analytic reference must never become a production recovery input.
