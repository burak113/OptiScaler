"""Independent held-input hit-alpha ablation audit; no GPU/native calls."""
from pathlib import Path
import hashlib,json,re
import numpy as np
ROOT=Path(__file__).resolve().parents[2];HERE=Path(__file__).resolve().parent
CASE=ROOT/'tools_tmp/specular_hit_native_ablation_20260930';E=CASE/'evidence'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def metrics(a,b):
 d=b.astype(float)-a.astype(float);where=np.argwhere(d!=0);loc=np.unravel_index(np.argmax(abs(d)),d.shape)
 return dict(exact_equal=bool(np.array_equal(a,b)),rms=float(np.sqrt(np.mean(d*d))),maximum_absolute=float(abs(d[loc])),maximum_location=list(map(int,loc)),differing_values=int(np.count_nonzero(d)),first_difference=where[0].tolist() if len(where) else None,frame_rms=np.sqrt(np.mean(d*d,axis=tuple(range(1,d.ndim)))).tolist(),maximum_signed_delta=float(d[loc]))
def paths(line,n):
 out=[];dec=json.JSONDecoder()
 for _ in range(n):line=line.lstrip();v,k=dec.raw_decode(line);out.append(Path(v));line=line[k:]
 return out,list(map(int,line.split()))
rp=E/'results.json';r=json.loads(rp.read_text());before={rp:sha(rp)}
assert r['status']=='completed_diagnostic_not_solution' and r['completed_native_contexts']==12 and r['completed_native_RR_dispatches']==768 and r['conversion_dispatches']==0 and not r['quality_accepted'] and not r['game_run']
parent_path=Path(r['parent_report_path']);parent=json.loads(parent_path.read_text());assert sha(parent_path)==r['parent_report_sha256'];before[parent_path]=sha(parent_path)
runner=Path(parent['runner_path']);provider=Path(parent['provider_path']);assert sha(runner)==r['runner_sha256'] and sha(provider)==r['provider_sha256']
guard_source=parent_path.parents[1]/'native_resource_guard.py'
for p,key in ((CASE/'analyze.py','script_sha256'),(CASE/'preregistration.md','preregistration_sha256'),(guard_source,'guard_source_sha256')):
 assert sha(p)==r[key];before[p]=sha(p)
inputs=[]
for row,bpp in zip(parent['frozen_inputs'],[4,8,4,4,4,8,8]):
 p=Path(row['path']);origin=Path(row['source_path']);assert sha(p)==row['sha256'] and sha(origin)==row['source_sha256']
 assert p.stat().st_size==80*128*bpp and p.read_bytes()==origin.read_bytes()[:80*128*bpp]
 inputs.append(dict(index=row['index'],format=row['format'],sha256=sha(p),source_frame0_exact=True));before[p]=sha(p)
original_spec=np.fromfile(parent['frozen_inputs'][6]['path'],'<f2').reshape(80,128,4)
original_diff=np.fromfile(parent['frozen_inputs'][5]['path'],'<f2').reshape(80,128,4)
assert not original_spec[...,3].any();specular={};input_table=[]
for arm,row in r['input_specular'].items():
 p=Path(row['path']);assert sha(p)==row['sha256'] and row['frames']==1 and p.stat().st_size==80*128*8;before[p]=sha(p)
 a=np.fromfile(p,'<f2').reshape(80,128,4);assert np.array_equal(a[...,:3],original_spec[...,:3]) and np.all(a[...,3]==row['alpha']) and np.isfinite(a).all()
 # Byte-level change is restricted to offsets6,7 of each eight-byte RGBA16 texel.
 byte=np.frombuffer(p.read_bytes(),np.uint8).reshape(-1,8);old=np.frombuffer(Path(parent['frozen_inputs'][6]['path']).read_bytes(),np.uint8).reshape(-1,8)
 assert np.array_equal(byte[:,:6],old[:,:6]);specular[arm]=a
 input_table.append(dict(arm=arm,input6_alpha_unique=np.unique(a[...,3]).astype(float).tolist(),input5_alpha_unique=np.unique(original_diff[...,3]).astype(float).tolist(),RGB_bytes_exact_original=True,only_alpha_bytes6_7_may_differ=True,sha256=sha(p),frame_count=1))
controls0=(parent_path.parent/'repeat_0/dispatch_controls.bin').read_bytes();assert hashlib.sha256(controls0).hexdigest()==r['applied_controls_expected_sha256']
native={};runs=[]
for row in r['runs']:
 arm,i=row['arm'],row['repeat'];folder=E/f'{arm}_repeat{i}';job=folder/'job.txt';assert sha(job)==row['job_sha256'];lines=job.read_text().splitlines()
 first=lines[0].split(maxsplit=8);assert list(map(int,first[:8]))==[128,80,64,2,32,0,1,0] and Path(json.loads(first[8])).resolve()==provider.resolve()
 for k,(line,source) in enumerate(zip(lines[1:8],parent['frozen_inputs'])):
  p,values=paths(line,1);expected=Path(r['input_specular'][arm]['path']) if k==6 else Path(source['path']);assert p[0].resolve()==expected.resolve() and values==[source['format'],1]
 output,extra=paths(lines[8],2);assert not extra and [p.name for p in output]==['diffuse.bin','specular.bin']
 guard=folder/'resource_guard.json';assert sha(guard)==row['guard_sha256'];g=json.loads(guard.read_text());assert g==row['guard'] and g['args']==[str(runner),str(job)]
 assert g['status']=='completed' and g['returncode']==0 and not g['terminated_owned_child'] and g['termination_reason'] is None
 assert g['timeout_seconds']==240 and g['maximum_working_set_bytes']==2*1024**3 and g['minimum_available_memory_bytes']==1024**3
 for name in ('stdout','stderr'):
  p=folder/(name+'.log');assert sha(p)==row[name+'_sha256'];before[p]=sha(p)
 log=(folder/'stdout.log').read_text();assert 'debug_layer=1' in log and 'dispatches=64' in log and not (folder/'stderr.log').stat().st_size
 assert all(re.search(r'\b'+k+r'=0\b',log) for k in ('validation_errors','validation_warnings','sdk_errors','sdk_warnings'))
 controls=folder/'dispatch_controls.bin';assert controls.read_bytes()==controls0 and sha(controls)==row['applied_controls_sha256']
 u=np.frombuffer(controls0,'<u4').reshape(64,46);f=np.frombuffer(controls0,'<f4').reshape(64,46);np.testing.assert_array_equal(u[:,0],np.arange(64));np.testing.assert_array_equal(u[:,1],np.r_[3,np.full(63,2)]);np.testing.assert_array_equal(u[:,2:4],np.tile([128,80],(64,1)));assert not np.any(f[:,10:12])
 assert (folder/'frame_controls.txt').read_bytes()==(parent_path.parent/'repeat_0/frame_controls.txt').read_bytes()
 lobes=[];alphas={}
 for name in ('diffuse','specular'):
  p=folder/(name+'.bin');assert sha(p)==row[name+'_sha256'] and p.stat().st_size==64*80*128*8;before[p]=sha(p)
  a=np.fromfile(p,'<f2').reshape(64,80,128,4);assert np.isfinite(a).all();lobes.append(a);alphas[name]=np.unique(a[...,3]).astype(float).tolist();assert alphas[name]==row[name+'_alpha_unique']
 native[arm,i]=np.stack(lobes,-1)
 runs.append(dict(arm=arm,repeat=i,job_sha256=sha(job),input_formats=[x['format'] for x in inputs],all7_upload_frames1=True,applied_controls_sha256=sha(controls),SDK_D3D_counts_zero=True,guard_sha256=sha(guard),stdout_sha256=sha(folder/'stdout.log'),raw_lobe_sha256={name:row[name+'_sha256'] for name in ('diffuse','specular')},native_output_alpha_unique=alphas,output_specular_alpha_exact_input=bool(np.all(lobes[1][...,3]==specular[arm][...,3])),output_diffuse_alpha_exact_input=bool(np.all(lobes[0][...,3]==original_diff[...,3]))))
 for p in (job,guard,controls,folder/'frame_controls.txt'):before[p]=sha(p)
pairs=[]
for kind in ('within_arm','cross_arm'):
 for row in r[kind]:
  arm=row['arm'];i=row['first'] if kind=='within_arm' else row['zero_repeat'];j=row['second'] if kind=='within_arm' else row['candidate_repeat']
  a=native[arm,i] if kind=='within_arm' else native['zero_distance',i];b=native[arm,j]
  measured={name:metrics(x,y) for name,x,y in (('RGBA',a,b),('RGB',a[...,:3,:],b[...,:3,:]),('alpha',a[...,3,:],b[...,3,:]))}
  for name,m in measured.items():
   for key in ('exact_equal','rms','maximum_absolute','maximum_location','differing_values','first_difference','frame_rms'):assert m[key]==row[name][key]
  windows={name:metrics(a[start:stop,...,:3,:],b[start:stop,...,:3,:]) for name,start,stop in (('pre32',0,32),('post32',32,64))}
  pairs.append(dict(kind=kind,arm=arm,first=i,second=j,**measured,windows=windows))
assert len(pairs)==50 and len(runs)==12
assert all(p['RGB']['exact_equal'] for p in pairs if p['arm']=='sky_distance65504' or (p['arm']=='zero_distance' and p['kind']=='within_arm'))
assert all(sha(p)==s for p,s in before.items())
out=dict(schema='independent-hit-alpha-native-ablation-audit-v1',analysis_sha256=sha(__file__),report_sha256=sha(rp),parent_report_sha256=r['parent_report_sha256'],native_contexts=12,native_RR_dispatches=768,new_GPU_native_calls=0,quality_accepted=False,all_original_evidence_unchanged=True,runner_sha256=sha(runner),provider_sha256=sha(provider),inputs=inputs,input_alpha_table=input_table,runs=runs,pairs=pairs,
 conclusion='Finite positive alpha10 arm has nonzero same-input context RGB variability. Zero input alpha is not necessary for variability in this fixture/sample; no provider/caller cause, quality or production fix is established.',
 qualifications=['All7 inputs have identical formats/frame1 upload schedules across arms; only input6 alpha bytes differ. Camera/controls/tuning/provider/runner pinned.',
 'The selected positive length10 is an untraced virtual-geometry intervention. Sky65504 is the sample sentinel, not a clean quality target.',
 'Header says indirect diffuse/specular output alpha is preserved. Actual native stored alpha is0 for all arms, including positive input10/65504 and diffuse65504. This is a measured discrepancy with preserved wording in this runner/provider setup, not an established visual cause or internal implementation explanation.',
 'Four-repeat spreads and zero/sky RGB equality are descriptive, not statistical confidence or universal determinism.',
 'Composition does not consume output alpha; no quality inference from alpha equality/discrepancy alone.'])
out['finite10_outlier_repeats']=sorted({p['second'] for p in pairs if p['kind']=='cross_arm' and p['arm']=='finite_distance10' and not p['RGB']['exact_equal']})
out['maximum_finite10_cross_RGB_RMS']=max(p['RGB']['rms'] for p in pairs if p['kind']=='cross_arm' and p['arm']=='finite_distance10')
p=HERE/'audit.json';assert not p.exists();p.write_text(json.dumps(out,indent=2)+'\n');print('audit_sha256',sha(p));print('outliers',out['finite10_outlier_repeats'],'maxRGB',out['maximum_finite10_cross_RGB_RMS'])
for p in pairs:
 if p['kind']=='cross_arm' and p['first']==0 and not p['RGB']['exact_equal']:print(p['arm'],p['second'],'first',p['RGB']['first_difference'],'max',p['RGB']['maximum_location'],'prepost',p['windows']['pre32']['rms'],p['windows']['post32']['rms'])
