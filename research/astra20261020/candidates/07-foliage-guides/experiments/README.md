# Synthetic experiment: implementation decision and evidence scope

## Decision

Keep the original-guide observer as research. Do not activate the hypothetical
cosine history consumer as a production denoising change. The observer is
default-OFF and never writes RGB, normal, depth, material code, roughness, or
alpha. Its output is evidence for inspecting guide consistency. It is not a
foliage label, an AMD RR confidence input, or permission to accept denoiser
history.

The final frozen benchmark has **51 protocol rows and 40 distinct input
realizations**. Repeated reference rows retain their place in one-family
comparisons. `summary` is explicitly row-weighted; `summary_unique_inputs`
deduplicates input hashes. All repeated input groups also have identical truth
hashes, as checked independently; deduplicating `(input, truth)` therefore gives
the same result. The nine held-out rows have distinct inputs and were not used
to change observer parameters, scoring thresholds, or the development protocol.

The benchmark was replayed after a concrete float32 arithmetic correction for
NumPy scalar metadata. The final implementation-owned run took **55.0129 s**, exit
0, with Python 3.12.14 and NumPy 2.3.5. That time is CPU experiment wall time,
not GPU pass cost. The independent reviewer replayed all final rows and obtained
exactly matching case payloads and row-weighted summary, with unchanged source
hashes before and after execution. Consult the review receipt for its own
executor and elapsed time.

## What was implemented

`src/foliage_guides.py` decodes the source R10G10B10A2 oct-normal contract and
observes unmodified original guides. Its 3x3 angular dispersion and relative
depth span describe a neighbourhood. Its temporal innovation compares current
normal against four manually weighted previous taps, after chronological frame,
crop, finite-motion, category-equality and signed previous-depth checks. Frame
coordinates include current-origin minus previous-origin and full-render UV
motion. Even a zero-weight corner must be valid under the conservative four-tap
support rule. The arithmetic is explicitly float32; it is not an emulation of
D3D sampler fraction quantization.

`TEMPORAL_SUPPORTED` means numerical comparability of the supplied guide values.
A finite depth sanitized from invalid raw geometry can be indistinguishable from
a valid finite depth. The observer does not have the native raw-validity byte
unless an adapter supplies separate provenance. A test deliberately demonstrates
that limitation. Unknown depth conventions, nonconsecutive history, reset,
out-of-crop taps, category mismatch, or invalid predicted depth cannot manufacture
a non-identity confidence penalty. Material code zero is a valid opaque code,
not a semantic class.

The optional `experimental_history_multiplier` is the clamped cosine agreement
of supported normal observations. It is an uncalibrated geometric proxy. Its
CPU consumer is tested only inside the clearly labelled surrogate in
`src/proxy_metrics.py`. No active production consumer is proposed.

`src/synthetic_scene.py` builds 4x4 supersampled thin opaque cards over a textured
facade, narrow window frames, block-text-like strokes, distant window views and
sky gaps. Geometric, deterministic alpha-test and stochastic coverage are
distinct constructions. Single guides come from actual selected-layer subpixel
witnesses before explicit quantization. The full-precision observed-guide
ablation removes only quantization; it does not magically represent the entire
mixture with one vector. Leaf plane normals and depths are exact. Background
per-layer oracle buffers contain known moments that may include several
background facets, and are not mislabeled as perfect per-sample geometry.

The generator retains per-layer lighting, coverage, normals, depth and motion
for truth and oracle evaluation. These are never candidate inputs. The synthetic
lighting is positive linear radiance constructed from a directional Lambertian
term and a simple specular lobe. Independent versus persistent noise uses a
lognormal field with sparse bright outliers; it is not a ReSTIR model or a claim
to reproduce the captured zero-mass distribution. Coverage, guide selection and
lighting use separate deterministic random-number streams, so changing a guide
observation rule does not silently change lighting noise.

Synthetic D/S inputs undergo one disclosed FP16 store, retaining distinct
hit-distance-like alpha constants. Their RGB sum is formed in float32. Inputs,
truth and masks are read-only arrays. No averaged capture is substituted for raw
data, and no sequence is looped to manufacture history.

## Falsifiers and measured outcomes

The 51 rows sweep thickness, orientation, overlap, coverage fraction,
quantization, object-motion difference, noise correlation, coverage rule, guide
rule and subpixel phase. Static/moving rigid controls and paired moderate light
changes are included. The nine held-out rows combine frozen unseen seeds,
orientations, phases, trajectories and correlation levels.

The exact synthetic truth masks and denominator are created before evaluating
any method. Grain, p99 residual sparkles, flicker, edge error, coverage projection,
motion-region error, cross-layer mixing and false composite-history support are
reported separately. Detail transfer combines both spatial axes and returns
unavailable when truth has no detail energy. The frozen detail gate is 0.95;
none of the denoising surrogates passes it. Their aggregate score cannot override
that failure. The surrogate is intentionally transparent and modest; its low
absolute detail transfer also prevents using it as a quantitative AMD predictor.

Selected results from `evidence/synthetic_benchmark.json`:

- Held-out mean detail transfer for the hypothetical cosine consumer changes
  from about 0.40007 to 0.41289 relative to the single-guide surrogate. Mean p99
  sparkle error worsens from about 0.95624 to 0.97038. The worst paired sparkle
  regression is 3.80%, and the worst flicker regression is 1.52%. This is not an
  accepted visual improvement.
- In the static rigid-facade control, flattening normals lowers flicker while
  detail transfer falls from about 0.44708 to 0.35010, a further 21.69% relative
  loss. These are newly executed CPU surrogate measurements; they are not a
  replay of the historical native GPU facade loss.
- With fixed coverage, changing independent to persistent lighting noise keeps
  the guide diagnostic identical, while p99 error of the single-guide surrogate
  rises from about 0.65458 to 1.16909. Flicker decreases at the same time. A low
  flicker number can therefore coexist with more persistent grain/sparkles.
- Ten homogeneous analytic normal witnesses have at most 0.14265 degrees of
  error after the correct 10-bit oct encoding/decoding. Deliberately decoding the
  channels as XYZ UNORM produces about 58.51 degrees mean error. This separates
  the numerical-contract test from coverage representation; it does not certify
  an unavailable native known-normal capture.
- An exact observation collision supplies identical dominant guides from two
  hidden mixtures whose true RGB differs by up to 0.16 synthetic radiance units.
  Both receive the same observer output and full cosine agreement. Low measured
  guide uncertainty cannot prove homogeneous coverage.

`src/transport_discriminator.py` adds a small analytic transport falsifier because
the broad benchmark's layer-motion oracle difference is small. A fixed 60/40
unresolved mixture has layers moving at +0.25 and -0.5 pixels/frame. Dominant
guides remain constant. Exact analytic previous-layer evaluation eliminates
sampler, noise and filtering confounds. Normalized RGB transport RMSE is
0.13549 with the correct dominant-layer motion, 0.17562 with coverage-mean motion,
and exactly 0 with separate correct layer motion. The observed normal innovation
is zero. This proves a possible representation/transport ambiguity in the
construction, not that a specific captured foliage pixel follows this rule.

## Commands and meaningful tests

From the repository root:

```sh
python research/astra20261020/candidates/07-foliage-guides/run_benchmark.py --executor implementation_subagent_final_cpu_verification
python research/astra20261020/candidates/07-foliage-guides/src/transport_discriminator.py
python -m unittest discover -s research/astra20261020/candidates/07-foliage-guides/tests -p 'test_candidate*.py' -v
```

The implementation-owned suite has 19 passing tests. Its final run took 0.421 s,
exit 0. The tests cover encoding/code preservation, default-OFF and input-byte
identity, crop-origin transport, outside-crop rejection, signed motion-depth,
four-tap invalid data, unknown history, extreme finite arithmetic, NumPy metadata
dtype stability, observational collisions, exact coverage decomposition, alpha
and mask immutability, independent RNG streams, moderate light response,
rotational detail scoring and the analytic two-layer transport discriminator.
Reviewer and captured-data tests are separate additions; do not confuse this
implementation-only count with the final complete suite.

This command is deliberately expected to fail:

```sh
python research/astra20261020/candidates/07-foliage-guides/tests/test_candidate_contract.py --mutant-clamp-history
```

It changes only the test process's crop-support function to pretend every
reprojected coordinate is inside the previous crop. The contract assertion
fails with exit 1. The normal suite launches this mutant and requires that
failure; it does not rename a failed mutant as a successful measurement.

No native GPU execution, shader compilation, AMD RR output improvement, Windows
host build, GPU timing, VRAM cost or final game result was executed by this
implementation workstream. Those measurements remain unavailable and belong to
the local gate described in the main handoff.
