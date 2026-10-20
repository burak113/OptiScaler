# Geometry transport research — job04

**Recommendation: keep as research.** CPU boundary protection is conditional on
trustworthy support; matched-dose temporal error worsens. GPU/AMD RR/game gates
remain unexecuted, and production files/defaults are unchanged.

- [Full report](REPORT.md)
- [Machine-readable result](RESULT.json)
- [Transport API](docs/API_TRANSPORT.md)
- [Reconstruction API](docs/API_RECONSTRUCTION.md)
- [Coordinate ledger](docs/COORDINATE_LEDGER.md)
- [Independent review](docs/INDEPENDENT_REVIEW.md)
- [Exact adapter specification](adapter/PRODUCTION_ADAPTER.md)
- [Local GPU request](GPU_REQUEST.json)
- [Surgical missing-data request](BLOCKED_DATA_REQUEST.json)

From the repository root:

```sh
python -B research/astra20261020/candidates/04-geometry-transport/run_checks.py
```

Python3.11+ and NumPy2.3.5 are sufficient for all CPU checks. The optional figure
script needs matplotlib. See `REPORT.md` for baseline commands, exact provenance,
expected limitations, source revisions, and the point-gain/oracle discrepancy
that was preserved and separated from the final exact-footprint experiment.
