# Job 05 — Glass NZR research bundle

**Keep as research; do not enable this candidate as a production visual fix.**
Start with [REPORT.md](REPORT.md) and [RESULT.json](RESULT.json). All source,
tests and evidence belong to this isolated candidate directory. Production and
the packaged baseline were not modified.

Base tag: `astra-handoff-20261020`.
Resolved base: `5d7839a930106cf8fe1ba8dbbc6750509e7f26a8`.
Working branch: `astra/05-glass-nzr`.
PR target: `sol/26-integration`; no merge or auto-merge is performed.

## Reproduce

Python 3.11+ and NumPy 2.3.5. From the repository root after checking out this
task's revision:

```sh
python -B research/astra20261020/candidates/05-glass-nzr/verify_bundle.py
python -m pip install -r research/astra20261020/requirements.txt
python -B research/astra20261020/candidates/05-glass-nzr/run_checks.py
```

This runs the four original CPU suites, 35 task tests, causal probes, recorded
inventory/calibration, adapter applicability, two expected failing controls,
and 240 held-out synthetic sequences. It does not run the Windows test drivers,
AMD RR or the game. Use `--skip-holdout` for a subsequent contract-only check.

The standalone commands are:

```sh
python -B research/astra20261020/candidates/05-glass-nzr/experiments/causal_probes.py
python -B research/astra20261020/candidates/05-glass-nzr/experiments/recorded.py --images
python -B research/astra20261020/candidates/05-glass-nzr/experiments/synthetic.py --split development
python -B research/astra20261020/candidates/05-glass-nzr/experiments/synthetic.py --split holdout
python -B research/astra20261020/candidates/05-glass-nzr/adapter/validate_adapter.py
python -B research/astra20261020/candidates/05-glass-nzr/tests/test_review_adversarial.py --mutation-alpha
```

The last command must fail with exit 1: it intentionally writes the wrong
alpha source. The wrapper expects this failure. Candidate quality is separately
rejected despite passing correctness/counterexample tests.

Results include execution times and source/input/mask hashes. Reproduction
updates generated results and naturally changes timing fields; the checksum
manifest describes the published snapshot. No fixture is overwritten. Original
development and reviewer scope versions are retained and explicitly labelled.

`verify_bundle.py` checks the published checksums and local links before any
experiment rewrites its evidence. `finalize_result.py` assembles the return
metadata from existing measurements; it does not execute or tune the candidate.
The result names the source/evidence commit, while a later metadata-only commit
records that identifier and the final checksum manifest.

## Job 08 adapter boundary

[adapter/PRODUCTION.patch](adapter/PRODUCTION.patch) only adds an unreachable
HLSL source file and is not an enabled implementation. It can be checked against
the recorded base with:

```sh
git apply --check research/astra20261020/candidates/05-glass-nzr/adapter/PRODUCTION.patch
```

Applying it is job 08's choice after reading [ADAPTER.md](adapter/ADAPTER.md),
the [uncertainty interface](src/UNCERTAINTY_INTERFACE.md),
[GPU_REQUEST.json](GPU_REQUEST.json), and
[BLOCKED_DATA_REQUEST.json](BLOCKED_DATA_REQUEST.json). No uncertainty producer
or scheduling/ownership change is supplied. The CPU API deliberately abstains
when the sidecar is missing. No compiled shader or DLL is delivered.
