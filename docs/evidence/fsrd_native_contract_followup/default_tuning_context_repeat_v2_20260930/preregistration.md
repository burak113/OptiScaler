# Provider-initialized tuning bundle, before execution

Run four fresh 64-frame lighting-step contexts using the exact existing long64
runner executable. Reconstruct and authenticate all seven native input payloads
and applied dispatch controls against the saved source context. Only the job
tuning flag changes from 1 to 0, which skips the six effect-key Configure calls;
global debug configuration remains enabled. Do not change reset, jitter, camera,
signal types, source data, binary, provider, resource initialization or outputs.

Defaults were measured by a separately compiled query-only utility before any
effect-key Configure: key6=.01, key1=1, key2=1, key3=65504, key4=50, key5=0.
Record that utility's source, executable, provider and result hashes. Do not
claim that the existing pinned runner queried defaults or that these query
results measured the active state of the four tested contexts.

Retain exact FP16 diffuse/specular sequence arrays, their native output-byte
hash authentication, and composed RGB for frames 0,1,31,32,33,34,63. Compare all
six context pairs in RGB and alpha, including frames before and after frame32.
Compare selected composition to retained tuning1 source baselines. Four pairs'
observed ranges are descriptive, not a confidence bound. A bundle change does
not isolate any single key, establish a defect or demonstrate game quality.

No threshold sweep, additional reset, pilot change or production change is
authorized by this experimental protocol. Preserve earlier divergent evidence.

The prior attempt completed one native context/64dispatches, then failed in
Python metadata recording due to a missing pathlib import. It is retained
separately and excluded from this four-repeat analysis. This retry changes
only that import, not native runner bytes or requested controls.
