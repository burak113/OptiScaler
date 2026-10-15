# P01 — OFF/ON measurement matrix (NRD→AMD RR bridge)

Scope: this document plans the A–E comparison runs from the tracking report
(`NRD_Bridge_Takip_Raporu_bdab0c01.md`, P01) and records which parts are already
covered by repository fixtures. It is a plan plus fixture mapping; it contains no
FPS or frame-time claim. The live rows are explicit user capture requests.

## A–E matrix

| Run | Startup hook/metadata | RR runtime | Recovery / Trace / debug | What the difference isolates |
|---|---|---|---|---|
| A | Not installed (separate launch) | Off | Off | Title + driver baseline without the bridge loaded |
| B | Installed | Off | Off | Startup/hook/metadata infrastructure cost alone |
| C | Installed | On | Recovery, Trace, debug off | RR bridge cost beyond B; RR renderer paths differ, so C−B is not "RR kernel cost" |
| D | Installed | On | Only Recovery on | Marginal Recovery cost over C |
| E | Installed | On | One diagnostic feature on | Diagnostic cost over C; never reported as the normal path |

Rules:
- Every row is a separate run. Native NRD denoise and RR are never enabled in
  the same run (K7). RR-on rows keep the native denoise counter at zero.
- First use and steady state are always reported separately; the same scene
  (camera path, resolution, exposure, warm-up) is required across rows.
- The values of interest are the CPU Consumer cadence quantiles and the
  thread-time / wait sums from the one-shot 100-interval window, plus live
  wait/hold distributions. They are not FPS.

## Fixture-side coverage (executed in this repo, no game)

- **B / startup cost separation:** `test_fsrd_nrd_runtime_off.py` drives the
  actual coordinator with startup hooks installed and the runtime toggled OFF
  in four modes (`startup-root`, `startup-table`, `toggle-root`,
  `toggle-table`), 101 native submissions each. It asserts zero provider work,
  zero native omissions and one complete 100-interval Consumer report, and now
  also asserts the measured per-interval cadence quantiles and the thread-time
  accessor naming split. This is the closest in-repo proxy for run B.
- **CopyDescriptors/RootTable call cost:** `test_fsrd_nrd_descriptor_copy_perf.py`
  measures call-level and slot-level cost, per-call wait/hold quantiles and the
  serialized writer window of the real copied-descriptor metadata path
  (CPU-only; synthetic heaps; no driver call). RootTable mirror call cost is
  **not** measured by any CPU fixture; see the live request below.
- **C-ish:** the actual-host transaction tests (`test_fsrd_nrd_native_transactions.py`,
  stencil/raster variants) exercise RR-on A/B transactions with the real signed
  provider while asserting native NRD filter GPU executions stay at zero. They
  are correctness/ownership evidence, not timing evidence.
- **E:** Trace/debug cost is not measured here; the tracking report requires a
  separate diagnostic-on run.

## Live capture requests (game required)

1. **Run A (bridge absent):** launch Cyberpunk 2077 once with the `dxgi.dll`
   bridge removed/renamed, same save and camera path as run B; capture the
   OptiScaler-free run with an external present-interval sampler if FPS context
   is wanted. This cannot be produced by any repository fixture.
2. **Run B:** with the bridge DLL installed but `FfxDenoiserNrdBridgeEnabled`
   (runtime) OFF for the whole session, stand still in a benchmarked spot for
   at least 15 s so the 100-interval perf line is emitted; keep the same
   resolution and settings as run A. Capture `OptiScaler.log`.
3. **Run C:** same spot, enable the RR runtime (menu) after the B window,
   Recovery/Trace/debug OFF; capture the next `window=100_gameplay_Consumer_intervals`
   perf line (now containing `consumer_interval_p50/p95/p99_ms`,
   `cpu_hook_thread_time_sum_ms_per_interval`,
   `lock_wait_thread_time_sum_ms_per_interval`) plus menu screenshot of the
   active settings.
4. **Run D/E:** repeat the same spot with only Recovery on (D) and only one
   diagnostic feature on (E); one perf window each.
5. **RootTable/CopyDescriptors live distribution:** with the bridge active,
   capture a 60 s gameplay window and the perf line; the current log exposes
   per-hook averages, but a live wait/hold p50/p95/p99 distribution for
   CopyDescriptors/RootTable still needs the instrumentation request below.

Sequencing rule for all rows: same save, same weather/time-of-day state where
possible, same camera walk; do not compare a first-use window against a
steady-state window.

## Known limits

- C−B mixes bridge cost with renderer-path differences; it must not be labelled
  "RR kernel cost".
- The 71,642 ms hook total from the earlier live log is a thread-time sum over a
  window that includes native calls; it is never a frame duration.
- Summing per-hook p95 values never yields a frame p95; only per-interval
  samples do (now collected as `intervalTicks` in the one-shot window).
