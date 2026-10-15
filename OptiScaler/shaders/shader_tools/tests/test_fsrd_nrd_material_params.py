"""Same-recording native material.G guide fidelity, with a distinct capture ABI.

CPU mode never invokes a compiler or GPU. --run is a serialized native job and
must run through lead_ops/run_task_test.py without --cpu. NativeBirth/detour
installation is outside this explicit-adapter fixture's scope; COM objects and
the RecordedComputeLease registry are real.
"""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[4]
PASS = ROOT / 'OptiScaler/shaders/fsrd_preprocess'
PRE = PASS / 'precompile'
OUT = Path(os.environ.get('FSRD_GPU_TEST_OUTPUT', 'F:/FSRD/sol_batch/15b-inputs/tests/material-params'))
REPORT = Path(os.environ.get('FSRD_TASK_REPORT_DIR', 'E:/FSRD/sol_batch/15b-inputs'))
LEGACY = {
    'FSRDNrdBridge': '2a3b01f53e543f144c4a269d3a9c834809acd15b1b572cd848563d923594c8c9',
    'FSRDNrdBridgeCopy': 'b221f986a212dfc04ed5652a68914dd443d545754eafb2f2e47d9223cf016eca',
    'FSRDNrdBridgeCommit': 'e7519a9c4c89083c79019943da4c7a46c01931ae626003de1bb677e132936cb9',
    'FSRDNrdBridgeNativeDebug': '41fa2ee2df558b7044b353c924ed80a4f5512e9debb2b98d2ca46e9ee7794ef9',
    'FSRDNrdBridgeMotion': 'd68d5ed4a04be0964ace8a72506484490c182f37ae8b10f126345e85d8a7c3d8',
    'FSRDNrdBridgeMotionNative': 'c564c2f0cf65760705d437e224efb02a956ed1d84dde2542f5f2f4e8250d1297',
    'FSRDNrdBridgeMaterial': 'fce84b6bdf7ff5079160efd3edf3b5bae5fbe73c1f83b2e61149c38c516f2204',
    'FSRDNrdNativeMaterialCapture': 'cdada5182a8dcdbdeefac64ebf4bf2e8e4682772bd9a8c7800b7708fd9d46597',
}
NEW = ('FSRDNrdNativeMaterialParamsCapture', 'FSRDNrdBridgeMaterialParams')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def scalar_brdf(base, metal, roughness, nov):
    """Independent expanded polynomial oracle, not HLSL matrix emulation."""
    f0 = .04 + (np.asarray(base, np.float64) - .04) * np.asarray(metal)[..., None]
    n = np.abs(np.asarray(nov, np.float64)); a = np.asarray(roughness, np.float64) ** 2
    bn = (.99044 - 1.28514*n) + (1.29678 - .755907*n)*a
    bd = (1 + 2.92338*n + 59.4188*n**3) + (20.3225 - 27.0302*n + 222.592*n**3)*a + (121.563 + 626.13*n + 316.627*n**3)*a**3
    sn = (.0365463 + 3.32707*n) + (9.0632 - 9.04756*n)*a
    sd = (1 + 3.59685*n**2 - 1.36772*n**3) + (9.04401 - 16.3174*n**2 + 9.22949*n**3)*a + (5.56589 + 19.7886*n**2 - 20.2123*n**3)*a**3
    bias = bn / bd * np.clip(f0[..., 1]*50, 0, 1)
    return f0*np.maximum(sn/sd, 0)[..., None] + np.maximum(bias, 0)[..., None]


def half_rne_positive(values):
    v = np.asarray(values, np.float32)
    bits = v.view(np.uint32)
    normal = ((bits + np.uint32(0xfff) + ((bits >> np.uint32(13)) & 1)) & np.uint32(0xffffe000)).view(np.float32)
    subnormal = np.rint(v*np.float32(16777216))*np.float32(1/16777216)
    return np.where(v < np.float32(2**-14), subnormal, normal)


class CpuTests(unittest.TestCase):
    def test_all_raw_material_codes_preserved_before_floor(self):
        raw = np.arange(256, dtype=np.float32) / np.float32(255)
        owned = half_rne_positive(raw)
        np.testing.assert_array_equal(owned, raw.astype(np.float16).astype(np.float32))
        self.assertEqual(owned[0], 0)
        self.assertLess(owned[10], .04)
        guide = np.clip(owned, .04, 1)
        np.testing.assert_array_equal(guide[:11], np.full(11, np.float32(.04)))
        np.testing.assert_array_equal(guide[11:], owned[11:])

    def test_base_and_metal_legacy_quantization_unchanged(self):
        codes = np.arange(1024, dtype=np.float32) / np.float32(1023)
        np.testing.assert_array_equal(half_rne_positive(codes*codes), (codes*codes).astype(np.float16).astype(np.float32))
        raw = np.arange(256, dtype=np.float32) / np.float32(255)
        np.testing.assert_array_equal(half_rne_positive(raw), raw.astype(np.float16).astype(np.float32))

    def test_brdf_matrix_and_independent_scalar_agree(self):
        n, r = np.meshgrid(np.linspace(0, 1, 31), np.linspace(.04, 1, 29))
        a = r*r; x = np.stack((n*0+1, n, n*n, n*n*n), -1)
        y = np.stack((a*0+1, a, a*a, a*a*a), -1)
        m1 = np.array([[.99044, -1.28514], [1.29678, -.755907]])
        m2 = np.array([[1, 2.92338, 59.4188], [20.3225, -27.0302, 222.592], [121.563, 626.13, 316.627]])
        m3 = np.array([[.0365463, 3.32707], [9.0632, -9.04756]])
        m4 = np.array([[1, 3.59685, -1.36772], [9.04401, -16.3174, 9.22949], [5.56589, 19.7886, -20.2123]])
        dot = lambda matrix, left, right: np.sum(np.einsum('ij,...j->...i', matrix, left)*right, -1)
        bias = dot(m1, x[..., :2], y[..., :2]) / dot(m2, x[..., [0, 1, 3]], y[..., [0, 1, 3]])
        scale = dot(m3, x[..., :2], y[..., :2]) / dot(m4, x[..., [0, 2, 3]], y[..., [0, 1, 3]])
        base = np.broadcast_to([.06, .42, .85], (*n.shape, 3)); metal = n*.7
        f0 = .04 + (base-.04)*metal[..., None]
        matrix = f0*np.maximum(scale, 0)[..., None] + np.maximum(bias*np.clip(f0[..., 1]*50, 0, 1), 0)[..., None]
        np.testing.assert_allclose(matrix, scalar_brdf(base, metal, r, n), rtol=2e-13, atol=2e-15)

    def test_parameter_changes_only_requested_guide_math(self):
        n = np.linspace(.05, 1, 256)
        base = np.broadcast_to([.03, .2, .8], (256, 3)); metal = np.linspace(0, 1, 256)
        native_b = np.full(256, .2); material_g = np.clip(np.linspace(0, 1, 256), .04, 1)
        old = scalar_brdf(base, metal, native_b, n); new = scalar_brdf(base, metal, material_g, n)
        self.assertGreater(np.max(np.abs(old-new)), .05)
        np.testing.assert_array_equal(base*(1-metal[..., None]), base*(1-metal[..., None]))

    def test_trailing_nullable_input_and_laziness(self):
        types = (PASS/'FSRDNrdBridge_Types.h').read_text()
        schema = types.split('struct ConversionInputs', 1)[1].split('};', 1)[0]
        self.assertRegex(schema, r'nativeMaterial = nullptr;[^\n]*\n\s*ID3D12Resource\* nativeMaterialRoughness = nullptr;')
        source = (PASS/'FSRDNrdBridgePass_Dx12.cpp').read_text()
        self.assertIn('const bool materialParams = materialGuides && inputs.nativeMaterialRoughness;', source)
        self.assertIn('if (materialParams && !owner->materialParamsInitialized)', source)
        self.assertIn('if (materialGuides && !materialParams && !owner->materialInitialized)', source)
        self.assertIn('FSRDNrdBridgeMaterialParams_cso),6,9)', source)
        self.assertEqual(source.count('list->ResourceBarrier(1,&materialBarrier);'), 2)

    def test_distinct_shader_abis_and_no_signal_change(self):
        shader = (PRE/'FSRDNrdNativeMaterialParamsCapture.hlsl').read_text()
        self.assertIn('UAV(u0, numDescriptors = 2)', shader)
        self.assertIn('material.g, 0.0f, 0.0f, 0.0f', shader)
        self.assertNotIn('clamp(', shader)
        bridge = (PRE/'FSRDNrdBridge.hlsl').read_text()
        extension = bridge.split('const float rawMaterialRoughness', 1)[1].split('#else', 1)[0]
        self.assertIn('clamp(rawMaterialRoughness, 0.04f, 1.0f)', extension)
        self.assertNotIn('OutNormalRoughness', extension)
        self.assertNotIn('OutSpec[p]', extension)
        self.assertNotIn('OutDiff[p]', extension)
        self.assertIn('normalRoughness.a, normalRoughness.b, noV', bridge)

    def test_all_sealed_legacy_assets_unchanged(self):
        for name, digest in LEGACY.items():
            with self.subTest(shader=name):
                self.assertEqual(sha(PRE/(name+'_Shader.cso')), digest)


def native_build():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from fsrd_toolchain import compile_cpp, dxc
    from build_fsrd_shader import build
    compiler = dxc(); OUT.mkdir(parents=True, exist_ok=True)
    # All old outputs go to scratch; these calls never republish legacy assets.
    for name, expected in LEGACY.items():
        target = OUT/(name+'.legacy-recompile.cso')
        subprocess.run([str(compiler), '-T', 'cs_6_2', '-E', 'CSMain', '-enable-16bit-types', '-O3',
                        '-Qstrip_debug', '-Qstrip_reflect', str(PRE/(name+'.hlsl')), '-Fo', str(target)], check=True)
        if sha(target) != expected:
            raise AssertionError('legacy bytecode changed: '+name)
    for name in NEW:
        build(name, compiler)
    module_path = Path(__file__).with_name('test_fsrd_nrd_conversion.py')
    spec = importlib.util.spec_from_file_location('material_params_conversion_support', module_path)
    support = importlib.util.module_from_spec(spec); spec.loader.exec_module(support)
    support.OUT = OUT; support.build(prepare_only=True)
    fixture = Path(__file__).with_name('fsrd_nrd_conversion_fixture.cpp').read_text()
    if fixture.count('static ULONG References(') != 1:
        raise AssertionError('native fixture prefix boundary changed')
    prefix = fixture.split('static ULONG References(')[0]
    marker = '    if (format == DXGI_FORMAT_R16G16B16A16_FLOAT) return 8;'
    if prefix.count(marker) != 1:
        raise AssertionError('pixel-size adapter boundary changed')
    prefix = prefix.replace(marker, '    if (format == DXGI_FORMAT_R16_FLOAT) return 2;\n'+marker)
    capture = (PASS/'FSRDNrdNativeMaterialCapture_Dx12.h').read_text()
    for include in ('#include "resource_tracking/ResTrack_Dx12.h"', '#include "State.h"'):
        if capture.count(include) != 1:
            raise AssertionError('capture include adapter boundary changed')
        capture = capture.replace(include, '')
    if capture.count('list->Dispatch(') != 1:
        raise AssertionError('actual capture dispatch instrumentation boundary changed')
    capture = capture.replace('list->Dispatch(', 'ParamsAuditDispatch(list,')
    capture = capture.replace('list->ResourceBarrier(', 'AuditedNrdBarriers(list,')
    (OUT/'production_material_params_capture.h').write_text(capture)
    audit = ('\nstatic uint32_t gParamsCaptureDispatches=0;\n'
             'static void ParamsAuditDispatch(ID3D12GraphicsCommandList* list,UINT x,UINT y,UINT z) '
             '{++gParamsCaptureDispatches;list->Dispatch(x,y,z); }\n')
    source = prefix + audit + '\n#include "production_material_params_capture.h"\n' + Path(__file__).with_name('fsrd_nrd_material_params_fixture.cpp').read_text()
    (OUT/'material_params.cpp').write_text(source)
    executable = OUT/'material_params.exe'
    compile_cpp(OUT/'material_params.cpp', executable, ('d3d12.lib', 'dxgi.lib'),
                (OUT, Path(__file__).parent, PASS, ROOT/'OptiScaler', ROOT/'OptiScaler/include', ROOT/'external/streamline'))
    return executable


def native_data():
    OUT.mkdir(parents=True, exist_ok=True)
    y, x = np.mgrid[:65, :127]
    r = (x*17+y*7) % 1024; g = (x*3+y*29) % 1024; b = (x*59+y*11) % 1024
    base = (r | (g << 10) | (b << 20) | ((x % 4) << 30)).astype('<u4')
    metal = (x*13+y*37) % 256; roughness = (x+y*127) % 256
    params = (metal | (roughness << 8) | (np.uint32(0x4b) << 16) | (np.uint32(0xe3) << 24)).astype('<u4')
    nr = np.stack((np.full(x.shape, 511), np.full(x.shape, 511), np.full(x.shape, 257), (x+y*3) % 4), -1)
    packed = (nr[..., 0] | (nr[..., 1] << 10) | (nr[..., 2] << 20) | (nr[..., 3] << 30)).astype('<u4')
    spec = np.stack((.002+x*.0001, .001+y*.0002, .003+(x+y)*.00003, 1+(x+3*y) % 97), -1).astype('<f2')
    diff = np.stack((.008+y*.0002, .004+x*.0001, .001+(x+y)*.00003, (x+3*y) % 61), -1).astype('<f2')
    values = {'base': base, 'params': params, 'nr': packed, 'spec': spec, 'diff': diff,
              'depth': np.full(x.shape, 5, '<f4'), 'motion': np.zeros((*x.shape, 4), '<f2')}
    for name, value in values.items():
        value.tofile(OUT/(name+'.bin'))
    return values


def native_compare(values, stdout):
    h, w = values['depth'].shape
    shape = (h, w, 4)
    outputs = lambda prefix, name, dtype: np.fromfile(OUT/(prefix+'-'+name+'.bin'), dtype).reshape(shape)
    material = np.fromfile(OUT/'params-base-metal.bin', '<f2').reshape(shape)
    legacy = np.fromfile(OUT/'legacy-base-metal.bin', '<f2').reshape(shape)
    np.testing.assert_array_equal(material.view('<u2'), legacy.view('<u2'))
    roughness = np.fromfile(OUT/'params-roughness.bin', '<f2').reshape(h, w)
    codes = ((values['params'] >> 8) & 255).astype(np.float32)
    np.testing.assert_array_equal(roughness.view('<u2'), (codes/np.float32(255)).astype('<f2').view('<u2'))
    for mode in ('white', 'legacy', 'params', 'off-ignored', 'fallback'):
        for signal in ('spec', 'diff'):
            np.testing.assert_array_equal(outputs(mode, signal, '<f2').view('<u2'), values[signal].view('<u2'))
        normals = np.fromfile(OUT/(mode+'-nr.bin'), '<u4').reshape(h, w)
        np.testing.assert_array_equal(normals, values['nr'])
    for name in ('spec', 'diff', 'nr', 'depth', 'motion', 'spec-albedo', 'diff-albedo'):
        self_a = (OUT/('legacy-'+name+'.bin')).read_bytes()
        if self_a != (OUT/('fallback-'+name+'.bin')).read_bytes():
            raise AssertionError('null roughness did not keep legacy path: '+name)
        if (OUT/('white-'+name+'.bin')).read_bytes() != (OUT/('off-ignored-'+name+'.bin')).read_bytes():
            raise AssertionError('OFF consumed optional material input: '+name)
    np.testing.assert_array_equal(outputs('legacy', 'diff-albedo', np.uint8), outputs('params', 'diff-albedo', np.uint8))
    # Independent scalar polynomial; compare only the normalized UAV's documented
    # rounding bound. Input half capture is already verified word-exact above.
    x, y = np.meshgrid(np.arange(w), np.arange(h))
    fovy = np.pi/3; ray = np.stack(((2*(x+.5)/w-1)*(w/h)*np.tan(fovy/2),
                                  -(2*(y+.5)/h-1)*np.tan(fovy/2), -np.ones((h, w))), -1)
    normal = np.full((h, w, 3), 511/1023*2-1); normal[..., 2] = 1-np.abs(normal[..., 0])-np.abs(normal[..., 1])
    normal /= np.linalg.norm(normal, axis=-1, keepdims=True)
    to_camera = -ray/np.linalg.norm(ray, axis=-1, keepdims=True)
    nov = np.clip(np.sum(normal*to_camera, -1), 0, 1)
    expected = scalar_brdf(material[..., :3], material[..., 3], np.clip(roughness.astype(np.float64), .04, 1), nov)
    category = ((values['nr'] >> 30) & 3)
    expected = np.where((category == 3)[..., None], 1, expected)
    actual = outputs('params', 'spec-albedo', np.uint8)[..., :3]/255
    error = float(np.max(np.abs(actual-np.clip(expected, 0, 1))))
    if error > .501/255 + 3e-6:
        raise AssertionError('material.G guide polynomial/UNORM bound: '+str(error))
    if np.array_equal(outputs('legacy', 'spec-albedo', np.uint8), outputs('params', 'spec-albedo', np.uint8)):
        raise AssertionError('material.G did not change specular guide')
    if 'debug_errors=0 debug_warnings=0' not in stdout:
        raise AssertionError('native debug-clean marker missing')
    return {'maximum_specular_guide_abs_error': error,
            'capture_roughness_codes': 256, 'all_signal_and_normal_words_unchanged': True,
            'legacy_null_and_off_exact': True, 'native_stdout': stdout}


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--run', action='store_true')
    options = parser.parse_args()
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(CpuTests))
    if not result.wasSuccessful():
        return 1
    if options.run:
        values = native_data(); executable = native_build()
        completed = subprocess.run([str(executable), str(OUT)], capture_output=True, text=True)
        (OUT/'native.stdout.log').write_text(completed.stdout); (OUT/'native.stderr.log').write_text(completed.stderr)
        print(completed.stdout, end=''); print(completed.stderr, file=sys.stderr, end='')
        completed.check_returncode()
        evidence = native_compare(values, completed.stdout)
        evidence.update(executable_sha256=sha(executable), legacy_cso_sha256=LEGACY,
                        new_cso_sha256={name: sha(PRE/(name+'_Shader.cso')) for name in NEW})
        (OUT/'result.json').write_text(json.dumps(evidence, indent=2))
        print('material params native comparisons PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
