# Native oct corner representation equivalence

Three arms, four fresh contexts each, blocked by repeat with arm order
baseline, opposite_constant, opposite_step.64 frames/context. Seven inputs are
frozen first-frame native bytes from the four-context frozen-source study.
Only R10G10 UV bits of the normal texture may change; roughness B/material A
bits remain exact. Baseline corner(0,0), opposite(1,1), both locally/sample
decode to exact world−Z. Opposite constant uses(1,1) every frame. Opposite step
uses original(0,0) frames0..31 and(1,1) frames32..63. All physical geometry,
radiance/guides, motion, and184-byte applied controls are equal; no extra reset.
Same pinned binary/provider, fork tuning1, ordinary D3D12 validation. No GPU
conversion, game capture, or production shader/runtime changes.

Preserve raw native outputs/logs/controls and generated normal input bytes. The
step arm changes only public normal representation, not physical normal. Compare
all within-arm repeat pairs, all baseline-versus-candidate pairs, full RGB/RGBA,
pre32/post32 and per-frame RMS. Record whether candidate differences exceed the
observed maximum of the six baseline repeat pairs by frame, descriptively.
Four repeats provide no population confidence envelope. A context offset before
frame32 cannot be attributed to the later normal step. A post32 divergence is
evidence for this fixture only; its cause and actual game relevance require more
controls. No outcome alone accepts a stain/wave quality solution.

Use the previously smoke-checked owned-child resource guard unchanged:240s,
child working set2GiB, free physical memory floor1GiB, poll.2s. Stop on failure
and preserve partial results; no GPU-based validation retry.
