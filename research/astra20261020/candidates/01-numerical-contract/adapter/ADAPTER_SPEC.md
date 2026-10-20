# Scoped finite-depth adapter for job 08

**Status: proposed source only, default-off A/B pending local acceptance.**
The task branch keeps production unchanged. `PRODUCTION.patch` changes one
history-validity predicate in
`OptiScaler/shaders/fsrd_preprocess/precompile/FSRDColourTrackTrack.hlsl`.
`FSRDColourTrackTrack.hlsl` in this directory is the exact resulting candidate
source. Its includes still resolve from the production precompile directory
when applied. No denoising policy, pass, resource, constant, packing or default
setting is added.

## Mechanism and falsifier

The existing source accepts history when
`abs(history.a - expected) <= Params.y * max(abs(expected), 1e-3f)`.
With finite history and infinite expected depth, both sides can be infinite;
`Inf <= Inf` is true. The proposed predicate first requires
`isfinite(history.a) && isfinite(expected)`. NaNs also reject. Current depth and
motion depth are typed R16 fields; actual GPU tests must inject representable
half infinities. Two finite half-expanded operands cannot overflow float32.

The falsifier has two parts: the invalid-depth cases must use fresh-source
history, and every observed finite-domain decision must match the baseline.
CPU review tested every finite half payload against four motion probes
(253,952 comparisons), plus 4,096 seeded finite half/interpolated-history cases,
with **zero** changed finite-domain decisions. Exact inclusive positive and
negative 2% boundaries are preserved. See
[GUARD_ADAPTER_REVIEW.md](../evidence/GUARD_ADAPTER_REVIEW.md) and
[test_guard_adapter.py](../tests/test_guard_adapter.py).

Under the source expressions, adding finite tests is analytically an identity
on finite operands and finite expected depth. That CPU statement does not prove
that DXC under fast-math preserves the tests or that any device implements the
same nonfinite path. Source compilation, bytecode review and GPU A/B are gates.

## Apply and build on the integration checkout

First review job 08's current source against the recorded base. From repository
root, the exact patch can be checked and applied with:

```sh
git apply --check research/astra20261020/candidates/01-numerical-contract/adapter/PRODUCTION.patch
git apply research/astra20261020/candidates/01-numerical-contract/adapter/PRODUCTION.patch
```

This handoff ran the equivalent check and application in an isolated clean copy
of the recorded source, compared the resulting source byte-for-byte with the
candidate, and checked that the working production source stayed unchanged.
Run that portable verification with:

```sh
python -B research/astra20261020/candidates/01-numerical-contract/verify_adapter.py
```

On the authorized Windows integration environment, use the audited builder:

```sh
python OptiScaler/shaders/shader_tools/build_fsrd_shader.py FSRDColourTrackTrack --dxc OptiScaler/shaders/shader_tools/dxc.exe
python OptiScaler/shaders/shader_tools/tests/test_fsrd_shader_artifact_contract.py
```

The target is `cs_6_2`, entry point `CSMain`, flags
`-enable-16bit-types -O3 -Qstrip_debug -Qstrip_reflect`. Record new source, CSO,
embedded header, compiler executable and DLL hashes. The bundled compiler's
actual tag hashes are in `../evidence/source_inventory.json`; no historical
report's compiler identity is substituted. The Linux task did not execute the
Windows compiler or produce a new CSO/header.

## Acceptance and default-off boundary

Use the baseline and candidate CSOs as separately labeled local test selections.
Leave the user's selected production baseline active until job 08 accepts this
change. No new runtime configuration is introduced by this one-predicate patch.
The integration owner can exercise it in the existing opt-in ColourTrack A/B
path or a standalone shader harness; record the actual selection method.

Run the precise guard microcases in `../GPU_REQUEST.json`, including current
depth `+Inf`, `-Inf`, infinite motion depth, finite inclusive positive/negative
boundaries, inactive history, true viewport exit and poisoned unused resources.
Use separate baseline/fresh-source controls, identical resources/constants and
UAV/fence order. Return intermediate sampled/expected depth and validity bits
from a diagnostic companion, plus the uninstrumented source/candidate history
and gain bytes. A one-ULP allowance must not conceal a changed finite branch.

Check D3D debug messages, descriptor formats, state transitions, UAV ordering,
resource lifetime and complete reset. Any compiled finite-path change rejects
the adapter pending explanation. Actual invalid-depth prevalence in a game is
unmeasured; no FPS or visual benefit follows from the analytic falsifier.

Job 08 remains responsible for its local shader build, GPU parity, AMD RR/game
gate and preserving no-new-grain/sparkles/flicker behavior. The recommendation
for this bundle remains **keep as research** until those gates are observed.
