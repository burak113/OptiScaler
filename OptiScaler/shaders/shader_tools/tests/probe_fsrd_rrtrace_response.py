"""Authenticated RRTrace frozen-source operator attribution, never quality.

Actual source RGB is repeated to examine the native operator on fixed geometry.
These repetitions are NOT independent observations or captured game history.
No synthetic truth constructor, clean-reference metric or acceptance gate exists.
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
from probe_fsrd_additive_split import run_amd, DLL
from probe_fsrd_response_calibration import assert_counterfactual_contract, radiance_fallback
from fsrd_response_pilot import make_spectral_pilot
from fsrd_toolchain import compile_cpp
import run_fsrd_gpu_tests as t

DEFAULT_CAPTURE = Path('F:/Ultra Yedek 2/overwrite/bin/x64/RRTraceCaptures/frame_33098_stage6_3_2898562/capture.json')
DEFAULT_NATIVE_ROI = (0,24,96,64)
SOURCE_NAMES = ('raw_rgba', 'source_diffuse_albedo', 'source_specular_albedo',
                'source_normals', 'rr_linear_depth', 'source_specular_hit_distance')


def validate_native_roi(roi):
    """Conservative probe policy after an observed 80x60 native crash.

    This runner passed 96x64, 128x80 and 256x256 studies. Divisibility by 16
    does not prove all such dimensions supported, and is not an SDK contract.
    Generic source loading and ray-closure tests remain unrestricted by this.
    """
    if len(roi)!=4 or any(not isinstance(v,(int,np.integer)) for v in roi):
        raise ValueError('Native ROI must be integer x,y,width,height')
    if min(roi[2:])<16 or any(v%16 for v in roi[2:]):
        raise ValueError('This research probe conservatively requires native width/height multiples of 16; not a universal SDK constraint')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def crop_transform(full_size, origin, size):
    """Row-vector clip-space transform, preserving the selected pixel rays."""
    fw, fh = full_size; ox, oy = origin; w, h = size
    if min(fw, fh, w, h) <= 0 or min(ox, oy) < 0 or ox+w > fw or oy+h > fh:
        raise ValueError('Crop lies outside its parent extent')
    matrix = np.eye(4)
    matrix[0, 0], matrix[1, 1] = fw/w, fh/h
    matrix[3, 0], matrix[3, 1] = (fw-2*ox-w)/w, (2*oy+h-fh)/h
    return matrix


def load_recorded(metadata, roi=(5,25,80,60), frames=32):
    """Authenticate original bytes before cropping; construct no metric truth."""
    metadata = Path(metadata).resolve(); m = json.loads(metadata.read_text())
    if not m.get('complete') or not m.get('gpu_completion_verified') or m.get('format') != 'rgba32f_le':
        raise ValueError('Require a completed, authenticated FP32 historical capture')
    if not m['settings']['conversion_flags'] & (1 << 2):
        raise ValueError('Capture does not identify packed source roughness')
    if not isinstance(frames, (int, np.integer)) or not 1 <= frames <= 64:
        raise ValueError('Require 1..64 frozen-source repetitions')
    if len(roi) != 4 or any(not isinstance(v, (int, np.integer)) for v in roi):
        raise ValueError('ROI must be integer x,y,width,height')
    arrays = {}; hashes = {}
    for name in SOURCE_NAMES:
        records = [item for item in m['images'] if item['name'] == name]
        if len(records) != 1:
            raise ValueError('Missing or duplicate original payload: '+name)
        record = records[0]; path = (metadata.parent/record['file']).resolve()
        if path.parent != metadata.parent or record['channels'] != 4:
            raise ValueError('Invalid payload location/channel count')
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != record['sha256'] or len(data) != record['width']*record['height']*16:
            raise ValueError('Original payload SHA/size mismatch: '+name)
        arrays[name] = np.frombuffer(data, '<f4').reshape(record['height'], record['width'], 4).copy()
        hashes[name] = record['sha256']
    h, w = arrays['raw_rgba'].shape[:2]
    if any(a.shape != (h,w,4) for a in arrays.values()) or [w,h] != [m['width'],m['height']]:
        raise ValueError('Original payload/capture dimensions differ')
    x, y, cw, ch = roi
    if min(cw,ch) < 8:
        raise ValueError('Spectral support requires at least 8x8 pixels')
    subcrop = crop_transform((w,h), (x,y), (cw,ch))
    fullcrop = crop_transform(m['render_size'], m['origin_xy'], (w,h))
    cropped = {name: a[y:y+ch,x:x+cw].copy() for name,a in arrays.items()}
    if any(not np.isfinite(a).all() for a in cropped.values()):
        raise ValueError('Nonfinite authenticated source; no fabricated replacement')
    raw = cropped['raw_rgba'][...,:3]
    if np.any(raw < 0) or np.any(raw > 65504):
        raise ValueError('Source RGB cannot be represented as nonnegative FP16')
    for name in ('source_diffuse_albedo','source_specular_albedo'):
        if np.any(cropped[name][...,:3] < 0) or np.any(cropped[name][...,:3] > 1):
            raise ValueError('Invalid authenticated albedo: '+name)
    view = np.asarray(m['dispatch']['view'],float).reshape(4,4)
    projection = np.asarray(m['dispatch']['projection'],float).reshape(4,4) @ fullcrop @ subcrop
    jitter = np.asarray(m['dispatch']['jitter'],float)
    bounds = np.asarray(m['dispatch']['depth_bounds'],float)
    if jitter.shape != (2,) or bounds.shape != (2,) or not np.isfinite(np.r_[view.ravel(),projection.ravel(),jitter,bounds]).all() or not 0 <= bounds[0] < bounds[1]:
        raise ValueError('Invalid captured camera/jitter/depth bounds')
    controls = np.zeros((frames,3),np.float32); controls[0,0] = 1; controls[:,1:] = jitter
    observed = np.repeat(raw.astype(np.float16).astype(np.float32)[None],frames,axis=0)
    depth = np.clip(abs(cropped['rr_linear_depth'][...,0]), *bounds).astype(np.float32)
    flags = (1 << 1) | (1 << 4) | (1 << 5) | (m['settings']['conversion_flags'] & (1 << 11))
    camera = [*view.ravel(),*projection.ravel(),*jitter,*bounds]
    overrides = dict(InvViewMatrix=np.linalg.inv(view).ravel(),InvProjMatrix=np.linalg.inv(projection).ravel(),
                     PrevViewMatrix=view.ravel(),NearPlane=float(bounds[0]),FarPlane=float(bounds[1]),
                     JitterOffsets=[*jitter,*jitter],Flags=flags)
    provenance = dict(metadata_path=str(metadata),metadata_sha256=digest(metadata),
        source_payload_sha256=hashes,cropped_payload_sha256={n:hashlib.sha256(a.astype('<f4').tobytes()).hexdigest() for n,a in cropped.items()},
        original_capture_size=[w,h],render_size=m['render_size'],original_origin_xy=m['origin_xy'],
        crop_xywh=list(roi),render_origin_xy=[m['origin_xy'][0]+x,m['origin_xy'][1]+y],
        backend=m.get('backend'),source_frame=m['frame_index'],source_format='Authenticated rgba32f_le',
        operator_source_format='RGB FP16 roundtrip; raw alpha is not radiance input',
        raw_fp16_roundtrip_max_delta=float(abs(observed[0]-raw).max()),
        geometry='Captured normals/roughness/depth/specular hit; fixed camera and zero motion',
        true_game_history=False,independent_observations=False,clean_reference_available=False)
    return dict(observed=observed,source_arrays=cropped,diff=rgba(cropped['source_diffuse_albedo'][...,:3]),
        spec=rgba(cropped['source_specular_albedo'][...,:3]),normals=cropped['source_normals'],
        roughness=cropped['source_normals'][...,3].copy(),depth=depth,
        resources={5:cropped['source_specular_hit_distance'][...,0].copy()},
        motion=np.zeros((ch,cw,4),np.float32),controls=controls,camera=camera,overrides=overrides,
        provenance=provenance)


def guide_correlations(raw, diff, spec):
    records=[]
    for guide in (diff,spec):
        a=raw.reshape(-1,3).astype(float);b=guide[...,:3].reshape(-1,3).astype(float)
        a-=a.mean(0);b-=b.mean(0);den=np.sqrt(np.sum(a*a,0)*np.sum(b*b,0))
        records.append(np.divide(np.sum(a*b,0),den,out=np.zeros(3),where=den>1e-20).tolist())
    return dict(rho_diffuse_specular_rgb=records,nominal_pixels=raw.shape[0]*raw.shape[1],
                effective_independent_pixels=None,interpretation='Current-source association; no physical attribution or independence proof')


def appearance_stats(value):
    # Nonfinite candidate values remain invalid evidence. Record unavailable
    # moments as JSON null rather than hiding them or failing serialization.
    finite=np.isfinite(value);valid_channels=finite.all((0,1,2))
    mean=[];spatial=[];temporal=[]
    for ch in range(3):
        a=value[...,ch]
        mean.append(float(a.mean(dtype=np.float64)) if valid_channels[ch] else None)
        spatial.append(float(a.std((1,2)).mean()) if valid_channels[ch] else None)
        temporal.append(float(a.std(0).mean()) if valid_channels[ch] else None)
    return dict(mean_rgb=mean,spatial_std_rgb=spatial,frozen_operator_temporal_std_rgb=temporal,
        invalid_pixel_fraction=float(np.mean(~np.all(np.isfinite(value)&(value>=0)&(value<=65504),axis=-1))),
        nonfinite_value_fraction=float(np.mean(~finite)),
        minimum=float(value[finite].min()) if finite.any() else None,
        maximum=float(value[finite].max()) if finite.any() else None)


def save_plot(path,raw,baseline,candidate,pilot,rgb_max=.25,delta_max=.05):
    """Fixed linear RGB scales, and fixed signed per-RGB delta scales."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(2,3,figsize=(12,6),constrained_layout=True)
    for ax,value,title in zip(axes[0],(raw,baseline,candidate),('Authenticated source RGB','Native baseline','Signed corrected candidate')):
        ax.imshow(np.clip(value/rgb_max,0,1));ax.set_title(title);ax.axis('off')
    axes[1,0].imshow(np.clip(pilot/rgb_max,0,1));axes[1,0].set_title('Current source-only FFT pilot');axes[1,0].axis('off')
    axes[1,1].imshow(np.clip(.5+.5*(candidate-baseline)/delta_max,0,1))
    axes[1,1].set_title('Candidate − baseline; RGB signed delta');axes[1,1].axis('off')
    axes[1,2].axis('off');axes[1,2].text(0,.9,f'Linear RGB display: 0 to {rgb_max}\nSigned delta display: ±{delta_max}\nDisplay saturation only; arrays remain unclamped.\nFrozen source, not game temporal history.\nChanges are attribution, not quality evidence.',va='top',wrap=True)
    fig.savefig(path,dpi=150);plt.close(fig)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture-metadata',type=Path,default=DEFAULT_CAPTURE)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--frames',type=int,default=32)
    parser.add_argument('--roi',default=','.join(map(str,DEFAULT_NATIVE_ROI)),
                        help='Capture-local x,y,width,height; native dimensions restricted to multiples of 16 by this probe')
    parser.add_argument('--split-strengths',default='0,1')
    parser.add_argument('--radiance-fallback',action='store_true')
    parser.add_argument('--rgb-max',type=float,default=.25)
    parser.add_argument('--delta-max',type=float,default=.05)
    args=parser.parse_args();roi=tuple(map(int,args.roi.split(',')))
    validate_native_roi(roi)
    strengths=list(map(float,args.split_strengths.split(',')))
    if not strengths or len(set(strengths))!=len(strengths) or any(s not in (0,1) for s in strengths):
        raise ValueError('Use distinct split strengths 0 and/or 1')
    if not np.isfinite([args.rgb_max,args.delta_max]).all() or min(args.rgb_max,args.delta_max)<=0:
        raise ValueError('Positive finite fixed display scales required')
    output=args.output.resolve()
    if output.exists():raise ValueError('Use a fresh evidence directory')
    data=load_recorded(args.capture_metadata,roi,args.frames)
    output.mkdir(parents=True);os.environ['OPENBLAS_NUM_THREADS']='1'
    snapshot=output/'source_snapshot';snapshot.mkdir()
    for name in ('probe_fsrd_rrtrace_response.py','fsrd_response_pilot.py','probe_fsrd_response_calibration.py',
                 'probe_fsrd_statistical_resolve.py','probe_fsrd_additive_split.py','fsrd_alpha_common.py',
                 'fsrd_quality_contours.py','fsrd_rr_runner.cpp','fsrd_gpu_runner.cpp','run_fsrd_gpu_tests.py',
                 'verify_fsrd_mirrors.py','fsrd_toolchain.py'):
        source=Path(__file__).with_name(name)
        if not source.exists():source=Path(__file__).parent.parent/name
        shutil.copy2(source,snapshot/name)
    shutil.copy2(args.capture_metadata,output/'original_capture.json')
    np.savez_compressed(output/'authenticated_source_crop.npz',**data['source_arrays'])
    pilot,active,diagnostics=make_spectral_pilot(data['observed'])
    pilot=pilot.astype(np.float16).astype(np.float32)
    identity=shader_identity(t.PRE)
    report=dict(schema='rrtrace-frozen-source-native-response-attribution-v1',status='prepared',
        quality_accepted=False,quality_measured=False,game_run=False,runtime_implemented=False,
        frames=args.frames,roi_xywh=list(roi),split_strengths=strengths,radiance_fallback_registered=args.radiance_fallback,
        native_extent_policy='Conservative probe-only multiples-of-16 restriction; not an SDK constraint or proof of arbitrary extent support',
        previously_successful_native_extents=[[96,64],[128,80],[256,256]],
        git_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=t.ROOT,text=True).strip(),
        working_status=subprocess.check_output(['git','status','--porcelain'],cwd=t.ROOT,text=True),
        production_shaders=identity,native_provider_sha256=digest(DLL),
        source_sha256={p.name:digest(p) for p in snapshot.iterdir()},
        captured_source=data['provenance'],source_crop_npz_sha256=digest(output/'authenticated_source_crop.npz'),
        pilot_diagnostics=diagnostics,guide_correlations=guide_correlations(data['observed'][0],data['diff'],data['spec']),
        display=dict(linear_rgb_max=args.rgb_max,signed_rgb_delta_max=args.delta_max),
        amd_completed_sequences=0,rows=[],
        limitations=['No clean truth or quality/error/acceptance assessment.',
            'The same observed source is repeated; not independent noise or a captured game sequence.',
            'Historical Joint capture is reinterpreted by current conversion and AMD; not an exact game replay.',
            'Frozen camera, zero motion, captured constant jitter; captured camera delta/motion are not replayed.',
            'Floor disabled and detail recovery zero; these settings are operator controls, not the configured game output.',
            'Current-source FFT pilot assumes periodic spatial iid support; actual correlated noise/materials can violate it.',
            'A second AMD context has cost; signed response subtraction can amplify artifacts or become invalid.',
            'Fallback rejects invalid pixels to the exact baseline; it does not repair those pixels.',
            'Null repeats measure observed native variation, not a population confidence bound.'])
    def save():
        (output/'results.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    save()
    try:
        executable=output/'fsrd_rr_runner.exe'
        compile_cpp(Path(__file__).with_name('fsrd_rr_runner.cpp'),executable,('d3d12.lib','dxgi.lib'))
        report['runner_sha256']=digest(executable);report['status']='running';save()
        with GPUWorker(output):
            for strength in strengths:
                folder=output/('split_'+str(int(strength)));folder.mkdir()
                def pack(color):
                    return [convert(rgba(frame),data['diff'],data['spec'],strength,depth=data['depth'],
                        normals=data['normals'],roughness=data['roughness'],motion=data['motion'],
                        overrides=data['overrides'],resources=data['resources']) for frame in color]
                def execute(packed,name):
                    d,s,_=run_amd(folder/name,executable,packed,data['depth'],camera=data['camera'],frame_controls=data['controls'])
                    result=np.stack([compose(p,s[i],d[i],depth=data['depth'],detail=0)[...,:3] for i,p in enumerate(packed)])
                    report['amd_completed_sequences']+=1;save();return result
                packed=pack(data['observed']);baseline=execute(packed,'observed');repeat=execute(packed,'null_repeat')
                pilot_inputs=pack(pilot);assert_counterfactual_contract(packed,pilot_inputs)
                response=execute(pilot_inputs,'pilot')
                candidate=baseline+active[:,None,None,None]*(pilot-response)
                variants={'candidate':candidate};fractions={}
                if args.radiance_fallback:
                    safe,fraction=radiance_fallback(candidate,baseline);variants['candidate_safe']=safe;fractions['candidate_safe']=fraction
                np.savez_compressed(folder/'sequences.npz',observed=data['observed'],pilot=pilot,pilot_response=response,
                    baseline=baseline,null_repeat=repeat,active=active,**variants)
                native={}
                for name in ('observed','null_repeat','pilot'):
                    context=folder/name;manifest=context/'amd_context_identity.json'
                    native[name]=dict(manifest_sha256=digest(manifest),context=json.loads(manifest.read_text()),
                        camera_sha256=digest(context/'camera.txt'),frame_controls_sha256=digest(context/'frame_controls.txt'))
                row=dict(split_strength=strength,conversion_selection='original PSO' if strength==0 else 'enabled additive PSO',
                    source_stats=appearance_stats(data['observed']),baseline_stats=appearance_stats(baseline),pilot_stats=appearance_stats(pilot),
                    null_rms=float(np.sqrt(np.mean((baseline-repeat)**2))),
                    native_contexts=native,sequences_sha256=digest(folder/'sequences.npz'),variants={})
                for name,value in variants.items():
                    delta=value-baseline;finite_delta=bool(np.isfinite(delta).all())
                    row['variants'][name]=dict(appearance=appearance_stats(value),
                        activity=float(np.mean(abs(value-baseline)>1e-5)),
                        candidate_baseline_rms_difference=float(np.sqrt(np.mean(delta**2))) if finite_delta else None,
                        mean_tone_delta_rgb=appearance_stats(delta)['mean_rgb'],
                        fallback_pixel_fraction=fractions.get(name,0),
                        interpretation='Signed change from native baseline; not clean-reference error or quality improvement')
                    save_plot(folder/(name+'_last.png'),data['observed'][-1],baseline[-1],value[-1],pilot[-1],args.rgb_max,args.delta_max)
                    save_plot(folder/(name+'_first.png'),data['observed'][0],baseline[0],value[0],pilot[0],args.rgb_max,args.delta_max)
                report['rows'].append(row);save()
                if shader_identity(t.PRE)!=identity:raise RuntimeError('Production shader mutation invalidates operator evidence')
        report['status']='completed_attribution_not_quality';save();return 0
    except Exception as exc:
        report['status']='failed';report['error']=str(exc);save();raise


if __name__=='__main__':sys.exit(main())
