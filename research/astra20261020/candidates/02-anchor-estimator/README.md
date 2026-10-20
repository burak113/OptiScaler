# Job 02 — native anchor estimator research

**Decision: keep as research. Reject the provisional estimator as an active
correction.** The implemented application field explicitly abstains (`gain=1`)
without an independent illumination witness. This is a reproducible negative
result and useful diagnostic implementation, not a denoising release.

Read [REPORT.md](REPORT.md) for measured trade-offs and
[RESULT.json](RESULT.json) for revisions, commands, timings, hashes and status.

From the repository root, with Python 3.11+:

```sh
python -m pip install -r research/astra20261020/candidates/02-anchor-estimator/requirements.txt
python -B research/astra20261020/candidates/02-anchor-estimator/run_checks.py
```

For the numerical checks without regenerating the figures, the original
handoff dependency `numpy==2.3.5` is sufficient:

```sh
python -B research/astra20261020/candidates/02-anchor-estimator/run_checks.py --skip-plots
```

The runner verifies frozen candidate source hashes before held-out access,
validates the original package before and after, runs implementation and
independent falsifier tests, reproduces the captured/analytic experiments, and
writes an execution ledger. It never runs a GPU, game, DLL installation or
production source mutation. A successful check includes rejection of known bad
controls and of the active provisional candidate; it is not a quality approval.

## Deliverable map

| File/folder | Purpose |
|---|---|
| `estimator.py` | Paired-log diagnostic, explicit support/rounding envelope, causal abstention, modeled Apply |
| `experiments.py`, `metrics.py` | Synthetic controls, fixed-mask captured comparisons, matched dose, chronology-aware metrics |
| `tests/` | Candidate and measurement contracts |
| `mechanism/` | Causal hypotheses, raw fixture inventory, smallest distinguishing experiments |
| `reviewer/` | Preregistered independent controls, original failed audit, corrected audit, held-out reproduction |
| `adapter/ESTIMATOR_SPEC.md` | Exact adapter specification for job08, without an applied production patch |
| `adapter/AnchorDiagnostic.pseudo.hlsl` | Source-shaped pseudocode; not compiled HLSL or bytecode |
| `evidence/` | Preserved baseline run, source freeze, measured JSON/NPZ, plots, final execution ledger |
| `GPU_REQUEST.json`, `BLOCKED_DATA_REQUEST.json` | Surgical missing-observation request and local native/RR acceptance gates |
| `SHA256SUMS.json` | SHA-256 manifest of delivered candidate files, excluding its own hash |

All production files, the other jobs, and the packaged baseline remain
unchanged. The PR target is `sol/26-integration`; no merge or auto-merge is
requested. The recommended protected game preset continues to keep Anchor OFF.
