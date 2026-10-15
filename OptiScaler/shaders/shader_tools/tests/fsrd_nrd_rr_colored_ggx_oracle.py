"""NEW V8 physical colored-Schlick GGX experiment, CPU preparation only.

No frozen V2/V5/V6 arrays/sources are changed. Native-style G8 roughness31/255
defines physical transport; the captured guide uses explicit R16F-RNE G, and
RR's normal carries nearest R10 roughness124. Those two quantization errors
are disclosed, not mislabeled an exact equality. No zero-roughness shortcut.

Schlick is integrated per ray: F0*L1+(1-F0)*LFc, Fc=(1-VoH)^5. Reusing an
F=1 image multiplied by a material tint would omit LFc and is not used here.
Runtime candidates receive no reference/ghost masks or oracle-derived gates.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

import numpy as np

import fsrd_nrd_rr_corrected_qs as material
import fsrd_nrd_rr_corrected_qs_views as common
import fsrd_nrd_rr_ggx_oracle as transport
import fsrd_nrd_rr_ggx_sampling as sampling
import fsrd_nrd_rr_material_quality as files
import fsrd_nrd_rr_mirror_oracle as scene


SCHEMA='fsrd-colored-schlick-native-style-material-v8'
G8=31
PHYSICAL_ROUGHNESS=G8/255.
GUIDE_ROUGHNESS=float(material.float32_to_half_rne(np.array([np.float32(G8)/np.float32(255)]))[0])
NORMAL_CODE=int(np.rint(PHYSICAL_ROUGHNESS*1023))
RGB10=np.array([[730,190,100],[110,420,880],[160,790,260],
                [690,690,690],[850,650,190],[180,180,180]],'<u4')
METAL8=np.array([0,255,128,0],dtype='u1')
CHECKS=0


def need(condition,message):
    global CHECKS
    CHECKS+=1
    if not bool(condition):
        raise AssertionError(message)


def material_at(points,object_mask,pose):
    """Exact storage codes, world-fixed background/object-local translating tile.

    All tiles are prescribed independently of light/noise/reference, and every
    tile is native category0. No private title material-model inference is made.
    """
    points=np.asarray(points,np.float64)
    moving=np.asarray(object_mask,bool)
    local=points-np.where(moving[...,None],np.asarray(pose['center']),0.)
    u,v=local@scene.TANGENT,local@scene.BITANGENT
    x=np.floor((u+.1732050807568877)*1.25).astype(np.int64)
    y=np.floor((v-.2718281828459045)*1.25).astype(np.int64)
    color=np.mod(x+3*y+2*moving,len(RGB10))
    mx=np.floor((u+.3141592653589793)*.7).astype(np.int64)
    my=np.floor((v+.1414213562373095)*.9).astype(np.int64)
    metal_index=np.mod(mx-my+moving,len(METAL8))
    rgb,metal=RGB10[color],METAL8[metal_index]
    packet=material.captured_material(rgb,metal)
    f0=.04*(1-packet[...,3:].astype(np.float64))+packet[...,:3].astype(np.float64)*packet[...,3:].astype(np.float64)
    qd=packet[...,:3].astype(np.float64)*(1-packet[...,3:].astype(np.float64))
    return dict(rgb10=rgb,metal8=metal,base_metal=packet,f0=f0,qd=qd,
        material_id=(color+len(RGB10)*metal_index+24*moving).astype('u1'))


def schlick_fc(vo_h):
    return (1-np.clip(vo_h,0.,1.))**5


def combine(l1,lfc,f0):
    return f0*l1+(1-f0)*lfc


def integrate_moments(points,to_camera,pose,roughness,samples,seed):
    """Same independent NDF maps/seeds as frozen V5; new L1 AND LFc at new r.

    Sum order for L1 deliberately matches frozen integrate_reference, allowing
    an exact stored-FP32 replay check at its old r without calling bad Qs code.
    Only one1024x64 ray tile is resident. A/B shifts and noisy rays remain
    independent; moments share samples within each replica as required by the
    linear Schlick decomposition, rather than treating them as independent.
    """
    shape=points.shape[:-1]
    points=np.asarray(points,np.float64).reshape(-1,3)
    view=np.asarray(to_camera,np.float64).reshape(-1,3)
    shifts=np.random.default_rng(seed).random((len(points),2))
    base=sampling.reference_points(samples)
    l1=np.zeros((len(points),3),np.float64)
    lfc=np.zeros_like(l1)
    misses=invalid=0
    for first in range(0,len(points),transport.PIXEL_BATCH):
        stop=min(first+transport.PIXEL_BATCH,len(points))
        origin=points[first:stop,None,:]+scene.NORMAL*transport.RAY_ORIGIN_OFFSET
        v=view[first:stop,None,:]
        total=np.zeros((stop-first,3),np.float64)
        total_fc=np.zeros_like(total)
        for begin in range(0,samples,transport.SAMPLE_BATCH):
            xi=np.mod(base[None,begin:begin+transport.SAMPLE_BATCH,:]+shifts[first:stop,None,:],1.)
            sample=sampling.ndf_reference(v,roughness,xi)
            ray=transport.nearest_emission(origin,sample['direction'],pose)
            contribution=ray['radiance']*sample['weight'][...,None]
            fc=schlick_fc(sample['vo_h'])
            if not np.isfinite(contribution).all() or not np.isfinite(fc).all():
                raise AssertionError('finite physical Schlick moments required')
            total+=np.sum(contribution,axis=1)
            total_fc+=np.sum(contribution*fc[...,None],axis=1)
            misses+=int(np.count_nonzero(ray['miss']))
            invalid+=int(np.count_nonzero(sample['no_l']<=0))
        l1[first:stop]=total/samples
        lfc[first:stop]=total_fc/samples
    need(np.all(lfc>=0) and np.all(lfc<=l1+2e-16),'Schlick Fc moment nonnegative and bounded by exact same L1 samples')
    return l1.reshape(shape+(3,)),lfc.reshape(shape+(3,)),dict(samples=samples,rays=len(points)*samples,
        explicit_range_misses=misses,below_hemisphere_zero_contributions=invalid)


def noisy_physical(points,to_camera,pose,roughness,xi,f0):
    sample=sampling.bounded_vndf(to_camera,roughness,xi)
    ray=transport.nearest_emission(points+scene.NORMAL*transport.RAY_ORIGIN_OFFSET,sample['direction'],pose)
    l1=ray['radiance']*sample['weight'][...,None]
    lfc=l1*schlick_fc(sample['vo_h'])[...,None]
    colored=combine(l1,lfc,f0)
    rgba=np.concatenate((colored,ray['distance'][...,None]),axis=-1).astype('<f2')
    need(np.isfinite(rgba).all() and np.all(rgba[...,3]>0),'positive true nearest-hit/miss A; every noisy Schlick lighting sample will enter RR')
    return rgba,sample,ray,l1,lfc


def guides(cues,no_v):
    qs=material.unorm8(material.reflectance(cues['f0'],GUIDE_ROUGHNESS,no_v))
    qd=material.unorm8(cues['qd'])
    need(np.all(qs>0),'chosen colored materials keep every specular guide channel positive')
    return qs,qd


def divide_rgb(physical_rgba,q,zero_extension=None):
    q=np.asarray(q,np.float64)
    source=np.asarray(physical_rgba,'<f2')
    result=source.copy()
    if zero_extension is None:
        need(np.all(q>0),'strict positive demod denominator; no epsilon or arbitrary sentinel')
        rgb=source[...,:3].astype(np.float64)/q
    else:
        zeros=q==0
        need(np.all(source[...,:3][zeros]==0),'zero-Qd channels are exactly zero physical diffuse radiance')
        rgb=np.asarray(zero_extension,np.float64).copy()
        np.divide(source[...,:3].astype(np.float64),q,out=rgb,where=~zeros)
    result[...,:3]=rgb.astype('<f2')
    need(np.array_equal(result[...,3].copy().view('<u2'),source[...,3].copy().view('<u2')),'RGB-only demod preserves all actual first-hit/miss alpha words')
    need(np.isfinite(result).all(),'finite once-demod actual noisy inputs')
    return result


def configuration(samples):
    dependencies=(Path(__file__),Path(material.__file__),Path(common.__file__),Path(transport.__file__),
        Path(sampling.__file__),Path(files.__file__),Path(scene.__file__),transport.CAMERA_SOURCE)
    return dict(schema=SCHEMA,width=scene.WIDTH,height=scene.HEIGHT,count=scene.COUNT,
        physical_perceptual_roughness=PHYSICAL_ROUGHNESS,guide_native_g8=G8,
        guide_captured_half_roughness=GUIDE_ROUGHNESS,rr_normal_r10_code=NORMAL_CODE,
        rr_normal_perceptual_roughness=NORMAL_CODE/1023.,
        physical_vs_rr_roughness_delta=NORMAL_CODE/1023.-PHYSICAL_ROUGHNESS,
        physical_vs_guide_roughness_delta=GUIDE_ROUGHNESS-PHYSICAL_ROUGHNESS,
        source_files={str(p):files.file_sha(p) for p in dependencies},
        rgb10_palette=RGB10.tolist(),metal8_palette=METAL8.tolist(),
        input_seed=transport.INPUT_SEED,reference_seeds=list(transport.REFERENCE_SEEDS),
        reference_samples_per_replica=samples,reference_replicas=2,input_spp=1,
        physical_specular_definition='Schlick F0*L1+(1-F0)*LFc; L1=integral Le*D*SmithV*NoL; LFc=same with (1-VoH)^5',
        noisy_sampling='one bounded-VNDF ray; matching physical BRDF*cos/pdf, no synthetic intensity/chroma multiplier',
        reference_sampling='two independent NDF inverse-CDF QMC replicas; independent per-pixel shifts, identical declared maps/seeds to V5',
        material_storage='chosen exact RGB10 sqrt-base codes and metalR8; FP32 decode RGB^2 -> integer IEEE RNE half packet, F0/Qd computed consistently from that packet',
        guide_storage='correct AMD rational with native G half; FP64 independent matrix -> chosen directUNORM8-RNE upload words, no extra FP16 conversion',
        guide_hardware_quantization_verified=False,
        diffuse_model='independent analytic Lambertian unit direct field times Qd; no injected diffuse noise; not an energy-conserving joint layered-BSDF claim',
        native_recon_parity_claimed=False,synthetic_only=True,zero_roughness_used=False,
        ray_origin_offset=transport.RAY_ORIGIN_OFFSET,ray_min=transport.RAY_MIN,ray_max=transport.RAY_MAX,
        miss_distance=transport.MISS_DISTANCE,normal=scene.NORMAL.tolist(),
        candidate_axis='WHITE vs ACTUAL only albedo-guide RGB; same once-demod RGB/A, primary surface MV, depth and normal',
        remodulation='both candidates use SAME chosen actual current quantized Qs/Qd for physical-domain metrics; never change Consumer exposure to prefer one',
        zero_qd_definition='metal1 Qd0 has exactly zero physical diffuse; define demod by continuous unit-direct extension, identical for both candidates',
        oracle_runtime_access=False,production_changes=False)


def frame(root,index,samples,config,camera):
    prefix=f'frame{index+2:03d}'
    folder=root/'dataset'/prefix
    info_path=folder/'frame.json'
    digest=files.sha(json.dumps(config,sort_keys=True).encode())
    if folder.exists():
        need(info_path.exists(),'do not overwrite incomplete/negative frame evidence; choose a fresh destination')
        old=json.loads(info_path.read_bytes())
        need(old['config_sha256']==digest,'complete chunk reuse requires exact immutable source/config SHA')
        return old
    folder.mkdir(parents=True)
    geom=transport.frame_geometry(index,camera)
    current,pose,old_pose=geom['current'],geom['pose'],geom['previous_pose']
    cues=material_at(current['point'],current['object'],pose)
    previous_cues=material_at(geom['previous_point'],current['object'],old_pose)
    need(np.array_equal(cues['base_metal'].view('<u2'),previous_cues['base_metal'].view('<u2')),'same moving/static material point has exact captured cues in prior pose')
    xi=np.random.default_rng(transport.INPUT_SEED+index).random((scene.HEIGHT,scene.WIDTH,2))
    physical_spec,sample,ray,_,_=noisy_physical(current['point'],-current['direction'],pose,PHYSICAL_ROUGHNESS,xi,cues['f0'])
    refs,moments,ref_info=[],{},[]
    for suffix,seed in zip(('a','b'),transport.REFERENCE_SEEDS):
        l1,lfc,info=integrate_moments(current['point'],-current['direction'],pose,PHYSICAL_ROUGHNESS,samples,seed+index)
        refs.append(combine(l1,lfc,cues['f0']))
        moments['l1_spec_'+suffix]=l1.astype('<f4')
        moments['lfc_spec_'+suffix]=lfc.astype('<f4')
        ref_info.append(info)
    age=np.full((scene.HEIGHT,scene.WIDTH),255,'u1')
    ghost_a=np.zeros((scene.HEIGHT,scene.WIDTH,3),np.float64)
    ghost_b=ghost_a.copy()
    ghost_diff=ghost_a.copy()
    ghost_f0=ghost_a.copy()
    ghost_qs=np.ones_like(ghost_a)
    ghost_qd=np.ones_like(ghost_a)
    ghost_packet=np.zeros((scene.HEIGHT,scene.WIDTH,4),'<f2')
    reveal=geom['inside']&(current['object']==0)&(geom['previous_visible']['object']==1)
    if index==0:
        reveal[:]=False
    else:
        old_info=json.loads((root/'dataset'/f'frame{index+1:03d}'/'frame.json').read_bytes())
        old_folder=root/'dataset'/old_info['directory']
        old={n:files.load(old_folder,old_info['payloads'][n]) for n in
            ('object','reveal_age','ghost_spec_a','ghost_spec_b','ghost_diff','ghost_f0','ghost_qs','ghost_qd','ghost_base_metal')}
        sy,sx=geom['sy'],geom['sx']
        reveal &= old['object'][sy,sx]==1
        carried=geom['inside']&geom['same']&(old['reveal_age'][sy,sx]<32)&(current['object']==0)
        age[carried]=np.minimum(old['reveal_age'][sy[carried],sx[carried]].astype(int)+1,32).astype('u1')
        for dst,name in ((ghost_a,'ghost_spec_a'),(ghost_b,'ghost_spec_b'),(ghost_diff,'ghost_diff'),
                         (ghost_f0,'ghost_f0'),(ghost_qs,'ghost_qs'),(ghost_qd,'ghost_qd'),(ghost_packet,'ghost_base_metal')):
            dst[carried]=old[name][sy[carried],sx[carried]]
    age[reveal]=0
    ghost_info=[]
    if reveal.any():
        old_surface=geom['previous_visible']
        old_cues=material_at(old_surface['point'][reveal],old_surface['object'][reveal],old_pose)
        old_qs,old_qd=guides(old_cues,old_surface['no_v'][reveal])
        ghost_f0[reveal]=old_cues['f0']
        ghost_packet[reveal]=old_cues['base_metal']
        ghost_qs[reveal]=old_qs.astype(np.float64)/255.
        ghost_qd[reveal]=old_qd.astype(np.float64)/255.
        ghost_diff[reveal]=old_surface['diff'][reveal]*old_cues['qd']
        for out,seed in ((ghost_a,transport.REFERENCE_SEEDS[0]),(ghost_b,transport.REFERENCE_SEEDS[1])):
            l1,lfc,info=integrate_moments(old_surface['point'][reveal],-old_surface['direction'][reveal],old_pose,
                PHYSICAL_ROUGHNESS,samples,seed+0x100000+index)
            out[reveal]=combine(l1,lfc,old_cues['f0'])
            ghost_info.append(info)
    qs8,qd8=guides(cues,current['no_v'])
    qs,qd=qs8.astype(np.float64)/255.,qd8.astype(np.float64)/255.
    physical_diff=np.concatenate((current['diff']*cues['qd'],current['diffuse_metric'][...,None]),axis=-1).astype('<f2')
    spec=divide_rgb(physical_spec,qs)
    diff=divide_rgb(physical_diff,qd,current['diff'])
    albedo_spec=np.concatenate((qs8,np.zeros((scene.HEIGHT,scene.WIDTH,1),'u1')),-1)
    albedo_diff=np.concatenate((qd8,np.zeros((scene.HEIGHT,scene.WIDTH,1),'u1')),-1)
    white=albedo_spec.copy();white[...,:3]=255
    arrays=dict(spec=spec,diff=diff,physical_spec=physical_spec,physical_diff=physical_diff,
        depth=current['signed_depth'].astype('<f4'),motion=geom['motion'],
        normals=np.full((scene.HEIGHT,scene.WIDTH),scene.NORMAL_RG|(np.uint32(NORMAL_CODE)<<np.uint32(20)),'<u4'),
        spec_albedo=albedo_spec,diff_albedo=albedo_diff,white_albedo=white,
        reference_spec_a=refs[0].astype('<f4'),reference_spec_b=refs[1].astype('<f4'),
        reference_spec=((refs[0]+refs[1])*.5).astype('<f4'),reference_diff=(current['diff']*cues['qd']).astype('<f4'),
        ghost_spec_a=ghost_a.astype('<f4'),ghost_spec_b=ghost_b.astype('<f4'),ghost_spec=((ghost_a+ghost_b)*.5).astype('<f4'),
        ghost_diff=ghost_diff.astype('<f4'),ghost_f0=ghost_f0.astype('<f4'),ghost_qs=ghost_qs.astype('<f4'),
        ghost_qd=ghost_qd.astype('<f4'),ghost_base_metal=ghost_packet,
        qs_current=qs.astype('<f4'),qd_current=qd.astype('<f4'),physical_f0=cues['f0'].astype('<f4'),
        physical_qd=cues['qd'].astype('<f4'),base_metal=cues['base_metal'],stored_rgb10=cues['rgb10'],
        stored_metal8=cues['metal8'],material_id=cues['material_id'],native_g8=np.full((128,128),G8,'u1'),
        guide_roughness=np.full((128,128),GUIDE_ROUGHNESS,'<f2'),no_v=current['no_v'].astype('<f4'),
        reveal_age=age,reveal_mask=reveal.astype('u1'),object=current['object'],
        current_world=current['point'].astype('<f4'),previous_world=geom['previous_point'].astype('<f4'),
        previous_uv=geom['previous_uv'].astype('<f4'),rr_previous_uv=geom['sample_uv'].astype('<f4'),
        reprojection_valid=geom['inside'].astype('u1'),surface_visible=geom['same'].astype('u1'),
        previous_surface_depth=geom['previous_depth'].astype('<f4'),canonical_motion=geom['canonical'],
        interior=np.pad(np.ones((96,96),'u1'),((16,16),(16,16))),
        secondary_world=ray['point'].astype('<f4'),secondary_object=ray['object'],
        sampled_direction=sample['direction'].astype('<f4'),sampled_weight=sample['weight'].astype('<f4'),
        sampled_pdf=sample['pdf'].astype('<f4'),sampled_vo_h=sample['vo_h'].astype('<f4'),
        below_hemisphere=(sample['no_l']<=0).astype('u1'),real_miss=ray['miss'].astype('u1'),**moments)
    need(all(np.isfinite(v).all() for v in arrays.values()),'every physical/demod/guide/reference/geometry payload finite')
    need(np.all(((arrays['normals']>>20)&1023)==NORMAL_CODE) and NORMAL_CODE>0,'strictly positive R10 RR roughness, no skipfilter success')
    records={name:files.put(folder,name+'.bin',value) for name,value in arrays.items()}
    for candidate in ('white','actual'):
        for name in common.NATIVE:
            source=folder/('white_albedo.bin' if candidate=='white' and name.endswith('_albedo') else name+'.bin')
            common.link_immutable(root/'views'/candidate/prefix/(name+'.bin'),source)
    for name in common.NATIVE:
        if not name.endswith('_albedo'):
            need(files.file_sha(root/'views/white'/prefix/(name+'.bin'))==files.file_sha(root/'views/actual'/prefix/(name+'.bin')),
                 'native candidates differ only in albedo RGB, never source signals/geometry/history')
    need(np.array_equal(albedo_spec[...,3],white[...,3]) and np.array_equal(albedo_diff[...,3],white[...,3]),'both candidates keep identical albedo alpha')
    crop=np.s_[16:112,16:112]
    info=dict(frame=index+2,directory=prefix,payloads=records,config_sha256=digest,
        reference_replicas=ref_info,ghost_reference_replicas=ghost_info,
        replica_difference_rgb_rmse=float(np.sqrt(np.mean((refs[0][crop]-refs[1][crop])**2))),
        reveal_pixels=int(reveal.sum()),checks=CHECKS,
        physical_input_alpha_minmax=[float(physical_spec[...,3].min()),float(physical_spec[...,3].max())])
    files.write_json(info_path,info)
    return info


def prepare(root,first,count,samples):
    root=Path(root)
    need(root.resolve().is_relative_to(scene.BASE.resolve()),'new task-local V8 path only')
    need(0<=first<64 and 1<=count<=8 and first+count<=64,'CPU job bounded to <=8 consecutive frames')
    need(samples==256,'predeclared256spp x2 independent references, never retune after outputs')
    root.mkdir(parents=True,exist_ok=True)
    config=configuration(samples)
    files.immutable(root/'config.json',(json.dumps(config,sort_keys=True,indent=2)+'\n').encode())
    camera=transport.camera_api()
    original=files.original(Path('F:/FSRD/sol_batch/15e-quality/inputs'))
    table=(Path('F:/FSRD/sol_batch/15e-quality/inputs')/original['native_replay']['file']).read_bytes()
    for target in (root,root/'views/white',root/'views/actual'):
        files.immutable(target/'native-replay.txt',table)
    started=time.perf_counter()
    rows=[]
    for index in range(first,first+count):
        before=time.perf_counter()
        info=frame(root,index,samples,config,camera)
        rows.append(info)
        print(json.dumps(dict(frame=index+2,seconds=time.perf_counter()-before,
            replica_difference_rgb_rmse=info['replica_difference_rgb_rmse'],reveal_pixels=info['reveal_pixels'])),flush=True)
    result=dict(schema=SCHEMA+'-chunk',first=first,count=count,seconds=time.perf_counter()-started,
        checks=CHECKS,sealed_payload_checks=files.CHECKS,gpu_executed=False,compiler_executed=False)
    files.write_json(root/f'chunk-{first:03d}-{first+count-1:03d}.json',result)
    if first+count==64:
        frames=[json.loads((root/'dataset'/f'frame{i+2:03d}'/'frame.json').read_bytes()) for i in range(64)]
        manifest=dict(config,frames=frames,submitted_frames=64,comparison_crop=[16,16,96,96],
            native_replay=original['native_replay'],views={name:str(root/'views'/name) for name in ('white','actual')},
            reference_uncertainty='both independent256spp replicas retained; paired differences and cross-reference gradient energy, no result below uncertainty called improvement')
        files.write_json(root/'colored-ggx-sequence.json',manifest)
        result['manifest_sha256']=files.file_sha(root/'colored-ggx-sequence.json')
    print(json.dumps(result,indent=2),flush=True)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--first',type=int,default=0)
    parser.add_argument('--count',type=int,default=8)
    parser.add_argument('--samples',type=int,default=256)
    args=parser.parse_args()
    prepare(args.output,args.first,args.count,args.samples)
