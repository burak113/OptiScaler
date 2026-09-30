"""Retained native/conversion/composition byte-graph and frozen CPU replay audit."""
from pathlib import Path
import os,sys,json,hashlib,re,importlib.util,difflib
import numpy as np
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1];TMP=ROOT/'tools_tmp'
INITIAL=TMP/'native_continuous_harmonic_initial_20260930';RETRY=TMP/'native_continuous_harmonic_fresh_retry_20260930';REST=TMP/'native_continuous_harmonic_remaining_20260930'
TESTS=ROOT/'OptiScaler/shaders/shader_tools/tests'
os.environ['FSRD_GPU_TEST_OUTPUT']=str(HERE/'unused_CPU_import')
sys.path.insert(0,str(TESTS));sys.path.insert(0,str(RETRY));sys.path.append(str(TMP/'native_significant_phase_initial_20260930'))
import run_fsrd_gpu_tests as t
from fsrd_alpha_common import conversion_cb,rgba
def loadmod(name,p):
    s=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
cpu=loadmod('harmonic_CPU_score',TMP/'source_continuous_harmonic_feasibility_20260930/analyze.py')
old=loadmod('native_fixture_only',TMP/'native_significant_phase_initial_20260930/probe_significant_phase.py')
pilot=loadmod('audit_frozen_harmonic',RETRY/'harmonic_pilot.py')
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def tokens(s):return [json.loads(x) if x.startswith('"') else x for x in re.findall(r'"(?:\\.|[^"\\])*"|[^\s]+',s)]
SIZES={10:8,41:4,24:4,28:4,3:16}
FORMATS=[41,10,24,28,28,10,10]
CONVF=[10,41,10,10,41,41,10,10,41,10,10,10,10,10,41,41,10]
def tex(a,fmt):
    a=np.asarray(a,dtype=np.uint32 if fmt==3 else np.float32)
    if a.ndim==2:a=np.repeat(a[...,None],4,-1)
    if a.shape[-1]<4:a=np.pad(a,((0,0),(0,0),(0,4-a.shape[-1])))
    if fmt==10:return a.astype('<f2').tobytes()
    if fmt==41:return a[...,0].astype('<f4').tobytes()
    if fmt==3:return a.astype('<u4').tobytes()
    if fmt==28:return np.rint(np.clip(a,0,1)*255).astype('u1').tobytes()
    if fmt==24:
        q=np.rint(np.clip(a,0,1)*[1023,1023,1023,3]).astype('<u4')
        return (q[...,0]|q[...,1]<<10|q[...,2]<<20|q[...,3]<<30).astype('<u4').tobytes()
    raise ValueError(fmt)
def equal(a,b):assert np.asarray(a).tobytes()==np.asarray(b).tobytes()
def recursive(a,b,path=''):
    if isinstance(b,dict):
        assert a.keys()==b.keys(),path
        for k in b:recursive(a[k],b[k],path+'.'+k)
    elif isinstance(b,list):
        assert len(a)==len(b),path
        for i in range(len(b)):recursive(a[i],b[i],path+f'[{i}]')
    elif isinstance(b,(float,int)) and not isinstance(b,bool):np.testing.assert_allclose(a,b,rtol=2e-12,atol=2e-14,err_msg=path)
    else:assert a==b,(path,a,b)

def audit_jobs(base):
    E=base/'evidence';M=read(E/'persisted_shader_jobs/manifest.json');jobs=[];files=0
    assert M['source_sha256']==sha(base/'capturing_worker.py')
    for entry in M['jobs']:
        d=E/'persisted_shader_jobs'/entry['job_name'];assert entry['returncode']==0 and entry['actual_run_completed']
        for f in entry['files']:
            assert (d/f['name']).stat().st_size==f['size'] and sha(d/f['name'])==f['sha256'];files+=1
        assert sha(d/'runner.log')==entry['runner_log_sha256']
        log=(d/'runner.log').read_text();assert 'debug_layer=1' in log and 'validation_errors=0 validation_warnings=0' in log
        rows=[tokens(s) for s in (d/'job.txt').read_text().splitlines()];head=rows[0]
        assert list(map(int,head[2:4]))==[128,80] and int(head[6])==1
        shader=Path(head[0]);ni,no=int(head[4]),int(head[5]);assert len(rows)==1+ni+no
        formats=[int(v[3]) for v in rows[1:]]
        for line in rows[1:]:
            assert list(map(int,line[1:3]))==[128,80]
            assert (d/Path(line[0]).name).stat().st_size==128*80*SIZES[int(line[3])]
        if shader.name=='FSRDInputConvAdditive_Shader.cso':
            assert ni==17 and no==8 and formats==CONVF+[10,10,10,24,28,28,10,10]
            expected=bytes(t.constants('FSRDInputConvAdditive',conversion_cb(128,80,1)));kind='convert'
        else:
            assert shader.name=='FSRDOutputComp_Shader.cso' and ni==11 and no==3
            assert formats==[10,28,10,28,10,24,10,41,10,10,3]+[10,10,3]
            cb=dict(DstTexSize=[128,80,1/128,1/80],Flags=8,DetailPreservation=0,SpecularAlbedoDemodulation=1,DiffuseAlbedoModulation=1,RecoveryMask=1,FloorHandoverAnchorClamp=4,FloorHandoverCorrelationMix=1,LumaRecovery=1,ChromaRecovery=1)
            expected=bytes(t.constants('FSRDOutputComp',cb));kind='compose'
        assert (d/'cb.bin').read_bytes()==expected
        jobs.append(dict(path=d,kind=kind,shader=shader.name,shader_sha256=sha(shader)))
    return jobs,{'manifest_sha256':sha(E/'persisted_shader_jobs/manifest.json'),'job_count':len(jobs),'files_hashed':files,
                 'conversion_count':sum(j['kind']=='convert' for j in jobs),'composition_count':sum(j['kind']=='compose' for j in jobs)}

def expected_conversion(jobs,raw,data):
    zero=np.zeros((80,128,4),np.float32)
    for frame,job in enumerate(jobs):
        source=rgba(raw[frame]);depth=data['depth'];motion=data.get('motion',[zero]*64)[frame]
        arrays=[source,depth,motion,data['normals'],data['roughness'],depth,data['diff'][frame],data['spec'][frame],zero,zero,zero,zero,zero,zero,depth,zero,source]
        for slot,value in (data.get('resources') or {}).items():arrays[slot]=value
        for i,(a,fmt) in enumerate(zip(arrays,CONVF)):assert (job['path']/f'in{i}.bin').read_bytes()==tex(a,fmt)

def native_input_graph(ctx,conversion):
    rows=[tokens(s) for s in (ctx/'job.txt').read_text().splitlines()]
    assert list(map(int,rows[0][:8]))==[128,80,64,2,32,0,1,0]
    assert sha(Path(rows[0][8]))=='48f1e5888ba6a0a3d59a98b9751e37c392b0f7b8c223d0082d5c1f40642879d3'
    mapping=['in1.bin','out2.bin','out3.bin','out4.bin','out5.bin','out1.bin','out0.bin'];uploads=[]
    for i,line in enumerate(rows[1:8]):
        fmt,n=map(int,line[1:]);assert fmt==FORMATS[i] and n in (1,64)
        blob=(ctx/f'input{i}.bin').read_bytes();framebytes=128*80*SIZES[fmt];assert len(blob)==n*framebytes
        for f,c in enumerate(conversion):
            assert (c['path']/mapping[i]).read_bytes()==blob[(f if n==64 else 0)*framebytes:((f+1) if n==64 else 1)*framebytes]
        uploads.append(n)
    return uploads

def context(ctx,conversion,compositions,composed,controls,data,report):
    identity=read(ctx/'amd_context_identity.json');assert sha(ctx/'amd_context_identity.json')==report['context_identity_sha256'][ctx.name]
    assert identity['dll_sha256']=='48f1e5888ba6a0a3d59a98b9751e37c392b0f7b8c223d0082d5c1f40642879d3'
    assert identity['runner_sha256']=='3427689a4764380f885545c353250277e4d71944d3310c8a17b3cbba0f3c21d2'
    assert identity['tuning']==1 and identity['signals']==[2,32] and identity['tuning_values']==[.1,.5,.5,40000.,40.,.5]
    assert identity['reset_every']==0 and identity['passthrough']==0 and identity['frames']==64 and identity['dimensions']==[128,80]
    for name,digest in identity['inputs'].items():assert sha(ctx/name)==digest
    uploads=native_input_graph(ctx,conversion)
    raw=(ctx/'dispatch_controls.bin').read_bytes();assert len(raw)==64*184 and sha(ctx/'dispatch_controls.bin')==identity['applied_dispatch_sha256']==report['matched_applied_controls_sha256']
    records=np.frombuffer(raw,dtype=np.dtype([('header','<u4',(4,)),('values','<f4',(42,))]))
    for frame,r in enumerate(records):
        np.testing.assert_array_equal(r['header'],[frame,2 | int(frame==0 or controls[frame,0]),128,80])
        np.testing.assert_array_equal(r['values'][:6],[1,1,1,0,0,0]);np.testing.assert_array_equal(r['values'][6:8],controls[frame,1:].astype('f4'))
        np.testing.assert_array_equal(r['values'][8:10],[0,1024]);np.testing.assert_array_equal(r['values'][10:26],np.eye(4).ravel().astype('f4'))
    parsed=np.loadtxt(ctx/'frame_controls.txt');np.testing.assert_array_equal(parsed.astype('f4'),controls.astype('f4'))
    # Native DirectX perspective byte-rounding is retained; independently check
    # the geometric formula, then require all three contexts byte-identical.
    ys=1/math_tan_pi_over_6();proj=np.zeros((4,4));proj[0,0]=ys/1.6;proj[1,1]=ys;proj[2,2]=1000/999.9;proj[2,3]=1;proj[3,2]=-.1*1000/999.9
    np.testing.assert_allclose(records['values'][:,26:],np.repeat(proj.ravel()[None],64,axis=0),rtol=2e-7,atol=1e-8)
    process=read(ctx/'runner_process.json');guard=read(ctx/'resource_guard.json');assert process['returncode']==0 and process['log_sha256']==sha(ctx/'runner.log')
    assert process['runner_sha256']==identity['runner_sha256'] and guard['status']=='completed' and guard['returncode']==0 and not guard['terminated_owned_child']
    assert guard['minimum_available_memory_bytes']==2**30 and guard['maximum_working_set_bytes']==2**31 and guard['timeout_seconds']==240
    log=(ctx/'runner.log').read_text();assert 'debug_layer=1' in log and 'dispatches=64' in log
    assert all(re.search(r'\b'+field+r'=0\b',log) for field in ('validation_errors','validation_warnings','sdk_errors','sdk_warnings'))
    lobes=[]
    for name in ('diffuse.bin','specular.bin'):
        assert sha(ctx/name)==identity['output_sha256'][name]
        lobes.append(np.fromfile(ctx/name,'<f2').reshape(64,80,128,4).astype('f4'))
    zero=np.zeros((80,128,4),np.float32)
    for f,job in enumerate(compositions):
        cv=conversion[f]['path'];p=job['path']
        expected=[tex(lobes[1][f],10),(cv/'out4.bin').read_bytes(),tex(lobes[0][f],10),(cv/'out5.bin').read_bytes(),(cv/'out6.bin').read_bytes(),(cv/'out3.bin').read_bytes(),(cv/'out7.bin').read_bytes(),tex(data['depth'],41),tex(zero,10),tex(np.full_like(zero,-1),10),tex(zero.astype('u4'),3)]
        for i,value in enumerate(expected):assert (p/f'in{i}.bin').read_bytes()==value
        output=np.fromfile(p/'out0.bin','<f2').reshape(80,128,4).astype('f4');equal(output[...,:3],composed[f])
    return dict(identity_sha256=sha(ctx/'amd_context_identity.json'),input_hashes=identity['inputs'],output_hashes=identity['output_sha256'],applied_controls_sha256=sha(ctx/'dispatch_controls.bin'),native_input_uploads=uploads,log_sha256=sha(ctx/'runner.log'),guard_sha256=sha(ctx/'resource_guard.json'),output_alpha_range=[[float(a[...,3].min()),float(a[...,3].max())] for a in lobes])
def math_tan_pi_over_6():return np.tan(np.pi/6)

def dc(candidate,source,active,controls,history,epochs=None):
    value=candidate.copy();start=0
    for f in range(len(value)):
        if controls[f,0]:start=f
        if epochs is not None:start=max(start,int(epochs[f]))
        if active[f]:
            target=source[max(start,f-history+1):f+1,5:-5,5:-5].astype(float).mean((0,1,2))
            actual=candidate[f,5:-5,5:-5].astype(float).mean((0,1))
            value[f]+=active[f]*(target-actual)
    return value

def main():
    report1=read(RETRY/'evidence/results.json');report2=read(REST/'evidence/results.json');initial=read(INITIAL/'evidence/results.json')
    assert report2['status']=='completed_native_diagnostic_not_solution','Remaining report must be terminal before audit acceptance'
    assert report1['status']=='failed_preserved' and report1['completed_native_contexts']==3 and len(report1['rows'])==1
    assert report1['error']=="'absolute_detail_pass'" and report2['completed_native_contexts']==15 and report2['native_RR_calls']==960
    assert initial['status']=='failed_preserved' and initial['completed_native_contexts']==0 and not initial['rows']
    frozen={};source_audits=[]
    for base in (INITIAL,RETRY,REST):
        freeze=read(base/'pre_native_freeze.json')
        for p,digest in freeze['sources'].items():assert sha(p)==digest
        for name in ('harmonic_pilot.py','native_helper.py','native_resource_guard.py','capturing_worker.py','preregistration.json'):
            assert (base/name).read_bytes()==(RETRY/name).read_bytes()
        for p in (base/'evidence/source_snapshot').iterdir():
            if p.name!='run.log':assert p.read_bytes()==(base/p.name).read_bytes()
        assert sha(base/'harmonic_pilot.py')=='be66624153a286c6b3299735fc2a1bbf5162ffe24a52d7f9421d1c4b90a52173'
        jobs,counts=audit_jobs(base);frozen[str(base)]=jobs;source_audits.append(dict(base=str(base),freeze_sha256=sha(base/'pre_native_freeze.json'),report_sha256=sha(base/'evidence/results.json'),**counts))
        for j in jobs:assert j['shader_sha256']==report1['production_shaders'][j['shader']]
    assert [a['job_count'] for a in source_audits]==[128,320,1600]
    guard=read(INITIAL/'evidence/material/observed/resource_guard.json')
    assert guard['status']=='not_launched_low_available_memory' and guard['child_pid'] is None and guard['returncode'] is None and guard['samples']==0
    assert guard['initial_available_bytes']==445657088<guard['minimum_available_memory_bytes']==2**30
    assert not (INITIAL/'evidence/material/observed/diffuse.bin').exists()
    lineage=''.join(difflib.unified_diff((RETRY/'analyze.py').read_text().splitlines(True),(REST/'analyze.py').read_text().splitlines(True),fromfile='retry',tofile='remaining'))
    rows=[];windows=[('full',slice(None)),('mature',slice(-16,None)),('startup_first8',slice(0,8)),('activation8to16',slice(8,16))]
    for base,report in ((RETRY,report1),(REST,report2)):
      alljobs=frozen[str(base)]
      for index,row in enumerate(report['rows']):
        scene=row['scene'];folder=base/'evidence'/scene;assert sha(folder/'sequences.npz')==row['sequences_sha256']
        data=old.research_fixture(scene,128,80,64,950301);controls=data['controls'];truth=data['truth']
        observed=(truth+np.random.default_rng(956432).normal(0,.012,truth.shape)).astype('f2').astype('f4')
        regenerated,active,diag=pilot.make_continuous_harmonic_pilot(observed,controls)
        regenerated=regenerated.astype('f2').astype('f4');assert diag==row['pilot_diagnostics']
        with np.load(folder/'sequences.npz') as z:
            equal(observed,z['observed']);equal(truth,z['clean_reference']);equal(regenerated,z['pilot']);equal(active,z['active'])
            B=z['baseline'];R=z['null_repeat'];TP=z['pilot_response']
            chunk=alljobs[index*320:(index+1)*320];assert [x['kind'] for x in chunk]==['convert']*128+['compose']*192
            sourceconv=chunk[:64];pilotconv=chunk[64:128]
            expected_conversion(sourceconv,observed,data);expected_conversion(pilotconv,regenerated,data)
            for f in range(64):
                for slot in (2,3):assert (sourceconv[f]['path']/f'out{slot}.bin').read_bytes()==(pilotconv[f]['path']/f'out{slot}.bin').read_bytes()
                for slot in (4,5):
                    aa=np.frombuffer((sourceconv[f]['path']/f'out{slot}.bin').read_bytes(),'u1').reshape(80,128,4)[...,:3]
                    bb=np.frombuffer((pilotconv[f]['path']/f'out{slot}.bin').read_bytes(),'u1').reshape(80,128,4)[...,:3];equal(aa,bb)
                for slot in (0,1):
                    aa=np.frombuffer((sourceconv[f]['path']/f'out{slot}.bin').read_bytes(),'<f2').reshape(80,128,4)[...,3]
                    bb=np.frombuffer((pilotconv[f]['path']/f'out{slot}.bin').read_bytes(),'<f2').reshape(80,128,4)[...,3];equal(aa,bb)
            contexts=[]
            for i,(name,cv,value) in enumerate((('observed',sourceconv,B),('null_repeat',sourceconv,R),('harmonic_pilot',pilotconv,TP))):
                contexts.append(context(folder/name,cv,chunk[128+i*64:192+i*64],value,controls,data,row))
            assert contexts[0]['input_hashes']==contexts[1]['input_hashes']
            for i in range(3):assert contexts[0]['input_hashes'][f'input{i}.bin']==contexts[2]['input_hashes'][f'input{i}.bin']
            guide_alpha_changes={}
            for i in (3,4):
                a=np.fromfile(folder/'observed'/f'input{i}.bin','u1').reshape(-1,80,128,4)
                b=np.fromfile(folder/'harmonic_pilot'/f'input{i}.bin','u1').reshape(-1,80,128,4)
                if len(a)==1:a=np.broadcast_to(a,(64,80,128,4))
                if len(b)==1:b=np.broadcast_to(b,(64,80,128,4))
                equal(a[...,:3],b[...,:3]);guide_alpha_changes[f'input{i}.bin']=float(np.mean(a[...,3]!=b[...,3]))
            if scene=='material':
                initjobs=frozen[str(INITIAL)];expected_conversion(initjobs[:64],observed,data);expected_conversion(initjobs[64:],regenerated,data)
                native_input_graph(INITIAL/'evidence/material/observed',initjobs[:64])
                for i in range(7):assert (INITIAL/'evidence/material/observed'/f'input{i}.bin').read_bytes()==(folder/'observed'/f'input{i}.bin').read_bytes()
            null=float(np.sqrt(np.mean((B-R)**2)));np.testing.assert_allclose(null,row['null_rms'],rtol=1e-13,atol=0)
            blind=B+active[:,None,None,None]*(regenerated-TP);epochs=[v['epoch_start'] for v in diag['frames']]
            variants={'harmonic':blind,'harmonic_dc':dc(blind,observed,active,controls,64,epochs),'harmonic_dc_current':dc(blind,observed,active,controls,1)}
            fallbacks={}
            for name,value in list(variants.items()):
                invalid=~np.all(np.isfinite(value)&(value>=0)&(value<=65504),axis=-1);variants[name+'_safe']=np.where(invalid[...,None],B,value);fallbacks[name+'_safe']=float(invalid.mean())
            bm={window:cpu.first.detail(B[sl],truth[sl]) for window,sl in windows};recursive(bm,row['baseline_metrics'])
            metrics={}
            for name,value in variants.items():
                equal(value,z[name]);out={}
                for window,sl in windows:
                    m=cpu.first.detail(value[sl],truth[sl]);activity=float(np.mean(abs(value[sl]-B[sl])>1e-5))
                    m['relative_gate']=old.acceptance(m['score'],bm[window]['score'],activity,null,scene)
                    denom=bm[window]['score']['residual_temporal_std'];m['actual_STD_ratio_to_native_baseline']=m['score']['residual_temporal_std']/denom if denom else None
                    out[window]=m
                got=dict(metrics=out,fallback_pixel_fraction=fallbacks.get(name,0),invalid_pixel_fraction=float(np.mean(~np.all(np.isfinite(value)&(value>=0)&(value<=65504),axis=-1))))
                recursive(got,row['variants'][name]);metrics[name]=got
            rows.append(dict(scene=scene,sequences_sha256=sha(folder/'sequences.npz'),null_RMS_RGB=null,contexts=contexts,guide_RGBA_alpha_changed_fraction=guide_alpha_changes,geometry_and_guide_RGB_counterfactual_exact=True,all_retained_shader_graph_edges_exact=True,frozen_source_P_active_diagnostics_regenerated_exact=True,metrics=metrics,baseline_metrics=bm))
            print(scene,'byte graph/formulas/metrics verified',flush=True)
    assert len(rows)==6
    totals={window:dict(relative_nonregression=sum(r['metrics']['harmonic_dc_current_safe']['metrics'][window]['relative_gate']['nonregression'] for r in rows),relative_effective=sum(r['metrics']['harmonic_dc_current_safe']['metrics'][window]['relative_gate']['effective_success'] for r in rows),absolute_detail=sum(r['metrics']['harmonic_dc_current_safe']['metrics'][window]['per_frame_absolute_detail_pass'] for r in rows),strict_STD_nonincrease=sum(r['metrics']['harmonic_dc_current_safe']['metrics'][window]['actual_STD_ratio_to_native_baseline']<=1 for r in rows)) for window,_ in windows}
    out=dict(status='completed_independent_native_diagnostic_not_solution',quality_accepted=False,game_validated=False,GPU_used=False,completed_contexts=18,RR_dispatches=1152,completed_shader_jobs=1920,not_launched_attempt_shader_jobs_separate=128,
             source_audits=source_audits,initial_guard=guard,material_failed_report_reconciled='3 native contexts and192 RR completed; row/NPZ persisted, then stdout missing-key exception; not a native failure or discarded row',remaining_driver_diff=lineage,
             caller_flags_contract='SDK NON_GAMMA_ALBEDO2 | RESET1, native184-byte records; converter Flags34 are a separate namespace',rows=rows,chosen_totals=totals,
             limitations=['Scores are synthetic truth diagnostic only, no current-alpha game quality acceptance.', 'All CB/input/output graph bytes retained; direct DLL provider query unavailable, exact DLL hash is identity.', 'No old T(P) substituted: every native context is fresh; no repeat average used.', 'Current/mature relative gates allow noise allowance; exact STD and absolute gain/phase reported separately.', 'Full-source noise estimate and adaptive heldout model selection are not independent confidence tests.', 'Exposure metadata absent/unknown, signed invalid whole-frame fallback and atomic finalRGB baseline fallback are disclosed.'])
    out['audit_source_sha256']=sha(__file__);(HERE/'audit.json').write_text(json.dumps(out,indent=2,allow_nan=False)+'\n')
    print('audit SHA',sha(HERE/'audit.json'),'totals',totals,flush=True)
if __name__=='__main__':main()
