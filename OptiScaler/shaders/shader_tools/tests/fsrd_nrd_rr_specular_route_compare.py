"""One frozen positive-r123 demod IS-vs-DS model control, research only.

Default is CPU provenance validation. --run compiles a NEW fixture and executes
only after a parent-granted shared compiler/GPU slot via lead_ops. Production
flags stay DD|IS. The DS route receives indirect RGB intentionally, with ABI-
valid positive unchanged A, so this is not a direct-light equivalence claim.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import struct
import subprocess
import sys

import numpy as np

import fsrd_nrd_rr_ggx_audit_compare as audit
import fsrd_nrd_rr_ggx_compare as baseline
import fsrd_nrd_rr_ggx_oracle as oracle
import fsrd_nrd_rr_ggx_uncertainty as uncertainty
import fsrd_nrd_rr_ggx_views as domain
import fsrd_nrd_rr_material_compare as native_common
import fsrd_nrd_rr_material_quality as sealed

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(HERE.parent))
CASE = Path('F:/FSRD/sol_batch/15c-rr/ggx-v5-demod/r123')
ORIGINAL_CPP_SHA = 'ba873fd2505b05b4a4dd11b9068d60907b3461da3a5830a18385089fe25624c3'


def validate_fixture_body():
    raw = (HERE / 'fsrd_nrd_rr_specular_route_replay.cpp').read_bytes()
    lines = raw.splitlines(keepends=True)
    domain.need(lines[1].strip() == b'#include "fsrd_nrd_rr_specular_route_adapter.h"', 'new adapter is explicit outside original fixture body')
    raw = b''.join(line for line in lines[2:] if not line.startswith((b'    SpecularRouteResearch::Check(', b'    result["research"]=')))
    raw = raw.replace(b'loadReal();SpecularRouteResearch::Install();need(', b'loadReal();need(')
    entry = b'int main(int argc,char** argv) try{SpecularRouteResearch::Check(argc==7,"specular route replay adds explicit final is|ds argument");const std::string route=argv[6];SpecularRouteResearch::Check(route=="is"||route=="ds","explicit provider specular route");SpecularRouteResearch::direct=route=="ds";return WorldMotionQuality::run(argc-1,argv);}'
    domain.need(raw.count(entry) == 1, 'only added CLI selector wraps original entry')
    raw = raw.replace(entry, b'int main(int argc,char** argv) try{return WorldMotionQuality::run(argc,argv);}')
    domain.need(sealed.sha(raw) == ORIGINAL_CPP_SHA, 'removing only the explicit adapter lines reconstructs every byte of the sealed original assertion body')


def build(output):
    from fsrd_toolchain import compile_cpp, dxc
    domain.need(not output.exists(), 'fresh isolated compiler/cache root')
    output.mkdir(parents=True)
    os.environ['FSRD_CPP_CACHE'] = str(output / 'cache')
    (output / 'pch.h').write_text('#pragma once\n', encoding='ascii')
    shader = output / 'consumer.cso'
    subprocess.run([str(dxc()), '-T', 'cs_6_2', '-E', 'CSMain', '-O3', '-force-rootsig-ver',
        'rootsig_1_0', str(HERE / 'nrd_bridge_consumer_fixture.hlsl'), '-Fo', str(shader)], check=True)
    (output / 'consumer_shader.h').write_text('const unsigned char ConsumerShaderBytes[] = {' + ','.join(map(str, shader.read_bytes())) + '};\n', encoding='ascii')
    executable = output / 'specular_route_quality.exe'
    compile_cpp(HERE / 'fsrd_nrd_rr_specular_route_replay.cpp', executable,
        ['d3d12.lib', 'dxgi.lib', 'd3dcompiler.lib', 'bcrypt.lib'],
        [output, ROOT / 'OptiScaler', ROOT / 'OptiScaler/include', ROOT / 'external/nlohmann',
         ROOT / 'external/streamline', ROOT / 'external/FidelityFX-SDK/ffx-api/include/ffx_api'])
    sources = (Path(__file__), HERE / 'fsrd_nrd_rr_specular_route_replay.cpp',
        HERE / 'fsrd_nrd_rr_specular_route_adapter.h', HERE / 'nrd_bridge_rr_fixture.cpp',
        HERE / 'nrd_bridge_rr_test_support.h', ROOT / 'OptiScaler/shaders/fsrd_preprocess/FSRDNrdBridgeRR_Dx12.cpp',
        ROOT / 'OptiScaler/shaders/fsrd_preprocess/FSRDNrdBridgeRR_Dx12.h', shader)
    return executable, dict(executable_sha256=sealed.file_sha(executable), sources={str(path): sealed.file_sha(path) for path in sources})


def native(executable, view, destination, route, settings=None):
    from test_fsrd_nrd_bridge_rr import bounded_run
    domain.need(not destination.exists(), 'fresh signed output preserves earlier attempts')
    destination.mkdir(parents=True)
    probe = settings is None
    command = [str(executable), str(view), str(destination), 'dd', 'DEFAULT' if probe else str(settings), '1' if probe else 'ALL', route]
    text, peak, elapsed, log = bounded_run(command, destination / 'native')
    result = json.loads((destination / 'native-result.json').read_bytes())
    domain.need('PASS world_motion ' in text and result['checks'] == (211 if probe else 8214), 'every original strict world-motion assertion is retained')
    domain.need(result['creates'] == result['destroys'] == 1 and result['dispatches'] == (1 if probe else 64), 'fresh actual context with deferred balanced destruction')
    domain.need(result['debug_errors'] == result['debug_warnings'] == 0, 'strict zero native D3D12 errors AND warnings')
    domain.need(result['route'] == 'dd' and result['signal_flags'] == 0x22 and result['specular_descriptor_type'] == 0x50048,
        'original production wrapper still produces DD|IS without any source mutation')
    selected = result['research']
    domain.need(selected['specular_route'] == route and selected['actual_provider_signal_flags'] == (0x06 if route == 'ds' else 0x22) and
        selected['actual_provider_specular_type'] == (0x50045 if route == 'ds' else 0x50048), 'actual signed export receives the explicit DS/IS create+dispatch ABI')
    domain.need(selected['actual_provider_creates'] == 1 and selected['actual_provider_dispatches'] == result['dispatches'] and selected['original_body_sha256'] == ORIGINAL_CPP_SHA, 'adapter forwards every actual sample and retains original fixture provenance')
    domain.need(result['provider_version_id'] == 4311875584 and not result['native_birth_ready'], 'signed AMD1.2 and standalone adapter boundary')
    domain.need([row['reset'] for row in result['frames']] == [True] + [False] * (result['dispatches'] - 1) and
        all(row['current_gpu_guides_exact'] for row in result['frames']), 'first-only reset and current exact seven-input GPU readbacks')
    result.update(directory=str(destination), native_log=str(log), peak_resident_bytes=peak, elapsed_seconds=elapsed)
    return result


def execute(case, manifest, output):
    domain.need(not output.exists() and output.resolve().is_relative_to(native_common.TASK.resolve()), 'fresh task-local run root')
    domain.need(sealed.file_sha(native_common.DLL) == native_common.DLL_SHA, 'exact installed signed AMD provider')
    output.mkdir(parents=True)
    executable, build_info = build(output / 'build')
    view = Path(next(iter(manifest['views'].values())))
    probe = native(executable, view, output / 'defaults-probe', 'is')
    values = struct.unpack('<8f', struct.pack('<8I', *probe['effective_words']))
    settings = output / 'common-effective-settings.txt'
    settings.write_text(' '.join(format(value, '.9g') for value in values) + '\n', encoding='ascii')
    runs = {}
    for route in ('is', 'ds'):
        result = native(executable, view, output / route, route, settings)
        domain.need(result['effective_words'] == probe['effective_words'], 'both physically fresh contexts use identical eight effective setting bits')
        result.update(input_case=str(case), input_manifest_sha256=sealed.file_sha(case / 'ggx-sequence.json'), outputs={})
        for frame in manifest['frames']:
            folder = output / route / frame['directory']
            domain.need(sealed.file_sha(folder / 'motion.bin') == frame['payloads']['motion']['sha256'], 'exact same actual primary-motion input in each provider route')
            result['outputs'][str(frame['frame'])] = {}
            for signal, alpha in (('spec', .75), ('diff', 2.)):
                path = folder / (signal + '.bin')
                value = np.fromfile(path, '<f2').reshape(128, 128, 4)
                domain.need(np.isfinite(value).all() and np.all(value[..., 3] == np.float16(alpha)), 'finite RGB and exact opaque title alpha in both routes')
                result['outputs'][str(frame['frame'])][signal] = sealed.file_sha(path)
        sealed.write_json(output / route / 'native-result.json', result)
        runs[route] = result
    sealed.write_json(output / 'runs.json', dict(schema=oracle.SCHEMA + '-specular-route-runs', build=build_info,
        input_case=str(case), input_manifest_sha256=sealed.file_sha(case / 'ggx-sequence.json'), probe=probe, runs=runs,
        provider_dll_sha256=native_common.DLL_SHA, compiler_executed=True, gpu_executed=True))


def compare(case, manifest, output):
    runs = json.loads((output / 'runs.json').read_bytes())
    domain.need(runs['input_manifest_sha256'] == sealed.file_sha(case / 'ggx-sequence.json'), 'same immutable case before scoring')
    physical_case = Path(manifest['physical_case'])
    physical_manifest = json.loads((physical_case / 'ggx-sequence.json').read_bytes())
    camera = oracle.camera_api()
    frames, paired = [], []
    gradient_rows = {route: [] for route in ('is', 'ds')}
    for index, frame in enumerate(manifest['frames']):
        data = domain.load_frame(case, manifest, frame)
        physical = domain.load_frame(physical_case, physical_manifest, physical_manifest['frames'][index],
            ('reference_spec', 'reference_spec_a', 'reference_spec_b', 'reference_diff', 'object'))
        qs = data['spec_albedo'][..., :3].astype(np.float64) / 255.
        values = {}
        for route in ('is', 'ds'):
            values[route] = {}
            for signal in ('spec', 'diff'):
                path = output / route / frame['directory'] / (signal + '.bin')
                domain.need(sealed.file_sha(path) == runs['runs'][route]['outputs'][str(frame['frame'])][signal], 'sealed actual signed output before scoring')
                rgb = np.fromfile(path, '<f2').reshape(128, 128, 4)[..., :3].astype(np.float64)
                values[route][signal] = rgb * (qs if signal == 'spec' else 1.)
        metrics = {signal: {} for signal in ('spec', 'diff')}
        for signal in ('spec', 'diff'):
            for route in ('is', 'ds'):
                ghost = data['ghost_' + signal].astype(np.float64) * (qs if signal == 'spec' else 1.)
                metrics[signal][route] = camera['metrics'](values[route][signal], physical['reference_' + signal], data['reveal_age'], ghost, manifest['comparison_crop'])
        a, b = [physical['reference_spec_' + suffix] for suffix in ('a', 'b')]
        row = uncertainty.paired_mse(values['ds']['spec'], values['is']['spec'], a, b, manifest['comparison_crop'])
        paired.append(row)
        x, y, width, height = manifest['comparison_crop']
        crop = np.s_[y:y + height, x:x + width]
        for route in ('is', 'ds'):
            gradient_rows[route].append(audit.gradients(values[route]['spec'][crop], a[crop], b[crop]))
        frames.append(dict(frame=frame['frame'], domains=metrics, ds_minus_is_spec_paired_mse=row))
    result = dict(schema=oracle.SCHEMA + '-specular-route-comparison', summaries=native_common.summarize(frames, ['is', 'ds']),
        ds_minus_is_spec_paired_mse=uncertainty.summarize_paired(paired), split_reference_gradients={route: audit.summarize(rows) for route, rows in gradient_rows.items()},
        frames=frames, runs=runs, checks=domain.CHECKS, payload_integrity_checks=sealed.CHECKS,
        all_noisy_lighting_through_rr=True, zero_roughness_used=False, production_signal_changed=False,
        scope='one positive-r123 guide-defined-demod synthetic history, only real-export specular route changed; DS radiance semantics intentionally differ; not a production recommendation or native-title quality claim')
    sealed.write_json(output / 'comparison.json', result)
    print(json.dumps({name: value for name, value in result.items() if name not in ('frames', 'runs')}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', type=Path, default=CASE)
    parser.add_argument('--output', type=Path, default=native_common.TASK / 'ggx-specular-route-run1')
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--analyze-existing', action='store_true')
    args = parser.parse_args()
    validate_fixture_body()
    manifest = baseline.validate(args.case)
    domain.need(manifest['schema'] == domain.DEMOD_SCHEMA and manifest['code'] == 123, 'predeclared single strictly positive r123 demod control')
    if args.run:
        execute(args.case, manifest, args.output)
    if args.run or args.analyze_existing:
        compare(args.case, manifest, args.output)
    else:
        print(json.dumps(dict(checks=domain.CHECKS, sealed_payload_checks=sealed.CHECKS,
            gpu_executed=False, compiler_executed=False, measured_routes=['is', 'ds'], original_cpp_sha256=ORIGINAL_CPP_SHA), indent=2))


if __name__ == '__main__':
    main()
