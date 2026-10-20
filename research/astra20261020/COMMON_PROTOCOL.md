# Research protocol

The user explicitly authorizes substantial implementation and subagent research.
Use available subagents with distinct responsibilities: mechanism/data-flow
analysis, numerical prototype, and independent skeptical review. You own the
final reconciliation. If the environment cannot delegate or execute code, state
that limitation and still return a concrete reviewable artifact where possible.
Do not claim a run, PR, model capability or GPU test that did not occur.

Start from tag `astra-handoff-20261020`, record `git rev-parse HEAD`, and create
your task's `astra/0N-topic` branch. Never overwrite another task's branch, force
push, merge master, or enable an experiment by default. Place new research under
`research/astra20261020/candidates/0N-topic/`. Give the integration task a scoped
production adapter patch; independent jobs should not all edit shared host/UI
files. The frozen baseline data and references must remain unchanged.

Read the relevant source, then state competing causal hypotheses and a prediction
that distinguishes each. Use the cheapest discriminating real-data test first.
Inspect sparsity, zero mass, tail energy, lobe separation, material/depth coverage
and temporal/spatial correlation before choosing a filter. Do not keep tuning a
family after its shared assumption is falsified. Literature can inform a new
representation; use primary sources, links and a precise implementation mapping.

Calibrate metrics against the known failures in FINDINGS.md. Grain, sparkles and
flicker matter more to this user than a modest blur change, but eliminating
detail is not an acceptable way to win. Report level and structure separately.
Use fixed masks from unmodified baseline inputs, identical crop/exposure and
sample support, real frame order, explicit startup/history limits, and multiple
deterministic noise seeds when synthesizing noise. Freeze a holdout before tuning.
Do not fabricate independent captured samples from one repeated frame. A late
input frame, raw RR or selected RR is not converged ground truth.

For each serious candidate implement CPU reference code, reproducible tests and
a deployable HLSL/host adapter proposal when justified. Include a known bad
control and a mutation that makes a correctness test fail. Test identity/OFF,
invalid history, real moderate light changes, geometry boundaries and unsupported
regions as relevant. Choose thresholds before examining held-out results; show
failures and sensitivity, not just the best aggregate. Do not add test counts for
their own sake. A well-proved negative result with useful diagnostic code is
better than a falsely accepted filter.

CPU conclusions are limited to the modeled arithmetic and data. Preserve bit
formats, float16 store rounding, D/S units, alpha, render extent, crop origins and
motion conventions. Ideal NumPy bilinear is not an exact D3D sampler. New HLSL
must ship with its compiler target/flags and local parity request. Do not call
stale generated CSO/header bytes a finished shader build. Do not install a DLL.

Continue until the strongest plausible approaches have been implemented and
challenged, or a precise missing observable makes further work unidentifiable.
Do not pad work to a fixed duration. Return the exact blocker and the smallest
capture/GPU experiment that would resolve it. Request missing data using the
return protocol rather than silently inventing it.

Return a PR targeting `sol/26-integration` if write tools permit, otherwise a
downloadable ZIP with sources, binary-safe git patch, results and hashes. If only
read tools exist, disclose this and provide the best supported export; never
pretend a PR was created. No automatic merge. Local GPU acceptance is mandatory
before a production visual improvement claim.

Prompt structure follows the official guidance to provide relevant context,
scope autonomy and explicitly request useful delegation:
https://developers.openai.com/blog/rethinking-skills-and-prompts-for-gpt-6-astra
https://developers.openai.com/api/docs/guides/latest-model
These links do not establish the user's subscription quota or ChatGPT tools.
