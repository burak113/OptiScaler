# Same-binary instrumentation retry, before execution

The first GPU-based-validation attempt reached its 300-second process watchdog
without a completed native frame output. Its outputs/controls were empty, and
partial stdout/stderr were not retained by the initial wrapper. This timeout
does not establish an SDK/D3D failure or a quality result.

Repeat the same 64-frame job with the exact same already compiled instrumented
executable and consumed input paths, provider, frame controls and tuning1.
Only output paths and process watchdog change: allow900seconds and persist
stdout/stderr directly during execution. Preserve the first attempt. Remain
explicit that context creation/dispatch completion in the earlier process is
unknown. Record process return status and all resulting validation messages;
do not claim validation passed if no complete summary is available.
