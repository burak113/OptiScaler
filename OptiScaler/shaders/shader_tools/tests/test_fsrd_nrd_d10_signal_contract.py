"""Pin D10/WP11 signal/material/alpha contract rows to production sources.

CPU-only source and independent-arithmetic checks; no compiled shader, no
provider, no GPU, no in-game claim. Each failure message names the row it pins
in tools/fsrd_frame_survey/NRD_SIGNAL_MATERIAL_ALPHA_CONTRACT.md. Rows whose
result is unknown stay hypotheses there; nothing here marks them "found
correct". Pins are deliberately source-exact: a contract change must update the
document and this test together.
"""
from __future__ import annotations
import json
import math
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
PRE = ROOT / 'OptiScaler/shaders/fsrd_preprocess/precompile'
SRC = ROOT / 'OptiScaler/shaders/fsrd_preprocess'
DOCS = ROOT / 'tools/fsrd_frame_survey'
CHECKS = 0


def need(value, message):
    global CHECKS
    CHECKS += 1
    if not value:
        raise AssertionError(message)


def read(path):
    text = path.read_text(encoding='utf-8', errors='replace')
    need(len(text) > 200, f'{path.name} present')
    return text


def f32(value):
    return struct.unpack('<f', struct.pack('<f', value))[0]


# The HLSL known-category literals are float32; compare with float32 words.
KNOWN_CATEGORIES = (0.0, f32(1.0 / 3.0), f32(2.0 / 3.0))


def safe_signal_alpha(value):
    """Row D1: every finite native alpha preserved (incl. signed zero); NaN/Inf -> +0."""
    return value if math.isfinite(value) else 0.0


def safe_radiance_channel(value):
    """Row A3: finite nonnegative radiance; negative/nonfinite collapse to zero."""
    return max(value, 0.0) if math.isfinite(value) else 0.0


def known_material(base_metal, category):
    """Row B: known category plus a finite packet clamped to [0,1]."""
    if category not in KNOWN_CATEGORIES:
        return False
    return all(math.isfinite(x) and 0.0 <= x <= 1.0 for x in base_metal)


def diffuse_guide(base, metal, category):
    """Row B: base.rgb * (1 - metal) when known, else white."""
    if not known_material((*base, metal), category):
        return 1.0
    return tuple(channel * (1.0 - metal) for channel in base)


def specular_guide_falls_back(category, roughness, no_v):
    """Row B: white fallback guards around the analytic GGX evaluation."""
    if category not in KNOWN_CATEGORIES:
        return True
    if not math.isfinite(roughness) or not math.isfinite(no_v):
        return True
    if roughness < 0.0 or roughness > 1.0 or abs(no_v) > 1.0:
        return True
    return False


def alpha_contract_cases():
    for value in (0.0, -0.0, 1e-7, -3.5, 65504.0, -65504.0, f32(2.0 ** -24),
                  float('inf'), float('-inf'), float('nan')):
        expected = value if math.isfinite(value) else 0.0
        actual = safe_signal_alpha(value)
        need(actual == expected and math.copysign(1.0, actual) == math.copysign(1.0, expected),
             'D1 input alpha preserves every finite native value incl. signed zero; malformed becomes +0')
        radiance = safe_radiance_channel(value)
        need(radiance == (max(value, 0.0) if math.isfinite(value) else 0.0) and radiance >= 0.0,
             'A3 input radiance is finite nonnegative; negative/nonfinite collapse to zero')


def guide_contract_cases():
    base = (0.65, 0.12, 0.025)
    need(diffuse_guide(base, 0.0, 0.0) == base,
         'B dielectric diffuse guide is the base color with no extra division/modulation')
    need(diffuse_guide(base, 1.0, KNOWN_CATEGORIES[1]) == (0.0, 0.0, 0.0),
         'B pure metal has a zero diffuse multiplier')
    need(diffuse_guide(base, 0.35, 0.5) == 1.0,
         'B unknown material category falls back to the white guide')
    need(diffuse_guide((0.65, 1.2, 0.025), 0.35, KNOWN_CATEGORIES[1]) == 1.0,
         'B out-of-range material packet falls back to the white guide')
    need(diffuse_guide((0.65, 0.12, float('nan')), 0.35, KNOWN_CATEGORIES[2]) == 1.0,
         'B nonfinite material packet falls back to the white guide')
    need(not specular_guide_falls_back(KNOWN_CATEGORIES[2], 0.5, -0.8),
         'B specular guard uses the explicit abs(NoV) convention')
    for roughness, no_v in ((-0.1, 0.7), (1.2, 0.7), (0.5, 1.5)):
        need(specular_guide_falls_back(KNOWN_CATEGORIES[1], roughness, no_v),
             'B out-of-range roughness/NoV falls back to the white specular guide')
    need(specular_guide_falls_back(float('nan'), 0.5, 0.7),
         'B unknown category falls back to the white specular guide')


def source_pins():
    bridge = read(PRE / 'FSRDNrdBridge.hlsl')
    need('already demodulated' in bridge,
         'A2 the conversion header declares the carried RGB domain as already demodulated')
    need('return isfinite(value) ? value : 0.0f;' in bridge and
         'negative inactive sentinels' in bridge,
         'D1 SafeSignalAlpha keeps every finite native alpha and replaces malformed values')
    need('isfinite(value.x) ? max(value.x, 0.0f) : 0.0f' in bridge,
         'A3 SafeRadiance clamps negative radiance and nonfinite to zero')
    need('float4(NrdSpecularMaterialGuide(baseMetal, normalRoughness.a, guideRoughness, noV), noV)' in bridge,
         'B params-ABI specular guide carries noV in the guide alpha channel')
    need('float4(NrdSpecularMaterialGuide(baseMetal, normalRoughness.a, normalRoughness.b, noV), noV)' in bridge,
         'B packed-normal-roughness specular guide carries noV in the guide alpha channel')
    need('float4(NrdDiffuseMaterialGuide(baseMetal, normalRoughness.a), 0.0f)' in bridge,
         'B diffuse guide alpha is zero, not a hit distance')
    need('float4(1.0f, 1.0f, 1.0f, noV)' in bridge and 'float4(1.0f, 1.0f, 1.0f, 0.0f)' in bridge,
         'B the no-guides path writes constant white guides with the same alpha convention')
    need("RGBA8_UNORM" in bridge,
         'B guide store keeps the provider-preferred normalized RGBA8_UNORM format')
    need('clamp(rawMaterialRoughness, 0.04f, 1.0f)' in bridge,
         'B the 0.04 roughness floor exists only in the analytic specular-guide evaluation')

    guides = read(PRE / 'FSRDNrdMaterialGuides.hlsli')
    need('return baseMetal.rgb * (1.0f - baseMetal.a);' in guides,
         'B diffuse guide is baseColor * (1 - metallic)')
    need('nativeCategory == 0.0f || nativeCategory == (1.0f / 3.0f) ||' in guides and
         'nativeCategory == (2.0f / 3.0f);' in guides,
         'B only the three known native categories are interpreted')
    need('all(baseMetal >= 0.0f) && all(baseMetal <= 1.0f)' in guides,
         'B the guide fallback guard requires a finite in-range packet')
    need('lerp(float3(0.04f,0.04f,0.04f),baseMetal.rgb,baseMetal.a)' in guides,
         'B specular F0 is the documented dielectric/metal lerp')
    need('NrdApproximateGgxMaterialAlbedo(F0,roughness*roughness,NoV)' in guides,
         'B the analytic GGX guide uses alpha = roughness squared, not a second unpack')

    capture = read(PRE / 'FSRDNrdNativeMaterialCapture.hlsl')
    need('float4(encoded * encoded, NativeMaterialParams[tid.xy].r)' in capture,
         'B capture squares the sqrt-encoded native baseColor to linear; metallic is materialParams.r')

    params = read(PRE / 'FSRDNrdNativeMaterialParamsCapture.hlsl')
    need('NrdRoundMaterialHalfNearestEven(float4(material.g, 0.0f, 0.0f, 0.0f)).x' in params,
         'B the params capture keeps raw material.G roughness for the guide shader')

    rr = read(SRC / 'FSRDNrdBridgeRR_Dx12.cpp')
    need('FFX_API_DISPATCH_DESC_TYPE_DENOISER_DIRECT_DIFFUSE' in rr and
         'FFX_API_DISPATCH_DESC_TYPE_DENOISER_INDIRECT_SPECULAR' in rr,
         'C the route is DirectDiffuse + IndirectSpecular with independent signals')
    need('dispatch.flags = FFX_DENOISER_DISPATCH_NON_GAMMA_ALBEDO | (reset ? FFX_DENOISER_DISPATCH_RESET : 0);' in rr,
         'A5/§7 NON_GAMMA_ALBEDO is set (existing linear-albedo convention, not a new proposal)')
    need('dispatch.motionVectorScale = { 1.0f, 1.0f, 1.0f };' in rr,
         'C dispatch keeps unit motion scale')
    need('dispatch.specularAlbedo = ffxApiGetResourceDX12(input.specAlbedo' in rr and
         'dispatch.diffuseAlbedo = ffxApiGetResourceDX12(input.diffAlbedo' in rr,
         'B guides are bound as the provider diffuseAlbedo/specularAlbedo inputs')

    stage = read(SRC / 'FSRDNrdBridge_Dx12.cpp')
    need('history->materialGuidesUsed != materialApplied' in stage and
         'if (materialModeReset) reset = true;' in stage and
         'history->materialGuidesKnown = true; history->materialGuidesUsed = materialApplied;' in stage,
         '§7 guide-mode change resets RR history (existing behavior, not a new fix)')

    signals = read(SRC / 'FSRDNrdRawSignals_Dx12.h')
    need('PrePassPending = PrePass' in signals,
         '§7 the PrePass enum alias exists (existing naming, not a new profile)')

    commit = read(PRE / 'FSRDNrdBridgePureCommit.hlsl')
    need('const float specAlpha = TitleSpec[tid.xy].a;' in commit and
         'const float diffAlpha = TitleDiff[tid.xy].a;' in commit,
         'D2 commit reads the title target alpha, not the staged alpha')
    need('float4(EncodeNrdSignal(StagedSpec[tid.xy].rgb, encoding), specAlpha)' in commit and
         'float4(EncodeNrdSignal(StagedDiff[tid.xy].rgb, encoding), diffAlpha)' in commit,
         'D2/A4 commit writes staged RR RGB under the preserved title alpha')
    need('The title owns opaque alpha' in commit and commit.count('LegacyUnusedBlend') == 1,
         'D2 the commit reads no title RGB and the ABI padding word stays unused')


def document_and_infrastructure_pins():
    contract = read(DOCS / 'NRD_SIGNAL_MATERIAL_ALPHA_CONTRACT.md')
    for token in ('SafeSignalAlpha', 'NON_GAMMA_ALBEDO', 'PrePassPending', 'materialModeReset',
                  'opaque alpha', 'double demodulation', 'do not re-invent', 'hit-distance'):
        need(token in contract, f'contract document pins the {token!r} row')
    sequence = read(DOCS / 'NRD_G05_EXPERIMENT_SEQUENCE.md')
    for token in ('Axis 1', 'Axis 2', 'Axis 3', 'Prohibited', 'defaults-probe',
                  'NrdBridgeNativeMaterialGuides'):
        need(token in sequence, f'experiment sequence document pins {token!r}')

    config = read(ROOT / 'OptiScaler/Config.cpp')
    need('readBool("FSR-RR", "NrdBridgeNativeMaterialGuides")' in config,
         'the in-game guide axis runs through the existing config key, not new code')
    header = read(ROOT / 'OptiScaler/Config.h')
    need('CustomOptional<bool> FfxDenoiserNrdBridgeNativeMaterialGuides {true};' in header,
         'the documented default of the guide axis key is native guides on')
    compare = read(ROOT / 'OptiScaler/shaders/shader_tools/tests/fsrd_nrd_rr_material_compare.py')
    need("'defaults-probe'" in compare,
         'provider defaults are queried by the existing defaults-probe, never assumed')


def main():
    alpha_contract_cases()
    guide_contract_cases()
    source_pins()
    document_and_infrastructure_pins()
    print(f'PASS d10_signal_contract_pins={CHECKS}')
    print(json.dumps({'schema': 'fsrd-d10-signal-contract-pins-v1', 'checks': CHECKS,
                      'scope': 'source + independent CPU arithmetic; no compiled shader, provider, '
                              'GPU or in-game claim; unknown-result rows stay hypotheses in the document',
                      'compiler_run': False, 'gpu_run': False, 'quality_claimed': False}))


if __name__ == '__main__':
    main()
