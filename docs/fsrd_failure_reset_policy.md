# Reset after a failed FSRD frame — 2026-09-30

Two existing false returns after successful native RR recording now call
`InvalidateDenoiserHistory()`: composition dispatch failure and SR upscale
failure. The change adds eight lines to `FSRDFeature_Dx12.cpp`. It requests
a conservative reset on the next valid RR setup after a partially recorded
frame is reported as failed. The stain/wave objective remains open.

The existing helper invalidates native CPU history and composition history.
On the next valid setup, the existing control flow sets native RESET,
camera position delta to zero, previous view/jitter to current view/jitter,
and `MotionHistoryValid` to false. It does not zero the title's XY motion
values. The composition guard subsequently calling `Finish(false)` is
idempotent and does not flip its history read index.

An independent source review checked the exact eight-line change. Reversing
the two added blocks reproduces the committed pre-policy source after
newline normalization. Eighteen pre-policy source/snapshot pairs were
checked; only the intended cpp differs. Normal success, debug/bypass paths,
earlier returns and optional postprocessing's existing outer success
contract are unchanged. No new resource lifetime or submission behavior is
introduced.

The isolated [discarded-recording diagnostic](fsrd_native_discarded_recording_diagnostic.md)
and [SDK call-presence control](fsrd_native_gap_call_presence.md) establish
that explicit reset restores matching reference output for their pinned
wave cohort. Those fixtures do not execute these production failure branches
or establish the game's failure/submission behavior. Their existing native
work is not counted again for this change.

If a caller executes a failed frame's otherwise valid RR prefix, the reset
can discard useful accumulation on the next RR evaluation. This is the
intentional cost of conservatively handling the failed recording. The
change does not observe successful evaluations later discarded by a caller,
repair already-recorded successors, reset the SR context, or resolve pending
constant-buffer/descriptor lifetime. Exceptions outside these checked bool
branches retain their existing behavior. No current-alpha game capture or
accepted visual solution is claimed.

The full solution Release/x64 compile and link passed with MSBuild
17.14.51.32402 and v143. All 198 evaluated compile items had `/MP` disabled;
`/m:1` and `/nodeReuse:false` were used. MSBuild reported 76 warnings and
zero errors; the full diagnostics are retained, including LNK4098. This
was one actual build. An earlier metadata-only preparation stopped at an
unnecessary linker-help assertion before compilation and is preserved.

The DLL remains in the isolated validation folder, with SHA256
`d1ca5e38f05ca1680be65a13bd601e72410a18e6e5c6d33eaa630fc13e35d0fe`.
The reviewed/compiled working cpp has SHA256
`d2cb58c65f6e9d3699e56e34675e6d50593b2bd89bd568025083cb8e09fdd628`;
Git's LF-normalized blob is
`3204de5c97f0af8f73f9985736e66c8689fd2cdeda509960bb3703c1405b3e29`.
Their bytes agree after CRLF-to-LF replacement only. The archived reviewed
source retains the compiled raw bytes.
All 273 pinned source, shader, provider, project and resource-header identities
matched before and after the build. Prebuild metadata regeneration and
postbuild packaging were disabled through an owned import; existing version
metadata was retained. No deployment, game run, native RR call or GPU test
occurred during this validation. Compilation does not establish runtime
recovery or visual acceptance.

The [compact evidence](evidence/fsrd_failure_reset_policy/manifest.json)
preserves the reviewed source, independent review, full build diagnostics,
effective settings, preparation qualification and generated-file cleanup.
The compiled DLL, changed-source object and binary build log retain external
size/SHA identities. Native totals remain 398 contexts and 21,050 successful
API RR recordings, including 21,042 queued recordings and eight recorded-only
discards; the four no-API omissions remain separate.
