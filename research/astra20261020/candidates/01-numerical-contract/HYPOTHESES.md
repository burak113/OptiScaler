# Precommitted mechanism tests

Written after source/fixture inspection and the untouched baseline run, before
candidate calibration. The independent reviewer chose boundary controls before
seeing implementation results. There is no tunable denoising policy in this job.

| Hypothesis | Prediction | Falsifier / identifying observation |
| --- | --- | --- |
| H1: storage conversion is sufficient | Injecting the supported FP16 store rule at the actual store changes downstream threshold decisions; higher precision without the store does not repair them. | A mismatch survives all explicitly selected store rules while a sampler intervention changes it. Never choose a rule just because output error falls. |
| H2: sampler coordinates/fractions explain hard-gate differences | Errors vary with subpixel phase and local depth slope; exact texel loads remove interpolation phase. Constant fields and texel centres retain their values. | Constant-field drift, an unexplained integer-centre branch, or mismatches outside the documented addressing/filter envelope. |
| H3: guide packing dominates | All 2048 audited integer payloads survive half storage, while the old normalized 16-bit payload loses codes and can change normal gates. | Any valid new payload loses bits. Invariance of packing does not prove that all normal quantization error vanished. |
| H4: missing pre-store bits make exact reconstruction unidentifiable | Distinct float32 inputs in one exported half bin produce different downstream valid values or atomic increments. | A singleton preimage/observable interval, or an additional captured pre-store observable, would identify the result. An exact-output request must reject a non-singleton interval. |

## Frozen populations and acceptance

- The colour calibration population is every cell/pixel of the published frame63
  fixture. Statistics, history, gain, sampled depth and validity are compared
  separately. Expected arrays are identified by provenance; their names do not
  make them GPU outputs. No population is chosen from candidate values.
- Anchor calibration includes every one of the 133 combined and 7 native-policy
  frames. Use the stored `fixed_mask`; native original atomics are absent.
- Chronological clips are inventoried in original order with their original crop
  origins/render dimensions. No warmup frame is fabricated and no sequence loops.
- Exhaustive payload/integer spaces and independently chosen boundary cases are
  correctness populations. Seed20261020 is development; seed20261021 is reserved
  for reproducible holdout properties. No threshold is fitted to either.
- Report exact equality when justified, otherwise explicit intervals and maxima,
  percentiles, nonzero error counts and changed decision counts. No image-quality
  improvement can be accepted from this numerical work alone.
- A single executable float32 or quantized sampler is a profile, not the entire
  set of permitted HLSL/API executions. Unresolved compiler, sampler and storage
  assumptions remain machine-readable and have local microcases.
