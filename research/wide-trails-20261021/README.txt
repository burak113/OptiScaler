Broad coloured trails and shadow-like persistence: research, no promotion
2026-10-21. Source baseline 605c785bb7ebe4cd5e9e28613a738b7d47461206.

Decision
No candidate in this research batch met the acceptance requirement. No runtime
source, shader, default, game installation, or production DLL was changed.
The previous material-aperture A/B remains separate. It does not solve these
broad same-surface trails. This folder records rejected experiments so they
are not accidentally presented as completed quality features later.

User priority: coloured trails and shadow-like persistence, especially floors,
walls and newly revealed regions. Preserve real light, material colour, detail
and temporal stability. No subagents were used for this research batch.

Evidence scope
The new c37d3609 trace contains actual nonwhite albedo guides, 61 consecutive
published frames and only a short stationary interval after the last turn.
It is an incomplete 512-frame recording: bounded staging backlog stopped it.
Its captured lighting is AFTER Anchor and BEFORE the turn filter/brightness
gain. Replay uses the previously GPU-generated exact old-filter inputs from
task31, plus the captured effective tuning. Anchor is not applied twice.
Earlier 87ee,22f9,2405,d6d2,f2ef,06fa captures are controls, not substitutes for
a longer current trace. Most older natural postfilter tests use captured raw
input/output; f2ef has its own turn-filter mismatch. These caveats rule out a
single aggregate "game quality improvement" percentage.
The cropped replay starts with fresh RR history and cannot recover pre-capture
or off-ROI history. Compare replay variants to the matching replay baseline,
not directly to recorded raw RR as though they were identical executions.

Captured raw RR already has pink/level bias before the selected-output path.
For example the camera-aligned 87ee late-window red share differs between
input and raw RR, while selected diffuse matches raw. c37d is not globally
too bright; indiscriminate darkening would be wrong. Albedo is a guide, not
the desired lighting colour; no test divides native lighting by albedo again.

All photographic panels use a shared exposure within each comparison. They
show demodulated RR lobes or their sum, NOT the game's final compositor.
Camera warps do not align animated objects. Late input averages are noisy
diagnostic targets, NOT ground truth. Fixed interior masks avoid borders but
do not turn these short/noisy captures into ground truth. Post metrics use
absolute second temporal differences to separate rapid variation from an
intended slow correction; this remains a diagnostic, not a perceptual score.

Competing mechanisms and outcomes
1. Illumination normalisation around RR: divide diffuse by a Gaussian32 RGB
   envelope, denoise the remainder, multiply the envelope back. This tests
   whether the slowly changing illumination representation causes lag.
   Real signed AMD RR light/chroma steps become much faster. However broad
   temporal standard deviation rises 3.27x on c37d,2.92x on87ee,5.80x on the
   static d6 control. Rejected: restores noisy low-frequency illumination.
   Repaired benchmark errors: 87ee initially used mismatched tuning; it was
   rerun with matching adaptive tuning. c37d metric target initially used
   pre-turn captured input; final metrics use the actual filtered input.

2. Spatial Haar innovation: shrink multiscale input-minus-RR differences
   according to input sample variance. All bands leaked grain; restricting
   to >=16px bands left weak correction or residual colour fluctuation.
   Current source/control JSON describes the restricted version, not the
   earlier all-band trial. Rejected, no shader port.

3. Global coherent colour drift: require tile sign agreement before a robust
   log-chroma correction. Mostly inert in current/other controls and cannot
   safely assume that every material shares the same lighting bias.
   Rejected for insufficient general benefit/protected local-colour risk.

4. Temporal coarse innovation: camera/depth validated input moments followed
   by variance-thresholded coarse Haar residuals. Direct additive correction
   reduced the noisy target discrepancy but increased colour flicker. A
   multiplicative, slowly changing gain better preserves fine texture, yet
   delayed a local light step which RR already tracked correctly.

5. Light-change guarded coarse gain: withdraw stale correction on significant
   input change. The local3x light test's mean relative endpoint distance over
   first32 frames is .01731 baseline,.05489 unguarded,.01666 guarded. Thus the
   particular local-step regression was fixed. Whole-field half/1.1x/chroma
   changes improve as well, but natural87ee/22f9 colour second-difference
   increases24.3%/29.1%. Inspection also shows new broad patch boundaries.
   Rejected despite lower input-average error. Synthetic controls use6
   independent heavy-tailed noise streams and3 edge phases. Their protected
   stripe was not separately scored; they do not prove full detail safety.
   Natural preparation encountered a GPU-helper device removal and completed
   with CPU fallback. These exploratory mixed-backend outputs are NOT final
   acceptance runs. CPU guard-step controls completed cleanly in isolated
   files. A separate failed run collided on an intermediate filename; the
   script now separates natural and step tags. The failed run is excluded.

6. Diffuse-only RR context: tests cross-lobe context coupling, without any
   lighting-output correction. Three fresh signed-provider runs complete.
   The separate context changes diffuse, but87ee red share .3736->.3731 does
   not resolve the pink bias. On static d6, broad second-difference is2.05x
   and colour second-difference2.33x the matching joint-context replay.
   Rejected. Previous task23 measured split-context performance cost, not
   this quality test. Those historical cost measurements are not rerun here.

7. Sum-preserving bright-tail split: split diffuse at fixed luminance caps
   .02/.08/.32 into core and residual, denoise each in its own diffuse-only
   context, add outputs. The input split preserves RGB sum mathematically;
   each branch is separately quantised to FP16. No energy is deliberately
   discarded. Eighteen fresh signed-provider runs complete: three caps,
   two branches, three captures (1530 ordered frame dispatches).
   Cap.02 on c37d raises broad second-difference2.08x versus joint replay;
   cap.08 raises low-band target discrepancy2.15x and reduces measured detail
   to.779. Other caps/controls trade noise, level and detail rather than
   removing the pink bias. Rejected. The joint->diffuse-only context change
   itself contributes to these differences; tail-metrics retains BOTH
   baselines. Do not attribute all differences solely to the split.
   The actual inputs contain no negative RGB components; float32 core+tail
   equals input exactly on the tested frames. Separate FP16 branch rounding
   contributes at most0.0105% relative L1 input error across these cases.

Signed GPU execution and provenance
After a helper error0x887a0005, no reboot/driver/system/Parsec changes were
made. The user reported a contemporaneous Parsec attempt; causality is NOT
established. A small production-shader health test passed with0 debug errors
and0 warnings. A fresh4-frame AMD-provider health replay then completed with
finite outputs. Subsequent context/tail jobs ran serially under the shared
GPU lock; preparation/metrics used RRLAB_GPU=0. Incomplete/failed executions
are not acceptance evidence. The provider DLL is unchanged and signed.
No production build was necessary because no production source changed.
Task31's DLL/build/test results must not be advertised as this batch's tests.

Reproduction and layout
Working data: E:/FSRD/sol_batch/32-wide-trails. Shared harness: E:/FSRD/rrlab.
Captures: F:/Ultra Yedek 2/overwrite/bin/x64/GAME_TRACE/<uuid>/capture.json.
The repository snapshot includes scripts, result JSON, selected panels and
hash provenance, not multi-GB captures/arrays/cache or provider binaries.
Scripts have explicit local paths; adjust these together when relocating.
The shared harness source snapshot is included for audit, not automatically
installed over the live harness. Full GPU replay needs the original traces,
task31 gpu-old.npy, Windows D3D12, AMD RR provider and SDK headers.

Set TEMP/TMP=F:/FSRD/tmp, OPENBLAS_NUM_THREADS=2, RRLAB_GPU=0.
Use bundled Python with NumPy and Pillow. Commands, in the working folder:
  python gpu_health.py
  python make_diffuse_runner.py
  python diffuse_context_probe.py
  python tail_split_probe.py
  python measure_tail.py
  python guard_probe.py steps
  python guard_controls.py
  python step_summary.py
  python measure_post.py
  python measure_normalize.py
normalize_probe.py creates normalisation inputs/replays; its step preparation
is in measure_normalize.py steps. Avoid concurrent jobs writing the same
capture/tag. Natural guard generation was exploratory; rerun cleanly before
any future attempt to promote that family.

Next evidence needed
A longer consecutive current-settings trace after a turn, covering several
seconds of the affected floor/wall, is needed to distinguish persistent input
bias from RR recovery and validate motion/light response. This short trace
does not justify declaring the problem fixed. Do not reuse a looped static
replay as evidence for camera-turn/disocclusion quality.

Primary references used for hypotheses, not implementation-equivalence claims:
https://research.nvidia.com/labs/rtr/publication/schied2017spatiotemporal/
https://www.momentsingraphics.de/HPG2018.html
https://gpuopen.com/manuals/fsr_sdk/techniques/denoising/
Adaptive temporal-gradient resampling in the cited paper requires control of
the path tracer's random samples. This project does not have that control;
the noisy input-difference guard is NOT that paper's gradient estimator.
