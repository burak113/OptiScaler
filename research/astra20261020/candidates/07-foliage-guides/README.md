# Job 07: original-guide observations for mixed coverage

**Recommendation: keep as research.** The default-OFF observer preserves every
original input. Its separate moments describe available guide evidence; they
are neither a foliage classifier nor an AMD RR confidence input. The tested
hypothetical cosine history consumer is **rejected for production activation**:
held-out sparkle and flicker regress, and the CPU surrogate's detail gate fails.

Start with [REPORT.md](REPORT.md), the machine-readable [RESULT.json](RESULT.json),
and the independently authored [review/REVIEW.md](review/REVIEW.md).

## Run all meaningful CPU checks

From the OptiScaler repository root, with Python 3.11+ and the package's pinned
NumPy dependency:

```sh
python -m pip install -r research/astra20261020/requirements.txt
python research/astra20261020/candidates/07-foliage-guides/run_checks.py
```

This checks the frozen package, reruns its four CPU suites, runs candidate and
independent tests, requires the known bad controls to fail for their intended
reasons, replays all recorded guide controls, reruns the frozen synthetic sweep,
and compares its numerical results with the delivered evidence. It does not
invoke GPU tools. New execution logs go to the ignored `evidence/reproduction/`
directory; original masks and delivered results stay separate. The elapsed time
is machine dependent; the recorded CPU environment is in RESULT.json.

For a quicker development contract check, add `--skip-benchmark`. That option
does not claim to reproduce the full synthetic sweep.

## Individual experiments

```sh
python research/astra20261020/candidates/07-foliage-guides/analyze_captures.py --with-candidate --executor local_cpu
python research/astra20261020/candidates/07-foliage-guides/run_benchmark.py --executor local_cpu
python research/astra20261020/candidates/07-foliage-guides/src/transport_discriminator.py
```

These individual commands refresh their corresponding evidence files. Use the
combined runner above to keep a new reproduction separate from shipped evidence.
Masks are already supplied and verified against BASE; `--freeze-masks` is for
initial construction or exact verification, not changing a candidate denominator.

Two explicit mutants must exit **1**. The standard test runner treats them as
successful falsification only when their intended failure is detected:

```sh
python research/astra20261020/candidates/07-foliage-guides/tests/test_candidate_contract.py --mutant-clamp-history
python research/astra20261020/candidates/07-foliage-guides/review/blind_calibration.py --mutant-ignore-detail
```

## Native handoff

The branch starts at immutable tag `astra-handoff-20261020`, resolved to
`5d7839a930106cf8fe1ba8dbbc6750509e7f26a8`. The audited production revision is
separately `87e8b7ab2a428bd91d3c044decf7d4dbccd8cefd`. The intended PR base is
`sol/26-integration`.

All changes belong to this candidate folder. [adapter/PRODUCTION_SPEC.md](adapter/PRODUCTION_SPEC.md)
is an exact, scoped **diagnostic-only** adapter specification for job08, paired
with candidate HLSL and a checked portable constants layout. No production files
are edited; no CSO is presented as newly built. HLSL compilation and native
execution remain pending. Follow [GPU_REQUEST.json](GPU_REQUEST.json), including
source-word identity and the protected D16/S256+G2/G3 and NZR settings.

The missing observations are listed surgically in
[BLOCKED_DATA_REQUEST.json](BLOCKED_DATA_REQUEST.json). Raw foliage guides are
already present; the remaining request concerns their source/validity/material
lineage, controlled layer/coverage truth and actual native acceptance.

## Figures and evidence

The five stored PNGs are computed from captured arrays or the independent
synthetic control. They contain explicit stage labels. Both RGB panels in each
captured identity illustration use the **same recorded output**; they do not
pretend to show a newly executed RR candidate. Diagnostic unsupported regions
are gray. Optional regeneration:

```sh
python -m pip install -r research/astra20261020/candidates/07-foliage-guides/requirements-figures.txt
python research/astra20261020/candidates/07-foliage-guides/make_figures.py
```

See [evidence/figures/manifest.json](evidence/figures/manifest.json) for exact
exposure, frame and source hashes, and [SHA256SUMS.json](SHA256SUMS.json) for the
delivery file inventory. Hashes prove byte identity, not image quality.
