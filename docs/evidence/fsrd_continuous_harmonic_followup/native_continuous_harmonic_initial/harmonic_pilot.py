"""Preregistered two continuous atoms plus frozen causal residual prototype."""
from pathlib import Path
import ast, hashlib
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
FROZEN=ROOT/'tools_tmp/significant_phase_pilot_feasibility_20260930/significant_pilot.py'
FROZEN_SHA='8c68c808482226284377734d941c95553d91e29ebfb33ede121d184585c3fa48'
EPS=np.finfo(float).eps

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

class Plumbing(ast.NodeTransformer):
    def visit_Subscript(self,node):
        s=ast.unparse(node)
        if s in ('out[i]','active[i]'):
            return ast.copy_location(ast.Name('result' if s=='out[i]' else 'is_active',node.ctx),node)
        if s=='ctrl[i, 0]':return ast.copy_location(ast.parse('control[0]',mode='eval').body,node)
        if s=='ctrl[i, 1:]':return ast.copy_location(ast.parse('control[1:]',mode='eval').body,node)
        if s=='ctrl[i - 1, 1:]':return ast.copy_location(ast.parse('previous[1:]',mode='eval').body,node)
        return self.generic_visit(node)

def _build_stepper():
    assert sha(FROZEN)==FROZEN_SHA
    fn=next(n for n in ast.parse(FROZEN.read_text()).body if isinstance(n,ast.FunctionDef))
    loop=next(n for n in fn.body if isinstance(n,ast.For))
    skeleton=ast.parse('''def frozen_stepper(h,w):
 n=h*w;end=-1 if w%2==0 else None;boundary=[0]+([w//2] if w%2==0 else [])
 past=[];sigmas=[];records=[];epoch=0;i=0;previous=None
 packet=yield None
 while True:
  frame,control=packet;result=frame.copy();is_active=False
  pass
  previous=control.copy();i+=1
  packet=yield (result,is_active,records[-1])
''')
    wh=next(n for n in skeleton.body[0].body if isinstance(n,ast.While))
    point=next(i for i,n in enumerate(wh.body) if isinstance(n,ast.Pass))
    wh.body[point:point+1]=[Plumbing().visit(n) for n in loop.body]
    tree=ast.fix_missing_locations(skeleton);namespace={'np':np}
    exec(compile(tree,'frozen-significant-source-stream-plumbing','exec'),namespace)
    return namespace['frozen_stepper'],ast.unparse(tree)+'\n'

STEPPER,STEPPER_SOURCE=_build_stepper()

def stream(h,w):
    g=STEPPER(h,w);next(g);return g

def mask_for(h,w):
    y,x=np.indices((h,w),dtype=np.uint32)
    key=(x*np.uint32(73856093))^(y*np.uint32(19349663))^np.uint32(117003)
    return key%5!=0

def sigma_of(frame):
    h,w,_=frame.shape;n=h*w;F=np.fft.rfft2(frame,axes=(0,1))/n;end=-1 if w%2==0 else None
    return max(float(np.median(abs(F[:,1:end,:])))*np.sqrt(n/np.log(2)),EPS*max(1.,float(frame.max())))

def columns_for(freqs,h,w):
    y,x=np.indices((h,w));x=(x-(w-1)/2)/w;y=(y-(h-1)/2)/h
    columns=[np.ones((h,w))]; derivative=[];groups=[]
    for fx,fy in freqs:
        phase=2*np.pi*(fx*x+fy*y);c=np.cos(phase);s=np.sin(phase)
        cols=[c-c.mean(),s-s.mean()]
        dx=[-2*np.pi*x*s,2*np.pi*x*c];dy=[-2*np.pi*y*s,2*np.pi*y*c]
        dx=[v-v.mean() for v in dx];dy=[v-v.mean() for v in dy]
        groups.append([len(columns),len(columns)+1]);columns.extend(cols);derivative.append((dx,dy))
    return np.stack(columns,-1),derivative,groups

def fit_model(freqs,frames,training):
    h,w=training.shape;full,derivatives,groups=columns_for(freqs,h,w)
    X=full[training];norms=np.sum(X*X,0);chosen=[];orth=[]
    for j in range(X.shape[1]):
        v=X[:,j].copy()
        for u in orth:v-=np.dot(v,u)*u
        nv=float(np.dot(v,v))
        if nv>64*EPS*max(float(norms.max()),1.):
            chosen.append(j);orth.append(v/np.sqrt(nv))
    # Redundant candidate atoms are unsupported, not a silently smaller model.
    if any(not any(j in chosen for j in g) for g in groups):return None
    Xt=X[:,chosen];G=Xt.T@Xt
    vals=np.linalg.eigvalsh(G)
    if vals[0]<=0 or vals[-1]/vals[0]>10000:return None
    gamma=np.linalg.inv(G);Y=frames[:,training,:].transpose(1,0,2).reshape(Xt.shape[0],-1)
    beta=gamma@(Xt.T@Y);res=Y-Xt@beta
    return dict(freqs=[list(f) for f in freqs],full=full[...,chosen],Xt=Xt,gamma=gamma,beta=beta,
        residual=res,RSS=float(np.sum(res*res)),chosen=chosen,groups=[[chosen.index(j) for j in g if j in chosen] for g in groups],
        original_groups=groups,derivatives=derivatives,condition=float(vals[-1]/vals[0]))

class BudgetFailure(RuntimeError):pass

def select_model(frames,sigmas,training):
    h,w=training.shape;n=h*w;chosen=[]
    counts=dict(objective_attempts=0,factorization_attempts=0,successful_linear_matrix_refits=0,linear_scalar_RHS=0,GN_solve_attempts=0,GN_trial_attempts=0,backtracking_trials=0)
    selections=[]
    def objective(freqs):
        counts['objective_attempts']+=1;counts['factorization_attempts']+=1
        if counts['objective_attempts']>136:raise BudgetFailure('objective_budget')
        model=fit_model(freqs,frames,training)
        if model is not None:
            counts['successful_linear_matrix_refits']+=1;counts['linear_scalar_RHS']+=len(frames)*3
        return model
    # Intercept-only baseline is algebraic, not a proposal objective/refit.
    mean=frames[:,training,:].mean(1);baseline_prediction=mean[:,None,:]
    validation=~training;validation_values=frames[:,validation,:]
    baseline_RSS=float(np.sum((validation_values-baseline_prediction)**2))
    prior_model=None
    for slot in range(2):
        if prior_model is None:residual=frames-mean[:,None,None,:]
        else:
            predicted=(prior_model['full'].reshape(n,-1)@prior_model['beta']).reshape(h,w,len(frames),3).transpose(2,0,1,3)
            residual=frames-predicted
        masked=residual*training[None,...,None]
        F=np.fft.rfft2(masked,axes=(1,2))/n
        power=np.mean(np.sum(abs(F)**2,-1),0)-3*np.mean(np.asarray(sigmas)**2)*training.sum()/(n*n)
        yy=np.fft.fftfreq(h)*h;xx=np.arange(w//2+1)
        candidates=[]
        for flat in np.argsort(-power.ravel(),kind='stable'):
            iy,ix=np.unravel_index(flat,power.shape);f=np.array([xx[ix],yy[iy]],float)
            if np.linalg.norm(f)<1 or (f[0]==0 and f[1]<0):continue
            if any(np.linalg.norm(f-np.array(old))<1.5 for old in chosen+candidates):continue
            candidates.append(f.tolist())
            if len(candidates)==4:break
        best=None
        for proposal in candidates:
            local=None
            for dx in (-.5,0,.5):
                for dy in (-.5,0,.5):
                    freq=np.array(proposal)+[dx,dy]
                    legal=bool(0<=freq[0]<=w/2 and -h/2<=freq[1]<=h/2 and np.linalg.norm(freq)>=1 and not(freq[0]==0 and freq[1]<0))
                    # Illegal grid points still consume an objective slot.
                    if not legal:
                        counts['objective_attempts']+=1
                        if counts['objective_attempts']>136:raise BudgetFailure('objective_budget')
                        continue
                    fit=objective(chosen+[freq.tolist()])
                    if fit is not None and (local is None or fit['RSS']<local['RSS']):local=fit
            if local is None:continue
            for iteration in range(8):
                counts['GN_solve_attempts']+=1
                # Reuse the selected fitted coefficients/Gamma; no refit here.
                group_orig=local['original_groups'][-1];J=[]
                for axis in (0,1):
                    derivative=local['derivatives'][-1][axis];v=np.zeros_like(local['residual'])
                    for k,original_j in enumerate(group_orig):
                        if original_j in local['chosen']:
                            beta=local['beta'][local['chosen'].index(original_j)]
                            v+=derivative[k][training,None]*beta[None,:]
                    v-=local['Xt']@(local['gamma']@(local['Xt'].T@v));J.append(v)
                H=np.array([[np.sum(a*b) for b in J] for a in J]);g=np.array([np.sum(v*local['residual']) for v in J])
                if not np.isfinite(H).all() or np.linalg.eigvalsh(H)[0]<=64*EPS*max(float(np.trace(H)),1.):continue
                delta=np.clip(np.linalg.solve(H,g),-.125,.125)
                freq=np.asarray(local['freqs'][-1])+delta
                freq[0]=np.clip(freq[0],0,w/2);freq[1]=np.clip(freq[1],-h/2,h/2)
                counts['GN_trial_attempts']+=1
                if counts['GN_trial_attempts']>64:raise BudgetFailure('GN_trial_budget')
                if np.linalg.norm(freq)<1 or (freq[0]==0 and freq[1]<0):
                    counts['objective_attempts']+=1
                    if counts['objective_attempts']>136:raise BudgetFailure('objective_budget')
                    continue
                trial=objective(chosen+[freq.tolist()])
                if trial is not None and trial['RSS']<local['RSS']:local=trial
            if best is None or local['RSS']<best['RSS']:best=local
        if best is None:return None,counts,selections,'invalid_training_fit'
        Xv=best['full'][validation];pred=(Xv@best['beta']).reshape(Xv.shape[0],len(frames),3).transpose(1,0,2)
        val_RSS=float(np.sum((validation_values-pred)**2));cost=float(3*np.sum(np.asarray(sigmas)**2)*np.sum((Xv@best['gamma'])*Xv))
        accepted=bool(baseline_RSS-val_RSS>4*cost)
        selections.append(dict(slot=slot,frequency=best['freqs'][-1],training_RSS=best['RSS'],validation_baseline_RSS=baseline_RSS,
            validation_model_RSS=val_RSS,nominal_validation_prediction_noise_cost=cost,accepted=accepted,condition=best['condition'],groups=best['groups']))
        if not accepted:break
        chosen=best['freqs'];prior_model=best;baseline_RSS=val_RSS
    return prior_model,counts,selections,'selected' if prior_model is not None else 'heldout_rejected'

def current_fit(model,frame,training):
    Xt=model['Xt'];beta=model['gamma']@(Xt.T@frame[training])
    # A is nonDC only; nuisance intercept excluded from reconstruction.
    A=np.einsum('hwk,kc->hwc',model['full'][...,1:],beta[1:])
    return beta,A

def predict_atom(current,qcurrent,past,pastq,rank):
    m=len(past);theta=0.;used=False;se_used=0.
    if rank==2 and m>=8:
        old=np.stack(past);q=np.asarray(pastq);a=old[1:];b=old[:-1]
        A=float(np.mean(np.sum(abs(a)**2,-1)));B=float(np.mean(np.sum(abs(b)**2,-1)))
        qa=3*np.mean(q[1:]);qb=3*np.mean(q[:-1]);C=np.sum(a*np.conj(b))
        coherence=abs(C)/((m-1)*np.sqrt(A*B)) if A*B>0 else 0
        power=min(max(A-qa,0)/qa,max(B-qb,0)/qb)
        E=max((A+B-qa-qb)/2,0);V=E*(q[0]+q[-1])/2+3*np.sum(q[1:]*q[:-1])/2
        SE=np.sqrt(V)/abs(C) if abs(C)>0 else np.inf
        angle=float(np.angle(C));used=bool(power>16 and coherence>=.8 and abs(angle)>3*SE)
        if used:theta=angle;se_used=float(SE)
    if m:
        aligned=[z*np.exp(1j*theta*(m-j)) if rank==2 else z for j,z in enumerate(past)]
        total=sum(aligned);weighted=sum((m-j)*z for j,z in enumerate(aligned));prior=total/m;mean=(total+current)/(m+1)
        vp=(np.sqrt(sum(pastq)/(m*m))+abs(1j*weighted/m)*se_used)**2
        vm=(np.sqrt((sum(pastq)+qcurrent)/(m+1)**2)+abs(1j*weighted/(m+1))*se_used)**2
        innovation=bool(np.any(abs(current-prior)>3*np.sqrt(qcurrent+vp)))
    else:mean=current.copy();vm=np.full(current.shape,qcurrent);innovation=False
    predicted=current if innovation else mean
    return predicted,dict(phase_used=used,phase_increment=theta,nominal_phase_SE=se_used,innovation=innovation,
        rank=rank,prior_count=m,nominal_current_variance=float(qcurrent),nominal_predicted_variance_max=float(qcurrent if innovation else np.max(vm)))

def make_continuous_harmonic_pilot(raw,controls,exposure=None):
    original=np.asarray(raw);c=np.asarray(raw,float);ctrl=np.asarray(controls,float)
    if c.ndim!=4 or c.shape[-1]!=3 or not len(c) or min(c.shape[1:3])<8 or original.dtype.kind!='f':raise ValueError('Floating NxHxWx3 >=8 required')
    if ctrl.shape!=(len(c),3):raise ValueError('Nx3 reset/jitter controls')
    exp=None if exposure is None else np.asarray(exposure,float)
    if exp is not None and exp.shape!=(len(c),):raise ValueError('N exposure metadata')
    nf,h,w,_=c.shape;training=mask_for(h,w);out=original.copy();active=np.zeros(nf,bool)
    state={};records=[];epoch=0;total_counts=dict(objective_attempts=0,GN_trial_attempts=0,factorization_attempts=0,successful_linear_matrix_refits=0,linear_scalar_RHS=0,
        GN_solve_attempts=0,backtracking_trials=0,current_coefficient_RHS=0,background_FFT_steps=0,residual_FFT_steps=0)
    def clear(i):
        nonlocal epoch
        epoch=i;state.clear();state.update(raws=[],sigmas=[],selection_done=False,model=None,atoms=[],background=stream(h,w),residual=None)
    clear(0)
    for i,frame in enumerate(c):
        metadata=bool(np.isfinite(ctrl[i]).all() and ctrl[i,0] in (0,1))
        exposure_valid=bool(exp is None or np.isfinite(exp[i]) and exp[i]>0)
        changed=bool(exp is not None and i and exp[i]!=exp[i-1])
        reset=bool(metadata and ctrl[i,0]);jitter=bool(i and not np.array_equal(ctrl[i,1:],ctrl[i-1,1:]))
        if reset or jitter:clear(i)
        valid=bool(np.isfinite(frame).all() and frame.min()>=0 and frame.max()<=65504 and np.all(frame.mean((0,1))>1e-4))
        rec=dict(frame=i,epoch_start=epoch,reset=reset,jitter_changed=jitter,exposure_unknown=exp is None,exposure_changed=changed,active=False,
            selection=None,atom_frequencies=[],atom_diagnostics=[],raw_passthrough=False,reason=None)
        if not metadata or not exposure_valid or changed or not valid:
            rec.update(raw_passthrough=True,reason='unsupported_source_or_metadata_exact_raw');records.append(rec);clear(i+1);continue
        sigma=sigma_of(frame);localctrl=ctrl[i].copy()
        if not state['raws']:localctrl[0]=1
        fallback,fa,fd=state['background'].send((frame,localctrl));total_counts['background_FFT_steps']+=1
        warmup=len(state['raws'])<8 and not state['selection_done']
        if warmup:
            rec.update(raw_passthrough=True,reason='first8_exact_raw_warmup',preceding_sources=len(state['raws']))
        else:
            if not state['selection_done']:
                try:
                    model,counts,selection,reason=select_model(np.stack(state['raws'][-8:]),state['sigmas'][-8:],training)
                except BudgetFailure as error:
                    rec.update(raw_passthrough=True,reason=str(error)+'_exact_raw_epoch_cut');records.append(rec);clear(i+1);continue
                for key,value in counts.items():total_counts[key]+=value
                state['model']=model;state['selection_done']=True
                rec['selection']=dict(counts=counts,candidates=selection,reason=reason)
                if reason=='invalid_training_fit':
                    rec.update(raw_passthrough=True,reason='invalid_training_fit_exact_raw_epoch_cut');records.append(rec);clear(i+1);continue
                if model is not None:
                    state['residual']=stream(h,w);state['atoms']=[dict(past=[],q=[]) for _ in model['groups']]
            model=state['model']
            if model is None:
                prediction=fallback;okay=bool(fa)
                rec.update(reason='no_atom_frozen_source_fallback',no_atom_prior_observations=fd['preceding_observations'])
            else:
                beta,A=current_fit(model,frame,training);total_counts['current_coefficient_RHS']+=3
                if not np.isfinite(beta).all():
                    rec.update(raw_passthrough=True,reason='invalid_current_fit_exact_raw');records.append(rec);clear(i+1);continue
                predicted_beta=beta.copy()
                for j,(indices,history) in enumerate(zip(model['groups'],state['atoms'])):
                    rank=len(indices);Gamma=model['gamma'][np.ix_(indices,indices)]
                    current=(beta[indices[0]]-1j*beta[indices[1]])/2 if rank==2 else beta[indices[0]].copy()
                    q=sigma*sigma*(np.linalg.eigvalsh(Gamma).max()/2 if rank==2 else Gamma[0,0])
                    selected,diagnostics=predict_atom(current,q,history['past'],history['q'],rank);rec['atom_diagnostics'].append(diagnostics)
                    if rank==2:predicted_beta[indices[0]]=2*selected.real;predicted_beta[indices[1]]=-2*selected.imag
                    else:predicted_beta[indices[0]]=selected
                    history['past'].append(current);history['q'].append(q)
                    if len(history['past'])>=64:history['past'].pop(0);history['q'].pop(0)
                Ahat=np.einsum('hwk,kc->hwc',model['full'][...,1:],predicted_beta[1:])
                R=frame-A;carrier=max(0.,1e-4-float(R.min()));encoded=R+carrier
                if not np.isfinite(encoded).all() or encoded.min()<0 or encoded.max()>65504:
                    rec.update(raw_passthrough=True,reason='invalid_residual_carrier_exact_raw');records.append(rec);clear(i+1);continue
                residualctrl=ctrl[i].copy()
                if not rec['atom_diagnostics'] or rec['atom_diagnostics'][0]['prior_count']==0:residualctrl[0]=1
                residual,ra,rd=state['residual'].send((encoded,residualctrl));total_counts['residual_FFT_steps']+=1
                prediction=residual-carrier+Ahat;okay=bool(ra and np.isfinite(prediction).all() and prediction.min()>=0 and prediction.max()<=65504)
                rec.update(reason='harmonic_plus_frozen_residual',atom_frequencies=model['freqs'],atom_column_indices=model['groups'],
                    carrier=carrier,source_sigma=sigma,residual_nominal_sigma=rd['nominal_iid_pixel_sigma'],
                    residual_prior_observations=rd['preceding_observations'],conditional_coefficient_covariance=(sigma*sigma*model['gamma']).tolist(),
                    numerical_condition=model['condition'])
            if okay:
                out[i]=prediction;active[i]=True;rec['active']=True
                rec['precast_current_DC_max_error']=float(abs(prediction.mean((0,1))-frame.mean((0,1))).max())
            else:
                rec.update(raw_passthrough=True,reason='invalid_prediction_exact_raw_epoch_cut');records.append(rec);clear(i+1);continue
        state['raws'].append(frame.copy());state['sigmas'].append(sigma)
        if len(state['raws'])>64:state['raws'].pop(0);state['sigmas'].pop(0)
        records.append(rec)
    return out,active,dict(schema='continuous-harmonic-source-CPU-v2',history=64,capacity=2,frames=records,total_counts=total_counts,
        mask_sha256=hashlib.sha256(training.astype('u1').tobytes()).hexdigest(),training_pixels=int(training.sum()),validation_pixels=int((~training).sum()),
        frozen_residual_source_sha256=FROZEN_SHA,stream_adapter_sha256=hashlib.sha256(STEPPER_SOURCE.encode()).hexdigest(),
        raw_dtype_preserved=str(original.dtype),exposure_unknown=exp is None,no_clean_truth_input=True,guide_inputs=False,
        quality_accepted=False,native_measured=False,effective_independent_pixels=None)
