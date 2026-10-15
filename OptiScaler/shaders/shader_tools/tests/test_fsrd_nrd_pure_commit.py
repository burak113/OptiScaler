"""Pure staged-RR commit: source proof and explicit native shader regressions.

Default is CPU-only. --run needs the lead's compiler/GPU grant and the shared
run_task_test.py wrapper without --cpu. No SDK, NRD output, or game hook runs.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[4]
PRE = ROOT/'OptiScaler/shaders/fsrd_preprocess/precompile'
OUT = Path(os.environ.get('FSRD_GPU_TEST_OUTPUT', 'F:/FSRD/sol_batch/15b-inputs/tests/pure-commit'))
NAME = 'FSRDNrdBridgePureCommit'
COEFFICIENTS = [0, 0x3ec00000, 0x3f800000, 0x7fc12345, 0x7f800000, 0xff800000]
WIDTH, HEIGHT = 33, 17


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def root_text(source):
    definition = source.split('#define MainRS', 1)[1].split('Texture2D', 1)[0]
    return ''.join(re.findall(r'"([^\"]*)"', definition))


def stage_data():
    y, x = np.mgrid[:HEIGHT, :WIDTH]
    spec_palette = np.array([[1.5, 7, 9.25], [.125, .25, .5], [-.5, .125, 2],
                             [65504, 65504, 65504], [2**-24, 2**-23, 2**-22], [-0., 0., 0.]], '<f2')
    diff_palette = np.array([[9, 2.75, .5], [.375, 1.25, 2.5], [2, -.25, .125],
                             [65504, 1, 0], [2**-22, 2**-23, 2**-24], [0., -0., 0.]], '<f2')
    spec = np.zeros((HEIGHT, WIDTH, 4), '<f2'); diff = spec.copy()
    spec[..., :3] = spec_palette[(x+3*y) % len(spec_palette)]
    diff[..., :3] = diff_palette[(x*3+y) % len(diff_palette)]
    # Staged alpha is deliberately unrelated to opaque title alpha.
    spec[..., 3] = np.nan; diff[..., 3] = -65504
    return spec, diff


def title_data(variant):
    y, x = np.mgrid[:HEIGHT, :WIDTH]
    spec = np.zeros((HEIGHT, WIDTH, 4), '<f2'); diff = spec.copy()
    patterns = [[.125, 3, -.5], [np.nan, np.nan, np.nan], [np.inf, -np.inf, np.inf],
                [65504, -65504, 65504], [-0., 0., -65504]]
    spec[..., :3] = patterns[variant]; diff[..., :3] = patterns[4-variant]
    alphas_s = np.array([.75, -0., 0., -1, 65504], '<f2')
    alphas_d = np.array([2, -0., 0., 2**-24, -12], '<f2')
    spec[..., 3] = alphas_s[(x+y) % 5]; diff[..., 3] = alphas_d[(3*x+y) % 5]
    return spec, diff


def encoded(rr, encoding, alpha):
    result = rr.copy(); rgb = rr[..., :3].astype(np.float32)
    if encoding:
        result[..., 0] = ((rgb[..., 0]+np.float32(2)*rgb[..., 1])+rgb[..., 2])*np.float32(.25)
        result[..., 1] = (rgb[..., 0]-rgb[..., 2])*np.float32(.5)
        result[..., 2] = ((-rgb[..., 0]+np.float32(2)*rgb[..., 1])-rgb[..., 2])*np.float32(.25)
    result[..., 3] = alpha
    return result


class CpuProof(unittest.TestCase):
    def test_exact_legacy_root_abi(self):
        pure = (PRE/(NAME+'.hlsl')).read_text(); old = (PRE/'FSRDNrdBridgeCommit.hlsl').read_text()
        self.assertEqual(root_text(pure), root_text(old))
        self.assertIn('num32BitConstants = 5', pure)
        self.assertIn('TitleConsumerConstants[75].w != 0u', pure)

    def test_title_rgb_is_not_a_source(self):
        shader = (PRE/(NAME+'.hlsl')).read_text(); body = shader.split('void CSMain', 1)[1]
        self.assertEqual(shader.count('LegacyUnusedBlend'), 1)
        reads = re.findall(r'=\s*(Title(?:Spec|Diff)\[tid.xy\])([^;]*);', body)
        self.assertEqual(reads, [('TitleSpec[tid.xy]', '.a'), ('TitleDiff[tid.xy]', '.a')])
        self.assertEqual(body.count('EncodeNrdSignal(Staged'), 2)
        self.assertNotIn('native.rgb', body); self.assertNotIn('lerp(', body)
        self.assertNotIn('saturate(', body); self.assertNotIn('isfinite(', body)

    def test_all_perturbations_keep_the_same_opaque_alpha(self):
        baseline = title_data(0)
        for variant in range(5):
            for actual, original in zip(title_data(variant), baseline):
                np.testing.assert_array_equal(actual[..., 3].copy().view('<u2'), original[..., 3].copy().view('<u2'))
        self.assertTrue(np.isnan(title_data(1)[0][..., :3]).all())
        self.assertTrue(np.isinf(title_data(2)[0][..., :3]).all())

    def test_expected_results_never_depend_on_legacy_coefficient_or_title_rgb(self):
        stage = stage_data()
        for encoding in (0, 1):
            expected = [encoded(rr, encoding, title[..., 3]) for rr, title in zip(stage, title_data(0))]
            for variant in range(5):
                for coefficient in COEFFICIENTS:
                    for rr, title, reference in zip(stage, title_data(variant), expected):
                        np.testing.assert_array_equal(encoded(rr, encoding, title[..., 3]).view('<u2'), reference.view('<u2'))
        self.assertIn(0x3f800000, COEFFICIENTS); self.assertIn(0x7fc12345, COEFFICIENTS)


def input_files():
    OUT.mkdir(parents=True)
    for signal, data in zip(('spec', 'diff'), stage_data()): data.tofile(OUT/('stage-'+signal+'.bin'))
    for variant in range(5):
        for signal, data in zip(('spec', 'diff'), title_data(variant)):
            data.tofile(OUT/('title%d-'%variant+signal+'.bin'))
    for mode in (0, 1):
        for signal, rr, title in zip(('spec', 'diff'), stage_data(), title_data(0)):
            encoded(rr, mode, title[..., 3]).tofile(OUT/('expected%d-'%mode+signal+'.bin'))


def compiled_alpha_only_proof(assembly):
    handles = re.findall(r'(%\d+) = call %dx.types.Handle @dx.op.createHandle\(i32 57, i8 1, i32 \d+, i32 [01], i1 false\)', assembly)
    if len(handles) != 2: raise AssertionError('exact two title UAV handles required')
    loads = []
    for handle in handles:
        loads += re.findall(r'(%\d+) = call %dx.types.ResRet.f32 @dx.op.textureLoad.f32\(i32 66, %dx.types.Handle '+re.escape(handle)+r',', assembly)
    if len(loads) != 2: raise AssertionError('exact two title alpha loads required')
    for value in loads:
        extracts = re.findall(r'extractvalue %dx.types.ResRet.f32 '+re.escape(value)+r', (\d+)', assembly)
        if extracts != ['3']: raise AssertionError('compiled title RGB data dependency: '+repr(extracts))
        uses = [line for line in assembly.splitlines() if re.search(re.escape(value)+r'(?!\d)', line)]
        if len(uses) != 2: raise AssertionError('title load has an unexpected compiled consumer')
    b0 = re.findall(r'(%\d+) = call %dx.types.Handle @dx.op.createHandle\(i32 57, i8 2, i32 \d+, i32 0, i1 false\)', assembly)
    if len(b0) != 1: raise AssertionError('exact b0 handle required')
    rows = re.findall(r'@dx.op.cbufferLoadLegacy.\w+\(i32 59, %dx.types.Handle '+re.escape(b0[0])+r', i32 (\d+)\)', assembly)
    if not rows or set(rows) != {'0'}: raise AssertionError('compiled code reads fifth legacy constant')
    return dict(title_uav_loads=2, extracted_title_components=[3, 3], b0_register_rows=[0], legacy_fifth_word_read=False)


def run_native():
    sys.path.insert(0, str(HERE.parent))
    from fsrd_toolchain import compile_cpp, dxc
    from build_fsrd_shader import build
    compiler = dxc(); legacy_files = [PRE/('FSRDNrdBridgeCommit'+suffix) for suffix in ('.hlsl', '_Shader.cso', '_Shader.h')]
    before = {str(path): sha(path) for path in legacy_files}
    build(NAME, compiler)
    assembly = (PRE/(NAME+'_Shader.h')).read_text().split('#endif', 1)[0]
    ir = compiled_alpha_only_proof(assembly)
    original = (HERE/'fsrd_nrd_conversion_fixture.cpp').read_text()
    if original.count('static ULONG References(') != 1: raise AssertionError('existing fixture prefix changed')
    prefix = original.split('static ULONG References(')[0]
    marker = '#include "production_nrd_pass.cpp"'
    if prefix.count(marker) != 1: raise AssertionError('fixture include seam changed')
    include = '#include "'+(HERE/'dx12_shader_test_support.h').as_posix()+'"\n'
    include += '#include "misc/NrdBridgeOwned_Dx12.h"\n#include "FSRDNrdSignalConstants_Dx12.h"\n'
    prefix = prefix.replace(marker, include)
    source = prefix+(HERE/'fsrd_nrd_pure_commit_fixture.cpp').read_text()
    (OUT/'pure_commit.cpp').write_text(source)
    executable = OUT/'pure_commit.exe'
    compile_cpp(OUT/'pure_commit.cpp', executable, ('d3d12.lib', 'dxgi.lib', 'd3dcompiler.lib'),
                (OUT, HERE, PRE.parent, ROOT/'OptiScaler', ROOT/'OptiScaler/include', ROOT/'external/streamline'))
    from test_fsrd_nrd_bridge_rr import bounded_run
    text, peak, elapsed, log = bounded_run([str(executable), str(OUT)], OUT/'native')
    print(text, end='')
    if 'pure_commit PASS' not in text or 'debug_errors=0 debug_warnings=0' not in text: raise AssertionError('native result incomplete')
    if {str(path): sha(path) for path in legacy_files} != before: raise AssertionError('legacy Commit source/assets changed')
    result = dict(shader_sha256=sha(PRE/(NAME+'_Shader.cso')), executable_sha256=sha(executable),
        native_stdout=text, peak_resident_bytes=peak, native_seconds=elapsed, native_log=str(log),
        compiled_data_dependency_proof=ir, legacy_untouched_sha256=before,
        coefficient_words=COEFFICIENTS, actual_shader_only=True, provider_invoked=False,
        nrd_rgb_used=False, test_source_sha256=sha(Path(__file__)))
    (OUT/'result.json').write_text(json.dumps(result, indent=2)+'\n')


HERE = Path(__file__).resolve().parent
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--run', action='store_true'); args = parser.parse_args()
    tests = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(CpuProof))
    if not tests.wasSuccessful(): raise SystemExit(1)
    if args.run:
        if OUT.exists() or not OUT.resolve().is_relative_to(Path('F:/FSRD/sol_batch/15b-inputs').resolve()):
            raise AssertionError('fresh own-task native output required; preserve negatives')
        input_files(); run_native()
