"""Read-only fixed-input four-context native repeat audit; no native/GPU calls."""
import hashlib,json,re
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[2];HERE=Path(__file__).resolve().parent
CASE=ROOT/'tools_tmp/frozen_source_context_repeat_20260930';STUDY=CASE/'evidence'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def metrics(a,b):
    d=np.asarray(b,float)-np.asarray(a,float);where=np.argwhere(d!=0);peak=np.unravel_index(np.argmax(abs(d)),d.shape)
    return dict(exact_equal=bool(np.array_equal(a,b)),rms=float(np.sqrt(np.mean(d*d))),maximum_absolute=float(abs(d[peak])),
        maximum_location=list(map(int,peak)),maximum_signed_delta=float(d[peak]),maximum_old_value=float(a[peak]),maximum_new_value=float(b[peak]),
        differing_values=int(np.count_nonzero(d)),first_difference=where[0].tolist() if len(where) else None,
        frame_rms=np.sqrt(np.mean(d*d,axis=tuple(range(1,d.ndim)))).tolist(),
        RGB_bias=(d.mean(tuple(range(d.ndim-1))).tolist() if d.ndim==4 else None))
def parse_json_path(line,n):
    # Native job uses C++ std::quoted paths with forward slashes; JSON-compatible.
    decoder=json.JSONDecoder();values=[]
    for _ in range(n):line=line.lstrip();p,end=decoder.raw_decode(line);values.append(Path(p));line=line[end:]
    return values,list(map(int,line.split()))
rp=STUDY/'results.json';before=sha(rp);r=json.loads(rp.read_text())
assert r['status']=='completed_diagnostic_not_solution' and not r['quality_accepted'] and not r['game_run']
assert r['completed_native_contexts']==4 and r['completed_native_RR_dispatches']==256 and r['conversion_dispatches']==0
assert sha(CASE/'analyze.py')==r['script_sha256'] and sha(CASE/'native_resource_guard.py')==r['guard_source_sha256']
assert sha(CASE/'preregistration.md')==r['preregistration_sha256']
runner=Path(r['runner_path']);provider=Path(r['provider_path']);assert sha(runner)==r['runner_sha256'] and sha(provider)==r['provider_sha256']
old=ROOT/'tools_tmp/default_tuning_context_repeat_20260930';failure=old/'failure.json';assert sha(failure)==r['source_failure_report_sha256']
previous=json.loads(failure.read_text());fingerprints={rp:before,failure:sha(failure)}
for name,row in previous['retained_files'].items():
    p=old/name;assert p.stat().st_size==row['size'] and sha(p)==row['sha256'];fingerprints[p]=sha(p)
inputs=[]
for row,bpp in zip(r['frozen_inputs'],[4,8,4,4,4,8,8]):
    p=Path(row['path']);source=Path(row['source_path']);assert sha(p)==row['sha256'] and sha(source)==row['source_sha256']
    assert p.read_bytes()==source.read_bytes()[:128*80*bpp] and row['source_frame']==0 and row['frames']==1 and p.stat().st_size==row['size']==128*80*bpp
    inputs.append(dict(index=row['index'],format=row['format'],source_sha256=sha(source),frozen_first_frame_sha256=sha(p),first_frame_exact=True))
    fingerprints[p]=sha(p)
snapshot=Path('C:/Users/burak/.codex/visualizations/2026/09/29/01a0eeeb-48a8-7733-add1-58a3bd1f37ce/response_soft_temporal_long_alpha_fresh/source_snapshot/fsrd_rr_runner.cpp')
source=snapshot.read_text();assert 'if(frame&&t.frames==1) continue;' in source
assert 'values[6]={.1f,.5f,.5f,40000.f,40.f,.5f}' in source.replace(' ','') or '40000.f' in source
guard_source=(CASE/'native_resource_guard.py').read_text()
assert 'working_set(process)' in guard_source and 'int(process._handle)' in guard_source and 'process.terminate()' in guard_source
assert 'GetCim' not in guard_source
audit=dict(schema='fixed-seven-input-pinned-four-context-independent-audit-v1',analysis_sha256=sha(__file__),report_sha256=before,
    native_contexts=4,native_RR_dispatches=256,new_GPU_or_native_calls=0,quality_accepted=False,
    runner_sha256=sha(runner),provider_sha256=sha(provider),pinned_runner_source_snapshot_sha256=sha(snapshot),frozen_input_authentication=inputs,runs=[],pairs=[],
    qualifications=['All seven actual textures are held fixed at source frame0. This is not clean radiance, IID history, game quality or a stain/wave acceptance test.',
        'The pinned runner frames=1 path uploads each input once and skips later uploads; this also differs in upload schedule from full64 dynamic inputs.',
        'Native frame index advances and first-frame reset is retained. Operator history can mature despite fixed inputs; context-pair differences are the measured issue.',
        'Four-context ranges are descriptive. No caller/provider cause, statistical confidence, determinism proof, or production fix is inferred.',
        'Resource guard samples owned-child working set/free memory every.2s. Observed peaks are sampled values, not a hard OS memory limit or bound on unobserved transient peaks. Ordinary debug layer is not GPU-based validation.'])
native=[]
original_controls=(old/'evidence/repeat_0/dispatch_controls.bin').read_bytes()
assert hashlib.sha256(original_controls).hexdigest()==r['applied_controls_expected_sha256']
for record in r['runs']:
    i=record['run'];folder=STUDY/f'repeat_{i}';job=folder/'job.txt';assert sha(job)==record['job_sha256']
    lines=job.read_text().splitlines();first=lines[0].split(maxsplit=8);assert list(map(int,first[:8]))==[128,80,64,2,32,0,1,0]
    assert Path(json.loads(first[8])).resolve()==provider.resolve()
    for row,line in zip(r['frozen_inputs'],lines[1:8]):
        p,values=parse_json_path(line,1);assert p[0].resolve()==Path(row['path']).resolve() and values==[row['format'],1]
    outpaths,extra=parse_json_path(lines[8],2);assert not extra and [p.name for p in outpaths]==['diffuse.bin','specular.bin']
    g=folder/'resource_guard.json';assert sha(g)==record['guard_sha256'];guard=json.loads(g.read_text());assert guard==record['guard']
    assert guard['status']=='completed' and guard['returncode']==0 and not guard['terminated_owned_child'] and guard['termination_reason'] is None
    assert guard['args']==[str(runner),str(job)] and guard['maximum_working_set_bytes']==2*1024**3 and guard['minimum_available_memory_bytes']==1024**3
    assert guard['timeout_seconds']==240 and guard['sample_interval_seconds']==.2 and guard['samples']>0 and guard['child_pid']>0
    assert guard['peak_observed_working_set_bytes']<guard['maximum_working_set_bytes'] and guard['minimum_observed_available_bytes']>=guard['minimum_available_memory_bytes'] and guard['elapsed_seconds']<guard['timeout_seconds']
    stdout=folder/'stdout.log';stderr=folder/'stderr.log';assert sha(stdout)==record['stdout_sha256'] and sha(stderr)==record['stderr_sha256'] and stderr.stat().st_size==0
    log=stdout.read_text();assert 'debug_layer=1' in log and 'dispatches=64' in log
    assert all(re.search(r'\b'+k+r'=0\b',log) for k in ('validation_errors','validation_warnings','sdk_errors','sdk_warnings'))
    controls=folder/'dispatch_controls.bin';assert controls.read_bytes()==original_controls and sha(controls)==record['applied_controls_sha256']
    rows=np.frombuffer(controls.read_bytes(),'<u4').reshape(64,46);floats=np.frombuffer(controls.read_bytes(),'<f4').reshape(64,46)
    np.testing.assert_array_equal(rows[:,0],np.arange(64));np.testing.assert_array_equal(rows[:,1],np.r_[3,np.full(63,2)])
    np.testing.assert_array_equal(rows[:,2:4],np.tile([128,80],(64,1)));np.testing.assert_array_equal(floats[:,10:12],0)
    assert (folder/'frame_controls.txt').read_bytes()==(old/'evidence/repeat_0/frame_controls.txt').read_bytes()
    values={}
    for lobe in ('diffuse','specular'):
        p=folder/(lobe+'.bin');assert sha(p)==record[lobe+'_sha256'] and p.stat().st_size==64*128*80*8
        a=np.frombuffer(p.read_bytes(),'<f2').reshape(64,80,128,4).copy();assert np.isfinite(a).all();values[lobe]=a;fingerprints[p]=sha(p)
    native.append(values)
    audit['runs'].append(dict(run=i,job_sha256=sha(job),applied_control_sha256=sha(controls),control_stride184_exact_original=True,
        guard_sha256=sha(g),guard_source_sha256=r['guard_source_sha256'],owned_child_pid=guard['child_pid'],sampled_working_set_peak_bytes=guard['peak_observed_working_set_bytes'],
        sampled_minimum_available_bytes=guard['minimum_observed_available_bytes'],sample_count=guard['samples'],elapsed_seconds=guard['elapsed_seconds'],
        stdout_sha256=sha(stdout),stderr_sha256=sha(stderr),SDK_D3D_error_warning_counts_zero=True,
        alpha_range={k:[float(v[...,3].min()),float(v[...,3].max())] for k,v in values.items()}))
    for p in (job,g,stdout,stderr,controls):fingerprints[p]=sha(p)
for pair in r['pairwise']:
    i,j=pair['first'],pair['second'];a,b=native[i],native[j]
    all_a=np.stack((a['diffuse'],a['specular']),-1);all_b=np.stack((b['diffuse'],b['specular']),-1)
    rgba=metrics(all_a,all_b);rgb=metrics(all_a[...,:3,:],all_b[...,:3,:])
    for actual,stored in ((rgba,pair['RGBA']),(rgb,pair['RGB'])):
        for key in ('exact_equal','rms','maximum_absolute','maximum_location','differing_values','first_difference','frame_rms'):assert actual[key]==stored[key]
    lobes={lobe:dict(RGB=metrics(a[lobe][...,:3],b[lobe][...,:3]),alpha=metrics(a[lobe][...,3:4],b[lobe][...,3:4])) for lobe in ('diffuse','specular')}
    window={name:metrics(all_a[start:stop,...,:3,:],all_b[start:stop,...,:3,:])['rms'] for name,start,stop in (('RGB_pre32',0,32),('RGB_from32',32,64))}
    audit['pairs'].append(dict(first=i,second=j,RGBA=rgba,RGB=rgb,lobes=lobes,windows=window))
smoke=CASE/'guard_smoke/resource_guard.json';s=json.loads(smoke.read_text())
assert s['status']=='completed' and s['returncode']==0 and not s['terminated_owned_child'] and s['samples']>0
assert (smoke.parent/'stdout.log').read_text().strip()=='guard smoke'
audit['guard_smoke_completed_no_native_dispatch']=dict(report_sha256=sha(smoke),stdout_sha256=sha(smoke.parent/'stdout.log'),script_sha256=sha(CASE/'smoke_guard.py'))
audit['nonzero_RGB_pairs']=sum(p['RGB']['rms']>0 for p in audit['pairs'])
audit['RGB_pair_RMS_range']=[min(p['RGB']['rms'] for p in audit['pairs']),max(p['RGB']['rms'] for p in audit['pairs'])]
audit['all_alpha_zero_and_pairwise_equal']=all(v==0 for row in audit['runs'] for values in row['alpha_range'].values() for v in values)
audit['conclusion']='Five of six pairs differ with all seven input textures fixed. Frame-varying input histories are not necessary for observed context variability in this fixed-input path/sample; cause and quality remain unresolved.'
assert all(sha(p)==value for p,value in fingerprints.items());audit['all_original_evidence_unchanged']=True
out=HERE/'audit.json';assert not out.exists();out.write_text(json.dumps(audit,indent=2)+'\n')
print('audit_sha256',sha(out))
for p in audit['pairs']:print(p['first'],p['second'],'RGB',p['RGB']['rms'],'first',p['RGB']['first_difference'],'max',p['RGB']['maximum_location'],p['RGB']['maximum_signed_delta'])
