# Anchor CPU reference and real shader grids

Run `python -m unittest discover -s tests -v` with Python 3.10+ and NumPy. No GPU,
game, Windows runtime, RR Lab, absolute path, or model download is required.

`anchor_reference.py` freezes the existing gain formula; it is not an improved
algorithm. `fixtures/manifest.json` records source/CSO SHA-256, frame, motion-window
age k, ratio provenance, ROI scope and original binary hashes. Combined fixtures
contain 133 actual source-driven GPU frames and exact original 1/1024 atomic sums.
Native-policy fixtures contain seven actual native Stats/Gain CSO frames on the
same harness schedule. They do **not** prove native bridge routing or RR quality.
The bundled HLSL/header copies are provenance for the formula, not a shader build.
Their frame ratios are bounded 16.16 estimates from stored FP16 fields; pre-store
native atomics were not exported. Tests require the guard decision to be constant
over the whole rounding interval.

Arrays are `stats=(level,depth,static,0)`,
`recalled=(warped_key_level,valid,physical_slice,static)`, scalar `gain`, and an
immutable `fixed_mask`. Raw six-slice key textures are **not** included: recall
already happened on the GPU. This dataset can test gain estimators, not a new
reprojection/key-selection algorithm. Gain is the input correction field, not
rendered RR output. Use `allow_pickle=False` when loading the NPZ files.

Known baseline falsifiers are intentional passing tests: a genuine 1.25x light
step is almost fully removed; equal-global-energy antithetic residuals still
darken. Captured residuals mix geometry, temporal change, lighting and noise, so
this null does not prove pure Monte Carlo causality. Identical observations can
represent a real light step or an input bias; document any additional observable
needed to distinguish them. Native local identity protects grid-cell centres;
full-resolution bilinear Apply can still bleed over a mask boundary.

Research must keep the original masks and baseline calibration, test identity,
moderate 1.1/1.25/1.4x light changes, noise nulls and unsupported moving/new-view
cells together, and report lost early correction dose alongside reduced bias.
No new estimator or production change is proposed by this package.
