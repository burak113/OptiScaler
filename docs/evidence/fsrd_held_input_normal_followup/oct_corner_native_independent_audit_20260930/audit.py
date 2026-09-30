"""Independent byte/format/native-repeat audit. No GPU or native calls."""
import hashlib,json,re
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[2]; HERE=Path(__file__).resolve().parent
CASE=ROOT/'tools_tmp/oct_corner_native_equivalence_20260930'; E=CASE/'evidence'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def metric(a,b):
 d=b.astype(float)-a.astype(float); where=np.argwhere(d!=0); loc=np.unravel_index(np.argmax(abs(d)),d.shape)
 return dict(exact_equal=bool(np.array_equal(a,b)),rms=float(np.sqrt(np.mean(d*d))),maximum_absolute=float(abs(d[loc])),maximum_location=list(map(int,loc)),differing_values=int(np.count_nonzero(d)),first_difference=where[0].tolist() if len(where) else None,frame_rms=np.sqrt(np.mean(d*d,axis=tuple(range(1,d.ndim)))).tolist(),maximum_signed_delta=float(d[loc]))
def decode(word):
 xy=np.stack(((word&1023)/1023,((word>>10)&1023)/1023),-1)*2-1
 z=1-abs(xy).sum(-1); n=np.concatenate((xy,z[...,None]),-1); t=np.maximum(-z,0)
 n[...,:2]+=np.where(xy>=0,-t[...,None],t[...,None]);return n/np.linalg.norm(n,axis=-1,keepdims=True)
def paths(line,n):
 dec=json.JSONDecoder(); out=[]
 for _ in range(n):line=line.lstrip();v,k=dec.raw_decode(line);out.append(Path(v));line=line[k:]
 return out,list(map(int,line.split()))
rp=E/'results.json';r=json.loads(rp.read_text()); fingerprints={rp:sha(rp)}
assert r['status']=='completed_diagnostic_not_solution' and r['completed_native_contexts']==12 and r['completed_native_RR_dispatches']==768 and r['conversion_dispatches']==0
assert not r['quality_accepted'] and not r['game_run']
for p,key in ((CASE/'analyze.py','script_sha256'),(CASE/'preregistration.md','preregistration_sha256'),(Path(r['guard_source_path']),'guard_source_sha256'),(Path(r['parent_results_path']),'parent_results_sha256')):
 assert sha(p)==r[key];fingerprints[p]=sha(p)
parent=json.loads(Path(r['parent_results_path']).read_text());runner=Path(parent['runner_path']);provider=Path(parent['provider_path'])
assert sha(runner)==r['runner_sha256']==parent['runner_sha256'] and sha(provider)==r['provider_sha256']==parent['provider_sha256']
inputs=[]
for row,bpp in zip(parent['frozen_inputs'],[4,8,4,4,4,8,8]):
 p=Path(row['path']);source=Path(row['source_path']);assert sha(p)==row['sha256'] and sha(source)==row['source_sha256']
 assert p.read_bytes()==source.read_bytes()[:128*80*bpp] and p.stat().st_size==128*80*bpp
 inputs.append(dict(index=row['index'],format=row['format'],sha256=sha(p),source_sha256=sha(source),exact_original_source_frame0=True));fingerprints[p]=sha(p)
normal={arm:np.fromfile(v['path'],'<u4').reshape(v['frames'],80,128) for arm,v in r['normal_inputs'].items()}
base=normal['baseline'];alt=normal['opposite_constant'];step=normal['opposite_step']
assert not np.any(base&0xfffff);assert np.array_equal(alt,base|np.uint32(0xfffff))
assert np.array_equal(step[:32],np.repeat(base,32,0)) and np.array_equal(step[32:],np.repeat(alt,32,0))
for arm,a in normal.items():
 assert np.array_equal(a&np.uint32(0xfff00000),np.broadcast_to(base&np.uint32(0xfff00000),a.shape))
 assert np.array_equal(decode(a),np.broadcast_to([0.,0.,-1.],(*a.shape,3)))
 p=Path(r['normal_inputs'][arm]['path']);assert sha(p)==r['normal_inputs'][arm]['sha256'];fingerprints[p]=sha(p)
original_controls=(Path(r['parent_results_path']).parent/'repeat_0/dispatch_controls.bin').read_bytes()
assert hashlib.sha256(original_controls).hexdigest()==r['applied_controls_expected_sha256']
native={};run_audit=[]
for row in r['runs']:
 arm,i=row['arm'],row['repeat'];folder=E/f'{arm}_repeat{i}';job=folder/'job.txt';lines=job.read_text().splitlines()
 assert sha(job)==row['job_sha256'];first=lines[0].split(maxsplit=8);assert list(map(int,first[:8]))==[128,80,64,2,32,0,1,0] and Path(json.loads(first[8])).resolve()==provider.resolve()
 for k,(line,source) in enumerate(zip(lines[1:8],parent['frozen_inputs'])):
  p,fmt=paths(line,1); expected=Path(r['normal_inputs'][arm]['path']) if k==2 else Path(source['path']);frames=64 if k==2 and arm=='opposite_step' else 1
  assert p[0].resolve()==expected.resolve() and fmt==[source['format'],frames]
 output,rest=paths(lines[8],2);assert not rest and [p.name for p in output]==['diffuse.bin','specular.bin']
 guard=folder/'resource_guard.json';assert sha(guard)==row['guard_sha256'];g=json.loads(guard.read_text());assert g==row['guard']
 assert g['status']=='completed' and g['returncode']==0 and not g['terminated_owned_child'] and g['termination_reason'] is None
 assert g['args']==[str(runner),str(job)] and g['maximum_working_set_bytes']==2*1024**3 and g['minimum_available_memory_bytes']==1024**3 and g['timeout_seconds']==240
 for name in ('stdout','stderr'):
  p=folder/(name+'.log');assert sha(p)==row[name+'_sha256'];fingerprints[p]=sha(p)
 log=(folder/'stdout.log').read_text();assert 'debug_layer=1' in log and 'dispatches=64' in log and not (folder/'stderr.log').stat().st_size
 assert all(re.search(r'\b'+k+r'=0\b',log) for k in ('validation_errors','validation_warnings','sdk_errors','sdk_warnings'))
 controls=folder/'dispatch_controls.bin';assert controls.read_bytes()==original_controls and sha(controls)==row['applied_controls_sha256']
 u=np.frombuffer(controls.read_bytes(),'<u4').reshape(64,46);f=np.frombuffer(controls.read_bytes(),'<f4').reshape(64,46)
 np.testing.assert_array_equal(u[:,0],np.arange(64));np.testing.assert_array_equal(u[:,1],np.r_[3,np.full(63,2)]);np.testing.assert_array_equal(u[:,2:4],np.tile([128,80],(64,1)));assert not np.any(f[:,10:12])
 assert (folder/'frame_controls.txt').read_bytes()==(Path(r['parent_results_path']).parent/'repeat_0/frame_controls.txt').read_bytes()
 lobes=[]
 for name in ('diffuse','specular'):
  p=folder/(name+'.bin');assert sha(p)==row[name+'_sha256'] and p.stat().st_size==64*80*128*8
  a=np.fromfile(p,'<f2').reshape(64,80,128,4);assert np.isfinite(a).all() and not np.any(a[...,3]);lobes.append(a);fingerprints[p]=sha(p)
 native[arm,i]=np.stack(lobes,-1)
 run_audit.append(dict(arm=arm,repeat=i,job_sha256=sha(job),controls_sha256=sha(controls),raw_lobe_sha256={name:row[name+'_sha256'] for name in ('diffuse','specular')},guard_sha256=sha(guard),log_sha256=row['stdout_sha256'],alpha_all_zero=True,SDK_D3D_counts_zero=True,normal_upload_frame_count=64 if arm=='opposite_step' else 1))
 for p in (job,guard,controls,folder/'frame_controls.txt'):fingerprints[p]=sha(p)
pairs=[]
for kind in ('within_arm','cross_arm'):
 for row in r[kind]:
  arm=row['arm'];i=row['first'] if kind=='within_arm' else row['baseline_repeat'];j=row['second'] if kind=='within_arm' else row['candidate_repeat']
  a=native[arm,i] if kind=='within_arm' else native['baseline',i];b=native[arm,j]
  measured={label:metric(x,y) for label,x,y in (('RGBA',a,b),('RGB',a[...,:3,:],b[...,:3,:]),('RGB_pre32',a[:32,...,:3,:],b[:32,...,:3,:]),('RGB_post32',a[32:,...,:3,:],b[32:,...,:3,:]))}
  for label,m in measured.items():
   for key in ('exact_equal','rms','maximum_absolute','maximum_location','differing_values','first_difference','frame_rms'):assert m[key]==row[label][key]
  pairs.append(dict(kind=kind,arm=arm,first=i,second=j,**measured))
assert len(pairs)==50 and len(run_audit)==12
assert all(p['RGB']['exact_equal'] for p in pairs if p['arm']=='opposite_step' or (p['kind']=='within_arm' and p['arm']=='baseline'))
assert all(sha(p)==s for p,s in fingerprints.items())
out=dict(schema='independent-oct-opposite-corner-native-repeat-audit-v1',analysis_sha256=sha(__file__),report_sha256=sha(rp),parent_report_sha256=r['parent_results_sha256'],native_contexts=12,native_RR_dispatches=768,new_native_GPU_calls=0,quality_accepted=False,all_original_evidence_unchanged=True,runner_sha256=sha(runner),provider_sha256=sha(provider),source_inputs=inputs,normal_payloads=r['normal_inputs'],normal_RG20_only_change=True,upper12_roughness_material_bits_exact=True,all_local_sample_decoded_normals_exact_minusZ=True,runs=run_audit,pairs=pairs,
 qualifications=['Only opposite corners (0,0) and (1,1) tested natively; CPU algebra for all four corners does not prove private provider behavior.', 'Step normal has64 uploaded frames, constant arms have1. Upload scheduling differs; no universal invariance or caller/provider cause inferred.', 'Four baseline and all step contexts are byte-exact across full64 frames. One constant-arm context differs despite identical local/sample normal geometry; previous held-input variability prevents attributing this outlier to oct encoding.', 'Observed baseline repeat maximum zero is descriptive, not a statistical confidence bound. Held noisy source has no clean quality truth.', 'All raw native alpha channels are0. Their validity/semantic effect is a separate contract question.'])
out['opposite_constant_outlier_repeats']=sorted({p['second'] for p in pairs if p['kind']=='cross_arm' and p['arm']=='opposite_constant' and not p['RGB']['exact_equal']})
out['max_constant_vs_baseline_RGB_RMS']=max(p['RGB']['rms'] for p in pairs if p['kind']=='cross_arm' and p['arm']=='opposite_constant')
target=HERE/'audit.json';assert not target.exists();target.write_text(json.dumps(out,indent=2)+'\n')
print('audit_sha256',sha(target));print('outliers',out['opposite_constant_outlier_repeats'],'maxRGB',out['max_constant_vs_baseline_RGB_RMS'])
for p in pairs:
 if p['kind']=='cross_arm' and p['first']==0 and not p['RGB']['exact_equal']:print(p['arm'],p['second'],'first',p['RGB']['first_difference'],'max',p['RGB']['maximum_location'],'prepost',p['RGB_pre32']['rms'],p['RGB_post32']['rms'])
