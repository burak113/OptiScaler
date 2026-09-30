"""Frozen nominal-significance source-pilot CPU feasibility; no GPU/native reuse."""
from pathlib import Path
import hashlib,importlib.util,json,sys,inspect
import numpy as np
from significant_pilot import make_significant_phase_pilot
ROOT=Path(__file__).resolve().parents[2];HERE=Path(__file__).resolve().parent;FIRST=ROOT/'tools_tmp/phase_aligned_pilot_feasibility_20260930'
sys.path.insert(0,str(FIRST));s=importlib.util.spec_from_file_location('first_phase_reference',FIRST/'analyze.py');first=importlib.util.module_from_spec(s);s.loader.exec_module(first)
ref=first.ref;helper=first.helper;make_first=first.make_phase_aligned_pilot;make_hard=first.make_temporal_spectral_pilot
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
PRE=HERE/'preregistration.json';PILOT=HERE/'significant_pilot.py';PRE_SHA=sha(PRE);PILOT_SHA=sha(PILOT)
assert PRE_SHA=='2e46bd36521d9d93a5f87477954dd87b5b32a44d2d6e51eea8db0c8efd62bb11'
assert PILOT_SHA=='8c68c808482226284377734d941c95553d91e29ebfb33ede121d184585c3fa48'
def selfchecks():
 rng=np.random.default_rng(97149);y,x=np.indices((24,32));wave=.03*np.cos(2*np.pi*(3*x/32+2*y/24));raw=.2+wave[None,...,None]+rng.normal(0,.012,(72,24,32,3));ctrl=np.zeros((72,3));ctrl[0,0]=1
 p,a,d=make_significant_phase_pilot(raw,ctrl);changed=raw.copy();changed[48:]+=.1;q,b,e=make_significant_phase_pilot(changed,ctrl)
 np.testing.assert_array_equal(p[:48],q[:48]);np.testing.assert_array_equal(a[:48],b[:48]);assert d['frames'][:48]==e['frames'][:48]
 np.testing.assert_allclose(p.mean((1,2)),raw.mean((1,2)),atol=1e-14);assert max(f['preceding_observations'] for f in d['frames'])==63
 assert all(f['nominal_3SE_used_phase_frequencies']==0 for f in d['frames'][:8])
 original,_,_=make_first(raw,ctrl);np.testing.assert_array_equal(p[:8],original[:8])
 cc=ctrl.copy();cc[12,0]=1;cc[43:,1:]=[.25,.125];pp,aa,dd=make_significant_phase_pilot(raw,cc)
 for i in (0,12,43):
  alone,_,_=make_significant_phase_pilot(raw[i:i+1],ctrl[:1]);np.testing.assert_array_equal(pp[i],alone[0]);assert dd['frames'][i]['preceding_observations']==0
 assert list(inspect.signature(make_significant_phase_pilot).parameters)==['raw','controls']
 constant=np.full((16,24,32,3),.2);q,_,_=make_significant_phase_pilot(constant,ctrl[:16]);np.testing.assert_allclose(q,constant,atol=1e-15)
 binary=np.zeros_like(constant);binary[:,:,16:]=1.;q,aa,_=make_significant_phase_pilot(binary,ctrl[:16]);assert (~aa).any();np.testing.assert_array_equal(q[~aa],binary[~aa]);assert np.all(q>=0)
 return dict(no_future=True,phase_past_only_before8=True,first_phase_exact_match_before8=True,reset_jitter_fresh=True,history64=True,current_DC=True,no_guide_truth_argument=True,signed_invalid_exact_raw_inactive=True,flat_RGB_preserved=True)
def evaluate(raw,truth,ctrl,scene):
 sig,active,diagnostics=make_significant_phase_pilot(raw,ctrl);hard,ha,_=make_hard(raw,ctrl,history=64);old,oa,od=make_first(raw,ctrl)
 outputs={'raw_source':(raw,np.zeros(len(raw),bool)),'frozen_hard_history64':(hard,ha),'first_phase_history64':(old,oa),'nominal_significant_phase_history64':(sig,active)};metrics={}
 for name,(p,a) in outputs.items():
  p=p.astype(np.float16).astype(np.float32)
  metrics[name]=dict(active_fraction=float(a.mean()),full=first.detail(p,truth),mature=first.detail(p[-16:],truth[-16:]),startup_first8=first.detail(p[:8],truth[:8]),invalid_pixel_fraction=float(np.mean(~np.all(np.isfinite(p)&(p>=0)&(p<=65504),axis=-1))))
 for window in ('full','mature'):
  candidate=metrics['nominal_significant_phase_history64'][window]
  for name,base in (('frozen_hard_history64',hard),('first_phase_history64',old)):
   b=metrics[name][window]['score'];activity=float(np.mean(abs(sig-base)>1e-5));candidate['source_only_relative_gate_against_'+name]=ref.acceptance(candidate['score'],b,activity,0,scene)
   candidate['STD_ratio_to_'+name]=candidate['score']['residual_temporal_std']/b['residual_temporal_std'] if b['residual_temporal_std'] else None
 return dict(metrics=metrics,significant_diagnostics=diagnostics,first_phase_final_diagnostics=od['frames'][-1],no_native_response_used=True)
def adversaries():
 f,h,w=64,64,96;y,x=np.indices((h,w));base=2*np.pi*(5*x/w+3*y/h);rng=np.random.default_rng(83729);noise=rng.normal(0,.012,(f,h,w,3));ctrl=np.zeros((f,3));ctrl[0,0]=1;out=[]
 for name,angles in (('slow_constant_phase',np.arange(f)*.02),('phase_acceleration',.0015*np.arange(f)**2)):
  truth=np.broadcast_to(.2+.008*np.cos(base[None]+angles[:,None,None])[...,None],noise.shape).copy();out.append(dict(family=name,result=evaluate(truth+noise,truth,ctrl,name)))
 truth=np.broadcast_to(.2+.008*np.cos(base)[None,...,None],noise.shape).copy();truth[32:]=.2+1.7*(truth[32:]-.2)
 out.append(dict(family='lighting_amplitude_step',result=evaluate(truth+noise,truth,ctrl,'lighting_step')))
 reset=ctrl.copy();reset[32,0]=1;out.append(dict(family='lighting_step_reset',result=evaluate(truth+noise,truth,reset,'reset')))
 checker=np.broadcast_to(.2+.0008*((-1.)**x)[None,...,None],noise.shape).copy();out.append(dict(family='weak_Nyquist_startup',result=evaluate(checker+noise,checker,ctrl,'weak_material')))
 static=np.broadcast_to(.2+.008*np.cos(base)[None,...,None],noise.shape).copy();colored=noise*np.array([.5,1,2]);out.append(dict(family='colored_RGB_noise',result=evaluate(static+colored,static,ctrl,'colored_RGB_noise')))
 # The first seven adversaries retain exact prior package seed/constructions.
 bias=.008*np.cos(base)[None,...,None]*np.array([1,.8,.6]);clean=np.full_like(noise,.2);out.append(dict(family='persistent_correlated_source_bias',result=evaluate(clean+bias+noise,clean,ctrl,'persistent_shared_bias'),unidentifiable_clean_or_true_texture=True))
 ar=noise.copy()
 for i in range(1,f):ar[i]=.8*ar[i-1]+.6*noise[i]
 out.append(dict(family='temporal_AR_source_noise',result=evaluate(static+ar,static,ctrl,'temporal_AR_source_noise'),stationary_marginal_sigma=.012,AR=.8,nominal_IID_assumption_false=True))
 p,a,_=make_significant_phase_pilot(static+noise,ctrl);q,b,_=make_significant_phase_pilot(static+noise,ctrl);np.testing.assert_array_equal(p,q);np.testing.assert_array_equal(a,b)
 return out
def main():
 output=HERE/'results.json'
 if output.exists():raise ValueError('Preserve prior evidence')
 frozen_first={name:sha(FIRST/name) for name in ('phase_pilot.py','analyze.py','preregistration.json','results.json','compact_report.json')}
 report=dict(schema='nominal-significant-phase-CPU-source-feasibility-v1',quality_accepted=False,native_measured=False,native_response_reused=False,game_run=False,runtime_implemented=False,preregistration_sha256=PRE_SHA,prototype_sha256=PILOT_SHA,script_sha256=sha(__file__),frozen_first_package_sha256=frozen_first,
  frozen_hard_pilot_sha256=sha(ref.TESTS/'fsrd_response_pilot.py'),metric_source_sha256=sha(ref.TESTS/'probe_fsrd_statistical_resolve.py'),self_checks=selfchecks(),rows=[],counterexamples=[],
  limitations=['Posthoc13 old alpha families and source-only CPU; no new native response/cost/game acceptance', 'Truth only authenticated fixture/reference match and scoring, source and controls only estimator',
   'Nominal first-order IID uncertainty excludes nonlinear/random plugin/selection guarantees; no effectiveN or confidence proof','Oldhard currentORmean vs selectedsupport confound; firstphase selectedsupport benchmark separates this distinction',
   'Weak startup, acceleration, AR/colored/sharednoise and currentDC noise remain explicit counterexamples'])
 folder=ref.EVIDENCE/'response_temporal_spectral_alpha_holdout';rp=folder/'results.json';rh=sha(rp);native=json.loads(rp.read_text());fixture,hashes=helper.snapshot_fixture(folder,native);report['frozen_fixture_sources']=hashes
 for row in native['rows']:
  scene=row['scene'];sp=folder/scene/'sequences.npz';cp=folder/scene/'observed/frame_controls.txt';sh=sha(sp);ch=sha(cp);observed,data=helper.regenerate(scene,native,fixture)
  with np.load(sp) as saved:
   np.testing.assert_array_equal(observed,saved['observed']);np.testing.assert_array_equal(data['truth'],saved['clean_reference']);controls=ref.controls_from_native(cp,len(observed));np.testing.assert_array_equal(controls,data['controls']);result=evaluate(observed,saved['clean_reference'],controls,scene)
  assert sha(rp)==rh and sha(sp)==sh and sha(cp)==ch
  report['rows'].append(dict(scene=scene,authenticated_observed_reference_controls_exact=True,source_files_unchanged=True,provenance=dict(native_report_sha256=rh,native_sequences_sha256=sh,native_controls_sha256=ch),result=result))
  metrics=result['metrics'];a=metrics['nominal_significant_phase_history64'];print(scene,'matureSTD hard/first/sig',*(metrics[name]['mature']['score']['residual_temporal_std'] for name in ('frozen_hard_history64','first_phase_history64','nominal_significant_phase_history64')),'gain',a['full']['absolute_gain_min'],a['full']['absolute_gain_max'],'phase',a['full']['absolute_phase_max'],flush=True)
 report['counterexamples']=adversaries();assert sha(PRE)==PRE_SHA and sha(PILOT)==PILOT_SHA and all(sha(FIRST/name)==value for name,value in frozen_first.items())
 report['status']='completed_CPU_source_feasibility_not_solution';output.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n');print('results_sha256',sha(output),flush=True)
if __name__=='__main__':main()
