"""Execute production roughness selection and acceptance with injectable input failures.

This compiles the complete, unmodified PrepareDenoiseConvInput body and its actual
roughness/extent validators. Only external resource acquisition, camera validation
and signal-layout failure results are mocked. --source-ref HEAD is a negative
control against the pre-fix source while the change remains uncommitted.
"""
from pathlib import Path
import argparse
import os
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fsrd_toolchain import compile_cpp

ROOT = Path(__file__).resolve().parents[4]
FEATURE = 'OptiScaler/upscalers/fsr31/FSRDFeature_Dx12.cpp'
HEADER = 'OptiScaler/upscalers/fsr31/FSRDFeature_Dx12.h'


def source_text(path, ref):
    if ref:
        return subprocess.check_output(['git', 'show', f'{ref}:{path}'], cwd=ROOT, text=True)
    return (ROOT / path).read_text(encoding='utf-8-sig')


def function(source, marker):
    """Locate a brace-delimited function, ignoring braces in strings/comments."""
    start = source.index(marker)
    tokens = re.compile(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|[{}]', re.S)
    depth = 0
    opened = False
    for match in tokens.finditer(source, start):
        token = match.group()
        if token == '{':
            depth += 1
            opened = True
        elif token == '}':
            depth -= 1
            if opened and depth == 0:
                return source[start:match.end()]
    raise AssertionError(f'Unclosed production function: {marker}')


def run():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-ref', help='Compile a Git revision instead of the working source')
    parser.add_argument('--scenario', choices=['packed-then-separate', 'separate-then-packed'],
                        help='Run one missing-albedo two-frame regression')
    args = parser.parse_args()
    source = source_text(FEATURE, args.source_ref)
    header = source_text(HEADER, args.source_ref)
    production = '\n\n'.join(function(source, marker) for marker in [
        'static XMUINT2 GetSubrectBase(',
        'static bool ValidateSourceExtent(',
        'static bool SupportsPackedRoughness(',
        *(['static bool SupportsSeparateRoughness('] if 'static bool SupportsSeparateRoughness(' in source else []),
        'RRResult FSRDFeatureDx12::PrepareDenoiseConvInput('
    ])
    conversion = function(source, 'bool FSRDFeatureDx12::ConvertDenoiserBuffers(')
    flag = re.search(
        r'if \(_roughnessSource == RoughnessSource::Packed\)\s*'
        r'_convDesc\.Flags \|= \(uint32_t\) FSRDConvFlags::IsRoughnessPacked;', conversion)
    assert flag, 'Conversion must derive the packed flag from committed instance state'
    production += '\n\nvoid FSRDFeatureDx12::ApplyRoughnessFlag()\n{\n' + flag.group() + '\n}\n'

    out = Path(os.environ.get('FSRD_GPU_TEST_OUTPUT', ROOT / 'tools_tmp/fsrd_roughness_acceptance'))
    out = out / ('baseline' if args.source_ref else 'working')
    out.mkdir(parents=True, exist_ok=True)
    (out / 'roughness_production.inc').write_text(production, encoding='utf-8')
    enum = function(header, 'enum class RoughnessSource : uint8_t') + ';\n'
    (out / 'roughness_enum.inc').write_text(enum, encoding='utf-8')
    keys = sorted(set(re.findall(r'\bNVSDK_NGX_Parameter_\w+', production)))
    (out / 'roughness_keys.inc').write_text('\n'.join(
        f'inline constexpr const char* {key} = "{key}";' for key in keys) + '\n', encoding='utf-8')
    # The isolated harness has no application PCH dependencies.
    (out / 'pch.h').write_text('#pragma once\n', encoding='utf-8')
    harness = Path(__file__).with_name('roughness_acceptance_test.h')
    test_source = out / 'roughness_acceptance_test.cpp'
    alignment = ROOT / 'OptiScaler/upscalers/fsr31/FSRInputAlignment.h'
    alignment_include = f'#include "{alignment.as_posix()}"\n' if alignment.exists() else ''
    test_source.write_text('#include "pch.h"\n' + alignment_include +
                           f'#include "{harness.as_posix()}"\n', encoding='utf-8')
    exe = out / 'roughness_acceptance_test.exe'
    compile_cpp(test_source, exe, include_dirs=(out,))
    result = subprocess.run([str(exe), *([args.scenario] if args.scenario else [])], text=True, capture_output=True)
    log = out / ('roughness_' + (args.scenario or 'results') + '.log')
    log.write_text(result.stdout + result.stderr, encoding='utf-8')
    print(result.stdout + result.stderr, end='')
    if result.returncode:
        raise SystemExit(result.returncode)


if __name__ == '__main__':
    run()
