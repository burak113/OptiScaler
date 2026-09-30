"""Current reconstruction endpoint OLS; saved matching B/P/TP, no clean/guide input."""
from pathlib import Path
import importlib.util,json
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
DC_PATH=ROOT/'tools_tmp/harmonic_response_dc_innovation_feasibility_20260930/model.py'
sp=importlib.util.spec_from_file_location('fixed_final_source_DC',DC_PATH);dc=importlib.util.module_from_spec(sp);sp.loader.exec_module(dc)
HISTORY=16;MARGIN=5;EPS=np.finfo(float).eps;MAX_CONDITION=10000.

def endpoint_weights(n):
    if not 1<=n<=HISTORY:raise ValueError('history count outside1..16')
    if n==1:return np.ones(1)
    t=np.arange(n,dtype=float);centered=t-t.mean()
    return np.ones(n)/n+centered*centered[-1]/np.dot(centered,centered)

def physical_projection(descriptor,h,w):
    if descriptor is None:return None
    freqs=descriptor['frequencies'];chosen=descriptor['chosen'];groups=descriptor['groups']
    if not freqs or len(freqs)>2 or not chosen or chosen[0]!=0 or len(set(chosen))!=len(chosen):return None
    if len(groups)!=len(freqs) or len(descriptor['original_groups'])!=len(freqs):return None
    y,x=np.indices((h,w));x=(x-(w-1)/2)/w;y=(y-(h-1)/2)/h
    full=[];physical_groups=[]
    for j,((fx,fy),group) in enumerate(zip(freqs,groups)):
        if not np.isfinite([fx,fy]).all() or len(group) not in (1,2):return None
        originals=[chosen[k] for k in group]
        if descriptor['original_groups'][j]!=[2*j+1,2*j+2] or any(k not in [2*j+1,2*j+2] for k in originals):return None
        if len(group)==2 and originals!=[2*j+1,2*j+2]:return None
        angle=2*np.pi*(fx*x+fy*y);columns=[np.cos(angle),np.sin(angle)];indices=[]
        for k in originals:
            v=columns[k-(2*j+1)];v=v-v[MARGIN:-MARGIN,MARGIN:-MARGIN].mean();indices.append(len(full));full.append(v)
        physical_groups.append(indices)
    if sorted(k for g in groups for k in g)!=list(range(1,len(chosen))):return None
    Phi=np.stack(full,-1);X=Phi[MARGIN:-MARGIN,MARGIN:-MARGIN].reshape(-1,len(full))
    u,s,vh=np.linalg.svd(X,full_matrices=False)
    if np.any(s<=64*EPS*max(float(s[0]),1.)) or s[0]/s[-1]>MAX_CONDITION:return None
    inverse=(vh.T/s)@u.T
    return dict(Phi=Phi,inverse=inverse,groups=physical_groups,singular_values=s.tolist(),condition=float(s[0]/s[-1]))

def make_reconstruction_endpoint_history(raw,P,TP,B,active,controls,source_diagnostics,descriptors,exposure=None):
    raw=np.asarray(raw);P=np.asarray(P);TP=np.asarray(TP);B=np.asarray(B);active=np.asarray(active);controls=np.asarray(controls,float)
    if raw.ndim!=4 or raw.shape[-1]!=3 or raw.dtype.kind!='f' or min(raw.shape[1:3])<13:raise ValueError('floating N,H,W,RGB')
    n,h,w,_=raw.shape
    if any(v.shape!=raw.shape for v in (P,TP,B)) or active.shape!=(n,) or controls.shape!=(n,3):raise ValueError('shape mismatch')
    frames=source_diagnostics['frames']
    if len(frames)!=n or len(descriptors)!=n:raise ValueError('source diagnostic length')
    epochs=np.asarray([r['epoch_start'] for r in frames])
    T,V,dd=dc.make_source_dc_innovation_target(raw,controls,epochs,exposure)
    C=B+active[:,None,None,None]*(P-TP);candidate=C.copy();eligible=active.copy();history=[];psi=None;previous=None;cache={};records=[];coefficient_epoch=0
    ex=None if exposure is None else np.asarray(exposure,float)
    def cut(i):
        nonlocal psi,coefficient_epoch
        history.clear();psi=None;coefficient_epoch=i
    for i in range(n):
        rec=frames[i];desc=descriptors[i];reasons=[];drec=dd['frames'][i]
        valid=bool(np.isfinite(controls[i]).all() and controls[i,0] in (0,1) and 0<=epochs[i]<=i and (i==0 or epochs[i]>=epochs[i-1]) and V[i])
        valid=bool(valid and all(np.all(np.isfinite(v[i])&(v[i]>=0)&(v[i]<=65504)) for v in (P,TP)) and np.isfinite(C[i]).all())
        if not np.all(np.isfinite(B[i])&(B[i]>=0)&(B[i]<=65504)):raise ValueError('Invalid baseline cannot serve as fallback')
        details=rec.get('atom_diagnostics',[]);key=None if desc is None else json.dumps(desc,sort_keys=True,separators=(',',':'))
        phase_used=tuple(bool(a['phase_used']) for a in details)
        if controls[i,0]:reasons.append('reset')
        if i and not np.array_equal(controls[i,1:],controls[i-1,1:]):reasons.append('jitter')
        if i and epochs[i]!=epochs[i-1]:reasons.append('source_epoch')
        if ex is not None and i and ex[i]!=ex[i-1]:reasons.append('exposure')
        if any(bool(a['innovation']) for a in details):reasons.append('source_atom_innovation')
        if drec.get('innovation',False):reasons.append('source_DC_innovation')
        identity=(key,phase_used)
        if previous is not None and identity!=previous:reasons.append('basis_or_phase_qualification')
        if reasons:cut(i)
        if not valid or not active[i]:
            candidate[i]=B[i];eligible[i]=False;cut(i+1);previous=None
            records.append(dict(frame=i,coefficient_epoch=coefficient_epoch,reason='invalid_or_inactive_exact_baseline',cut_reasons=reasons,history_count=0));continue
        if key not in cache:cache[key]=physical_projection(desc,h,w)
        projection=cache[key]
        if projection is None or len(details)!=len(projection['groups']):
            # Original C, not a numerically reconstructed O+A.
            candidate[i]=C[i];cut(i+1);previous=None
            records.append(dict(frame=i,coefficient_epoch=coefficient_epoch,reason='no_atom_or_unsupported_current_C',cut_reasons=reasons,history_count=0));continue
        theta=np.asarray([a['phase_increment'] if len(g)==2 and a['phase_used'] else 0. for a,g in zip(details,projection['groups'])],float)
        if not np.isfinite(theta).all() or any((not a['phase_used']) and a['phase_increment']!=0 for a in details):
            candidate[i]=B[i];eligible[i]=False;cut(i+1);previous=None;records.append(dict(frame=i,reason='invalid_phase_exact_baseline',history_count=0,cut_reasons=reasons));continue
        R0=C[i].astype(float);roi=R0[MARGIN:-MARGIN,MARGIN:-MARGIN];mean=roi.mean((0,1));beta=projection['inverse']@(roi-mean).reshape(-1,3)
        current=[]
        for g in projection['groups']:current.append((beta[g[0]]-1j*beta[g[1]])/2 if len(g)==2 else beta[g[0]].astype(complex))
        current=np.stack(current)
        if psi is None:psi=np.zeros(len(current))
        else:psi=psi+theta
        history.append(dict(frame=i,z=current.copy(),psi=psi.copy()))
        if len(history)>HISTORY:history.pop(0)
        weights=endpoint_weights(len(history))
        chosen=sum(weight*r['z']*np.exp(1j*(psi-r['psi']))[:,None] for weight,r in zip(weights,history))
        mean_beta=beta.copy()
        for a,g in enumerate(projection['groups']):
            if len(g)==2:mean_beta[g[0]]=2*chosen[a].real;mean_beta[g[1]]=-2*chosen[a].imag
            else:mean_beta[g[0]]=chosen[a].real
        if not np.isfinite(beta).all() or not np.isfinite(mean_beta).all():
            candidate[i]=B[i];eligible[i]=False;cut(i+1);previous=None;records.append(dict(frame=i,reason='nonfinite_fit_exact_baseline',history_count=0,cut_reasons=reasons));continue
        # Algebraic C + (Amean-Acurrent); n1 must retain the original current C bytes.
        candidate[i]=C[i] if len(history)==1 else C[i]+np.einsum('hwk,kc->hwc',projection['Phi'],mean_beta-beta)
        if not np.isfinite(candidate[i]).all():
            candidate[i]=B[i];eligible[i]=False;cut(i+1);previous=None;records.append(dict(frame=i,reason='nonfinite_reconstruction_exact_baseline',history_count=0,cut_reasons=reasons));continue
        previous=identity
        records.append(dict(frame=i,coefficient_epoch=coefficient_epoch,reason='single_observation_original_C' if len(history)==1 else 'transported_reconstruction_coefficient_endpoint_OLS',cut_reasons=reasons,
            history_count=len(history),endpoint_weights=weights.tolist(),nominal_IID_weight_square_sum=float(np.dot(weights,weights)),history_frames=[r['frame'] for r in history],phase_used=list(phase_used),theta=theta.tolist(),psi=psi.tolist(),
            current_beta=beta.tolist(),mean_beta=mean_beta.tolist(),source_descriptor=desc,projection_condition=projection['condition'],
            projection_singular_values=projection['singular_values'],interior_mean_coefficient_shift=np.einsum('hwk,kc->hwc',projection['Phi'],mean_beta-beta)[MARGIN:-MARGIN,MARGIN:-MARGIN].mean((0,1)).tolist()))
    # DC and atomic RGB fallback are exactly the already frozen application, not new rules.
    out,application=dc.apply_target(candidate,B,eligible,T,V,True)
    assert out[~active].tobytes()==B[~active].tobytes()
    assert out[~eligible].tobytes()==B[~eligible].tobytes()
    return out,dict(schema='current-reconstruction-endpoint-OLS-v1',frames=records,DC_target_diagnostics=dd,application=application,
        application_eligible=eligible.tolist(),effective_independent_observations=None,exposure_unknown=exposure is None,no_new_P_or_TP=True,history=HISTORY,polynomial_degree=1,filtered_observable='C=B+active*(P-TP)',quality_accepted=False),candidate

# Existing analyzer-compatible API; this module is a distinct law.
make_response_history=make_reconstruction_endpoint_history
