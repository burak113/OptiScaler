"""Frozen normalized response transfer hypotheses; post-hoc offline only.

Estimators see P, native T(P), native baseline, controls and activity. Truth
is used only by measurement. Existing native studies are never modified.
"""
from pathlib import Path
import importlib.util,json
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
REFERENCE=ROOT/'tools_tmp/delta_history_offline_20260930/analyze.py'
spec=importlib.util.spec_from_file_location('frozen_reference',REFERENCE)
reference=importlib.util.module_from_spec(spec);spec.loader.exec_module(reference)
HISTORY=16
DENOMINATOR_MIN=1e-4
MODES=('normalized_delta_mean16','ratio_current','ratio_mean16')


def transfer(pilot,response,baseline,controls,active,mode):
    """Inclusive causal mean, invalid past pixels excluded, no truth argument."""
    p=np.asarray(pilot,float);tp=np.asarray(response,float);b=np.asarray(baseline,float)
    controls=np.asarray(controls,float);active=np.asarray(active,bool)
    if mode not in MODES or p.ndim!=4 or p.shape[-1]!=3 or tp.shape!=p.shape or b.shape!=p.shape:
        raise ValueError('Invalid transfer mode or RGB dimensions')
    if controls.shape!=(len(p),3) or active.shape!=(len(p),) or not np.isfinite(controls).all() or not np.isin(controls[:,0],[0,1]).all():
        raise ValueError('Invalid immutable native controls')
    if not np.isfinite(b).all():raise ValueError('Baseline must be finite')
    valid=np.all(np.isfinite(p)&np.isfinite(tp)&(p>DENOMINATOR_MIN)&(tp>DENOMINATOR_MIN),axis=-1)
    eligible=valid & active[:,None,None]
    out=b.copy();past=[];diagnostics=[];epoch=0
    for i in range(len(p)):
        if controls[i,0] or (i and not np.array_equal(controls[i,1:],controls[i-1,1:])) or not active[i]:
            past.clear();epoch=i
        count=np.zeros(p.shape[1:3],int)
        if active[i]:
            numer=p[i]-tp[i] if mode=='normalized_delta_mean16' else p[i]
            denom=p[i] if mode=='normalized_delta_mean16' else tp[i]
            q=np.divide(numer,denom,out=np.zeros_like(numer),where=valid[i,...,None])
            if mode=='ratio_current':mean=q;count=valid[i].astype(int)
            else:
                past.append((q,valid[i]))
                if len(past)>HISTORY:past.pop(0)
                count=sum(v.astype(int) for _,v in past)
                total=sum(qv for qv,_ in past)
                mean=np.divide(total,count[...,None],out=np.zeros_like(total),where=count[...,None]>0)
            candidate=b[i]+p[i]*mean if mode=='normalized_delta_mean16' else b[i]*mean
            out[i]=np.where(valid[i,...,None],candidate,b[i])
        diagnostics.append(dict(frame=i,epoch_start=epoch,history_observations=len(past) if mode!='ratio_current' else int(active[i]),
            valid_pixel_fraction=float(eligible[i].mean()),valid_history_min=int(count.min()),valid_history_max=int(count.max())))
    return out,eligible,diagnostics


def self_checks():
    rng=np.random.default_rng(7123);p=rng.uniform(.1,.4,(32,8,8,3));tp=p*rng.uniform(.7,.9,p.shape);b=tp.copy()
    controls=np.zeros((32,3));controls[0,0]=1;active=np.ones(32,bool)
    for mode in MODES:
        a,mask,records=transfer(p,tp,b,controls,active,mode)
        changed=p.copy();changed[20:]*=2;c,_,_=transfer(changed,tp,b,controls,active,mode)
        np.testing.assert_array_equal(a[:20],c[:20]);assert max(x['history_observations'] for x in records)<=16
        cc=controls.copy();cc[12,0]=1;cc[24:,1:]=[.25,.125]
        a,_,rec=transfer(p,tp,b,cc,active,mode)
        for i in (0,12,24):
            current=p[i] if mode!='normalized_delta_mean16' else b[i]+p[i]-tp[i]
            np.testing.assert_allclose(a[i],current,rtol=0,atol=1e-15);assert rec[i]['epoch_start']==i
        aa=active.copy();aa[18]=False;a,_,rec=transfer(p,tp,b,cc,aa,mode)
        np.testing.assert_array_equal(a[18],b[18]);assert rec[19]['history_observations']==1
        # Illumination scale changes track exactly only in a homogeneous model.
        scale=np.linspace(.4,2.3,32)[:,None,None,None]
        pp=np.full_like(p,.3)*scale;tt=.8*pp
        a,_,_=transfer(pp,tt,tt,controls,active,mode)
        np.testing.assert_allclose(a,pp,rtol=0,atol=1e-15)
        badp=p.copy();badt=tp.copy();badp[8,2,3,0]=DENOMINATOR_MIN;badt[9,2,3,1]=0;badt[10,2,3,2]=np.nan
        a,mask,_=transfer(badp,badt,b,controls,active,mode)
        for i in (8,9,10):np.testing.assert_array_equal(a[i,2,3],b[i,2,3]);assert not mask[i,2,3]
        assert np.isfinite(a).all()
        if mode!='ratio_current':
            indices=[i for i in range(12) if i not in (8,9,10)]
            q=(p[indices,2,3]-tp[indices,2,3])/p[indices,2,3] if mode=='normalized_delta_mean16' else p[indices,2,3]/tp[indices,2,3]
            expected=b[11,2,3]+p[11,2,3]*q.mean(0) if mode=='normalized_delta_mean16' else b[11,2,3]*q.mean(0)
            np.testing.assert_allclose(a[11,2,3],expected,rtol=0,atol=1e-15)
    a,_,_=transfer(p,tp,b,controls,active,'normalized_delta_mean16')
    np.testing.assert_allclose(a[0],b[0]+p[0]-tp[0],atol=1e-15)
    return dict(no_future=True,bounded_16=True,reset_jitter_epochs=True,inactive_exact_baseline=True,
        flat_homogeneous_illumination_scaling=True,nearzero_and_nonfinite_atomic_baseline=True,
        invalid_past_excluded=True,current_additive_identity=True)


def main():
    output=Path(__file__).with_name('results.json')
    if output.exists():raise ValueError('Preserve previous results')
    report=dict(schema='normalized-response-transfer-offline-v1',status='running',quality_accepted=False,
        native_rerun=False,game_run=False,runtime_implemented=False,history=HISTORY,denominator_min=DENOMINATOR_MIN,
        thresholds_changed=False,filtering_precision='float64 signed; inclusive warmup; per-pixel valid past count',
        script_sha256=reference.digest(__file__),reference_script_sha256=reference.digest(REFERENCE),self_checks=self_checks(),
        metric_source_sha256={n:reference.digest(reference.TESTS/n) for n in ('probe_fsrd_statistical_resolve.py','probe_fsrd_response_calibration.py','fsrd_quality_contours.py')},
        filter_inputs=['pilot RGB','native pilot response RGB','native baseline RGB','native reset/jitter controls','frozen activity'],
        limitations=['Post-hoc reuse of frozen studies, not an independent holdout.',
            'Homogeneous multiplicative response may track scalar lighting; nonlinear spatial/material response need not.',
            'Pixel-corresponding normalized transfer history is assumed, not proved.',
            'Division guard is whole RGB; invalid historical samples excluded pixelwise; current guard always exact baseline.',
            'Current source RGB enters only the separately declared current-DC constraint.',
            'DC is computed before restoring denominator-guard pixels; exact mean conservation is not promised with guard pixels.',
            'Atomic radiance fallback is separate and never clamps.',
            'Persistent shared source bias remains unidentifiable; low error without detail/phase gates is insufficient.'],rows=[])
    for study in reference.STUDIES:
        folder=reference.EVIDENCE/study;rp=folder/'results.json';rh=reference.digest(rp);original=json.loads(rp.read_text())
        if original['status']!='completed_research_not_solution':raise ValueError('Incomplete source study')
        for row in original['rows']:
            scene=row['scene'];sp=folder/scene/'sequences.npz';sh=reference.digest(sp)
            cp=folder/scene/'observed/frame_controls.txt';ch=reference.digest(cp);variants={};diagnostics={}
            with np.load(sp) as a:
                controls=reference.controls_from_native(cp,len(a['pilot']))
                for mode in MODES:
                    candidate,eligible,records=transfer(a['pilot'],a['pilot_response'],a['baseline'],controls,a['active'],mode)
                    epochs=[d['epoch_start'] for d in records];diagnostics[mode]=records
                    dc=reference.dc_conservation(candidate,a['observed'],a['active'],controls,1,epochs)
                    dc=np.where(eligible[...,None],dc,a['baseline'])
                    safe,fraction=reference.radiance_fallback(dc,a['baseline'])
                    for suffix,value,fallback in (('',candidate,0),('_dc_current',dc,0),('_dc_current_safe',safe,fraction)):
                        v=reference.evaluate(value,a['baseline'],a['clean_reference'],scene,a['active'],row['null_rms'],fallback)
                        v['denominator_guard_pixel_fraction']=float(np.mean(~eligible & a['active'][:,None,None]))
                        variants[mode+suffix]=v
            unchanged=reference.digest(rp)==rh and reference.digest(sp)==sh and reference.digest(cp)==ch
            if not unchanged:raise ValueError('Original evidence changed')
            report['rows'].append(dict(study=study,scene=scene,split_strength=original.get('split_strength',0),
                source_files_unchanged=unchanged,provenance=dict(native_report_sha256=rh,native_sequences_sha256=sh,native_controls_sha256=ch),
                baseline_full=row['baseline_full'],baseline_mature=row['baseline_mature'],null_rms=row['null_rms'],
                diagnostics=diagnostics,variants=variants))
            print(study,scene,{n:dict(full=v['full_gate']['failures'],mature=v['mature_gate']['failures']) for n,v in variants.items() if n.endswith('_safe')},flush=True)
    report['status']='completed_posthoc_falsification_not_solution'
    output.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n',encoding='utf-8')


if __name__=='__main__':main()
