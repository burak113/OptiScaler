# NRD → AMD RR signal, material and alpha contracts (D10 / WP11)

**Inspection point:** `bdab0c01` · **Branch:** `sol/15e-signal` · **Type:** contract
tables for RGB domain, guide domain, lobe kind and alpha lifetime, with an
explicit "already existing — do not re-invent" register.

This document pins what the code does today. It does **not** select a physical
signal kind, does **not** prove or disprove double demodulation, and does
**not** close any live-game question. Companion document:
[`NRD_G05_EXPERIMENT_SEQUENCE.md`](NRD_G05_EXPERIMENT_SEQUENCE.md) for the
experiment order that is allowed to change behavior, and where it is not.

## 0. Evidence labels

Every row carries one label:

- **[code]** — code-shown behavior: an exact source fact in this commit.
- **[arith]** — arithmetic/model result derived from an exact source fact or a
  prior signed-run recording; no new GPU/game execution claimed.
- **[live]** — live log/observation quoted from prior evidence (S1 or earlier
  test recordings); not reproduced in this branch.
- **[hypothesis]** — untested hypothesis; must not be cited as a result.

## 1. Signal path and carriers

| # | Stage | Producer (this commit) | Written content | Label |
|---|---|---|---|---|
| 1 | Native raw capture | `precompile/FSRDNrdRawCapture.hlsl` (A before Recon, B before PrePass) | Packed native half4 spec/diff into the private raw buffer after the owned 1536-byte constant prefix; no bridge transform of the words | [code] |
| 2 | Raw decode | `precompile/FSRDNrdRawDecode.hlsl` | Word-selected mode: RGB passthrough (0) or the exact native Consumer YCoCg→RGB inverse (1); RGB finite-clamped to [0, 65504] after decode, never before; input alpha kept if finite, else +0 | [code] |
| 3 | Conversion (radiance/geometry/guides) | `precompile/FSRDNrdBridge.hlsl` and `precompile/FSRDNrdBridgeGeometry.hlsl` | Sanitized radiance RGB, finite alpha, positive view depth, RR depth, motion, packed normal+roughness, spec/diff albedo guides | [code] |
| 4 | Provider dispatch | `FSRDNrdBridgeRR_Dx12.cpp` (~L989–1030) | `DirectDiffuse` + `IndirectSpecular` route; `NON_GAMMA_ALBEDO` (+ `RESET` on reset); `motionVectorScale = 1,1,1`; guides bound as `diffuseAlbedo`/`specularAlbedo` | [code] |
| 5 | Optional lobe recovery | `FSRDNrdLobeRecovery*` | Bridge-owned recovery only; never reads native NRD filtered lighting | [code] |
| 6 | Commit | `precompile/FSRDNrdBridgePureCommit.hlsl` | Staged RR RGB re-encoded with the live word-selected mode; title target alpha preserved | [code] |

The bridge header states the input domain directly: *"Cyberpunk NRD inputs are
already demodulated. Preserve RGB and their native hit-distance metric; white
albedos require no further demodulation."* No bridge stage multiplies or divides
the signal by a material factor. [code]

## 2. RGB domain per carrier (Table A)

| Carrier | Storage | RGB meaning | Not this RGB | Label |
|---|---|---|---|---|
| Native raw signal | packed half4 in private raw buffer | Title lighting as the title's own Consumer decodes it (mode 0 RGB / mode 1 YCoCg words) | Not an NRD-format hit-distance; not bridge-normalized radiance | [code] |
| `converted.spec/diff` (RR input) | RGBA16F | Demodulated linear radiance, sanitized finite nonnegative | No title gamma transfer applied; no factor64/exposure folded | [code] |
| Staged RR output (`lease->slot->spec/diff`) | RGBA16F | Provider output in the mode selected by the executed native word value (same value decode and commit must use) | Not final display color; Consumer transform is still pending | [code] |
| Committed title target RGB | title target format | `EncodeNrdSignal(staged RGB, encoding)` from the live `TitleConsumerConstants[75].w` when constants are present | No title RGB read, decoded, blended or used as fallback; factor64/exposure belong to the title Consumer | [code] |
| Albedo guides (`OutSpecAlbedo`/`OutDiffAlbedo`) | RGBA8_UNORM normalized store | Linear albedo guide (see Table B); `NON_GAMMA_ALBEDO` declares the linear convention to the provider | Not a demodulation divisor; RR multiplies demodulated lighting by guides internally | [code] |

The Recon ×1000 intermediate is a central sample weight that cancels in the
title's normalization; it is not an alpha or hit-distance unit conversion.
[arith, pinned by `test_fsrd_nrd_raw_signals.py`]

## 3. Guide domain (Table B)

| Row | Contract | Label |
|---|---|---|
| Guide capture input | Native baseColor target is sqrt-encoded; capture computes `encoded*encoded` → linear RGB, metallic = `materialParams.r`; quantized half-RNE before store (`FSRDNrdNativeMaterialCapture.hlsl`, `FSRDNrdMaterialQuantization.hlsli`) | [code] |
| Roughness input (params ABI) | `materialParams.G` kept raw; the 0.04 floor appears only as `clamp(rawMaterialRoughness, 0.04f, 1.0f)` in the analytic specular-guide evaluation; malformed values stay malformed and fall to the white fallback | [code] |
| Diffuse guide RGB | `baseMetal.rgb * (1 - baseMetal.a)` when the category is known and the packet is finite in [0,1]; else 1.0 (white) | [code] |
| Diffuse guide alpha | Always `0.0` (material and white paths) | [code] |
| Specular guide RGB | Analytic GGX albedo of AMD denoising.md5.5.2 with `F0 = lerp(0.04, base, metal)`, `alpha = roughness²`, `NoV = abs(dot(viewNormal, toCamera))`; finite nonnegative or white | [code] |
| Specular guide alpha | `noV` (view-space cosine), in the normalized RGBA8 store | [code] |
| White fallback (both guides) | Unknown category (only 0, 1/3, 2/3 are known), nonfinite or out-of-range packet, nonfinite/out-of-range roughness/NoV, or nonfinite guide result → `1.0` | [code] |
| No-guides path (`nativeMaterialGuides` off or no capture) | Constant white `float4(1,1,1,noV)` spec / `float4(1,1,1,0)` diff | [code] |
| Known categories | `0.0`, `1/3`, `2/3` — the title's four normalized categories are otherwise not interpreted | [code] |

Guide RGB is an **input model**, explicitly not the title's late-compositor
LUT/CB6 multiplier. The same analytic model is mirrored in
`fsrd_nrd_rr_material_quality.ggx_albedo` and numerically pinned by
`test_fsrd_nrd_rr_material_quality.py`. [code]+[arith]

## 4. Lobe / route contracts (Table C)

| Row | Contract | Label |
|---|---|---|
| Diffuse lobe | `ffxDispatchDescDenoiserDirectDiffuse`, captured before Recon; input `converted.diff`, output owned staged diff | [code] |
| Specular lobe | `ffxDispatchDescDenoiserIndirectSpecular`, captured before PrePass; input `converted.spec`, output owned staged spec | [code] |
| Histories | The two transactions have independent RR histories | [code] |
| B control words | PrePass `b6 register36.xy` selects mode 0/1/2 per lobe; parity/origin/rect words are recorded by Game_Trace | [code] |
| Diffuse physical content | **Open.** "DirectDiffuse" is the route name; the title's diffuse signal content (which exact transport term it carries) is *not* derivable from the name and is not selected here | [hypothesis — explicit non-claim] |
| Checkerboard activation in the live scene | **Open.** Old captures lack live selector operands | [hypothesis — explicit non-claim] |

## 5. Alpha contracts (Table D) — two separate contracts

**D1 — Input hit-distance alpha (RR raw input).** [code]

| Row | Contract |
|---|---|
| Sanitization | `SafeSignalAlpha`: every finite native value preserved, including negative inactive sentinels and signed zero; NaN/Inf → `+0`. Malformed values must never reach RR 1.2 |
| Zero | Zero is active/finite; it is not labelled "miss" |
| Negative | AMD inactive convention, not an environment-hit oracle; not clamped away |
| ×1000 | Reconstruction sample weight cancelled by normalization; not a unit conversion |
| Consumer scope | The two attested retained Consumers read **only RGB** from the committed targets (local DXIL closing evidence, prior session); unknown readers are not covered |

**D2 — Committed opaque alpha (title target).** [code]

| Row | Contract |
|---|---|
| Ownership | PureCommit reads the title target's own alpha and writes it back unchanged: `float4(EncodeNrdSignal(stagedRGB, encoding), titleAlpha)` |
| Meaning | The opaque channel is not an RR history/input and not a current hit-distance claim |
| First write | Whether the title initializes this alpha after native elision is **not proved** — open |
| Numeric pin | Stage alpha deliberately unrelated (NaN / −65504) is discarded; title alpha preserved bit-exactly — `test_fsrd_nrd_pure_commit.py` |

D1 and D2 must never be merged in an argument: an observed input alpha value
says nothing about the committed opaque channel and vice versa.

## 6. What this document does NOT establish

1. Demodulated-carried RGB combined with a non-white guide is **not**, by
   itself, proof of "double demodulation" anywhere in the pipeline. [hypothesis]
2. The physical kind of the diffuse signal is not chosen or confirmed by the
   route name. [hypothesis]
3. Live checkerboard activation, and any packed-provider layout conclusion,
   remain open; prior negative results are preserved, not superseded. [live]
4. No new quality, signal-kind, or double-demodulation correction is claimed.
   Result-unknown means "unknown", never "found correct".

## 7. Already existing — do not re-invent (S1/D10 register)

These exist at this commit and must not be re-proposed as new features or new
bugs:

| Item | Where | Label |
|---|---|---|
| `NON_GAMMA_ALBEDO` linear-albedo convention | `FSRDNrdBridgeRR_Dx12.cpp` `dispatch.flags` | [code] |
| Queried AMD defaults (no tuned SDK settings) | `fsrd_nrd_rr_material_compare.py` defaults-probe: disposable 1-frame context; all candidates require bit-identical effective/default words | [code] |
| History reset on guide-mode change | `FSRDNrdBridge_Dx12.cpp` `materialModeReset` → `reset` | [code] |
| PrePass enum alias | `FSRDNrdRawSignals_Dx12.h` `NativeRawProfile::PrePassPending = PrePass` | [code] |
| PureCommit uses staged RR RGB only | `FSRDNrdBridgePureCommit.hlsl` (no title RGB read path) | [code] |
| Negative-alpha sentinel shortcut rejected | Prior signed-provider experiment: inactive poisoned RGB leaked into output; not used | [live] |
| Packed vs reconstructed checkerboard | Prior signed-provider control: approximate alternatives (reconstruction higher RGB error, slightly lower chroma error in that toy scene) | [live] |
| Colored guides worse than white in some synthetic cases | `fsrd_nrd_rr_material_quality.md` recorded signed run | [live] |
| HLSL/CSO artifact identity vs deterministic source build | Different evidence kinds; neither is a quality verdict | [code] |

## 8. Pinning tests

| Contract row | Pinned by |
|---|---|
| A1–A2 raw capture/decode, alpha ×1000, packed half words | `test_fsrd_nrd_raw_signals.py` (existing) |
| A3 sanitation (`SafeRadiance`/`SafeSignalAlpha`), B guide rows, C route/flags, D commit, §7 register rows | `test_fsrd_nrd_d10_signal_contract.py` (new, CPU-only source+arithmetic) |
| A5/B commit numerics (alpha preservation, encoding modes) | `test_fsrd_nrd_pure_commit.py`, `test_fsrd_nrd_pixel_flag.py` (existing) |
| B guide analytic model numerics | `test_fsrd_nrd_rr_material_quality.py` (existing) |
| B capture ABI/state | `test_fsrd_nrd_material_capture.py`, `test_fsrd_nrd_material_params*.py` (existing) |
| D1 live-value statistics on published Recon snapshots | `fsrd_nrd_rr_signal_contract.py` (existing, read-only evidence) |

Updating any pinned source requires updating its contract row and the pinning
test in the same change — that is the point of the pins.
