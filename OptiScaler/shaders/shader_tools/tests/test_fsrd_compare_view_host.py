"""Host/source invariants for the compare (split) view.

These are fast static checks (no GPU) that the compare view stayed a display-only,
post-SR presentation and that the canonical composition still feeds the upscaler and
GAME_TRACE. Run:  python OptiScaler/shaders/shader_tools/tests/test_fsrd_compare_view_host.py
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[4]
PRE_CPP = ROOT / 'OptiScaler/shaders/fsrd_preprocess/FSRDPreprocessor_Dx12.cpp'
FEATURE_CPP = ROOT / 'OptiScaler/upscalers/fsr31/FSRDFeature_Dx12.cpp'
COMPARE_HLSL = ROOT / 'OptiScaler/shaders/fsrd_preprocess/precompile/FSRDCompareView.hlsl'

checks = []


def check(name, condition, **metrics):
    checks.append(bool(condition))
    print(('PASS' if condition else 'FAIL') + ' ' + name + ' ' + str(metrics))


def function_body(text, signature):
    start = text.index(signature)
    brace = text.index('{', start)
    depth = 0
    for i in range(brace, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                return text[brace:i + 1]
    raise ValueError('unterminated ' + signature)


def main():
    pre = PRE_CPP.read_text(encoding='utf-8')
    feature = FEATURE_CPP.read_text(encoding='utf-8')
    compare = COMPARE_HLSL.read_text(encoding='utf-8')

    # 1. The composition the upscaler/GAME_TRACE read is never the compare composite.
    comp = function_body(pre, 'ID3D12Resource* CompositionColor() const')
    check('CompositionColor() never returns the compare composite', 'm_compare' not in comp)
    check('GetCompositionOutput() returns CompositionColor()',
          'return m_impl->CompositionColor();' in pre)

    # 2. Composition only captures snapshots; it never builds/presents the split.
    dispatch = function_body(pre, 'void DispatchComposition(ID3D12GraphicsCommandList* cmdList, const CompositionDesc& desc)')
    check('DispatchComposition captures snapshots', 'CaptureCompare(' in dispatch)
    check('DispatchComposition never builds the split', 'DispatchCompare(' not in dispatch)
    check('DispatchComposition never presents the split', 'PrepareComparePresentation(' not in dispatch)

    # 3. Presentation happens after the canonical SR dispatch and its GAME_TRACE capture.
    sr_dispatch = feature.index('DispatchUpscaler(InCommandList, upscalerDesc)')
    sr_capture = feature.index('CompleteGameTraceSr(')
    present = feature.index('FSRDConvShader->PrepareComparePresentation(')
    check('SR dispatch precedes the compare presentation', sr_dispatch < present)
    check('same-evaluation SR capture precedes the compare presentation', sr_capture < present)
    check('SR still receives the canonical composition',
          'FSRDConvShader->GetCompositionOutput()' in feature)

    # 4. The split is presented into the upscaler output resource, not the composition.
    present_body = feature[present - 400:present + 900]
    check('presentation targets the upscaler output resource',
          'upscalerDesc.output.resource' in present_body)
    check('presentation only runs on the RR composition path',
          'UpscalerInputMode::RRComposition' in present_body)

    # 5. Shader: resampling path present, no second denoiser/SR dispatch.
    check('compare shader resamples both halves with SampleLevel', 'SampleLevel' in compare)
    check('compare shader has an embedded root signature', '[RootSignature(MainRS)]' in compare)
    check('compare shader has no barrier/denoiser trickery',
          'Dispatch(' not in compare and 'FFX' not in compare)

    passed = all(checks)
    print(('PASS' if passed else 'FAIL') + f' {sum(checks)}/{len(checks)} host invariants')
    return 0 if passed else 1


if __name__ == '__main__':
    sys.exit(main())
