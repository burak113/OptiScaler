"""Read-only retained-byte/native-cohort audit; no GPU or cleantruth estimator."""
from pathlib import Path
import os,sys,hashlib,json,re,itertools
import numpy as np
HERE=Path(__file__).resolve().parent; ROOT=HERE.parents[1]
E=ROOT/'tools_tmp/same_pilot_context_cohort_20260930/evidence'
SRC=ROOT/'tools_tmp/native_significant_phase_initial_20260930/evidence'
os.environ['FSRD_GPU_TEST_OUTPUT']=str(HERE/'unused_cpu_import')
sys.path.insert(0,str(ROOT/'OptiScaler/shaders/shader_tools/tests'))
import run_fsrd_gpu_tests as t
from fsrd_alpha_common import conversion_cb,rgba
from probe_fsrd_statistical_resolve import fixture

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text())
def tokens(line):
    return [json.loads(s) if s.startswith('"') else s for s in re.findall(r'"(?:\\.|[^"\\])*"|[^\s]+',line)]
def texture_bytes(a,fmt):
    a=np.asarray(a,dtype=np.uint32 if fmt==3 else np.float32)
    if a.ndim==2:a=np.repeat(a[...,None],4,axis=-1)
    if a.shape[-1]<4:a=np.pad(a,((0,0),(0,0),(0,4-a.shape[-1])))
    if fmt==10:return a.astype('<f2').tobytes()
    if fmt==41:return a[...,0].astype('<f4').tobytes()
    if fmt==3:return a.astype('<u4').tobytes()
    if fmt==28:return np.rint(np.clip(a,0,1)*255).astype('u1').tobytes()
    if fmt==24:
        q=np.rint(np.clip(a,0,1)*[1023,1023,1023,3]).astype('<u4')
        return (q[...,0]|q[...,1]<<10|q[...,2]<<20|q[...,3]<<30).astype('<u4').tobytes()
    raise ValueError(fmt)
def compare(a,b):
    d=np.asarray(a,float)-np.asarray(b,float); frames=np.any(d!=0,axis=(1,2,3))
    return dict(exact=not frames.any(),first_difference_frame=int(np.flatnonzero(frames)[0]) if frames.any() else None,
        rms=float(np.sqrt(np.mean(d*d))),maximum=float(abs(d).max()),per_frame_rms=np.sqrt(np.mean(d*d,axis=(1,2,3))).tolist())
def decomposition(p,tp):
    p=np.asarray(p,float); tp=np.asarray(tp,float); delta=p[None]-tp
    centered=delta-delta.mean(1,keepdims=True); common=centered.mean(0); scatter=centered-common
    total=float(np.mean(centered**2)); shared=float(np.mean(common**2)); noise=float(np.mean(scatter**2))
    pc=p-p.mean(0); tc=tp.mean(0)-tp.mean(0).mean(0)
    vp=float(np.mean(pc**2)); vt=float(np.mean(tc**2)); cov=float(np.mean(pc*tc))
    return dict(cohort_count=len(tp),mean_context_temporal_variance=total,common_correction_temporal_variance=shared,
        context_scatter_temporal_variance=noise,scatter_fraction=noise/total if total else None,
        common_pilot_temporal_variance=vp,mean_native_response_temporal_variance=vt,pilot_mean_response_covariance=cov,
        variance_identity_error=abs(total-shared-noise),shared_identity_error=abs(shared-vp-vt+2*cov))
def numeric_dict_close(actual,expected):
    assert actual.keys()==expected.keys()
    for k,v in expected.items():
        if isinstance(v,(int,float)) and v is not None:np.testing.assert_allclose(actual[k],v,rtol=1e-10,atol=1e-20,err_msg=k)
        else:assert actual[k]==v

def main():
    if (HERE/'audit.json').exists():raise ValueError('Preserve audit')
    r=read(E/'results.json'); original=read(SRC/'results.json'); manifest=read(E/'persisted_shader_jobs/manifest.json')
    inputs_before={str(E/'results.json'):sha(E/'results.json'),str(E/'persisted_shader_jobs/manifest.json'):sha(E/'persisted_shader_jobs/manifest.json')}
    assert r['status']=='completed_diagnostic_not_solution' and r['completed_native_contexts']==6 and r['native_RR_dispatches']==384
    assert r['original_report_sha256']==sha(SRC/'results.json')
    for name,digest in r['source_sha256'].items():
        assert sha(E/'source_snapshot'/name)==digest and sha(E.parent/name)==digest
    assert manifest['source_sha256']==r['source_sha256']['capturing_worker.py']
    jobs=manifest['jobs']; assert len(jobs)==640
    conversion=[]; composition=[]; hash_count=0; decoded=[]; shader_hashes={}
    byte_sizes={10:8,41:4,24:4,28:4,3:16}
    for entry in jobs:
        path=E/'persisted_shader_jobs'/entry['job_name']; assert entry['returncode']==0 and entry['actual_run_completed']
        for f in entry['files']:
            p=path/f['name']; assert p.stat().st_size==f['size'] and sha(p)==f['sha256']; hash_count+=1
        assert sha(path/'runner.log')==entry['runner_log_sha256']
        log=(path/'runner.log').read_text(); assert 'debug_layer=1' in log and 'validation_errors=0 validation_warnings=0' in log
        rows=[tokens(s) for s in (path/'job.txt').read_text().splitlines()]
        head=rows[0]; assert [int(x) for x in head[2:4]]==[128,80] and int(head[6])==1
        shader=Path(head[0]); csosha=sha(shader); shader_hashes[shader.name]=csosha
        ni,no=int(head[4]),int(head[5]); assert len(rows)==1+ni+no
        assert Path(head[1]).name=='cb.bin'
        for line in rows[1:]:
            name=Path(line[0]).name; w,h,fmt=map(int,line[1:]); assert (w,h)==(128,80)
            assert (path/name).stat().st_size==w*h*byte_sizes[fmt]
        item=dict(path=path,rows=rows,input_formats=[int(s[3]) for s in rows[1:ni+1]],output_formats=[int(s[3]) for s in rows[ni+1:]])
        if shader.name=='FSRDInputConvAdditive_Shader.cso':
            assert ni==17 and no==8
            assert item['input_formats']==[10,41,10,10,41,41,10,10,41,10,10,10,10,10,41,41,10]
            assert item['output_formats']==[10,10,10,24,28,28,10,10]
            assert (path/'cb.bin').read_bytes()==bytes(t.constants('FSRDInputConvAdditive',conversion_cb(128,80,1)))
            conversion.append(item)
        else:
            assert shader.name=='FSRDOutputComp_Shader.cso' and ni==11 and no==3
            assert item['input_formats']==[10,28,10,28,10,24,10,41,10,10,3] and item['output_formats']==[10,10,3]
            cb=dict(DstTexSize=[128,80,1/128,1/80],Flags=8,DetailPreservation=0,SpecularAlbedoDemodulation=1,DiffuseAlbedoModulation=1,
                RecoveryMask=1,FloorHandoverAnchorClamp=4,FloorHandoverCorrelationMix=1,LumaRecovery=1,ChromaRecovery=1)
            assert (path/'cb.bin').read_bytes()==bytes(t.constants('FSRDOutputComp',cb)); composition.append(item)
    assert len(conversion)==128 and len(composition)==512
    rows_out=[]
    for scene_index,row in enumerate(r['rows']):
        scene=row['scene']; folder=E/scene; old=SRC/scene/'blind_pilot'; ident=read(old/'amd_context_identity.json')
        source_npz=SRC/scene/'sequences.npz'; assert sha(source_npz)==row['source_sequences_sha256']
        assert sha(old/'amd_context_identity.json')==row['source_context_identity_sha256']
        with np.load(source_npz) as z:p=z['pilot'].copy(); old_tp=z['pilot_response'].copy()
        with np.load(folder/'cohort.npz') as z:np.testing.assert_array_equal(z['pilot'],p); cohort=z['pilot_responses'].copy()
        np.testing.assert_array_equal(cohort[0],old_tp)
        fixture_data=fixture(scene,128,80,64,950301); cv=conversion[scene_index*64:(scene_index+1)*64]; comp=composition[scene_index*256:(scene_index+1)*256]
        zero=np.zeros((80,128,4),np.float32); depth=fixture_data['depth']; native_inputs=[]
        for f,item in enumerate(cv):
            path=item['path']; raw=rgba(p[f]);
            expected=[raw,depth,zero,fixture_data['normals'],fixture_data['roughness'],depth,fixture_data['diff'][f],fixture_data['spec'][f],zero,zero,zero,zero,zero,zero,depth,zero,raw]
            for j,(a,fmt) in enumerate(zip(expected,item['input_formats'])):assert (path/f'in{j}.bin').read_bytes()==texture_bytes(a,fmt)
        # Native geometry streams may be stored as one immutable frame; compare
        # each conversion output before authenticating exact native input hashes.
        native_bindings={0:('in1.bin',0),1:('out2.bin',2),2:('out3.bin',3),3:('out4.bin',4),4:('out5.bin',5),5:('out1.bin',1),6:('out0.bin',0)}
        schedules=[]
        for idx,(filename,_) in native_bindings.items():
            original_bytes=(old/f'input{idx}.bin').read_bytes(); fmt=[41,10,24,28,28,10,10][idx]; framebytes=128*80*byte_sizes[fmt]
            stored_frames=len(original_bytes)//framebytes; assert stored_frames in (1,64); schedules.append(stored_frames)
            for f,item in enumerate(cv):assert (item['path']/filename).read_bytes()==original_bytes[(f if stored_frames==64 else 0)*framebytes:(f+1 if stored_frames==64 else 1)*framebytes]
            assert sha(folder/'regenerated_native_inputs'/f'input{idx}.bin')==ident['inputs'][f'input{idx}.bin']==sha(old/f'input{idx}.bin')
        lobes=[]; context_audits=[]
        for repeat in range(4):
            ctx=old if repeat==0 else folder/f'repeat_{repeat}'; identity=read(ctx/'amd_context_identity.json')
            assert identity['inputs']==ident['inputs']; assert identity['dll_sha256']==r['provider_sha256'] and identity['runner_sha256']==r['runner_sha256']
            assert identity['tuning']==1 and identity['tuning_values']==[.1,.5,.5,40000.,40.,.5]
            assert identity['applied_dispatch_sha256']==ident['applied_dispatch_sha256']==sha(ctx/'dispatch_controls.bin')
            assert (ctx/'dispatch_controls.bin').read_bytes()==(old/'dispatch_controls.bin').read_bytes()
            records=np.frombuffer((ctx/'dispatch_controls.bin').read_bytes(),dtype='u1').reshape(64,184)
            for frame,record in enumerate(records):
                # Local caller sets NON_GAMMA_ALBEDO bit2 on every dispatch,
                # plus RESET bit1 on reset/first frames; do not erase that bit.
                u=np.frombuffer(record[:16],'<u4'); np.testing.assert_array_equal(u,[frame,2 | (1 if frame==0 or fixture_data['controls'][frame,0] else 0),128,80])
                v=np.frombuffer(record[16:],'<f4'); np.testing.assert_array_equal(v[6:8],fixture_data['controls'][frame,1:].astype('f4'))
            for filename,digest in identity['inputs'].items():assert sha(ctx/filename)==digest
            values=[]
            for filename,digest in identity['output_sha256'].items():
                assert sha(ctx/filename)==digest
            for filename in ('diffuse.bin','specular.bin'):
                values.append(np.fromfile(ctx/filename,'<f2').reshape(64,80,128,4).astype(np.float32))
            lobes.append(np.concatenate(values,-1))
            log=(ctx/'runner.log').read_text(); assert all(re.search(r'\b'+name+r'=0\b',log) for name in ('validation_errors','validation_warnings','sdk_errors','sdk_warnings'))
            assert 'debug_layer=1' in log and 'dispatches=64' in log
            if repeat:
                process=read(ctx/'runner_process.json'); assert process['returncode']==0 and process['log_sha256']==sha(ctx/'runner.log')
                guard=read(ctx/'resource_guard.json'); assert guard['status']=='completed' and not guard['terminated_owned_child'] and guard['returncode']==0
                assert guard['maximum_working_set_bytes']==2**31 and guard['minimum_available_memory_bytes']==2**30 and guard['timeout_seconds']==240
            context_audits.append(dict(repeat=repeat,identity_sha256=sha(ctx/'amd_context_identity.json'),applied_controls_sha256=sha(ctx/'dispatch_controls.bin'),
                raw_output_sha256=identity['output_sha256'],all_seven_input_sha256=identity['inputs'],runner_log_sha256=sha(ctx/'runner.log'),provider_query='Unavailable per direct effect DLL log; provider identity here is exact DLL SHA'))
            for f,item in enumerate(comp[repeat*64:(repeat+1)*64]):
                path=item['path']; conv=cv[f]['path']
                expected_bytes=[values[1][f].astype('<f2').tobytes(),(conv/'out4.bin').read_bytes(),values[0][f].astype('<f2').tobytes(),
                    (conv/'out5.bin').read_bytes(),(conv/'out6.bin').read_bytes(),(conv/'out3.bin').read_bytes(),(conv/'out7.bin').read_bytes(),
                    texture_bytes(depth,41),texture_bytes(zero,10),texture_bytes(np.full_like(zero,-1),10),texture_bytes(np.zeros_like(zero,dtype=np.uint32),3)]
                for idx,expected in enumerate(expected_bytes):assert (path/f'in{idx}.bin').read_bytes()==expected
                output=np.fromfile(path/'out0.bin','<f2').reshape(80,128,4).astype(np.float32)
                np.testing.assert_array_equal(output[...,:3],cohort[repeat,f])
        lobes=np.stack(lobes); pairwise=[]
        for a,b in itertools.combinations(range(4),2):
            observed=next(q for q in row['pairs'] if q['a']==a and q['b']==b)
            raw=compare(lobes[a],lobes[b]); composed=compare(cohort[a],cohort[b])
            for name,got in (('raw_lobes',raw),('composed',composed)):
                old_pair=observed[name]; assert got['exact']==old_pair['exact'] and got['first_difference_frame']==old_pair['first_difference_frame']
                np.testing.assert_allclose(got['rms'],old_pair['rms'],rtol=1e-13,atol=0);np.testing.assert_array_equal(got['per_frame_rms'],old_pair['per_frame_rms'])
            pairwise.append(dict(a=a,b=b,raw_8channel_lobes=raw,composed_RGB=composed))
        windows={};precision={}
        for name,sl in [('full',slice(None)),('mature',slice(-16,None))]:
            pp=p[sl,5:-5,5:-5];tt=cohort[:,sl,5:-5,5:-5]
            total=decomposition(pp,tt); non_dc_v1=decomposition(pp-pp.mean((1,2),keepdims=True),tt-tt.mean((2,3),keepdims=True))
            numeric_dict_close(total,row['windows'][name]['total']); numeric_dict_close(non_dc_v1,row['windows'][name]['non_dc'])
            pd=pp.astype(float);td=tt.astype(float); non_dc_64=decomposition(pd-pd.mean((1,2),keepdims=True),td-td.mean((2,3),keepdims=True))
            windows[name]=dict(total=total,non_dc_original_FP32_spatial_mean=non_dc_v1,non_dc_float64_spatial_mean=non_dc_64)
            precision[name]=dict(maximum_P_nonDC_difference=float(abs((pp-pp.mean((1,2),keepdims=True))-(pd-pd.mean((1,2),keepdims=True))).max()),
                maximum_TP_nonDC_difference=float(abs((tt-tt.mean((2,3),keepdims=True))-(td-td.mean((2,3),keepdims=True))).max()),
                scatter_fraction_difference=non_dc_64['scatter_fraction']-non_dc_v1['scatter_fraction'])
        rows_out.append(dict(scene=scene,source_sequences_sha256=sha(source_npz),cohort_npz_sha256=sha(folder/'cohort.npz'),
            native_input_frame_upload_schedule=schedules,actual_conversion_inputs_and_CB_exact=True,actual_conversion_outputs_to_native_all_seven_exact=True,
            actual_composition_inputs_CB_and_outputs_to_cohort_all_frames_exact=True,contexts=context_audits,pairwise=pairwise,windows=windows,FP32_qualification=precision))
        print(scene,'audit passed',windows['mature']['non_dc_original_FP32_spatial_mean']['scatter_fraction'],flush=True)
    assert all(sha(p)==digest for p,digest in inputs_before.items())
    out=dict(schema='same-pilot-native-cohort-independent-byte-audit-v1',status='completed_diagnostic_not_solution',quality_accepted=False,
        source_report_sha256=sha(E/'results.json'),shader_payload_manifest_sha256=sha(E/'persisted_shader_jobs/manifest.json'),
        producer_sources_sha256=r['source_sha256'],audit_source_sha256=sha(__file__),native_contexts_new=6,native_dispatches_new=384,
        reused_measured_original_contexts=2,total_cohort_contexts=8,conversion_dispatches=128,composition_dispatches=512,
        retained_shader_jobs_audited=640,retained_shader_files_hashed=hash_count,shader_CSO_sha256=shader_hashes,rows=rows_out,
        qualifications=['Raw-lobe RMS averages8 channels (diff/specRGBA); composed RMS averages3RGB; alpha0 dilutes raw vs RGB-only amplitude',
            'Original v1 nonDC spatial means computed FP32 before float64 decomposition, reproduced and separatefloat64 precision delta recorded',
            'Temporal variance full/mature measured in5px score interior70x118, not full128x80',
            'Sample of4 contexts includes original earlier measurement; not population/confidence inference',
            'Fixed-P context scatter cannot explain/remove shared P variation or shared deterministic native settling',
            'No cleantruth, image-quality acceptance, causation, performance or game fix claimed'])
    (HERE/'audit.json').write_text(json.dumps(out,indent=2,allow_nan=False)+'\n'); print('audit SHA',sha(HERE/'audit.json'),flush=True)
if __name__=='__main__':main()
