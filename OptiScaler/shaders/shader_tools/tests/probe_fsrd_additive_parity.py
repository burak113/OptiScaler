"""Exact optimization gate against the frozen, measured additive DXIL398.

Run all targeted native contracts through a paired-dispatch hook, then conversion
only on independently reproducible quality inputs and optional captured guides.
There is no AMD dispatch here: exact stored-output parity preserves the prior AMD
experiment without confounding it with another denoiser run.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import traceback
import numpy as np
import run_fsrd_gpu_tests as t
import probe_fsrd_additive_split as quality
import test_fsrd_additive_split as native
from fsrd_alpha_common import (GPUWorker, convert, extract_baseline, frozen_identity,
                               rgba, save_json, seed_frame, shader_identity)

MEASURED_DXIL = '398dd3bc20486780479feb0aa4782438d6ea053e9fa4a305cc0b945a2d17728d'
MEASURED_SOURCE = 'd41694ccaaa2a906bbbd11e7526898483bec85fd2e39777cf34180823d525344'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def json_value(value):
    if isinstance(value, dict):
        return {k: json_value(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [json_value(v) for v in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    return value


class ExactParity:
    def __init__(self, baseline, output):
        self.baseline, self.output = baseline, output
        self.original = t.dispatch
        self.checks = []
        self.no_fit_checks = []
        self.label = 'native'
        self.saved_failures = 0

    def __enter__(self):
        t.dispatch = self.dispatch
        return self

    def __exit__(self, *args):
        t.dispatch = self.original

    def dispatch(self, shader, values, inputs, output_formats, size,
                 directory=t.PRE, repetitions=1):
        result = self.original(shader, values, inputs, output_formats, size, directory, repetitions)
        if shader != 'FSRDInputConvAdditive' or Path(directory).resolve() != t.PRE.resolve():
            return result
        # The frozen398 artifact predates the dual-PSO basename. Its original
        # cbuffer/source text supplies the same complete416-byte contract.
        old = self.original('FSRDInputConv', values, inputs, output_formats, size, self.baseline, 1)
        differences = []
        for i, (a, b) in enumerate(zip(old, result)):
            changed = a != b
            if np.any(changed):
                differences.append(dict(output=i, changed_channels=changed.sum(axis=(0, 1)).tolist(),
                    maximum_delta_channels=np.abs(a-b).max(axis=(0, 1)).tolist()))
        check = dict(case=self.label, strength=float(values.get('AdditiveLightSplit', 0)),
                     size=list(size), passed=not differences, differences=differences)
        self.checks.append(check)
        if differences:
            print('FAIL measured398 parity '+str(check), flush=True)
            if self.saved_failures < 8:
                folder = self.output/('failure_'+str(self.saved_failures))
                folder.mkdir()
                np.savez_compressed(folder/'inputs.npz', **{f't{i}':a for i, a in enumerate(inputs)})
                np.savez_compressed(folder/'outputs.npz', **{
                    **{f'old_u{i}':a for i, a in enumerate(old)},
                    **{f'new_u{i}':a for i, a in enumerate(result)}})
                save_json(folder/'case.json', dict(check=check, constants=json_value(values)))
                self.saved_failures += 1
        return result


def patterned(w, h, rng):
    y, x = np.indices((h, w))
    pattern = ((x+2*y) % 7)/6
    d = rgba((.07+.40*pattern)[..., None]*np.array([.70, .85, 1]))
    s = t.rgba(w, h, (13/255, 16/255, 21/255))
    c = rgba((d[..., :3]+s[..., :3])*[.45, .38, .32]+[.08, .07, .055])
    c[..., :3] += rng.uniform(-.005, .005, c[..., :3].shape)
    return c, d, s


def stress(parity):
    rng = np.random.default_rng(92631)
    sizes = [(1, 1), (1, 17), (17, 1), (3, 5), (7, 9), (8, 8), (9, 9), (41, 31), (65, 33)]
    for w, h in sizes:
        c, d, s = patterned(w, h, rng)
        for strength in (.5, 1):
            parity.label = f'odd_or_partial_group_{w}x{h}'
            convert(c, d, s, strength)
    w, h = 43, 29
    c, d, s = patterned(w, h, rng)
    z = np.full((h, w), 10, np.float32)
    z[:, w//2:] = 20
    n = t.rgba(w, h, (0, 0, -1))
    n[h//2:, :, :3] = (0, 1, 0)
    r = np.full((h, w), .55, np.float32)
    r[:h//3] = 0
    r[h//3:2*h//3] = .04
    floor = rgba(np.minimum(c[..., :3], .045))
    # Zero roughness, geometry edges and partial modulation exercise the existing
    # Floor handover exclusions and fullSignal/retainedFloor accounting.
    for sm, dm in ((1, 1), (.5, 1), (1, .5), (0, 0)):
        for strength in (.5, 1):
            parity.label = f'floor_handover_geometry_sm{sm}_dm{dm}'
            convert(c, d, s, strength, depth=z, normals=n, roughness=r, floor=floor,
                    overrides=dict(SpecularAlbedoDemodulation=sm, DiffuseAlbedoModulation=dm))
    for angle in (-1.1, -.4, .35, 1):
        co, si = np.cos(angle), np.sin(angle)
        inv = np.array([[co, 0, -si, 0], [0, 1, 0, 0], [si, 0, co, 0], [0, 0, 0, 1]])
        for strength in (.5, 1):
            parity.label = f'orbit_rotation_{angle}'
            convert(c, d, s, strength, normals=n, roughness=r, depth=z,
                    overrides=dict(InvViewMatrix=inv.ravel(), PrevViewMatrix=inv.T.ravel(),
                                   Flags=(1 << 1)|(1 << 5)|(1 << 11)))
    # Valid irregular guides exercise rejected channels and divisor/clamp floors.
    for i in range(4):
        c = rgba(rng.uniform(.001, 8, (h, w, 3)))
        d = rgba(rng.uniform(0, 1.05, (h, w, 3)))
        s = rgba(rng.uniform(0, .15, (h, w, 3)))
        for strength in (.5, 1):
            parity.label = f'irregular_rgb_guides_{i}'
            convert(c, d, s, strength, depth=z, normals=n, roughness=r)
    # Independently offset source planes with valid data beyond the logical
    # extent; those extra texels must never become duplicated/extra fit taps.
    c, d, s = patterned(w, h, rng)
    def pad(a, ox, oy, value):
        result = np.full((h+8, w+8, *a.shape[2:]), value, np.float32)
        result[oy:oy+h, ox:ox+w] = a
        return result
    origins = dict(InputBase0=[2, 3, 0, 0], InputBase1=[4, 2, 3, 4],
                   InputBase2=[0, 0, 5, 1], InputBase3=[1, 5, 0, 0])
    for strength in (.5, 1):
        parity.label = 'distinct_origins_partial_groups'
        convert(pad(c, 2, 3, 6), pad(d, 5, 1, .8), pad(s, 1, 5, .6), strength,
                normals=pad(n, 4, 2, 1), roughness=pad(r, 3, 4, .95), depth=z,
                reference=c, size=(w, h), origins=origins)


def constant_halo_stress(parity):
    """Independent no-variance truth, including varying complementary lobes."""
    rng = np.random.default_rng(51493)
    cases = [(level, w, h, 'valid', False) for level in (2, 8, 32, 128, 255)
             for w, h in ((1, 17), (9, 7), (19, 13))]
    cases += [(128, 19, 13, mode, False) for mode in ('normal', 'guide', 'bias', 'emissive')]
    cases += [(level, 19, 13, 'valid', True) for level in (128, 255)]
    for level, w, h, mode, complementary in cases:
        y, x = np.indices((h, w))
        sc = min(13, max(1, level//4))
        spec_codes = np.full((h, w), sc, np.float32)
        if complementary:
            spec_codes += (x+y) % 2
        d, s = rgba((level-spec_codes)/255), rgba(spec_codes/255)
        c = rgba(rng.uniform(.04, .3, (h, w, 3)))
        n = t.rgba(w, h, (0, 0, -1))
        mask = (x+3*y) % 11 == 0
        opts = dict(normals=n)
        if mode == 'normal':
            n[mask, :3] = 0
        elif mode == 'guide':
            d[mask, 0] = np.nan
        elif mode in ('bias', 'emissive'):
            signal = t.rgba(w, h, (0, 0, 0))
            signal[mask, :3] = .6 if mode == 'bias' else .02
            opts['resources'] = {8 if mode == 'bias' else 11:signal}
            opts['overrides'] = {'Flags':(1 << 1)|(1 << 5)|(1 << (15 if mode == 'bias' else 6))}
        a = native.quantized(d[..., :3])+native.quantized(s[..., :3])
        for floor_on in (False, True):
            values = dict(opts)
            if floor_on:
                values['floor'] = rgba(np.minimum(c[..., :3], .03))
                if 'overrides' in values:
                    values['overrides'] = dict(values['overrides'])
                    values['overrides']['Flags'] |= 1 << 7
            parity.label = f'constant_halo_code{level}_{w}x{h}_{mode}_complementary{complementary}_floor{floor_on}'
            zero = convert(c, d, s, 0, kernel='additive', **values)
            for strength in (.5, 1):
                enabled = convert(c, d, s, strength, **values)
                differences = [i for i, (p, q) in enumerate(zip(zero, enabled)) if not np.array_equal(p, q)]
                check = dict(case=parity.label, strength=strength, passed=not differences,
                    different_outputs=differences, stored_total_minimum=np.nanmin(a, axis=(0, 1)).tolist(),
                    stored_total_maximum=np.nanmax(a, axis=(0, 1)).tolist())
                parity.no_fit_checks.append(check)
                if differences:
                    print('FAIL constant-halo no-fit '+str(check), flush=True)
    print(f'Constant-halo no-fit checks: {sum(c["passed"] for c in parity.no_fit_checks)}/{len(parity.no_fit_checks)}', flush=True)


def quality_inputs(parity, frames, base, capture, metadata):
    cases = [(s, 17331, ('off',), (.5, 1)) for s in quality.DEFAULT_SCENES]
    cases += [(s, 91743, ('off',), (1,)) for s in ('fake_island', 'material_additive', 'wave_lighting',
                                                    'moving_additive', 'exposure_additive')]
    cases += [(s, 17331, ('on',), (.5, 1)) for s in ('fake_island', 'material_additive')]
    if capture:
        cases += [(s, 17331, ('off',), (.5, 1)) for s in ('recorded_island', 'recorded_wave')]
    for scene, seed, floors, strengths in cases:
        data = quality.fixture(scene, frames, seed, capture, metadata)
        for floor_mode in floors:
            for f, raw in enumerate(data['raw']):
                floor, depth, reference = (seed_frame(rgba(raw), quality.frame_array(data['diff'], f),
                    data['depth'], data['normals'], base, overrides=data['overrides'])
                    if floor_mode == 'on' else (None, data['depth'], None))
                for strength in strengths:
                    parity.label = f'quality_{scene}_seed{seed}_floor{floor_mode}_frame{f}'
                    overrides = dict(data['overrides'])
                    if data['extra_flags']:
                        overrides['Flags'] = (1 << 1)|(1 << 5)|data['extra_flags']|((1 << 7) if floor_mode == 'on' else 0)
                    convert(rgba(raw), quality.frame_array(data['diff'], f), quality.frame_array(data['spec'], f),
                        strength, depth=depth, normals=data['normals'], roughness=data['roughness'], floor=floor,
                        reference=reference, motion=data['motion'][f], overrides=overrides, resources=data['resources'])
            print(f'Compared all {frames} frames of {scene} seed {seed} Floor {floor_mode}; checks={len(parity.checks)}', flush=True)


def captured_edges(parity, frames, capture, metadata):
    if not capture:
        return
    for scene in ('recorded_island', 'recorded_wave'):
        data = quality.fixture(scene, frames, 17331, capture, metadata)
        for f in (0, frames-1):
            for strength in (.5, 1):
                parity.label = f'capture_edge_{scene}_frame{f}'
                overrides = dict(data['overrides'])
                overrides['Flags'] = (1 << 1)|(1 << 5)|data['extra_flags']
                convert(rgba(data['raw'][f]), data['diff'], data['spec'], strength,
                    depth=data['depth'], normals=data['normals'], roughness=data['roughness'],
                    motion=data['motion'][f], overrides=overrides, resources=data['resources'])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline', type=Path, required=True, help='Frozen pre-dual measured398 source+CSO directory')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--original-baseline', type=Path)
    parser.add_argument('--frames', type=int, default=64)
    parser.add_argument('--captured-island', '--trace', type=Path)
    parser.add_argument('--captured-metadata', type=Path)
    parser.add_argument('--skip-quality', action='store_true', help='Fast native/stress gate only')
    parser.add_argument('--skip-stress', action='store_true', help='Quick native/captured gate before isolated performance')
    args = parser.parse_args()
    if bool(args.captured_island) != bool(args.captured_metadata):
        parser.error('Captured NPZ and original metadata must be supplied together')
    if args.frames < 4 or args.frames % 2:
        parser.error('Even frames>=4 required')
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    args.baseline = args.baseline.resolve()
    if (args.baseline == t.PRE.resolve() or sha(args.baseline/'FSRDInputConv_Shader.cso') != MEASURED_DXIL or
            sha(args.baseline/'FSRDInputConv.hlsl') != MEASURED_SOURCE):
        raise ValueError('Expected separate immutable measured398 baseline')
    base = args.original_baseline or extract_baseline(args.output)
    original = frozen_identity(base)
    initial = shader_identity(t.PRE)
    report = dict(baseline=dict(path=str(args.baseline), source_sha256=sha(args.baseline/'FSRDInputConv.hlsl'),
        dxil_sha256=MEASURED_DXIL), original=original, candidate=initial, frames=args.frames,
        actual_amd=False, source_sha256=sha(__file__), checks=[])
    failure = None
    parity = ExactParity(args.baseline, args.output)
    try:
        with parity:
            os.environ['FSRD_GPU_TEST_OUTPUT'] = str(args.output/'native')
            os.environ['FSRD_ALPHA_BASELINE'] = str(base)
            native.run()
            report['native_report'] = str(args.output/'native/results.json')
            with GPUWorker(args.output/'conversion'):
                constant_halo_stress(parity)
                if not args.skip_stress:
                    stress(parity)
                captured_edges(parity, args.frames, args.captured_island, args.captured_metadata)
                if not args.skip_quality:
                    quality_inputs(parity, args.frames, base, args.captured_island, args.captured_metadata)
    except BaseException:
        failure = traceback.format_exc()
    report.update(checks=parity.checks, constant_halo_no_fit_checks=parity.no_fit_checks,
        failure=failure, dispatches=t.timings,
        artifact_freeze_passed=initial == shader_identity(t.PRE),
        passed_checks=sum(c['passed'] for c in parity.checks), checked_dispatches=len(parity.checks))
    save_json(args.output/'results.json', report)
    print(f"Exact measured398 parity: {report['passed_checks']}/{len(parity.checks)}; production dispatches={len(t.timings)}", flush=True)
    if (failure or not report['artifact_freeze_passed'] or not all(c['passed'] for c in parity.checks) or
            not all(c['passed'] for c in parity.no_fit_checks)):
        raise AssertionError(failure or 'Optimized additive output differs from measured398')


if __name__ == '__main__':
    main()
