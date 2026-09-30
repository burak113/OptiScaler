# Preparation selfcheck correction before first scene score

The first execution stopped inside self_checks, before any six-scene score or
results.json write. The constructed expected delta had one RGB channel while
the model returns three. The displayed actual values also exposed a numerical
rank problem: at DC, both features are collinear and a theoretically tiny
positive ridge can disappear in float64 subtraction. Clipping a negative
determinant to machine tiny produced huge finite predictions.

Preserve all three initial files in preparation_v1. Correct the expected RGB
shape and, before first scoring, require det>64*eps*vz*vg for the joint fit;
otherwise use the existing one-feature fit exactly. No quality thresholds or
history/ridge constants changed. The updated model adds identified fractions
to diagnostics. This guard is numerical rank handling, not a confidence gate.
