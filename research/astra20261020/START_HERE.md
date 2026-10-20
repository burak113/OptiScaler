# FSRD: audited source and cloud research handoff — 2026-10-20

This package is for CPU research and code proposals on GitHub. It does not contain
a Windows game, AMD RR runtime, complete game captures, or a converged reference.
The owner runs GPU and in-game acceptance locally. No account subscription or
tool capability is assumed.

Repository: https://github.com/burak113/OptiScaler
Research base tag: `astra-handoff-20261020`
PR target branch: `sol/26-integration` (never the default master branch).
Frozen production source commit: `87e8b7ab2a428bd91d3c044decf7d4dbccd8cefd`.
The handoff commit adds research data/documentation; it changes no production
algorithm. Earlier authorship labels and "completed" reports are not evidence.

Start with [the protocol](COMMON_PROTOCOL.md), [verified findings](FINDINGS.md),
[data contracts](DATA_CONTRACT.md), and [return format](RETURN_PROTOCOL.md).
Use [eight task prompts](PROMPTS.md). Tasks 01–07 may run independently on branches
from the tag. Task 08 may build acceptance tools immediately, but integration
requires the actual resulting revisions and the local GPU verdicts.

## Run the portable calibration

Python 3.11+ and NumPy are sufficient. From the repository root:

```sh
python -m pip install -r research/astra20261020/requirements.txt
python research/astra20261020/validate_package.py
python research/astra20261020/run_cpu.py
```

Tests are expected to **demonstrate existing defects**, not hide them. A passing
test of a biased estimator means the baseline's bias was reproduced. The CPU
runner never runs the repository's Windows/D3D12 GPU drivers. Read each fixture's
provenance: some files are shader fields, others are captured native inputs, and
one colour fixture contains CPU-warmed history followed by one GPU frame.

## Architecture and source entry points

All paths below are repository relative. Find them by basename with `git ls-files`
if another branch rearranges the tree. Start in
`OptiScaler/shaders/fsrd_preprocess/`:

- `FSRDNrdPostMotionAnchor_Dx12.h`: native private D/S input copies, resources,
  ownership and dispatch integration.
- `precompile/FSRDNrdPostMotionAnchorStatsRecall.hlsl` and
  `precompile/FSRDNrdPostMotionAnchorGain.hlsl`: native statistics/recall and gain.
- `precompile/FSRDPostMotionAnchorApply.hlsl`: shared spatial gain application.
- `precompile/FSRDColourTrack*.hlsl`, `FSRDColourTrackConstants.h`: combined-path
  chroma history. These are not an already-integrated native D/S solution.
- `precompile/FSRDPostFlick*.hlsl`: combined-path history experiment.
- `FSRDGameTraceSession.cpp`: native stage and mixed-extent trace contracts.
- Search `BridgeRR`, `Bridge`, and `Service` implementations for source routing,
  G2/G3, NZR, frame history and the shared family budget. Read actual call sites.
- `OptiScaler/shaders/shader_tools/tests/`: existing production host/ABI,
  D3D12/WARP and GPU tests. Many Python files here launch GPU tools; their
  extension does not make them cloud-portable.

The four user captures use the native NRD bridge. Original PostFlick,
ColourTrack and Anchor were combined-path preprocessors. Task 26 added native
Anchor; PostFlick and ColourTrack remain combined-only. Never claim a combined
result improves native output without an adapter and a local native-path test.
Native Anchor produces private D/S textures consumed by RR and NZR; G3 reads
the original inputs. Preserve this domain split and alpha/hit-distance values.

## Protected working configuration

Keep the user's D16/S256, G2/G3, RR Fallback, Diffuse RR and Reflection History
enabled, and NZR Temporal disabled. Old turn filters, Anchor, PostFlick and
ColourTrack remain OFF in the recommended preset. Glass Blend 0.5 is a local
A/B recommendation with a detail trade-off; 0.75 is the less soft alternative.
New experiments must be default-off. CPU plots cannot override in-game feedback.

## What is bundled

- `portable/anchor`: frozen NumPy estimator, actual shader grids and falsifiers.
- `portable/colour`: frozen numerical reference, one real calibrated frame and
  synthetic edge/FP16 adversarial controls.
- `fixtures/clips`: chronological bottle, foliage and facade crops, with raw
  fields and changing crop origins where required.
- `fixtures/glass`: fixed-support glass experiment and reconstruction code.
- `evidence`: sanitized local audit receipts and source hashes. These are
  historical evidence, not tests newly executed in the cloud.
- `images`: a few same-exposure comparisons. Full frame animations, full captures,
  machine memory, compiled DLL and large local replay caches remain local.

Each file's package hash is in `MANIFEST.json`. Fixture provenance is more
specific than this overview and takes precedence when stating coverage.
