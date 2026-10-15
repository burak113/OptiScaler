# NRD recovery activity contract and D07 memory plan (15c-recovery)

Worktree `sol/15c-recovery`, base `bdab0c0100c1fe9a08317ac35ff070b4e864a4da`.
This document names the control model of the bridge's OWN separate lobe
recovery graph. Following the tracking report's rule, every name below is
**proposed diagnostic vocabulary (control-model names), not an INI key, not a
shader API and not a provider ABI**. Nothing here changes which pixels RR
produces: the shipped conditions are exactly the shipped conditions.

## 1. D06 — three named axes

Shipped conditions live in `FSRDNrdLobeRecoveryReference.hlsl` (Reference
pass) and the eligibility mirror in
`OptiScaler/shaders/shader_tools/tests/fsrd_recovery_eligibility_matrix.py`.

| Control-model name | Shipped condition | Lobe scope |
|---|---|---|
| `signalActivity` | Noisy lobe alpha (hit-distance metric) strictly `> 0` | Both lobes |
| `hitDistanceValidity` | Noisy lobe alpha finite (`all(isfinite(input))`) | Both lobes |
| `recoveryEligibility` | `geometry` AND signal axes above AND reference age/footprint gates | Both lobes |

### Chosen diffuse alpha=0 policy (explicit)

The shipped diffuse condition stays `input.a>0` — **this round chooses the
"inactive-alpha excluded" policy for BOTH lobes and documents it**, because:

1. The provider's DirectDiffuse documented active domain is non-negative and
   plausibly includes zero, so `input.a>0` is *optionally narrower* than the
   provider's activity; the behavior difference is proven (S1 §4 D06), but
   whether it is a *defect* depends on live alpha0 population data that is
   not measured here.
2. Activating genuinely-inactive samples is forbidden by the acceptance
   rule; without live alpha0/correlation data, widening coverage cannot
   prove it keeps inactive samples out. So no `>=0` widening is applied —
   for specular the same judgment applies: no blanket widening.
3. The negative-alpha sentinel shortcut stays rejected (poisoned RGB is a
   measured negative result in the packed-provider experiment).
4. `strength==0` identity and the pure-RR fallback are preserved exactly;
   no config key was added because no behavior was changed.

Widening later requires: live alpha0-rate capture (user request), the
eligibility matrix extended to the live claim, and an explicitly documented
config switch with `strength0`/passthrough proofs re-run.

### Rejection-reason vocabulary (ret reason)

Per-pixel primary reasons, priority-checked in this order inside the mirror:

`uncertain_hit_distance` (nonfinite alpha) → `roughness0` (roughness<=0) →
`inactive_alpha` (alpha<=0) → `geometry_mismatch` →
`insufficient_history_age` (eligible but aged < minimum) → `eligible`.

`budget_fallback` is the host-side seventh reason: the shared recovery
family or a helper failure denied the whole graph this frame. Host-visible
fallback reasons (new this round, control-model names):

`not_requested`, `debug_constraint`, `zero_strength`,
`external_family_unavailable`, `family_capacity`, `preparation_failed`,
plus the **real helper error text** (never truncated) published next to the
effective fallback in `RRSettingsState`.

Counter surfaces added this round (metadata-only, off the hot path):
- `LobeRecovery::Family`: `retainedPeakBytes`, `coldRetryDenials`,
  `preparationFailures` (monotone; only failure/cold paths touch them).
- `LobeRecovery::SnapshotDiagnostics()` exposes helper+family totals.
- The per-pixel GPU counters are NOT added in this graph: the Control flag
  name `NRD_RECOVERY_REJECT_STATS (8u)` is RESERVED for that future opt-in
  pass, which must bring its own UAV contract. Evidence class: code-level
  behavior (function getters) plus model arithmetic in the eligibility
  matrix test; no live pixel distribution was captured.

## 2. D07 — tier, byte admission and accounting

- The two native chains (A/B) share ONE `RRRecoveryFamily`; the 2 GiB family
  cap already sees both chains' cumulative charge. Effective-vs-requested
  tier is now published per recorded chain via `RRSettingsState`
  (`requestedTier=full_precision` when requested; `effectiveTier` locked to
  `FullPrecision` only after an admitted commit; fallback reason + error
  text otherwise). No automatic Mixed downgrade was implemented this round;
  automatic Mixed selection remains an open hypothesis (history-structure
  transition and tier flapping require a stable-selection policy first).
- Staging byte admission: `NrdBridgeCaptureBudget::StagingLedger` is shared
  across retained staging generations of one wrapper, counts slot pair
  bytes only, records a retained high-water and a monotone retired total,
  and is **disabled at its default limit 0** — the shipped per-context
  32-slot cap stays the single active admission. When a limit is set and a
  new slot exceeds the remaining budget, `NewSlot` fails and the mandatory
  RR transaction denies (no native denoise, no partially-recorded frame).
  Enabling key: none this round (a config key was deliberately not added;
  the ledger compiles in, inactive, and is exercised by fixtures).
- Accounting classes (P05) reported per class, "allocated" D3D extents only,
  never claimed as resident VRAM: conversion (`ConversionPass::Owned…`),
  raw snapshots (`RawSignalSnapshotPass::OwnedBytes`), RR staging pair bytes
  (`RRWrapper::OwnedStagingBytes` + the new ledger snapshot), provider
  internal cost — **unknown, reported unknown, never zero** —, recovery
  graph (`Family.graphBytes` includes retained old graphs,
  `retainedPeakBytes` high-water), debug targets (`AuxiliaryBytes`), and
  warm recording slots (`OwnedAuxiliaryBytes`). Retired staging bytes are
  the ledger's retired total; retired graph bytes return through
  `GraphCharge` retirement.
- Nominal decision boundary (Ek B formulas; GiB=2^30; LOGICAL texel payload,
  no padding/residency): 1440p A+B Full ≈ 2.013992 GiB, 4K single Full ≈
  2.265746 GiB, 4K A+B Mixed ≈ 2.966046 GiB — all three exceed the shared
  2 GiB cap at nominal payload alone. 1505×847 A+B Full ≈ 0.696650 GiB sits
  inside. Proof class: arithmetic in `test_fsrd_recovery_memory_model.py`.

## 3. P07 — transient aliasing research scope (design-only)

The aliasing investigation is restricted to same-frame transient resources:
resources written and read inside ONE prepared graph frame. History
ping-pong surfaces and every source re-read by a later recording are NOT
transients. Each alias candidate needs an explicit (last reader, next
writer, recording lifetime) triple review before any claim. No aliasing
optimization was applied or proven this round.

## 4. P09 — cold path visibility

The cold-retry backoff stays ~1 s (`DelayColdRetry`); this round adds:
cooldown denials counter, preparation-failure counter, one
rate-limited `LOG_WARN` per NEW (reason, text) pair, and the reason + real
text in the settings state. Normal frames check nothing new on the hot path.

## 5. Evidence bounds

Code-level behavior: getters/counters compile and run (header check,
capture-budget fixture). Arithmetic: memory model + eligibility matrix
tests (CPU). NOT claimed: live alpha0 population, resident VRAM totals,
FPS/quality change, automatic Mixed tier behavior, live A/B retention
high-water under a real provider session. Live capture requests are listed
in the work report.
