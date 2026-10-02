# Observable source-radiance SPEC SDK guide

SOURCE_ONLY_UNEXECUTED. No implementation, payload reads, numerical work, compiler, GPU or native execution. Production and previous CLOSED packets remain unchanged.

## Bounded novelty finding

No exact completed intervention was identified in the selected history: replacing only the SDK SPEC guide RGB with current observed noisy source RGB while retaining the current full1 caller factors, signal buffers and Skip. This is a bounded source-history finding, not an exhaustive claim about every old artifact.

The tempting precedents have different operands:

- `OptiScaler/shaders/shader_tools/tests/probe_fsrd_real_rr.py:62–73` defines clean-pattern and observed-noisy guides. However, every `noisy` case constructed at149–154 uses `path='demod'`;81–85 consequently change the supplied signal, remodulation factor and Skip. The full guide-only cases at175–186 use pattern/flat/white/black or wrong alignment, not noisy radiance. They are also separate-lobe direct-output measurements. `docs/fsrd_real_rr_albedo_experiment.md:126–130` records a negative clean-pattern guide-only result;185–191 describes noisy remodulation noise re-entry. Neither is the precise fixed-caller current-joint intervention.
- `docs/fsrd_virtual_albedo_noise_audit.md:18–27` explicitly swaps both signals, both guides, Skip and DetailReference and composes with the same reconstructed carrier. Its rejection and retirement remain binding for that coupled family; they are not an exact guide-only counterpart.
- The statistical `guide_only` label is output reconstruction: `probe_fsrd_statistical_resolve.py:189–215` fits source observations using guide features after native outputs already exist;238–239 disallows promotion. `probe_fsrd_recorded_resolve.py:33–39` likewise calls a CPU resolver with material features. It does not replace SDK slot3.
- `docs/fsrd_additive_residual_independent_lobe_holdout.md:1471–1502` closes constant64 SPEC-guide-only on the current full1 graph. It preserves material detail but fails illumination detail in both repeats. This is a constant-field rejection, not an observed-radiance field measurement. No old format, encoding, dose or coupled-factor failure is converted into a PASS here.

## One fixed empirical mapping

If root selects this mechanism, use exactly:

`G_spec.rgb = R8_UNORM_RNE(saturate(C_stored.rgb))`

Here `C_stored` is the current observable source-color RGB actually supplied to conversion, after its declared resource decoding, not clean truth, reconstructed lobes or a fitted/reference image. Quantization means nearest-even integer code in0..255 after multiplication by255. Copy original SDK SPEC-guide alpha byte-for-byte. No minimum floor, mean matching, normalization, spatial/temporal denoise, carrier extraction, history, gain parameter or fitted exposure is added. Saturation is the unavoidable fixed representation bound of this particular R8 mapping; clipped-guide coverage must be reported and limits HDR generalization. It must not be silently replaced by exposure fitting.

Give this field a separate native slot3 resource. Slots0,1,2,4,5,6 remain byte-identical to baseline. Composer t1 remains the original converter SPEC guide, and t3, original full1 strengths, signal inputs, Skip, flags, roughness, geometry and applied controls remain unchanged. `FSRDInputConv.hlsl:1197–1205` confirms the current guide RGB is published separately from its diagnostic alpha; this proposal changes its SDK binding only, not the converter's allocation or caller remodulation.

This is an empirical feature intervention, **not** a physical specular-albedo repair. The primary SDK table `external/FidelityFX-SDK-v2/Kits/FidelityFX/docs/techniques/denoising.md:482,503` requires specular albedo and defines linear/sqrt interpretation;1034–1067 constructs it from material F0, roughness and view-dependent BRDF. It does not endorse source radiance as that feature. The constant64 sensitivity result supports that guidance can affect the observed response; it provides no guarantee that this mapping will restore detail or reject noise. No source algebra or private-model claim establishes success.

## Decision relevance and limits

The hypothesis is that current-frame radiance contrast in a separate guide can change filtering of visible illumination without weakening caller demod/remod. It also sends stochastic RGB noise into that guide, so sharpness alone is insufficient. The previous clean-pattern guide-only failure is an explicit adverse precedent.

Any later selected quality decision must keep one mapping and require the existing hard material/illumination detail gates and unchanged noise/error nonregression simultaneously in both fixed repeats. Static illumination tests persistent spatial loss; animated illumination at static geometry tests current visible-light response without attributing light animation to geometric motion. Existing valid geometry/MV transport is retained; no oracle motion or retrospective alignment is allowed. Independent colored input noise tests whether guide contrast merely preserves noise or imprints color. Truth is score-only. Reuse established gain[.95,1.05]/phase<=.05 and existing physical-error/noise metrics, not new thresholds or selected frequencies.

Any necessary hard-detail failure rejects this fixed mapping. Passing an endpoint is inconclusive; positive implementation requires the complete predeclared quality conjunction, including moving illumination and colored noise. A positive result supports only bounded experimental SDK-guide/caller-guide separation with declared radiometry/format limits; it would not identify physical lobes, establish correct material semantics or prove a game fix. Negative closes this mapping with no dose/normalization/filter bank. No executable packet or experiment is authorized by this note.
