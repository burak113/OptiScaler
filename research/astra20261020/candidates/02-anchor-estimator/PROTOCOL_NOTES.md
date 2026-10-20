# Execution notes and clarifications

The candidate constants and eleven source/test/protocol files were hashed in
`evidence/FROZEN_SOURCE.json` before release of held-out anchor arrays. Historical
manifest summaries were already public, and the untouched calibration runner
checked all packaged fixtures. This is therefore an engineering holdout of array
evaluation, not a claim of a completely unseen capture or concealed metadata.

The preregistered calibration's phrase "physical level 1" refers to its unit
scale. The actual evaluator, frozen before holdout, uses the deterministic clean
texture `1 + .15*sin(.7*x) + .10*cos(.8*y)` with a **spatially uniform
multiplicative** excess `.18*exp(-k/10)`. The radiance field is not perfectly
uniform. All reported doses use the actual frozen arrays and their exact
fixed-mask input-energy denominators. No metric or parameter was changed after
viewing held-out results to address this wording.

The independent review requested a separate static-background light response
for the moving-object control. That evaluator addition and both 90% and 95%
sustained-response latency fields were completed before the source freeze.
Background support excludes the union of every original foreground position,
and is identical across variants and frames. Moving-pixel bilinear loss remains
a separate full-resolution CPU proxy.

Two defensive API issues were fixed during independent review before freeze:
invalid/nonfinite configuration and invalid interval coverage could make
diagnostic results unsafe. A pseudocode reason-bit mismatch was also repaired.
No threshold tuning followed those reviews. The original failing review log is
retained with its actual failure; passing reruns are separate receipts.

The sole implemented deployment result abstains (`gain=1`); this loses all
potential excess correction. `provisional_gain` is a diagnostic comparator and
fails genuine-light and correlated-null controls. Positive dose comparisons
never include the zero-dose deployment field as an efficacy winner.
