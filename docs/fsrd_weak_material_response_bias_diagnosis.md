# Weak-material response decomposition — 2026-09-30

The weak-material gain failure is visible in three measured terms: source
pilot error, the native baseline-minus-pilot-response difference, and the
endpoint history shift. This is an algebraic location of error, not an
identification of its native cause. No new estimator, native/GPU work or
production change occurred.

All six saved `clean_reference` arrays are raw constructed fixture targets.
Frozen fixture reconstruction reproduces their dtype and bytes exactly;
the observed noisy/FP16 sequences also reproduce exactly. These targets
are not SDK outputs from clean-input dispatches. Existing native contexts
measure observed, null and pilot responses; T(clean) has not been measured.

Weak material has one real checker coefficient in the authenticated source
basis, with true beta approximately -0.001 in each channel. Its mature mean
pilot gains are approximately [0.99945, 0.98038, 1.00327]. Native baseline
gains are [1.29129, 1.22527, 1.13250], and pilot-response gains are
[1.32248, 1.27080, 1.16658]. Their difference attenuates the pilot when
forming C, whose gains become [0.96825, 0.93485, 0.96919]. Endpoint history
then gives [0.93540, 0.92919, 0.94651]. The final DC operation changes this
checker coefficient by zero.

The mean coefficient bias separates as pilot error
[0.551, 19.625, -3.271]e-6 plus B-minus-TP
[31.198, 45.528, 34.080]e-6, followed by endpoint shift
[32.846, 5.659, 22.680]e-6. A positive bias attenuates this negative true
coefficient. These are signed measured terms with covariance; they are not
independent percentages of causal noise.

The active coefficient history cuts at frame42 for source-atom innovation.
The mature window starts at48 with seven observations and reaches16 at57.
Basis and phase stay unchanged, with zero phase transport. Recomputing the
saved endpoint law closes within 7.45e-9, including FP32 output rounding.
An earlier diagnostic roundoff assertion failed at roughly 3.4e-17; its
script and qualification are preserved. Only that diagnostic numerical
tolerance changed, with no score gate or estimator change.

The [sealed decomposition](evidence/fsrd_weak_material_response_bias/manifest.json)
preserves source/provenance checks, projected existing terms and the failure
qualification. Native transfer, noise-dependent nonlinearity and common
bias remain unidentifiable from these observed/pilot pairs. A meaningful
clean-response control needs actual clean converter outputs and matching
SDK guides, formats, controls and provider. Raw FP16 quantization alone
cannot substitute for the two SDK demodulated radiance inputs.
