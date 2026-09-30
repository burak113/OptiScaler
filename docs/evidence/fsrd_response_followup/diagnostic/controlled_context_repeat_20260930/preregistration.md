# Four native contexts with one pinned runner, before execution

Reconstruct the long64 lighting-step source input and verify all seven consumed
texture hashes plus reset/jitter controls against its saved source manifest.
Use exactly its existing compiled runner binary for four separate contexts;
do not recompile it, change tuning, zero outputs, reset additional frames or
alter provider/geometry/ray semantics. Retain exact FP16 diffuse/specular
sequence bytes and composed RGB for frames 0,1,31,32,33,34,63. Compare all
pairwise native arrays and these selected composed outputs to the old16 and
long64 source baselines. This is an operator-stability diagnostic, not a pilot
quality study or a statistical confidence bound. Any difference remains an
observation with unresolved cause; successful contexts do not erase earlier
large null divergence.
