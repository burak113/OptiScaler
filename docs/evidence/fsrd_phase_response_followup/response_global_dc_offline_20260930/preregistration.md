# Observable global-DC conditioned response hypothesis

Posthoc diagnostic on the frozen six-scene significant-phase native initial
matrix, not a fresh native acceptance trial. No new P or reused T(P) mismatch.
Keep P and its actually measured response together. Original evidence unchanged.

New hypothesis: a same-frequency affine model misses nonlocal guide artifacts
whose amplitude depends on global illumination. Regress D_k=P_k-T(P)_k on both
current P_k and current global pilot luminance DC, with a complex intercept,
current-inclusive last16 corresponding samples, minimum8. Reset/jitter changes
or inactive frames clear history; startup uses current D, inactivity uses zero.
The reference is the unchanged prior affine_pilot model, run on the same arrays.

Use source FFT median nominal variance and the prior fixed4x ridge. DC ridge
uses sum(luminance_weights^2) times that variance, an IID heuristic rather than
a physical confidence bound. No clean reference, native baseline, guide or
future values enter the estimator. No age term or post-score coefficient tuning.
Pre-execution numerical selfcheck correction: use the unchanged one-feature
fit when det<=64*eps*vz*vg, avoiding a canceled rank-deficient determinant. See
pre_execution_erratum.md and preserved preparation_v1, before first scene score.
Keep raw correction, separately declared current-source DC conservation, and
whole-RGB representability fallback variants. Reuse existing full/mature gates;
also report actual STD ratio and absolute per-frame gain[.95,1.05]/phase<=.05.

Required selfchecks: causality; history16; reset/jitter/inactivity; exact algebra
on a constructed nonlocal DC-dependent artifact with rotating detail; constant
DC reduction to same-frequency reference; rank-deficient DC finite behavior.
Unknown temporal correlation, endogeneity, context settling, changing transfer,
spatial correspondence, persistent shared bias and startup remain limitations.
Six cases cannot establish the full stain/wave solution or game quality.
