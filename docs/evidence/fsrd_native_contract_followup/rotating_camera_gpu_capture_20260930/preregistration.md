# Retained-job conversion repeat, before execution

The first four-camera conversion experiment stored fixture/result NPZs and job
paths, but the existing dispatch helper removed all CB/input/output .bin files
and its worker checked stdout without retaining per-job logs. Preserve that
result and independently audit it with its provenance limitation.

Repeat the exact same two inverse matrices times strengths0/1 at roughness.1,
using the same CPU fixture hashes and current production shader artifacts. Only
change the worker wrapper to copy all actual job bytes after server completion
and before helper cleanup, plus each actual stdout log. Hash originals and
copies. No native RR calls, shader edits, threshold changes or quality claim.
The separately derived script also corrects the misleading tolerance key name
to one_ulp_plus_1e_minus_5; its numeric tolerance remains unchanged.
