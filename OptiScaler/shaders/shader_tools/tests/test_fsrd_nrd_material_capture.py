"""Native material snapshots, real GPU lease registry, and pinned SDK guide math.

Run through run_task_test.py without --cpu; the wrapper owns the GPU/compiler
slot. No game pixels or binaries are needed by this deterministic fixture.
The D3D callbacks are explicit adapters, not a NativeBirth/detour-install test.
"""
from pathlib import Path
import hashlib
import json
import os
import re
import subprocess
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[4]
PASS = ROOT / 'OptiScaler/shaders/fsrd_preprocess'
OUT = Path(os.environ.get('FSRD_GPU_TEST_OUTPUT', 'F:/FSRD/sol_batch/15b-inputs/tests/material'))
REPORT = Path(os.environ.get('FSRD_TASK_REPORT_DIR', 'E:/FSRD/sol_batch/15b-inputs'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fsrd_toolchain import compile_cpp, dxc
from build_fsrd_shader import build as build_shader

CHECKS = 0


def check(name, condition):
    global CHECKS
    CHECKS += 1
    if not condition:
        raise AssertionError(name)


def build():
    OUT.mkdir(parents=True, exist_ok=True)
    compiler = dxc()
    build_shader('FSRDNrdNativeMaterialCapture', compiler)
    compiled = OUT / 'guides.cso'
    subprocess.run([str(compiler), '-T', 'cs_6_2', '-E', 'CSMain', '-O3', '-I', str(PASS / 'precompile'),
                    str(Path(__file__).with_name('nrd_material_guides_fixture.hlsl')), '-Fo', str(compiled)], check=True)
    (OUT / 'material_guides_shader.h').write_text('const unsigned char MaterialGuidesShader[] = {' +
        ','.join(str(x) for x in compiled.read_bytes()) + '};\n')
    quantized = OUT / 'quantization.cso'
    subprocess.run([str(compiler), '-T', 'cs_6_2', '-E', 'CSMain', '-O3', '-I', str(PASS / 'precompile'),
                    str(Path(__file__).with_name('nrd_material_quantization_fixture.hlsl')), '-Fo', str(quantized)], check=True)
    (OUT / 'material_quantization_shader.h').write_text('const unsigned char MaterialQuantizationShader[] = {' +
        ','.join(str(x) for x in quantized.read_bytes()) + '};\n')
    production = (PASS / 'FSRDNrdNativeMaterialCapture_Dx12.h').read_text()
    for include in ('#include "resource_tracking/ResTrack_Dx12.h"', '#include "State.h"'):
        check('one isolated app include: ' + include, production.count(include) == 1)
        production = production.replace(include, '')
    check('two actual private barrier calls', production.count('list->ResourceBarrier(1,&barrier)') == 2)
    production = production.replace('list->ResourceBarrier(1,&barrier)', 'MaterialAuditBarriers(list,1,&barrier)')
    check('one actual capture dispatch', production.count('list->Dispatch(') == 1)
    production = production.replace('list->Dispatch(', 'MaterialAuditDispatch(list,')
    (OUT / 'production_material_capture.h').write_text(production)
    existing = Path(__file__).with_name('fsrd_nrd_conversion_fixture.cpp').read_text()
    check('existing native fixture prefix boundary', existing.count('static ULONG References(') == 1)
    prefix = existing.split('static ULONG References(')[0]
    check('one app implementation include', prefix.count('#include "production_nrd_pass.cpp"') == 1)
    support = Path(__file__).with_name('dx12_shader_test_support.h').as_posix()
    audit = r'''
#include "resource_tracking/FrameSurvey_Dx12.h"
#include <unordered_set>
static uint32_t gMaterialDispatches=0, gMaterialPrivateBarriers=0, gMaterialSourceBarriers=0;
static std::unordered_set<ID3D12Resource*> gMaterialTitleSources;
static void MaterialAuditBarriers(ID3D12GraphicsCommandList* list,UINT count,const D3D12_RESOURCE_BARRIER* barriers)
{
    for(UINT i=0;i<count;++i) {
        if(barriers[i].Type==D3D12_RESOURCE_BARRIER_TYPE_TRANSITION &&
           gMaterialTitleSources.contains(barriers[i].Transition.pResource)) {
            ++gMaterialSourceBarriers; throw std::runtime_error("production capture transitioned title source");
        }
        ++gMaterialPrivateBarriers;
    }
    list->ResourceBarrier(count,barriers);
}
static void MaterialAuditDispatch(ID3D12GraphicsCommandList* list,UINT x,UINT y,UINT z)
{ ++gMaterialDispatches; list->Dispatch(x,y,z); }
#include "production_material_capture.h"
'''
    prefix = prefix.replace('#include "production_nrd_pass.cpp"', f'#include "{support}"\n' + audit)
    original = 'ScopedInternal::ScopedInternal() noexcept : previous_(false) {}\nScopedInternal::~ScopedInternal() {}'
    check('two exact owned scope adapter definitions', original in prefix)
    prefix = prefix.replace(original, 'static thread_local bool materialInternal=false;\n'
        'ScopedInternal::ScopedInternal() noexcept : previous_(materialInternal) { materialInternal=true; }\n'
        'ScopedInternal::~ScopedInternal() { materialInternal=previous_; }')
    source = prefix + Path(__file__).with_name('fsrd_nrd_material_capture_fixture.cpp').read_text()
    (OUT / 'fixture.cpp').write_text(source)
    exe = OUT / 'material_capture.exe'
    compile_cpp(OUT / 'fixture.cpp', exe, ('d3d12.lib', 'dxgi.lib'),
                (OUT, Path(__file__).parent, PASS, ROOT / 'OptiScaler', ROOT / 'OptiScaler/include', ROOT / 'external/streamline'))
    return exe


def data():
    width, height = 127, 65
    y, x = np.mgrid[:height, :width]
    r = (x * 17 + y * 7) % 1024
    g = (x * 3 + y * 29) % 1024
    b = (x * 59 + y * 11) % 1024
    base = (r | (g << 10) | (b << 20) | ((x % 4) << 30)).astype('<u4')
    metal = (x * 13 + y * 37) % 256
    params = (metal | (np.uint32(0x7f) << 8) | (np.uint32(0x4b) << 16) | (np.uint32(0xe3) << 24)).astype('<u4')
    normal = np.zeros((height, width, 4), '<f4')
    normal[..., 2] = ((x + y) % 17) / 16
    normal[..., 3] = ((x + y * 3) % 4) / 3
    nov = ((x * 3 + y * 7) % 29 / 28).astype('<f4')
    normal[0, :6, 2] = [np.nan, np.inf, -0.1, 1.1, 0.0, 1.0]
    nov[1, :7] = [np.nan, np.inf, -1.1, 1.1, -0.5, 0.0, 1.0]
    for name, value in (('base', base), ('params', params), ('normal', normal), ('nov', nov)):
        value.tofile(OUT / (name + '.bin'))
    encoded = np.stack((r, g, b), -1).astype(np.float64) / 1023
    invalid_material = np.concatenate((encoded**2, (metal / 255)[..., None]), -1).astype('<f2')
    invalid_material[2, 0, 0] = np.nan
    invalid_material[2, 1, 1] = np.inf
    invalid_material[2, 2, 2] = -0.1
    invalid_material[2, 3, 3] = 1.1
    invalid_material[2, 4, 3] = -0.1
    invalid_material.tofile(OUT / 'invalid-material.bin')
    return encoded, metal / 255, normal, nov


def reference(material, normal, nov):
    base = material[..., :3].astype(np.float64)
    metal = material[..., 3].astype(np.float64)
    f0 = 0.04 + (base - 0.04) * metal[..., None]
    no = np.abs(nov.astype(np.float64))
    alpha = normal[..., 2].astype(np.float64) ** 2
    category = normal[..., 3]
    known = (category == np.float32(0)) | (category == np.float32(1/3)) | (category == np.float32(2/3))
    known &= np.isfinite(material).all(-1) & (material >= 0).all(-1) & (material <= 1).all(-1)
    diff = np.where(known[..., None], base * (1 - metal[..., None]), 1)
    # Written as scalar polynomials, independently of HLSL's matrix operations.
    bias_num = (0.99044 - 1.28514 * no) + (1.29678 - 0.755907 * no) * alpha
    bias_den = (1 + 2.92338 * no + 59.4188 * no**3) + (20.3225 - 27.0302 * no + 222.592 * no**3) * alpha + (121.563 + 626.13 * no + 316.627 * no**3) * alpha**3
    scale_num = (0.0365463 + 3.32707 * no) + (9.0632 - 9.04756 * no) * alpha
    scale_den = (1 + 3.59685 * no**2 - 1.36772 * no**3) + (9.04401 - 16.3174 * no**2 + 9.22949 * no**3) * alpha + (5.56589 + 19.7886 * no**2 - 20.2123 * no**3) * alpha**3
    with np.errstate(invalid='ignore', divide='ignore'):
        bias = bias_num / bias_den * np.clip(f0[..., 1] * 50, 0, 1)
        scale = scale_num / scale_den
        spec = f0 * np.maximum(scale[..., None], 0) + np.maximum(bias[..., None], 0)
    valid = known & np.isfinite(normal[..., 2]) & (normal[..., 2] >= 0) & (normal[..., 2] <= 1) & np.isfinite(nov) & (no <= 1)
    spec = np.where(valid[..., None], spec, 1)
    return diff, spec, known, valid


def quantization_data():
    # All finite nonnegative half endpoints and both float32 neighbours of every
    # adjacent-half midpoint exercise ties, exponent carries and subnormals.
    halves = np.arange(0x7c00, dtype=np.uint16).view(np.float16).astype(np.float32)
    midpoints = ((halves[:-1].astype(np.float64) + halves[1:].astype(np.float64)) * 0.5).astype(np.float32)
    values = np.concatenate((halves, midpoints, np.nextafter(midpoints, np.float32(0)),
                             np.nextafter(midpoints, np.float32(np.inf))))
    check('quantizer finite positive domain through65504', np.isfinite(values).all() and
          (values >= 0).all() and (values <= 65504).all())
    bits = values.view(np.uint32)
    normal = ((bits + np.uint32(0xfff) + ((bits >> np.uint32(13)) & np.uint32(1))) &
              np.uint32(0xffffe000)).view(np.float32)
    subnormal = np.rint(values * np.float32(16777216)) * np.float32(1 / 16777216)
    rounded = np.where(values < np.float32(2**-14), subnormal, normal)
    expected = values.astype(np.float16).astype(np.float32)
    check('dense CPU quantizer equals independent FP16 RNE', np.array_equal(rounded, expected))
    midpoint_expected = np.where((np.arange(len(midpoints)) & 1) == 0, halves[:-1], halves[1:])
    check('all midpoint ties choose even half encoding', np.array_equal(midpoints.astype(np.float16).astype(np.float32), midpoint_expected))
    check('subnormal and normal boundary controls included', np.any(values == np.float32(2**-25)) and
          np.any(values == np.float32(2**-14)) and np.any(values == np.float32(65504)))
    width = 256
    height = (len(values) + width * 4 - 1) // (width * 4)
    padded = np.zeros(width * height * 4, '<f4')
    padded[:len(values)] = values
    padded.tofile(OUT / 'quantization-input.bin')
    (OUT / 'quantization-size.txt').write_text(f'{width} {height}\n')
    return padded.reshape(height, width, 4), len(values)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    quantization_input, dense_quantization_components = quantization_data()
    exe = build()
    encoded, metal, normal, nov = data()
    run = subprocess.run([str(exe), str(OUT)], capture_output=True, text=True, errors='replace')
    (OUT / 'native.stdout.log').write_text(run.stdout)
    (OUT / 'native.stderr.log').write_text(run.stderr)
    print(run.stdout, end=''); print(run.stderr, end='', file=sys.stderr); run.check_returncode()
    check('native debug layer clean', 'debug_errors=0 debug_warnings=0' in run.stdout)
    quantization_expected = quantization_input.astype(np.float16)
    quantization_float = np.fromfile(OUT / 'quantization-float.bin', '<f4').reshape(quantization_input.shape)
    quantization_half = np.fromfile(OUT / 'quantization-half.bin', '<f2').reshape(quantization_input.shape)
    check('dense GPU manual quantizer exact FP32 half values',
          np.array_equal(quantization_float, quantization_expected.astype(np.float32)))
    check('dense GPU typed-half store preserves explicit RNE including subnormals',
          np.array_equal(quantization_half.view(np.uint16), quantization_expected.view(np.uint16)))
    actual = np.fromfile(OUT / 'material.bin', '<f2').reshape(65, 127, 4).astype(np.float64)
    exact = np.concatenate((encoded**2, metal[..., None]), -1)
    # D3D UNORM->float and one float multiply, then explicit nearest-even
    # quantization before the D3D RTZ typed-FLOAT store.
    half_ulp = np.spacing(exact.astype(np.float16)).astype(np.float64)
    error_bound = 0.5 * half_ulp + np.finfo(np.float32).eps * 4
    check('GPU capture agrees with exact integer decode within FP16 rounding', np.all(np.abs(actual - exact) <= error_bound))
    check('capture finite/bounded', np.isfinite(actual).all() and (actual >= 0).all() and (actual <= 1).all())
    diff, spec, known, valid = reference(actual, normal, nov)
    diff_gpu = np.fromfile(OUT / 'diffuse.bin', '<f4').reshape(65, 127, 4)
    spec_gpu = np.fromfile(OUT / 'specular.bin', '<f4').reshape(65, 127, 4)
    check('diffuse guide linear Qd', np.allclose(diff_gpu[..., :3], diff, rtol=2e-6, atol=2e-7))
    check('specular guide pinned SDK GGX formula', np.allclose(spec_gpu[..., :3], spec, rtol=2e-5, atol=2e-6))
    check('unknown material fallback exactly white', np.all(diff_gpu[~known, :3] == 1) and np.all(spec_gpu[~known, :3] == 1))
    check('invalid roughness/NoV fallback exactly white', np.all(spec_gpu[~valid, :3] == 1))
    check('known material guidance is not white', np.any(diff_gpu[known, :3] < 0.5) and np.any(spec_gpu[valid, :3] < 0.5))
    invalid_material = np.fromfile(OUT / 'invalid-material.bin', '<f2').reshape(65, 127, 4).astype(np.float64)
    invalid_diff, invalid_spec, invalid_known, invalid_valid = reference(invalid_material, normal, nov)
    invalid_diff_gpu = np.fromfile(OUT / 'invalid-diffuse.bin', '<f4').reshape(65, 127, 4)[..., :3]
    invalid_spec_gpu = np.fromfile(OUT / 'invalid-specular.bin', '<f4').reshape(65, 127, 4)[..., :3]
    check('malformed owned material diffuse fallback', np.allclose(invalid_diff_gpu, invalid_diff, rtol=2e-6, atol=2e-7))
    check('malformed owned material specular fallback', np.allclose(invalid_spec_gpu, invalid_spec, rtol=2e-5, atol=2e-6))
    check('all invalid owned material cells exactly white', np.all(invalid_diff_gpu[~invalid_known] == 1) and np.all(invalid_spec_gpu[~invalid_valid] == 1))
    match = re.search(r'PASS (\d+) native_material_checks', run.stdout)
    check('native check count present', match is not None)
    timings = [json.loads(line.removeprefix('MATERIAL_TIMING ')) for line in run.stdout.splitlines() if line.startswith('MATERIAL_TIMING ')]
    check('both requested GPU timing resolutions present', {(t['width'], t['height']) for t in timings} == {(1505, 847), (2560, 1440)})
    for timing in timings:
        values = np.asarray(timing['gpu_ms'][timing['warmup']:], dtype=np.float64)
        check('positive finite GPU timestamps', len(values) == 8 and np.isfinite(values).all() and (values > 0).all())
        timing['measured_median_ms'] = float(np.median(values))
        timing['measured_p95_ms'] = float(np.percentile(values, 95))
    result = dict(python_checks=CHECKS, native_checks=int(match[1]), gpu_capture_timings=timings, source_shader_sha256=hashlib.sha256((PASS/'precompile/FSRDNrdNativeMaterialCapture.hlsl').read_bytes()).hexdigest(),
        dense_quantization_components=dense_quantization_components,
        capture_max_error=float(np.max(np.abs(actual-exact))), diffuse_max_error=float(np.max(np.abs(diff_gpu[..., :3]-diff))),
        specular_max_error=float(np.max(np.abs(spec_gpu[..., :3]-spec))), known_material_pixels=int(known.sum()),
        specular_valid_pixels=int(valid.sum()), scope='Actual production capture class/HLSL and RecordedComputeLease; explicit hooks, no NativeBirth or installed-detour claim.')
    REPORT.mkdir(parents=True, exist_ok=True)
    (REPORT/'native-material-evidence.json').write_text(json.dumps(result, indent=2, allow_nan=False)+'\n')
    print('PASS', CHECKS, 'python_material_checks')


if __name__ == '__main__':
    main()
