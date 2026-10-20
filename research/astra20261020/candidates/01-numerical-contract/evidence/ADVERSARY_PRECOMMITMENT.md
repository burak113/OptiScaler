# Independent adversary precommitment

Executor: `independent_skeptic`. Base: `astra-handoff-20261020`, commit
`5d7839a930106cf8fe1ba8dbbc6750509e7f26a8`. The controls below were selected and
executed **before reading any candidate implementation or claimed improvement**.
Only the prompt, protocols, frozen portable packages and production source were
read during this phase. This is synthetic CPU evidence, not executed GPU evidence.

## Competing mechanisms and fixed falsifiers

| Mechanism | Prediction | Preselected falsifier |
| --- | --- | --- |
| Store placement/rounding | Quantizing each accumulator step can change a result that only stores once in the shader. | Four terms `[1, 2^-11, 2^-11, 2^-11]`, divide by four, FP16 RTZ only at output. Reject per-add half rounding. |
| Payload encoding | Normalized 16-bit packed payload cannot survive half; an 11-bit integer can. | Enumerate **all** 65,536 old payloads and **all** 2,048 new payloads, keeping the full denominator. |
| Low-word overflow | Ignoring high words loses physical energy after a natural wrap. | 262,145 legal cap16 increments, each `16 * 65536`; exact Python integer sum has high word 64. |
| Missing pre-store information | Two binary32 values with the same RTZ half export can have different 16.16 increments. | `1` and `1 + 2^-11` both export half `1`; legal increments are 65,536 and 65,568. Reject any claimed unique reconstruction. |
| Pixel-centre/allocation mapping | Correct texel-centre sampling on an allocated plane is invariant; active/allocation confusion shifts it. | Allocation `(17,11)`, active `(13,7)`, plane `x+100*y`, texel centre `(3,2)`; normalization must use allocation. |
| Point/bilinear substitution | A nonconstant field at fractional phase separates nearest from bilinear. | Plane `x+100*y`, position `(3.25,2.5)`: bilinear 253.25, nearest differs. Include constant and texel-centre controls. |
| Crop support | Missing observations cannot become valid by edge clamping. | Full allocation `(9,7)`, crop origin `(3,2)`, observed extent `(3,3)`; query exact last known texel centre versus a positive-weight tap outside crop. Zero-weight missing taps cannot invalidate exact-centre identity. |
| Exceptional storage | A model must state finite saturation and nonfinite handling by actual source boundary. | Signed zero, `+/-2^-25`, exact half subnormals, signed halfway cases, `+/-65520`, `+/-Inf`, NaN. Never substitute a universal GPU guarantee. |
| Inactive fields | Unread constants and inactive history cannot influence output. | Poison unused constant lanes; history invalid means unrelated previous values do not change current output. |

No adaptive threshold tuning is permitted in this review. Candidate APIs may be
adapted into these cases, but changing the cases to fit a candidate failure must
be identified as a new test, not a revision of this precommitment.

## First executed negative controls

Command from repository root:

```sh
python -B research/astra20261020/candidates/01-numerical-contract/adversary_controls.py
```

The first independent inline execution, before writing the reusable file, found:

- Old normalized 16-bit payload: **59,383 / 65,536** mismatches; maximum code
  error **32**. First failing codes: 2049, 2051, 2053, 2055, 2057, 2059, 2061, 2063.
- New integer payload: **2,048 / 2,048** exact after half storage.
- Natural-wrap case: exact sum **274,878,955,520**; high word **64**, low word
  **1,048,576**. A low-only mutant loses **274,877,906,944** integer units.
- Correct final-only RTZ output **0.250244140625**; premature-store mutant
  **0.25**. Their difference is one half step at this magnitude.
- Two same-export preimages yield distinct valid atomic increments, so exact
  reconstruction is mathematically non-identifiable without the pre-store bits.

These passing diagnostics demonstrate that the specified wrong models fail.
They do not show that the production source still contains those already repaired
mistakes, nor do they approve any denoising policy.
