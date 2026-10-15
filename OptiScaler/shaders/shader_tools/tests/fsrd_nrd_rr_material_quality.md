# Controlled native-style material guide ablation

Bu deney aynı64-frame sentetik ışık/kamera/gürültü dizisinde beyaz rehber ile
gerçekçi materyal rehberini ayırır. İki ışık lobu da her adayda gerçek RR'dan
geçer; kaynak RGB/A, depth, normal, surface motion ve kamera bitleri sabittir.
Yalnız diffuse/specular albedo rehberinin RGB'si değişir. Oyun/NRD eşli çekimi
veya title LUT doğruluğu iddia edilmez.

## Frozen CPU preparation

Generator: `fsrd_nrd_rr_material_quality.py`. Source v1 manifest SHA:
`27545e6db81e5214b2c0622a57ae05efa9ca2ed8148666e86e9542c63fd9974d`.
The script never regenerates or writes v1. It verifies every original payload,
re-traces the original primary geometry using the hash-matched independent
oracle and requires exact float32 world-point/object-mask agreement. Source
RGB/hit/depth/normal/surface-motion and complete native camera-table hashes are
identical in all four prepared views.

Background materials use world XY; the translating rectangle uses object-local
XY. Six predeclared asymmetric color palettes and four metal values are tiled
with fixed frequencies/offsets unrelated to radiance/reference/noise. Canonical
stored color is RGB10 `round(sqrt(linearColor)*1023)`, decoded and squared;
metal is R8 UNORM. The same material point must retain exact canonical words
after object/camera movement. Normal material category remains v1's supported0.

Qd = baseLinear*(1-metal). Specular F0 = lerp(.04,baseLinear,metal). Qs uses the
four matrices/rational polynomials of AMD denoising.md5.5.2, alpha=roughness²,
NoV=abs(dot(normal,toCamera)), including the zero-reflectance bias term. This
is the same **analytic guide model** used by the new production helper; it is
not the native late-compositor LUT/CB6 multiplier. No extra signal division,
roughness unpack square/root or guessed exposure gain is applied.

Guide NoV uses the normal decoded from the unchanged packed normal input.
The reference reflectance uses exact geometric +Z and full canonical material
precision. The owned synthetic base/metal packet explicitly uses half-RNE;
guide RGB is half-RNE then R8-RNE on CPU before upload. The upload therefore
defines exact provider input words. This does not assert bit parity with a
particular hardware typed-store conversion in the production capture path.
Unused albedo alpha is copied exactly from v1 for every candidate.

Candidates: `white`, `diffuse-only`, `specular-only`, `both`. Actual RR uses the
unchanged DD|IS route, surface-motion B, NON_GAMMA_ALBEDO and one physically
fresh context per complete history. A disposable1-frame actual context queries
the common defaults; all8 effective float words are then identical across
candidates. No SDK setting is tuned and no improvement assertion is present.

CPU prep passed6149checks. Independent scalar-polynomial versus vector/matrix
BRDF, material motion/storage and metric properties passed744checks (all prior
737 retained). Frozen view validation passed4934checks. Prepared manifest SHA:
`e25fc2aa20189d26ad9ad525cff658fa615822415013f82c63c41a08e0c7b3c8`.
No GPU or compiler ran for this checkpoint. Max guide quantization/normal/
captured-packet difference from full-precision reference factors was measured
as Qd .00185815373, Qs .00266259649; it is reported as an input-model precision
floor, not hidden by a widened result tolerance.

## Scheduled native runner and analysis

`fsrd_nrd_rr_material_compare.py` defaults to CPU validation. `--run` requires a
lead-granted shared GPU slot via `F:/FSRD/sol_batch/lead_ops/run_task_test.py`.
It accepts `--native-exe` and mandatory `--native-exe-sha` for the existing
signed-provider RRWrapper/Consumer executable. It never invokes a compiler or
edits the C++ harness. Every attempt needs a fresh native output folder; failure
logs and partial outputs are preserved. The native executable keeps all original
finite, seven GPU input-identity, opaque-alpha, Consumer, warm-pool, first-reset
and deferred context-destruction assertions. Compiler/native work is pending
until the parent explicitly schedules it.

CPU-only commands (paths illustrative within this task):

```
python fsrd_nrd_rr_material_quality.py --output F:/FSRD/sol_batch/15c-rr/material-v2
python test_fsrd_nrd_rr_material_quality.py --output E:/FSRD/sol_batch/15c-rr/material-properties.json
python fsrd_nrd_rr_material_compare.py --prepared F:/FSRD/sol_batch/15c-rr/material-v2
```

The comparator reports every candidate, including worse rows, in five domains:
demodulated specular/diffuse, current-material-remodulated specular/diffuse,
and the combined lighting. Actual output is multiplied by **current** Qd/Qs;
the stale-light reference uses current factors too because RR stores
demodulated lighting before the late compositor. Specular exposure is fixed1.
Reported units precede the common Consumer64 multiplier; post-Consumer RMSE
would be64 times larger.64 is never used as an input/pre-exposure correction.

Demodulated detail metrics remain essential: a dark material can hide error
without restoring lost RR light. Material discontinuities can also inflate the
combined gradient score. Original demodulated gradients and same-material
adjacent-pair gradients are therefore both reported. Reveal-age cohorts use the
original independent physical support and retain all ages, not a tuned crop.

This adds a well-defined material-reflectance model to v1's prescribed point-
sampled light. It does not turn that light into a full rough-BRDF/path-integrated
transport simulation, a native NRD reference, or an in-game quality/FPS result.
Production native material-capture/typed-store/state-provenance tests are a
separate fixture family; this experiment isolates provider response to guide
RGB, not those hooks. A quality conclusion requires the actual signed runs and
an eventual in-game A/B; CPU preparation alone proves none.

Primary source: [AMD GGX guide example](https://gpuopen.com/manuals/fsr_sdk/techniques/denoising/#552-example-brdf-approximation),
locally pinned `Kits/FidelityFX/docs/techniques/denoising.md`5.5.2 and production
helper `FSRDNrdMaterialGuides.hlsli` at28afe3b0. Native material-remodulation proof
is maintained by15b; this synthetic experiment does not substitute for it.
