"""V8 Schlick algebra, native-style material correspondence and frozen L1 replay."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

import fsrd_nrd_rr_colored_ggx_oracle as colored
import fsrd_nrd_rr_corrected_qs as qs
import fsrd_nrd_rr_ggx_sampling as sampling
import fsrd_nrd_rr_ggx_oracle as old
import fsrd_nrd_rr_material_quality as files
import fsrd_nrd_rr_mirror_oracle as scene


def run(output):
    checks=0
    def need(condition,message):
        nonlocal checks
        checks+=1
        if not bool(condition):
            raise AssertionError(message)
    need(colored.G8==31 and colored.NORMAL_CODE==124,'predeclared native G8 and positive nearest normalR10')
    need(0<colored.PHYSICAL_ROUGHNESS and 0<colored.GUIDE_ROUGHNESS and colored.NORMAL_CODE>0,'all physical/provider roughness values strictly positive; no RR skipfilter')
    need(abs(colored.NORMAL_CODE/1023.-colored.PHYSICAL_ROUGHNESS)<=.5/1023.,'normal roughness differs only by explicitly disclosed nearest R10 quantization')
    camera=old.camera_api()
    geometry=old.frame_geometry(0,camera)
    current,pose=geometry['current'],geometry['pose']
    cues=colored.material_at(current['point'],current['object'],pose)
    color_pixels=int(np.count_nonzero(np.ptp(cues['base_metal'][...,:3],axis=-1)>0))
    dielectric=int(np.count_nonzero(cues['metal8']==0))
    metal=int(np.count_nonzero(cues['metal8']==255))
    need(color_pixels>1000 and dielectric>1000 and metal>1000,'world-fixed colored metal AND dielectric strata, not F1-white surrogate')
    material_edges=0
    for i in range(64):
        g=old.frame_geometry(i,camera)
        now=colored.material_at(g['current']['point'],g['current']['object'],g['pose'])
        prev=colored.material_at(g['previous_point'],g['current']['object'],g['previous_pose'])
        need(np.array_equal(now['rgb10'],prev['rgb10']) and np.array_equal(now['metal8'],prev['metal8']),
             'same corresponding material point retains exact native storage through motion')
        need(np.array_equal(now['base_metal'].view('<u2'),prev['base_metal'].view('<u2')),'explicit captured-half cues stable at corresponding points')
        actual_qs,actual_qd=colored.guides(now,g['current']['no_v'])
        need(np.all(actual_qs>0),'every chosen specular Q channel positive; no hidden denominator epsilon')
        need(np.array_equal(actual_qd,qs.unorm8(now['base_metal'][...,:3].astype(np.float64)*(1-now['base_metal'][...,3:].astype(np.float64)))),
             'diffuse guide exact chosen captured half base*(1-metal), direct UNORM not sqrt')
        material_edges+=int(np.count_nonzero(now['material_id'][:,1:]!=now['material_id'][:,:-1]))
    need(material_edges>1000,'scene genuinely contains material edges for separate physical/remodulated scoring')
    source=scene.BASE/'ggx-v5/r123'
    manifest=json.loads((source/'ggx-sequence.json').read_bytes())
    need(files.file_sha(source/'ggx-sequence.json')=='a190536fb46b3ba2502887d84474be9cdbc49333b51fbe3e450db8f948af59ac',
         'exact expensive frozen physical F1 baseline remains unchanged')
    original=manifest['frames'][0]
    xi=np.random.default_rng(old.INPUT_SEED).random((128,128,2))
    f0_one=np.ones((128,128,3),np.float64)
    rgba,sample,ray,l1,lfc=colored.noisy_physical(current['point'],-current['direction'],pose,123/1023.,xi,f0_one)
    frozen=files.load(source/'dataset'/original['directory'],original['payloads']['spec'])
    need(np.array_equal(rgba.view('<u2'),frozen.view('<u2')),'new Schlick F1 noisy ray replay EXACT original V5 input RGB/A words before changing roughness')
    need(np.array_equal(colored.combine(l1,lfc,np.ones_like(l1)),l1),'F0=1 moment identity exact')
    need(np.array_equal(colored.combine(l1,lfc,np.zeros_like(l1)),lfc),'F0=0 Schlick retains grazing Fc rather than incorrect black tint')
    l1_results=[]
    for suffix,seed in zip(('a','b'),old.REFERENCE_SEEDS):
        exact,fc,info=colored.integrate_moments(current['point'],-current['direction'],pose,123/1023.,256,seed)
        reference=files.load(source/'dataset'/original['directory'],original['payloads']['reference_spec_'+suffix])
        need(np.array_equal(exact.astype('<f4').view('<u4'),reference.view('<u4')),'new L1 integration EXACT stored independent V5 reference replica, same maps/seeds/reduction')
        need(np.all(fc<=exact+2e-16) and np.all(fc>=0),'Fresnel moment bounded by original per-ray sample integral')
        l1_results.append(dict(replica=suffix,rays=info['rays'],exact_float32_words=True))
    # Independent direct per-ray Schlick multiplication versus moment algebra.
    points=current['point'][32:36,32:36].reshape(-1,3)
    view=-current['direction'][32:36,32:36].reshape(-1,3)
    f0=cues['f0'][32:36,32:36].reshape(-1,3)
    count=64
    seed=0x15C8001
    a,b,_=colored.integrate_moments(points,view,pose,colored.PHYSICAL_ROUGHNESS,count,seed)
    shifts=np.random.default_rng(seed).random((len(points),2))
    xi=np.mod(sampling.reference_points(count)[None,:,:]+shifts[:,None,:],1.)
    s=sampling.ndf_reference(view[:,None,:],colored.PHYSICAL_ROUGHNESS,xi)
    rays=old.nearest_emission(points[:,None,:]+scene.NORMAL*old.RAY_ORIGIN_OFFSET,s['direction'],pose)
    fc=(1-np.clip(s['vo_h'],0,1))**5
    fresnel=f0[:,None,:]+(1-f0[:,None,:])*fc[...,None]
    direct=np.mean(rays['radiance']*s['weight'][...,None]*fresnel,axis=1)
    combined=colored.combine(a,b,f0)
    need(np.allclose(combined,direct,rtol=6e-15,atol=1e-17),'colored Schlick moment decomposition equals independent per-ray physical integral')
    need(np.max(abs(combined-f0*a))>1e-10,'Fc moment is materially nonzero; reject naive F0*F1-reference tint')
    # Zero-Qd is only the explicit metal1 physical-zero lobe. It must not cause
    # an epsilon divide, nonfinite input or loss of the native hit metric.
    qd8=qs.unorm8(cues['qd'])
    physical_diff=np.concatenate((current['diff']*cues['qd'],current['diffuse_metric'][...,None]),-1).astype('<f2')
    divided=colored.divide_rgb(physical_diff,qd8/255.,current['diff'])
    need(np.isfinite(divided).all(),'physical-zero metal diffuse has declared finite continuous demod extension')
    need(np.array_equal(divided[...,3].copy().view('<u2'),physical_diff[...,3].copy().view('<u2')),'diffuse first-hit alpha remains bitexact even for zero albedo')
    need(np.any(qd8==0) and np.all(physical_diff[...,:3][qd8==0]==0),'zero albedo extension exercised only on true physical-zero diffuse channels')
    need(len(set(old.REFERENCE_SEEDS+(old.INPUT_SEED,)))==3,'noisy and two reference streams use distinct fixed seeds')
    result=dict(schema=colored.SCHEMA+'-properties',checks=checks,helper_checks=colored.CHECKS,
        l1_replays=l1_results,material_edge_count=material_edges,
        first_frame_colored_pixels=color_pixels,first_frame_dielectric_pixels=dielectric,first_frame_metal_pixels=metal,
        physical_roughness=colored.PHYSICAL_ROUGHNESS,guide_half_roughness=colored.GUIDE_ROUGHNESS,
        normal_r10=colored.NORMAL_CODE,source_frozen=True,compiler_executed=False,gpu_executed=False,
        oracle_not_in_runtime=True,guide_hardware_quantization_verified=False)
    files.write_json(output,result)
    print(json.dumps(result,indent=2))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    run(parser.parse_args().output)
