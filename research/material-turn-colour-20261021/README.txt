Material-aware post-turn input colour: experimental A/B
2026-10-21, source baseline 6d6990f15

Problem and result
The existing 11x11 turn-colour box can copy one surface's lighting colour into
another before RR accumulates it. The new default-OFF option restricts that
existing filter using each lobe's admitted albedo and original normal,
roughness and depth. It does not treat albedo as the desired lighting colour,
demodulate again, alter hit distance, or add a temporal history.

This fixes a demonstrated cross-surface colour-mixing mechanism. It is NOT a
demonstration that the user's broad coloured trails or shadow-like persistence
are solved. The real replay differences are modest; pink/glass/foliage marks
remain. The option is for in-game A/B, not a new recommended default.

Enable "Material edges in turn colour (experimental)" under the existing Turn
colour filter. Both that parent and native material guides must be active.
INI: [FSR-RR] NrdBridgeTurnMaterialFence=true. Default is false. Existing fade
and turn threshold remain authoritative. Thin surfaces may retain more colour
noise. Light changes within the same surface are deliberately not rejected.

Capture and competing hypotheses
- Actual GAME_TRACE c37d3609-a666-4bb6-8b48-39cc07b72b3f, native chain A, 61
  consecutive published frames, 512x512 ROI at (496,167), full render1505x847.
  It is incomplete: bounded CPU staging backlog ended recording, target512.
  It has several fast turns and only short stationary intervals. Hidden prior
  history is unavailable and the first frame is not an actual reset.
- Real guide pixels are present: first-frame diffuse99.9775% and
  specular99.9790% nonwhite; last-frame diffuse99.9931%, specular100%.
  This supplements the earlier successful live reader/admission log proof.
- Material mismatch in temporal reprojection predicted improvement from
  per-pixel rejection. A prototype marking relative-albedo mismatches in
  motion Z affected only about0.1-0.9% of pixels; the RR change did not show a
  persuasive advantage over null-repeat variability. NOT shipped. Adding .5
  to motion Z is also not a universal proof of RR history reset.
- Spatial cross-material averaging predicts colour leakage even without
  history. A fixed-colour two-material GPU fixture reproduces it; gating the
  existing aperture removes that leakage down to half-output rounding.
- Same-material lighting history predicts remaining trails despite good
  material guides. The light-only-edge control remains effectively unchanged.
  Therefore this change cannot be advertised as a general ghosting fix.

Implementation and admission
- Two-hop separable 11+11-tap surface support, 11x11 footprint, 16x16 groups,
  ~28KB LDS. This is not the initial 121-tap prototype. Both hops use guide
  similarity; gradual guide transitions can still connect nearby surfaces.
- No new full-frame textures; reuses existing turn-filter destinations.
  New PSO/root and slot descriptors are lazy and recording-owned.
- Lobe luminance is preserved to FP16 rounding before the existing brightness
  gain; source lighting remains untouched and alpha is copied exactly.
  A finite-half gamut bound reduces chroma interpolation instead of clipping
  channels. No source-albedo-colour multiplication is performed.
- frame.nativeMaterialGuides was only the REQUEST. ConvertedResources now
  carries actual materialGuidesApplied from both conversion paths. New path
  requires both. Failed/missing native capture retains the existing filter.
- GAME_TRACE records requested and frozen actual activation when requested ON.
  Existing OFF metadata and legacy TurnColour shader remain unchanged.

Verification on AMD Radeon RX9070, driver32.0.31021.5001
- 12 actual production shader/host fixtures PASS: independent lobe boundaries,
  flat, light-only edge, depth, normal, roughness, curved boundary, thin strip,
  multiplicative noise, HDR, zero and half fade. Non-multiple-of16 dimensions.
  Debug layer clean; source bytes unchanged, alpha exact, finite output,
  luminance bounded by FP16 quantization. These are fixed-truth mechanism
  tests, not gameplay quality metrics.
- Two-material diffuse RGB relative L1: old0.0617158, new0.00005688;
  specular old0.0598896, new0.00028907. Curved boundary also passed. Do not
  reinterpret those synthetic numbers as a percentage gameplay improvement.
- Actual native reader/coordinator with the option ON:19 signed AMD dispatches,
  359 checks PASS,0 debug errors/warnings,0 borrowed-source transitions.
  Rejection, aliases, stale/cancelled recordings, OFF/ON and recovery covered.
  Synthetic title PSO/readiness adapters remain; not a real-game ON verdict.
- OFF byte proof against6d6990f15:4 profiles x24 frames,312 files,
  28,320,861 bytes identical, including controls/dispatch inputs/title commits.
  Deterministic mock provider isolates wrapper behavior; not a quality proof.
- Menu/INI/save/reload/reset PASS567. Shader artifact contract PASS1001,
  108 headers inventoried,14 fresh compiles, final9036-byte CSO matched header.
  Canonical Windows SDK26100 DXC1.8 used. New CSO SHA256:
  9a23633bd2b9510a477cf39765c46026906fe229de1288b9b6fe05081532f5db
- Builder's general mirror precheck has a pre-existing missing FloorSeed
  namespace failure. New shader was built with --compile-only, then the
  independent artifact contract freshly compiled and compared actual bytes.
  Do not report the general mirror checker as passing.

Actual shader -> signed AMD RR replay
All61 captured frames passed through the exact production old/new shaders,
then RRLab with captured per-frame effective tuning, D16/S256, the recorded
post-turn fade/brightness schedule and native motion. Captured inputs already
include Anchor; it was not applied twice. Original roughness was used.
Two independent old-path runs estimate RR variability. Candidate relativeMAE
is about1.23-3.47%, null repeat about0.60-1.71%. These measure DIFFERENCE, not
improvement. They are not a calibrated ghosting score.
Scope excludes NZR, final remodulation/compositor, hidden pre-capture history
and the unknown initial turn envelope. ROI edges lack outside neighbours.
Images use identical exposure22.13719367980957 and native square ROI pixels.

Isolated GPU timing, median of48 timestamp samples after24 warmup samples
(uploads excluded; larger sizes tile real capture at native pixel scale):
- 512x512: old0.04424ms, new0.08760ms, extra0.04336ms.
- 1505x847: old0.18824ms, new0.36848ms, extra0.18024ms.
- 2560x1440: old0.54948ms, new1.13080ms, extra0.58132ms.
These are pass costs, not a full game FPS measurement. The first121-tap
prototype measured0.27144ms at512x512 and was replaced; its results must not
be mixed with this separable implementation.

Reproduction and local evidence
Repository tests under OptiScaler/shaders/shader_tools/tests/:
  test_fsrd_turn_material.py (set FSRD_GPU_TEST_OUTPUT outside repo; NumPy)
  test_fsrd_nrd_material_reader.py with FSRD_READER_MATERIAL_FENCE=1
  test_fsrd_temporal_off_golden.py with FSRD_OFF_GOLDEN_BASE=6d6990f15
  test_fsrd_nrd_menu_settings.py
  test_fsrd_shader_artifact_contract.py --shaders FSRDNrdBridgeTurnMaterial
GPU runs use the shared GPU lock. Microsoft C++/DXC and signed AMD provider
are required by the relevant fixtures. MSBuild does NOT rebuild these shaders.
Local scripts, captured replay images/animation, logs, prototype counter-tests
and build/delivery records: E:/FSRD/sol_batch/31-material-trails/.
GPU test artifacts: F:/FSRD/sol_batch/31-material-trails/tests/.
No DLL/INI is installed into a game directory by this work.
