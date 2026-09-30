# Reconstruction coefficient endpoint history — 2026-09-30

This candidate remains rejected as a stain/wave solution. One frozen CPU
evaluation used the same six saved native response sets and 24 constructed
operators. No new native/GPU work or runtime change occurred. Full-window
combined acceptance is 0/6; mature-window acceptance is 5/6. Weak material
still fails both strict noise reduction and absolute gain.

The candidate fits coefficients of current reconstruction
`C = B + active * (P - TP)` in the existing source harmonic basis. It retains
the current orthogonal residual and shifts only those coefficients toward
a current-inclusive endpoint linear fit over at most 16 transported history
observations. A single observation retains original C bytes before the
unchanged source DC application. Source reset/innovation/phase cuts,
invalid-frame exact-B eligibility and final atomic RGB fallback remain the
previous V2 policy. The law was reviewed and frozen before scoring.

Endpoint weights preserve constant and affine coefficients in transported
coordinates. This does not establish reconstruction/source phase agreement.
Independent rational arithmetic finds nominal IID variance gain 31/136 at
16 observations, an uncut-step peak of 22/17 and quadratic endpoint bias
`-35*q`. Unknown native covariance, common bias, phase mismatch and nonlinear
changes remain explicit risks; nominal gain is not confidence.

In the mature native window, relative gates pass 6/6, actual temporal STD
does not increase in 5/6, absolute gain passes 5/6 and phase passes 6/6.
Weak material STD is 1.06933 times baseline and 1.08637 times V2. Full-window
gain passes 0/6 and phase passes 4/6; the first eight inactive frames remain
exact baseline. No native-row output needs invalid-pixel fallback. Relative
passes alone therefore do not establish strict noise or absolute-detail
acceptance.

Constructed controls show useful mechanism differences: exact B/D
cancellation remains essentially constant, the true correction ramp retains
gain 1 and the moving-source/static-response control retains gain 1 with
negligible phase error. Static spectral coefficient noise worsens relative
to V2. Shared bias retains gain 1.1667, phase-toggle error remains 0.08579
and the shared constant-speed gain reaches 1.05745. These failures are
preserved without changing thresholds or fitting another candidate.

An independent audit recomputed 108 full/mature metric dictionaries from
the six saved output arrays; all matched. Known24 candidate arrays were not
saved, so that portion is authenticated report/input/comparator evidence,
without an independent candidate-array rescore. Original metrics, exact V2
comparators and all 61 frozen source identities remain unchanged.

The [evidence archive](evidence/fsrd_reconstruction_endpoint_history/manifest.json)
includes preparation, law review, authorization, results and post-score
audit. The original preparation manifest's erroneous empty self-entry is
preserved; a separate corrected seal verifies the 19 nonself records and
61 sources without changing the law. Other seven source families and 22
source adversaries still lack matching native response coverage. The
[weak-material decomposition](fsrd_weak_material_response_bias_diagnosis.md)
locates the remaining gain loss without claiming an opaque SDK mechanism.

Native totals remain 398 contexts/21,050 successful API RR recordings:
21,042 queued and eight recorded-only discards, plus four separate no-API
omissions. No current-alpha game acceptance is established.
