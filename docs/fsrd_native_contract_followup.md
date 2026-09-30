# Native FSRD contract follow-up on `ffxD-experimental-alpha`

This investigation continues the unaccepted response-pilot work in
`fsrd_response_transfer_followup.md`. No production shader, DLL or game-quality
fix is claimed. Historical Joint RRTrace geometry remains useful evidence, but
does not validate the current alpha in Cyberpunk 2077. The user cannot currently
open the game; local diagnosis continues without requiring new captures.

## Camera input control

The synthetic converter used identity inverse projection while the native
runner used PerspectiveFovLH. For the fixed linear-depth, identity-view lighting
fixture, replace only the converter inverse projection by the inverse of the
exact native matrix from the applied dispatch record. Frame0 and frame32 all
seven native-format input payloads match the original bytes exactly.

The second agent independently rederived the generator and verified stored
bytes, format sizes, FP16 lobe reconstruction and inverse-matrix closure. This
eliminates that camera difference as a consumed-input explanation **only for
these two static frames**. It does not establish conformance of rotating cameras,
hardware-depth reconstruction, every frame/scene or actual game inputs.

## Measured provider defaults

A separate query-only utility creates one fresh128x80 context with signals34,
validation creation flag2 and API4202496, using the exact previously pinned AMD
DLL. Immediately after CreateContext, before any effect-key Configure or RR
Dispatch, query six defaults with `ffxQueryDescDenoiserGetDefaultKeyValue`.
Each query returnedOK with a finite float. Recorded float32 bits are authoritative.

- Disocclusion threshold: measured `.00999999978`; fork override `.1`.
- Cross-bilateral normal strength: measured `1`; fork override `.5`.
- Stability bias: measured `1`; fork override `.5`.
- Maximum radiance: measured `65504`; fork override `40000`.
- Radiance clipping standard-deviation K: measured `50`; fork override `40`.
- Gaussian kernel relaxation: measured `0`; fork override `.5`.

The direct DLL's provider-version query remains unsupported. That did not imply
the separate default-key query was unsupported. Defaults are not current active
values after configuration, universal values across providers, API numeric
validity limits or a quality recommendation. The original pinned repeat runner
does not query these keys. This utility performed zero native RR dispatches.

## Default-bundle repeat control

Preregister four fresh64-frame lighting-step contexts with the exact existing
runner binary. Only job tuning1 changes to tuning0, skipping all six effect-key
overrides together. Global debug Configure remains enabled. Input hashes and
all184-byte applied frame controls match the original tuning1 source exactly.
Metadata records no applied override values, rather than incorrectly labeling
the unused literals as active. Preserve full native FP16 lobes and selected
composed RGB at frames0,1,31,32,33,34,63.

An initial attempt completed one native context/64dispatches with zero ordinary
D3D/SDK messages, then Python metadata recording failed because the derived
helper omitted `pathlib.Path`. All original inputs, raw outputs and logs remain
retained. A separately identified corrected attempt completed the four repeats.
The first attempt is excluded from their comparison and counted separately.

In the four completed repeats, context0/1/3 match exactly; context2 differs.
Nonzero pairs have native RGB RMS `.0076225315`; alpha is exactly equal and zero.
First diffuse difference is frame24,y75,x32,R, preceding the frame32 light step.
First specular difference is frame26,y0,x10,G. Nonzero pair native RGB RMS is
`.0000802329` before32 and `.0107795889` from32. Selected composed pair RMS is
`.0011650992` overall / `.0015411882` from32. Independent audit reauthenticated
all inputs, controls, executable, provider, logs and FP16 bytes.

The six overrides are therefore not necessary for observed variability in this
fixture. The bundle control does not isolate a single key or identify a cause.
Four-context ranges are descriptive, not a statistical confidence bound. The
earlier tuned and transition-reset contexts remain evidence.

Spatial attribution of the one nonzero pair shows a single changed diffuse
value at frame24, then differences in both edge and interior pixels. At frame32,
diffuse and specular changed-pixel fractions are `.78408` and `.80811`; the
interior fractions exceed `.81`. This is not a purely border-confined difference
and does not itself establish a padding, race, precision or initialization bug.

## Further diagnostics

A separately compiled helper explicitly enables ID3D12Debug1 GPU-based validation
before device creation. This is different from the ordinary debug layer used in
the earlier successful runs and may change shader scheduling. Its first process
reached a300-second watchdog without completed output frames. The timeout is not
a detected validation error; partial stdout/stderr were not retained by that
first wrapper, and context creation/dispatch completion is unknown.

A separate retry preserves the same instrumented executable,64-frame input job,
provider and tuning1, allows900seconds, and writes stdout/stderr directly during
execution. It consumed substantial memory before a completed frame appeared:
the last recorded system observation had448528KiB free of16697804KiB physical
memory. A request to stop only the identified owned child was issued. Its tool
handles subsequently disappeared, the native process is now absent, and the
original running metadata is retained alongside a terminal reconciliation.
The stop command's completion and actual exit cause remain unproven; no stop
record file was produced. This distinction is preserved rather than inferring
an SDK failure or successful cancellation from the last process state.

Retained stdout confirms GPU-based validation was requested and context creation
completed, because the provider-version line appears after CreateContext.
Outputs and applied-controls files are empty and no complete validation summary
exists. Completed RR dispatch count is zero. Do not restart this heavy helper
merely because its old snapshot says running. No driver/global settings or
production files were changed, and no GPU-based-validation success is claimed.

## Previous-camera conversion conformance

The second agent specified a world planeZ10, current viewidentity and previous
Yrotation+.02radians, using the native perspective and matrices quantized to
their consumed float32 representation. Independent analytic world/view/UV/depth
closure maximum error stayed below5e-7world units. Low/high roughness CPU controls
give identical primary motion, with expected specular alpha10/0 respectively.

The root then ran four ordinary-debug conversion dispatches at roughness.1:
matched/identity inverse projection times production strength0/1 PSO selection.
All four agree with their stated converter reference to oneFP16ulp plus1e-5.
Both matched cases satisfy the physical previous-depth minus current-depth
reference at all pixels (RMS `.0000451368`, maximum `.0001163141`). Both identity
counterexamples fail physical closure (RMS `.12417872`, maximum `.21347865`).
Matched versus identity primary MVXY, normal/roughness/material and source lobe
RGB are byte-equal; MVZ differs as expected. This is a successful conversion
contract check and intentional wrong-input counterexample, not a shader defect,
native RR observation or image-quality fix. Current viewidentity does not test
a nonidentity current-view normal transform. The overall visual issue, pilot
acceptance, runtime implementation and real-game validation remain open.

Independent audit found the original worker removed CB/input/output staging
bytes and checked stdout without retaining per-job logs. Its result therefore
does not directly authenticate consumed CB/upload bytes or each original log.
Those limits and a misleading tolerance-key spelling (`1e5`, calculated as
`1e-5`) remain explicitly recorded. A separately derived four-call repeat uses
a capture worker that copies actual job bytes and stdout after completion and
before cleanup. All four numerical results agree with the original experiment;
this repeat changes retention only, and corrects the new metadata key spelling.

The second agent verified every retained416-byte CB, all17 input byte payloads,
all8 decoded output payloads against saved NPZs, the selected CSO hashes and all
four zero-error/zero-warning ordinary debug logs. Matched/identity arms change
only inverse-projection CB bytes64-127; strengths0/1 change only additive-strength
CB bytes414-415 and produce equal outputs for this fixture. Matched physical
failure count is0; the intentionally inconsistent identity arm fails at all10240
pixels. Original staging/log limitations remain in a separate audit.

The [exact-byte archive](evidence/fsrd_native_contract_followup/manifest.json)
adds four completed native repeats/256dispatches plus the separately qualified
metadata-failed native completion/64dispatches, one default-query context with
zeroRRdispatches, and12 conversion-only dispatches. With the previous package,
completed native totals including that metadata-failed completion are289contexts
/14128dispatches. Neither incomplete instrumented attempt contributes completed
RRdispatches or a validation pass. Large outputs remain at recorded external
paths with hashes. All visual acceptance requirements remain unresolved.
