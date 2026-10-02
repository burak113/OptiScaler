# Final SOURCE selection: unselected/deprioritized

This clarification preserves SOURCE_DECISION.md (7288B, SHA256 b08e520db8d9eb11378b18fd32d265978ddc63476a5436fe878ed0c3c06cd5ef). Its novelty finding does not select an implementation or test.

The proposed valid-pixel law is a **replacement**:

`F = M * (w * Fline(U) + (1-w) * Fiso(U))`, where `U=C/M`.

Native composed R is retained only on invalid-domain/support fallback. The spatial/RGB coherence weight w chooses line versus isotropic filtering; it does not retain R in valid pixels or certify adequate stochastic-noise reduction. It must not be described as `R+w*(F-R)`.

Root's already CLOSED native-noise observations raise a concrete selection objection: a short fixed spatial filter can preserve more source noise than the actual native baseline. No new noise calculation, array review or experiment was performed here. The proposed tangent filter's novelty and possible clean-detail retention do not establish the required noise/nonworse conjunction.

`R + confidence*(F-R)` would be a distinct current-frame residual operator, but this audit has not justified a fixed observable confidence law for it. The proposed tensor/cross-channel agreement measures observed spatial/color coherence, not correction-error variance, source/native error covariance or clean residual evidence. Correlated stochastic illumination can be coherent, while legitimate multicolor detail can be incoherent. F and R also share the same noisy source, so population independence of RGB input noise does not provide independent evidence for their correction. Reusing w as confidence would introduce an unsupported inference rather than resolve the objection.

Decision: **SOURCE_CONCEPT_UNSELECTED_DEPRIORITIZED_NO_TEST**. No footprint/threshold retuning, replacement/blend relabeling, confidence fit, kernel family, executable preparation or quality bank is selected. The exact contour-filter novelty remains bounded; it does not establish a defensible noise-safe repair. All previous CLOSED candidate rejections remain intact, and the full1 visible-detail/noise objective remains unresolved. No production modification or execution occurred.
