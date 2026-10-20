# Boundary-safe low-band colour from sparse, heavy-tailed native inputs

Build and falsify a CPU estimator that stabilizes the low-frequency colour target without corrupting RR's sharp text, adding chroma grain, or leaking colour at material/geometry boundaries. This is a research task, not a request to enable a production option. Preserve the audited baseline and expose experimental changes separately.

Start from `colour_portable.py`, the phase counterexamples and the separately supplied chronological raw-array fixture. Keep at least two mechanisms distinct: noisy/sparse target observations versus subcell information loss versus temporal history acceptance. Record a different prediction for each before adding code. A box mean cannot later recover the distribution it discarded; quarter-grid means alone cannot test a heavy-tail estimator.

Use the smallest experiments that separate those causes. Evaluate actual chronological frames once, with a fixed warmup/reset convention. Use common masks derived from original guides and a common baseline-luma denominator. Include the known-bad NZR calibration/control where supplied. A mask selected from modified outputs can be diagnostic but is not a neutral material mask. Keep input-proxy colour closure separate from truth; exact game remod factors and a reference display are unavailable.

Required evidence before recommending a candidate:

- All 32 edge phases in the supplied falsification set, plus phase-shifted thin text/lines and depth/normal discontinuities. An aligned-only result cannot pass.
- Unlooped turn/settle and static-control chroma residuals with fixed masks/denominators. Report noise, mean RGB drift, edge bleed and luma storage error separately; do not let blur hide grain.
- A clean temporal reset and controlled persistent colour step/one-frame flash response. Label synthetic lighting interventions as synthetic.
- At least one counterexample search that could reject the candidate. Preserve failed hypotheses, exact commands/seeds and before/after images at identical exposure/aspect. If nothing dominates the baseline, say so.

Keep the original ideal CPU sampler as a named reference. Any optional 1/256 sampler experiment must be explicit and evaluated separately; changing a hard depth-gate decision can dominate a small arithmetic parity error. Do not claim a production/GPU/native/game fix from CPU output alone.

Deliver portable NumPy code, a repeatable evaluation command, measured comparisons and a concise recommendation with tradeoffs. No GPU/DLL/build/capture-loader dependency is available in this handoff. Do not synthesize a fake chronological capture by looping the single-frame fixture.
