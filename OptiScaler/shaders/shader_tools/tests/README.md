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

The experimental alpha additive split is covered by `test_fsrd_additive_split.py`
in the release gate. It authenticates frozen base shaders from commit
`56e1af15ee9fd6d57daac12e240159eac1c3df8e` and runs production DXIL, including
activation, per-channel fallback, source origins, masks, HDR and Floor accounting.
`FSRD_ALPHA_BASELINE` can point at an already extracted base snapshot; otherwise
the test extracts authenticated files from Git. Native tests do not establish
AMD denoising quality.

`probe_fsrd_additive_split.py --baseline <snapshot> --output <new-directory>` runs
production conversion, the real AMD DLL, and production composition per frame.
It requires NumPy and Pillow, initialized FidelityFX SDK v2, MSVC and D3D12.
Its exit code confirms experiment completion; the recorded quality flags and
local error metrics determine acceptance. `--prospective` explicitly selects
the revised clean-truth contrast/local-bias criteria for a fresh seed; it does
not change the earlier report. Captured guide tests require matching NPZ and
capture metadata, never captured RGB as clean truth.

`benchmark_fsrd_additive_split.py --baseline <snapshot> --output <new-directory>`
measures conversion only. Run it without concurrent GPU tests or a game; the
measurements do not represent complete RR or game frame time. See the
[alpha findings](../../../../docs/fsrd_alpha_additive.md) for actual outcomes.
Disabled conversion uses the original shader; enabled conversion selects
`FSRDInputConvAdditive`. Lossless comparison permits no channel exceptions.

`probe_fsrd_additive_parity.py --baseline <frozen-measured-additive-snapshot>
--output <new-directory>` is the separate optimization audit. It authenticates
the measured prototype DXIL (`398dd3bc...`) and source, then requires exact
stored outputs for native contracts, group/edge/origin stress, constant-halo
rejection and complete 64-frame quality input sequences. This reference is the
archived additive prototype, **not** the original branch snapshot used by the
release gate. The optional captured cases need the same source capture as the
quality probe. Timing from simultaneous correctness tests is not a performance
measurement.

`probe_fsrd_real_rr.py` and `fsrd_rr_runner.cpp` are separate controlled AMD RR
experiments; the ordinary shader suites supply independent synthetic RR outputs.
These probes are not an in-game Cyberpunk capture or acceptance test. Optional
baseline comparisons need frozen shader artifacts and must never silently use
the current shader as their own reference.

Do not treat synthetic detail/noise budgets or dispatch timings as proof of
image quality or frame time in a game. The adaptive-demodulation experiment
was removed after real-game flashes persisted despite controlled checks.
