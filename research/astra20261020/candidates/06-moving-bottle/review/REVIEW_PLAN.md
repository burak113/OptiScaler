# Independent review plan (frozen before candidate results)

Reviewer role: skeptical validation, independent of candidate design and tuning.
The reviewer first executes the frozen colour `soft2` quality gate, which must
reject the known halo regression with exit code 1. No candidate result files
were inspected when this plan or the initial control record was written.

## Claims and counterexamples to test

1. **Coordinates.** Previous coordinates must use previous-minus-current motion
   in full-render UV, the full render extent, and both crop origins. A moving
   crop with compensating physical motion must reproduce the same local sample.
   Test wrong sign, wrong render extent and omitted crop displacement separately.
   Out-of-crop samples are unknown, not zeros or clamped edge history. Frame zero
   has no history; intervals must stay chronological and must not be looped.
2. **Independent geometry.** A lighting-independent geometry witness must be
   available before blaming motion. A zero-valued stochastic input pixel cannot
   prove an absent surface. Correct motion with sparse support and wrong motion
   with dense support must have different diagnoses, or explicit abstention.
3. **Level versus shape.** Lowering an unchanged stripe's radiance lowers its
   tail energy without shortening it. Shape/centroid measurements and radiance
   metrics must be separate; sensitivity uses predeclared thresholds and fixed
   denominators. Candidate-derived support is forbidden as an evaluation mask.
4. **Stage localization.** Equal raw RR and selected words rule out newly added
   differences at that observed handoff; equality does not locate a defect
   earlier in RR, prove upstream physical support, or validate final composition.
5. **Virtual motion.** Reflected features can move differently from the surface.
   Good diffuse/silhouette transport and poor specular transport do not by
   themselves prove provider malfunction. Hit distance is not generic view depth.
6. **Non-identifiability.** Distinct causes with identical available observations
   must produce abstention. Missing albedo/final composition/prior history cannot
   be reconstructed from a short crop or assigned invented confidence intervals.
7. **Preservation.** Diagnostic identity must retain every original byte, including
   FP16 sign bits and alpha/hit distance, in OFF and abstention paths. No production
   controls, baseline references, or another candidate folder may be modified.

## Blind evaluation protocol

The implementation owner/root will supply anonymous cases and allowed
observations without injection names or hidden labels. The reviewer will read
only those observations, save case-by-case predictions, uncertainty and required
additional observations, and hash the prediction file **before** receiving the
truth key. A held-out trajectory and a held-out noise family are required.
After reveal, report exact correct/incorrect/abstained counts and failure cases;
do not tune thresholds to the revealed labels. If an injection is not observable
from the delivered tensors, explicitly classify it as non-identifiable.

After blind predictions are frozen, audit implementation/results for mask
selection, denominators, thresholds, units, chronology, seed-level uncertainty,
mutation checks, unsupported samples and preservation of glass/water/text
controls. CPU checks cannot establish GPU timing, D3D lifetime safety, AMD RR
image quality, or in-game appearance.
