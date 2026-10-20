# Job 01: executable numerical contracts

This is a NumPy contract and calibration bundle for the immutable
`astra-handoff-20261020` tag, commit
`5d7839a930106cf8fe1ba8dbbc6750509e7f26a8`. The audited production baseline is
separately `87e8b7ab2a428bd91d3c044decf7d4dbccd8cefd`.

**Recommendation: keep as research.** The reusable CPU contract is ready for
jobs 02–04 and 08. A single proposed finite-depth correction is supplied as an
unapplied adapter for local compilation and default-off A/B acceptance. No new
GPU execution, RR output, game quality or performance is claimed.

## Run the complete CPU acceptance

From the repository root, with Python and the pinned package dependency:

```sh
python -m pip install -r research/astra20261020/requirements.txt
python -B research/astra20261020/candidates/01-numerical-contract/run_checks.py
```

The recorded environment already had Python 3.12.14 and NumPy 2.3.5; no package
installation was needed during this task. The runner executes the frozen
package validation, its four CPU suites, the shader artifact contract in
`--skip-compile` mode, all candidate tests, independent bad controls, actual
overlap recovery, source/data inventories, calibration, GPU-input generation,
and adapter application to a clean source copy. Five numerical mutants and the
historically rejected colour quality gate must exit **1**; all other checks must
exit **0**. The acceptance runner itself exits **0** only when these expectations
hold. A diagnostic that catches a bad model is not a passing quality gate.

The default command regenerates evidence within this directory. To preserve the
archived receipt, use a separate output directory, for example on Linux:

```sh
python -B research/astra20261020/candidates/01-numerical-contract/run_checks.py --output /tmp/optiscaler-contract-evidence
```

Individual tests import the standalone library using the candidate directory on
`PYTHONPATH`; the runner sets this automatically. Neither the library nor its
tests require a GPU, Windows, DXC, the game, albedo, or unseen frame history.

## Read the deliverable

| File | Purpose |
|---|---|
| [REPORT.md](REPORT.md) | Mechanisms, measurements, competing explanations, review and limits |
| [RESULT.json](RESULT.json) | Source identity, executor, exact commands/times, acceptance and measured results |
| [API.md](API.md) | Versioned API and examples for jobs 02–04 and 08 |
| [API_MANIFEST.json](API_MANIFEST.json) | Library file hashes and canonical aggregate identity |
| [HYPOTHESES.md](HYPOTHESES.md) | Predictions and falsifiers written before candidate tuning |
| [evidence/run_records.json](evidence/run_records.json) | Final command-by-command CPU receipt |
| [evidence/calibration.json](evidence/calibration.json) | Fixed-population comparisons, exact/bounded distinctions and residual coordinates |
| [evidence/data_inventory.json](evidence/data_inventory.json) | Every safe NPZ array, roles, units, chronology, crops and immutable supports |
| [evidence/source_inventory.json](evidence/source_inventory.json) | Actual tag source, compiler, CSO and embedded-header hashes |
| [evidence/INDEPENDENT_REVIEW.md](evidence/INDEPENDENT_REVIEW.md) | Independent challenge, corrections and reproduction |
| [GPU_REQUEST.json](GPU_REQUEST.json) | Exact local microcases, output bytes and hardware falsifiers |
| [BLOCKED_DATA_REQUEST.json](BLOCKED_DATA_REQUEST.json) | Small missing observations that resolve specific remaining ambiguities |
| [adapter/ADAPTER_SPEC.md](adapter/ADAPTER_SPEC.md) | Justification, compilation and acceptance for the unapplied production patch |
| [MANIFEST.sha256](MANIFEST.sha256) | Delivery checksums, excluding its own self-hash |

`RESULT.json.source_revision` identifies the implementation commit tested by the
final CPU run. The later handoff commit adds the final receipts and documentation;
its PR head SHA is returned with delivery. Hashes identify the tested source
bytes independently of that unavoidable commit/receipt ordering.

On a fresh checkout, verify the archived file manifest before regenerating logs:

```sh
cd research/astra20261020/candidates/01-numerical-contract
sha256sum --check MANIFEST.sha256
```

All submitted paths are in this candidate directory. The production proposal
has not been applied to the repository's production shader, and no generated
candidate CSO/header is labeled compiled.
