# Job09: default-off native observations and support provenance

This change starts at tag `astra-audit-20261020`, commit
`5fe436dd9a21cb9cc69dec371521a055c9af049d`, and targets
`sol/astra-audit-20261020` for review. It implements diagnostic capture and
portable authority/support contracts. It does not implement the job10 colour
pass, alter filter defaults, install a game/DLL, or claim improved image quality.

## Delivered implementation

- A transient, initially disabled native-observation option in the existing
  bridge GAME_TRACE capture; exact pre-anchor/pre-scale physical words are
  copied before lossy scale/restore, then adopted by the same late frame/fence.
- Explicit word/layout/crop/scale/frame/reset/resource provenance, actual host
  selection authority, opaque alpha and explicit missing title observations.
  Complete post-fence equality guards cannot manufacture selection authority.
- A portable support producer/consumer ABI that checks full-cell geometry,
  every nonzero +/-3-cell estimator donor, all nonzero recalled-key bilinear
  taps, original key validity, epoch/generation/publication and correspondence.
  Production emits invalid support with reasons because that native lineage
  is not exposed. `raw_edit_eligible` stays false.
- A strict offline capture reader, immutable fixture checks, deliberate broken
  implementations, independent lifetime review and a derived Windows/WARP
  recorder acceptance fixture with an explicit synthetic-provider boundary.

See [observation ABI](observation_ABI.md), [support ABI](support_ABI.md),
[host capture, schema and costs](HOST_CAPTURE.md),
[independent review](review_notes.md), [second host review](review_support_host.md),
and [Windows/GPU acceptance recipe](review_windows_recipe.md).

## Reproduce the checks

From the repository root, use Python 3 with the repository's frozen NumPy
requirement and a portable `g++` compiler. The exact requested existing aggregate
command is separate from the new checks:

```text
python research/astra20261020/audit_round2/run_cpu.py --output /tmp/astra09
python research/astra20261020/integration_round2/09-native-observability/run_checks.py --output /tmp/astra09-new
```

The first command needs historical Git object
`5d7839a930106cf8fe1ba8dbbc6750509e7f26a8` for the frozen adapter comparison.
If a shallow clone lacks it, fetch that exact object; do not weaken the
comparison or edit frozen files. The initial missing-object failure is retained
separately in this delivery's evidence.

The new runner executes these component commands with distinct scratch output
directories and records arguments, exit codes, timing and source/log hashes:

```text
python research/astra20261020/integration_round2/09-native-observability/observation_checks.py --output <scratch>/observation
python research/astra20261020/integration_round2/09-native-observability/support_run_checks.py --output <scratch>/support
python research/astra20261020/integration_round2/09-native-observability/review_run_lifecycle.py --output <scratch>/lifecycle
python research/astra20261020/integration_round2/09-native-observability/metadata_compile_checks.py --output <scratch>/metadata
python research/astra20261020/integration_round2/09-native-observability/observation_capture_reader_tests.py --output <scratch>/reader
python research/astra20261020/integration_round2/09-native-observability/review_run_capture_gpu.py --output <scratch>/gpu_prepare --prepare-only
```

`metadata_compile_checks.py` extracts and compiles the **actual unmodified
production serializer helper region** and copy-footprint metadata with portable
POD adapters and the repository's JSON header. It exercises emitted fields,
post-snapshot authority, opaque-alpha equality, scale, crop, optional validity
and carry words. It is not a full Windows source compile or GPU simulation.

The original bottle/foliage sequences retain their chronological single-pass
order and BASE masks. Three original native-policy fixtures retain their masks
and bytes. The existing aggregate independently verifies all 559 imported
candidate files before/after execution. No old evidence is rewritten.

## Recorded status and source binding

The exact executed results, commands and SHA-256 bindings are in
[RESULTS.json](RESULTS.json), the complete [source manifest](SOURCE_MANIFEST.json),
and the text receipts under `evidence/`. Positive suites must exit 0. Deliberate
broken implementations must exit 1 **with actual assertion failures**; that
rejection is the expected result, not a passing candidate implementation.
Captured logs and generated compiler inputs retain their exact bytes, including
tool-emitted trailing whitespace. The source/document whitespace check excludes
these immutable execution artifacts; their receipt hashes remain verifiable.

Linux portable compilation, CPU tests and native fixture source preparation
are the validation scope here. Windows DLL compilation, real WARP recorder
execution, hardware debug-layer validation, actual AMD SDK/provider scale
roundtrip, live reset/resize/device-loss behavior and final-game visual
acceptance remain pending. The prior audit's RX 9070 runs are historical
evidence for a different colour canary, not execution of this host integration.

## Interface for jobs10 and11

Job10 may consume `FSRDNrdObservationContract.h` and
`FSRDNrdSupportContract.h` as documented named-field/in-process contracts and
supply its separate unapplied host adapter. This change owns the observation
callback and capture plumbing only. A later consumer must independently require
valid selection authority, complete support, correct coordinates/epochs/scales
and opaque-alpha preservation. Present captures intentionally cannot authorize
an edit while native donor/key support remains unavailable. Job11 should review
both concrete changes together and run the remaining native acceptance gates.
