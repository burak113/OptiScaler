"""SR depth re-encoding: the shader formula against FFX SR's own decode, and its copies in sync.

The C++ test mirrors depth_encode.hlsl and decodes with FSR3's deviceToViewDepth. The source
checks keep that mirror, the runtime-compiled copy in DE_Common.h and the shader together.
"""
from pathlib import Path
import os
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fsrd_toolchain import compile_cpp

ROOT = Path(__file__).resolve().parents[4]
SHADER = ROOT/'OptiScaler/shaders/depth_encode/precompile/depth_encode.hlsl'
COMMON = ROOT/'OptiScaler/shaders/depth_encode/DE_Common.h'


def check_sources():
    hlsl = SHADER.read_text(encoding='utf-8')
    common = COMMON.read_text(encoding='utf-8')
    embedded = common[common.index('R"(') + 3:common.rindex(')"')]
    assert embedded == hlsl, 'DE_Common.h differs from depth_encode.hlsl'
    # The formula the C++ mirror implements.
    for line in ('const float raw = abs(LinearDepth.Load(int3(id.xy, 0)));',
                 'float d = 1.0f;',
                 'if (!isnan(raw))',
                 'const float z = clamp(raw, n, f);',
                 'd = Infinite != 0 ? 1.0f - n / z : (f * (z - n)) / (z * (f - n));',
                 'DeviceDepth[id.xy] = saturate(Inverted != 0 ? 1.0f - d : d);'):
        assert line in hlsl, line
    feature = (ROOT/'OptiScaler/upscalers/fsr31/FSRDFeature_Dx12.cpp').read_text(encoding='utf-8-sig')
    encode = feature[feature.index('bool FSRDFeatureDx12::EncodeSRDepth('):]
    encode = encode[:encode.index('\n}\n')]
    # Encoded for the SR context's own flags, and SR decodes with the same planes.
    for line in ('(_upscaleCtxDesc.flags & FFX_UPSCALE_ENABLE_DEPTH_INVERTED) != 0',
                 '(_upscaleCtxDesc.flags & FFX_UPSCALE_ENABLE_DEPTH_INFINITE) != 0',
                 'upscalerDesc.cameraNear = encoding.cameraNear;',
                 'upscalerDesc.cameraFar = encoding.cameraFar;'):
        assert line in encode, line
    print('PASS: SR depth encode sources agree')


def run():
    out = Path(os.environ.get('FSRD_GPU_TEST_OUTPUT', ROOT/'tools_tmp/fsrd_sr_depth_encode/tests'))/'sr_depth_encode'
    exe = out/'fsrd_sr_depth_encode_test.exe'
    compile_cpp(Path(__file__).with_name('fsrd_sr_depth_encode_test.cpp'), exe)
    subprocess.run([str(exe)], check=True)
    check_sources()


if __name__ == '__main__':
    run()
