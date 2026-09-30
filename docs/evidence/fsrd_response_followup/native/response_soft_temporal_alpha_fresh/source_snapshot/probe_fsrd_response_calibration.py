"""Native AMD paired-response research. Never a runtime or game quality claim.

Oracle and blind pilots have separate labels and call paths. The blind estimator
receives observed RGB, source guides and reset controls only. Production shaders
stay unchanged. A second AMD context measures the response to the pilot.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import numpy as np
from fsrd_alpha_common import GPUWorker, convert, compose, rgba, shader_identity
from probe_fsrd_additive_split import run_amd, write_texture, DLL, fixture as recorded_fixture
from probe_fsrd_statistical_resolve import fixture, score, acceptance
from fsrd_quality_contours import island_contours, contour_gate
from fsrd_response_pilot import make_pilot, make_constant_pilot, make_spectral_pilot, make_temporal_spectral_pilot
from fsrd_response_conditioned_pilot import make_dc_conditioned_pilot
from fsrd_response_soft_pilot import make_soft_temporal_spectral_pilot
from fsrd_toolchain import compile_cpp
import run_fsrd_gpu_tests as t


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def research_fixture(scene, w, h, frames, seed):
    """Extra falsifications frozen before their native measurement."""
    if scene == 'flat_lighting_step':
        data = fixture('fake_diffuse', w, h, frames, seed)
        data['truth'][frames//2:] *= 1.6
        return data
    if scene not in ('checker_material', 'weak_material', 'persistent_shared_bias'):
        return fixture(scene, w, h, frames, seed)
    data = fixture('material' if scene != 'persistent_shared_bias' else 'guide_noise', w, h, frames, seed)
    y, x = np.indices((h, w))
    if scene in ('checker_material', 'weak_material'):
        contrast = .15 if scene == 'checker_material' else .0025
        d = .25 + contrast*(2*((x+y) % 2)-1)
        diffuse = np.repeat(d[..., None], 3, axis=-1).astype(np.float32)
        specular = np.full_like(diffuse, .05)
        data['diff'] = np.repeat(rgba(diffuse)[None], frames, axis=0).astype(np.float16).astype(np.float32)
        data['spec'] = np.repeat(rgba(specular)[None], frames, axis=0).astype(np.float16).astype(np.float32)
        truth = .4*(diffuse+specular)+np.array([.08, .07, .055], np.float32)
        data['truth'] = np.repeat(truth[None], frames, axis=0)
    return data


def prepare_capture(metadata, output):
    """Bind original full-ROI source bytes, derived mask and camera metadata.

    A historical capture supplies static guides/geometry, never metric truth or
    independently observed game history. The caller injects synthetic radiance.
    """
    metadata = Path(metadata).resolve()
    m = json.loads(metadata.read_text())
    if not m.get('complete') or not m.get('gpu_completion_verified'):
        raise ValueError('Unfinished historical capture')
    names = ('source_diffuse_albedo', 'source_specular_albedo', 'source_normals',
             'rr_linear_depth', 'source_specular_hit_distance')
    arrays = {}; hashes = {}
    for name in names:
        item = next(v for v in m['images'] if v['name'] == name)
        path = (metadata.parent/item['file']).resolve()
        if path.parent != metadata.parent or item['channels'] != 4:
            raise ValueError('Invalid capture payload location/shape')
        data = path.read_bytes()
        if digest(path) != item['sha256'] or len(data) != item['width']*item['height']*16:
            raise ValueError('Capture SHA/size mismatch: '+name)
        arrays[name] = np.frombuffer(data, '<f4').reshape(item['height'], item['width'], 4).copy()
        hashes[name] = item['sha256']
    shape = arrays[names[0]].shape[:2]
    if any(a.shape[:2] != shape for a in arrays.values()) or min(shape) < 90:
        raise ValueError('Mismatching/small full capture ROI')
    if [m['width'], m['height']] != [shape[1], shape[0]]:
        raise ValueError('Capture metadata/payload dimensions mismatch')
    fw, fh = m['render_size']; ox, oy = m['origin_xy']
    if ox < 0 or oy < 0 or ox+shape[1] > fw or oy+shape[0] > fh:
        raise ValueError('Capture ROI exceeds original render extent')
    mask = np.zeros(shape, bool); mask[25:85, 5:85] = True
    target = output/'captured_source.npz'
    np.savez_compressed(target, **arrays, mask=mask)
    provenance = dict(metadata_path=str(metadata), metadata_sha256=digest(metadata),
                      npz_sha256=digest(target), source_payload_sha256=hashes,
                      mask_sha256=hashlib.sha256(mask.tobytes()).hexdigest(),
                      mask_rectangle_xywh=[5, 25, 80, 60], source_backend=m.get('backend'),
                      frame=m['frame_index'], synthetic_independent_radiance=True,
                      true_game_history=False, full_capture_size=[shape[1], shape[0]])
    return target, provenance


def captured_research_fixture(scene, frames, seed, capture, metadata):
    data = recorded_fixture(scene, frames, seed, capture, metadata)
    for name in ('diff', 'spec'):
        data[name] = np.repeat(data[name][None], frames, axis=0)
    controls = np.zeros((frames, 3), np.float32)
    controls[0, 0] = 1
    controls[:, 1:] = data['camera'][32:34]
    data['controls'] = controls
    data['overrides']['Flags'] = (1 << 1) | (1 << 5) | data['extra_flags']
    return data


def captured_roi_score(value, truth):
    # score excludes a five-pixel margin. Include the real capture halo so its
    # measured RGB/error region is precisely y25:85,x5:85, without edge padding.
    sub = (slice(None), slice(20, 90), slice(0, 90), slice(None))
    return score(value[sub], truth[sub], None)


def radiance_fallback(candidate, baseline):
    """Reject an unrepresentable RGB pixel atomically, preserving baseline.

    No clipping, truth, guides or new history. Rejected pixels are not repaired.
    A baseline with invalid radiance is not evidence of a safe fallback.
    """
    if candidate.shape != baseline.shape:
        raise ValueError('Fallback shape mismatch')
    if not np.all(np.isfinite(baseline) & (baseline >= 0) & (baseline <= 65504)):
        raise ValueError('Invalid baseline cannot serve as radiance fallback')
    valid = np.all(np.isfinite(candidate) & (candidate >= 0) & (candidate <= 65504), axis=-1)
    return np.where(valid[..., None], candidate, baseline), float(np.mean(~valid))


def authenticate_reused_source(context_folder, packed, depth, controls, output):
    """Verify all seven stored native inputs and controls, not just source RGB."""
    manifest_path=context_folder/'amd_context_identity.json'
    m=json.loads(manifest_path.read_text())
    n=len(packed);h,w=depth.shape
    if m['dimensions']!=[w,h] or m['frames']!=n or m['signals']!=[2,32] or m['reset_every']!=0 or m['tuning']!=1 or m['passthrough']!=0:
        raise ValueError('Reused native dispatch configuration mismatch')
    if m['dll_sha256']!=digest(DLL):raise ValueError('Reused provider mismatch')
    expected=''.join(f'{int(r)} {x:.9g} {y:.9g}\n' for r,x,y in controls)
    if (context_folder/'frame_controls.txt').read_text()!=expected:
        raise ValueError('Reused reset/jitter controls mismatch')
    if (context_folder/'camera.txt').exists():raise ValueError('Unexpected camera override in reused evidence')
    arrays=[depth,np.stack([v[2] for v in packed]),np.stack([v[3] for v in packed]),
            np.stack([v[4] for v in packed]),np.stack([v[5] for v in packed]),
            np.stack([v[1] for v in packed]),np.stack([v[0] for v in packed])]
    hashes={}
    for i,(array,fmt) in enumerate(zip(arrays,[41,10,24,28,28,10,10])):
        path=output/f'input{i}.bin'
        write_texture(path,array,fmt);hashes[path.name]=digest(path);path.unlink()
    if hashes!=m['inputs']:raise ValueError('Reused guide/geometry/radiance storage mismatch')
    return dict(native_context=str(manifest_path),manifest_sha256=digest(manifest_path),input_sha256=hashes,
                reset_jitter_sha256=digest(context_folder/'frame_controls.txt'))


def assert_counterfactual_contract(source,pilot):
    for a,b in zip(source,pilot):
        if any(not np.array_equal(a[i],b[i]) for i in (2,3)):
            raise ValueError('Pilot changed motion/geometry')
        if any(not np.array_equal(a[i][...,:3],b[i][...,:3]) for i in (4,5)):
            raise ValueError('Pilot changed consumed albedo RGB')
        if any(not np.array_equal(a[i][...,3],b[i][...,3]) for i in (0,1)):
            raise ValueError('Pilot changed ray/alpha meaning')


def dc_conservation(output, observed, active, controls, history, epochs=None):
    """Single-surface RGB DC constraint, using observations, never metric truth.

    A fixed interior ROI avoids padded boundary pixels. The caller's pilot gate
    rejects transitions; reset boundaries stop the mean's history as well.
    """
    result = output.copy()
    epoch = 0
    for i in range(len(output)):
        if controls[i, 0]:
            epoch = i
        if epochs is not None:
            epoch = max(epoch, int(epochs[i]))
        if active[i] <= 0:
            continue
        lo = max(epoch, i-history+1)
        target = observed[lo:i+1, 5:-5, 5:-5].mean((0, 1, 2), dtype=np.float64)
        actual = output[i, 5:-5, 5:-5].mean((0, 1), dtype=np.float64)
        result[i] += active[i] * (target-actual)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--scenes', default='fake_diffuse,fake_specular,material,wave,guide_noise,moving_light,lighting_step,disocclusion,reset')
    p.add_argument('--size', default='96x64')
    p.add_argument('--frames', type=int, default=32)
    p.add_argument('--seed', type=int, default=290929)
    p.add_argument('--history', type=int, default=16)
    p.add_argument('--noise-sigma', type=float, default=.012)
    p.add_argument('--noise-distribution', choices=('gaussian', 'uniform'), default='gaussian')
    p.add_argument('--split-strength', type=float, default=0,
                   help='0: original conversion PSO control; 1: enabled additive alpha')
    p.add_argument('--reuse-oracle-study', type=Path)
    p.add_argument('--reuse-blind-study', type=Path)
    p.add_argument('--capture-metadata', type=Path,
                   help='Authenticated historical full ROI; synthetic radiance, not game replay')
    p.add_argument('--pilot-mode', choices=('causal', 'constant', 'spectral', 'temporal_spectral', 'dc_conditioned', 'soft_temporal'), default='causal')
    p.add_argument('--skip-oracle', action='store_true')
    p.add_argument('--radiance-fallback', action='store_true',
                   help='Also evaluate whole-RGB baseline fallback for invalid correction pixels')
    a = p.parse_args()
    out = a.output.resolve()
    if out.exists():
        raise ValueError('Use a new evidence directory')
    w, h = map(int, a.size.split('x'))
    if min(w, h) < 32 or a.frames < 24 or not 8 <= a.history <= 64 or not 0 <= a.noise_sigma <= .024 or not 0 <= a.split_strength <= 1:
        raise ValueError('Invalid experiment dimensions/history/noise')
    os.environ['OPENBLAS_NUM_THREADS'] = '1'
    out.mkdir(parents=True)
    snapshot = out/'source_snapshot'
    snapshot.mkdir()
    for name in ('probe_fsrd_response_calibration.py', 'fsrd_response_pilot.py', 'fsrd_response_conditioned_pilot.py', 'fsrd_response_soft_pilot.py',
                 'probe_fsrd_statistical_resolve.py', 'probe_fsrd_additive_split.py',
                 'fsrd_alpha_common.py', 'fsrd_quality_contours.py', 'fsrd_rr_runner.cpp',
                 'fsrd_gpu_runner.cpp', 'run_fsrd_gpu_tests.py', 'verify_fsrd_mirrors.py', 'fsrd_toolchain.py'):
        src=Path(__file__).with_name(name)
        if not src.exists():src=Path(__file__).parent.parent/name
        shutil.copy2(src, snapshot/name)
    identity = shader_identity(t.PRE)
    report = dict(schema='native-paired-response-research-v1', status='running',
                  quality_accepted=False, runtime_implemented=False, game_run=False,
                  git_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=t.ROOT,text=True).strip(),
                  working_status=subprocess.check_output(['git','status','--porcelain'],cwd=t.ROOT,text=True),
                  frames=a.frames, seed=a.seed, size=[w, h], history=a.history,
                  noise_sigma=a.noise_sigma, pilot_mode=a.pilot_mode, native_provider_sha256=digest(DLL),
                  noise_distribution=a.noise_distribution,
                  split_strength=a.split_strength,
                  radiance_fallback_registered=a.radiance_fallback,
                  production_shaders=identity, amd_completed_sequences=0, rows=[],
                  source_sha256={f.name:digest(f) for f in snapshot.iterdir()},
                  limitations=['Oracle uses clean truth, blind pilot never does.',
                               'Global single planar surface; not a bounded local runtime estimator.',
                               'Consecutive source noise independence is fixture provenance, not established in a game.',
                               'Second AMD context has additional cost and lifetime requirements.',
                               'DC constraint requires same-surface correspondence and stable illumination.',
                               'No Floor or upscaler in this experiment.'])
    def save():
        (out/'results.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    save()
    if a.noise_distribution == 'uniform':
        report['limitations'].append('Bounded uniform IID source noise; spectral coefficient Gaussian scale is nominal, not verified confidence.')
    capture = None
    if a.capture_metadata:
        if a.reuse_blind_study or a.reuse_oracle_study:
            raise ValueError('Captured camera studies require fresh native contexts')
        capture, provenance = prepare_capture(a.capture_metadata, out)
        if provenance['full_capture_size'] != [w, h]:
            raise ValueError('--size must match the original full capture ROI')
        report['captured_source'] = provenance
        report['limitations'].append('Frozen historical geometry/zero motion; independently injected Gaussian radiance. No game temporal history.')
        save()
    reused = None
    reuse_dir = a.reuse_blind_study or a.reuse_oracle_study
    if reuse_dir:
        reused = json.loads((reuse_dir/'results.json').read_text())
        if (reused['status'] not in ('completed_oracle_diagnostic_not_solution','completed_research_not_solution') or
            reused['frames'] != a.frames or reused['size'] != [w, h] or reused['seed'] != a.seed or
            reused.get('split_strength', 0) != a.split_strength or
            reused.get('noise_distribution', 'gaussian') != a.noise_distribution or
            reused['native_provider_sha256'] != digest(DLL) or reused['production_shaders'] != identity):
            raise ValueError('Cannot reuse mismatching or incomplete AMD evidence')
        report['reused_report_sha256'] = digest(reuse_dir/'results.json')
    exe = out/'fsrd_rr_runner.exe'
    compile_cpp(Path(__file__).with_name('fsrd_rr_runner.cpp'), exe, ('d3d12.lib', 'dxgi.lib'))
    report['runner_sha256'] = digest(exe)
    try:
      with GPUWorker(out):
       for scene in a.scenes.split(','):
        if scene.startswith('recorded_'):
            if capture is None:
                raise ValueError('Recorded scenes require --capture-metadata')
            data = captured_research_fixture(scene, a.frames, a.seed, capture, a.capture_metadata)
        else:
            data = research_fixture(scene, w, h, a.frames, a.seed)
        rng = np.random.default_rng(a.seed+6131)
        noise = (rng.normal(0, a.noise_sigma, data['truth'].shape) if a.noise_distribution == 'gaussian'
                 else rng.uniform(-np.sqrt(3)*a.noise_sigma, np.sqrt(3)*a.noise_sigma, data['truth'].shape))
        observed = data['truth'] + noise
        if observed.min() < 0:
            raise ValueError('No biased clipping allowed')
        observed = observed.astype(np.float16).astype(np.float32)
        if scene == 'persistent_shared_bias':
            y, x = np.indices((h, w))
            common = .015*np.sin(.33*x+.13*y)[...,None]*np.array([1, .8, .6])
            observed = (observed+common).astype(np.float16).astype(np.float32)
            data['spec'][..., :3] = (.2+.5*common+rng.normal(0,.0002,data['truth'].shape)).astype(np.float16).astype(np.float32)
        if scene == 'guide_noise':
            data['spec'][..., :3] = (.2+.5*(observed-data['truth'])).astype(np.float16).astype(np.float32)
        folder = out/scene
        folder.mkdir()
        def pack(color):
            return [convert(rgba(color[i]), data['diff'][i], data['spec'][i], a.split_strength,
                            depth=data['depth'], normals=data['normals'], roughness=data['roughness'],
                            motion=data.get('motion', [None]*a.frames)[i],
                            overrides=data.get('overrides'), resources=data.get('resources'))
                    for i in range(a.frames)]
        def execute(inputs, name):
            d, s, _ = run_amd(folder/name, exe, inputs, data['depth'], camera=data.get('camera'), frame_controls=data['controls'])
            result = np.stack([compose(v, s[i], d[i], depth=data['depth'], detail=0)[..., :3] for i, v in enumerate(inputs)])
            report['amd_completed_sequences'] += 1
            save()
            return result
        reuse_row = next((r for r in reused['rows'] if r['scene']==scene and r.get('sigma',reused.get('noise_sigma'))==a.noise_sigma), None) if reused else None
        source_inputs = pack(observed)
        oracle = None
        if reuse_row:
            saved_path = reuse_dir/(scene+'_sigma_'+str(a.noise_sigma) if 'sigma' in reuse_row else scene)/'sequences.npz'
            with np.load(saved_path) as saved:
                if not np.array_equal(observed, saved['observed']) or not np.array_equal(data['truth'], saved['clean_reference']):
                    raise ValueError('Reused observed/reference sequence mismatch')
                baseline = saved['baseline'].copy()
                if 'oracle_calibrated' in saved:oracle = saved['oracle_calibrated'].copy()
                elif 'oracle' in saved:oracle = saved['oracle'].copy()
            null_rms = reuse_row['null_rms']
            provenance = dict(reused_npz=str(saved_path), sha256=digest(saved_path))
            context_folder=Path(reuse_row.get('provenance',{}).get('reused_npz') or saved_path).parent/'observed'
            provenance['authenticated_source']=authenticate_reused_source(context_folder,source_inputs,data['depth'],data['controls'],folder)
        else:
            baseline = execute(source_inputs, 'observed')
            repeat = execute(source_inputs, 'null_repeat')
            null_rms = float(np.sqrt(np.mean((baseline-repeat)**2)))
            provenance = dict(reused_npz=None)
        if a.pilot_mode == 'constant':
            pilot, active, diagnostics = make_constant_pilot(observed, require_flat=False)
        elif a.pilot_mode == 'spectral':
            pilot, active, diagnostics = make_spectral_pilot(observed)
        elif a.pilot_mode == 'temporal_spectral':
            pilot, active, diagnostics = make_temporal_spectral_pilot(observed, data['controls'], history=a.history)
        elif a.pilot_mode == 'dc_conditioned':
            pilot, active, diagnostics = make_dc_conditioned_pilot(observed, data['controls'], history=a.history)
        elif a.pilot_mode == 'soft_temporal':
            pilot, active, diagnostics = make_soft_temporal_spectral_pilot(observed, data['controls'], history=a.history)
        else:
            pilot, active, diagnostics = make_pilot(observed, data['diff'][..., :3],
                                                   data['spec'][..., :3], data['controls'], history=a.history)
        pilot = pilot.astype(np.float16).astype(np.float32)
        pilot_inputs=pack(pilot)
        assert_counterfactual_contract(source_inputs,pilot_inputs)
        response = execute(pilot_inputs, 'blind_pilot')
        blind = baseline + active[:, None, None, None]*(pilot-response)
        conserved = dc_conservation(blind, observed, active, data['controls'], a.history,
                                    diagnostics.get('epoch_start_by_frame'))
        prefix = a.pilot_mode if a.pilot_mode != 'causal' else 'blind'
        variants = {prefix:blind, prefix+'_dc':conserved}
        variants[prefix+'_dc_current'] = dc_conservation(blind, observed, active, data['controls'], 1)
        if a.pilot_mode == 'constant':
            flat_pilot, flat_active, flat_diagnostics = make_constant_pilot(observed, require_flat=True)
            if not np.array_equal(flat_pilot.astype(np.float16).astype(np.float32),pilot):
                raise RuntimeError('Flat gate unexpectedly changed pilot/context')
            flat = baseline + flat_active[:,None,None,None]*(pilot-response)
            variants['constant_flat'] = flat
            variants['constant_flat_dc'] = dc_conservation(flat, observed, flat_active, data['controls'], a.history)
            variants['constant_flat_dc_current'] = dc_conservation(flat, observed, flat_active, data['controls'], 1)
            diagnostics['flat_gate'] = flat_diagnostics
            gp, ga, gd = make_constant_pilot(observed, require_flat=True, diff=data['diff'][...,:3],
                                            spec=data['spec'][...,:3], guard_guides=True)
            if not np.array_equal(gp.astype(np.float16).astype(np.float32),pilot):
                raise RuntimeError('Guide veto unexpectedly changed pilot context')
            guided=baseline+ga[:,None,None,None]*(pilot-response)
            variants['constant_flat_guided']=guided
            variants['constant_flat_guided_dc']=dc_conservation(guided, observed, ga, data['controls'], a.history)
            variants['constant_flat_guided_dc_current']=dc_conservation(guided, observed, ga, data['controls'], 1)
            diagnostics['guided_gate']=gd
        if oracle is None and not a.skip_oracle:
            oracle_pilot = data['truth'].astype(np.float16).astype(np.float32)
            oracle_response = execute(pack(oracle_pilot), 'oracle_pilot')
            oracle = baseline+oracle_pilot-oracle_response
        if oracle is not None:
            variants['oracle'] = oracle
        fallback_fractions = {}
        if a.radiance_fallback:
            for name, value in list(variants.items()):
                if name == 'oracle':
                    continue
                safe, fraction = radiance_fallback(value, baseline)
                variants[name+'_safe'] = safe
                fallback_fractions[name+'_safe'] = fraction
        base_full = score(baseline, data['truth'], data['island'])
        base_mature = score(baseline[-16:], data['truth'][-16:], data['island'])
        decisions = {}
        for name, value in variants.items():
            activity = float(np.mean(abs(value-baseline)>1e-5))
            full = score(value, data['truth'], data['island'])
            mature = score(value[-16:], data['truth'][-16:], data['island'])
            fg = acceptance(full, base_full, activity, null_rms, scene)
            mg = acceptance(mature, base_mature, activity, null_rms, scene)
            if not np.isfinite(value).all() or np.any(value < 0):
                for gate in (fg, mg):
                    gate['failures'].append('invalid_radiance')
                    gate['nonregression'] = gate['effective_success'] = False
            contour = None
            if scene.startswith('fake_'):
                cc = island_contours(value, data['truth'])
                bc = island_contours(baseline, data['truth'])
                cg = contour_gate(cc, bc, w, h)
                contour = dict(candidate=cc, baseline=bc, gate=cg)
                if not cg['passed']:
                    for gate in (fg, mg):
                        gate['failures'].append('extended_stain_area')
                        gate['nonregression'] = gate['effective_success'] = False
            decisions[name] = dict(scope='ORACLE diagnostic' if name=='oracle' else 'blind research, not runtime',
                                   full=full, mature=mature, full_gate=fg, mature_gate=mg,
                                   activity=activity, contour=contour,
                                   baseline_fallback_pixel_fraction=fallback_fractions.get(name, 0),
                                   negative_fraction=float(np.mean(value<0)))
        np.savez_compressed(folder/'sequences.npz', observed=observed, pilot=pilot,
                            pilot_response=response, baseline=baseline, clean_reference=data['truth'],
                            active=active, **variants)
        row = dict(scene=scene, baseline_full=base_full, baseline_mature=base_mature,
                   null_rms=null_rms, provenance=provenance, pilot_diagnostics=diagnostics, variants=decisions)
        if scene.startswith('recorded_'):
            region = data['region']
            base_roi = captured_roi_score(baseline, data['truth'])
            base_roi_mature = captured_roi_score(baseline[-16:], data['truth'][-16:])
            roi_null = float(np.sqrt(np.mean((baseline[:,region]-repeat[:,region])**2)))
            roi_null_mature = float(np.sqrt(np.mean((baseline[-16:,region]-repeat[-16:,region])**2)))
            roi_variants = {}
            for k, v in variants.items():
                full = captured_roi_score(v, data['truth'])
                mature = captured_roi_score(v[-16:], data['truth'][-16:])
                activity = float(np.mean(abs(v[:,region]-baseline[:,region])>1e-5))
                roi_variants[k] = dict(full=full, mature=mature,
                    full_gate=acceptance(full,base_roi,activity,roi_null,scene),
                    mature_gate=acceptance(mature,base_roi_mature,activity,roi_null_mature,scene))
                if not np.all(np.isfinite(v[:,region]) & (v[:,region]>=0) & (v[:,region]<=65504)):
                    for key in ('full_gate','mature_gate'):
                        gate=roi_variants[k][key]
                        gate['failures'].append('invalid_radiance')
                        gate['nonregression']=gate['effective_success']=False
            row['recorded_roi'] = dict(baseline_full=base_roi, baseline_mature=base_roi_mature,
                null_rms_full=roi_null, null_rms_mature=roi_null_mature,
                variants=roi_variants, measured_rectangle_xywh=[5,25,80,60],
                fft_phase_halo_xywh=[0,20,90,70],
                scope='synthetic radiance on frozen captured geometry; no game quality acceptance')
        report['rows'].append(row)
        save()
        print(scene, {k:dict(rmse=v['full']['rmse'],full_fail=v['full_gate']['failures'],mature_fail=v['mature_gate']['failures']) for k,v in decisions.items()}, flush=True)
        if shader_identity(t.PRE) != identity:
            raise RuntimeError('Production shader mutation invalidates experiment')
      report['status'] = 'completed_research_not_solution'
      save()
      return 0
    except Exception as e:
      report['status']='failed'
      report['error']=str(e)
      save()
      raise


if __name__ == '__main__':
    sys.exit(main())
