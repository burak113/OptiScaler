"""NEW immutable V7 guide-only pairs over frozen physical GGX V5 transport.

Both WHITE and CORRECT receive the SAME once-demodulated noisy RGB and every
non-guide byte. The only candidate difference is specular-albedo RGB. Physical
F=1 references and expensive V5 arrays are never overwritten. At r123 corrected
Qs saturates to white, so that pair is a repeatability control, not albedo proof.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np

import fsrd_nrd_rr_corrected_qs as corrected
import fsrd_nrd_rr_ggx_oracle as physical
import fsrd_nrd_rr_ggx_views as old_domain
import fsrd_nrd_rr_material_quality as files
import fsrd_nrd_rr_mirror_oracle as scene


SCHEMA = 'fsrd-corrected-qs-guide-pair-v7'
NATIVE = ('spec','diff','depth','motion','normals','spec_albedo','diff_albedo')
CHECKS = 0


def need(condition,message):
    global CHECKS
    CHECKS += 1
    if not bool(condition):
        raise AssertionError(message)


def link_immutable(destination, source):
    source,destination=Path(source),Path(destination)
    destination.parent.mkdir(parents=True,exist_ok=True)
    if destination.exists():
        need(files.file_sha(destination)==files.file_sha(source),'existing hardlink payload remains immutable')
    else:
        os.link(source,destination)
    need(files.file_sha(destination)==files.file_sha(source),'all shared immutable native payloads verified after hardlink')


def load_frame(root,manifest,frame,names=None):
    names=frame['payloads'] if names is None else names
    derived=set(frame['derived_names'])
    return {name:files.load((root if name in derived else Path(manifest['physical_case']))/'dataset'/frame['directory'],frame['payloads'][name])
            for name in names}


def guide(roughness,no_v):
    words=corrected.corrected_guide(roughness,no_v)
    return np.broadcast_to(words,np.shape(no_v)+(3,)).copy()


def derive(source,destination):
    source,destination=Path(source),Path(destination)
    manifest=json.loads((source/'ggx-sequence.json').read_bytes())
    need(manifest['schema']==physical.SCHEMA and manifest['code'] in (123,307),'frozen physical F1 GGX source, not already-demodulated native title')
    need(not destination.exists() and destination.resolve().is_relative_to(scene.BASE.resolve()),'fresh task-scoped V7 destination; never overwrite frozen V2/V5/V6')
    need(manifest['submitted_frames']==len(manifest['frames'])==64,'complete fixed64-frame source')
    frozen_hash=files.file_sha(source/'ggx-sequence.json')
    destination.mkdir(parents=True)
    views={name:destination/'views'/name for name in ('white','correct')}
    for view in views.values():
        files.immutable(view/'native-replay.txt',(source/'native-replay.txt').read_bytes())
    camera=physical.camera_api()
    frames,quantization=[],[]
    previous_ghost_qs=previous_age=None
    changed=fp32_differences=0
    corrected_hist=np.zeros(256,np.int64)
    previous_hist=np.zeros(256,np.int64)
    minimum_no_v=1.
    for index,frame in enumerate(manifest['frames']):
        data=old_domain.load_frame(source,manifest,frame)
        geometry=physical.frame_geometry(index,camera)
        need(np.array_equal(data['motion'],geometry['motion']),'same immutable quantized primary motion and cohort addressing')
        no_v=geometry['current']['no_v']
        minimum_no_v=min(minimum_no_v,float(no_v.min()))
        rgb8=guide(manifest['roughness'],no_v)
        q=rgb8.astype(np.float64)/255.
        predicted=corrected.unorm8(corrected.reflectance((1.,1.,1.),manifest['roughness'],no_v,np.float32))
        fp32_differences+=int(np.count_nonzero(np.any(predicted!=rgb8,axis=-1)))
        changed+=int(np.count_nonzero(np.any(rgb8!=data['spec_albedo'][...,:3],axis=-1)))
        corrected_hist+=np.bincount(rgb8[...,0].ravel(),minlength=256)
        previous_hist+=np.bincount(data['spec_albedo'][...,0].ravel(),minlength=256)
        need(np.all(q>0) and np.isfinite(q).all(),'corrected quantized Qs strictly positive, no epsilon/zero shortcut')
        native_guide=data['spec_albedo'].copy()
        native_guide[...,:3]=rgb8
        white=native_guide.copy()
        white[...,:3]=255
        need(np.array_equal(native_guide[...,3],data['spec_albedo'][...,3]),'unused guide alpha held identical rather than introducing a second axis')
        new_spec,roundtrip=old_domain.divide_physical(data['spec'],q)
        quantization.append(roundtrip)
        ghost_q=np.ones_like(q)
        age=data['reveal_age']
        new=(age==0)
        carried=(age>0)&(age<=32)
        if index:
            sy,sx=geometry['sy'],geometry['sx']
            need(np.all(previous_age[sy[carried],sx[carried]].astype(int)+1==age[carried]),'historical ghost Q follows exact sealed visibility cohort')
            ghost_q[carried]=previous_ghost_qs[sy[carried],sx[carried]]
        else:
            need(not new.any() and not carried.any(),'first frame has no historical ghost')
        old_rgb8=guide(manifest['roughness'],geometry['previous_visible']['no_v'])
        ghost_q[new]=old_rgb8[new]/255.
        derived=dict(spec=new_spec,spec_albedo=native_guide,white_spec_albedo=white,
            qs_current=q.astype('<f4'),qs_historical_ghost=ghost_q.astype('<f4'))
        for suffix in ('a','b'):
            derived['reference_spec_'+suffix]=(data['reference_spec_'+suffix].astype(np.float64)/q).astype('<f4')
            derived['ghost_spec_'+suffix]=(data['ghost_spec_'+suffix].astype(np.float64)/ghost_q).astype('<f4')
        for prefix in ('reference','ghost'):
            derived[prefix+'_spec']=((derived[prefix+'_spec_a'].astype(np.float64)+derived[prefix+'_spec_b'])*.5).astype('<f4')
        folder=destination/'dataset'/frame['directory']
        payloads=dict(frame['payloads'])
        payloads.update({name:files.put(folder,name+'.bin',value) for name,value in derived.items()})
        for name,view in views.items():
            for field in NATIVE:
                if field=='spec_albedo':
                    path=folder/('white_spec_albedo.bin' if name=='white' else 'spec_albedo.bin')
                elif field=='spec':
                    path=folder/'spec.bin'
                else:
                    path=source/'dataset'/frame['directory']/frame['payloads'][field]['file']
                link_immutable(view/frame['directory']/(field+'.bin'),path)
        for field in NATIVE:
            if field!='spec_albedo':
                need(files.file_sha(views['white']/frame['directory']/(field+'.bin'))==files.file_sha(views['correct']/frame['directory']/(field+'.bin')),
                     'WHITE/CORRECT change no noisy RGB/A, motion, depth, normal or diffuse guide bytes')
        need(np.array_equal(new_spec[...,3].copy().view('<u2'),data['spec'][...,3].copy().view('<u2')),'all actual sampled first-hit/miss half words remain bitexact')
        need(np.all(data['diff_albedo'][...,:3]==255),'diffuse white control fixed; no colored diffuse claim')
        frames.append(dict(frame=frame['frame'],directory=frame['directory'],payloads=payloads,
            derived_names=list(derived),candidate_guide_sha256={name:files.file_sha(view/frame['directory']/'spec_albedo.bin') for name,view in views.items()}))
        previous_ghost_qs,previous_age=ghost_q,age
    hist=lambda value:{str(i):int(n) for i,n in enumerate(value) if n}
    identity_pair=all(frame['candidate_guide_sha256']['white']==frame['candidate_guide_sha256']['correct'] for frame in frames)
    if manifest['code']==123:
        need(identity_pair,'r123 corrected F1 approximation saturates to exact white; predeclared repeatability control')
    else:
        need(not identity_pair,'r307 positive small achromatic guide axis exists')
    need(files.file_sha(source/'ggx-sequence.json')==frozen_hash,'source physical manifest unchanged after derivation')
    result=dict(manifest,schema=SCHEMA,physical_case=str(source),physical_manifest_sha256=frozen_hash,
        frames=frames,views={name:str(view) for name,view in views.items()},
        source_files={**manifest['source_files'],str(Path(__file__)):files.file_sha(Path(__file__)),
            str(Path(corrected.__file__)):files.file_sha(corrected.__file__)},
        correction=corrected.CORRECTION,
        candidate_axis='ONLY specular-albedo RGB; identical once-demod RGB/A and all non-guide bytes',
        signal_definition='new physical synthetic F1 RGB / corrected positive quantizedQs exactly once; never native Recon RGB',
        guide_definition='correct AMD rational F0=1, current actual decoded normal/NoV/r; CPU FP64 directUNORM8-RNE upload choice',
        guide_alpha='unchanged original zero in BOTH candidates; public albedo RGB contract; no NoV-alpha axis',
        hardware_quantization_verified=False,fp32_prediction_differing_pixels=fp32_differences,
        identity_pair=identity_pair,colored_material_test=False,
        remodulation='both candidates multiply actual RRspec by SAME corrected currentQs before physical-reference metrics',
        ghost_definition='old physical radiance / corrected historical visibility-sourceQs, carried with cohort; physical scoring uses untouched physical ghost',
        reference_definition='original physical independent FP32 A/B; derived demod A/B retained, never used to retune gates',
        input_quantization=quantization,minimum_no_v=minimum_no_v,
        changed_legacy_pixels=changed,corrected_code_histogram=hist(corrected_hist),legacy_code_histogram=hist(previous_hist),
        checks=CHECKS,sealed_payload_checks=files.CHECKS,gpu_executed=False,compiler_executed=False)
    files.write_json(destination/'ggx-sequence.json',result)
    print(json.dumps({name:value for name,value in result.items() if name not in ('frames','source_files','input_quantization')},indent=2))
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--physical-case',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    derive(args.physical_case,args.output)


if __name__=='__main__':
    main()
