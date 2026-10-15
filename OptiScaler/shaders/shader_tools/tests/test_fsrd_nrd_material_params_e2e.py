"""Actual coordinator CaptureParams -> 6SRV guides -> signed AMD RR.

--prepare-only generates source without compiler/native/GPU work. Run under the
lead's exclusive shared GPU/build lock. Original fixture bodies remain intact.
"""
from pathlib import Path
import argparse
import ast
import hashlib
import json
import os
import sys
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path[:0] = [str(HERE), str(HERE.parent)]
from fsrd_toolchain import compile_cpp
import test_fsrd_nrd_e2e as baseline
from test_fsrd_nrd_bridge_rr import bounded_run, DLL


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def prepare(out):
    out.mkdir(parents=True, exist_ok=True)
    commands, old = [], baseline.compile_cpp
    baseline.compile_cpp = lambda *args, **kwargs: commands.append((args, kwargs))
    try:
        baseline.build(out)
    finally:
        baseline.compile_cpp = old
    assert len(commands) == 1
    args, kwargs = commands[0]
    source = Path(args[0]).read_text(encoding='utf-8')
    marker = '  ++internalBarriers;'
    assert source.count(marker) == 1
    source = source.replace(marker, marker + '\n  ParamsHostAudit(barriers[i]);')
    prefix = '#include <d3d12.h>\nvoid ParamsHostAudit(const D3D12_RESOURCE_BARRIER&) noexcept;\n#define main PreservedNrdMaterialE2EMain\n'
    fixture = HERE / 'fsrd_nrd_material_params_e2e.cpp'
    path, exe = out / 'material_params_host.cpp', out / 'material_params_host.exe'
    path.write_text(prefix + source + '\n#undef main\n' + fixture.read_text(encoding='utf-8'), encoding='utf-8')
    evidence = dict(schema='fsrd-material-params-host-source-v1', compiler_executed=False, native_executed=False,
                    gpu_executed=False, generated_cpp_sha256=sha(path), new_fixture_sha256=sha(fixture),
                    unchanged_fixture_sha256=sha(HERE / 'fsrd_nrd_e2e_fixture.cpp'),
                    unchanged_driver_sha256=sha(HERE / 'test_fsrd_nrd_e2e.py'),
                    expected_native_birth_ready=False, expected_signed_dispatches_per_mode=7)
    (out / 'source-preparation.json').write_text(json.dumps(evidence, indent=2) + '\n', encoding='utf-8')
    return exe, (path, exe, *args[2:]), kwargs


def guide_bounds(material, nr, spec_albedo, exact_roughness):
    """Independent expanded public-SDK rational with FP32/UNORM8 intervals.

    Exact captured R16F G is consumed directly; never requantized through NR.B.
    NoV is bounded by its observed same-scalar UNORM8 alpha +/-0.6/255. Bounds
    include gamma64 polynomial rounding and the specified 2^-21 rcp error.
    The original guide reference and all original tests remain unchanged.
    """
    from test_fsrd_nrd_conversion import material_brdf_polynomials
    m = material.astype(np.float64)
    known = (nr >> 30) != 3
    known &= np.isfinite(m).all(-1) & (m >= 0).all(-1) & (m <= 1).all(-1)
    base, metal = m[..., :3], m[..., 3:]
    f0 = .04 * (1-metal) + base * metal
    diffuse = base * (1-metal)
    rough = np.clip(np.asarray(exact_roughness, dtype=np.float64), float(np.float32(.04)), 1)
    nov = spec_albedo[..., 3].astype(np.float64)/255
    a = rough**2
    nb, db, ns, ds = material_brdf_polynomials(nov, a)
    point = f0*np.maximum(ns/ds, 0)[..., None] + (np.maximum(nb/db, 0)*np.clip(f0[..., 1]*50, 0, 1))[..., None]
    eps, unorm = 2.**-23, .6/255
    gamma = 64*eps/(1-64*eps)
    n = (np.maximum(0, nov-unorm), np.minimum(1, nov+unorm))
    r = (np.maximum(0, rough-eps), np.minimum(1, rough+eps))
    alpha = (np.maximum(0, r[0]**2-eps), np.minimum(1, r[1]**2+eps))
    terms = (
        ((.99044,0,0),(-1.28514,1,0),(1.29678,0,1),(-.755907,1,1)),
        ((1,0,0),(2.92338,1,0),(59.4188,3,0),(20.3225,0,1),(-27.0302,1,1),(222.592,3,1),(121.563,0,3),(626.13,1,3),(316.627,3,3)),
        ((.0365463,0,0),(3.32707,1,0),(9.0632,0,1),(-9.04756,1,1)),
        ((1,0,0),(3.59685,2,0),(-1.36772,3,0),(9.04401,0,1),(-16.3174,2,1),(9.22949,3,1),(5.56589,0,3),(19.7886,2,3),(-20.2123,3,3)))

    def poly(coefficients):
        lo, hi, mass = np.zeros_like(nov), np.zeros_like(nov), np.zeros_like(nov)
        for coefficient, npow, apow in coefficients:
            c = float(np.float32(coefficient))
            left, right = c*n[0]**npow*alpha[0]**apow, c*n[1]**npow*alpha[1]**apow
            if c < 0:
                left, right = right, left
            lo += left; hi += right; mass += np.maximum(abs(left), abs(right))
        return lo-gamma*mass, hi+gamma*mass

    def mul(left, right):
        values = np.stack([l*r for l in left for r in right])
        return values.min(0), values.max(0)

    def ratio(numerator, denominator):
        assert np.all(denominator[0] > 0), 'Independent rational denominator interval must stay positive'
        return mul(numerator, ((1-2.**-21)/denominator[1], (1+2.**-21)/denominator[0]))

    bias, scale = ratio(poly(terms[0]), poly(terms[1])), ratio(poly(terms[2]), poly(terms[3]))
    f_error = (4*eps)/(1-4*eps)*(.04+base*metal)
    f = (np.maximum(0, f0-f_error), np.minimum(1, f0+f_error))
    b = mul((np.maximum(bias[0], 0), np.maximum(bias[1], 0)), (np.clip(f[0][..., 1]*50, 0, 1), np.clip(f[1][..., 1]*50, 0, 1)))
    scaled = mul(f, (np.maximum(scale[0], 0)[..., None], np.maximum(scale[1], 0)[..., None]))
    lo, hi = scaled[0]+b[0][..., None], scaled[1]+b[1][..., None]
    final = (8*eps)/(1-8*eps)*np.maximum(abs(lo), abs(hi))
    diff_error = (3*eps)/(1-3*eps)*abs(diffuse)
    return dict(known=known, point=np.clip(point, 0, 1), spec=(np.clip(lo-final, 0, 1)-unorm, np.clip(hi+final, 0, 1)+unorm),
                diff=(np.clip(diffuse-diff_error, 0, 1)-unorm, np.clip(diffuse+diff_error, 0, 1)+unorm))


def validate(directory, value):
    checks, hashes, wrong_b = 0, {}, 0

    def require(condition, reason):
        nonlocal checks
        assert bool(np.all(condition)), reason
        checks += 1

    def load(frame, name, dtype, shape):
        path = directory / ('frame'+str(frame)+'-'+name+'.bin')
        raw = path.read_bytes();hashes[path.name] = hashlib.sha256(raw).hexdigest()
        require(len(raw) == np.prod(shape)*np.dtype(dtype).itemsize, 'Exact exported GPU footprint: '+name)
        return np.frombuffer(raw, dtype=dtype).reshape(shape)

    enabled = value['enabled']; previous = False
    require(value['debug_errors'] == value['debug_warnings'] == 0, 'Zero actual D3D12 errors and warnings')
    require(len(value['frames']) == value['provider_dispatches'] == 7, 'Exactly seven actual complete signed frames')
    require(value['provider_contexts'] == 1 and value['unexpected_title_transitions'] == 0, 'One physical context and exact allowed borrowed transition set')
    baseline_alpha = None
    for row in value['frames']:
        index = row['frame'];applied = enabled and index in (2, 3, 5, 6, 8)
        require(row['applied'] == applied and row['active'], 'Current actual albedo admission with active signed RR')
        require(row['reset'] == (index == 2 or applied != previous), 'Exact cue-transition RESET policy')
        spec = load(index, 'spec-guide', 'u1', (128, 128, 4));diff = load(index, 'diff-guide', 'u1', (128, 128, 4))
        base = load(index, 'base', '<u4', (128, 128));params = load(index, 'params', 'u1', (128, 128, 4))
        nr = load(index, 'normal', '<u4', (128, 128));converted = load(index, 'converted-normal', '<u4', (128, 128))
        require(np.array_equal((nr >> 20) & 1023, (converted >> 20) & 1023), 'Native normal.B remains exact in actual provider normals')
        if baseline_alpha is None:
            baseline_alpha = spec[..., 3].copy()
        require(np.array_equal(spec[..., 3], baseline_alpha) and np.all(diff[..., 3] == 0), 'Geometry NoV alpha and diffuse alpha stay unchanged')
        if applied:
            material = load(index, 'snapshot', '<f2', (128, 128, 4));g = load(index, 'roughness', '<f2', (128, 128))
            encoded = np.stack([(base >> shift) & 1023 for shift in (0, 10, 20)], -1).astype(np.float32)/np.float32(1023)
            expected = np.concatenate([(encoded*encoded).astype('<f2'), (params[..., :1].astype(np.float32)/np.float32(255)).astype('<f2')], -1)
            require(np.array_equal(material.view('<u2'), expected.view('<u2')), 'Exact actual GPU base-linear/metal pair')
            require(np.array_equal(g.view('<u2'), (params[..., 1].astype(np.float32)/np.float32(255)).astype('<f2').view('<u2')), 'R16F raw G exact RNE from native Params.G')
            bounds = guide_bounds(material, nr, spec, g)
            for actual, interval in ((spec[..., :3]/255, bounds['spec']), (diff[..., :3]/255, bounds['diff'])):
                known = bounds['known'][..., None]
                require(np.where(known, actual >= interval[0], actual == 1), 'Independent exact-G lower bound and categorical white fallback')
                require(np.where(known, actual <= interval[1], actual == 1), 'Independent exact-G upper bound and categorical white fallback')
            require(np.any(spec[..., :3] != 255) and np.any(diff[..., :3] != 255), 'Valid native material must not silently become all-white actual RR guides')
            native_b = ((nr >> 20) & 1023).astype(np.float64)/1023
            wrong = guide_bounds(material, nr, spec, native_b)['spec']
            wrong_b += np.count_nonzero(bounds['known'][..., None] & ((spec[..., :3]/255 < wrong[0]) | (spec[..., :3]/255 > wrong[1])))
            require(row['snapshot_pair_allocation_bytes'] == value['warm_pair_bytes'] > 0, 'Warmed paired allocation equals two independently queried actual resource allocations')
        else:
            require(np.all(spec[..., :3] == 255) and np.all(diff[..., :3] == 255), 'COMMON and explicit OFF are quiet white fallback')
            require(row['source_transitions'] == 0 and row['snapshot_pair_allocation_bytes'] == 0, 'Rejected sources record zero hidden borrowed read transitions or capture pair')
        previous = applied
    require(wrong_b > 0 if enabled else wrong_b == 0, 'Independent old normal.B roughness negative must be rejected when Params.G is available')
    value.update(gpu_payload_sha256=hashes, rejected_wrong_normal_b_components=int(wrong_b), python_checks=checks)
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--output', type=Path, default=Path(os.environ.get('FSRD_GPU_TEST_OUTPUT', 'F:/FSRD/sol_batch/15e-quality/material-params-host')))
    args = parser.parse_args();out = args.output
    os.environ.update(TEMP='F:/FSRD/tmp', TMP='F:/FSRD/tmp', OMP_NUM_THREADS='2', OPENBLAS_NUM_THREADS='2', MKL_NUM_THREADS='2')
    exe, command, kwargs = prepare(out)
    ast.parse(Path(__file__).read_text(encoding='utf-8'))
    if args.prepare_only:
        print(json.dumps(dict(source=str(command[0]), compiler_executed=False, native_executed=False, gpu_executed=False)));return
    compile_cpp(*command, **kwargs)
    modes = {}
    for enabled in (False, True):
        directory = out / ('on' if enabled else 'off');directory.mkdir(exist_ok=True)
        _, peak, elapsed, log = bounded_run([str(exe), str(directory), str(DLL)] + ([] if enabled else ['--off']), directory / 'native_run')
        value = json.loads((directory / 'material-params-host-result.json').read_text(encoding='utf-8'))
        validate(directory, value);value.update(native_log=str(log), elapsed_seconds=elapsed, peak_resident_bytes=peak)
        (directory / 'material-params-host-result.json').write_text(json.dumps(value, indent=2)+'\n', encoding='utf-8');modes['on' if enabled else 'off'] = value
    comparison = dict(modes=modes, python_checks=sum(v['python_checks'] for v in modes.values()), executable_sha256=sha(exe), dll_sha256=sha(DLL))
    (out / 'material-params-host-comparison.json').write_text(json.dumps(comparison, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(result=str(out / 'material-params-host-comparison.json'), python_checks=comparison['python_checks']), indent=2))


if __name__ == '__main__':
    main()
