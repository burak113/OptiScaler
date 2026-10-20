# Job 06 — moving-bottle support diagnostics

**Recommendation: keep as research.** This is runnable diagnostic code plus a
bit-preserving identity/abstention candidate. It does not change production
pixels or claim an accepted bottle repair.

## Run from repository root

Python 3.11+ and NumPy 2.3.5 are sufficient. If necessary, install the pinned
dependency using `python -m pip install -r research/astra20261020/requirements.txt`.
The execution environment used for this delivery already had the exact version.

```sh
python -B research/astra20261020/candidates/06-moving-bottle/run.py
```

This checks the frozen package, runs the four original portable suites and all
candidate tests, requires the deliberate crop-origin mutant to fail, evaluates
the frozen synthetic and recorded experiments, checks identity preservation,
and regenerates the synchronized PNG/HTML evidence. It never invokes a GPU.
The mutant's expected exit code is **1**; the overall runner must return **0**.

Results are written under `evidence/`. The committed logs/JSON are the actual
delivery snapshot. A rerun can change elapsed times and therefore log hashes;
`SHA256SUMS` attests the delivered snapshot, not a freshly rerun working tree.

## Read the result

- [REPORT.md](REPORT.md): findings, measurements, rejected shortcuts and limits.
- [RESULT.json](RESULT.json): revisions, execution receipts, measured results and hashes.
- [evidence/visuals/index.html](evidence/visuals/index.html): open locally to step
  through all seven original bottle frames in lockstep. PNG frames are beside it.
- [review/REVIEW.md](review/REVIEW.md): independent blind review and defects it caught.
- [adapter/ADAPTER_SPEC.md](adapter/ADAPTER_SPEC.md): exact read-only native adapter
  and coordinate handoff for job08/job04; no production patch is proposed.
- [BLOCKED_DATA_REQUEST.json](BLOCKED_DATA_REQUEST.json) and
  [GPU_REQUEST.json](GPU_REQUEST.json): bounded existing-data export first,
  followed by the actual native/GPU/game gate if needed.

## Reproduce independent blind measurements

```sh
python -B research/astra20261020/candidates/06-moving-bottle/review/analyze_blind.py
python -B research/astra20261020/candidates/06-moving-bottle/review/score_blind.py
```

The original predictions were frozen before labels were revealed. The included
labels are now public for reproducibility; rerunning the scripts is not a new
blinded human/agent diagnosis. Cases13/14 contain identical observations and
form one non-identifiability check, not two independent trials.

All task additions are scoped to this directory. The immutable research tag is
`astra-handoff-20261020`, resolved to
`5d7839a930106cf8fe1ba8dbbc6750509e7f26a8`. The PR target is
`sol/26-integration`; the branch is `astra/06-moving-bottle`.
