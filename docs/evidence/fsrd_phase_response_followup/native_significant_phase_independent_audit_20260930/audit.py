"""Independent finalized fresh native significant-phase audit; no GPU calls."""
from pathlib import Path
import hashlib,json,ast,re,sys,importlib.util
import numpy as np
ROOT=Path(__file__).resolve().parents[2];HERE=Path(__file__).resolve().parent;CASE=ROOT/'tools_tmp/native_significant_phase_initial_20260930';E=CASE/'evidence'
OLD=ROOT/'tools_tmp/factorized_pilot_feasibility_20260930';sys.path.insert(0,str(OLD));s=importlib.util.spec_from_file_location('fixture_helpers',OLD/'analyze.py');helper=importlib.util.module_from_spec(s);s.loader.exec_module(helper);ref=helper.ref
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def paths(line,n):
 out=[];dec=json.JSONDecoder()
 for _ in range(n):line=line.lstrip();v,k=dec.raw_decode(line);out.append(Path(v));line=line[k:]
 return out,list(map(int,line.split()))
def expanded(p,fmt,frames):
 dtype={41:'<f4',10:'<f2',24:'<u4',28:'u1'}[fmt];channels={41:1,10:4,24:1,28:4}[fmt]
 a=np.fromfile(p,dtype).reshape(frames,80,128,channels)
 return np.broadcast_to(a,(64,80,128,channels)) if frames==1 else a
rp=E/'results.json';r=json.loads(rp.read_text());before={rp:sha(rp)}
assert r['status']=='completed_research_not_solution' and r['amd_completed_sequences']==18 and len(r['rows'])==6
assert r['pilot_mode']=='significant_phase' and r['history']==64 and r['size']==[128,80] and r['frames']==64 and r['seed']==950301
assert r['split_strength']==1 and r['noise_sigma']==.012 and r['noise_distribution']=='gaussian' and r['radiance_fallback_registered']
assert not r['quality_accepted'] and not r['runtime_implemented'] and not r['game_run']
runner=Path(r['runner_path']);provider=ROOT/'external/FidelityFX-SDK-v2/Kits/FidelityFX/signedbin/amd_fidelityfx_denoiser_dx12.dll'
assert sha(runner)==r['runner_sha256']=='3427689a4764380f885545c353250277e4d71944d3310c8a17b3cbba0f3c21d2' and sha(provider)==r['native_provider_sha256']
for name,value in r['source_sha256'].items():p=E/'source_snapshot'/name;assert sha(p)==value;before[p]=value
assert sha(E/'source_snapshot/significant_pilot.py')==r['pilot_prototype_sha256'] and sha(E/'source_snapshot/probe_significant_phase.py')==r['actual_research_driver_sha256']
spec=importlib.util.spec_from_file_location('native_snapshot_pilot',E/'source_snapshot/significant_pilot.py');pilot_module=importlib.util.module_from_spec(spec);spec.loader.exec_module(pilot_module)
fixture,fixture_hashes=helper.snapshot_fixture(E,r)
namespace={'np':np};tree=ast.parse((E/'source_snapshot/probe_significant_phase.py').read_text())
for name in ('dc_conservation','radiance_fallback'):
 node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name);exec(compile(ast.Module(body=[node],type_ignores=[]),str(E/'source_snapshot/probe_significant_phase.py'),'exec'),namespace)
rows=[];contexts=[]
for row in r['rows']:
 scene=row['scene'];folder=Path(row['evidence_directory']);sp=folder/'sequences.npz';before[sp]=sha(sp)
 assert row['provenance']=={'reused_npz':None} and row['null_repeat_saved'] and not (folder/'oracle_pilot').exists()
 actual={};control_bytes=[]
 for context in ('observed','null_repeat','blind_pilot'):
  f=folder/context;mp=f/'amd_context_identity.json';m=json.loads(mp.read_text());proc=json.loads((f/'runner_process.json').read_text());g=json.loads((f/'resource_guard.json').read_text());job=f/'job.txt';lines=job.read_text().splitlines()
  assert m['runner_sha256']==sha(runner)==proc['runner_sha256'] and m['dll_sha256']==sha(provider)
  assert m['dimensions']==[128,80] and m['frames']==64 and m['signals']==[2,32] and m['tuning']==1 and m['reset_every']==m['passthrough']==0
  assert m['tuning_values']==[.1,.5,.5,40000.,40.,.5] and proc['returncode']==0 and sha(f/'runner.log')==proc['log_sha256']
  assert g['status']=='completed' and g['returncode']==0 and not g['terminated_owned_child'] and g['termination_reason'] is None and g['args']==[str(runner),str(job)]
  assert g['maximum_working_set_bytes']==2*1024**3 and g['minimum_available_memory_bytes']==1024**3 and g['timeout_seconds']==240 and g['sample_interval_seconds']==.2
  log=(f/'runner.log').read_text();assert 'debug_layer=1' in log and 'dispatches=64' in log and all(re.search(r'\b'+k+r'=0\b',log) for k in ('validation_errors','validation_warnings','sdk_errors','sdk_warnings'))
  assert (f/'runner.log').read_text()==(f/'stdout.log').read_text()+(f/'stderr.log').read_text() and not (f/'stderr.log').stat().st_size
  first=lines[0].split(maxsplit=8);assert list(map(int,first[:8]))==[128,80,64,2,32,0,1,0] and Path(json.loads(first[8])).resolve()==provider.resolve()
  arrays=[];input_info=[]
  for k,(line,fmt) in enumerate(zip(lines[1:8],[41,10,24,28,28,10,10])):
   p,v=paths(line,1);assert p[0].resolve()==(f/f'input{k}.bin').resolve() and v[0]==fmt and v[1] in (1,64) and sha(p[0])==m['inputs'][p[0].name]
   a=expanded(p[0],fmt,v[1]);assert np.isfinite(a).all();arrays.append(a);before[p[0]]=sha(p[0]);input_info.append(dict(index=k,format=fmt,frames=v[1],sha256=sha(p[0])))
  p,extra=paths(lines[8],2);assert not extra and [x.name for x in p]==['diffuse.bin','specular.bin']
  outputs={}
  for name in ('diffuse','specular'):
   p=f/(name+'.bin');assert sha(p)==m['output_sha256'][p.name] and p.stat().st_size==64*80*128*8
   outputs[name]=np.fromfile(p,'<f2').reshape(64,80,128,4);assert np.isfinite(outputs[name]).all();before[p]=sha(p)
  cb=f/'dispatch_controls.bin';raw=cb.read_bytes();assert sha(cb)==m['applied_dispatch_sha256'] and len(raw)==64*184;control_bytes.append(raw)
  u=np.frombuffer(raw,'<u4').reshape(64,46);fl=np.frombuffer(raw,'<f4').reshape(64,46);controls=np.loadtxt(f/'frame_controls.txt',ndmin=2)
  np.testing.assert_array_equal(u[:,0],np.arange(64));np.testing.assert_array_equal(u[:,1],2+controls[:,0]);np.testing.assert_array_equal(u[:,2:4],np.tile([128,80],(64,1)));np.testing.assert_array_equal(fl[:,10:12],controls[:,1:].astype(np.float32))
  assert not (f/'camera.txt').exists()
  actual[context]=dict(inputs=arrays,outputs=outputs)
  contexts.append(dict(scene=scene,context=context,manifest_sha256=sha(mp),raw_inputs=input_info,output_sha256=m['output_sha256'],applied_controls_sha256=sha(cb),guard_sha256=sha(f/'resource_guard.json'),runner_log_sha256=sha(f/'runner.log'),ordinary_debug_zero_SDK_D3D=True,output_alpha_unique={k:np.unique(a[...,3]).astype(float).tolist() for k,a in outputs.items()}))
  for p in (mp,job,cb,f/'runner_process.json',f/'resource_guard.json',f/'runner.log',f/'stdout.log',f/'stderr.log',f/'frame_controls.txt'):before[p]=sha(p)
 assert control_bytes[0]==control_bytes[1]==control_bytes[2]
 source=actual['observed']['inputs'];null=actual['null_repeat']['inputs'];counter=actual['blind_pilot']['inputs']
 assert all(np.array_equal(a,b) for a,b in zip(source,null))
 assert all(np.array_equal(source[k],counter[k]) for k in (0,1,2))
 assert all(np.array_equal(source[k][...,:3],counter[k][...,:3]) for k in (3,4))
 assert all(np.array_equal(source[k][...,3],counter[k][...,3]) for k in (5,6))
 observed,data=helper.regenerate(scene,r,fixture)
 with np.load(sp) as saved:
  np.testing.assert_array_equal(observed,saved['observed']);np.testing.assert_array_equal(data['truth'],saved['clean_reference']);controls=ref.controls_from_native(folder/'observed/frame_controls.txt',64);np.testing.assert_array_equal(controls,data['controls'])
  P,active,d=pilot_module.make_significant_phase_pilot(observed,controls);d['epoch_start_by_frame']=[f['epoch_start'] for f in d['frames']];P=P.astype(np.float16).astype(np.float32)
  np.testing.assert_array_equal(P,saved['pilot']);np.testing.assert_array_equal(active,saved['active']);assert d==row['pilot_diagnostics']
  B=saved['baseline'];TP=saved['pilot_response'];repeat=saved['null_repeat'];truth=saved['clean_reference']
  null_rms=float(np.sqrt(np.mean((B-repeat)**2)));assert null_rms==row['null_rms']
  blind=B+active[:,None,None,None]*(P-TP)
  variants={'significant_phase':blind,'significant_phase_dc':namespace['dc_conservation'](blind,observed,active,controls,64,d['epoch_start_by_frame']),'significant_phase_dc_current':namespace['dc_conservation'](blind,observed,active,controls,1)}
  fallback={}
  for name,value in list(variants.items()):variants[name+'_safe'],fallback[name+'_safe']=namespace['radiance_fallback'](value,B)
  base_full=ref.score(B,truth,None);base_mature=ref.score(B[-16:],truth[-16:],None);assert base_full==row['baseline_full'] and base_mature==row['baseline_mature'];measured={}
  for name,value in variants.items():
   np.testing.assert_array_equal(value,saved[name]);record=row['variants'][name];activity=float(np.mean(abs(value-B)>1e-5));full=ref.score(value,truth,None);mature=ref.score(value[-16:],truth[-16:],None)
   fg=ref.acceptance(full,base_full,activity,null_rms,scene);mg=ref.acceptance(mature,base_mature,activity,null_rms,scene)
   if not np.isfinite(value).all() or np.any(value<0):
    for gate in (fg,mg):gate['failures'].append('invalid_radiance');gate['nonregression']=gate['effective_success']=False
   assert full==record['full'] and mature==record['mature'] and fg==record['full_gate'] and mg==record['mature_gate'] and activity==record['activity'] and fallback.get(name,0)==record['baseline_fallback_pixel_fraction']
   gain=[g for g in full['contrast_gain'] if g is not None];phase=[p for p in full['phase_error_radians'] if p is not None]
   measured[name]=dict(full_gate=fg,mature_gate=mg,activity=activity,baseline_fallback_fraction=fallback.get(name,0),invalid_RGB_pixel_fraction=float(np.mean(~np.all(np.isfinite(value)&(value>=0)&(value<=65504),-1))),
    actual_full_STD=full['residual_temporal_std'],baseline_full_STD=base_full['residual_temporal_std'],actual_mature_STD=mature['residual_temporal_std'],baseline_mature_STD=base_mature['residual_temporal_std'],
    full_RGB_bias=full['bias_rgb'],full_gain_range=[min(gain),max(gain)] if gain else None,full_absolute_phase_max=max(phase) if phase else None,
    full_absolute_gain_failing_frames=[i for i,g in enumerate(full['contrast_gain']) if g is not None and not .95<=g<=1.05],full_absolute_phase_failing_frames=[i for i,p in enumerate(full['phase_error_radians']) if p is not None and p>.05],
    mature_gain_range=[min(g for g in mature['contrast_gain'] if g is not None),max(g for g in mature['contrast_gain'] if g is not None)] if gain else None,
    mature_absolute_phase_max=max(p for p in mature['phase_error_radians'] if p is not None) if phase else None,
    full_RMSE=full['rmse'],baseline_full_RMSE=base_full['rmse'],mature_RMSE=mature['rmse'],baseline_mature_RMSE=base_mature['rmse'])
 rows.append(dict(scene=scene,npz_sha256=sha(sp),null_rms=null_rms,mature_null_rms=float(np.sqrt(np.mean((B[-16:]-repeat[-16:])**2))),observed_pilot_reference_controls_regenerated_exact=True,algebra_variants_exact=True,source_null_all7_equal=True,counterfactual_motion_normal_depth_guideRGB_rayalpha_equal=True,
  native_albedo_alpha_changed_pixels={str(k):int(np.count_nonzero(source[k][...,3]!=counter[k][...,3])) for k in (3,4)},variants=measured))
assert all(sha(p)==v for p,v in before.items())
out=dict(schema='fresh-native-significant-phase-initial-independent-audit-v1',analysis_sha256=sha(__file__),final_results_sha256=sha(rp),native_contexts=18,native_RR_dispatches=1152,new_GPU_native_calls=0,quality_accepted=False,all_original_evidence_unchanged=True,pilot_prototype_sha256=r['pilot_prototype_sha256'],driver_sha256=r['actual_research_driver_sha256'],runner_sha256=sha(runner),provider_sha256=sha(provider),fixture_snapshot_sha256=fixture_hashes,contexts=contexts,rows=rows,
 qualifications=['Initial6 families only; full13, correlated bias/noise, historic geometry, real game and runtime/cost remain open.',
 'Actual native7 input/lobe/control/log bytes retained and authenticated. Converter/composition shader job.txt retained, but CB/17input/8output files deleted by standard worker; composed NPZ response not independently redecoded from those missing GPU bytes.',
 'NPZ algebra, pilot/source/reference/control regeneration and scoring recomputed exactly. No old native source/TP or oracle reused.',
 'Consumed guide RGB and ray alpha invariant; guide alpha may carry nonconsumed conversion metadata and differs. Formats/frame counts are recorded per context; private implementation behavior not inferred.',
 'Relative1e-4 STD gate tolerance is not actual noise reduction. Every-frame absolute gain/phase, real STD againstbaseline and null spread separately reported.',
 'Pilot diagnostics native_measuredFalse belong to source estimator; later18 logs/raw outputs prove distinct fresh native measurement, not quality acceptance.'])
target=HERE/'audit.json';assert not target.exists();target.write_text(json.dumps(out,indent=2)+'\n');print('audit_sha256',sha(target))
for row in rows:
 v=row['variants']['significant_phase_dc_current_safe'];print(row['scene'],'gates',v['full_gate']['failures'],v['mature_gate']['failures'],'matureSTD base/candidate',v['baseline_mature_STD'],v['actual_mature_STD'],'gain',v['full_gain_range'],'phase',v['full_absolute_phase_max'],'null',row['null_rms'])
