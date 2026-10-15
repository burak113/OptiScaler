# G05 — guide / domain / signal-kind experiment sequence (WP11)

**Inspection point:** `bdab0c01` · **Branch:** `sol/15e-signal` · **Type:**
experiment design. This document changes **no production behavior**. Every
runnable variant below executes only through existing test/oracle scripts or
existing menu/config keys.

Companion contract tables:
[`NRD_SIGNAL_MATERIAL_ALPHA_CONTRACT.md`](NRD_SIGNAL_MATERIAL_ALPHA_CONTRACT.md).

## 1. One axis per variant

A variant may change exactly one experimental axis. If a guide change and a
demod/remod or signal-kind change land in the same comparison, the difference
cannot be attributed. This is the WP11 dependency rule; it overrides any
convenience of combined runs.

## 2. Axis order

### Axis 1 — white vs native guide, RGB domain fixed (runnable now)

- Variants: `white` / `diffuse-only` / `specular-only` / `both` guide RGB.
- Fixed: same raw noisy series, depth, normal, surface motion, camera words,
  alpha words, provider defaults (defaults-probe), fresh physical context,
  NON_GAMMA_ALBEDO, `DD|IS` route.
- Synthetic runner (existing): `fsrd_nrd_rr_material_compare.py` over the
  frozen `material-v2` prepared views; properties in
  `test_fsrd_nrd_rr_material_quality.py`.
- In-game runner (existing menu/config key, no code change):
  `[FSR-RR] NrdBridgeNativeMaterialGuides` (default `true` = native guides;
  `false` = white guides). Guide-mode change resets RR history by design
  (`materialModeReset`), so A/B halves must start from an explicit history
  reset each.
- Metrics reported separately by the existing comparator domains: demodulated
  specular/diffuse, remodulated specular/diffuse, combined — each with
  `rgb_rmse` (noise/energy proxy), `chroma_rmse` (color energy),
  `detail_gradient_rmse` + `gradient_projection_ratio` (edge/detail mixing with
  material boundaries excluded), and reveal-age cohorts (`positive_stale_energy`
  = stale/ghost tail energy). Noise, color energy and edge mixing are never
  summed into one score.

**Measured baseline (recorded, prior signed-provider run
`15c-rr/material-v2-rr-root-run1`, 64 frames × 4 candidates, 33067 native
checks, 8830 Python checks; quoted from the sealed `comparison.json`, no new
GPU run by this task):** [arith — recorded result of a prior signed run]

| Candidate | Combined pre-Consumer RGB RMSE | Notable recorded deltas |
|---|---:|---|
| white | 0.00694524934 | baseline candidate |
| diffuse-only | 0.00685886 | diffuse RMSE −7.34 % vs white came from the *specular-only* candidate, not this one |
| specular-only | 0.00693522541 | diffuse RMSE −7.34 %; specular RMSE +0.32 %; spec age 9..16 positive stale energy +4.44 % |
| both | 0.00699517947 | demod spec chroma RMSE +1.46 %, diffuse chroma +6.79 % (worse) |

Recorded interpretation limits (from the sealed report, unchanged): the
material route is not a demonstrated reflection-detail fix; cross-lobe RMSE
shifts do not establish restored reflected detail; original and same-material
gradient projections must both be read (0.00874505 / 0.01550407 / 0.00778586 /
0.00790412 original-crop; 0.00169848 / 0.00832642 / 0.00072083 / 0.00096669
same-material pairs) so material color boundaries cannot masquerade as
recovered lighting detail. All raw rows, including worse reveal cohorts, are in
the unedited comparison JSON. **No "guide axis is settled" conclusion is
drawn; in-game A/B is still pending.**

### Axis 2 — RGB domain / compositor factor (conditional, blocked)

Preconditions, all currently open:

1. The title compositor's factor/exposure application to RR output must be
   verified (which factor, where applied, per lobe). [hypothesis]
2. The demodulated-domain meaning of the carried RGB must be confirmed against
   that compositor (is the RR output consumed as demodulated lighting or
   final color). [hypothesis]

Only after both: design a second-domain variant that changes the carried RGB
domain interpretation alone, with guides and signal-kind fixed. Prohibited
until then: extra π, any alpha rescale, remod/demod with an approximate BRDF
beyond the documented guide model, "physically corrected" factors without a
verified compositor identity.

### Axis 3 — signal-kind (third independent axis)

Signal-kind variants (e.g. which transport term the diffuse input is assumed
to carry) run only after axes 1 and 2 have their own conclusions, on the same
fixed controls. "Found the correct signal kind" may not be said while the
result is unknown — the axis produces comparisons, not confirmations, until a
verified physical model exists.

## 3. Controls required in every experiment

- Same material boundaries (asymmetric color palettes × metal values), plus
  the mirror / zero-roughness control (`fsrd_nrd_rr_mirror_oracle.py`) and the
  low-roughness sampling control (`fsrd_nrd_rr_lowrough_sampling.py`).
- Moving camera and moving object controls (the frozen sequence includes both).
- Same raw series or a disclosed repeat-noise separation.
- Provider defaults probe; fresh physical context per history; reset behavior
  recorded; Recovery off or pinned for the duration.
- Negative controls kept: strength0 identity, safe-RR-only fallback, native
  NRD counters zero while RR is active.

## 4. Prohibited combinations and shortcuts

1. Extra π or any compositor factor applied before verification. [rule]
2. Arbitrary alpha scaling of either alpha contract (D1/D2 in the contract
   doc). Alpha is not a quality knob. [rule]
3. Remod/demod with an approximate BRDF beyond the documented analytic guide
   model. [rule]
4. Guide switch + demod/remod change in one variant. [rule]
5. Sentinel-count inflation: tests are added to pin contracts, not to grow
   check numbers; check count is not scenario diversity. [rule]
6. Negative-alpha signal masking of inactive texels. Measured negative result
   (poisoned RGB leak), preserved. [live]

## 5. Runnable-infrastructure map

| Axis / variant | Runner (existing) | Mode |
|---|---|---|
| A1 synthetic guide ablation | `fsrd_nrd_rr_material_compare.py --prepared <sealed views>` (+ `--run` under lead GPU grant) | CPU validation / signed-provider run |
| A1 guide model numerics | `test_fsrd_nrd_rr_material_quality.py` | CPU |
| A1 controls: mirror / low-rough | `test_fsrd_nrd_rr_mirror_oracle.py`, `test_fsrd_nrd_rr_lowrough_sampling.py` | CPU |
| A1 in-game toggle | `[FSR-RR] NrdBridgeNativeMaterialGuides` (menu: Albedo guides) | production key, no code change |
| Signal mode (RGB/YCoCg word) identity | `test_fsrd_native_signal_modes.py`, `test_fsrd_nrd_pure_commit.py` | GPU / CPU default |
| D1 alpha statistics on real captures | `fsrd_nrd_rr_signal_contract.py` | CPU, read-only |
| D2 commit numerics | `test_fsrd_nrd_pure_commit.py`, `test_fsrd_nrd_pixel_flag.py` | CPU default / GPU |
| Capture ABIs feeding guides | `test_fsrd_nrd_material_capture.py`, `test_fsrd_nrd_material_params.py`, `test_fsrd_nrd_material_params_e2e.py` | CPU default + GPU variants |
| Radiance-domain loss/identity controls | `test_fsrd_nrd_radiance_domain.py` | CPU |

Axis 2 and axis 3 have **no runner** yet by design; building one before their
preconditions close would freeze an unverified model into the harness.

## 6. Status

| Item | State |
|---|---|
| Axis 1 synthetic measurement | Recorded (prior signed run; quoted, not re-run by this task) |
| Axis 1 in-game A/B | **Pending** — needs the user capture request (below) |
| Axis 2 | Blocked on compositor-factor and domain-meaning verification |
| Axis 3 | Blocked on axes 1–2 conclusions |
| Production behavior changed by this branch | None |

**Live capture request (user):** with identical camera path, scene, exposure
and resolution — one recording with `NrdBridgeNativeMaterialGuides=true` and
one with `=false`, each starting right after an explicit history reset, ≥64
full-render frames, plus the Game_Trace armed recording of the same passes.
Inspect-only ROI recordings are not sufficient for the temporal metrics.
