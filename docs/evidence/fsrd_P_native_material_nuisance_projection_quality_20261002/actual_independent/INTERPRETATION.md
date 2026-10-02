# Fixed nuisance projector — independent actual interpretation

**Interpretation PASS; fixed projector REJECTED.** Completion was read before result and matches SHA256 `fcdd834e994a7aeade888db515842f0d8f32fafc531c2b213061670b4a3a2d65`. Driver20940 / child16964 closed ordinarily with rc0 in1.813s, no termination/monitor error, unchanged source and zero new GPU/RR dispatches. Result identity is66,149 bytes / SHA256 `b1e00ec226eb86347bfd27b45eedccb2b64eb4b726baa5b10739a2d56bdc2694`.

The clean RGB material and illumination gain/phase gates pass against both paired baselines. Clean illumination amplitude is approximately .997779–1.000578 static and .985908–.990254 animated; recorded absolute phase remains below .001347/.010286 respectively. Every region improves physical clean-target RMSE and does not worsen absolute RGB bias. Retain these actual endpoint benefits:

- WHOLE RMSE: .01473421→.00933643 and .01473612→.00933717.
- STATIC_NOISY RMSE: .01311650→.01160778 and .01313684→.01161009.
- ANIM_NOISY RMSE: .01712574→.01427088 and .01712173→.01426944.

The only recorded failures are the unchanged strict structured-material-error requirement in WHOLE and both noisy regions, in BOTH pairs:

- WHOLE: .00082283→.00259415 and .00080996→.00259533.
- STATIC_NOISY: .00048448→.00233181 and .00048572→.00233219.
- ANIM_NOISY: .00070418→.00134029 and .00069571→.00134542.

Thus lower RMSE/bias and preserved clean carriers do not satisfy the required conjunction. RMSE is aggregate error against physical truth, not isolated noise variance; structured-material error is the centered x-profile of y-averaged error, not a direct water-stain measurement. All589 patches succeed per arm, with nuisance rank2 and projected spatial rank6 throughout. All10,240 pixels are covered and changed, overlap count1–4, with zero fallback/arithmetic rejection. The adverse profile result is not explained by missing coverage or a reported arithmetic failure.

The selected local normalized nuisance constraint did not meet the global physical-profile requirement. This is consistent with its declared limits: residualized polynomial projection, multiplication by spatial M, overlap gather and retained patch DC do not provide a physical material-null guarantee. The endpoint does not isolate which of those mechanisms accounts for the residual error or show that the SVD/orthogonality computation was incorrect. It rejects this one fixed law; it does not reject every possible material/illumination separating method.

Continuation is false; all64 quality and temporal efficacy are null; actual GPU candidate is false. Paired candidates differ because each uses its own actual R. Earlier rejected laws remain unchanged. No degree, rank, footprint, guide or confidence sweep is justified by this result. This single synthetic f63 CPU/HALF endpoint provides no game stain cause, private SDK conclusion, direct water/temporal proof or GPU port qualification. Reviewer consumed saved JSON scalars only and ran no candidate, scorer or numerical kernel.
