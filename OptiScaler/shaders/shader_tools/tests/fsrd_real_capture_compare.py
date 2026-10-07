"""Compare two frozen pipelines on one genuine captured sequence with actual RR.

Changed native input plans concatenate baseline then candidate in one AMD RR
context, with an explicit reset at the segment boundary. This is two replays of
the same real 128-frame capture, not a new 256-frame game recording. Identical
native input plans reuse the exact verified baseline GPU readback when supplied,
so a composition-only change cannot be confused with native run variance.

Example:
  python fsrd_real_capture_compare.py --capture TRACE/UUID --frames 128
      --baseline-dir FROZEN --baseline-packed-dir BASE_PREPROCESS
      --baseline-readback-dir BASE_HISTORY --candidate-dir FROZEN_CANDIDATE
      --output E:/FSRD/comparison --cases 0:0 0:1 1:0 1:1
"""
from pathlib import Path
import argparse
import copy
import hashlib
import json
import os
import struct

import numpy as np

import fsrd_real_capture_replay as capture


NATIVE_KEYS=('diffuse','specular','depth','motion','normals','diffuse_albedo','specular_albedo')


def identities(directory):
    return {p.name:capture.digest(p) for p in capture.safe_path(directory).iterdir()
            if p.suffix in ('.cso','.hlsl','.hlsli')}


def normalized_preprocessing(cap, gpu, floor, bleed, reset_frames, packed=None):
    if packed is None:
        packed=capture.preprocess(cap,gpu,floor,bleed)
    for frame in sorted({0,*reset_frames,*[i for i,f in enumerate(cap['frame_metadata']) if f['reset']]}):
        if not 0<=frame<len(cap['frame_metadata']):raise ValueError('reset outside sequence')
        single={k:(v[frame:frame+1] if isinstance(v,np.ndarray) else v) for k,v in cap.items()}
        single['frame_metadata']=[cap['frame_metadata'][frame]]
        corrected=capture.preprocess(single,gpu,floor,bleed)
        for name,array in corrected.items():packed[name][frame]=array[0]
    return packed


def cached_preprocessing(root, provenance, hashes, floor, bleed):
    path=capture.safe_path(root)/f'packed_floor{int(floor)}_bleed{int(bleed)}.npz'
    recorded=json.loads(path.with_suffix('.json').read_text())
    sha=recorded.pop('npz_sha256',None)
    expected=dict(capture_manifest_sha256=provenance['capture_manifest_sha256'],frames=provenance['frames'],
                  floor=int(floor),bleed=int(bleed),shader_hashes=hashes)
    if recorded!=expected or sha!=capture.digest(path):raise ValueError('baseline preprocessing cache identity mismatch')
    with np.load(path,allow_pickle=False) as archive:return {k:archive[k] for k in archive.files}


def verified_native_controls(folder,metadata,cap,reset_frames):
    """Bind an exact readback to controls actually applied by the native runner."""
    frames=len(cap['frame_metadata']);w,h=cap['roi']['extent']
    if metadata.get('native_dimensions')!=[w,h] or metadata.get('viewport',{}).get('padded'):
        raise ValueError('baseline native viewport differs from current capture')
    resets=sorted({0,*reset_frames,*[i for i,f in enumerate(cap['frame_metadata']) if f['reset']]})
    if metadata['reset_frames']!=resets:raise ValueError('baseline readback reset plan differs')
    controls=[f['controls'] for f in cap['frame_metadata']]
    projections=np.asarray([c['projection'] for c in controls],np.float64).reshape(-1,4,4)@np.linalg.inv(capture.camera_crop(cap['extent'],cap['roi'])).T
    views=np.asarray([c['view'] for c in controls],np.float32).reshape(-1,4,4)
    projections=projections.astype(np.float32)
    record=struct.Struct('<4I42f')
    path=folder/'dispatch_controls.bin';applied=metadata.get('applied_controls',{})
    if not path.is_file() or applied.get('record_bytes')!=record.size or capture.digest(path)!=applied.get('sha256'):
        raise ValueError('baseline applied native controls digest/layout mismatch')
    blob=path.read_bytes()
    if len(blob)!=frames*record.size:raise ValueError('baseline applied native control frame count differs')
    for frame,value in enumerate(record.iter_unpack(blob)):
        c=controls[frame];scale=c['motion_vector_scale']
        scale=scale+[1] if len(scale)==2 else scale
        delta=[0,0,0] if frame in resets else c['camera_delta']
        expected=np.asarray([*scale,*delta,*c['jitter'],*c['depth_bounds'],*views[frame].ravel(),*projections[frame].ravel()],np.float32)
        if value[:4]!=(frame,2|int(frame in resets),w,h) or not np.array_equal(np.asarray(value[4:],np.float32),expected):
            raise ValueError(f'baseline native camera/jitter/scale/depth controls differ at frame {frame}')
    camera_path=folder/'frame_camera.txt'
    if not camera_path.is_file() or capture.digest(camera_path)!=metadata.get('frame_camera',{}).get('sha256'):
        raise ValueError('baseline requested frame-camera digest differs')


def verified_readback(root, packed, bleed, cap, reset_frames):
    folder=capture.safe_path(root)/'rr'
    metadata=json.loads((folder/'metadata.json').read_text())
    frames=len(cap['frame_metadata'])
    if metadata.get('status')!='passed' or metadata['frames']!=frames or metadata['counters']['dispatches']!=frames:
        raise ValueError('baseline native readback is not a passed complete sequence')
    verified_native_controls(folder,metadata,cap,reset_frames)
    inputs={i['name']:i for i in metadata['logical_inputs']}
    for name in NATIVE_KEYS+(('direct_specular','indirect_diffuse') if bleed else ()):
        if inputs[name]['sha256']!=hashlib.sha256(np.ascontiguousarray(packed[name]).tobytes()).hexdigest():
            raise ValueError('baseline native readback input differs: '+name)
    if metadata['logical_readback_npz']['sha256']!=capture.digest(folder/'readback.npz'):
        raise ValueError('baseline native GPU readback digest mismatch')
    with np.load(folder/'readback.npz',allow_pickle=False) as archive:rr={k:archive[k] for k in archive.files}
    rr['metadata']=metadata
    return rr


def slice_readback(rr,start,count):
    result={k:v[start:start+count] for k,v in rr.items() if k!='metadata'}
    metadata=copy.deepcopy(rr['metadata'])
    metadata['source_joint_frames']=metadata['frames']
    metadata['joint_segment']=[start,start+count]
    metadata['frames']=count
    metadata['reset_frames']=[r-start for r in metadata['reset_frames'] if start<=r<start+count]
    result['metadata']=metadata
    return result


def native_repeat_difference(a,b):
    """Aligned differences for identical native inputs, never a clean target."""
    result={}
    for name in ('diffuse','specular','direct_specular','indirect_diffuse'):
        if name not in a:continue
        first,second=capture.luminance(a[name]),capture.luminance(b[name])
        first,second=first[:,8:-8,8:-8],second[:,8:-8,8:-8]
        delta=second-first
        result[name]=dict(mean_luma_difference=float(delta.mean()),
            luma_difference_rms=float(np.sqrt(np.mean(delta**2))),
            luma_difference_rms_relative_to_baseline_rms=float(np.sqrt(np.mean(delta**2))/
                max(float(np.sqrt(np.mean(first**2))),1e-8)),
            maximum_luma_difference=float(np.max(np.abs(delta))))
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture',type=Path,required=True)
    parser.add_argument('--baseline-dir',type=Path,required=True)
    parser.add_argument('--baseline-packed-dir',type=Path,required=True)
    parser.add_argument('--baseline-readback-dir',type=Path)
    parser.add_argument('--candidate-dir',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--frames',type=int,default=128)
    parser.add_argument('--cases',nargs='+',default=['0:0','0:1','1:0','1:1'])
    parser.add_argument('--reset-frame',type=int,action='append',default=[])
    parser.add_argument('--candidate-old-witness',action='store_true',help='Repeat-baseline controls only; omit for corrected Evidence')
    args=parser.parse_args()
    cases=[]
    for pair in args.cases:
        values=pair.split(':')
        if len(values)!=2 or any(v not in ('0','1') for v in values):
            parser.error('--cases requires Floor:Bleed binary pairs')
        cases.append((pair,*[bool(int(v)) for v in values]))
    output=capture.safe_path(args.output);output.mkdir(parents=True,exist_ok=True)
    baseline=capture.safe_path(args.baseline_dir);candidate=capture.safe_path(args.candidate_dir)
    baseline_hashes,candidate_hashes=identities(baseline),identities(candidate)
    provenance,cap=capture.inspect_capture(args.capture,True,args.frames)
    frames=len(cap['frame_metadata'])
    if any(not 0<=frame<frames for frame in args.reset_frame):parser.error('--reset-frame lies outside the capture')
    os.environ.setdefault('FSRD_VS_ROOT','F:/VisualStudio')
    gpu_exe=output/'build/fsrd_gpu_runner.exe';gpu_exe.parent.mkdir(parents=True,exist_ok=True)
    capture.compile_cpp(capture.HERE/'fsrd_gpu_runner.cpp',gpu_exe,('d3d12.lib','dxgi.lib'))
    rr_exe=capture.native.build_native(output/'build/fsrd_floor_rr_replay.exe')
    report=dict(capture=provenance,baseline_directory=str(baseline),candidate_directory=str(candidate),
                baseline_shader_hashes=baseline_hashes,candidate_shader_hashes=candidate_hashes,cases={})
    for pair,floor,bleed in cases:
        folder=output/f'floor{int(floor)}_bleed{int(bleed)}';folder.mkdir(exist_ok=True)
        a=cached_preprocessing(args.baseline_packed_dir,provenance,baseline_hashes,floor,bleed)
        gpu=capture.Gpu(folder/'baseline_reset_preprocess',baseline,gpu_exe)
        try:a=normalized_preprocessing(cap,gpu,floor,bleed,args.reset_frame,a)
        finally:gpu.close()
        gpu=capture.Gpu(folder/'candidate_preprocess',candidate,gpu_exe)
        try:b=normalized_preprocessing(cap,gpu,floor,bleed,args.reset_frame)
        finally:gpu.close()
        np.savez_compressed(folder/'baseline_packed.npz',**a)
        np.savez_compressed(folder/'candidate_packed.npz',**b)
        keys=NATIVE_KEYS+(('direct_specular','indirect_diffuse') if bleed else ())
        same_inputs=all(np.array_equal(a[k],b[k]) for k in keys)
        rr_a=None
        if same_inputs and args.baseline_readback_dir:
            try:rr_a=verified_readback(args.baseline_readback_dir/folder.name,a,bleed,cap,args.reset_frame)
            except ValueError as error:print('readback_reuse_rejected='+str(error),flush=True)
        if rr_a is not None:
            rr_b=rr_a
            protocol='identical_native_inputs_exact_baseline_readback_reuse'
        else:
            joint_cap=cap.copy()
            joint_cap['frame_metadata']=cap['frame_metadata']+cap['frame_metadata']
            joint={k:np.concatenate((a[k],b[k])) for k in a}
            reset_plan=[frames,*args.reset_frame,*[frames+r for r in args.reset_frame]]
            rr=capture.replay(joint_cap,joint,folder/'rr_joint',rr_exe,bleed,reset_plan)
            rr_a,rr_b=slice_readback(rr,0,frames),slice_readback(rr,frames,frames)
            protocol='one_native_context_two_captured_sequence_segments_reset_at_boundary'
        metrics={}
        for label,packed,rr,shaders,witness in (('baseline',a,rr_a,baseline,False),
                                               ('candidate',b,rr_b,candidate,not args.candidate_old_witness)):
            gpu=capture.Gpu(folder/(label+'_composition'),shaders,gpu_exe)
            try:image,trust=capture.compose(cap,packed,rr,gpu,bleed,witness,floor=floor)
            finally:gpu.close()
            np.savez_compressed(folder/(label+'_final.npz'),image=image,trust=trust)
            metrics[label]=capture.measure(cap,packed,image,trust,args.reset_frame)
            metrics[label]['composition_history']=dict(enabled=floor,write_history=floor,successful_frame_commit=True,
                invalidated_frames=rr['metadata']['reset_frames'])
            metrics[label]['composition_profile']=capture.composition_profile(floor)
            (folder/(label+'_metrics.json')).write_text(json.dumps(metrics[label],indent=2)+'\n')
        result=dict(native_inputs_identical=same_inputs,protocol=protocol,frames_per_segment=frames,
                    captured_sequence_repeated_for_comparison=(rr_a is not rr_b),metrics=metrics)
        result['packed_artifacts']={label:dict(path=str(folder/(label+'_packed.npz')),
            sha256=capture.digest(folder/(label+'_packed.npz'))) for label in ('baseline','candidate')}
        result['native_metadata']=rr_a['metadata']
        if same_inputs:
            result['identical_input_native_repeat_difference']=native_repeat_difference(rr_a,rr_b)
        report['cases'][pair]=result
        (output/'comparison.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(dict(case=pair,protocol=protocol,metrics=metrics),indent=2),flush=True)
    if identities(baseline)!=baseline_hashes or identities(candidate)!=candidate_hashes:
        raise RuntimeError('comparison shader snapshot changed during replay')


if __name__=='__main__':main()
