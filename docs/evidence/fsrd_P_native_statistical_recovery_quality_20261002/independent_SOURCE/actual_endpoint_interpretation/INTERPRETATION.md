# Fixed P/native recovery endpoint — independent saved-result interpretation

**Interpretation PASS; fixed candidate REJECTED.** Completion was read before result: driver 30516 / CPU child 30956 returned rc0 with ordinary completed closure, no termination or monitor error, in 7.422 seconds. It records unchanged source and zero new GPU/RR dispatches. Saved result identity matches 65,736 bytes / SHA256 `3f83745a43338e07e25373788769734b74566985abdefbfa5c450000015d41aa`.

Both paired applications pass every required clean RGB material/illumination gain and phase gate. Static-clean illumination gain is approximately .998–1.001; animated-clean gain approximately .9965–.9989, with phase below .002 radians. The detail recovery is a measured endpoint benefit, not an unconditional algebraic guarantee. Clean-region RMSE and structured material error also improve against both actual A baselines.

There is a mixed whole/noisy tradeoff, repeated against both baselines:

- WHOLE RMSE improves: A1 .01473421 → .01197622; A2 .01473612 → .01197623. Structured material error worsens: .00082283 → .00272397 and .00080996 → .00272348.
- ANIM_NOISY RMSE improves: .01712574 → .01468588 and .01712173 → .01468559. Structured material error nevertheless worsens: .00070418 → .00151332 and .00069571 → .00151293.
- STATIC_NOISY fails both requirements: RMSE .01311650 → .01891178 and .01313684 → .01891207; structured material error .00048448 → .00285688 and .00048572 → .00285509.

No absolute RGB bias failure is recorded. The unchanged conjunction still fails both pairs: WHOLE and both noisy regions require strict structured-error improvement, and STATIC_NOISY requires nonworse RMSE. Thus `REJECT_FIXED_P_NATIVE_RECOVERY_ENDPOINT_QUALITY` is correct despite the clean-detail, whole-RMSE and animated-noisy-RMSE benefits. RMSE is error against physical clean truth, not an isolated noise-variance measurement. The structured metric is the centered horizontal profile of error averaged over y; it is not a direct stain metric.

Each application changes all 10,240 pixels, with zero fallback, unsupported-stencil or arithmetic rejection. Each reports 15,534 fully suppressed centered-highband channels, while local mean residual transfer remains unconditional. The observed adverse structured error is compatible with the predeclared mean/coarse-structure risk, but this endpoint does not experimentally isolate mean transfer from the empirical allowance, P errors or other terms. It therefore does not prove a specific mechanism caused the failure. Paired candidate outputs differ: this law depends on each actual R baseline, unlike the previous P-only output. That difference does not imply a new native temporal experiment.

Continuation is false; all64 quality and temporal efficacy are null; actual GPU candidate is false. Single-frame temporal STD=0 supplies no temporal evidence. Earlier radiance-guide and P-whole-output rejections remain unchanged. This decision concerns one fixed law on the existing synthetic f63 fixture and two paired actual baseline outputs. It establishes neither game stain causation, physical lobe recovery, calibrated native confidence nor rejection of every statistical recovery method. No port, rerun, altered law or parameter scan follows from this review.
