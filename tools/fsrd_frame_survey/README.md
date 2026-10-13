# One-frame D3D12 survey

Set `[FSR-RR] FrameSurvey=true` before starting the game. Open OptiScaler's
denoiser settings, expand `GAME_TRACE / Frame survey`, click `Survey next frame`
once and close the overlay. This captures the interval between two real
Presents, independently of the RR owner. Restart after changing the startup key.
The shipped default is false. No denoiser dispatch is replaced by this feature.

The destination is the loaded DLL's directory plus
`GAME_TRACE/FRAME_SURVEY/<uuid>`. A survey uses the existing GAME_TRACE allocation
ledger, submission fences, immutable CPU snapshot worker and disk writer.
`frames/N` refers to a command-list payload, not N consecutive game frames.
Only `manifest_published_frames` is public. Pending folders are forensic data.

Shader SHA-256 values hash actual creation bytecode. Root hashes canonicalize
the creation blob to a version 1.1 serialization; sampler overrides in other
OptiScaler hooks can affect the executed root signature. Creation through a
pipeline library, ray tracing state objects and shaders created before these
debug hooks can have unknown hashes. Resource IDs represent observed creation
generations; pointer values are process local. Bound SRV/UAV views expose
potential access, not proof of individual shader loads/stores.

Snapshots need an observed, valid copy state. Each candidate is copied after
potential writes to its private readback; the last words per list survive placed
resource alias reuse. Submission order chooses the latest list version offline.
Direct-indexed heaps, unbounded descriptor tables, dynamic indirect root views,
enhanced barriers, unobserved state, non-preserving render passes, unsupported
formats and caps produce coverage gaps. Cross-queue submission order is not a
proof of GPU execution order. Render-size candidates have priority; there is no
claim that a global heap was exhaustively enumerated.

Limits: 96 candidate textures; 192 MiB tight candidate bytes plus 64 MiB reserved
for tags within a 256 MiB payload cap; 512 MiB shared retained readbacks;
128 payload lists; 16,384 passes and 8,192 events. Buffer captures are limited to
64 KiB per indirect argument stream and 4 bytes for its count. Up to 64 root-CBV
prefixes of 1 KiB are sampled; they are not a decoded NRD constant ABI.
GPU storage is released after GPU completion and an observed successful Reset,
as required by executable-list lifetime; uncertain storage remains bounded.
One-frame capture can visibly stall because it inserts copies and barriers.

## Analysis

Use the bundled Python and the provided psutil shim, with TEMP/TMP on F:

```powershell
$env:TEMP='F:/FSRD/tmp'; $env:TMP='F:/FSRD/tmp'
$env:PYTHONPATH='F:/FSRD/tmp/pyshim'
& 'C:/Users/burak/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' `
  'F:/FSRD/frame_survey/survey.py' 'F:/path/to/uuid' `
  --output 'F:/FSRD/frame_survey/results/nrd.json' `
  --opaque-roi 'x,y,width,height' --water-roi 'x,y,width,height' --floor-roi 'x,y,width,height'
```

Replace the ROI values with render-space pixels from the actual capture.
Without `--opaque-roi`, ranking uses whole-frame pixels and makes no opacity
claim. The loader checks schema, publication bounds, paths, byte sizes and
SHA-256. It decodes sampled native words, not all images into RAM, and tests every
ordered distinct-resource pair under RGB/YCoCg and demodulated/already-modulated
hypotheses with fixed unit coefficients. Selection and holdout use disjoint
samples. `candidate_inventory` includes potential writers/readers and alpha
percentiles; range alone does not prove normalized hit distance. NRD run labels
are graph/event hypotheses, not a recognized method/version.

No fitted split enters production. A negative applies only to saved candidates
and tested encodings. Capture gaps make a global negative inconclusive.
Two real game captures, verified encoding, repeatable identity and in-game A/B
are required before an NRD-replacement recommendation can become GO.

## Verification

`test_survey.py` plants RGB and YCoCg signal pairs among 17 distractors, a later
water residual, combined-color aliases, already-modulated signals and a negative
case. It checks packed-word decoding, hash integrity and publication boundaries.
`test_fsrd_frame_survey.py` uses the actual production recorder on D3D12 hardware,
a hidden test swapchain, descriptor offsets, indirect argument readback, same-heap
alias reuse and successful Reset retirement. It is not a Cyberpunk capture.

`test_fsrd_frame_survey_wiring.py` compiles the production ResTrack lifecycle
attach/detach call sites and survey wrappers. Real WARP COM Reset, Close and queue
submission calls drive those detours, with no manually invoked lifecycle callbacks.
It reproduced the initial empty-capture bug before the Reset/submit attach fix.
The indirect forward guard suppresses nested runtime helper-list recordings, which
otherwise cannot acquire a title submission fence. The other controlled pass/view
callbacks remain explicit; this is not an exhaustive game-hook integration test.
