"""Authenticated CPU source-only phase pilot study; never substitutes native T(P)."""
from pathlib import Path
import hashlib,importlib.util,json,sys,inspect
import numpy as np
from phase_pilot import make_phase_aligned_pilot
ROOT=Path(__file__).resolve().parents[2];HERE=Path(__file__).resolve().parent
OLD=ROOT/'tools_tmp/factorized_pilot_feasibility_20260930';sys.path.insert(0,str(OLD))
spec=importlib.util.spec_from_file_location('frozen_helper',OLD/'analyze.py');helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
ref=helper.ref
from fsrd_response_pilot import make_temporal_spectral_pilot
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
PRE=HERE/'preregistration.json';PRE_SHA=sha(PRE);PILOT=HERE/'phase_pilot.py';PILOT_SHA=sha(PILOT)
assert PRE_SHA=='13073c7d2674f5eea721c6431589646bc4203655d1a2e3f5328a95bd644245e2'
assert PILOT_SHA=='11aa0d0d51408cecb5c6d8ae9e0d8c3b9f9b9fbf3aa174ba80885ff4b3aa4904'
def selfchecks():
 rng=np.random.default_rng(9341);y,x=np.indices((24,32));wave=.03*np.cos(2*np.pi*(3*x/32+2*y/24))
 raw=.2+wave[None,...,None]+rng.normal(0,.012,(28,24,32,3));ctrl=np.zeros((28,3));ctrl[0,0]=1
 p,a,d=make_phase_aligned_pilot(raw,ctrl);qraw=raw.copy();qraw[20:]+=.1;q,b,e=make_phase_aligned_pilot(qraw,ctrl)
 np.testing.assert_array_equal(p[:20],q[:20]);np.testing.assert_array_equal(a[:20],b[:20]);assert d['frames'][:20]==e['frames'][:20]
 np.testing.assert_allclose(p.mean((1,2)),raw.mean((1,2)),atol=1e-14)
 assert all(f['phase_qualified_frequencies']==0 for f in d['frames'][:8])
 cc=ctrl.copy();cc[10,0]=1;cc[18:,1:]=[.25,.125];pp,aa,dd=make_phase_aligned_pilot(raw,cc)
 for i in (0,10,18):
  alone,_,_=make_phase_aligned_pilot(raw[i:i+1],ctrl[:1]);np.testing.assert_array_equal(pp[i],alone[0]);assert dd['frames'][i]['preceding_observations']==0
 assert max(f['preceding_observations'] for f in dd['frames'])<=63
 assert list(inspect.signature(make_phase_aligned_pilot).parameters)==['raw','controls']
 constant=np.full((16,24,32,3),.2);q,aa,_=make_phase_aligned_pilot(constant,ctrl[:16]);np.testing.assert_allclose(q,constant,atol=1e-15)
 step=np.zeros((16,24,32,3));step[:,:,16:]=1.;q,aa,dd=make_phase_aligned_pilot(step,ctrl[:16]);assert (~aa).any();np.testing.assert_array_equal(q[~aa],step[~aa]);assert np.all(q>=0)
 return dict(no_future=True,past_only_phase_no_qualification_before8=True,reset_jitter_fresh=True,current_DC=True,history_bounded63_prior=True,no_guide_or_truth_parameter=True,constant_RGB_preserved=True,invalid_signed_Gibbs_exact_raw_inactive=True)
def detail(value,truth):
 m=helper.moments(value,truth);s=m['score'];g=s['contrast_gain'];phase=s['phase_error_radians']
 m['absolute_gain_failing_frames']=[i for i,v in enumerate(g) if v is not None and not .95<=v<=1.05]
 m['absolute_phase_failing_frames']=[i for i,v in enumerate(phase) if v is not None and v>.05]
 m['per_frame_absolute_detail_pass']=not m['absolute_gain_failing_frames'] and not m['absolute_phase_failing_frames']
 return m
def evaluate(raw,truth,controls,scene):
 phase,active,diagnostics=make_phase_aligned_pilot(raw,controls)
 hard,ha,hd=make_temporal_spectral_pilot(raw,controls,history=64)
 outputs={'raw_source':(raw,np.zeros(len(raw),bool)), 'frozen_hard_history64':(hard,ha),'phase_aligned_history64':(phase,active)};metrics={}
 for name,(p,a) in outputs.items():
  p=p.astype(np.float16).astype(np.float32)
  metrics[name]=dict(active_fraction=float(a.mean()),full=detail(p,truth),mature=detail(p[-16:],truth[-16:]),startup_first8=detail(p[:8],truth[:8]),
   invalid_pixel_fraction=float(np.mean(~np.all(np.isfinite(p)&(p>=0)&(p<=65504),axis=-1))))
 for window in ('full','mature'):
  m=metrics['phase_aligned_history64'][window]['score'];b=metrics['frozen_hard_history64'][window]['score']
  activity=float(np.mean(abs(phase-hard)>1e-5))
  metrics['phase_aligned_history64'][window]['source_only_relative_gate_against_old_hard']=ref.acceptance(m,b,activity,0,scene)
  metrics['phase_aligned_history64'][window]['STD_ratio_to_old_hard']=m['residual_temporal_std']/b['residual_temporal_std'] if b['residual_temporal_std'] else None
 return dict(metrics=metrics,phase_diagnostics=diagnostics,old_hard_active_fraction=float(ha.mean()),no_native_response_used=True)
def adversaries():
 f,h,w=64,64,96;y,x=np.indices((h,w));base=2*np.pi*(5*x/w+3*y/h);rng=np.random.default_rng(83729);noise=rng.normal(0,.012,(f,h,w,3));ctrl=np.zeros((f,3));ctrl[0,0]=1
 out=[]
 for name,angles in (('slow_constant_phase',np.arange(f)*.02),('phase_acceleration',.0015*np.arange(f)**2)):
  truth=np.broadcast_to(.2+.008*np.cos(base[None]+angles[:,None,None])[...,None],(f,h,w,3)).copy()
  out.append(dict(family=name,result=evaluate(truth+noise,truth,ctrl,name)))
 truth=np.broadcast_to(.2+.008*np.cos(base)[None,...,None],noise.shape).copy();truth[32:]=.2+1.7*(truth[32:]-.2)
 out.append(dict(family='lighting_amplitude_step',result=evaluate(truth+noise,truth,ctrl,'lighting_step')))
 reset=ctrl.copy();reset[32,0]=1;out.append(dict(family='lighting_step_reset',result=evaluate(truth+noise,truth,reset,'reset')))
 checker=np.broadcast_to(.2+.0008*((-1.)**x)[None,...,None],noise.shape).copy()
 out.append(dict(family='weak_Nyquist_startup',result=evaluate(checker+noise,checker,ctrl,'weak_material')))
 static=np.broadcast_to(.2+.008*np.cos(base)[None,...,None],noise.shape).copy();colored=noise*np.array([.5,1,2])
 out.append(dict(family='colored_RGB_noise',result=evaluate(static+colored,static,ctrl,'colored_RGB_noise')))
 bias=.008*np.cos(base)[None,...,None]*np.array([1,.8,.6]);clean=np.full_like(noise,.2)
 out.append(dict(family='persistent_correlated_source_bias',result=evaluate(clean+bias+noise,clean,ctrl,'persistent_shared_bias'),unidentifiable_clean_or_true_texture=True))
 # Guide data can change arbitrarily; API has no guide argument and consumes
 # the exact same source twice. This only establishes interface invariance.
 p,a,_=make_phase_aligned_pilot(static+noise,ctrl);q,b,_=make_phase_aligned_pilot(static+noise,ctrl);np.testing.assert_array_equal(p,q);np.testing.assert_array_equal(a,b)
 return out
def main():
 output=HERE/'results.json'
 if output.exists():raise ValueError('Preserve prior evidence')
 report=dict(schema='phase-aligned-pilot-CPU-source-feasibility-v1',quality_accepted=False,native_measured=False,native_response_reused=False,game_run=False,runtime_implemented=False,
  preregistration_sha256=PRE_SHA,prototype_sha256=PILOT_SHA,script_sha256=sha(__file__),authenticated_helper_sha256=sha(OLD/'analyze.py'),frozen_old_hard_pilot_sha256=sha(ref.TESTS/'fsrd_response_pilot.py'),metric_sha256=sha(ref.TESTS/'probe_fsrd_statistical_resolve.py'),
  self_checks=selfchecks(),rows=[],counterexamples=[],limitations=['Posthoc13 old alpha fixture families; source feasibility only, no fresh native response or game quality',
  'Guide and cleantruth excluded from estimator; cleantruth only fixture authentication/construction and scoring','Relative source gate is against frozen hard source pilot with null0; it is not native response acceptance',
  'Nominal variance excludes phase estimation uncertainty and independence unknown; colored/correlated source noise remains','Current DC forced/noise and hard threshold support churn not solved; absolute per-frame gain/phase separately recorded'])
 folder=ref.EVIDENCE/'response_temporal_spectral_alpha_holdout';rp=folder/'results.json';rh=sha(rp);native=json.loads(rp.read_text());fixture,hashes=helper.snapshot_fixture(folder,native);report['frozen_fixture_sources']=hashes
 for row in native['rows']:
  scene=row['scene'];sp=folder/scene/'sequences.npz';cp=folder/scene/'observed/frame_controls.txt';sh=sha(sp);ch=sha(cp)
  observed,data=helper.regenerate(scene,native,fixture)
  with np.load(sp) as saved:
   np.testing.assert_array_equal(observed,saved['observed']);np.testing.assert_array_equal(data['truth'],saved['clean_reference']);controls=ref.controls_from_native(cp,len(observed));np.testing.assert_array_equal(controls,data['controls'])
   result=evaluate(observed,saved['clean_reference'],controls,scene)
  assert sha(rp)==rh and sha(sp)==sh and sha(cp)==ch
  report['rows'].append(dict(scene=scene,authenticated_observed_reference_controls_exact=True,source_files_unchanged=True,provenance=dict(native_report_sha256=rh,native_sequences_sha256=sh,native_controls_sha256=ch),result=result))
  a=result['metrics']['phase_aligned_history64'];b=result['metrics']['frozen_hard_history64']
  print(scene,'matureSTD old/phase',b['mature']['score']['residual_temporal_std'],a['mature']['score']['residual_temporal_std'],'absoluteGain',a['full']['absolute_gain_min'],a['full']['absolute_gain_max'],'phase',a['full']['absolute_phase_max'],flush=True)
 report['counterexamples']=adversaries();assert sha(PRE)==PRE_SHA and sha(PILOT)==PILOT_SHA
 report['status']='completed_CPU_source_feasibility_not_solution';output.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n');print('results_sha256',sha(output),flush=True)
if __name__=='__main__':main()
