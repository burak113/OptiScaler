"""GPU checks of the production NRD bridge conversion, capture replay and timestamps.

Run through lead_ops/run_task_test.py so one machine-wide GPU lock covers the
compiler and every fixture. Recon stays in UAV state; guides have no UAV flag.
GPU validation and descriptor/barrier instrumentation verify the required views.
"""
from pathlib import Path
import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fsrd_toolchain import compile_cpp, dxc

ROOT = Path(os.environ.get('FSRD_NRD_PRODUCTION_ROOT', Path(__file__).resolve().parents[4])).resolve()
PASS = ROOT / 'OptiScaler/shaders/fsrd_preprocess'
OUT = Path(os.environ.get('FSRD_GPU_TEST_OUTPUT', 'F:/FSRD/sol_batch/13b-inputs/tests/nrd_conversion'))
REPORT = Path(os.environ.get('FSRD_NRD_REPORT_OUTPUT', f'E:/FSRD/sol_batch/{OUT.parents[1].name}/conversion-evidence'))
CAPTURES = Path('F:/Ultra Yedek 2/overwrite/bin/x64/GAME_TRACE/FRAME_SURVEY')
CHECKS = 0
DEFERRED = False

AUDIT = r'''
#include <unordered_set>
static uint32_t gNrdDescriptorAllocations = 0, gNrdAuditedViews = 0, gNrdAuditedBarriers = 0, gNrdMaterialBarriers = 0;
static std::unordered_set<ID3D12Resource*> gNrdReconInputs, gNrdGuideInputs, gNrdTitleOutputs, gNrdOwnedMaterials;
static void AuditNrdSrv(ID3D12Resource* resource)
{
    ++gNrdAuditedViews;
    if (gNrdReconInputs.contains(resource) || gNrdTitleOutputs.contains(resource))
        throw std::runtime_error("Borrowed UAV texture read through an SRV");
}
static void AuditNrdUav(ID3D12Resource* resource)
{
    ++gNrdAuditedViews;
    if (gNrdGuideInputs.contains(resource)) throw std::runtime_error("Borrowed guide bound through a UAV");
    if (gNrdOwnedMaterials.contains(resource)) throw std::runtime_error("Owned material snapshot bound through a UAV");
}
static void AuditedNrdBarriers(ID3D12GraphicsCommandList* list, UINT count, const D3D12_RESOURCE_BARRIER* barriers)
{
    for (UINT i = 0; i < count; ++i)
    {
        ++gNrdAuditedBarriers;
        const auto& barrier = barriers[i];
        if (barrier.Type == D3D12_RESOURCE_BARRIER_TYPE_TRANSITION &&
            (gNrdReconInputs.contains(barrier.Transition.pResource) ||
             gNrdGuideInputs.contains(barrier.Transition.pResource) ||
             gNrdTitleOutputs.contains(barrier.Transition.pResource)))
            throw std::runtime_error("Bridge transitioned a borrowed title resource");
        if (barrier.Type == D3D12_RESOURCE_BARRIER_TYPE_TRANSITION && gNrdOwnedMaterials.contains(barrier.Transition.pResource))
        {
            ++gNrdMaterialBarriers;
            const auto before = barrier.Transition.StateBefore, after = barrier.Transition.StateAfter;
            if (barrier.Transition.Subresource != D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES ||
                !((before == D3D12_RESOURCE_STATE_COMMON && after == D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE) ||
                  (after == D3D12_RESOURCE_STATE_COMMON && before == D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE)))
                throw std::runtime_error("Owned material snapshot did not use exact COMMON/SRV/COMMON contract");
        }
    }
    list->ResourceBarrier(count, barriers);
}
'''


def check(name, condition):
    global CHECKS
    CHECKS += 1
    if not condition:
        raise AssertionError(name)


def build(prepare_only=False):
    OUT.mkdir(parents=True, exist_ok=True)
    source = (PASS / 'FSRDNrdBridgePass_Dx12.cpp').read_text(encoding='utf-8')
    support = Path(__file__).with_name('dx12_shader_test_support.h').as_posix()
    source = source.replace('#include "pch.h"', f'#include "{support}"\n' + AUDIT)
    source = source.replace('#include "resource_tracking/ResTrack_Dx12.h"', '')
    source = source.replace('#include "State.h"', '')
    check('one descriptor instrumentation point', source.count('slots.push_back(slot);') == 1)
    source = source.replace('slots.push_back(slot);', '++gNrdDescriptorAllocations; slots.push_back(slot);')
    check('six production barrier call sites plus audit forwarding', source.count('list->ResourceBarrier(') == 7)
    check('two native shadow barriers', source.count('list->ResourceBarrier(1, &shadowBarrier);') == 2)
    check('two owned material barriers', source.count('list->ResourceBarrier(1,&materialBarrier);') == 2)
    source = source.replace('list->ResourceBarrier(1, &barrier);', 'AuditedNrdBarriers(list, 1, &barrier);')
    source = source.replace('list->ResourceBarrier(2, barriers);', 'AuditedNrdBarriers(list, 2, barriers);')
    source = source.replace('list->ResourceBarrier(1, &shadowBarrier);', 'AuditedNrdBarriers(list, 1, &shadowBarrier);')
    source = source.replace('list->ResourceBarrier(1,&materialBarrier);', 'AuditedNrdBarriers(list, 1, &materialBarrier);')
    check('every production barrier is audited', source.count('list->ResourceBarrier(') == 1)
    check('one production SRV descriptor loop', source.count('for (auto* resource : srvs)\n        {') == 1)
    check('one production UAV descriptor loop', source.count('for (auto* resource : uavs)\n        {') == 1)
    source = source.replace('for (auto* resource : srvs)\n        {', 'for (auto* resource : srvs)\n        {\n            AuditNrdSrv(resource);')
    source = source.replace('for (auto* resource : uavs)\n        {', 'for (auto* resource : uavs)\n        {\n            AuditNrdUav(resource);')
    (OUT / 'production_nrd_pass.cpp').write_text(source, encoding='utf-8')
    shutil.copyfile(Path(__file__).with_name('fsrd_nrd_conversion_fixture.cpp'), OUT / 'fixture.cpp')
    if prepare_only:
        return None
    consumer_shader = OUT / 'consumer.cso'
    subprocess.run([str(dxc()), '-T', 'cs_6_2', '-E', 'CSMain', '-O3', '-force-rootsig-ver', 'rootsig_1_0',
                    str(Path(__file__).with_name('nrd_bridge_consumer_fixture.hlsl')), '-Fo', str(consumer_shader)], check=True)
    (OUT / 'consumer_shader.h').write_text('const unsigned char ConsumerShaderBytes[] = {' +
                                         ','.join(str(x) for x in consumer_shader.read_bytes()) + '};\n', encoding='utf-8')
    exe = OUT / 'fsrd_nrd_conversion_fixture.exe'
    compile_cpp(OUT / 'fixture.cpp', exe, ('d3d12.lib', 'dxgi.lib'),
                (OUT, Path(__file__).parent, PASS, ROOT / 'OptiScaler', ROOT / 'OptiScaler/include', ROOT / 'external/streamline'))
    return exe


def run_fixture(exe, mode, directory):
    if DEFERRED:
        mode = "deferred-" + mode
    result = subprocess.run([str(exe), mode, str(directory)], capture_output=True, text=True, errors='replace')
    (directory / 'fixture.stdout.log').write_text(result.stdout, encoding='utf-8')
    (directory / 'fixture.stderr.log').write_text(result.stderr, encoding='utf-8')
    print(result.stdout, end='')
    if result.stderr:
        print(result.stderr, file=sys.stderr, end='')
    result.check_returncode()
    check('D3D12 errors and warnings absent', 'debug_errors=0 debug_warnings=0' in result.stdout)
    return result.stdout


def projection(width, height, near=0.01, right_handed=True, reverse=True, infinite=True, far=1000):
    scale_y = 1 / math.tan(math.pi / 6)
    scale_x = scale_y / (width / height)
    sign = -1 if right_handed else 1
    if infinite:
        a, b = (0, near) if reverse else (sign, -near)
    else:
        n, f = (far, near) if reverse else (near, far)
        a, b = sign * f / (f - n), -n * f / (f - n)
    return np.array([[scale_x, 0, 0, 0], [0, scale_y, 0, 0],
                     [0, 0, a, b], [0, 0, sign, 0]], dtype=np.float32)


def frame(width, height, index=0, captured=False):
    right = captured or index not in (2, 3, 4)
    near = 0.02 if captured else (0.25 if right else 0.5)
    proj = projection(width, height, near, right, reverse=right, infinite=right, far=100)
    view = np.eye(4, dtype=np.float32)
    if not captured:
        angle = 0.37 + index * 0.09
        cosine, sine = math.cos(angle), math.sin(angle)
        view[:3, :3] = [[cosine, 0, sine], [0, 1, 0], [-sine, 0, cosine]]
        view[:3, 3] = [17, -29, 101]  # Translation must not affect a world normal.
        proj[0, 2] = 0.13
        proj[1, 2] = -0.11
    return dict(near=near, far=65504 if captured else (40 if right else 32), sign=-1 if right else 1,
                scale=(1 / width, 1 / height) if not captured else (1, 1),
                jitter=(0, 0) if captured else (-0.25, 0.5),
                previous_jitter=(0, 0) if captured else (0.5, -0.25),
                jittered=index in (3, 6), reset=captured or index in (0, 2, 5),
                previous_valid=not captured and index > 0,
                mode=2 if index == 6 and not captured else 1, view=view, projection=proj)


def packed_nr(values):
    quantized = np.rint(np.clip(values, 0, 1) * np.array([1023, 1023, 1023, 3])).astype(np.uint32)
    return quantized[..., 0] | (quantized[..., 1] << 10) | (quantized[..., 2] << 20) | (quantized[..., 3] << 30)


def write_case(directory, inputs, params):
    directory.mkdir(parents=True, exist_ok=True)
    if 'material' not in inputs:
        (directory / 'material.bin').unlink(missing_ok=True)
    for name, value in inputs.items():
        value.tofile(directory / f'{name}.bin')
    values = [params['near'], params['far'], params['sign'], *params['scale'], *params['jitter'],
              *params['previous_jitter'], int(params['jittered']), int(params['reset']),
              int(params['previous_valid']), params['mode'], *params['view'].ravel(), *params['projection'].ravel(),
              int(params.get('camera_projected_depth_delta', False)), int(params.get('preserve_native_material_ids', False)),
              int(params.get('native_material_guides', False))]
    (directory / 'frame.txt').write_text(' '.join(str(value) for value in values), encoding='utf-8')


def inputs(width, height, index=0, extremes=False):
    y, x = np.mgrid[:height, :width]
    spec = np.empty((height, width, 4), np.float16)
    spec[..., 0] = (x + index * 2) * 0.13
    spec[..., 1] = y * 0.17
    spec[..., 2] = (x + y + index) * 0.11
    spec[..., 3] = 7 + (x + y * width + index) % 2000
    diff = spec.copy()
    diff[..., :3] *= 0.73
    diff[..., 3] += 100
    depth = (2 + x * 0.31 + y * 0.52 + index * 1.3).astype(np.float32)
    normal = np.empty((height, width, 4), np.float32)
    normal[..., 0] = 0.15 + (x % 5) * 0.14
    normal[..., 1] = 0.18 + (y % 4) * 0.17
    normal[..., 2] = (x % 7) / 6
    normal[..., 3] = (x % 4) / 3
    motion = np.zeros((height, width, 4), np.float16)
    motion[..., 0] = np.where(x % 2 == 0, 0.31, -1.23)
    motion[..., 1] = np.where(y % 2 == 0, -0.67, 1.39)
    motion[..., 2] = 123  # Raw title Z must never replace the signed-depth delta.
    if extremes:
        spec[0, :4, :3] = [[-1, np.nan, np.inf], [-np.inf, 2, -3], [65504, -0.1, 0], [0, 0, 0]]
        diff[0, :4, :3] = spec[0, :4, :3]
        spec[0, :8, 3] = [np.nan, np.inf, -np.inf, -1, -123, 0, -0.0, 65504]
        diff[0, :8, 3] = [-np.inf, np.nan, np.inf, -7, -65504, -0.0, 0, 123]
        depth[0, :6] = [-3, 0.001, 100000, np.nan, np.inf, -np.inf]
        motion[0, :4, :2] = [[np.nan, np.inf], [65504, -65504], [-4, 0.33], [0.17, 3.11]]
    return dict(spec=spec, diff=diff, nr=packed_nr(normal), depth=depth, motion=motion)


def normal_decode(nr):
    xy = np.stack((nr & 1023, (nr >> 10) & 1023), axis=-1).astype(np.float32) / 1023
    xy = 2 * xy - 1
    normal = np.concatenate((xy, (1 - np.abs(xy).sum(-1))[..., None]), axis=-1)
    t = np.maximum(-normal[..., 2], 0)
    normal[..., :2] += np.where(normal[..., :2] >= 0, -t[..., None], t[..., None])
    return normal / np.linalg.norm(normal, axis=-1, keepdims=True)


def reference(inputs, params, previous_depth, history_valid):
    height, width = inputs['depth'].shape
    raw_depth = inputs['depth']
    depth = params['sign'] * np.where(np.isfinite(raw_depth),
        np.clip(np.abs(raw_depth), params['near'], params['far']), params['far'])
    raw = inputs['motion'][..., :2].astype(np.float32)
    motion = np.where(np.isfinite(raw), raw, 0) * np.asarray(params['scale'], np.float32)
    if not params['jittered']:
        motion += (np.asarray(params['previous_jitter'], np.float32) - np.asarray(params['jitter'], np.float32)) / (width, height)
    y, x = np.mgrid[:height, :width]
    positions = np.stack((x + 0.5, y + 0.5), axis=-1).astype(np.float32) + motion * (width, height)
    valid = history_valid and params['previous_valid'] and not params['reset']
    inside = (positions[..., 0] >= 0) & (positions[..., 0] < width) & (positions[..., 1] >= 0) & (positions[..., 1] < height)
    delta = np.zeros_like(depth)
    if valid:
        coords = np.floor(positions[inside]).astype(int)
        delta[inside] = np.clip(previous_depth[coords[:, 1], coords[:, 0]] - depth[inside], -65504, 65504)
    output_motion = np.concatenate((np.clip(motion, -65504, 65504), delta[..., None], np.ones_like(delta)[..., None]), axis=-1).astype(np.float16)
    world_normal = normal_decode(inputs['nr'])
    view_normal = world_normal @ params['view'][:3, :3].T
    view_normal /= np.linalg.norm(view_normal, axis=-1, keepdims=True)
    clip = np.stack((2 * (x + 0.5) / width - 1, 1 - 2 * (y + 0.5) / height,
                     np.full_like(x, 0.5, dtype=np.float32), np.ones_like(x)), axis=-1).astype(np.float32)
    view_pos = clip @ np.linalg.inv(params['projection']).T
    view_ray = view_pos[..., :3] / view_pos[..., 3:]
    view_ray /= np.linalg.norm(view_ray, axis=-1, keepdims=True)
    no_v = np.clip((-view_ray * view_normal).sum(-1), 0, 1)
    return depth.astype(np.float32), output_motion, no_v


def read_outputs(directory, width, height):
    result = {}
    for name in ('spec', 'diff', 'motion', 'debug_spec', 'debug_diff'):
        file_name = name if name.startswith('debug_') else 'out_' + name
        result[name] = np.fromfile(directory / f'{file_name}.bin', '<f2').reshape(height, width, 4)
    result['depth'] = np.fromfile(directory / 'out_depth.bin', '<f4').reshape(height, width)
    result['nr'] = np.fromfile(directory / 'out_nr.bin', '<u4').reshape(height, width)
    for name in ('spec_albedo', 'diff_albedo'):
        result[name] = np.fromfile(directory / f'out_{name}.bin', 'u1').reshape(height, width, 4)
    return result


def material_brdf_polynomials(no_v, alpha):
    """Independent scalar expansion of AMD denoising.md 5.5.2, evaluated in FP64."""
    n, a = no_v, alpha
    return (
        .99044 - 1.28514*n + 1.29678*a - .755907*a*n,
        1 + 2.92338*n + 59.4188*n**3 + 20.3225*a - 27.0302*a*n + 222.592*a*n**3
          + 121.563*a**3 + 626.13*a**3*n + 316.627*a**3*n**3,
        .0365463 + 3.32707*n + 9.0632*a - 9.04756*a*n,
        1 + 3.59685*n**2 - 1.36772*n**3 + 9.04401*a - 16.3174*a*n**2 + 9.22949*a*n**3
          + 5.56589*a**3 + 19.7886*a**3*n**2 - 20.2123*a**3*n**3)


def material_guide_bounds(input_values, output, square_roughness=True):
    """Per-pixel forward intervals, never an empirical image-error tolerance.

    NoV was stored from the very same scalar used by GGX. FLOAT->UNORM permits
    0.6 integer ULP (D3D functional spec 3.2.3.6), so this bounds that hidden FP32
    scalar without assuming an exact rsqrt/matrix implementation. Existing angle
    and ON/OFF-alpha checks independently validate the geometry. Each polynomial
    gets gamma64 * sum(abs(terms)), covering all serial FP32/FMA reorderings,
    rounded coefficients/powers; rcp gets its specified 2^-21 relative bound.
    The final output gets exactly another 0.6/255 storage bound, no FP16 rounding.
    https://microsoft.github.io/DirectX-Specs/d3d/archive/D3D11_3_FunctionalSpec.htm
    """
    base_metal = input_values['material'].astype(np.float64)
    known = (input_values['nr'] >> np.uint32(30)) != 3
    known &= np.isfinite(base_metal).all(-1) & (base_metal >= 0).all(-1) & (base_metal <= 1).all(-1)
    clean = np.where(known[..., None], base_metal, 0)
    base, metal = clean[..., :3], clean[..., 3:]
    f0 = .04 * (1-metal) + base * metal
    diffuse = base * (1-metal)
    no_v = output['spec_albedo'][..., 3].astype(np.float64) / 255
    rough = ((input_values['nr'] >> 20) & 1023).astype(np.float64) / 1023
    alpha = rough**2 if square_roughness else rough
    nb, db, ns, ds = material_brdf_polynomials(no_v, alpha)
    bias = np.maximum(nb/db, 0) * np.clip(f0[..., 1] * 50, 0, 1)
    specular = f0 * np.maximum(ns/ds, 0)[..., None] + bias[..., None]
    diffuse = np.where(known[..., None], diffuse, 1)
    specular = np.where(known[..., None], specular, 1)

    eps = 2.0**-23  # one relative FP32 ULP, also covers worst unfused MAD steps
    gamma64 = (64*eps) / (1-64*eps)
    unorm = .6/255
    n = (np.maximum(0, no_v-unorm), np.minimum(1, no_v+unorm))
    r = (np.maximum(0, rough-eps), np.minimum(1, rough+eps))
    a = (r[0]**2, r[1]**2) if square_roughness else r
    a = (np.maximum(0, a[0]-eps), np.minimum(1, a[1]+eps))
    terms = (
        ((.99044,0,0),(-1.28514,1,0),(1.29678,0,1),(-.755907,1,1)),
        ((1,0,0),(2.92338,1,0),(59.4188,3,0),(20.3225,0,1),(-27.0302,1,1),
         (222.592,3,1),(121.563,0,3),(626.13,1,3),(316.627,3,3)),
        ((.0365463,0,0),(3.32707,1,0),(9.0632,0,1),(-9.04756,1,1)),
        ((1,0,0),(3.59685,2,0),(-1.36772,3,0),(9.04401,0,1),(-16.3174,2,1),
         (9.22949,3,1),(5.56589,0,3),(19.7886,2,3),(-20.2123,3,3)))

    def polynomial(coefficients):
        lo, hi, mass = np.zeros_like(no_v), np.zeros_like(no_v), np.zeros_like(no_v)
        for coefficient, npower, apower in coefficients:
            c = float(np.float32(coefficient))
            low, high = n[0]**npower * a[0]**apower, n[1]**npower * a[1]**apower
            left, right = (c*low, c*high) if c >= 0 else (c*high, c*low)
            lo += left; hi += right; mass += np.maximum(abs(left), abs(right))
        return lo-gamma64*mass, hi+gamma64*mass

    def multiply(left, right):
        values = np.stack([l*r for l in left for r in right])
        return values.min(0), values.max(0)

    def ratio(numerator, denominator):
        check('material rational denominator interval remains strictly positive', np.all(denominator[0] > 0))
        reciprocal = ((1-2.0**-21)/denominator[1], (1+2.0**-21)/denominator[0])
        return multiply(numerator, reciprocal)

    b = ratio(polynomial(terms[0]), polynomial(terms[1]))
    s = ratio(polynomial(terms[2]), polynomial(terms[3]))
    f0_error = (4*eps)/(1-4*eps) * (.04 + base*metal)
    f = (np.maximum(0, f0-f0_error), np.minimum(1, f0+f0_error))
    bias_gate = (np.clip(f[0][..., 1]*50, 0, 1), np.clip(f[1][..., 1]*50, 0, 1))
    b = multiply((np.maximum(b[0], 0), np.maximum(b[1], 0)), bias_gate)
    spec = multiply(f, (np.maximum(s[0], 0)[..., None], np.maximum(s[1], 0)[..., None]))
    lo, hi = spec[0]+b[0][..., None], spec[1]+b[1][..., None]
    final_error = (8*eps)/(1-8*eps) * np.maximum(abs(lo), abs(hi))
    spec_bounds = (np.clip(lo-final_error, 0, 1)-unorm, np.clip(hi+final_error, 0, 1)+unorm)
    diff_error = (3*eps)/(1-3*eps) * np.abs(base*(1-metal))
    diff_bounds = (np.clip(diffuse-diff_error, 0, 1)-unorm, np.clip(diffuse+diff_error, 0, 1)+unorm)
    return dict(known=known, specular=np.clip(specular,0,1), diffuse=diffuse,
                spec_bounds=spec_bounds, diff_bounds=diff_bounds, f0=f0)


def verify_native_material_guides(directory, input_values, output):
    oracle = material_guide_bounds(input_values, output)
    for name, bound_name in (('spec_albedo','spec_bounds'), ('diff_albedo','diff_bounds')):
        actual = output[name][..., :3].astype(np.float64)/255
        lo, hi = oracle[bound_name]
        known = oracle['known']
        check(f'{directory.name} {name} independent SDK rational/linear guide within derived FP32+UNORM8 interval',
              np.all((actual[known] >= lo[known]) & (actual[known] <= hi[known])))
        check(f'{directory.name} {name} model1/malformed owned material exact-white fallback',
              np.all(output[name][~known, :3] == 255))
    check(f'{directory.name} material diffuse alpha remains zero', np.all(output['diff_albedo'][..., 3] == 0))
    return oracle


def verify_case(directory, input_values, params, previous_depth=None, history_valid=False, expected_camera_delta=None):
    height, width = input_values['depth'].shape
    output = read_outputs(directory, width, height)
    depth, motion, no_v = reference(input_values, params, previous_depth, history_valid)
    if expected_camera_delta is not None:
        # Independent pose/plane oracle supplied by projected_depth_cases, not shader reconstruction.
        motion[..., 2] = np.asarray(expected_camera_delta, dtype=np.float16)
    for name in ('spec', 'diff'):
        expected = input_values[name].copy()
        expected[..., :3] = np.where(np.isfinite(expected[..., :3]), np.maximum(expected[..., :3], 0), 0)
        expected[..., 3] = np.where(np.isfinite(expected[..., 3]), expected[..., 3], np.float16(0))
        check(f'{directory.name} {name} RGB sanitizer/native finite-alpha policy', np.array_equal(output[name], expected))
        finite_alpha = np.isfinite(input_values[name][..., 3])
        check(f'{directory.name} {name} every finite alpha bit preserved including inactive/signedzero',
              np.array_equal(output[name][..., 3].view(np.uint16)[finite_alpha], input_values[name][..., 3].view(np.uint16)[finite_alpha]))
        check(f'{directory.name} {name} nonfinite alpha becomes exact positivezero',
              np.all(output[name][..., 3].view(np.uint16)[~finite_alpha] == 0))
        check(f'{directory.name} {name} finite', np.isfinite(output[name]).all())
        check(f'{directory.name} {name} debug alpha zero', np.all(output['debug_' + name][..., 3] == 0))
        if params['mode'] == 1:
            check(f'{directory.name} {name} raw RGB exact', np.array_equal(output['debug_' + name][..., :3], expected[..., :3]))
        else:
            check(f'{directory.name} {name} diagnostics finite bounded',
                  np.isfinite(output['debug_' + name]).all() and np.max(output['debug_' + name]) <= 1 and np.min(output['debug_' + name]) >= 0)
        encoded = np.fromfile(directory / f'debug_ycocg_{name}.bin', '<f2').reshape(height, width, 4).astype(np.float32)
        check(f'{directory.name} {name} encoded debug finite and alpha zero', np.isfinite(encoded).all() and np.all(encoded[..., 3] == 0))
        decoded = np.stack((encoded[..., 0] - encoded[..., 2] + encoded[..., 1],
                            encoded[..., 0] + encoded[..., 2],
                            encoded[..., 0] - encoded[..., 2] - encoded[..., 1]), -1)
        decoded = np.maximum(decoded, 0)
        original = output['debug_' + name][..., :3].astype(np.float32)
        # Three encoded half rounding errors plus the reference RGB half rounding.
        # eps=2^-11 (half ULP relative bound), subnormal halfstep=2^-25.
        encoded_error = (np.abs(encoded[..., :3]).sum(-1) + np.max(np.abs(original), -1)) * (2.0**-11) + 4 * (2.0**-25)
        check(f'{directory.name} {name} exact Consumer inverse roundtrip within derived FP16 quantization bound',
              np.all(np.abs(decoded-original) <= encoded_error[..., None] * 1.01))
        cancelled = np.fromfile(directory / f'debug_cancel_{name}.bin', '<f2').reshape(height, width, 4)
        check(f'{directory.name} {name} cancelled encoded debug leaves originalRGBA exact',
              np.array_equal(cancelled.view(np.uint16), output['debug_' + name].view(np.uint16)))
    check(f'{directory.name} signed depth sign clamp and nonfinite sky', np.allclose(output['depth'], depth, rtol=1e-7, atol=1e-6))
    if params.get('preserve_native_material_ids', False):
        check(f'{directory.name} packed native RGB/A preserved exact', np.array_equal(output['nr'], input_values['nr']))
    else:
        check(f'{directory.name} packed normals RGB preserved alpha zero', np.array_equal(output['nr'], input_values['nr'] & 0x3fffffff))
    check(f'{directory.name} motion scale jitter depth delta and W', np.allclose(output['motion'], motion, rtol=1e-3, atol=2e-4))
    check(f'{directory.name} motion finite', np.isfinite(output['motion']).all())
    if params.get('native_material_guides', False) and 'material' in input_values:
        verify_native_material_guides(directory, input_values, output)
    else:
        check(f'{directory.name} white specular albedo', np.all(output['spec_albedo'][..., :3] == 255))
        check(f'{directory.name} white diffuse albedo zero metalness', np.all(output['diff_albedo'][..., :3] == 255) and np.all(output['diff_albedo'][..., 3] == 0))
    check(f'{directory.name} exact world-normal NoV within storage quantization',
          np.max(np.abs(output['spec_albedo'][..., 3] / 255 - no_v)) <= 1.0 / 255 + 1e-5)
    if params['mode'] == 2:
        roughness_band = ((np.arange(width) * 3) // width) == 1
        expected_roughness = ((input_values['nr'] >> 20) & 1023) / 1023
        check('diagnostic roughness band uses actual guide',
              np.allclose(output['debug_spec'][:, roughness_band, 0], expected_roughness[:, roughness_band], atol=5e-4))
    return output['depth']


def verify_table_consumer(directory, width, height):
    flags = [0, 1, 0x80000000, 0x7fc00000, 0, 1, 0, 1]
    for name in ('spec', 'diff'):
        source = np.fromfile(directory / f'table_source_{name}.bin', '<f2').reshape(height, width, 4)
        for index, flag in enumerate(flags):
            title = np.fromfile(directory / f'table{index}' / f'{name}.bin', '<f2').reshape(height, width, 4)
            consumer = np.fromfile(directory / f'table{index}' / f'consumer_{name}.bin', '<f4').reshape(height, width, 4)
            check('volatile-table title and actual Consumer RGB finite', np.isfinite(title).all() and np.isfinite(consumer).all())
            check('debug title alpha0 and actual Consumer alpha1', np.all(title[..., 3].view('<u2') == 0) and np.all(consumer[..., 3] == 1))
            original = source[..., :3].astype(np.float32) * 64
            if flag == 0:
                check('overwritten native zero flag commits exact RGB', np.array_equal(title[..., :3].view('<u2'), source[..., :3].view('<u2')))
                check('actual GPU Consumer RGB zero branch exact', np.array_equal(consumer[..., :3], original))
            else:
                encoded = title[..., :3].astype(np.float32)
                rgb = source[..., :3].astype(np.float32)
                nearest = np.stack(((rgb[..., 0] + np.float32(2) * rgb[..., 1] + rgb[..., 2]) * np.float32(.25),
                                    (rgb[..., 0] - rgb[..., 2]) * np.float32(.5),
                                    (-rgb[..., 0] + np.float32(2) * rgb[..., 1] - rgb[..., 2]) * np.float32(.25)), -1).astype('<f2')
                check('encoded native title is exact nearest-half identity', np.array_equal(title[..., :3].view('<u2'), nearest.view('<u2')))
                bound = (np.abs(encoded).sum(-1) * 2**-11 + 3 * 2**-25) * 64
                check('actual GPU Consumer YCoCg inverse within half rounding',
                      np.all(np.abs(consumer[..., :3] - original) <= bound[..., None] * 1.01))


def projected_depth_cases(width=13, height=11, focal_scales=None):
    """Known world planes and physical camera poses, independent of inverse-projection helper."""
    poses = [
        (0.0, (0.0, 0.0, 0.0), (0.0, 0.0)),
        (0.0, (0.0, 0.0, 0.2), (-0.25, 0.5)),
        (0.17, (0.15, 0.0, 0.2), (0.25, -0.25)),
        (0.23, (0.15, 0.0, 0.2), (0.375, -0.125)),
        (0.23, (0.15, 0.0, 0.2), (-0.375, 0.125)),
        (0.35, (0.25, 0.1, 0.3), (0.5, -0.5)),
        (0.0, (0.0, 0.0, 0.0), (0.0, 0.0)),
        (0.0, (0.0, 0.0, 0.2), (-0.25, 0.5)),
    ]
    if focal_scales is not None:
        if len(focal_scales) != len(poses) or any(not math.isfinite(v) or v <= 0 for v in focal_scales):
            raise ValueError('Eight finite positive per-pose focal scales are required')
    descriptions = ['initial', 'translation', 'rotation', 'rotation+jitter+occluder',
                    'occluder reveal', 'invalid previous', 'LH reset', 'LH object-Z limitation']
    y, x = np.mgrid[:height, :width]
    cases = []
    rotations = []
    for index, (yaw, camera, jitter) in enumerate(poses):
        cosine, sine = math.cos(yaw), math.sin(yaw)
        rotation = np.array([[cosine, 0, sine], [0, 1, 0], [-sine, 0, cosine]], dtype=np.float64)
        rotations.append(rotation)
        right = index < 6
        sign = -1 if right else 1
        proj = projection(width, height, 0.05, right, reverse=right, infinite=right, far=64)
        if focal_scales is not None:
            proj[0, 0] *= focal_scales[index]
            proj[1, 1] *= focal_scales[index]
        proj[0, 2], proj[1, 2] = 0.13, -0.11
        view = np.eye(4, dtype=np.float32)
        view[:3, :3] = rotation
        view[:3, 3] = -rotation @ np.asarray(camera, dtype=np.float64)
        previous_jitter = poses[index-1][2] if index else jitter
        params = dict(near=0.05, far=64, sign=sign, scale=(1, 1), jitter=jitter,
                      previous_jitter=previous_jitter, jittered=index == 2,
                      reset=index in (0, 6), previous_valid=index not in (0, 5, 6),
                      mode=1, view=view, projection=proj)
        uv = np.stack(((x + 0.5-jitter[0])/width, (y + 0.5-jitter[1])/height), axis=-1)
        ndc = uv * (2, -2) + (-1, 1)
        # Perspective camera ray from physical focal lengths and pinhole offsets.
        camera_ray = np.dstack(((ndc[..., 0]-float(proj[0, 2])*sign)/float(proj[0, 0]),
                               (ndc[..., 1]-float(proj[1, 2])*sign)/float(proj[1, 1]),
                               np.full((height, width), sign, np.float64)))
        world_ray = camera_ray @ rotation
        plane_z = -6.0 if right else (3.0 if index == 7 else 6.0)
        distance = (plane_z-camera[2])/world_ray[..., 2]
        reveal_mask = (x >= width//3) & (x < 2*width//3) & (y >= height//3) & (y < 2*height//3)
        if index == 3:
            # Previous visibility contains a nearer occluder; the next frame exposes the fixed -6 world plane.
            distance[reveal_mask] = (-2.0-camera[2])/world_ray[..., 2][reveal_mask]
        value = inputs(width, height, index, extremes=False)
        value['depth'] = distance.astype('<f4')
        world = np.asarray(camera)+world_ray*value['depth'][..., None].astype(np.float64)
        current_z = sign*value['depth'].astype(np.float64)
        delta = np.zeros((height, width), np.float64)
        raw_motion = np.zeros((height, width, 4), '<f2')
        true_object_delta = None
        if index and index != 6:
            previous_camera = np.asarray(poses[index-1][1])
            previous_view = (world-previous_camera) @ rotations[index-1].T
            delta = previous_view[..., 2]-current_z
            previous_object = world.copy()
            if index == 7:
                previous_object[..., 2] += 3.0
                true_object_delta = ((previous_object-previous_camera) @ rotations[index-1].T)[..., 2]-current_z
                # Native Z exists, but its game CB scale/mode has not been attested and must not be guessed.
                raw_motion[..., 2] = true_object_delta.astype(np.float16)
            projected_previous = (previous_object-previous_camera) @ rotations[index-1].T
            previous_projection = cases[-1]['params']['projection'].astype(np.float64)
            clip = np.dstack((projected_previous, np.ones((height, width)))) @ previous_projection.T
            previous_uv = clip[..., :2]/clip[..., 3:] * (0.5, -0.5)+(0.5, 0.5)
            canonical = previous_uv-uv
            if params['jittered']:
                canonical += (np.asarray(previous_jitter)-np.asarray(jitter))/(width, height)
            raw_motion[..., :2] = canonical.astype(np.float16)
        if not params['previous_valid'] or params['reset']:
            delta.fill(0)
        value['motion'] = raw_motion
        cases.append(dict(inputs=value, params=params, expected_delta=delta,
                          description=descriptions[index], reveal_mask=reveal_mask,
                          world_points=world, true_object_delta=true_object_delta))
    return cases


def projected_depth(exe):
    cases = projected_depth_cases()
    height, width = cases[0]['inputs']['depth'].shape
    mode_outputs, evidence = {}, {}
    for enabled in (False, True):
        mode = 'on' if enabled else 'off'
        directory = OUT/'projected_depth'/mode
        directory.mkdir(parents=True, exist_ok=True)
        (directory/'meta.txt').write_text(f'{len(cases)} {width} {height}', encoding='utf-8')
        for index, case in enumerate(cases):
            params = dict(case['params'], camera_projected_depth_delta=enabled)
            write_case(directory/f'frame{index}', case['inputs'], params)
        stdout = run_fixture(exe, 'geometry', directory)
        previous, outputs = None, []
        for index, case in enumerate(cases):
            params = dict(case['params'], camera_projected_depth_delta=enabled)
            previous = verify_case(directory/f'frame{index}', case['inputs'], params,
                                   previous, index > 0, case['expected_delta'] if enabled else None)
            outputs.append(read_outputs(directory/f'frame{index}', width, height))
        verify_table_consumer(directory, width, height)
        mode_outputs[mode] = outputs
        evidence[mode] = dict(fixture_checks=int(re.search(r'fixture_checks=(\d+)', stdout)[1]),
                              table_fixture_checks=int(re.search(r'table_fixture_checks=(\d+)', stdout)[1]))
    off, on = mode_outputs['off'], mode_outputs['on']
    for index in range(len(cases)):
        for name in ('spec', 'diff', 'depth', 'nr', 'spec_albedo', 'diff_albedo', 'debug_spec', 'debug_diff'):
            check(f'projected frame{index} {name} byte identity across A/B',
                  on[index][name].tobytes() == off[index][name].tobytes())
        check(f'projected frame{index} XY/W exact across A/B',
              np.array_equal(on[index]['motion'][..., [0, 1, 3]].view('<u2'), off[index]['motion'][..., [0, 1, 3]].view('<u2')))
    for index in (0, 5, 6):
        check(f'projected frame{index} invalid previous/reset exact positivezero B',
              np.all(on[index]['motion'][..., 2].view('<u2') == 0))
    for index in (1, 7):
        check(f'projected frame{index} RH/LH +0.2 translation signed B',
              np.allclose(on[index]['motion'][..., 2].astype(np.float32), 0.2, atol=2e-4, rtol=0))
    check('projected rotation Z varies across a known fixed world plane', np.ptp(on[2]['motion'][..., 2]) > 0.1)
    mask = cases[4]['reveal_mask']
    cur = on[4]['depth']
    check('revealed fixed surface predicts its own previous Z, not the old occluder',
          np.max(np.abs((cur+on[4]['motion'][..., 2])[mask]-cur[mask])) < 2e-4)
    check('legacy old-visibility delta is observably wrong on the revealed surface',
          np.count_nonzero(np.abs(off[4]['motion'][..., 2][mask]-on[4]['motion'][..., 2][mask]) > 1) >= 4)
    limitation = np.max(np.abs(cases[7]['true_object_delta']-on[7]['motion'][..., 2].astype(np.float64)))
    check('camera-only mode explicitly cannot reconstruct object-Z displacement', limitation > 2.9)
    return dict(frames=len(cases), width=width, height=height, fixtures=evidence,
                oracle='physical pinhole camera rays intersect known world planes; previous pose projects known surface points',
                only_motion_B_changes=True, native_table_cases=8,
                object_depth_limitation_max= float(limitation), camera_only_object_Z_supported=False,
                note='Guide correctness A/B evidence; no claim of actual RR visual quality until E2E/user validation.')


def material_ids(exe):
    width, height, count = 13, 11, 8
    y, x = np.mgrid[:height, :width]
    cases = []
    for index in range(count):
        value = inputs(width, height, index, extremes=True)
        categories = ((x+y+index) % 4).astype('<u4')
        value['nr'] = (value['nr'] & np.uint32(0x3fffffff)) | (categories << np.uint32(30))
        cases.append((value, frame(width, height, index)))
    mode_outputs, evidence = {}, {}
    for enabled in (False, True):
        mode = 'on' if enabled else 'off'
        directory = OUT/'material_ids'/mode
        directory.mkdir(parents=True, exist_ok=True)
        (directory/'meta.txt').write_text(f'{count} {width} {height}', encoding='utf-8')
        for index, (value, params) in enumerate(cases):
            write_case(directory/f'frame{index}', value, dict(params, preserve_native_material_ids=enabled))
        stdout = run_fixture(exe, 'sequence', directory)
        previous, outputs = None, []
        for index, (value, params) in enumerate(cases):
            previous = verify_case(directory/f'frame{index}', value,
                                   dict(params, preserve_native_material_ids=enabled), previous,
                                   index > 0 and index != 4)
            outputs.append(read_outputs(directory/f'frame{index}', width, height))
        verify_table_consumer(directory, width, height)
        mode_outputs[mode] = outputs
        evidence[mode] = dict(fixture_checks=int(re.search(r'fixture_checks=(\d+)', stdout)[1]),
                              table_fixture_checks=int(re.search(r'table_fixture_checks=(\d+)', stdout)[1]))
    for index, (off, on) in enumerate(zip(mode_outputs['off'], mode_outputs['on'])):
        for name in ('spec', 'diff', 'depth', 'motion', 'spec_albedo', 'diff_albedo', 'debug_spec', 'debug_diff'):
            check(f'material frame{index} {name} byte identity across A/B',
                  on[name].tobytes() == off[name].tobytes())
        check(f'material frame{index} RG/B packed bits exact across A/B',
              np.array_equal(on['nr'] & np.uint32(0x3fffffff), off['nr']))
        check(f'material frame{index} all four native categories preserved',
              np.array_equal(np.unique(on['nr'] >> np.uint32(30)), np.arange(4, dtype='<u4')))
        check(f'material frame{index} OFF remains category0 exact', np.all(off['nr'] >> np.uint32(30) == 0))
    return dict(frames=count, width=width, height=height, fixtures=evidence, native_table_cases=8,
                only_normal_A_changes=True, native_categories=[0, 1, 2, 3],
                note='Exact guide A/B evidence; actual title ID distribution/flags and visual quality unmeasured.')


def native_material(exe):
    width, height, count = 13, 11, 8
    y, x = np.mgrid[:height, :width]
    cases = []
    for index in range(count):
        value = inputs(width, height, index, extremes=True)
        category = ((x+y+index) % 4).astype('<u4')
        value['nr'] = (value['nr'] & np.uint32(0x3fffffff)) | (category << np.uint32(30))
        material = np.empty((height,width,4), '<f2')
        material[..., 0] = (x % 7)/6
        material[..., 1] = ((y+index) % 5)/4
        material[..., 2] = ((x+y) % 9)/8
        material[..., 3] = np.asarray([0,.25,.5,1], '<f2')[(x+2*y+index) % 4]
        if index in (1,6):
            material[0,:8] = [[np.nan,.2,.3,0],[.1,np.inf,.3,.5],[.1,.2,-np.inf,1],
                              [-.1,.2,.3,0],[1.1,.2,.3,.5],[.1,.2,.3,-.1],
                              [.1,.2,.3,1.1],[0,0,0,0]]
        if index != 3:  # A missing authoritative source must keep white guides even with the option ON.
            value['material'] = material
        params = dict(frame(width,height,index), mode=1, preserve_native_material_ids=True)
        cases.append((value,params))

    mode_outputs, evidence = {}, {}
    for enabled in (False,True):
        mode = 'on' if enabled else 'off'
        directory = OUT/'native_material'/mode
        directory.mkdir(parents=True,exist_ok=True)
        (directory/'meta.txt').write_text(f'{count} {width} {height}',encoding='utf-8')
        for index,(value,params) in enumerate(cases):
            write_case(directory/f'frame{index}',value,dict(params,native_material_guides=enabled))
        if exe is None:
            continue
        stdout = run_fixture(exe,'sequence',directory)
        previous, outputs = None, []
        for index,(value,params) in enumerate(cases):
            previous = verify_case(directory/f'frame{index}',value,dict(params,native_material_guides=enabled),
                                   previous,index > 0 and index != 4)
            outputs.append(read_outputs(directory/f'frame{index}',width,height))
            if enabled:
                for name in ('spec','diff','material'):
                    if name in value:
                        check(f'native material frame{index} source {name} every byte unchanged',
                              (directory/f'frame{index}'/f'source_{name}.bin').read_bytes() == value[name].tobytes())
        verify_table_consumer(directory,width,height)
        mode_outputs[mode] = outputs
        evidence[mode] = dict(fixture_checks=int(re.search(r'fixture_checks=(\d+)',stdout)[1]),
                              table_fixture_checks=int(re.search(r'table_fixture_checks=(\d+)',stdout)[1]))
    if exe is None:
        for value,params in cases:
            if 'material' in value:
                _,_,no_v = reference(value,params,None,False)
                mock = {'spec_albedo':np.zeros((height,width,4),'u1')}
                mock['spec_albedo'][...,3] = np.rint(no_v*255).astype('u1')
                oracle = material_guide_bounds(value,mock)
                for name,bounds in (('specular','spec_bounds'),('diffuse','diff_bounds')):
                    lo,hi = oracle[bounds]; known = oracle['known']; expected = oracle[name]
                    check('independent FP64 point lies inside analytically propagated material interval',
                          np.all((expected[known] >= lo[known]) & (expected[known] <= hi[known])))
        return dict(prepared=True,frames=count,modes=['off','on'],native_table_cases=8,
                    cpu_oracle='FP64 SDK rational expansion; per-pixel FP32/rcp and 0.6-ULP UNORM8 intervals')

    rejected_f0 = rejected_roughness = rejected_gamma = known_pixels = fallback_pixels = 0
    maximum_spec_interval = maximum_diff_interval = 0.0
    for index,((value,params),off,on) in enumerate(zip(cases,mode_outputs['off'],mode_outputs['on'])):
        for name in ('spec','diff','depth','motion','nr','debug_spec','debug_diff'):
            check(f'native material frame{index} {name} byte identity across A/B',on[name].tobytes() == off[name].tobytes())
        check(f'native material frame{index} NoV A unchanged byte-for-byte',
              np.array_equal(on['spec_albedo'][...,3],off['spec_albedo'][...,3]))
        check(f'native material frame{index} diffuse guide A unchanged byte-for-byte',
              np.array_equal(on['diff_albedo'][...,3],off['diff_albedo'][...,3]))
        if 'material' not in value:
            check('unknown material source NULL keeps both original white guide images exact',
                  np.array_equal(on['spec_albedo'],off['spec_albedo']) and np.array_equal(on['diff_albedo'],off['diff_albedo']))
            continue
        oracle = material_guide_bounds(value,on); known = oracle['known']
        known_pixels += int(known.sum()); fallback_pixels += int((~known).sum())
        actual_spec = on['spec_albedo'][...,:3].astype(np.float64)/255
        actual_diff = on['diff_albedo'][...,:3].astype(np.float64)/255
        wrong_f0 = np.clip(oracle['f0'],0,1)
        rejected_f0 += int(np.any(np.abs(actual_spec-wrong_f0) > .6/255 + 8*2.0**-23,axis=-1)[known].sum())
        wrong_roughness = material_guide_bounds(value,on,square_roughness=False)
        lo,hi = wrong_roughness['spec_bounds']
        rejected_roughness += int(np.any((actual_spec < lo) | (actual_spec > hi),axis=-1)[known].sum())
        wrong_gamma = np.sqrt(np.clip(oracle['diffuse'],0,1))
        rejected_gamma += int(np.any(np.abs(actual_diff-wrong_gamma) > .6/255 + 8*2.0**-23,axis=-1)[known].sum())
        maximum_spec_interval = max(maximum_spec_interval,float(np.max(oracle['spec_bounds'][1][known]-oracle['spec_bounds'][0][known])))
        maximum_diff_interval = max(maximum_diff_interval,float(np.max(oracle['diff_bounds'][1][known]-oracle['diff_bounds'][0][known])))
    check('material cases exercise known guides and white model1/malformed fallbacks',known_pixels > 0 and fallback_pixels > 0)
    check('actual GGX guides reject the F0-only negative model',rejected_f0 > 0)
    check('actual GGX guides reject roughness-instead-of-roughness-squared',rejected_roughness > 0)
    check('actual linear diffuse guides reject unintended sqrt/gamma encoding',rejected_gamma > 0)
    return dict(frames=count,width=width,height=height,fixtures=evidence,native_table_cases=8,
                known_pixels=known_pixels,white_fallback_pixels=fallback_pixels,
                negative_models_rejected=dict(f0_only=rejected_f0,unsquared_roughness=rejected_roughness,sqrt_diffuse=rejected_gamma),
                max_spec_interval_width=maximum_spec_interval,max_diff_interval_width=maximum_diff_interval,
                quantization='FP32 forward intervals + 0.6 integer ULP UNORM8; no intermediate half conversion',
                scope='actual production ConversionPass; lighting/source bytes/normal/NoV unchanged; no quality/FPS claim')


def synthetic(exe):
    directory = OUT / 'synthetic'
    directory.mkdir(parents=True, exist_ok=True)
    width, height, count = 13, 11, 8
    (directory / 'meta.txt').write_text(f'{count} {width} {height}', encoding='utf-8')
    cases = []
    for index in range(count):
        value = inputs(width, height, index, extremes=True)
        params = frame(width, height, index)
        write_case(directory / f'frame{index}', value, params)
        cases.append((value, params))
    stdout = run_fixture(exe, 'sequence', directory)
    previous = None
    for index, (value, params) in enumerate(cases):
        previous = verify_case(directory / f'frame{index}', value, params, previous, index > 0 and index != 4)
    verify_table_consumer(directory, width, height)
    return dict(frames=count, width=width, height=height, fixture_checks=int(re.search(r'fixture_checks=(\d+)', stdout)[1]),
                table_fixture_checks=int(re.search(r'table_fixture_checks=(\d+)', stdout)[1]),
                native_table_cases=8, table_auxiliary_bytes=196608,
                gpu_based_validation=True, source_access='Recon UAV flag4 in UA state, guides SRV without UAV flag; descriptor and borrowed-resource barrier audit',
                audited_views=int(re.search(r'audited_views=(\d+)', stdout)[1]),
                audited_barriers=int(re.search(r'audited_barriers=(\d+)', stdout)[1]),
                lifetime='8 unsubmitted frames with conversion and debug dispatches; resize and owner destruction before Execute; fence and Reset retirement',
                title_refcounts='unchanged across conversion and debug dispatch')


def capture_images(cap):
    manifest = json.loads((cap / 'capture.json').read_text(encoding='utf-8'))
    return [image for frame in manifest['frames'][:manifest.get('manifest_published_frames', 0)] for image in frame['images']]


def find_image(cap, images, prefix, dtype, channels):
    image = next(image for image in reversed(images) if image['name'].startswith(prefix))
    width, height = image['extent']
    return np.fromfile(cap / image['file'], dtype).reshape(height, width, channels), image


def captured(exe):
    cap = CAPTURES / 'da9f46edb00fd2144b531c8c0b6fc6a2'
    images = capture_images(cap)
    spec, spec_meta = find_image(cap, images, 'p7141_r44308', '<f2', 4)
    diff, diff_meta = find_image(cap, images, 'p7141_r44310', '<f2', 4)
    depth, depth_meta = find_image(cap, images, 'p7151_r44307', '<f4', 1)
    height, width = depth.shape[:2]
    value = dict(spec=spec, diff=diff, depth=depth[..., 0],
                 nr=np.full((height, width), 512 | (512 << 10) | (512 << 20), '<u4'),
                 motion=np.zeros((height, width, 4), '<f2'))
    params = frame(width, height, captured=True)
    directory = OUT / 'captured'
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'meta.txt').write_text(f'1 {width} {height}', encoding='utf-8')
    write_case(directory / 'frame0', value, params)
    stdout = run_fixture(exe, 'capture', directory)
    verify_case(directory / 'frame0', value, params)
    verify_table_consumer(directory, width, height)
    output = read_outputs(directory / 'frame0', width, height)
    REPORT.mkdir(parents=True, exist_ok=True)
    from PIL import Image, ImageDraw
    figure = Image.new('RGB', (1024, 640), (22, 23, 27))
    draw = ImageDraw.Draw(figure)
    for index, (name, title) in enumerate((('spec', 'Specular'), ('diff', 'Diffuse'))):
        source = value[name][..., :3].astype(np.float32)
        luminance = source @ np.array([0.2126, 0.7152, 0.0722], np.float32)
        valid = luminance[(luminance > 0) & np.isfinite(luminance)]
        exposure = 0.5 / max(float(np.percentile(valid, 60)), 1e-6)
        for column, (pixels, label) in enumerate(((source, 'Recon capture'), (output[name][..., :3], 'Production bridge'))):
            rgb = np.maximum(np.nan_to_num(pixels.astype(np.float32), nan=0, posinf=0, neginf=0), 0) * exposure
            rgb = np.power(np.clip(rgb / (1 + rgb), 0, 1), 1 / 2.2)
            thumb = Image.fromarray(np.rint(rgb * 255).astype('u1')).resize((512, 288), Image.Resampling.LANCZOS)
            figure.paste(thumb, (column * 512, index * 320 + 32))
            draw.text((column * 512 + 10, index * 320 + 10), f'{title}: {label}', fill=(244, 228, 143))
    figure.save(REPORT / 'da9f_conversion_before_after.png')
    return dict(capture=cap.as_posix(), spec=spec_meta, diff=diff_meta, depth_substitute=depth_meta,
                exact_normals_present=any(re.search(r'_r3749(?:s|$)', image['name']) for image in images),
                assumptions=['Exact NR3749 and original VIEWZ44287 snapshots absent.',
                             'Internal NRD depth44307 used as depth substitute.',
                             'Synthetic camera-facing oct world normal, roughness512/1023.',
                             'Static zero motion, assumed RH/FOV60deg reverse infinite projection; near0.02 derived from D=a+b/Z fit, far65504.',
                             'This verifies real lighting payload conversion; missing captured normals/camera remain synthetic. Installed-title oct/B packing is independently attested.'],
                fixture_checks=int(re.search(r'fixture_checks=(\d+)', stdout)[1]),
                table_fixture_checks=int(re.search(r'table_fixture_checks=(\d+)', stdout)[1]),
                native_table_cases=8, table_auxiliary_bytes=196608,
                outputs=(directory / 'frame0').as_posix(), image=(REPORT / 'da9f_conversion_before_after.png').as_posix())


def normal_evidence():
    cap = CAPTURES / '98913f12f502410c700b02e3afe59977'
    images = capture_images(cap)
    matches = [image for image in images if re.search(r'(?:^|_)r55458(?:s|$)', image['name'])]
    if not matches:
        return dict(exact_role_verified=False, note='Older G-buffer55458 image not found in published snapshots.')
    image = matches[-1]
    width, height = image['extent']
    raw = np.fromfile(cap / image['file'], '<u4').reshape(height, width)
    normal = normal_decode(raw)
    check('older normal decoder produces finite unit vectors', np.isfinite(normal).all() and np.max(np.abs(np.linalg.norm(normal, axis=-1) - 1)) < 1e-6)
    xy = np.stack((raw & 1023, (raw >> 10) & 1023), -1) / 1023
    plane = np.all(np.abs(xy - 0.5) < 0.025, axis=-1)
    REPORT.mkdir(parents=True, exist_ok=True)
    from PIL import Image
    Image.fromarray(np.rint(np.clip(normal * 0.5 + 0.5, 0, 1) * 255).astype('u1')).resize((752, 423)).save(REPORT / 'older_gbuffer55458_decoded_normal.png')
    return dict(source=(cap / image['file']).as_posix(), extent=image['extent'], normal_length_range=[float(np.min(np.linalg.norm(normal, axis=-1))), float(np.max(np.linalg.norm(normal, axis=-1)))],
                xy_near_half_fraction=float(plane.mean()), world_z_median_near_half=float(np.median(normal[..., 2][plane])) if plane.any() else None,
                roughness_median_near_half=float(np.median(((raw >> 20) & 1023)[plane] / 1023)) if plane.any() else None,
                exact_role_verified=False,
                note='Different G-buffer resource. Unit length is guaranteed by oct decoding and does not establish this older resource role. Installed-title oct/B packing is independently attested; the missing exact captured normal guide remains synthetic.')


def benchmark(exe, width, height, native_material_guides=None):
    label = '' if native_material_guides is None else ('material_on_' if native_material_guides else 'material_off_')
    directory = OUT / f'timing_{label}{width}x{height}'
    value = inputs(width, height)
    params = frame(width, height, captured=True)
    if native_material_guides is not None:
        value['material'] = np.full((height,width,4),.25,'<f2')
        value['material'][...,1] = .5; value['material'][...,2] = .75; value['material'][...,3] = .5
        params['native_material_guides'] = native_material_guides
    write_case(directory / 'frame0', value, params)
    (directory / 'meta.txt').write_text(f'1 {width} {height}', encoding='utf-8')
    stdout = run_fixture(exe, 'benchmark', directory)
    samples = [float(value) for value in re.search(r'^gpu_ms=([\d.,eE+-]+)', stdout, re.M)[1].split(',')]
    check('nine timestamp samples after two warm batches', len(samples) == 9 and all(value > 0 for value in samples))
    check('no per-frame descriptor heaps after warmup', 'descriptor_allocations_after_warmup=0' in stdout)
    components = {}
    if DEFERRED:
        for label in ('recon', 'motion'):
            values = [float(x) for x in re.search(r'^' + label + r'_gpu_ms=([\d.,eE+-]+)', stdout, re.M)[1].split(',')]
            check(label + ' nine timestamp samples', len(values) == 9 and all(x > 0 for x in values))
            components[label + '_median_ms'] = float(np.median(values))
            components[label + '_samples_ms'] = values
    return dict(width=width, height=height, native_material_guides=native_material_guides,
                median_ms=float(np.median(samples)), min_ms=min(samples), max_ms=max(samples),
                **components,
                samples_ms=samples, repetitions_per_batch=16, warm_batches=2, measured_batches=9,
                owned_texture_bytes=int(re.search(r'texture_bytes=(\d+)', stdout)[1]),
                descriptor_heaps=int(re.search(r'descriptor_heaps=(\d+)', stdout)[1]),
                allocations_after_warmup=0, gpu_based_validation=False, d3d12_debug_layer=True)


def main():
    global DEFERRED
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=('all', 'synthetic', 'capture', 'benchmark', 'projected-depth', 'material-ids', 'native-material'), default='all')
    parser.add_argument('--deferred', action='store_true', help='Production Recon plus current-Temporal motion path')
    parser.add_argument('--prepare-only', action='store_true', help='Generate audited production source and CPU material cases without DXC/compiler/GPU')
    args = parser.parse_args()
    DEFERRED = args.deferred
    exe = build(args.prepare_only)
    result = dict(production_source=(PASS / 'FSRDNrdBridgePass_Dx12.cpp').as_posix(), phase=args.phase, deferred_motion=DEFERRED,
                  production_source_sha256=hashlib.sha256((PASS/'FSRDNrdBridgePass_Dx12.cpp').read_bytes()).hexdigest())
    if args.prepare_only:
        if args.phase == 'native-material':
            result['native_material'] = native_material(None)
        result['prepared_only'] = True; result['python_checks'] = CHECKS
        (OUT/f'prepared_{args.phase}.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps(result,indent=2)); return
    if args.phase in ('all', 'synthetic'):
        result['synthetic'] = synthetic(exe)
    if args.phase in ('all', 'projected-depth'):
        result['projected_depth'] = projected_depth(exe)
    if args.phase in ('all', 'material-ids'):
        result['material_ids'] = material_ids(exe)
    if args.phase in ('all', 'native-material'):
        result['native_material'] = native_material(exe)
        result['native_material_timings'] = [benchmark(exe,width,height,enabled)
            for width,height in ((1505,847),(2560,1440)) for enabled in (False,True)]
        result['native_material_shader_sha256'] = hashlib.sha256((PASS/'precompile/FSRDNrdBridgeMaterial_Shader.cso').read_bytes()).hexdigest()
    if args.phase in ('all', 'capture'):
        result['captured'] = captured(exe)
        result['normal_evidence'] = normal_evidence()
    if args.phase in ('all', 'benchmark'):
        result['timings'] = [benchmark(exe, 1505, 847), benchmark(exe, 2560, 1440)]
    result['python_checks'] = CHECKS
    (OUT / f'results_{args.phase}.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    REPORT.mkdir(parents=True, exist_ok=True)
    (REPORT / f'results_{args.phase}.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(f'PASS: {CHECKS} Python checks; production conversion numerics, UAV/SRV access, borrowed lifetimes and timestamps')


if __name__ == '__main__':
    main()
