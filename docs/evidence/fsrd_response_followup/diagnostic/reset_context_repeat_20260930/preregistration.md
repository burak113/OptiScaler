# Lighting transition reset diagnostic, before execution

Repeat the pinned-runner four-context lighting source diagnostic with identical
seven consumed texture inputs and only an added RESET at frame 32, the known
synthetic lighting step. All other controls, frame indices, projection, jitter,
provider, tuning, sizes and binary remain exact. Verify applied dispatch bytes
differ from the source anchor only by the RESET bit of frame 32. Retain complete
native FP16 diffuse/specular outputs and selected composed RGB as before.

This tests dependence on pre-transition native history. It does not prove an
initialization bug, determinism, a population variance bound or a production
reset policy. A true lighting detector, noise cost and early material/phase
acceptance would require separate work. Preserve the prior four divergent
contexts and original/no-reset results.
