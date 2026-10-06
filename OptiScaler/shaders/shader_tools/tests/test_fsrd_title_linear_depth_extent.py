"""Execute production tag capture/acquisition and title-depth selection on WARP.

The generated methods are copied from the application source on every run. Only
Config, logging and debug naming are substituted; real retained D3D12 resources,
Streamline structures, extent validation and view-format selection are used.
"""
from pathlib import Path
import argparse
import os
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fsrd_toolchain import compile_cpp

ROOT = Path(__file__).resolve().parents[4]


def method(source, signature):
    start = source.index(signature)
    opening = source.index('{', start)
    depth = 1
    end = opening + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


def run(verify_regression=False):
    out = Path(os.environ.get('FSRD_GPU_TEST_OUTPUT',
                             ROOT / 'tools_tmp/fsrd_title_linear_depth_extent'))
    out.mkdir(parents=True, exist_ok=True)
    feature = (ROOT / 'OptiScaler/upscalers/fsr31/FSRDFeature_Dx12.cpp').read_text(encoding='utf-8-sig')
    header = (ROOT / 'OptiScaler/hooks/Streamline_Hooks.h').read_text(encoding='utf-8-sig')
    hooks = (ROOT / 'OptiScaler/hooks/Streamline_Hooks.cpp').read_text(encoding='utf-8-sig')
    utils = (ROOT / 'OptiScaler/shaders/fsrd_preprocess/FSRDShaderUtils.h').read_text(encoding='utf-8-sig')
    # Copy the actual metadata declarations, not a test-only extent representation.
    metadata = header[header.index('enum class RRTaggedSignal'):header.index('struct SLConstantsSnapshot')]
    (out / 'fsrd_title_depth_metadata.inc').write_text(metadata, encoding='utf-8')
    helpers = method(hooks, 'static RRTaggedResourceDiagnostic CaptureSLResourceTag(')
    helpers += '\n' + method(feature, 'static bool ValidateSourceExtent(')
    helpers += '\nnamespace FSRD {\n' + method(utils, 'static inline DXGI_FORMAT GetViewFormat(') + '\n}\n'
    (out / 'fsrd_title_depth_helpers.inc').write_text(helpers, encoding='utf-8')
    acquire = method(feature, 'bool FSRDFeatureDx12::AcquireSLTaggedResource(').replace('FSRDFeatureDx12::', '')
    # The remainder acquires responsivity/diffuse guides independently. Retain the
    # complete production title-depth block, including its per-evaluation reset.
    optional = method(feature, 'void FSRDFeatureDx12::AcquireOptionalInputs(')
    optional = optional[:optional.index("    // The title's responsivity hint.")] + '}\n'
    optional = optional.replace('FSRDFeatureDx12::', '')
    (out / 'fsrd_title_depth_methods.inc').write_text(acquire + '\n' + optional, encoding='utf-8')
    include_dirs = (out, ROOT / 'OptiScaler/upscalers/fsr31', ROOT / 'external/streamline',
                    ROOT / 'external/FidelityFX-SDK/ffx-api/include/ffx_api')
    source = Path(__file__).with_name('fsrd_title_linear_depth_extent_test.cpp')
    exe = out / 'fsrd_title_linear_depth_extent_test.exe'
    compile_cpp(source, exe, ('d3d12.lib', 'dxgi.lib'), include_dirs=include_dirs)
    subprocess.run([str(exe)], check=True)
    # Pin the independent one-to-one contracts while depth deliberately accepts
    # oversized coverage. These assertions supplement the executed depth tests.
    ao = method(feature, 'bool FSRDFeatureDx12::AcquireTaggedAmbientOcclusionResources(')
    assert 'resource.effectiveWidth == RenderWidth() && resource.effectiveHeight == RenderHeight()' in ao
    assert 'diagnostic.effectiveWidth != renderWidth ||' in feature
    assert 'diagnostic.effectiveHeight != renderHeight)' in feature
    print('PASS: AO and specular hit-distance exact-size contracts remain in place', flush=True)
    if verify_regression:
        coverage = ('                FSRD::TaggedResourceExtentCovers(linearDepthDiagnostic,\n'
                    '                                                renderWidth, renderHeight) &&\n')
        assert optional.count(coverage) == 1
        mutant = out / 'missing_coverage'
        mutant.mkdir(exist_ok=True)
        (mutant / 'fsrd_title_depth_methods.inc').write_text(
            acquire + '\n' + optional.replace(coverage, ''), encoding='utf-8')
        mutant_exe = mutant / 'fsrd_title_linear_depth_extent_test.exe'
        compile_cpp(source, mutant_exe, ('d3d12.lib', 'dxgi.lib'),
                    include_dirs=(mutant, *include_dirs))
        result = subprocess.run([str(mutant_exe)], capture_output=True, text=True)
        assert result.returncode != 0 and '640x360 tag on 2048x2048 storage' in result.stderr, result
        print('PASS: removing production logical coverage reproduces the original regression', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-regression', action='store_true')
    run(parser.parse_args().verify_regression)
