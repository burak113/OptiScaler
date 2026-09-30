"""Eight retained conversion jobs against nonidentity-current-camera references."""
from pathlib import Path
import hashlib, json, sys
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'OptiScaler/shaders/shader_tools/tests'))
from fsrd_alpha_common import convert, shader_identity
from capturing_worker import CapturingGPUWorker
import run_fsrd_gpu_tests as t

CPU_HASH = 'ecc7e766732bcec20afafca571c0327a2ba2dcbd61a095cb4f53d2764f89700a'
WORKER_HASH = '268c956e'  # Full identity is checked against immutable parent below.

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def stats(actual, expected):
    delta = np.asarray(actual, dtype=float)-expected
    loc = np.unravel_index(np.argmax(abs(delta)), delta.shape)
    return dict(exact_equal=bool(np.array_equal(actual, expected)),
                rms=float(np.sqrt(np.mean(delta*delta))), maximum_absolute=float(abs(delta[loc])),
                maximum_location=list(map(int, loc)), differing_values=int(np.count_nonzero(delta)))

def half_tolerance(value):
    value = np.asarray(value, dtype=np.float16)
    upper = np.nextafter(value, np.float16(np.inf)).astype(float)
    lower = np.nextafter(value, np.float16(-np.inf)).astype(float)
    return np.maximum(abs(upper-value), abs(value.astype(float)-lower))+1e-5

def tolerance_check(actual, expected):
    delta = abs(np.asarray(actual, dtype=float)-expected)
    bad = delta > half_tolerance(expected)
    return dict(**stats(actual, expected), within_tolerance=bool(not np.any(bad)),
                failing_values=int(np.count_nonzero(bad)))

def oct_decode(uv):
    xy = np.asarray(uv, dtype=float)*2-1
    normal = np.concatenate((xy, (1-abs(xy).sum(axis=-1))[..., None]), axis=-1)
    fold = np.maximum(-normal[..., 2], 0)[..., None]
    normal[..., :2] += np.where(normal[..., :2]>=0, -fold, fold)
    return normal/np.linalg.norm(normal, axis=-1, keepdims=True)

def angle_check(actual, expected):
    expected = np.asarray(expected, dtype=float)
    expected = expected/np.linalg.norm(expected, axis=-1, keepdims=True)
    dot = np.clip(np.sum(actual*expected, axis=-1), -1, 1)
    angle = np.arccos(dot)
    return dict(maximum_angle_radians=float(angle.max()), rms_angle_radians=float(np.sqrt(np.mean(angle*angle))),
                within_0_003_radians=bool(np.all(angle<=.003)), failing_pixels=int(np.count_nonzero(angle>.003)))

def main():
    folder = Path(__file__).resolve().parent
    out = folder/'evidence'
    if out.exists():
        raise ValueError('Preserve existing current-camera GPU evidence')
    cpu = ROOT/'tools_tmp/current_camera_conformance_20260930'
    rp = cpu/'results.json'
    if sha(rp)!=CPU_HASH:
        raise ValueError('Unexpected frozen CPU reference')
    report = json.loads(rp.read_text())
    parent_worker = ROOT/'tools_tmp/rotating_camera_gpu_capture_20260930/capturing_worker.py'
    worker = folder/'capturing_worker.py'
    if worker.read_bytes()!=parent_worker.read_bytes():
        raise ValueError('Capturing worker must be byte-identical to retained parent')
    for row in report['source_identities']:
        if sha(row['path'])!=row['sha256']:
            raise ValueError('CPU source identity changed: '+row['path'])
    out.mkdir()
    identity = shader_identity(t.PRE)
    result = dict(schema='current-camera-eight-retained-conversion-conformance-v1', status='running',
                  quality_accepted=False, game_run=False, native_RR_dispatches=0, conversion_dispatches=0,
                  CPU_reference_sha256=CPU_HASH, script_sha256=sha(__file__), capture_worker_sha256=sha(worker),
                  byte_identical_capture_parent_path=str(parent_worker), production_shader_identity=identity,
                  rows=[], comparisons=[], limitations=report['scope'])
    def save():
        (out/'results.json').write_text(json.dumps(result, indent=2, allow_nan=False)+'\n')
    save()
    retained = {}
    with CapturingGPUWorker(out):
        for row in report['arms']:
            path = Path(row['payload_path'])
            if sha(path)!=row['payload_sha256']:
                raise ValueError('CPU fixture changed')
            with np.load(path) as f:
                data = {k:f[k].copy() for k in f.files}
            for strength in (0, 1):
                packed = convert(data['raw'], data['diff'], data['spec'], strength,
                                 depth=data['depth'], normals=data['normals'], roughness=data['roughness'],
                                 motion=data['motion'], overrides=row['overrides'], kernel='auto', directory=t.PRE)
                key = f'{row["name"]}_strength{strength}'
                target = out/(key+'.npz')
                np.savez_compressed(target, **{f'packed_{i}':value for i,value in enumerate(packed)})
                normal = oct_decode(packed[3][..., :2])
                rough_error = abs(packed[3][..., 2]-data['roughness'])
                entry = dict(arm=row['name'], strength=strength, fixture_sha256=row['payload_sha256'],
                             overrides=row['overrides'], actual_shader='FSRDInputConv' if strength==0 else 'FSRDInputConvAdditive',
                             payload_path=str(target), payload_sha256=sha(target),
                             expected_converter_motion=tolerance_check(packed[2], data['expected_converter_motion_fp16']),
                             physical_mvz=tolerance_check(packed[2][..., 2], data['physical_mvz']),
                             primary_motion_xy=stats(packed[2][..., :2], data['motion'][..., :2].astype(np.float16).astype(float)),
                             motion_alpha_exact_one=bool(np.all(packed[2][..., 3]==1)),
                             decoded_normal_physical=angle_check(normal, data['world_normal']),
                             decoded_normal_consumed_expected=angle_check(normal, data['expected_converter_world_normal']),
                             raw_oct_diagnostic=stats(packed[3][..., :2], data['expected_normal_R10_decoded'][..., :2]),
                             distinct_oct_encodings=np.unique(packed[3][..., :2].reshape(-1, 2), axis=0).tolist(),
                             roughness_maximum_error=float(rough_error.max()), roughness_within_tolerance=bool(np.all(rough_error<=1/1023+1e-4)),
                             material_id_exact_zero=bool(np.all(packed[3][..., 3]==0)),
                             specular_alpha=tolerance_check(packed[0][..., 3], data['expected_specular_alpha_fp16']),
                             diffuse_alpha_exact_65504=bool(np.all(packed[1][..., 3]==65504)))
                entry['conformance_pass'] = bool(entry['expected_converter_motion']['within_tolerance'] and
                    entry['physical_mvz']['within_tolerance'] and entry['primary_motion_xy']['exact_equal'] and
                    entry['motion_alpha_exact_one'] and entry['decoded_normal_physical']['within_0_003_radians'] and
                    entry['decoded_normal_consumed_expected']['within_0_003_radians'] and entry['roughness_within_tolerance'] and
                    entry['material_id_exact_zero'] and entry['specular_alpha']['within_tolerance'] and entry['diffuse_alpha_exact_65504'])
                retained[key] = packed
                result['rows'].append(entry)
                result['conversion_dispatches'] += 1
                save()
                print(key, 'pass='+str(entry['conformance_pass']), 'MVZ='+str(entry['physical_mvz']['maximum_absolute']),
                      'normal_angle='+str(entry['decoded_normal_physical']['maximum_angle_radians']), flush=True)
    for row in report['arms']:
        a,b = [retained[f'{row["name"]}_strength{s}'] for s in (0,1)]
        result['comparisons'].append(dict(kind='strength0_vs1', arm=row['name'],
                                         packed=[stats(x,y) for x,y in zip(a,b)]))
    for strength in (0,1):
        for mode in ('linear', 'hardware'):
            a,b = [retained[f'{mode}_{space}_strength{strength}'] for space in ('world','view')]
            result['comparisons'].append(dict(kind='world_vs_view', depth_mode=mode, strength=strength,
                                             packed=[stats(x,y) for x,y in zip(a,b)],
                                             decoded_normal=angle_check(oct_decode(a[3][...,:2]), oct_decode(b[3][...,:2]))))
    result['captured_jobs_manifest_sha256'] = sha(out/'persisted_shader_jobs/manifest.json')
    result['worker_stderr_sha256'] = sha(out/'gpu_worker_stderr.log')
    if sha(rp)!=CPU_HASH or shader_identity(t.PRE)!=identity:
        raise ValueError('Frozen reference or production shader changed')
    result['all_eight_conformance_pass'] = all(row['conformance_pass'] for row in result['rows'])
    result['status'] = 'completed_conversion_diagnostic_not_solution'
    save()

if __name__=='__main__':
    main()
