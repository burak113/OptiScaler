# Job 03: native colour research return

**Recommendation: keep as research; reject the frozen candidate for production
image quality.** The pink/chroma trail is not established as fixed.

Start with [REPORT.md](REPORT.md) for the mechanism, measurements, negative
controls, limitations and local integration contract. [RESULT.json](RESULT.json)
contains machine-readable provenance and results.

## Reproduce the delivered checks

From the repository root, using Python 3.11 or later:

```sh
python -m pip install -r research/astra20261020/candidates/03-native-colour/requirements.txt
python -B research/astra20261020/candidates/03-native-colour/verify_bundle.py
python -B research/astra20261020/candidates/03-native-colour/run_checks.py
```

The manifest verifier is read-only. The check runner executes the package
validator, four existing CPU suites and 24 new contract/mutation tests, then
checks the retained independent evidence. Its exit 0 means execution and
contracts pass. It reports the retained **quality rejection** separately and
refreshes only its own root-verification receipts.

The independent quality experiment can be reproduced with:

```sh
python -B research/astra20261020/candidates/03-native-colour/review/run_review.py --quality-gate
```

The frozen candidate returns **exit 1**. Run evidence-generating scripts on a
working copy: recomputed wall times and image metadata can change receipt hashes.
The complete experiment and optional plotting commands are in the report.

## Included work

| Artifact | Purpose |
|---|---|
| [native_colour.py](native_colour.py) | Default-off, separate-lobe log and linear CPU models |
| [tests](tests) | Native RGBA word contracts and independent mutation tests |
| [mechanism](mechanism) | Representation, radiance-tail, boundary and confidence ablations |
| [review/REVIEW.md](review/REVIEW.md) | Independent known-bad calibration and falsification |
| [evidence](evidence) | Original baseline logs, inventory, chronological clip results and figures |
| [NativeColourPacked.hlsl](shaders/NativeColourPacked.hlsl) | Uncompiled packed-half shader proposal |
| [INTEGRATION_SPEC.md](adapter/INTEGRATION_SPEC.md) | Exact job 08 adapter specification; production application pending |
| [GPU_REQUEST.json](GPU_REQUEST.json) | Small local canary, ordering and GPU validation requests |
| [BLOCKED_DATA_REQUEST.json](BLOCKED_DATA_REQUEST.json) | Missing observations that distinguish remaining mechanisms |
| [SHA256SUMS.json](SHA256SUMS.json) | All delivered candidate files except the manifest itself |

Base: tag `astra-handoff-20261020`, resolved commit
`5d7839a930106cf8fe1ba8dbbc6750509e7f26a8`.
Branch: `astra/03-native-colour`; PR target: `sol/26-integration`.
No production source or packaged reference is changed. There is no compiled
shader, GPU/AMD RR execution, game result or measured GPU performance in this
return.
