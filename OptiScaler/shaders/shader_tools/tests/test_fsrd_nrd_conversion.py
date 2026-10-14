"""GPU checks of the production NRD bridge conversion, capture replay and timestamps.

Run through lead_ops/run_task_test.py so one machine-wide GPU lock covers the
compiler and every fixture. Recon stays in UAV state; guides have no UAV flag.
GPU validation and descriptor/barrier instrumentation verify the required views.
"""
from pathlib import Path
import argparse
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

ROOT = Path(__file__).resolve().parents[4]
PASS = ROOT / 'OptiScaler/shaders/fsrd_preprocess'
OUT = Path(os.environ.get('FSRD_GPU_TEST_OUTPUT', 'F:/FSRD/sol_batch/12b-conversion/tests/nrd_conversion'))
REPORT = Path(os.environ.get('FSRD_NRD_REPORT_OUTPUT', f'E:/FSRD/sol_batch/{OUT.parents[1].name}/conversion-evidence'))
CAPTURES = Path('F:/Ultra Yedek 2/overwrite/bin/x64/GAME_TRACE/FRAME_SURVEY')
CHECKS = 0
DEFERRED = False

AUDIT = r'''
#include <unordered_set>
static uint32_t gNrdDescriptorAllocations = 0, gNrdAuditedViews = 0, gNrdAuditedBarriers = 0;
static std::unordered_set<ID3D12Resource*> gNrdReconInputs, gNrdGuideInputs, gNrdTitleOutputs;
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
    }
    list->ResourceBarrier(count, barriers);
}
'''


def check(name, condition):
    global CHECKS
    CHECKS += 1
    if not condition:
        raise AssertionError(name)


def build():
    OUT.mkdir(parents=True, exist_ok=True)
    consumer_shader = OUT / 'consumer.cso'
    subprocess.run([str(dxc()), '-T', 'cs_6_2', '-E', 'CSMain', '-O3', '-force-rootsig-ver', 'rootsig_1_0',
                    str(Path(__file__).with_name('nrd_bridge_consumer_fixture.hlsl')), '-Fo', str(consumer_shader)], check=True)
    (OUT / 'consumer_shader.h').write_text('const unsigned char ConsumerShaderBytes[] = {' +
                                         ','.join(str(x) for x in consumer_shader.read_bytes()) + '};\n', encoding='utf-8')
    source = (PASS / 'FSRDNrdBridgePass_Dx12.cpp').read_text(encoding='utf-8')
    support = Path(__file__).with_name('dx12_shader_test_support.h').as_posix()
    source = source.replace('#include "pch.h"', f'#include "{support}"\n' + AUDIT)
    source = source.replace('#include "resource_tracking/ResTrack_Dx12.h"', '')
    source = source.replace('#include "State.h"', '')
    check('one descriptor instrumentation point', source.count('slots.push_back(slot);') == 1)
    source = source.replace('slots.push_back(slot);', '++gNrdDescriptorAllocations; slots.push_back(slot);')
    check('two production barrier call sites', source.count('list->ResourceBarrier(') == 3)
    # One call is the audit wrapper itself, two are the production pass's helpers.
    source = source.replace('list->ResourceBarrier(1, &barrier);', 'AuditedNrdBarriers(list, 1, &barrier);')
    source = source.replace('list->ResourceBarrier(2, barriers);', 'AuditedNrdBarriers(list, 2, barriers);')
    check('one production SRV descriptor loop', source.count('for (auto* resource : srvs)\n        {') == 1)
    check('one production UAV descriptor loop', source.count('for (auto* resource : uavs)\n        {') == 1)
    source = source.replace('for (auto* resource : srvs)\n        {', 'for (auto* resource : srvs)\n        {\n            AuditNrdSrv(resource);')
    source = source.replace('for (auto* resource : uavs)\n        {', 'for (auto* resource : uavs)\n        {\n            AuditNrdUav(resource);')
    (OUT / 'production_nrd_pass.cpp').write_text(source, encoding='utf-8')
    shutil.copyfile(Path(__file__).with_name('fsrd_nrd_conversion_fixture.cpp'), OUT / 'fixture.cpp')
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
    for name, value in inputs.items():
        value.tofile(directory / f'{name}.bin')
    values = [params['near'], params['far'], params['sign'], *params['scale'], *params['jitter'],
              *params['previous_jitter'], int(params['jittered']), int(params['reset']),
              int(params['previous_valid']), params['mode'], *params['view'].ravel(), *params['projection'].ravel()]
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


def verify_case(directory, input_values, params, previous_depth=None, history_valid=False):
    height, width = input_values['depth'].shape
    output = read_outputs(directory, width, height)
    depth, motion, no_v = reference(input_values, params, previous_depth, history_valid)
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
    check(f'{directory.name} packed normals RGB preserved alpha zero', np.array_equal(output['nr'], input_values['nr'] & 0x3fffffff))
    check(f'{directory.name} motion scale jitter depth delta and W', np.allclose(output['motion'], motion, rtol=1e-3, atol=2e-4))
    check(f'{directory.name} motion finite', np.isfinite(output['motion']).all())
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


def benchmark(exe, width, height):
    directory = OUT / f'timing_{width}x{height}'
    value = inputs(width, height)
    params = frame(width, height, captured=True)
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
    return dict(width=width, height=height, median_ms=float(np.median(samples)), min_ms=min(samples), max_ms=max(samples),
                **components,
                samples_ms=samples, repetitions_per_batch=16, warm_batches=2, measured_batches=9,
                owned_texture_bytes=int(re.search(r'texture_bytes=(\d+)', stdout)[1]),
                descriptor_heaps=int(re.search(r'descriptor_heaps=(\d+)', stdout)[1]),
                allocations_after_warmup=0, gpu_based_validation=False, d3d12_debug_layer=True)


def main():
    global DEFERRED
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=('all', 'synthetic', 'capture', 'benchmark'), default='all')
    parser.add_argument('--deferred', action='store_true', help='Production Recon plus current-Temporal motion path')
    args = parser.parse_args()
    DEFERRED = args.deferred
    exe = build()
    result = dict(production_source=(PASS / 'FSRDNrdBridgePass_Dx12.cpp').as_posix(), phase=args.phase, deferred_motion=DEFERRED)
    if args.phase in ('all', 'synthetic'):
        result['synthetic'] = synthetic(exe)
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
