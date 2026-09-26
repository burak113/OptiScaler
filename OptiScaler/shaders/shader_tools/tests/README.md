# FSRD shader validation and experiment archive

Use `../validate_fsrd.py --build --output <new-directory>` from the repository
root with the full script path. Its `SUITES` list is the current release gate.
It checks production DXIL, D3D12 diagnostics, resource/layout mirrors, generated
artifact identity and DLL embedding. It reports unavailable historical A/B
references as skips, not successes. See
[the current checkpoint](../../../../docs/fsrd_floor_recovery_release_20260926.md).

This directory also retains research probes and fixtures for removed algorithms.
Running every `test_fsrd_*.py` is not the supported release gate: some describe
NLM/detail consensus, spatial/temporal colour accumulation, temporal detail
evidence, broad recovery or the reverted glint-pedestal experiment. Their
expectations belong to those historical implementations. Corresponding dated
reports in `docs/` explain the experiments and their limitations.

`probe_fsrd_real_rr.py` and `fsrd_rr_runner.cpp` are separate controlled AMD RR
experiments; the ordinary shader suites supply independent synthetic RR outputs.
These probes are not an in-game Cyberpunk capture or acceptance test. Optional
baseline comparisons need frozen shader artifacts and must never silently use
the current shader as their own reference.

Do not treat synthetic detail/noise budgets or dispatch timings as proof of
image quality or frame time in a game. The adaptive-demodulation experiment
was removed after real-game flashes persisted despite controlled checks.
