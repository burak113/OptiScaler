# Indirect specular alpha held-input ablation

Four fresh contexts each of zero_distance, finite_distance10 and sky_distance65504,
64 frames/context, blocked order zero,finite,sky for each repeat. Use the seven
frozen first-frame native input textures from the held-source study. Change only
input6 alpha, preserving its RGB and all six other input bytes. All inputs have
frame count1, so all three arms use the same upload scheduling. Same original
pinned runner/provider, tuning1, reset/jitter/camera/184-byte controls.

The finite value10 is a geometry counterfactual, not measured secondary-ray
length or verified substitute for the local roughness virtual-hit handover.
65504 follows the SDK sample miss sentinel, but this held radiance is not proven
to be sky. No arm is a production fix, and no game quality claim is made.

Retain every generated input, raw output, control, job and log. Compare every
within-arm repeat pair and all zero-versus-other pairs in full RGBA/RGB with
framewise RMS/first divergence. Record consumed input alpha and output alpha
separately; do not assume public output preservation or infer its cause from
zeros. Describe only observed variability from four contexts, not a population
bound. Absence of variability in a changed-alpha arm is not image-quality proof.

Native guard unchanged:240s, child working set2GiB, available physical floor1GiB,
sample.2s. Stop on failed guard/native run and retain partial evidence. Ordinary
debug validation only; no GPU-based validation, conversion or runtime edits.
