"""Deterministic, unlooped CPU experiments. All evaluation support is BASE-fixed."""
from pathlib import Path
import csv
import gzip
import hashlib
import io
import json
import math
import numpy as np
from reconstruction import (GeometryField, Policy, certify_cells,
    local_estimator_support, certify_estimator_support, reconstruct, bilinear_gain)

ROOT=Path(__file__).resolve().parent


def sha_array(a):
    return hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()


def scene(extent=(64,48), angle=0., phase=0., kind="two_surface_boundary", cell=8,
          *, coplanar=False, all_static=False):
    """Two analytic planar surfaces seen by a perspective pinhole camera.

    Surface labels are evaluation truth ONLY; the candidate receives positions,
    normals and explicit observed/eligible masks. Centre gains are an exact-gain
    intervention to remove estimator error, not a captured production gain.
    """
    w,h=extent
    yy,xx=np.mgrid[:h,:w]
    theta=math.radians(angle)
    def foreground(x,y):
        distance=(x-w/2)*math.cos(theta)+(y-h/2)*math.sin(theta)-phase
        return np.abs(distance)<.5 if kind=="one_pixel_foreground_strip" else distance>=0
    fg=foreground(xx+.5,yy+.5)
    depth=np.where(fg,8. if coplanar else 3.,8.)
    position=np.stack(((xx+.5-w/2)*depth/w,(h/2-yy-.5)*depth/w,depth),-1)
    normal=np.zeros_like(position);normal[...,2]=-1
    observed=np.ones((h,w),bool)
    if kind=="partial_observation":
        observed=(xx>=3)&(xx<w-5)&(yy>=2)&(yy<h-4)
    eligible=(np.ones_like(fg) if all_static else ~fg)&observed
    field=GeometryField(position,normal,observed,eligible,depth)
    gh,gw=(h+cell-1)//cell,(w+cell-1)//cell
    cy,cx=np.mgrid[:gh,:gw]
    coarse=np.where(foreground(cx*cell+cell/2,cy*cell+cell/2),1.,.8)
    truth=np.where((~fg)&observed,.8,1.)
    return field,coarse,truth,fg


def _metrics(output,truth,field,fg):
    observed=field.observed
    eligible=(~fg)&observed
    protected=fg&observed
    unknown=~observed
    spill=np.abs(1-output[protected])
    denom=float(np.sum(1-truth[eligible]))
    dose=float(np.sum(1-output[eligible]))/denom if denom else None
    return {
        "protected_pixels":int(protected.sum()),"eligible_pixels":int(eligible.sum()),
        "unknown_pixels":int(unknown.sum()),
        "spill_peak":float(spill.max(initial=0)),
        "spill_mean":float(spill.mean()) if spill.size else 0.,
        "occlusion_leakage_fraction":float(np.mean(spill>1e-12)) if spill.size else 0.,
        "unknown_changed_fraction":float(np.mean(np.abs(output[unknown]-1)>1e-12)) if unknown.any() else 0.,
        "eligible_correction_dose":dose,
        "gain_mae_all_observed":float(np.abs(output-truth)[observed].mean()),
        "eligible_identity_fraction":float(np.mean(np.abs(output[eligible]-1)<1e-12)) if eligible.any() else None,
    }


def _summarize(values):
    a=np.asarray([v for v in values if v is not None],float)
    if not a.size:return None
    return {"min":float(a.min()),"mean":float(a.mean()),"p50":float(np.median(a)),
            "p95":float(np.quantile(a,.95)),"max":float(a.max())}


def exact_support_oracle(field,cell):
    """Analytic exact-support ablation, separate from candidate geometric tests.

    Only the static background is eligible in these phase scenes. Ground-truth
    mask labels certify complete cells; candidate code never receives labels.
    """
    h,w=field.observed.shape;gh,gw=(h+cell-1)//cell,(w+cell-1)//cell
    padded=np.zeros((gh*cell,gw*cell),bool)
    padded[:h,:w]=field.observed&field.eligible
    pure=padded.reshape(gh,cell,gw,cell).all(axis=(1,3))
    yy,xx=np.mgrid[:h,:w]
    u,v=(xx+.5)/cell-.5,(yy+.5)/cell-.5
    ix,iy=np.floor(u).astype(int),np.floor(v).astype(int)
    a,b=u-ix,v-iy;any_support=np.zeros((h,w),bool)
    for dx,dy,weight in ((0,0,(1-a)*(1-b)),(1,0,a*(1-b)),(0,1,(1-a)*b),(1,1,a*b)):
        x,y=ix+dx,iy+dy
        inside=(x>=0)&(x<gw)&(y>=0)&(y<gh)
        any_support |= inside&(weight>1e-8)&pure[np.clip(y,0,gh-1),np.clip(x,0,gw-1)]
    return pure,np.where(field.eligible&field.observed&any_support,.8,1.)


def phase_sweep(evidence):
    plan=json.loads((ROOT/'EXPERIMENT_PLAN.json').read_text())
    cases=[]
    worst={}
    digest=hashlib.sha256()
    examples={}
    oracle_totals={'certified_cells':0,'false_certified_cells':0,'true_pure_cells':0,
                   'missed_pure_cells':0,'centre_sampled_gain_vs_exact_cell_gain_max_error':0.,
                   'centre_gain_disagrees_with_observed_cell_count':0,
                   'centre_gain_disagreement_scene_count':0,
                   'centre_gain_worst_case':None,
                   'exact_footprint_gain_output_max_abs_error':0.,'unknown_query_promoted':0}
    orientations=plan['canonical_orientation_degrees']+plan['held_out_orientation_degrees']
    for extent in plan['extent_width_height']:
        for cell in plan['cell_sizes']:
            for kind in plan['geometry']:
                for angle in orientations:
                    for phase in np.arange(0,8,.25):
                        field,coarse,truth,fg=scene(tuple(extent),angle,float(phase),kind,cell)
                        # Candidate-independent masks are frozen before variant evaluation.
                        digest.update(np.ascontiguousarray(np.stack((field.observed,field.eligible,fg))).tobytes())
                        cells=certify_cells(field,Policy(cell=cell))
                        support=local_estimator_support(cells,np.ones_like(cells.valid))
                        supported=reconstruct(coarse,support,field)
                        oracle_cells,oracle_output=exact_support_oracle(field,cell)
                        oracle_totals['certified_cells']+=int(cells.valid.sum())
                        oracle_totals['false_certified_cells']+=int((cells.valid&~oracle_cells).sum())
                        oracle_totals['true_pure_cells']+=int(oracle_cells.sum())
                        oracle_totals['missed_pure_cells']+=int((~cells.valid&oracle_cells).sum())
                        centre_error=float(np.abs(supported.gain-oracle_output).max())
                        if centre_error>oracle_totals['centre_sampled_gain_vs_exact_cell_gain_max_error']:
                            oracle_totals['centre_sampled_gain_vs_exact_cell_gain_max_error']=centre_error
                            oracle_totals['centre_gain_worst_case']={'extent':extent,'cell':cell,'kind':kind,
                                'angle':angle,'phase':float(phase)}
                        mismatched=oracle_cells&(np.abs(coarse-.8)>1e-12)
                        oracle_totals['centre_gain_disagrees_with_observed_cell_count']+=int(mismatched.sum())
                        oracle_totals['centre_gain_disagreement_scene_count']+=int(mismatched.any())
                        # Distinct exact-footprint intervention. Crucially the
                        # truth mask comes from oracle_cells, NOT cells.valid.
                        exact_gain=np.where(oracle_cells,.8,coarse)
                        exact_result=reconstruct(exact_gain,support,field)
                        exact_error=float(np.abs(exact_result.gain-oracle_output).max())
                        oracle_totals['exact_footprint_gain_output_max_abs_error']=max(
                            oracle_totals['exact_footprint_gain_output_max_abs_error'],exact_error)
                        assert exact_error<=1e-12, 'exact-footprint gain and exact-support oracle disagree'
                        oracle_totals['unknown_query_promoted']+=int(((~field.observed)&(supported.support_mass>0)).sum())
                        variants={
                            'bilinear':bilinear_gain(coarse,tuple(extent),cell),
                            'hard_identity':reconstruct(coarse,support,field,method='hard').gain,
                            'supported':supported.gain,
                            'wrong_half_pixel':bilinear_gain(coarse,tuple(extent),cell,'wrong_half_pixel'),
                        }
                        results={name:_metrics(g,truth,field,fg) for name,g in variants.items()}
                        # Match correction dose by attenuating (never amplifying) all controls.
                        doses=[results[n]['eligible_correction_dose'] for n in variants]
                        common=min(x for x in doses if x is not None)
                        pair_common=min(results[n]['eligible_correction_dose'] for n in ('bilinear','supported'))
                        for name,g in variants.items():
                            m=results[name]
                            dose=m['eligible_correction_dose']
                            factor=common/dose if dose and dose>0 else 0.
                            assert 0 <= factor <= 1+1e-12
                            matched=1-factor*(1-g)
                            m['matched_dose']=common
                            m['dose_attenuation']=factor
                            m['matched_spill_peak']=float(np.abs(1-matched[fg&field.observed]).max(initial=0))
                            m['pair_bilinear_supported_dose']=pair_common if name in ('bilinear','supported') else None
                            pair_factor=pair_common/dose if dose and dose>0 else 0.
                            m['pair_bilinear_supported_spill_peak']=(m['spill_peak']*pair_factor
                                if name in ('bilinear','supported') else None)
                            row={'width':extent[0],'height':extent[1],'cell':cell,'kind':kind,
                                 'angle':angle,'phase':float(phase),'held_out':angle in plan['held_out_orientation_degrees'],
                                 'variant':name,**m}
                            cases.append(row)
                            key=name
                            if key not in worst or m['spill_peak']>worst[key]['spill_peak']:
                                worst[key]=row.copy()
                        if extent==[67,53] and cell==8 and kind=='two_surface_boundary' and angle==17 and phase==3.25:
                            examples={**variants,'truth':truth,'protected':fg&field.observed,
                                      'observed':field.observed,'support_mass':supported.support_mass}
    with (evidence/'phase_sweep.csv.gz').open('wb') as raw:
        with gzip.GzipFile(filename='',fileobj=raw,mode='wb',mtime=0) as compressed:
            with io.TextIOWrapper(compressed,encoding='utf-8',newline='') as f:
                writer=csv.DictWriter(f,fieldnames=list(cases[0]));writer.writeheader();writer.writerows(cases)
    if examples:np.savez_compressed(evidence/'phase_example.npz',**examples)
    metrics=['spill_peak','spill_mean','occlusion_leakage_fraction','unknown_changed_fraction',
             'eligible_correction_dose','gain_mae_all_observed','eligible_identity_fraction','matched_spill_peak',
             'matched_dose','pair_bilinear_supported_dose','pair_bilinear_supported_spill_peak']
    summaries={}
    for variant in ('bilinear','hard_identity','supported','wrong_half_pixel'):
        rows=[x for x in cases if x['variant']==variant]
        holdout=[x for x in rows if x['held_out']]
        summaries[variant]={'all':{m:_summarize([x[m] for x in rows]) for m in metrics},
                            'held_out':{m:_summarize([x[m] for x in holdout]) for m in metrics},
                            'worst_spill':worst[variant],
                            'zero_common_dose_cases':sum(x['matched_dose']<=1e-12 for x in rows),
                            'zero_pairwise_dose_cases':sum(x['pair_bilinear_supported_dose'] is not None and
                                x['pair_bilinear_supported_dose']<=1e-12 for x in rows)}
    return {'scope':'analytic CPU; centre-sampled point-gain intervention, conservative measured geometry support',
            'gain_footprint_note':'Point-centre gain is not an exact full-cell statistic for aliased thin strips. Separate exact-footprint ablation replaces only independently oracle-pure cells; primary comparisons remain unchanged.',
            'scene_cases':len(cases)//4,'variant_rows':len(cases),'base_masks_sha256':digest.hexdigest(),
            'plan_sha256':hashlib.sha256((ROOT/'EXPERIMENT_PLAN.json').read_bytes()).hexdigest(),
            'variants':summaries,'exact_support_ablation':oracle_totals,
            'sampler':'ideal arithmetic, not D3D sampler parity'}


def estimator_contamination():
    field,coarse,truth,fg=scene((128,64),0,0,cell=8,all_static=True)
    cells=certify_cells(field)
    offsets=[(x,y) for y in (-3,0,3) for x in (-3,0,3)]
    yy,xx=np.mgrid[:coarse.shape[0],:coarse.shape[1]]
    mixed=sum(coarse[np.clip(yy+dy,0,coarse.shape[0]-1),np.clip(xx+dx,0,coarse.shape[1]-1)]
              for dx,dy in offsets)/len(offsets)
    local=local_estimator_support(cells,np.ones_like(cells.valid))
    full=certify_estimator_support(cells,np.ones_like(coarse),np.ones_like(cells.valid),offsets)
    variants={'exact_gain_local_support':reconstruct(coarse,local,field).gain,
              'mixed_gain_local_only_INVALID_PROVENANCE':reconstruct(mixed,local,field).gain,
              'mixed_gain_full_donor_certificate':reconstruct(mixed,full,field).gain}
    result={name:_metrics(g,truth,field,fg) for name,g in variants.items()}
    # Identical geometry + static observations cannot identify an albedo/light
    # correction discontinuity. This is an intentional nonzero-error limit.
    flat,cg,t,mask=scene((64,48),0,1.25,cell=8,coplanar=True,all_static=True)
    cs=certify_cells(flat);sp=local_estimator_support(cs,np.ones_like(cs.valid))
    g=reconstruct(cg,sp,flat).gain
    result['coplanar_identical_guides_unidentifiable']=_metrics(g,t,flat,mask)
    result['scope']='synthetic interventions; no captured keys; full support is a necessary precondition, not recovered evidence'
    return result


def temporal_metrics(evidence):
    """One chronological trajectory per independent seed; no warmup looping.

    Surface mask moves analytically through a static wall. Gain noise is injected
    in the coarse observation to expose variance cost of renormalized support.
    Pixel/frame denominators and adjacency masks come only from the BASE scene.
    """
    seeds=json.loads((ROOT/'EXPERIMENT_PLAN.json').read_text())['seeds']
    outputs={}
    for seed in seeds:
        rng=np.random.default_rng(seed)
        variants={n:[] for n in ('bilinear','hard_identity','supported')}
        noiseless={n:[] for n in variants}
        truth_seq=[];protected=[];eligible=[]
        for frame in range(48):
            field,coarse,truth,fg=scene((67,53),33,frame*.23-5,cell=8)
            cells=certify_cells(field)
            support=local_estimator_support(cells,np.ones_like(cells.valid))
            noise=rng.normal(0,.008,size=coarse.shape)
            noisy=np.where(coarse<1,np.clip(coarse+noise,0,1),1.)
            variants['bilinear'].append(bilinear_gain(noisy,(67,53)))
            variants['hard_identity'].append(reconstruct(noisy,support,field,method='hard').gain)
            variants['supported'].append(reconstruct(noisy,support,field).gain)
            noiseless['bilinear'].append(bilinear_gain(coarse,(67,53)))
            noiseless['hard_identity'].append(reconstruct(coarse,support,field,method='hard').gain)
            noiseless['supported'].append(reconstruct(coarse,support,field).gain)
            truth_seq.append(truth);protected.append(fg);eligible.append(~fg)
        truth_seq=np.asarray(truth_seq);protected=np.asarray(protected);eligible=np.asarray(eligible)
        yy,xx=np.mgrid[:53,:67]
        # Fixed synthetic microtexture: compare output to known gain-scaled truth.
        texture=1+.08*np.sin(xx*1.71)+.06*np.cos(yy*2.17)
        expected=truth_seq*texture
        static_pairs=eligible[1:]&eligible[:-1]
        fixed_detail=eligible[:,:,:-1]&eligible[:,:,1:]
        base_digest=sha_array(np.stack((protected,eligible)))
        doses={name:float(np.sum((1-np.asarray(seq))[eligible])/np.sum((1-truth_seq)[eligible]))
               for name,seq in variants.items()}
        common=min(doses.values())
        matched_expected=(1-common*(1-truth_seq))*texture
        metrics={}
        for name,seq in variants.items():
            gain=np.asarray(seq)
            image=gain*texture
            error=image-expected
            delta_error=np.diff(error,axis=0)
            grad=np.diff(image,axis=2);true_grad=np.diff(expected,axis=2)
            correction=float(np.sum((1-gain)[eligible])/np.sum((1-truth_seq)[eligible]))
            clean=np.asarray(noiseless[name])*texture
            noise_error=image-clean
            support_error=clean-expected
            factor=common/doses[name]
            matched_image=(1-factor*(1-gain))*texture
            matched_error=matched_image-matched_expected
            metrics[name]={
                'eligible_correction_dose':correction,
                'protected_spill_peak':float(np.abs((1-gain)[protected]).max()),
                'protected_error_rms':float(np.sqrt(np.mean(error[protected]**2))),
                'eligible_error_rms':float(np.sqrt(np.mean(error[eligible]**2))),
                'eligible_flicker_error_rms':float(np.sqrt(np.mean(delta_error[static_pairs]**2))),
                'eligible_sparkle_abs_error_p999':float(np.quantile(np.abs(error[eligible]),.999)),
                'eligible_spatial_error_std':float(np.std(error[eligible])),
                'detail_gradient_transfer':float(np.mean(np.abs(grad[fixed_detail]))/np.mean(np.abs(true_grad[fixed_detail]))),
                'isolated_gain_noise_error_std':float(np.std(noise_error[eligible])),
                'isolated_gain_noise_abs_p999':float(np.quantile(np.abs(noise_error[eligible]),.999)),
                'noiseless_support_flicker_error_rms':float(np.sqrt(np.mean(np.diff(support_error,axis=0)[static_pairs]**2))),
                'matched_correction_dose':common,'dose_attenuation':factor,
                'matched_eligible_flicker_error_rms':float(np.sqrt(np.mean(np.diff(matched_error,axis=0)[static_pairs]**2))),
                'matched_eligible_error_rms':float(np.sqrt(np.mean(matched_error[eligible]**2))),
                'matched_protected_error_rms':float(np.sqrt(np.mean(matched_error[protected]**2))),
                'matched_isolated_gain_noise_std':float(np.std((factor*noise_error)[eligible])),
            }
        outputs[str(seed)]={'base_masks_sha256':base_digest,'frames':48,'unlooped':True,'variants':metrics}
    return {'scope':'synthetic CPU noisy-gain trajectory; not temporal RR or captures',
            'truth':'exact per-frame geometry and scalar gain; fixed microtexture',
            'seeds':outputs}


def run(evidence):
    evidence=Path(evidence);evidence.mkdir(parents=True,exist_ok=True)
    result={'phase_sweep':phase_sweep(evidence),'estimator_ablation':estimator_contamination(),
            'temporal':temporal_metrics(evidence)}
    (evidence/'experiments.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    return result


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,default=ROOT/'evidence')
    args=parser.parse_args();result=run(args.out)
    print(json.dumps({'scene_cases':result['phase_sweep']['scene_cases'],
                      'variants':result['phase_sweep']['variants']},indent=2,allow_nan=False))
