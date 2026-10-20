# Blind reviewer calibration and frozen gates

This document and the accompanying control were prepared by `/root/skeptic`
before inspecting the candidate source, configuration, or results. No candidate
claims were provided to the reviewer during this step. The frozen control seeds
are 17041, 31873 and 60791. The test uses 24 frames in chronological order.

## Calibration actually executed here

`blind_calibration.py` synthesizes a relief facade, narrow window frames and FSR
glyphs. It applies a transparent 5x5 normal-gated reconstruction to the same noisy
radiance with exact normals or deliberately flattened normals. Both paths retain
the same raw samples, exposure, fixed truth-derived regions and truth detail
denominators. This is a CPU surrogate; neither output is AMD RR output.

Across the three seeds the flat-normal control has 0.7173–0.7264 times the
flicker RMS of the exact-normal control, but its signed detail transfer is
approximately -0.081 to -0.082 times the control. The wide box footprint even
inverts some narrow periodic contrast. Edge error is 11.74–11.81 times the
control. Thus an aggregate noise improvement is decisively insufficient.

The proper scorer rejects every flat-normal case; the explicit noise-only scorer
mutation incorrectly accepts all three. Running the mutant correctness command
exits 1 with `MUTANT CAUGHT`, as required. This is an intentionally failing
mutation run, not a passing candidate measurement. Exact commands, runtime and
stdout/stderr are in `calibration_run_receipt.json`.

The historical local Native NormalEMA .25 facade loss of 22–27% is quoted from
the packaged `FINDINGS.md` and `evidence/historical/task26_report.txt`. It has not
been re-executed here: the package does not provide a runnable native AMD replay
for those historical variants. Our calibration reproduces the failure mechanism
and validates rejection logic, not the historical magnitude or provider.

## Gates frozen before candidate review

For a pure sidecar diagnostic, every input normal/depth/packed material word and
RGBA signal (including alpha) must remain unchanged. Unsupported history must
not be presented as observed agreement or high confidence. The diagnostic must
be explicit that local guide variation is evidence of variation, not a material
class or proof of mixed foliage coverage.

If an image-quality win is claimed, each protected region must preserve at least
0.95 of exact-control detail transfer, keep flicker and sparkle at or below the
control, and not increase edge error beyond 1.05 times the control. These are
research falsification gates for this surrogate, not native-game acceptance
thresholds. Fixed BASE or analytic truth regions and denominators apply to all
variants. No candidate-selected mask or changed denominator is admissible.

The reviewer will additionally check chronology, moving-crop origin correction,
first-frame and out-of-crop validity, no per-layer truth leakage into candidate
observables, guide decode adversaries, conflicting per-layer motion, moderate
true-light changes, fixed and moving coverage, and independent versus correlated
noise. Held-out data must be selected before candidate tuning.

Any transition from this diagnostic to native reconstruction requires a separate
local GPU request, shader/host parity, native outputs using fixed masks, protected
facade/text controls and final video. No CPU run can waive that requirement.

## Commands

From the repository root:

```sh
python research/astra20261020/candidates/07-foliage-guides/review/blind_calibration.py
python -m unittest discover -s research/astra20261020/candidates/07-foliage-guides/tests -p 'test_review_calibration.py' -v
# Expected exit code 1: the weakened scorer fails the known-bad rejection test.
python research/astra20261020/candidates/07-foliage-guides/review/blind_calibration.py --mutant-ignore-detail --output research/astra20261020/candidates/07-foliage-guides/review/blind_mutant_result.json
```
