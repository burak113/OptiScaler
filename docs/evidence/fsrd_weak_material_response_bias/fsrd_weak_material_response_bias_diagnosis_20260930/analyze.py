"""Read-only provenance/algebra of one existing weak-material response row."""
from pathlib import Path
from datetime import datetime,timezone
import ast,hashlib,importlib.util,json
import numpy as np
ROOT=Path('F:/OptiRevelations/OptiScaler-ffxD-alpha');TMP=ROOT/'tools_tmp';HERE=Path(__file__).resolve().parent
NATIVE=TMP/'native_continuous_harmonic_remaining_20260930';END=TMP/'harmonic_reconstruction_endpoint_history_feasibility_20260930';V2=TMP/'harmonic_response_coefficient_history_feasibility_v2_20260930'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def digest(a):return hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()
def ident(p):p=Path(p);return dict(path=str(p),bytes=p.stat().st_size,sha256=sha(p))
def read(p):return json.loads(Path(p).read_text())
def save(n,v):
    content=(json.dumps(v,indent=2,allow_nan=False)+'\n').encode('utf-8')
    with(HERE/n).open('xb')as f:f.write(content)
fixturepath=ROOT/'OptiScaler/shaders/shader_tools/tests/probe_fsrd_statistical_resolve.py'
researchpath=TMP/'native_significant_phase_initial_20260930/probe_significant_phase.py'
nativepaths=[TMP/'native_continuous_harmonic_fresh_retry_20260930',NATIVE]
fixture_functions={};source_locations=[]
def extract(path,name,scope):
    source=path.read_text();tree=ast.parse(source);node=next(n for n in tree.body if isinstance(n,ast.FunctionDef)and n.name==name)
    code=compile(ast.Module(body=[node],type_ignores=[]),str(path),'exec');exec(code,scope)
    source_locations.append(dict(file=ident(path),function=name,start=node.lineno,end=node.end_lineno))
def rgba(x):return np.concatenate([x,np.ones(x.shape[:-1]+(1,),dtype=x.dtype)],axis=-1)
scope={'np':np,'rgba':rgba}
extract(fixturepath,'fixture',scope);extract(researchpath,'research_fixture',scope)
auth=read(V2/'source_authentication.json');hooks={r['scene']:r for r in auth['rows']}
assert len(hooks)==6
pins=[ident(fixturepath),ident(researchpath),ident(END/'model.py'),ident(END/'results.json'),ident(END/'weak_material_outputs.npz'),ident(V2/'source_authentication.json')]
clean_provenance=[]
for package in nativepaths:
    freeze=read(package/'pre_native_freeze.json')
    for p in [fixturepath,researchpath,package/'analyze.py']:
        expected=next(value for key,value in freeze['sources'].items()if Path(key)==p)
        assert sha(p)==expected
    snapshot=package/'evidence/source_snapshot/analyze.py'
    assert snapshot.read_bytes()==(package/'analyze.py').read_bytes();pins.extend([ident(package/'analyze.py'),ident(snapshot),ident(package/'evidence/results.json')])
for scene,hook in hooks.items():
    package=nativepaths[0]if scene=='material'else NATIVE;seq=package/'evidence'/scene/'sequences.npz'
    assert sha(seq)==hook['NPZ_sha256'];pins.append(ident(seq))
    # Only provenance regeneration: clean/raw constructor, not an estimator/native call.
    data=scope['research_fixture'](scene,128,80,64,950301)
    with np.load(seq)as z:
        truth=z['clean_reference'];observed=z['observed']
        assert truth.dtype==data['truth'].dtype and truth.tobytes()==data['truth'].tobytes()
        noise=np.random.default_rng(956432).normal(0,.012,truth.shape)
        constructed_observed=(data['truth']+noise).astype('f2').astype('f4')
        assert observed.tobytes()==constructed_observed.tobytes()
        clean_provenance.append(dict(scene=scene,clean_reference_dtype=str(truth.dtype),clean_reference_SHA=digest(truth),
            constructor_truth_bitexact=True,constructor_observed_FP16_bitexact=True,source_report_SHA=hook['source_report_SHA'],NPZ=ident(seq),
            native_context_names=['observed','null_repeat','harmonic_pilot'],clean_native_response_measured=False))
native_seq=NATIVE/'evidence/weak_material/sequences.npz';endpoint_npz=END/'weak_material_outputs.npz'
with np.load(native_seq)as z:
    values={name:z[key].copy()for name,key in [('raw','observed'),('P','pilot'),('TP','pilot_response'),('B','baseline'),('truth','clean_reference')]}
    active=z['active'].copy();storedC=z['harmonic'].copy()
with np.load(endpoint_npz)as z:values['endpoint_preDC']=z['preDC'].copy();values['endpoint_final']=z['candidate'].copy()
P,TP,B=values['P'],values['TP'],values['B']
values['D']=P-TP;values['C']=B+active[:,None,None,None]*(P-TP);assert storedC.tobytes()==values['C'].tobytes()
hook=hooks['weak_material'];descriptors=hook['descriptors'];descriptor=descriptors[8]
assert all(d==descriptor for d in descriptors[8:]) and descriptor['chosen']==[0,1] and descriptor['frequencies']==[[64.,-40.]]
sp=importlib.util.spec_from_file_location('read_only_endpoint_basis',END/'model.py');module=importlib.util.module_from_spec(sp);sp.loader.exec_module(module)
proj=module.physical_projection(descriptor,80,128);assert proj['groups']==[[0]]
# Independent complex-exponential physical basis and scalar projection.
y,x=np.indices((80,128));u=(x-63.5)/128;v=(y-39.5)/80
independent=np.exp(2j*np.pi*(64*u-40*v)).real;independent-=independent[5:-5,5:-5].mean()
np.testing.assert_allclose(proj['Phi'][...,0],independent,atol=2e-15,rtol=0)
phi=independent[5:-5,5:-5];norm=np.sum(phi**2)
beta={};mu={};residual={}
for name,value in values.items():
    roi=value[:,5:-5,5:-5].astype('float64');mu[name]=roi.mean((1,2));centered=roi-mu[name][:,None,None]
    beta[name]=np.einsum('hw,nhwc->nc',phi,centered)/norm
    residual[name]=centered-phi[None,...,None]*beta[name][:,None,None]
    check=proj['inverse']@centered.reshape(64,-1,3).transpose(1,0,2).reshape(-1,64*3)
    np.testing.assert_allclose(check.reshape(64,3),beta[name],rtol=0,atol=16*np.finfo(float).eps)
truth_beta=beta['truth'];assert np.max(abs(truth_beta-truth_beta[0]))==0
# All decompositions use scoring-only truth after stored observable arrays exist.
terms={'P_minus_truth':beta['P']-truth_beta,'B_minus_TP':beta['B']-beta['TP'],
    'active_C_minus_truth':beta['C']-truth_beta,'endpoint_shift':beta['endpoint_preDC']-beta['C'],
    'final_DC_rounding_shift':beta['endpoint_final']-beta['endpoint_preDC']}
identity=(terms['P_minus_truth']+terms['B_minus_TP'])[active]
np.testing.assert_allclose(identity,terms['active_C_minus_truth'][active],rtol=0,atol=4e-8)
law=read(END/'results.json');row=next(r for r in law['native_rows']if r['scene']=='weak_material');diags=row['diagnostics']['frames']
history_errors=[]
for i in range(8,64):
    r=diags[i];hf=r['history_frames'];weights=np.array(r['endpoint_weights']);expected=np.einsum('n,nc->c',weights,beta['C'][hf])
    error=float(np.max(abs(expected-beta['endpoint_preDC'][i])));history_errors.append(error)
assert max(history_errors)<4e-8
windows={'full':slice(None),'mature':slice(-16,None),'startup_first8':slice(0,8),'activation8to16':slice(8,16)}
summary={};identity_summaries={}
for window,sl in windows.items():
    frames=np.arange(64)[sl];summary[window]={}
    for name in values:
        b=beta[name][sl];m=mu[name][sl];err=b-truth_beta[sl];gain=b/truth_beta[sl]
        # Rank1 checker has no identifiable continuous quadrature phase. Sign flip is observable.
        phase=np.where(b*truth_beta[sl]<0,np.pi,0.)
        summary[window][name]=dict(mean_RGB=m.mean(0).tolist(),mean_bias_RGB=(m-mu['truth'][sl]).mean(0).tolist(),
            beta_mean_RGB=b.mean(0).tolist(),beta_bias_RGB=err.mean(0).tolist(),beta_temporal_variance_RGB=b.var(0).tolist(),
            gain_min_RGB=gain.min(0).tolist(),gain_max_RGB=gain.max(0).tolist(),gain_mean_RGB=gain.mean(0).tolist(),
            rank1_sign_phase_max_RGB=phase.max(0).tolist(),full_image_mean_RGB=values[name][sl].astype(float).mean((0,1,2)).tolist(),
            orthogonal_residual_temporal_variance_RGB=np.mean(np.var(residual[name][sl],axis=0),axis=(0,1)).tolist(),
            per_frame=[dict(frame=int(f),mean_RGB=mu[name][f].tolist(),beta_RGB=beta[name][f].tolist(),gain_RGB=(beta[name][f]/truth_beta[f]).tolist())for f in frames])
    active_frames=frames[active[frames]]
    if len(active_frames):
        a=terms['P_minus_truth'][active_frames];b=terms['B_minus_TP'][active_frames];e=terms['active_C_minus_truth'][active_frames]
        covariance=np.mean((a-a.mean(0))*(b-b.mean(0)),axis=0)
        identity_summaries[window]=dict(active_frames=active_frames.tolist(),source_P_bias_RGB=a.mean(0).tolist(),native_pair_B_minus_TP_bias_RGB=b.mean(0).tolist(),
            reconstruction_bias_RGB=e.mean(0).tolist(),source_P_variance_RGB=a.var(0).tolist(),native_pair_variance_RGB=b.var(0).tolist(),
            twice_covariance_RGB=(2*covariance).tolist(),reconstruction_variance_RGB=e.var(0).tolist(),
            variance_sum_RGB=(a.var(0)+b.var(0)+2*covariance).tolist(),
            endpoint_shift_bias_RGB=terms['endpoint_shift'][active_frames].mean(0).tolist(),final_DC_beta_shift_RGB=terms['final_DC_rounding_shift'][active_frames].mean(0).tolist())
np.savez_compressed(HERE/'projected_existing_terms.npz',**{'beta_'+k:v for k,v in beta.items()},**{'mean_'+k:v for k,v in mu.items()},**terms)
for p in pins:assert ident(p['path'])==p
save('report.json',dict(schema='existing-weak-material-response-bias-provenance-v1',UTC=datetime.now(timezone.utc).isoformat(),
 status='completed_read_only_algebra_diagnosis_not_causal_identification',native_GPU_calls=0,new_estimator_or_thresholds=False,
 clean_reference_provenance=clean_provenance,source_code_locations=source_locations,
 clean_reference_conclusion='All6 clean_reference arrays are bitexact constructed fixture radiance BEFORE native SDK, not native clean/oracle responses. Observed arrays are separately constructed Gaussiannoise+FP16 versions of that truth. Only observed/null/pilot native responses measured.',
 weak_recipe='unquantized float32 diffuse=.25+.0025*(2*((x+y)%2)-1), specular=.05; truth=.4*(diffuse+specular)+RGB[.08,.07,.055]. Stored guides were FP16-rounded separately; clean reference was not redefined by stored guides or SDK transfer.',
 basis=descriptor,basis_scope='Authenticated active source basis afterframe8; used as fixed scoring analysis basis retrospectively for first8 when no sourceatom was active. Rank1Nyquist means signphase0/pi only, no continuous quadrature uncertainty inferred.',
 windows=summary,active_bias_variance_identity=identity_summaries,endpoint_OLS_max_beta_error_from_saved_history=max(history_errors),
 endpoint_cut_history=[dict(frame=r['frame'],reason=r['reason'],history_frames=r.get('history_frames'),cut_reasons=r.get('cut_reasons'))for r in diags],
 exact_algebra='Foractiveframes beta(C)-beta(truth)=[beta(P)-beta(truth)]+[beta(B)-beta(TP)] up to savedFP32compositionrounding. Endpoint adds measured beta(preDC)-beta(C); finalDC adds measured beta(final)-beta(preDC). Eachvariance identity includes covariance, not independent noise percentages.',
 limitations=['Constructed truth is a radiance quality target but not a measurement of the SDK response to noiseless inputs. B-vs-truth mismatch is observed, not a proven native bias mechanism.',
 'P-vs-truth gain is a measured sourcepilot mismatch; B-minusTP is an observed paired-native contribution that mixes nativeinputnoise/nonlinearity/temporalresponse/context effects. No counterfactual holds allthose fixed independently here.',
 'Mean-term decomposition locates residualweak attenuation but cannot distinguish true native transfer, sourceendogeneity or persistentcommonbias causally.',
 'Endpointtimefit errors can be measured against currentC; static/linear invariance only under authenticatedbasis/phase/cuts. No new output or estimator run.',
 'PerRGBbeta gain/signphase is supplemental diagnosis; frozen officialluminance/Fourier metrics and acceptance remain unchanged.'],
 provenance_pins=pins,quality_accepted=False))
# Avoid self-entry: snapshot records before opening seal.
files=[ident(p)for p in sorted(HERE.iterdir())if p.is_file()]
save('completion_manifest.json',dict(files=files,source_pins=pins,self_entry_excluded=True,native_GPU_calls=0,producer_files_modified=False,quality_accepted=False))
print(json.dumps(dict(report=ident(HERE/'report.json'),manifest=ident(HERE/'completion_manifest.json'),mature=identity_summaries['mature'],mature_gain={k:summary['mature'][k]['gain_mean_RGB']for k in values},OLS_beta_error=max(history_errors))))
