# Independent skeptical review — job 07

## Decision

**Keep the observation-only candidate as research. Reject the experimental cosine-history consumer as an image-quality feature on the present evidence.** The observer measures original-guide variation and numerical comparability while preserving the supplied inputs. It does not establish that a pixel contains foliage, recover minority layers, verify physical history, or improve captured AMD RR output. Native integration remains unimplemented and local shader compilation/parity/GPU/game acceptance is pending.

The distinction matters here: the frozen held-out CPU consumer recovers a little detail relative to an already destructive surrogate baseline, but raises sparkle and flicker. The pure diagnostic leaves RGB unchanged, so it has no measured denoising gain to promote. No production file or packaged baseline was changed by this reviewer.

Reviewer: `/root/skeptic`. Immutable handoff: `5d7839a930106cf8fe1ba8dbbc6750509e7f26a8`.

## Independence and evidence order

Before opening candidate source or receiving a claimed result, I implemented and ran the independent facade/window/text destruction control in `blind_calibration.py`. The control, three seeds, fixed masks, scorer mutation, and review gates were recorded in `BLIND_REVIEW_PROTOCOL.md`, `blind_calibration.json`, `calibration_run_receipt.json` and `adversarial_plan.json`. Root then released the implementation for review. The independent probe seed 924619 was frozen at that stage.

I did not tune the candidate or edit its implementation. I reported specific faults to the implementation/root owners, who repaired them before the main sweep. Those were correctness, identifiability and reporting repairs, not threshold changes in response to held-out wins. The subsequent full benchmark replay recorded unchanged before/after hashes for the runner, observer, generator, proxy, and protocol.

### Blind known-bad control

The independent transparent CPU surrogate applies a normal-gated 5x5 local estimator to a static relief facade, narrow windows and FSR glyphs. Flattening only the normals admits more cross-boundary samples. Raw radiance, exposure, three noise seeds, 24-frame chronology, masks and truth-derived detail denominators remain fixed.

| Effect of flat normals versus exact normals | Range across three frozen seeds |
|---|---:|
| Flicker RMS ratio | 0.7173–0.7264 |
| Sparkle p99.5 ratio | 0.6179–0.6511 |
| Signed detail-transfer ratio | -0.082 to -0.081 |
| Edge-error ratio | 11.74–11.81 |

The wider admitted box footprint even inverts some thin periodic contrast. A noise-only scorer accepts every destructive case; the proper scorer rejects all three. The explicit `--mutant-ignore-detail` correctness command exits **1**, with `MUTANT CAUGHT`, as expected. Normal tests pass. This is a demonstrated rejection of a false win, not a successful mutation run.

The original native NormalEMA .25 loss of **22–27% facade detail** is historical package evidence (`research/astra20261020/FINDINGS.md` and `research/astra20261020/evidence/historical/task26_report.txt`, relative to the repository root). I did not re-execute that AMD experiment. The CPU control reproduces the mechanism and checks the scorer; its magnitude and estimator are different. The main synthetic suite independently reproduces the direction of facade loss: flat-normal detail transfer is 0.35010 versus 0.44708 in the static rigid control, and 0.30303 versus 0.37353 in the moving control. These are also CPU-surrogate results.

## Review findings and repairs

All line references below are to the frozen candidate source reviewed with the hashes in the receipts. They are new research-code findings, not claims of previously unknown production bugs.

| Finding | Concrete failure or confound | Resolution and verification |
|---|---|---|
| NumPy flag mutation failed immediately | In-place OR of `IntFlag` into a uint16 array raised `UFuncOutputCastingError` on NumPy 2.3.5 during the first enabled `observe_guides()` call. | Every flag operand is now explicitly uint16 in `src/foliage_guides.py`, `observe_guides()` starting at line 135. The independent enabled-API/input-byte regression passes. |
| Invalid predicted depth could manufacture support | With default tolerance .02, finite `d=previous_d=1e-10`, `MV.B=-2e-10` produced negative predicted depth but marked 24/35 pixels comparable. Finite float32 `3e38+3e38` overflowed to infinity and also passed the comparison. | The observer now requires finite positive `d+MV.B` before depth evidence or temporal support, uses a safe comparison value, and leaves unsupported multiplier at identity. Independent negative/overflow regressions pass. The overflow input is an API adversary, not a claim about bounded captured FP16 motion. |
| Detail metric depended on orientation | The first metric used only horizontal differences. A perfect image varying only in y had zero denominator and falsely reported zero transfer. | `src/proxy_metrics.py:139`, `gradient_transfer()`, combines x/y covariance and energy using fixed directional masks. Independent x/y/diagonal identity and destroyed-detail tests pass. Constant truth returns unavailable detail/gate rather than fabricated evidence. |
| A layer mean was mislabeled an exact selected guide | Background normals/depth were unconditional subpixel averages while visible lighting was conditional on visibility; the background can itself contain window/frame/sky facets. | `src/synthetic_scene.py:104`, `generate_scene()`, now supplies an actual selected-layer subpixel witness for the observed single guide. The unquantized ablation removes packing error from that witness. Oracle background buffers are explicitly described as layer moments, not perfect composite per-sample geometry. |
| Observation selection changed the noise realization | Coverage and stochastic guide selection consumed the lighting RNG stream, confounding a one-family intervention. | Separate SeedSequence streams for coverage, guide choice and lighting preserve common lighting inputs when guide observation changes. The final generator and source hashes were frozen before the full replay. |
| Captured reporting could imply unsupported evidence | A zero temporal innovation sentinel entered fixed-pair summaries; same-index lag correlation could be read as material-point/noise correlation; executor was hardcoded. | Root retained fixed-pair denominators, added supported-only conditional counts/distributions, labeled the lag as crop-index/Eulerian, qualified sanitized depth and added explicit executor attribution. |
| Experiment count could be overstated | 51 protocol rows include repeated OFAT reference rows and identical constructed controls. | `DEDUP_AUDIT.json` verifies **40 unique input realizations and 40 unique input+truth pairs**, with identical truth/masks within every repeated group. The nine held-out rows are distinct. Row-weighted and deduplicated summaries are separately labeled. |

The independent contract tests also check signed previous-minus-current MV.B, full-render UV displacement plus moving crop origins, first-frame absence, reset/gaps, unknown depth convention, OFF, out-of-crop history, nonfinite motion, all four category codes and known octahedral normals. They check actual input bytes, including an unusual motion-A payload. The input-only observer never receives D/S radiance or hidden layer truth; captured analysis additionally hashes every supplied source array before/after the call.

## Independent replay of the complete CPU sweep

I ran the final `run_benchmark.py` over all **51 protocol rows / 40 unique input realizations**, with `--executor /root/skeptic`, in **55.59 seconds**, exit code 0 and no stderr. All source hashes were identical before and after execution. Every case payload and the entire protocol-row summary matched the implementation owner's refreshed result exactly. The full evidence is `synthetic_replay.json` and `synthetic_run_receipt.json`.

The held-out seed/trajectory/phase/orientation family contains nine distinct cases. The table shows their arithmetic mean. These metrics are normalized against fixed analytic truth and refer to the disclosed CPU surrogate, not native RR.

| Held-out metric | Single observed guide surrogate | Cosine-history consumer | Flat-normal negative control |
|---|---:|---:|---:|
| Grain high-pass RMS | 0.22419 | 0.22541 | 0.18764 |
| Absolute-error p99 sparkle | 0.95624 | 0.97038 | 0.74442 |
| Residual-difference flicker RMS | 0.26125 | 0.26261 | 0.22460 |
| Detail-gradient transfer | 0.40007 | 0.41289 | 0.31698 |
| False-history-support fraction | 0.025592 | 0.025592 | 0.025704 |
| Current cross-layer mixing-weight proxy | 0.038370 | 0.038345 | 0.041675 |
| Paired light response, first four changed frames | 0.58807 | 0.61330 | 0.59419 |

The consumer's worst held-out sparkle increase is **3.80%** on `holdout_facade_17713`; worst flicker increase is **1.52%** on `holdout_facade_9001`. All three filtered variants shown fall far short of the frozen 0.95 truth-detail gate. A lower aggregate score does not reverse those failures. The raw/diagnostic-identity path retains exactly the same samples and therefore exactly the same metrics; it is not a denoising improvement.

The leakage quantities count current spatial/temporal mixing decisions; they are not a complete measurement of accumulated physical radiance leakage. Oracle modes consume hidden per-layer radiance and current exact coverage. Their zero cross-layer bookkeeping does not certify all fine background facets, and their reconstruction still fails the detail gate. The main scene's small per-layer-motion improvement cannot establish that motion is unimportant in the game; an analytic motion discriminator can identify representational ambiguity, but remains a separate construction.

## Additional independent falsifiers

`independent_probes.py` uses the independently frozen seed and cases from `adversarial_plan.json`.

**Identical observations, different composite history.** Two analytic worlds share every normal/depth/material/MV/metadata input. One has constant RGB. The other keeps the same dominant foreground guide while foreground coverage changes from .6 to .8 over a differently colored secondary layer. Maximum RGB change is approximately .08. The observer returns identical fields and multiplier 1 on all 77 comparable pixels in both worlds. Thus numerical agreement cannot certify composite history or infer minority coverage/motion. This is an explicit observational collision, not a poorly tuned threshold.

**Lighting changes while guides stay identical.** A static, fixed-coverage scene is evaluated with independent noise, correlation .95, and a true 1.1x light step. Guide words and all observer outputs are byte-identical across these interventions. Independent versus correlated raw residual flicker changes from 0.9592 to 0.2687 while grain remains 0.7566 versus 0.7234. A guide-only statistic cannot infer that lighting distinction. These are synthetic interventions, not evidence that a particular native sampling algorithm caused the captured foliage artifact.

The explicit decoder calibration also separates numerical encoding from coverage: the correct 10-bit oct decode has a maximum angular error of about .14265 degrees on the ten known-normal controls, while the deliberately wrong XYZ interpretation has mean error about 58.51 degrees. A uniform wrong decoder could still look temporally coherent, so coherence is not a substitute for this numerical contract.

## Captured controls and their limits

The final captured replay uses unchanged masks and the recorded original crop-origin formula. It ran with explicit reviewer attribution, with unchanged before/after analyzer/observer hashes, in approximately 3.37 seconds, exit code 0. Evidence: `capture_replay/captured_with_candidate.json` and `captured_run_receipt.json`.

| Original-guide clip | Fixed available-pair pixels | Numerically comparable fraction of that support | Mean spatial angular dispersion on that support |
|---|---:|---:|---:|
| Foliage, frames 43–65, 192×64 | 247,740 | 0.51878 | 0.24432 |
| Facade, frames 34–49, 96×96 | 126,960 | 0.94873 | 0.09725 |
| Bottle, frames 180–186, 128×256 | 141,929 | 0.45907 | 0.02942 |

No numerically comparable pixel was produced outside the fixed available-pair region, and first-frame history is absent. The output records conditional comparable-only innovation distributions in addition to the fixed-pair summaries. All source arrays remain unchanged. These values describe variation and numerical support; they do not label foliage or demonstrate captured output improvement. A moving crop is not a motion vector, and the short supplied windows do not recreate the RR history that preceded them.

The package also permits a **separately labeled prepared-guide glass control**. Its `original_*` guide arrays are unwarped copies of `input_normal_roughness`, whereas RGB/common masks are camera-aligned. They are not the pre-Flat `recovery_original_normal_roughness` source required by the live proposal. I ran `glass_prepared_control.py` on frames 46–63 at render origin [546,347], crop 192×160, using an independently frozen six-pixel unwarped rectangular halo and original positive finite depth. No aligned mask was used on the guide grid.

That independent glass control preserves every source array byte, has comparable fraction 17/18 on its fixed core (only the first frame lacks history), mean dispersion .01222 and mean multiplier .98275. It does not measure a glass image-quality improvement or validate the proposed original-guide host source. Root's glass control uses a separately disclosed two-pixel core; its counts must not be substituted for the reviewer's six-pixel mask. The historical aligned raw-versus-selected glass reconstruction remains a different stage and selected is old NZR, not converged truth.

The provider depth/motion fields may already be sanitized/clamped or affected by G3 source selection. The missing raw depth-validity class and original pre-G3 MV remain unresolved. Positive stored numbers and agreeing guides do not prove physically valid geometry. This limitation is retained in the source authority, support descriptions and data request.

## Adapter review

I reviewed `adapter/FoliageGuideObservation.hlsl`, `HOST_INTERFACE.h`, `INTERFACE.json`, `BUILD.json` and `PRODUCTION_SPEC.md`. No blocking source/interface inconsistency remains in the submitted proposal, but there is no executable host integration or shader/GPU parity result to approve.

The proposal uses five read-only inputs and two distinct sidecar UAVs, a 64-byte/16-DWORD constants ABI, and explicit point reads with written bilinear weights. Original normal, depth, motion, material codes, roughness and signal alpha are not output channels. Unsupported evidence retains identity and is explicitly distinguished from measured agreement. The host specification addresses typed/initialized descriptors, device/extent/format admission, original-versus-provider source authority, private immutable snapshots, source-state restoration, abandoned command lists, per-context generations and fence-retained ownership. Job04 transport keeps categorical flags distinct from interpolated observations; job08 may integrate only after local gates.

The C++ layout check is useful ABI evidence only. The HLSL remains pending `cs_6_2`, `CSMain`, `-HV 2021 -O3 -Gis`, DXIL/reflection and local parity. Its native input/output identity, allocation/copy cost, GPU timing, descriptor/resource lifetime behavior and game video are unmeasured. New memory-cost formulas are not resident-VRAM measurements.

## Required next gate

Retain this as an observation/debugging research bundle. Do not install the cosine number as an AMD, G3, native material, roughness, MV or depth-validity channel. A later filtering consumer is a new candidate and requires a new result under the existing fixed detail/noise controls.

The smallest useful next evidence is the chronological original bridge guide/physical-lobe/source-selection capture and native standalone observation parity specified in `GPU_REQUEST.json` and `BLOCKED_DATA_REQUEST.json`. It must include the raw validity/source witnesses needed to separate decoding, coverage, transport and lighting. The protected facade/text/sky/bottle/glass controls and final matched video still apply. A CPU observer, analytic counterexample, passing unit test or C++ struct compile cannot waive this gate.

## Reviewer commands and receipts

From the repository root:

```sh
python -m unittest discover -s research/astra20261020/candidates/07-foliage-guides/tests -p 'test_review*.py' -v
python research/astra20261020/candidates/07-foliage-guides/review/independent_probes.py
python research/astra20261020/candidates/07-foliage-guides/review/glass_prepared_control.py
python research/astra20261020/candidates/07-foliage-guides/run_benchmark.py --executor /root/skeptic --output research/astra20261020/candidates/07-foliage-guides/review/synthetic_replay.json
python research/astra20261020/candidates/07-foliage-guides/analyze_captures.py --with-candidate --executor /root/skeptic --output-dir research/astra20261020/candidates/07-foliage-guides/review/capture_replay
```

The ten reviewer tests pass. `final_cpu_receipt.json` contains the final contract/probe/glass commands, exit codes, elapsed times and unchanged source hashes. The blind mutant's expected failure is separately preserved in `calibration_run_receipt.json`. Full benchmark and captured replays have their own before/after hash receipts. `DEDUP_AUDIT.json` verifies the sample-count interpretation without changing or retuning the frozen runner.
