"""Controlled signed-provider DD/ID and fixed reciprocal RGB-gain research.

Default invocation prepares immutable inputs only. --run compiles and executes
GPU work and MUST be scheduled through lead_ops/run_task_test.py. The original
RR-wrapper regressions are unchanged and remain separate required jobs. Quality
improvement is never an assertion; all six candidate directions are reported.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import struct
import subprocess
import sys
import time

os.environ.update(TEMP='F:/FSRD/tmp', TMP='F:/FSRD/tmp', OMP_NUM_THREADS='2',
                  OPENBLAS_NUM_THREADS='2', MKL_NUM_THREADS='2')
import numpy as np

ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
SCHEMA = 'fsrd-rr-dd-id-reciprocal-gain-v1'
DLL = Path('F:/OptiRevelations/OptiScaler-ffxD-alpha/external/FidelityFX-SDK-v2/Kits/FidelityFX/signedbin/amd_fidelityfx_denoiser_dx12.dll')
DLL_SHA256 = '48f1e5888ba6a0a3d59a98b9751e37c392b0f7b8c223d0082d5c1f40642879d3'
GAINS = (1., .25, 4.)
ROUTES = ('dd', 'id')
GUIDES = ('depth', 'motion', 'normals', 'spec_albedo', 'diff_albedo')
CHECKS = 0


def require(condition, reason):
    global CHECKS
    CHECKS += 1
    if not condition:
        raise AssertionError(reason)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_hash(path):
    return sha(Path(path).read_bytes())


def put(directory, name, value):
    value = np.ascontiguousarray(value)
    data = value.tobytes()
    (directory/name).write_bytes(data)
    return dict(file=name, bytes=len(data), sha256=sha(data), dtype=value.dtype.str,
                shape=list(value.shape))


def write_json(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(value, indent=2, allow_nan=False).encode('utf-8')+b'\n')


def command_log(message):
    path = Path(os.environ.get('FSRD_NRD_RR_COMMAND_LOG', 'E:/FSRD/sol_batch/13c-rr/commands.log'))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as stream:
        stream.write(time.strftime('%Y-%m-%d %H:%M:%S ')+message+'\n')


def generate(directory):
    from fsrd_nrd_quality_replay import sequence
    from test_fsrd_nrd_conversion import projected_depth_cases, reference
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=True)
    values = sequence(128, 128)
    cases = projected_depth_cases(128, 128, focal_scales=[1, .98, 1.02, 1.04, 1.01, 1, 1, 1])[:5]
    require(len(values) == 44, 'shared immutable quality oracle must contain44 frames')
    y, x = np.mgrid[:128, :128]
    interior = (x >= 16) & (x < 112) & (y >= 16) & (y < 112)
    frames, native_lines, previous_depth = [], ['44 128 128'], None
    for index, value in enumerate(values):
        folder = directory/f'frame{value["frame"]:03d}'; folder.mkdir(parents=True, exist_ok=True)
        native = {name: array.copy() for name, array in value['inputs'].items()}
        primary = cases[value['key_pose']]['world_points'].astype(np.float64)
        # Declared SECONDARY ray: normalized world+Z, first secondary-mask
        # intersection is emitter worldZ+1. Reveal occluder is primary-mask-only.
        distance = 1.-primary[..., 2]
        hit = primary.copy(); hit[..., 2] += distance
        require(np.all(np.isfinite(distance[interior])) and np.all(distance[interior] > 0),
                'actual declared secondary first hit is finite and strictly positive')
        require(np.max(np.abs(hit[..., 2][interior]-1.)) <= 1e-12,
                'secondary ray intersects the declared emitter plane')
        require(np.max(np.abs(np.linalg.norm(hit-primary, axis=-1)[interior]-distance[interior])) <= 1e-12,
                'alpha uses SECONDARY Euclidean ray length, not primary VIEWZ')
        alpha = distance.astype('<f2'); alpha[~interior] = np.float16(7.)
        native['diff'][..., 3] = alpha
        require(np.array_equal(native['diff'][..., :3].view('<u2'), value['inputs']['diff'][..., :3].view('<u2')),
                'new secondary-distance manifest retains exact original diffuse noisy RGB')
        require(np.array_equal(native['spec'].view('<u2'), value['inputs']['spec'].view('<u2')),
                'exact original specular packet retained, including disclosed chosen metric alpha5')
        for name in ('nr', 'depth', 'motion'):
            require(native[name].tobytes() == value['inputs'][name].tobytes(), 'original native guides unchanged')
        for signal in ('spec', 'diff'):
            require(np.isfinite(native[signal]).all() and np.all(native[signal][..., 3] > 0),
                    'common noisy signal and every active/padding hit are finite and positive')
            require(np.max(native[signal][..., :3].astype(np.float32)*4) < 65504,
                    'predeclared largest gain cannot clip shared input RGB')
        params = dict(value['params'])
        # Fix baseline guide conditioning for both experimental axes. The scalar
        # reference is independently tested against the production conversion;
        # this fixture does not claim to execute title reconstruction/conversion.
        depth, motion, no_v = reference(native, params, previous_depth, index > 0)
        previous_depth = depth
        spec_albedo = np.full((128, 128, 4), 255, dtype='u1')
        spec_albedo[..., 3] = np.rint(np.clip(no_v, 0, 1)*255).astype('u1')
        diff_albedo = spec_albedo.copy(); diff_albedo[..., 3] = 0
        converted = dict(spec=native['spec'], diff=native['diff'], depth=depth.astype('<f4'),
                         motion=motion.astype('<f2'), normals=(native['nr'] & np.uint32(0x3fffffff)).astype('<u4'),
                         spec_albedo=spec_albedo, diff_albedo=diff_albedo)
        payloads = {name: put(folder, name+'.bin', array) for name, array in converted.items()}
        payloads.update({name: put(folder, name+'.bin', array) for name, array in (
            ('reference_spec', value['reference'][0]), ('reference_diff', value['reference'][1]),
            ('reveal_mask', value['reveal_mask']), ('expected_camera_delta', value['expected_delta']),
            ('primary_world', primary.astype('<f4')), ('secondary_hit_world', hit.astype('<f4')),
            ('secondary_first_distance', distance.astype('<f4')))})
        payloads.update({'native_'+name: put(folder, 'native_'+name+'.bin', array)
                         for name, array in native.items()})
        camera = np.asarray(value['camera'], '<f4')
        view = np.asarray(value['view'], '<f4'); projection = np.asarray(value['projection'], '<f4')
        numeric = [value['frame'], value['key_pose'], value['repeat'], int(params['reset'])]
        numeric += list(view.ravel())+list(projection.ravel())+list(camera)+list(params['jitter'])
        native_lines.append(' '.join(format(float(number), '.9g') for number in numeric))
        frames.append(dict(frame=value['frame'], key_pose=value['key_pose'], repeat=value['repeat'],
                           directory=folder.name, view=view.tolist(), projection=projection.tolist(),
                           camera=camera.tolist(), jitter=list(params['jitter']), reset=bool(params['reset']),
                           payloads=payloads,
                           diffuse_secondary_distance_min=float(alpha[interior].min()),
                           diffuse_secondary_distance_max=float(alpha[interior].max()),
                           original_noisy_rgb_sha256={name: sha(value['inputs'][name][..., :3].tobytes())
                                                     for name in ('spec', 'diff')}))
    native_data=('\n'.join(native_lines)+'\n').encode('ascii')
    (directory/'native-replay.txt').write_bytes(native_data)
    manifest=dict(schema=SCHEMA, width=128, height=128, frames=frames, submitted_frames=44,
                  source_seed=0x13E2026, comparison_crop=[16, 16, 96, 96], gains=list(GAINS), routes=list(ROUTES),
                  native_replay=dict(file='native-replay.txt', bytes=len(native_data), sha256=sha(native_data)),
                  input_domain='same immutable analytic noisy/reflection/checker/thin-detail/camera/reveal oracle from13e',
                  diffuse_alpha=dict(origin='current primary world surface point', normalized_direction=[0, 0, 1],
                                     emitter_plane_z=1., formula='first secondary Euclidean distance=1-primaryWorldZ',
                                     units='declared synthetic world units; no game meters claim',
                                     visibility='primary mask1 sees reveal occluder; secondary mask2 excludes that primary-only occluder and sees sole forward emitter',
                                     guard='excluded nonphysical16-pixel probes receive positive alpha7 padding'),
                  specular_alpha='unchanged chosen synthetic metric5; not an attested specular ray intersection',
                  guide_conditioning=dict(source='independently validated scalar conversion reference',
                                          camera_projected_depth_delta=False, preserve_native_material_ids=False,
                                          normals='exact packed oct RG/roughness B, category A0',
                                          albedos='white linear RGB; spec A is NoV, diffuse A0',
                                          viewZ='RH signed linear depth', motion='UV prev-current XY + pixel jitter delta; legacy previous visibility depth difference Z; W1'),
                  exposure='unity, no SDK exposure field; fixed test-only RGB gain undone before Consumer',
                  timing_scope='GPU gain + real RR staged RGB commit + inverse + original Consumer; no uploads/readbacks/CPU context setup/gameFPS',
                  oracle_sha256=file_hash(HERE/'fsrd_nrd_quality_replay.py'),
                  geometry_sha256=file_hash(HERE/'test_fsrd_nrd_conversion.py'),
                  generator_sha256=file_hash(__file__), native_nrd_paired=False, game_fps_measured=False,
                  scope='controlled synthetic signed-provider research; all noisy lighting passes through RR; no production-default change')
    write_json(directory/'sequence.json', manifest)
    return manifest


def read_manifest(directory):
    from fsrd_nrd_quality_replay import load_payload
    directory = Path(directory)
    manifest = json.loads((directory/'sequence.json').read_text(encoding='utf-8'))
    require(manifest['schema'] == SCHEMA and manifest['submitted_frames'] == 44, 'research manifest schema/history alignment')
    metadata = manifest['native_replay']; data=(directory/metadata['file']).read_bytes()
    require(len(data) == metadata['bytes'] and sha(data) == metadata['sha256'], 'sealed native metadata hash')
    for frame in manifest['frames']:
        require(Path(frame['directory']).name == frame['directory'], 'sealed frame directory is a local basename')
        for payload in frame['payloads'].values():
            load_payload(directory/frame['directory'], payload)
    return manifest


def build(work):
    from fsrd_toolchain import compile_cpp, dxc
    cache = work/'cache'; cache.mkdir(parents=True, exist_ok=True)
    os.environ['FSRD_CPP_CACHE'] = str(cache)
    (work/'pch.h').write_bytes(b'#pragma once\n')
    hashes = {}
    for source, symbol, target in (
            ('nrd_rr_radiance_gain.hlsl', 'RadianceGainShaderBytes', 'radiance_gain_shader.h'),
            ('nrd_bridge_consumer_fixture.hlsl', 'ConsumerShaderBytes', 'consumer_shader.h')):
        shader = work/(Path(source).stem+'.cso')
        command = [str(dxc()), '-T', 'cs_6_2', '-E', 'CSMain', '-O3', '-force-rootsig-ver', 'rootsig_1_0',
                   str(HERE/source), '-Fo', str(shader)]
        command_log('compiler '+repr(command))
        result = subprocess.run(command)
        command_log('compiler exit='+str(result.returncode))
        result.check_returncode()
        data=shader.read_bytes()
        (work/target).write_bytes(('const unsigned char '+symbol+'[] = {'+','.join(map(str, data))+'};\n').encode('ascii'))
        hashes[source]=dict(source_sha256=file_hash(HERE/source), cso_sha256=sha(data))
    exe = work/'fsrd_nrd_rr_conditioning_replay.exe'
    command_log('compile_cpp source='+str(HERE/'fsrd_nrd_rr_conditioning_replay.cpp')+' output='+str(exe))
    try:
        compile_cpp(HERE/'fsrd_nrd_rr_conditioning_replay.cpp', exe, ['d3d12.lib', 'dxgi.lib'],
                    [work, ROOT/'OptiScaler', ROOT/'OptiScaler/include', ROOT/'external/streamline',
                     ROOT/'external/FidelityFX-SDK/ffx-api/include/ffx_api'])
    except Exception:
        command_log('compile_cpp failed'); raise
    command_log('compile_cpp exit=0')
    hashes['executable_sha256']=file_hash(exe)
    hashes['cpp_sha256']=file_hash(HERE/'fsrd_nrd_rr_conditioning_replay.cpp')
    hashes['wrapper_sha256']=file_hash(ROOT/'OptiScaler/shaders/fsrd_preprocess/FSRDNrdBridgeRR_Dx12.cpp')
    hashes['proxy_sha256']=file_hash(HERE/'nrd_bridge_rr_test_support.h')
    hashes['half_helper_sha256']=file_hash(ROOT/'OptiScaler/shaders/fsrd_preprocess/precompile/FSRDNrdSignalEncoding.hlsli')
    return exe, hashes


def run_native(exe, inputs, output, route, gain_value, settings=None, probe=False):
    from test_fsrd_nrd_bridge_rr import bounded_run
    output.mkdir(parents=True, exist_ok=True)
    command = [str(exe), '--sequence', str(inputs), '--output', str(output), '--route', route,
               '--gain', format(gain_value, '.9g')]
    if probe:
        command.append('--probe-defaults')
    else:
        command += ['--settings', str(settings)]
    command_log('native '+repr(command))
    try:
        text, peak, elapsed, log = bounded_run(command, output/'native-result.json')
    except Exception:
        command_log('native failed; preserve negative log at '+str(output)); raise
    command_log('native exit=0 elapsed='+str(elapsed)+' peakWorkingSet='+str(peak))
    require('debug_errors=0 debug_warnings=0' in text, 'strict native GPU debug zero errors AND warnings')
    result=json.loads((output/'native-result.json').read_text(encoding='utf-8'))
    require(result['creates'] == result['destroys'] == 1, 'candidate physically fresh context fully retires after GPU fence')
    require(result['dispatches'] == (1 if probe else 44), 'actual signed-provider complete history sample count')
    require(result['signal_flags'] == (0x30 if route == 'id' else 0x22), 'exact DD-ID plus IS context flags')
    require(result['diffuse_dispatch_type'] == ((0x50000 << 32) | (0x47 if route == 'id' else 0x44)), 'exact actual diffuse dispatch effect-sub-ID')
    require(result['specular_dispatch_type'] == ((0x50000 << 32) | 0x48), 'unchanged actual indirect specular dispatch type')
    require(result['native_debug_dispatches'] == 0 and result['debug_errors'] == result['debug_warnings'] == 0,
            'research contains no diagnostic provider pass or debug warnings')
    result.update(peak_working_set_bytes=peak, elapsed_seconds=elapsed, native_log=str(log))
    return result


def opponent(value):
    value=np.asarray(value, dtype=np.float64)
    return np.stack((value[..., 0]-value[..., 2], value[..., 1]-(value[..., 0]+value[..., 2])*.5), axis=-1)


def moving_chroma_change(output, reference, previous_output, previous_reference, motion, reveal_mask, crop):
    """Same motion warp on output and exact reference; no quality pass threshold."""
    height, width = output.shape[:2]
    y,x=np.mgrid[:height,:width]
    px=x+motion[...,0].astype(np.float64)*width;py=y+motion[...,1].astype(np.float64)*height
    x0=np.floor(px).astype(np.int64);y0=np.floor(py).astype(np.int64)
    cx,cy,cw,ch=crop
    valid=(x>=cx)&(x<cx+cw)&(y>=cy)&(y<cy+ch)&(px>=cx)&(px<cx+cw-1)&(py>=cy)&(py<cy+ch-1)
    valid &= (np.hypot(motion[...,0]*width,motion[...,1]*height)>.25)&~np.asarray(reveal_mask,dtype=bool)
    if not valid.any():
        return dict(moving_chroma_change_pixels=0)
    ax=px[valid]-x0[valid];ay=py[valid]-y0[valid]
    def warp(source):
        source=opponent(source)
        a=source[y0[valid],x0[valid]];b=source[y0[valid],x0[valid]+1]
        c=source[y0[valid]+1,x0[valid]];d=source[y0[valid]+1,x0[valid]+1]
        return ((a*(1-ax)[:,None]+b*ax[:,None])*(1-ay)[:,None]
                +(c*(1-ax)[:,None]+d*ax[:,None])*ay[:,None])
    error=(opponent(output)[valid]-warp(previous_output))-(opponent(reference)[valid]-warp(previous_reference))
    return dict(moving_chroma_change_rmse=float(np.sqrt(np.mean(error*error))),
                moving_chroma_change_bias=float(np.mean(error)), moving_chroma_change_pixels=int(valid.sum()))


def metrics(directory, manifest, run_directory, result):
    from fsrd_nrd_quality_replay import frame_metrics, load_payload
    directory, run_directory = Path(directory), Path(run_directory)
    rows, previous = [], {}
    crop=manifest['comparison_crop'];x,y,width,height=crop
    actual_files={}
    require([f['frame'] for f in result['frames']]==[f['frame'] for f in manifest['frames']],
            'native candidate consumes the exact sealed44-frame history in order')
    for frame in manifest['frames']:
        folder=directory/frame['directory'];output_folder=run_directory/frame['directory'];payload=frame['payloads']
        motion=load_payload(folder,payload['motion']);reveal=load_payload(folder,payload['reveal_mask'])
        world=load_payload(folder,payload['primary_world']);reflection=np.exp(-((world[...,0]-.35)**2/.13+(world[...,1]+.15)**2/.4))
        reflection_mask=reflection[y:y+height,x:x+width]>.35
        signals={};hashes={};per_input={}
        for guide in GUIDES:
            data=(output_folder/('guide_'+guide+'.bin')).read_bytes()
            require(sha(data)==payload[guide]['sha256'], 'actual GPU guide bits exactly match common sealed guide for '+guide)
            per_input[guide]=sha(data)
        for signal, alpha in (('spec',.75),('diff',2.)):
            reference=load_payload(folder,payload['reference_'+signal])
            source=load_payload(folder,payload[signal]);gain_value=result['gain']
            def read(name,dtype='<f2',channels=4):
                data=(output_folder/name).read_bytes()
                value=np.frombuffer(data,dtype=dtype).reshape(128,128,channels)
                require(np.isfinite(value).all(), 'actual research GPU output finite: '+name)
                return value,sha(data)
            output,hashes[signal]=read(signal+'.bin')
            conditioned,per_input[signal]=read('conditioned_'+signal+'.bin')
            staged,hashes['rr_stage_'+signal]=read('rr_stage_'+signal+'.bin')
            committed,hashes['rr_committed_'+signal]=read('rr_committed_'+signal+'.bin')
            consumer,hashes['consumer_'+signal]=read('consumer_'+signal+'.bin','<f4')
            expected=(source[..., :3].astype(np.float32)*gain_value).astype('<f2')
            require(np.array_equal(conditioned[..., :3].view('<u2'),expected.view('<u2')), 'GPU gain RGB exact independent NumPy IEEE half bits')
            require(np.array_equal(conditioned[..., 3].view('<u2'),source[..., 3].view('<u2')), 'GPU gain retains exact native hit-distance alpha')
            require(np.array_equal(staged[..., 3].view('<u2'),source[..., 3].view('<u2')), 'signed SDK staged output preserves source hit-alpha bits')
            expected_inverse=(committed[..., :3].astype(np.float32)/gain_value).astype('<f2')
            require(np.array_equal(output[..., :3].view('<u2'),expected_inverse.view('<u2')), 'GPU inverse exact independent NumPy half RGB bits')
            for packet in (committed,output):
                require(np.all(packet[..., 3].view('<u2')==np.float16(alpha).view('<u2')), 'native opaque destination alpha unchanged by RR or inverse')
            require(np.array_equal(consumer[..., :3],output[..., :3].astype(np.float32)*64), 'actual original Consumer receives reciprocal-inverted RGB with exact factor64/unity exposure')
            require(np.all(consumer[..., 3]==1), 'original Consumer alpha1 independent of native input alphas')
            candidate=frame_metrics(output,reference,crop,reveal)
            noisy=frame_metrics(source,reference,crop,reveal)
            error=output[y:y+height,x:x+width,:3].astype(np.float64)-reference[y:y+height,x:x+width].astype(np.float64)
            chroma_error=opponent(output)[y:y+height,x:x+width]-opponent(reference)[y:y+height,x:x+width]
            candidate['opponent_chroma_rmse']=float(np.sqrt(np.mean(chroma_error*chroma_error)))
            if reflection_mask.any():
                candidate['reflection_rgb_rmse']=float(np.sqrt(np.mean(error[reflection_mask]**2)))
                candidate['reflection_pixels']=int(reflection_mask.sum())
            if signal in previous:
                candidate.update(moving_chroma_change(output,reference,*previous[signal],motion,reveal,crop))
            previous[signal]=(output.copy(),reference.copy())
            unscaled=((source[..., :3].astype(np.float32)*gain_value).astype('<f2').astype(np.float32)/gain_value).astype('<f2')
            quantization=dict(input_gain_inverse_changed_components=int(np.count_nonzero(unscaled.view('<u2')!=source[..., :3].view('<u2'))),
                              input_gain_inverse_rgb_rmse=float(np.sqrt(np.mean((unscaled.astype(np.float64)-source[..., :3].astype(np.float64))**2))))
            signals[signal]=dict(candidate=candidate,noisy_input=noisy,fp16_conditioning=quantization)
        actual_files[frame['frame']]=per_input
        rows.append(dict(frame=frame['frame'],key_pose=frame['key_pose'],repeat=frame['repeat'],
                         signals=signals,output_sha256=hashes,actual_rr_input_sha256=per_input))
    result.update(frames_metrics=rows,input_manifest_sha256=file_hash(directory/'sequence.json'),
                  dll_sha256=file_hash(DLL),actual_rr_inputs=actual_files)
    return result


def summary(runs, manifest):
    effective=[run['effective_words'] for run in runs.values()]
    require(all(value==effective[0] for value in effective), 'all routes and gains use bit-identical effective provider settings')
    require(len({run['dll_sha256'] for run in runs.values()})==1, 'all candidates execute identical signed provider DLL')
    require(len({run['provider_version_id'] for run in runs.values()})==1, 'all candidates select exact same actual AMD1.2 version ID')
    require(len({run['input_manifest_sha256'] for run in runs.values()})==1,
            'all candidate metrics derive from one identical sealed reference/input manifest')
    identity_count=0
    for gain_value in GAINS:
        dd=runs[label('dd',gain_value)];indirect=runs[label('id',gain_value)]
        require(dd['actual_rr_inputs']==indirect['actual_rr_inputs'], 'DD and ID see exact same conditioned RGB/hit-alpha/guide bits')
        identity_count+=44*7
    rows=[]
    for name,run in runs.items():
        frames=run['frames_metrics']; aggregate={}
        for signal in ('spec','diff'):
            selected=[frame['signals'][signal]['candidate'] for frame in frames if frame['repeat']>=4]
            all_values=[frame['signals'][signal]['candidate'] for frame in frames]
            aggregate[signal]={key:float(np.mean([v[key] for v in selected if key in v]))
                               for key in ('rmse','bias','detail_gradient_rmse','opponent_chroma_rmse','reflection_rgb_rmse')}
            for key in ('reveal_rmse','moving_chroma_change_rmse'):
                entries=[v[key] for v in all_values if key in v]
                aggregate[signal][key]=float(np.mean(entries)) if entries else None
        timing={key:float(np.mean([frame[key] for frame in run['frames'][4:]]))
                for key in ('input_gain_ms','rr_stage_commit_ms','inverse_gain_ms','consumer_ms','total_ms')}
        baseline=runs[label('dd',1.)]
        deltas={}
        for signal in ('spec','diff'):
            base=[f['signals'][signal]['candidate'] for f in baseline['frames_metrics'] if f['repeat']>=4]
            deltas[signal]={key:aggregate[signal][key]-float(np.mean([v[key] for v in base if key in v]))
                            for key in ('rmse','detail_gradient_rmse','opponent_chroma_rmse')}
        rows.append(dict(candidate=name,route=run['route'],gain=run['gain'],metrics=aggregate,
                         delta_vs_dd_gain1=deltas,mean_gpu_ms_excluding_first4=timing,
                         checks=run['checks'],peak_working_set_bytes=run['peak_working_set_bytes'],
                         creates=run['creates'],destroys=run['destroys'],dispatches=run['dispatches'],
                         signal_flags=run['signal_flags'],diffuse_dispatch_type=run['diffuse_dispatch_type']))
    return dict(schema=SCHEMA,input_manifest_sha256=runs[label('dd',1.)]['input_manifest_sha256'],
                dll_sha256=runs[label('dd',1.)]['dll_sha256'],provider_version_id=runs[label('dd',1.)]['provider_version_id'],
                paired_actual_input_identities=identity_count,effective_words=effective[0],rows=rows,
                native_nrd_paired=False,game_fps_measured=False,production_default_changed=False,
                quality_direction_asserted=False,scope=manifest['scope'],
                notes=['Metrics report every candidate even when it is worse.',
                       'Synthetic secondary-mask geometry and prescribed radiance do not attest native game decomposition.',
                       'Specular A5 and excluded binding guard are disclosed synthetic metrics/padding.',
                       'FP16 reciprocal quantization is measured; SDK has no exposure field in this API.',
                       'Motion-chroma metric applies the same bilinear UV warp to output and reference, excluding revealed/out-of-crop support.',
                       'Only stepped camera poses and static repeats are tested; continuous game motion and FPS remain unmeasured.'])


def label(route,gain_value):
    return route+'_gain'+format(gain_value,'.9g').replace('.','p')


def previews(directory, manifest, runs, output):
    from fsrd_nrd_quality_replay import load_payload
    from PIL import Image, ImageDraw
    output.mkdir(parents=True,exist_ok=True)
    choices=[next(f for f in reversed(manifest['frames']) if f['key_pose']==0)]
    choices += [next(f for f in manifest['frames'] if f['key_pose']==pose) for pose in (2,4)]
    x,y,width,height=manifest['comparison_crop'];scale=2;paths=[]
    for frame in choices:
        image=Image.new('RGB',(8*width*scale,2*(height*scale+24)+32),(20,20,20));draw=ImageDraw.Draw(image)
        draw.text((4,4),f'Frame{frame["frame"]}, pose{frame["key_pose"]}: same synthetic RGB; fixed gain4 + gamma2.2 preview',fill='white')
        folder=directory/frame['directory']
        for row,signal in enumerate(('spec','diff')):
            values=[load_payload(folder,frame['payloads']['reference_'+signal]),load_payload(folder,frame['payloads'][signal])[...,:3]]
            labels=['Analytic reference '+signal,'Same noisy input '+signal]
            for name in runs:
                data=(directory.parent/name/frame['directory']/(signal+'.bin')).read_bytes()
                values.append(np.frombuffer(data,'<f2').reshape(128,128,4)[...,:3]);labels.append(name+' '+signal)
            for column,(value,caption) in enumerate(zip(values,labels)):
                linear=np.maximum(value[y:y+height,x:x+width].astype(np.float32),0)*4
                display=np.clip(np.power(linear/(1+linear),1/2.2)*255+.5,0,255).astype('u1')
                tile=Image.fromarray(display).resize((width*scale,height*scale),Image.Resampling.NEAREST)
                left,top=column*width*scale,32+row*(height*scale+24)
                image.paste(tile,(left,top+24));draw.text((left+3,top+3),caption,fill='white')
        path=output/f'research-frame{frame["frame"]:03d}.png';image.save(path);paths.append(str(path))
    return paths


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--run',action='store_true',help='compiler/GPU job; mandatory external shared-lock wrapper')
    mode.add_argument('--analyze-only',action='store_true',help='analyze already sealed native results')
    parser.add_argument('--work',type=Path,default=Path(os.environ.get('FSRD_GPU_TEST_OUTPUT','F:/FSRD/sol_batch/13c-rr/tests/conditioning')))
    parser.add_argument('--report',type=Path,default=Path(os.environ.get('FSRD_NRD_RR_REPORT','E:/FSRD/sol_batch/13c-rr/conditioning')))
    args=parser.parse_args();work=args.work;report=args.report
    work.mkdir(parents=True,exist_ok=True);report.mkdir(parents=True,exist_ok=True);inputs=work/'inputs'
    if not args.run and not args.analyze_only:
        manifest=generate(inputs)
        write_json(report/'prepared-inputs.json',dict(schema=SCHEMA,frames=len(manifest['frames']),
                    manifest=str(inputs/'sequence.json'),input_manifest_sha256=file_hash(inputs/'sequence.json'),
                    compiled=False,gpu_executed=False,python_checks=CHECKS,scope=manifest['scope']))
        print(json.dumps(dict(prepared_frames=44,input_manifest_sha256=file_hash(inputs/'sequence.json'),compiled=False,gpu_executed=False)))
        return
    if args.run:
        manifest=generate(inputs);manifest=read_manifest(inputs)
        require(file_hash(DLL)==DLL_SHA256,'installed provider must match independently verified signed AMD1.2 binary')
        exe,hashes=build(work)
        probe=run_native(exe,inputs,work/'defaults_probe','dd',1.,probe=True)
        common_values=np.frombuffer(struct.pack('<8I',*probe['default_words']),dtype='<f4')
        require(np.isfinite(common_values).all(),'signed provider queried common defaults are finite')
        settings=work/'common-settings.txt';settings.write_bytes((' '.join(format(float(v),'.9g') for v in common_values)+'\n').encode('ascii'))
        reloaded=np.fromstring(settings.read_bytes().decode('ascii'),dtype=np.float32,sep=' ')
        require(np.array_equal(reloaded.view('<u4'),common_values.view('<u4')),
                'decimal common settings payload exactly roundtrips all eight queried float32 words')
        write_json(report/'defaults-probe.json',dict(probe=probe,common_values=common_values.tolist(),common_settings_sha256=file_hash(settings),build=hashes))
        runs={}
        for route in ROUTES:
            for gain_value in GAINS:
                name=label(route,gain_value);run=run_native(exe,inputs,work/name,route,gain_value,settings=settings)
                run=metrics(inputs,manifest,work/name,run);run['build']=hashes;run['common_settings_sha256']=file_hash(settings)
                write_json(work/name/'research-result.json',run);write_json(report/(name+'.json'),run);runs[name]=run
    else:
        manifest=read_manifest(inputs)
        runs={label(route,gain_value):json.loads((work/label(route,gain_value)/'research-result.json').read_text(encoding='utf-8'))
              for route in ROUTES for gain_value in GAINS}
    result=summary(runs,manifest);result['python_checks']=CHECKS
    result['preview_paths']=previews(inputs,manifest,runs,report/'images')
    write_json(report/'comparison.json',result)
    print(json.dumps(dict(comparison=str(report/'comparison.json'),python_checks=CHECKS,
                          candidates=len(runs),native_nrd_paired=False,game_fps_measured=False,quality_direction_asserted=False)))


if __name__=='__main__':
    main()
