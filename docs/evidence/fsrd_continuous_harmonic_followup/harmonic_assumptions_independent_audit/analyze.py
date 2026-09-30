"""Independent streamed archive/rFFT and small oracle linear-algebra audit. No GPU."""
from pathlib import Path
import hashlib, json, math
import numpy as np

ROOT=Path('F:/OptiRevelations/OptiScaler-ffxD-alpha')
ARCH=ROOT/'docs/evidence/fsrd_harmonic_model_assumptions'
HERE=Path(__file__).resolve().parent
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()
def load(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def close(a,b,rtol=2e-11,atol=2e-14):
    assert np.allclose(a,b,rtol=rtol,atol=atol),(a,b)

def rfft_pairs(rgb,window):
    h,w,_=rgb.shape
    weight=np.ones((h,w)) if window=='rectangular' else np.hanning(h)[:,None]*np.hanning(w)[None,:]
    center=(rgb-np.sum(rgb*weight[...,None],axis=(0,1))/weight.sum())*weight[...,None]
    f=np.fft.rfft2(center,axes=(0,1),norm='ortho')
    e=np.sum(np.abs(f)**2,axis=2)
    pairs=[]
    # Interior positive x owns both conjugate bins, while x boundary columns
    # contain both y partners and must collapse them explicitly.
    for x in range(w//2+1):
        boundary=x==0 or (w%2==0 and x==w//2)
        for y in range(h):
            yp=(-y)%h
            if boundary:
                if y>yp or (x==0 and y==0):continue
                pairs.append(float(e[y,x]+(e[yp,x] if y!=yp else 0)))
            else:pairs.append(float(2*e[y,x]))
    energies=np.sort(np.array(pairs))[::-1]
    total=float(energies.sum());direct=float(np.sum(center**2))
    close(total+float(e[0,0]),direct)
    return {'pairs':len(pairs),'energy':total,
            'top2':float(energies[:2].sum()/total),
            'n90':int(np.searchsorted(np.cumsum(energies),.9*total)+1)}

def archive_and_capacity():
    manifest=load(ARCH/'manifest.json');checks=[]
    for r in manifest['copied_files']:
        archived=ARCH/r['archive'];original=Path(r['source'])
        assert archived.stat().st_size==r['bytes'] and sha(archived)==r['sha256']
        assert original.stat().st_size==r['bytes'] and sha(original)==r['sha256']
        checks.append({'archive':r['archive'],'sha256':r['sha256'],'original_equal':True})
    parent=load(ARCH/'historical_source_capacity/results.json')
    rows={r['capture_id']:r for r in parent['rows']};metadata_checks=[];comparisons=[]
    for folder in sorted((ARCH/'captured_sources').iterdir()):
        md=load(folder/'capture.json')
        if md['schema_version']==1:
            assert md['capture_id'] in {r['capture_id'] for r in parent['excluded_inventory']}
            metadata_checks.append({'capture_id':md['capture_id'],'excluded':True,'schema':1})
            continue
        assert md['complete'] and md['source']=='live_gpu' and md['origin_xy']==[752,423]
        im=next(i for i in md['images'] if i['name'] in ('raw_rgb','raw_rgba'))
        path=folder/im['file'];assert sha(path)==im['sha256']
        rgba=np.fromfile(path,dtype='<f4').reshape(im['height'],im['width'],4)
        assert np.isfinite(rgba[...,:3]).all()
        rgb=rgba[...,:3].astype(np.float64);roi=rgb[25:85,5:85]
        regions={'full_crop':rgb,'historical_water_roi':roi}
        regions.update({f'roi_tile_{y}_{x}':roi[30*y:30*(y+1),40*x:40*(x+1)] for y in range(2) for x in range(2)})
        maxerr=0
        for p in rows[md['capture_id']]['records']:
            ours=rfft_pairs(regions[p['region']],p['window'])
            assert ours['pairs']==p['pair_count'] and ours['n90']==p['pairs_for_90pct']
            close(ours['energy'],p['nonDC_group_energy']);close(ours['top2'],p['topK_integer_pair_fraction']['2'])
            maxerr=max(maxerr,abs(ours['top2']-p['topK_integer_pair_fraction']['2']))
            comparisons.append({'capture_id':md['capture_id'],'region':p['region'],'window':p['window'],**ours})
        metadata_checks.append({'capture_id':md['capture_id'],'excluded':False,'raw_sha256':im['sha256'],'schema':md['schema_version'],'max_top2_absolute_error':maxerr})
    assert len(checks)==52 and len(metadata_checks)==20 and len(comparisons)==168
    water=[r for r in comparisons if r['region']=='historical_water_roi' and r['window']=='rectangular']
    assert len(water)==14
    yy,xx=np.indices((30,40));offgrid=np.cos(2*np.pi*(3.37*xx/40+2.19*yy/30))[...,None]*np.array([.3,.7,.5])
    offgrid_fraction=rfft_pairs(offgrid,'rectangular')['top2']
    close(offgrid_fraction,parent['selfchecks']['offgrid_single_clean_wave_integer_top2_fraction'])
    return {'manifest_sha256':sha(ARCH/'manifest.json'),'files':checks,'metadata':metadata_checks,
            'independent_rfft_views':comparisons,'water_top2_range':[min(r['top2'] for r in water),max(r['top2'] for r in water)],
            'water_n90_range':[min(r['n90'] for r in water),max(r['n90'] for r in water)],'independent_offgrid_top2_fraction':offgrid_fraction}

SIGMA=np.array([.012,.010,.014])
def basis(freq,h=30,w=40):
    # Complex exponential construction independent of parent's direct cos/sin.
    yy,xx=np.indices((h,w));xy=np.column_stack(((xx.ravel()-(w-1)/2)/w,(yy.ravel()-(h-1)/2)/h))
    columns=[np.ones(h*w)];derivatives=[]
    for v in freq:
        z=np.exp(2j*np.pi*(xy@v));dz=2j*np.pi*xy*z[:,None]
        columns.extend((z.real-z.real.mean(),z.imag-z.imag.mean()))
        derivatives.append(np.stack((dz.real-dz.real.mean(0),dz.imag-dz.imag.mean(0)),axis=1))
    return np.column_stack(columns),derivatives
def derive(ds,beta):return np.concatenate([np.einsum('naf,ar->nrf',d,beta[1+2*k:3+2*k]) for k,d in enumerate(ds)],axis=2)

def math_audit():
    parent=load(ARCH/'frequency_uncertainty_math/results.json');records=[]
    for row in parent['rows']:
        freq=np.array(row['true_oracle_frequency']);X,ds=basis(freq)
        mask=np.random.default_rng(718315).random(len(X))<.8;keep=[]
        for j in range(X.shape[1]):
            singular=np.linalg.svd(X[mask][:,keep+[j]],compute_uv=False)
            if singular[-1]>64*np.finfo(float).eps*singular[0]:keep.append(j)
        assert keep==row['physical_columns_retained'];D=X[mask][:,keep]
        Q,R=np.linalg.qr(D,mode='reduced');gamma=np.linalg.solve(R,np.eye(len(keep)));gamma=gamma@gamma.T
        beta=np.zeros((X.shape[1],3));beta[0]=[.3,.4,.5]
        amplitude=.1 if row['case']=='weak_one_offgrid' else 1
        for k in range(len(freq)):
            beta[1+2*k]=amplitude*np.array([.05,.035,.042])/(k+1)
            beta[2+2*k]=amplitude*np.array([-.018,.027,.011])/(k+1)
        beta[[j for j in range(len(beta)) if j not in keep]]=0
        DF=derive(ds,beta);information=np.zeros((2*len(freq),2*len(freq)))
        atom=X[:,keep].copy();atom[:,keep.index(0)]=0
        cond=float(sum(SIGMA[c]**2*np.sum((atom@gamma)*atom) for c in range(3)))
        for c in range(3):
            nuisancefree=DF[mask,c]-Q@(Q.T@DF[mask,c])
            information+=8*nuisancefree.T@nuisancefree/SIGMA[c]**2
        eigen=np.linalg.eigvalsh(information)
        close(eigen,row['frequency_information_eigenvalues'],rtol=2e-10,atol=1e-8)
        close(math.sqrt(cond/(len(X)*3)),row['nominal_conditional_current_atom_RMS'])
        envelope_min=[]
        for k in range(len(freq)):
            if 1+2*k in keep and 2+2*k in keep:
                ids=[keep.index(1+2*k),keep.index(2+2*k)];g=gamma[np.ix_(ids,ids)];sign=np.diag([1,-1])
                envelope_min.append(float(np.linalg.eigvalsh(np.eye(2)*np.linalg.eigvalsh(g)[-1]/4-sign@g@sign/4)[0]))
                assert envelope_min[-1]>-1e-15
        record={'case':row['case'],'conditional_RMS':math.sqrt(cond/(len(X)*3)),'envelope_min_eigen':envelope_min,'frequency_eigenvalues':eigen.tolist()}
        if row['frequency_information_status']=='singular_nonregular_no_inverse':
            assert eigen[-1]<=0 or eigen[0]<1e-12*max(1.,eigen[-1]);record['regular_inverse_forbidden']=True;record['uncertainty_zero_claim']=False
        else:
            cov=np.linalg.inv(information);extra=0.;fdmax=0
            Y=X@beta
            for c in range(3):
                sens=DF[:,c]-atom@np.linalg.lstsq(D,DF[mask,c],rcond=None)[0]
                extra+=float(np.sum((sens@cov)*sens))
                for j in range(2*len(freq)):
                    fplus=freq.copy();fminus=freq.copy();fplus.flat[j]+=1e-5;fminus.flat[j]-=1e-5
                    def predicted(f):
                        Z=basis(f)[0][:,keep];b=np.linalg.lstsq(Z[mask],Y[mask,c],rcond=None)[0];b[keep.index(0)]=0
                        return Z@b
                    numerical=(predicted(fplus)-predicted(fminus))/2e-5
                    fdmax=max(fdmax,float(np.max(abs(numerical-sens[:,j]))))
            close(np.sqrt(np.diag(cov)),row['nominal_past8_frequency_SE_bins'],rtol=2e-10)
            close(extra/cond,row['omitted_frequency_variance_over_conditional'],rtol=2e-10)
            assert fdmax<1e-8
            record.update(extra_over_conditional=extra/cond,refit_atom_sensitivity_FD_max=fdmax,SE_bins=np.sqrt(np.diag(cov)).tolist(),n56_common_over_conditional_mean=56*extra/cond)
        records.append(record)
    # Independent small joint Fisher inversion uses explicit per-frame/channel
    # block Jacobian and QR nuisance residual. No dense pixel projector.
    X,ds=basis([[2.37,1.19]],8,12);beta=np.array([[.3,.4,.5],[.05,.03,.04],[-.02,.04,.01]]);DF=derive(ds,beta)
    blocks=[]
    for f in range(2):
        for c in range(3):
            block=np.zeros((len(X),20));block[:,(f*3+c)*3:(f*3+c+1)*3]=X/SIGMA[c];block[:,-2:]=DF[:,c]/SIGMA[c];blocks.append(block)
    J=np.vstack(blocks);jointcov=np.linalg.inv(J.T@J);Q=np.linalg.qr(X,mode='reduced')[0];schur=np.zeros((2,2))
    for c in range(3):
        A=DF[:,c]-Q@(Q.T@DF[:,c]);schur+=2*A.T@A/SIGMA[c]**2
    error=float(np.max(abs(jointcov[-2:,-2:]-np.linalg.inv(schur)))/np.max(abs(jointcov[-2:,-2:])))
    assert error<2e-12
    history=load(ARCH/'frequency_uncertainty_math/history_implication_results.json')
    assert history['source_sha256']==sha(ARCH/'frequency_uncertainty_math/results.json')
    for r in history['rows']:
        row=next(p for p in records if p['case']==r['case']);n=r['independent_current_coefficient_observations']
        close(r['common_frequency_variance_over_conditional_mean'],row['extra_over_conditional']*n)
        close(r['nominal_conditional_average_atom_RMS'],row['conditional_RMS']/math.sqrt(n))
    truth=X@beta;perturbed=basis([[2.38,1.185]],8,12)[0]
    fitted=np.linalg.lstsq(perturbed,truth,rcond=None)[0];fitted[0]=0;A=perturbed@fitted
    residual=truth-A;closure=float(np.max(abs(A+residual-truth)))
    assert closure<2e-16
    return {'rows':records,'small_joint_Schur_relative_error':error,'history_rows_checked':len(history['rows']),
            'unfiltered_atom_plus_residual_cancellation_error':closure,
            'cancellation_scope':'Algebraic unfiltered reconstruction only; filtered residual/averaged atom need not cancel.'}

def main():
    result={'status':'completed_independent_assumption_audit_not_quality','quality_accepted':False,'GPU_used':False,
            'archive':archive_and_capacity(),'oracle_math':math_audit(),
            'limitations':['Historical raw appearance contains unknown signal and noise; integer energy concentration is not a bound on continuous atoms.',
                           'Oracle IID local covariance is conditional on known frequency and physical rank, not selected-estimator uncertainty or confidence.',
                           'At Nyquist first-order information is singular; zero uncertainty would be wrong.',
                           'Learned-frequency error is common across coefficient history; residual anticorrelation can cancel it in the final pilot.',
                           'Current prototype uses full-source sigma including heldout pixels and adaptively reuses heldout pixels for slot2; heldout acceptance is not independent.',
                           'This audit does not change prototype thresholds or score native/game quality.']}
    result['audit_source_sha256']=sha(__file__)
    (HERE/'audit.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps({'status':result['status'],'files':len(result['archive']['files']),'metadata':len(result['archive']['metadata']),'views':len(result['archive']['independent_rfft_views']),'math_cases':len(result['oracle_math']['rows']),'audit_sha256':sha(HERE/'audit.json')}))
if __name__=='__main__':main()
