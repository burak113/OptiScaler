# NRD generated-shader artifact contract (F06 / lane 15j-artifact-contract)

**Inspection point:** `943cdb54c` (+ shader_tools builder change in
`sol/15j-artifact-contract`) · **Type:** artifact-process contract, no production
behavior change.

This document pins what the shader artifact pipeline does today: which generated
header formats exist, which files use which format, what the canonical builder
(`OptiScaler/shaders/shader_tools/build_fsrd_shader.py`) must reproduce, and which
test enforces it. It closes Sol-audit finding **F06** ("Strict generated-header
reproducibility is not satisfied", `E:/FSRD/sol_batch/15-nrd-ghosting/SOL_AUDIT.md`)
via the audit's first recommended option: the canonical generator now reproduces the
sealed header format. It does **not** change any shipped shader byte, and it makes
**no** GPU, image-quality or live-game claim.

## 0. Evidence labels

- **[code]** — exact source/artifact fact in this commit.
- **[evidence]** — measured in this lane (commands and hashes in the lane report,
  `E:/FSRD/sol_batch/15j-artifact-contract/report.md`).
- **[boundary]** — explicit non-claim or known limitation.

## 1. The two generated header formats [code]

All 81 checked-in headers under
`OptiScaler/shaders/fsrd_preprocess/precompile/*_Shader.h` are in exactly one of two
formats, and both are LF (`*_Shader.h text eol=lf` is pinned in `.gitattributes`):

**Listing format — 78 files.** The dxc `-Fc` DXIL listing is kept for reference
inside an `#if 0` block, followed by the cso byte array:

```
#if 0
<dxc -Fc listing, per-line rstrip'd, CRLF normalized to LF>

#endif

const unsigned char <Name>_cso[] = {
    0x44, 0x58, 0x42, 0x43, ...   (12 bytes per line, ", " separated, 4-space indent)
};

```

**Sealed provenance format — exactly 3 files:** `FSRDNrdLobeRecoveryReference`,
`FSRDNrdLobeRecoveryDown`, `FSRDNrdLobeRecoveryBand`. These three ship DXIL
extracted from the validated full native signed no-correction graph (final-r1) —
the artifact provenance predates the standalone rebuild capability — so instead of a
reference listing the header opens with a provenance comment and the payload digest:

```
// Exact DXIL from full native signed no-correction graph final-r1; no recompilation.
// SHA-256: <SHA-256 of exactly the cso bytes in the array below>
const unsigned char <Name>_cso[] = {
    ... (identical array layout to the listing format)
};

```

The array writer (12 bytes/line, `", "` separator, `    ` indent, `};` terminator)
is shared by both formats. No third format exists in the tree.

## 2. Builder contract after F06 repair [code]

`build_fsrd_shader.py` now reproduces **both** formats, decided per shader:

| Rule | Value |
|---|---|
| Sealed set | `SEALED_PROVENANCE` keys = the three Recovery shaders; nothing else may use this format |
| Sealed prefix | `SEALED_PROVENANCE_COMMENT` (exact sentence above) + `// SHA-256: <digest of the freshly compiled payload>` |
| Listing prefix | unchanged `#if 0 ... #endif` wrapper with the fresh dxc listing |
| Compile flags | unchanged, factored into `compile_command()`; the trio keeps `-I <srcdir>` (validated graph compiler flags) |
| Line endings | mirrors the checked-in file (all 81 are LF today) |
| Publication | unchanged: nothing is rewritten unless bytes differ (`publish_if_changed`) |
| Pin guard | `check_sealed_provenance()`: a rebuild of a sealed shader whose payload digest differs from `SEALED_PROVENANCE` **fails the build** with re-pin instructions. The builder never re-labels different bytes with the old graph provenance; re-pinning is a conscious source edit |

## 3. Enforcing test [code]

`OptiScaler/shaders/shader_tools/tests/test_fsrd_shader_artifact_contract.py`
(CPU-only; DXC compile is its only execution; no GPU lock):

1. **Format census (81/81):** every header is exactly one of the two formats; the
   sealed set is exactly the pinned trio; every array region re-serializes
   identically through the canonical writer; every embedded array equals its
   `_Shader.cso` twin; sealed `// SHA-256:` lines equal the payload digest and the
   `SEALED_PROVENANCE` pins.
2. **Pin guard negative control (pure CPU):** drifted payload bytes are refused by
   `check_sealed_provenance` and cannot regenerate the sealed header; shipped bytes
   regenerate it byte-for-byte without a listing.
3. **Fresh-rebuild proof (F06 set):** for the 13 shaders whose sources changed in
   the audited window (8 Bridge/prepass + 2 RawPrePass decodes + the sealed trio), a
   fresh standalone dxc rebuild reproduces the checked-in `.cso` **and** the
   complete checked-in header byte-for-byte — full-file equality for both formats,
   which is exactly the strict gate F06 found unsatisfied.

Runner: `<venv-python> F:/FSRD/sol_batch/15j-artifact-contract/run_test.py
<name> <script.py> [--cpu]` (harness delegates to the canonical lead runner).

## 4. Evidence snapshot [evidence]

Measured in this lane at `943cdb54c` + builder change (DXC
`10.0.26100.0`, dxcompiler/dxil 1.8.2502.11; full commands and hashes in the lane
report):

- Rebuild of all 13 affected shaders through the modified builder: **26/26 header+cso
  files byte-identical** (SHA-256 and mtime unchanged; nothing was rewritten).
- Fresh dxc rebuild reproduces full header bytes for 13/13 (10 listing + 3 sealed).
- Sealed payload digests: Reference `5696c2ab…`, Down `8a063414…`, Band `b92089d1…`
  — header comment = `SEALED_PROVENANCE` pin = shipped `.cso` hash, all computed.
- Companion checks: `test_fsrd_nrd_lobe_recovery.py --prepare-only` PASS
  (embedded trio arrays equal the sealed independent graph CSOs),
  `test_fsrd_toolchain_cache.py` PASS, `test_fsrd_nrd_valid_fill.py` PASS.

## 5. Boundaries [boundary]

- DXC byte-reproducibility is pinned to the toolchain that produced the artifacts
  (Windows SDK 10.0.26100.0 dxc, dxcompiler 1.8). A DXC upgrade may change listing
  text and/or payload bytes; that is a conscious re-verification and (for the trio)
  a conscious re-pin, not a silent rewrite — the guard makes it loud.
- The two fused SSS shaders (`FSRDInputConvSkinFused[Additive]`) use the separate
  rootsignature-link pipeline; they are not part of the F06 set and are covered by
  their own tests, not by item 3.
- `verify_fsrd_mirrors.py` currently fails at the known baseline `namespace
  FloorSeed` marker error; builder runs use `--compile-only`. That red is a mirror
  verification issue inherited from the base, not an artifact-contract failure, and
  this lane's runs are **not** mirror verification passes.
- This contract is about build artifacts and their provenance metadata. It does not
  re-certify GPU behavior of the sealed DXIL (already covered by the sealed13 graph
  evidence) and makes no quality, performance or live-game claim.
