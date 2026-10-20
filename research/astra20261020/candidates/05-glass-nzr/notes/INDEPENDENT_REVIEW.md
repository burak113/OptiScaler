# Independent skeptical review — workstream 05

Reviewer: `/root/skeptical_review`, cloud Linux CPU.

## Separation from candidate tuning

Before reading candidate source, results, or its proposed mechanism, I reproduced the frozen rejected soft2 control and the recorded glass trade-off. Only after sending those results to the parent did I receive the proposed mechanism. I do not tune its parameters or choose its favorable seeds.

The immutable tag resolves to `5d7839a930106cf8fe1ba8dbbc6750509e7f26a8`. All commands below ran against unchanged baseline files with NumPy 2.3.5 and Python 3.12.14. GPU execution: **false**.

## Known-bad control, before candidate exposure

`python research/astra20261020/portable/colour/compare.py --quality-gate` returned **1**, as required, in 2.430079 s. The rejected soft2 candidate worsened six of 32 synthetic edge phases. At phase 4, depth-edge bleed was 0.05717988 → 0.09770542; normal-edge bleed was 0.05717988 → 0.09826054. This is an independently rerun CPU falsifier, not the historical GPU test.

`python research/astra20261020/fixtures/glass/glass_fixture.py analyze` returned **0** in 0.310955 s. The fixture contains 6,497 fixed eligible pixels from frames 46–63, not the historical full-ROI 8,048-pixel support. It reproduced NZR temporal CV 0.08453058 versus Blend.5 0.06051007, accompanied by detail proxy 0.0006692721 versus 0.0004747073. This verifies a trade-off, not a lossless improvement.

Exact commands, exit codes, durations, output hashes and full outputs are recorded in `evidence/reviewer_controls.json`, `evidence/reviewer_known_bad_soft2.log` and `evidence/reviewer_glass_calibration.log`.

## Metric calibration nulls, before candidate exposure

The same frozen 6,497-pixel mask, frame order and current equal diffuse were used for all variants. Spatial sigma-2 blur reduced high-pass CV from 0.03238877 to 0.01686412 while reducing detail from 0.0006692721 to 0.0002760848. Holding only the specular image at frame 46 scored even lower fine temporal CV, 0.02590319, while ignoring all subsequent specular changes. Its mean absolute deviation from current selected specular was 0.0006596751. Results are in `evidence/reviewer_metric_nulls.json`.

Consequently a lower noise proxy, even together with a surviving temporal-mean detail proxy, cannot establish current-scene correctness. Known lighting/colour response and moving thin-feature tests are mandatory.

## Independent challenges fixed before candidate results

- OFF, missing sidecar, invalid provenance/count/variance, empty/partial blocks and non-specular channels must preserve the authorized baseline exactly.
- Crossing normals/depth and newly visible glass must not borrow from incompatible block support. Low-count startup and resets must not manufacture support.
- Every subpixel/block phase of a thin sign/glint must be tested with immutable truth masks. A stateless filter can still create phase-dependent flicker.
- Under correlated noise, the covariance assumptions are an observable requirement. A supplied variance derived under independence cannot establish native uncertainty.
- A true moderate light/colour step and abrupt reflected-feature movement must be evaluated for present-frame error and phase-dependent attenuation, without stale history receiving stability credit.
- Competing controls must be compared at similar retained detail and response; dominance only against unscaled NZR is insufficient.
- Raw RR, selected RR and their difference cannot universally distinguish an isolated real glint from an identical stochastic outlier. An observationally identical counterexample will bound any general detail-preservation claim.

## Candidate review and recommendation

**Keep the deliverable as research; reject shipping the proposed Haar intervention as a visual improvement.** The implementation has useful conservative contracts, but an independent experiment exposes a phase-dependent thin-sign failure and the recorded data do not provide its required uncertainty sidecar. No native quality, GPU execution, or full-game performance is established.

### Concrete thin-feature counterexample

I used 128 independently seeded RGB-noise realizations (`51000`–`51127`) at each of four fixed block phases. The scene is a two-pixel-wide bright line, amplitude 0.06 above a 0.4 background, with IID channel noise sigma 0.04. The raw RR control lacks the line. Truth masks are fixed before noise generation and before invoking the candidate. The same noise realization is reused only across each paired phase intervention, while all 128 independent seeds remain distinct.

| Block phase | Mean recovered line amplitude | Retention of true line amplitude |
| --- | ---: | ---: |
| 0 | 0.05940392 | 99.0065% |
| 1 | 0.04907531 | 81.7922% |
| 2 | 0.05934445 | 98.9074% |
| 3 | 0.04925903 | 82.0984% |

The line retains different contrast solely because it crosses a 2×2 transform boundary: a **17.2144 percentage-point modulation**. The maximum whole-image RGB-sum difference from selected in any trial was below `9e-7`. Thus conserving the block low band does not prevent movement from producing contrast flicker. These are a controlled synthetic phase sweep, not a claim that a captured game flickers by this amount. They suffice to reject general claims of simultaneous temporal stability and thin-sign preservation.

### Noise covariance and glint ambiguity

A second independent 128-seed experiment (`65000`–`65127`) used coherent alternating noise within each block. Its per-pixel marginal variances match the IID sidecar, but its actual high-band noise energy was **3.9469×** the supplied IID estimate. Correctly marking `independent_spatial=false` retained selected RGB bit for bit. Claiming independence without evidence underestimates this noise. History count or per-pixel variance alone cannot fill this requirement.

An isolated positive 0.08 feature above a uniform true 0.005 correction is observationally identical whether the feature is a true reflection omitted by raw RR or a stochastic outlier. Every original tap differs from raw RR, so this witness satisfies the adapter's BASE-changed eligibility requirement. The uniform correction and peak reference are fixed before candidate evaluation. With the same finite inputs and sidecar, the candidate reduced the incremental feature peak to 0.02 and distributed its low band within the block. This is a **75% loss of the true peak** in the signal world. Neither possible truth is supplied to the estimator, so the probe does not claim either interpretation for real glass. It falsifies universal glint-preservation claims based on these observables. An earlier generic-API version left three neighbours unchanged relative to raw, where the proposed adapter would abstain. Its measurements are retained as `evidence/reviewer_adversarial_measurements_api_only_v1.json`; adding the common correction fixes that applicability limit and preserves the measured 75% incremental peak loss without changing the candidate.

### Contracts and fault injection

The independent suite contains 11 tests. It checks OFF and missing-evidence bit identity, low counts, NaN/Inf uncertainty/count, invalid/new-view support, geometry partitions, odd DRS extents, current-frame light/colour response, zero-noise behavior, raw/current alpha word preservation, immutable inputs, and existing Glass strength semantics. It also **expects and records** the phase, covariance and ambiguity counterexamples above; a green test run is not acceptance.

The normal test command returned 0. The explicit `--mutation-alpha` command returned **1**, as intended, after substituting selected alpha for original raw/current alpha. The failure proves that the independent contract test detects an actual channel-authority violation. Exact commands, elapsed times, source/test hashes and expected exit codes are in `evidence/reviewer_adversarial_runs.json`; full test and mutation outputs remain alongside it.

The test takes current source inputs and has no access to native geometry transport. “Crossed geometry” means the producer correctly supplies different support partitions; it does not prove that a production producer can identify those partitions. Likewise DRS/reset tests exercise rejected or mismatched support semantics, not real D3D resource lifetimes.

### Source-shaped H1–H4 probes

I reviewed `src/native_subset.py`, `experiments/causal_probes.py` and their tests against the tagged Seed, History and HybridPrep shader formulas. The centre-conditioned first fit, second Tukey fit and centre fallback match the intended bounded Seed subset. The flat supplied support and float64 fitting are arithmetic diagnostics; they omit the actual guide decode/weights, Refine, compiler arithmetic, native scheduling and AMD provider. The reported robust weight-support statistic is not an independently established effective sample count and must not populate the candidate sidecar.

The capped-history AR(1) expression is correct for the stated stationary scalar recurrence with alpha = 1/MaxCount, exact support and no reprojection/store effects. HybridPrep's expected `(m2 - mean²)/count` differs from the actual variance of a capped-count EMA. The synthetic choice MaxCount=16 is not evidence of the user's live constant. With IID inputs the source-shaped estimate exceeds actual mean variance by 1.875×; at rho=0.85, actual mean variance exceeds the source-shaped estimate by 6.3889×. This distinguishes count from effective independent support; it does not measure captured native correlation.

The selector/gain algebra correctly shows that raw and selected RGB cannot recover a unique hidden Base, selector and gain. Its freezing/replacement interventions remain synthetic because those native tensors are missing. The moving-reflection probe correctly separates known virtual-feature transport from a static surface vector; it is not a replacement native history model.

During review I reported two scope issues to the owner: the source tests directional support before 8-bit weight quantization, and inputs must fit the FP16 storage range. The owner corrected both in `native_subset.py`, and I confirmed the revised code uses unquantized directional weights and rejects RGB above 65504. The published 0/1 support, low-radiance experiments are unaffected; no quality tuning followed this correction.

### Final holdout audit and comparison fairness

I inspected the root-executed `evidence/synthetic_holdout.json` without rerunning its generator. It contains **240 sequences: 48 independent held-out noise seeds in each of five models, 32 chronological frames per sequence**. These are new noise realizations of the registered synthetic scene, not new captured scenes or 240 unrelated scene designs. The root run took 26.483966 s and returned 0. Its SHA-256 is `bf2b89353e1afeda86117cee327f7908d756cb15a26043afad3b600db26ad4ef`.

The read-only `--audit-holdout` command independently checks both source hashes, re-aggregates every reported **mean of paired seed ratios**, verifies every eligible-mask hash equals the actual original NZR-changed mask hash in this dataset, and confirms the truth-dependent scalar control matches the candidate's texture regression coefficient within `2e-8`. It returned 0. Results are in `evidence/reviewer_holdout_audit.json`.

| Synthetic model, candidate Blend.5 vs detail-matched scalar | Quiet grain RMS | Quiet positive sparkle p99.5 | Temporal error RMS | Isolated glint peak |
| --- | ---: | ---: | ---: | ---: |
| Independent Gaussian | −20.36% | −10.05% | −11.44% | −8.49% |
| Sparse heavy tail | −5.89% | **+9.99%** | −0.38% | **−24.31%** |

These are means of each seed's candidate/control ratio minus one, not ratios of aggregate means. The sparse heavy-tail result is an additional rejection: with the same aggregate texture coefficient, sparkle tails worsen, temporal error barely changes, and isolated feature peaks fall further. The candidate is not uniformly dominated in the favorable Gaussian model, but that conditional benefit does not overcome its heavy-tail and phase failures.

The detail-matched scalar is explicitly an evaluation oracle, selected from known synthetic truth. It matches one texture coefficient, not all spatial frequencies, individual glints, or native quality. Sparkle p99.5 uses the immutable quiet-flat mask. The separately named all-active high-pass tails include true-detail blur errors and must not be presented as pure sparkle. Temporal error subtracts known true motion/lighting changes; the separate output-change metric deliberately does not. The frozen-output null gets zero output-change RMS but fails true response. These distinctions are appropriate.

Both the honest spatial-correlated model and the temporal AR(1) model accepted **zero blocks** and are exact identity relative to Blend.5. They establish conservative abstention, not active correlated-noise reduction. The AR(1) annotation N=64, rho=.85 yields effective count 5.738462, below the required 8. The nominal 64 is supplied synthetic support information, **not 64 observed frames**; each generated sequence only contains 32 frames, and the generator does not reconstruct an unseen native history. Startup/reset counts are likewise controlled annotations.

Finally the generator constructs raw RR as twice-blurred current truth plus mild shared noise, and selected as sharp truth plus noise. Its raw texture coefficient is about 0.052 in the Gaussian model, much softer than a guarantee about any real provider. This is a stated mechanism surrogate with analytic uncertainty, not a calibrated model of native RR, Seed/Refine, selector or reflected-feature history. None of its percentages should be exported as a native-game quality result.

### Adapter review and local gate

I read the standalone HLSL and adapter specification. Its four-tap ordering, three RGB vector gains, whole-block range abstention and current-alpha staging are consistent with the CPU model at the stated arithmetic level. Its immutable SRVs and distinct output avoid an in-place neighbour-read/write race. The proposed production patch adds an unreachable source file; it does not enable a host pass, compile bytecode or produce a noise sidecar.

The CPU reference requires global origin (0,0). The captured glass crop begins at render coordinates (546,347), with odd global y parity, and its RGB is aligned while its original geometry is unwarped. It therefore cannot certify native block-phase/geometry parity. The adapter appropriately requires full-render coordinates or an even aligned ROI and complete support. The native host must validate generation, frame, stage, units, crop and estimator provenance before setting validity. A boolean or a nonnegative surface label does not establish those facts.

The standalone HLSL's Enabled=0 copy is a shader parity control only. Production OFF must schedule no additional work and preserve the existing graph, settings, resources and output bit for bit. Valid-v1-ABI arithmetic parity and malformed-native-metadata handling are separate tests: the Python API raises for some invalid configuration values while the shader abstains. No diffuse lobe is bound to the standalone shader; the final native integration still owns diffuse, original alpha, barriers and resource lifetimes.

The required next local work is a narrowly scoped native diagnostic capture of actual pre-Glass selected/raw lobe tensors and their uncertainty/support provenance, followed by matched native NZR+Glass/AMD RR and game A/B. The conservative absence-of-evidence identity is useful; it is not evidence of denoising improvement.
