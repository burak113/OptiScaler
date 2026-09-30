# GPU-based validation diagnostic, before execution

Create a separate native helper by changing the preserved runner only to
require ID3D12Debug1 and call SetEnableGPUBasedValidation(TRUE) before device
creation, print the enabled mode, and resolve SDK includes to absolute paths.
Use its standard tuning1 fork values and the same 64-frame lighting source,
all seven native payloads and frame reset/jitter controls already retained by
the metadata-failed tuning0 attempt. Authenticate those inputs and applied
dispatch controls against the original long64 source context.

Run one fresh context / 64 RR dispatches first. Retain the generated source,
new executable, job, process status, complete validation log and full FP16
outputs. This is a memory/resource-use diagnostic with a different executable
and GPU instrumentation. It cannot be counted as an exact-binary repeat,
production quality improvement, or proof of no defect if no messages appear.

Abort on unavailable GPU-based validation, process failure, SDK or D3D error;
retain failed evidence. Do not modify the production feature, driver registry,
device-global settings, original pinned executable or earlier evidence.
