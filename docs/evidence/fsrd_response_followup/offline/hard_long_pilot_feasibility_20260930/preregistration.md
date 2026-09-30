# Fixed hard/soft history ablation, before execution

Compare the unchanged binary and continuous 4-RMS source-only pilots with
history 16 and 64 on all thirteen old additive holdout scenes. No new threshold,
truth input, guide input or posthoc threshold sweep. This isolates shrinkage
versus retained-coefficient variance: longer binary history might preserve weak
detail better but can retain noise and switch support abruptly. Require exact
first-sixteen equality across the two histories, original evidence hashes, all
lighting/moving/disocclusion/reset/shared-bias families, and absolute gain on
every scored frame. This is CPU feasibility only; no old native response will
be substituted for a newly generated pilot's response.
