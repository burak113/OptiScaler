"""Rebuild FSRD shaders, run independent GPU/INI checks, optionally build Release x64.

python OptiScaler/shaders/shader_tools/validate_fsrd.py --quick          (about a minute)
python OptiScaler/shaders/shader_tools/validate_fsrd.py --build          (every suite)
python OptiScaler/shaders/shader_tools/validate_fsrd.py --build --floor-quality
    also runs fresh paired native AMD Floor texture/disocclusion and holdout gates.
Historical A/B is optional: --references <directory of pinned version packages>.

--quick keeps the production contracts: shader mirrors and reproducible artifacts, the CPU
host/lifetime/INI contracts, the core GPU contracts, specialized composition pipelines
against the generic one, signal layouts, unsupported-albedo recovery, the CP2077
regressions and the zero-rough screen acceptance suite. The full run adds the historical
feature-regression and research suites. Suites run in parallel (--jobs) and each reuses
one GPU runner process; the lossless gate and D3D12 debug-layer checks are unchanged.

FSRD_GPU_RUNNER_WORKER=0 restores one runner process per dispatch; FSRD_GPU_RUNNER_CROSSCHECK=1
also runs every dispatch in a fresh process and requires byte-identical outputs (use it
after changing the runner); FSRD_CPP_CACHE=0 rebuilds every native test helper.
"""
from pathlib import Path
import argparse
from concurrent.futures import ThreadPoolExecutor, FIRST_COMPLETED, wait
from datetime import datetime, timezone
import hashlib
import json
import os
import subprocess
import sys
import threading
import time

from fsrd_toolchain import dxc, msbuild, visual_studio

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PRE = ROOT/'OptiScaler/shaders/fsrd_preprocess/precompile'
BASELINE_SHADERS = ('FSRDFloorSeed', 'FSRDFloor', 'FSRDInputConv', 'FSRDOutputComp')
SHADERS = (*BASELINE_SHADERS, 'FSRDFloorSeedCleanLighting', 'FSRDInputConvAdditive', 'RRTraceAdditive',
           'FSRDOutputCompLight', 'FSRDOutputCompNoRecovery',
           'FSRDOutputCompTileLight', 'FSRDOutputCompTileAnchor',
           'FSRDAlbedoTrustEvidence', 'FSRDAlbedoTrustPropagate',
           'FSRDVolumeGather', 'FSRDVolumeAccumulate', 'FSRDVolumeApply', 'FSRDRecoveryVolumeAccumulate', 'FSRDRecoveryVolumeApply', 'FSRDSssPrepare', 'FSRDSssBlur', 'FSRDSkinPrefilter', 'FSRDInputConvSkin', 'FSRDInputConvSkinAdditive', 'FSRDProbeInputs', 'FSRDReference', 'FSRDLeak', 'FSRDAlbedoStabilise', 'FSRDFogStats', 'FSRDFogKappa', 'FSRDFogRank', 'FSRDFogSmooth', 'FSRDFogRoute')
HOST_CORRECTNESS = (
    'test_fsrd_fog_host_contract',
    'test_fsrd_roughness_acceptance', 'test_fsr_output_scaling',
    'test_fsrd_camera_matrices', 'test_fsrd_sr_alignment',
    'test_fsr_upscale_settings', 'test_fsrd_title_linear_depth_extent', 'test_fsr_reactive_masks',
    'test_fsrd_blit_mapping', 'test_fsrd_sr_depth_encode',
    'test_fsrd_toolchain_cache',
)
SUITES = (
    *HOST_CORRECTNESS,
    'test_fsrd_recovery_v2', 'test_fsrd_recovery_volume',
    'test_fsrd_dispatch_chain',
    'test_fsrd_composition_variants',
    'test_fsrd_composition_graph',
    'test_fsrd_signal_modes', 'test_fsrd_unsupported_albedo', 'test_fsrd_unsupported_albedo_skip',
    'test_fsrd_albedo_support', 'test_fsrd_signal_policy',
    'test_fsrd_host_lifetimes',
    'test_fsrd_stage_timings', 'test_fsrd_rr_retry_policy', 'test_fsrd_skin_sss', 'test_fsrd_research',
    'test_fsrd_additive_split',
    'test_fsrd_additive_diagnostics',
    'test_fsrd_additive_capture_reader',
    'test_fsrd_additive_lifetime',
    'test_fsrd_game_trace_capture',
    'test_fsrd_game_trace_v5_reader',
    'test_fsrd_full_bias_guard',
    'test_fsrd_magnifier_lifetime',
    'test_fsrd_allocation_models',
    'test_fsrd_statistical_resolve',
    'test_fsrd_response_pilot',
    'test_fsrd_response_protocol',
    'test_fsrd_response_conditioned_pilot',
    'test_fsrd_response_soft_pilot',
    'test_fsrd_rrtrace_response',
    'run_fsrd_gpu_tests', 'test_fsrd_cp2077_regressions', 'test_fsrd_panel_recovery',
    'test_fsrd_floor_model_contract',
    'test_fsrd_floor_split_contract',
    'test_fsrd_floor_lighting_contract',
    'test_fsrd_textured_reference', 'test_fsrd_volume_handover',
    'test_fsrd_zero_rough_screen', 'test_fsrd_screen_review',
    'test_fsrd_speckle_anchor', 'test_fsrd_patch_handover',
    'test_fsrd_current_colour_contracts',
    'test_fsrd_surface_selection',
    'test_fsrd_stage_diagnostics',
    'test_fsrd_chroma_recovery',
    'test_fsrd_luma_recovery',
    'test_fsrd_blur_evidence',
    'test_fsrd_composition_temporal',
    'test_fsrd_shared_composition',
    'test_fsrd_skip_grain',
    'test_fsrd_screen_only_handover',
    'test_fsrd_volume_visibility',
    'test_fsrd_correlated_grain',
    'test_fsrd_recovery_controls',
    'test_fsrd_specular_noise_return',
    'test_fsrd_recovery_detail_contrast',
    'test_fsrd_animated_recovery', 'test_fsrd_light_anchor_mix',
    'test_fsrd_light_recovery_detail',
    'test_fsrd_demod_risk_view',
    'test_fsrd_small_colour_screen', 'test_fsrd_colour_anchor',
    'test_fsrd_ini_cleanup', 'test_fsrd_reference_integrity',
)
QUICK = (
    *HOST_CORRECTNESS,
    'test_fsrd_dispatch_chain', 'test_fsrd_signal_policy', 'test_fsrd_host_lifetimes',
    'test_fsrd_magnifier_lifetime',
    'test_fsrd_stage_timings', 'test_fsrd_rr_retry_policy', 'test_fsrd_skin_sss', 'test_fsrd_research', 'test_fsrd_ini_cleanup', 'test_fsrd_reference_integrity',
    'test_fsrd_additive_lifetime', 'test_fsrd_game_trace_capture', 'test_fsrd_game_trace_v5_reader',
    'test_fsrd_full_bias_guard',
    'run_fsrd_gpu_tests', 'test_fsrd_composition_variants', 'test_fsrd_composition_graph',
    'test_fsrd_signal_modes', 'test_fsrd_unsupported_albedo', 'test_fsrd_unsupported_albedo_skip',
    'test_fsrd_albedo_support', 'test_fsrd_additive_split', 'test_fsrd_cp2077_regressions',
    'test_fsrd_zero_rough_screen', 'test_fsrd_current_colour_contracts',
    'test_fsrd_floor_model_contract',
    'test_fsrd_floor_split_contract',
    'test_fsrd_floor_lighting_contract',
)
OPTIONAL = {'test_fsrd_small_colour_screen', 'test_fsrd_colour_anchor'}
# Previous suite durations, so the longest start first and the parallel run ends early.
DURATIONS = ROOT/'tools_tmp/fsrd_validation/durations.json'
CPU = {'test_fsrd_dispatch_chain', 'test_fsrd_signal_policy', 'test_fsrd_host_lifetimes', 'test_fsrd_stage_timings', 'test_fsrd_rr_retry_policy', 'test_fsrd_ini_cleanup', 'test_fsrd_reference_integrity', 'test_fsrd_additive_lifetime',
       'test_fsrd_game_trace_capture', 'test_fsrd_game_trace_v5_reader',
       'test_fsrd_magnifier_lifetime',
       'test_fsrd_allocation_models', 'test_fsrd_statistical_resolve', 'test_fsrd_additive_capture_reader',
       'test_fsrd_response_pilot', 'test_fsrd_response_protocol', 'test_fsrd_rrtrace_response',
       'test_fsrd_response_conditioned_pilot', 'test_fsrd_response_soft_pilot'} | set(HOST_CORRECTNESS)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_release_package(dll):
    if not dll.is_file():
        raise RuntimeError(f'Release output missing: {dll}')
    image=dll.read_bytes()
    for name in SHADERS:
        if (PRE/(name+'_Shader.cso')).read_bytes() not in image:
            raise RuntimeError(f'Built DLL does not embed validated {name} bytecode')
    denoiser=dll.parent/'OptiScaler/amd_fidelityfx_denoiser_dx12.dll'
    source=ROOT/'external/FidelityFX-SDK-v2/Kits/FidelityFX/signedbin/amd_fidelityfx_denoiser_dx12.dll'
    if not denoiser.is_file() or digest(denoiser)!=digest(source):
        raise RuntimeError('Release package is missing the validated AMD denoiser DLL')
    for sdk, version in (('FidelityFX-SDK', 'v1'), ('FidelityFX-SDK-v2', 'v2')):
        notice=dll.parent/f'Licenses/FidelityFX_{version}_LICENSE.md'
        if not notice.is_file() or digest(notice)!=digest(ROOT/'external'/sdk/'docs/license.md'):
            raise RuntimeError(f'Release package is missing the FidelityFX {version} license')
    return {'release_dll':{'path':str(dll),'sha256':digest(dll)},
            'denoiser_dll':{'path':str(denoiser),'sha256':digest(denoiser)}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', action='store_true', help='Also build Release x64')
    parser.add_argument('--references', type=Path, help='Parent of baseline/zero_rough_v*/precompile')
    parser.add_argument('--require-references', action='store_true', help='Fail if any historical comparisons are skipped')
    parser.add_argument('--output', type=Path, help='New/empty report directory (default: tools_tmp/fsrd_validation/<timestamp>)')
    parser.add_argument('--dxc', help='Explicit DXC executable')
    parser.add_argument('--msbuild', help='Explicit MSBuild executable')
    parser.add_argument('--lossless-baseline', type=Path,
                        help='Frozen precompile directory: require bit-identical GPU outputs for every fixture')
    parser.add_argument('--quick', action='store_true', help='Only the production contracts (see module help)')
    parser.add_argument('--floor-quality', action='store_true',
                        help='After every suite, run the complete fresh paired native AMD Floor quality protocol')
    parser.add_argument('--jobs', type=int, default=0,
                        help='Suites run at once (default: half the logical CPUs, at most 6; 1 = sequential)')
    args = parser.parse_args()
    jobs = args.jobs if args.jobs > 0 else max(1, min(6, (os.cpu_count() or 2) // 2))
    if args.require_references and args.references is None:
        parser.error('--require-references needs --references')
    if args.floor_quality and args.quick:
        parser.error('--floor-quality requires the full suite; omit --quick')
    out = (args.output or ROOT/'tools_tmp/fsrd_validation'/datetime.now().strftime('%Y%m%d_%H%M%S_%f')).resolve()
    if out.exists() and any(out.iterdir()):
        parser.error(f'Report directory must be new or empty: {out}')
    out.mkdir(parents=True, exist_ok=True)
    temp = out/'temp'; temp.mkdir()
    env = dict(os.environ, PYTHONUNBUFFERED='1', PYTHONDONTWRITEBYTECODE='1', TEMP=str(temp), TMP=str(temp))
    env.pop('FSRD_REFERENCE_ROOT', None)
    env.pop('FSRD_LOSSLESS_BASELINE', None)
    if args.lossless_baseline is not None:
        baseline = args.lossless_baseline.resolve()
        if baseline == PRE.resolve() or any(not (baseline/(s+'_Shader.cso')).is_file() for s in BASELINE_SHADERS):
            parser.error('Lossless baseline must be a separate complete precompile snapshot')
        env['FSRD_LOSSLESS_BASELINE'] = str(baseline)
    if args.references is not None:
        if not args.references.is_dir():
            parser.error(f'Reference root does not exist: {args.references}')
        env['FSRD_REFERENCE_ROOT'] = str(args.references.resolve())
    suites = QUICK if args.quick else SUITES
    report = {'started_utc':datetime.now(timezone.utc).isoformat(), 'python':sys.version,
              'root':str(ROOT), 'references':env.get('FSRD_REFERENCE_ROOT'),
              'lossless_baseline':env.get('FSRD_LOSSLESS_BASELINE'), 'steps':[],
              'profile':'quick' if args.quick else 'full', 'parallel_jobs':jobs,
              'limitations':'Synthetic RR inputs; no AMD model execution or in-game acceptance.'}
    lock = threading.Lock()

    def save():
        with lock:
            text = json.dumps(report, indent=2)
        (out/'summary.json').write_text(text, encoding='utf-8')

    def run(label, command, environment=None):
        with lock:
            print(f'RUN {label}', flush=True)
        started = time.monotonic()
        log = out/(label+'.log')
        with log.open('w', encoding='utf-8') as stream:
            result = subprocess.run([str(a) for a in command], cwd=ROOT, env=environment or env,
                                    stdout=stream, stderr=subprocess.STDOUT)
        row = {'name':label, 'exit_code':result.returncode, 'seconds':time.monotonic()-started,
               'log':str(log), 'status':'passed' if result.returncode==0 else 'failed'}
        with lock:
            report['steps'].append(row)
        return row

    def run_suite(suite):
        # Each suite gets its own environment and output directory; nothing is shared.
        suite_out = out/'suites'/suite
        environment = dict(env, FSRD_GPU_TEST_OUTPUT=str(suite_out/'gpu_tests'))
        row = run(suite, [sys.executable, HERE/'tests'/(suite+'.py')], environment)
        try:
            return checked_suite(suite, suite_out, row)
        except Exception:
            row['status'] = 'failed'
            save()
            raise

    def checked_suite(suite, suite_out, row):
        if row['exit_code']==77 and suite in OPTIONAL:
            row['status']='skipped'
            row['reason']='Historical reference package not supplied; no A/B pass claimed.'
        elif row['exit_code']:
            raise RuntimeError(f'{suite} failed; see {row["log"]}')
        elif suite not in CPU:
            results=list(suite_out.rglob('results.json'))
            if len(results)!=1:
                raise RuntimeError(f'{suite}: expected one fresh result file, found {len(results)}')
            data=json.loads(results[0].read_text(encoding='utf-8'))
            checks=data['checks']; dispatches=data['dispatches']
            if not checks or not dispatches or not all(c['passed'] for c in checks):
                raise RuntimeError(f'{suite}: incomplete or failed result checks')
            if any(int(d.get('debug_layer','0'))!=1 for d in dispatches):
                raise RuntimeError(f'{suite}: install Windows Graphics Tools; D3D12 debug layer is required')
            if any(int(d.get('validation_errors','-1')) != 0 or
                   int(d.get('validation_warnings','-1')) != 0 for d in dispatches):
                raise RuntimeError(f'{suite}: missing or nonzero D3D12 validation diagnostics')
            row.update(checks=len(checks),dispatches=len(dispatches),results=str(results[0]),
                       adapters=sorted({d.get('adapter','unknown') for d in dispatches}),
                       skipped_comparisons=[r for r in data.get('records',[]) if r.get('status')=='skipped'])
        with lock:
            print(row['status'].upper(), suite, f'({row["seconds"]:.0f}s)', flush=True)
        save()
        return row

    def required(label, command):
        row = run(label, command)
        if row['exit_code']:
            raise RuntimeError(f'{label} failed; see {row["log"]}')
        save()
        return row

    try:
        import numpy
        report['numpy'] = numpy.__version__
        compiler = dxc(args.dxc)
        report['dxc'] = str(compiler)
        report['dxc_version'] = subprocess.check_output([str(compiler), '--version'], text=True).strip()
        report['visual_studio'] = str(visual_studio())
        generated = [PRE/(name+suffix) for name in SHADERS for suffix in ('_Shader.cso','_Shader.h')]
        before = {p.name:digest(p) for p in generated}
        required('mirrors', [sys.executable,HERE/'verify_fsrd_mirrors.py'])
        required('shaders', [sys.executable,HERE/'build_fsrd_shader.py','all','--dxc',compiler])
        after = {p.name:digest(p) for p in generated}
        report['generated_hashes'] = after
        changed = [name for name in before if before[name]!=after[name]]
        if changed:
            raise RuntimeError('Generated shaders differ from checked-in artifacts; review/regenerate with the documented DXC before validating: '+', '.join(changed))
        try:
            durations = json.loads(DURATIONS.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            durations = {}
        # Unknown suites first: they may be the longest.
        order = sorted(suites, key=lambda s: -durations.get(s, 1e9))
        failures = []
        with ThreadPoolExecutor(max_workers=jobs + (1 if args.build else 0)) as pool:
            # The DLL embeds the headers just verified, so it can build while tests run.
            build = None
            if args.build:
                builder=msbuild(args.msbuild)
                report['msbuild']=str(builder)
                build = pool.submit(run, 'release_x64', [builder,ROOT/'OptiScaler.sln','/p:Configuration=Release',
                                                         '/p:Platform=x64','/m','/v:minimal','/nologo'])
            pending, running = list(order), {}
            while pending or running:
                # Stop starting suites after a failure; let the running ones finish.
                while pending and len(running) < jobs and not failures:
                    suite = pending.pop(0)
                    running[pool.submit(run_suite, suite)] = suite
                if not running:
                    break
                done, _ = wait(running, return_when=FIRST_COMPLETED)
                for future in done:
                    suite = running.pop(future)
                    try:
                        future.result()
                    except Exception as error:
                        failures.append(str(error))
                        with lock:
                            print('FAILED', suite, flush=True)
            if build is not None:
                row = build.result()
                with lock:
                    print(row['status'].upper(), 'release_x64', f'({row["seconds"]:.0f}s)', flush=True)
                if row['exit_code']:
                    failures.append(f'release_x64 failed; see {row["log"]}')
        try:
            known = json.loads(DURATIONS.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            known = {}
        known.update({r['name']: r['seconds'] for r in report['steps'] if r['status'] == 'passed'})
        DURATIONS.parent.mkdir(parents=True, exist_ok=True)
        DURATIONS.write_text(json.dumps(known, indent=1, sort_keys=True), encoding='utf-8')
        if failures:
            raise RuntimeError('; '.join(failures))
        skipped=[r['name'] for r in report['steps'] if r['status']=='skipped' or r.get('skipped_comparisons')]
        report['historical_comparisons_skipped_in']=skipped
        if any(digest(p)!=after[p.name] for p in generated):
            raise RuntimeError('Shader artifacts changed while tests were running; results cannot validate this build')
        if skipped and args.require_references:
            raise RuntimeError('Required historical comparisons were skipped: '+', '.join(skipped))
        if args.build:
            report.update(validate_release_package(ROOT/'x64/Release/a/OptiScaler.dll'))
        if args.floor_quality:
            required('floor_quality', [sys.executable, HERE/'validate_fsrd_floor_quality.py',
                                      '--candidate-dir', PRE, '--output', out/'floor_quality',
                                      '--python', sys.executable])
            quality_path = out/'floor_quality/results.json'
            quality = json.loads(quality_path.read_text(encoding='utf-8'))
            if quality.get('accepted') is not True or quality.get('completed') is not True:
                raise RuntimeError('Complete Floor quality protocol did not accept the candidate')
            report['floor_quality'] = {'results': str(quality_path), 'sha256': digest(quality_path),
                                      'accepted': True, 'checks': len(quality['checks']),
                                      'native_contexts': len(quality['native_contexts'])}
            report['limitations'] = 'Synthetic scenes with actual signed AMD RR; no in-game acceptance.'
        if any(digest(p)!=after[p.name] for p in generated):
            raise RuntimeError('Shader artifacts changed during the build')
        report['status']='passed'
    except Exception as error:
        report['status']='failed'
        report['error']=str(error)
        print('FAIL:',error,flush=True)
    report['checks']=sum(r.get('checks',0) for r in report['steps'])
    report['dispatches']=sum(r.get('dispatches',0) for r in report['steps'])
    report['finished_utc']=datetime.now(timezone.utc).isoformat()
    save()
    elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(report['started_utc'])).total_seconds()
    print(f'{report["status"].upper()}: {report["checks"]} GPU checks, {report["dispatches"]} dispatches '
          f'in {elapsed:.0f}s ({report["profile"]}, {jobs} parallel); {out/"summary.json"}',flush=True)
    return 0 if report['status']=='passed' else 1


if __name__=='__main__':
    raise SystemExit(main())
