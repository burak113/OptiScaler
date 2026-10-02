"""Root-owned guarded CPU stages; never compiles or calls native/GPU."""
from pathlib import Path
import hashlib, json, os, struct, sys
from common import *

def rgba(np,rgb,alpha=0):
    rgb=np.asarray(rgb,dtype=np.float64)
    if rgb.ndim==2: rgb=np.repeat(rgb[...,None],3,-1)
    return np.concatenate((rgb,np.full((*rgb.shape[:-1],1),alpha)),axis=-1)
def halfwrite(np,p,a):
    valid_rgb(np,a,str(p));b=a.astype('<f2');valid_rgb(np,b,str(p)+' typed')
    return write(p,b.tobytes())
def assembly(np,d):
    data=d/'data';data.mkdir();truth=d/'score_only_truth';truth.mkdir();jobs=d/'converter_jobs';jobs.mkdir()
    control=Path(item('expected_controls')['path']).read_bytes();assert len(control)==N*184
    proj=control[120:184];cam=load(item('matched_camera')['path'])
    assert hashlib.sha256(proj).hexdigest()==cam['native_projection_sha256']
    inverse=struct.pack('<16f',*cam['inverse_projection'])
    view=control[56:120];identity=struct.pack('<16f',*[float(i%5==0) for i in range(16)])
    assert view==identity
    for f in range(N):
        words=struct.unpack('<4I42f',control[f*184:(f+1)*184])
        assert words[:4]==(f,3 if f==0 else 2,W,H)
        assert words[4:15]==(1.,1.,1.,0.,0.,0.,0.,0.,0.,1024.,1.)
        assert control[f*184+56:(f+1)*184]==view+proj
    # Same stored row-major inverse as the CLOSED matched-camera recipe.
    cb=bytearray(416);cb[:64]=identity;cb[64:128]=inverse;cb[128:192]=identity
    struct.pack_into('<4f',cb,192,W,H,1/W,1/H);struct.pack_into('<4f',cb,208,W,H,1/W,1/H)
    struct.pack_into('<4f',cb,224,1,1,0,0)
    struct.pack_into('<3fI',cb,352,.1,1000,0,54)
    struct.pack_into('<f',cb,396,.008);struct.pack_into('<2f',cb,400,1,1)
    write(data/'converter_cb.bin',cb)
    ccb=bytearray(96);struct.pack_into('<4f',ccb,0,W,H,1/W,1/H);struct.pack_into('<I',ccb,16,8)
    struct.pack_into('<2f',ccb,32,1,1);struct.pack_into('<2f',ccb,68,1,1)
    write(data/'composer_cb.bin',ccb)
    zero=np.zeros((H,W,4));zhalf=halfwrite(np,data/'zero_half.bin',zero)
    zscalar=write(data/'zero_scalar.bin',np.zeros((H,W),dtype='<f4').tobytes())
    depth=write(data/'depth.bin',np.full((H,W),10,dtype='<f4').tobytes())
    normal=zero.copy();normal[...,2]=-1;normal[...,3]=.55
    # Geometry is not radiance: negative Z is required, not an RGB clipping case.
    write(data/'normal.bin',normal.astype('<f2').tobytes())
    write(data/'roughness.bin',np.full((H,W),.55,dtype='<f4').tobytes())
    write(data/'zero_uint4.bin',bytes(W*H*16))
    s=np.broadcast_to(np.array(SPECCODES,dtype=np.float64).T[np.arange(W)%8]/255,(H,W,3))
    dm=np.broadcast_to(np.array(DIFFCODES,dtype=np.float64)/255,(H,W,3))
    # Primary physics uses the exact material halfwords supplied to conversion.
    s=s.astype('<f2').astype(np.float64);dm=dm.astype('<f2').astype(np.float64)
    refs=[]
    for f in range(N):
        phase=np.where((np.arange(W)//32)%2==1,f%16,0)
        light=.75+np.array(LIGHTCODES,dtype=np.float64)[(np.arange(H)[:,None]+phase[None,:])%16][...,None]/np.array(LIGHTDIV,dtype=np.float64)
        refs.append(rgba(np,(s+dm)*light))
    refs=np.stack(refs);valid_rgb(np,refs,'primary physical truth')
    write(truth/'TOTAL.bin',refs.astype('<f8').tobytes())
    write(truth/'TOTAL_source_encoded_half.bin',refs.astype('<f2').tobytes())
    halfwrite(np,data/'raw_spec.bin',rgba(np,s));halfwrite(np,data/'raw_diff.bin',rgba(np,dm))
    rng=np.random.default_rng(91022);z=rng.standard_normal((N,H,W//2,3))
    noise=.15*(np.exp(.65*z-.5*.65**2)-1)
    conv=[]
    for f in range(N):
        jd=jobs/f'{f:02d}';jd.mkdir();raw=refs[f].copy();raw[:,W//2:,:3]+=noise[f]
        halfwrite(np,jd/'rawC.bin',raw)
        ins=[jd/'rawC.bin',data/'depth.bin',data/'zero_half.bin',data/'normal.bin',data/'roughness.bin',data/'depth.bin',data/'raw_diff.bin',data/'raw_spec.bin',data/'zero_scalar.bin',data/'zero_half.bin',data/'zero_half.bin',data/'zero_half.bin',data/'zero_half.bin',data/'zero_half.bin',data/'depth.bin',data/'zero_scalar.bin',jd/'rawC.bin']
        outs=[(jd/f'out{i}.bin',fmt) for i,fmt in enumerate(OUT_FMT)]
        job=gpujob(jd,item('input_cso')['path'],data/'converter_cb.bin',list(zip(ins,IN_FMT)),outs)
        conv.append(dict(frame=f,job=record(job),inputs=[record(p) for p in ins],outputs=[dict(path=str(p),bytes=W*H*(8 if fmt==10 else 4),format=fmt) for p,fmt in outs]))
    save(d/'assembly.json',dict(status='ASSEMBLY_CLOSED_NO_GPU_NATIVE',converter_jobs=conv,data=str(data),truth=str(truth),physical_reference='perframe decoded serialized material half S/D times declared RGB L; source-encoded C half separate',truth_records=[record(truth/'TOTAL.bin'),record(truth/'TOTAL_source_encoded_half.bin')],noise=dict(seed=91022,generator='NumPy PCG64/default_rng standard_normal frame/y/x/channel shape64x80x64x3',noise_generated_once=True),raw_materials=[record(data/'raw_spec.bin'),record(data/'raw_diff.bin')],camera_inverse_source=item('matched_camera'),source_projection_sha256=hashlib.sha256(proj).hexdigest(),converter_CB=record(data/'converter_cb.bin'),composer_CB=record(data/'composer_cb.bin')))

def producer(np,d):
    a=load(RUNTIME/'assemble'/'assembly.json');out=d/'native_inputs';out.mkdir();rows=a['converter_jobs']
    streammap=(None,2,3,4,5,1,0);ins=[]
    for slot,fmt in enumerate(NATIVE_FMT):
        if slot==0:r=write(out/'input0.bin',Path(a['data'],'depth.bin').read_bytes());frames=1
        else:
            p=out/f'input{slot}.bin'
            with p.open('xb') as stream:
                for row in rows:
                    r0=row['outputs'][streammap[slot]];assert Path(r0['path']).stat().st_size==r0['bytes']
                    b=Path(r0['path']).read_bytes()
                    if fmt==10:
                        arr=np.frombuffer(b,'<f2').reshape(H,W,4)
                        if slot in (5,6): valid_rgb(np,arr,'converter signal')
                        else: assert np.isfinite(arr).all() and np.all(arr[...,:3]==0),'static motion not zero'
                    if fmt==24:
                        packed=np.frombuffer(b,'<u4');assert np.all(packed==packed[0]),'static normal/material variation'
                    if slot==3:
                        g=np.frombuffer(b,'u1').reshape(H,W,4);codes=np.array(SPECCODES,dtype='u1').T[np.arange(W)%8]
                        assert np.all(g[...,:3]==codes[None,:,:]) and all(np.unique(g[...,c]).size>1 for c in range(3))
                    if slot==4:
                        g=np.frombuffer(b,'u1').reshape(H,W,4);assert np.all(g[...,:3]==np.array(DIFFCODES,dtype='u1'))
                    stream.write(b)
            r=record(p);frames=N
        ins.append((r,fmt,frames))
    gb=bytearray(Path(ins[3][0]['path']).read_bytes())
    guide=np.frombuffer(gb,'u1').reshape(N,H,W,4);clipped=0
    for f,row in enumerate(rows):
        raw=np.fromfile(Path(row['job']['path']).parent/'rawC.bin',dtype='<f2').reshape(H,W,4).astype(np.float64)
        valid_rgb(np,raw,'original stored noisy HALF C')
        clipped+=int(np.count_nonzero((raw[...,:3]<0)|(raw[...,:3]>1)))
        guide[f,...,:3]=np.rint(np.clip(raw[...,:3],0,1)*255).astype('u1')
    bguide=write(out/'B_SPEC_SDK_only.bin',gb)
    original=Path(ins[3][0]['path']).read_bytes();assert gb[3::4]==original[3::4]
    for row in rows:
        for i in (6,7):
            arr=np.fromfile(row['outputs'][i]['path'],dtype='<f2').reshape(H,W,4)
            if i==6: valid_rgb(np,arr,'Skip')
            else: assert np.isfinite(arr).all()
    cases=[];nd=RUNTIME/'native';assert not nd.exists()
    jobs=d/'native_jobs';jobs.mkdir()
    for name in ORDER:
        jd=jobs/name;jd.mkdir();sel=list(ins)
        if name.startswith('B'):sel[3]=(bguide,28,N)
        write(jd/'tuning_values.bin',Path(item('tuning')['path']).read_bytes())
        write(jd/'frame_controls.txt',Path(item('frame_controls')['path']).read_bytes())
        outputs=[nd/'outputs'/name/(s+'.bin') for s in ('diffuse','specular')]
        job=nativejob(jd,sel,item('provider')['path'],outputs)
        cases.append(dict(tag=name,job=record(job),inputs=[r for r,_,_ in sel],formats=list(NATIVE_FMT),input_frames=[1]+[N]*6,config=record(jd/'tuning_values.bin'),frame_controls=record(jd/'frame_controls.txt'),outputs=[dict(path=str(p),bytes=N*HALF_BYTES) for p in outputs],controls_path=str(jd/'dispatch_controls.bin')))
    assert all(cases[0]['inputs'][i]==case['inputs'][i] for case in cases for i in (0,1,2,4,5,6))
    save(d/'producer.json',dict(status='PRODUCER_QUALIFIED_CLOSED',assembly=str(RUNTIME/'assemble'/'assembly.json'),cases=cases,original_caller_SPEC=ins[3][0],B_SDK_SPEC=bguide,mapping='R8 nearest-even(saturate(decoded original stored HALF noisy C RGB)); no fitted mean/floor/filter',guide_clipped_RGB_words=clipped,original_declared_RGB_patterns_exact=True,slot3_alpha_exact=True,other_six_slots_exact=True,nonphysical_empirical_feature=True))

def prep_compositions(np,d,frames):
    a=load(RUNTIME/'assemble'/'assembly.json');p=load(RUNTIME/'produce'/'producer.json')
    data=Path(a['data']);tasks=[]
    for name in ORDER:
        for f in frames:
            native=RUNTIME/'native'/'outputs'/name;sd=[]
            for lobe in ('specular','diffuse'):
                with (native/(lobe+'.bin')).open('rb') as stream:
                    stream.seek(f*HALF_BYTES);b=stream.read(HALF_BYTES);assert len(b)==HALF_BYTES
                arr=np.frombuffer(b,'<f2').reshape(H,W,4);valid_rgb(np,arr,name+lobe,known_alpha=False)
                target=d/'slices'/name/f'{f:02d}';target.mkdir(parents=True,exist_ok=True)
                path=target/(lobe+'.bin');write(path,b);sd.append(path)
            cv=RUNTIME/'assemble'/'converter_jobs'/f'{f:02d}'
            for mode in MEASURES:
                jd=d/'compositions'/name/f'{f:02d}'/mode;jd.mkdir(parents=True)
                z=data/'zero_half.bin'
                assert mode=='TOTAL'
                paths=[sd[0],cv/'out4.bin',sd[1],cv/'out5.bin',cv/'out6.bin',cv/'out3.bin',cv/'out7.bin',data/'depth.bin',cv/'out2.bin',z,data/'zero_uint4.bin']
                outs=[(jd/f'out{i}.bin',fmt) for i,fmt in enumerate((10,10,3))]
                job=gpujob(jd,item('output_cso')['path'],data/'composer_cb.bin',list(zip(paths,COMP_FMT)),outs)
                tasks.append(dict(tag=name,frame=f,mode=mode,job=record(job),inputs=[record(v) for v in paths],outputs=[dict(path=str(v),bytes=W*H*(8 if fmt==10 else 16),format=fmt) for v,fmt in outs],measured_output=str(jd/'out0.bin')))
    save(d/'composition_jobs.json',dict(status='PREPARED_ACTUAL_CURRENT_CSO',jobs=tasks,only_TOTAL_original_caller_and_Skip=True))

def measured(np,stage,name,mode,frames):
    a=[]
    for f in frames:
        use='endpoint' if f==63 else 'remaining'
        p=RUNTIME/use/'compositions'/name/f'{f:02d}'/mode/'out0.bin'
        assert p.stat().st_size==HALF_BYTES
        v=np.fromfile(p,dtype='<f2').reshape(H,W,4).astype(np.float64);valid_rgb(np,v,str(p));a.append(v[...,:3])
    return np.stack(a)
def metrics(np,out,truth,lo,hi):
    # Per-frame moving truth, three independent RGB coefficients; never align outputs.
    v=out[:,:,lo:hi];t=truth[:,:,lo:hi,:3];err=v-t
    x=np.arange(lo,hi);y=np.arange(H);carriers={}
    for key,axis,frequency,idx in [('material',2,1/8,x),('illumination',1,1/16,y)]:
        prof=v.mean(1 if axis==2 else 2);ref=t.mean(1 if axis==2 else 2)
        carrier=np.exp(-2j*np.pi*frequency*idx)
        rv=np.einsum('fic,i->fc',ref-ref.mean(1,keepdims=True),carrier)
        ov=np.einsum('fic,i->fc',prof-prof.mean(1,keepdims=True),carrier)
        gain=[];phase=[];null=[]
        for frame in range(len(out)):
            gf=[];pf=[];nf=[]
            for c in range(3):
                zero=bool(abs(rv[frame,c])<1e-12);nf.append(zero)
                if zero:gf.append(None);pf.append(None)
                else:
                    q=ov[frame,c]/rv[frame,c];gf.append(float(q.real));pf.append(float(abs(np.angle(q))))
            gain.append(gf);phase.append(pf);null.append(nf)
        carriers[key]=dict(gain_RGB= gain,phase_RGB=phase,reference_zero_RGB=null,
                           leakage_RGB=(abs(ov)/len(idx)).tolist())
    profile=err.mean(1);profile-=profile.mean(1,keepdims=True)
    return dict(rmse=float(np.sqrt(np.mean(err**2))),bias_rgb=err.mean((0,1,2)).tolist(),temporal_std=float(np.std(err,axis=0).mean()),material_error=float(np.sqrt(np.mean(profile**2))),carriers=carriers)
def detail_ok(row):
    for key in ('material','illumination'):
        c=row['carriers'][key]
        for gains,phases,zeros in zip(c['gain_RGB'],c['phase_RGB'],c['reference_zero_RGB']):
            for g,ph,zero in zip(gains,phases,zeros):
                # This declared TOTAL clean fixture has both nonzero carriers in RGB.
                # Unexpected missing truth carrier is a qualification STOP, never PASS.
                assert not zero and g is not None and ph is not None,'unexpected zero clean reference carrier'
                if not (.95<=g<=1.05 and ph<=.05):return False
    return True
def score(np,d,endpoint):
    a=load(RUNTIME/'assemble'/'assembly.json');frames=[63] if endpoint else list(range(N))
    truth={m:np.fromfile(Path(a['truth'])/(m+'.bin'),dtype='<f8').reshape(N,H,W,4)[frames] for m in MEASURES}
    outs={(name,m):measured(np,'endpoint' if endpoint else 'remaining',name,m,frames) for name in ORDER for m in MEASURES}
    windows={'ENDPOINT63':[0]} if endpoint else {'FULL':list(range(N)),'STARTUP':list(range(8)),'MATURE':list(range(48,64))}
    regions={'WHOLE':(0,W),'STATIC_CLEAN':(0,32),'ANIM_CLEAN':(32,64),
             'STATIC_NOISY':(64,96),'ANIM_NOISY':(96,128)};rows={}
    for name in ORDER:
        rows[name]={}
        for win,ix in windows.items():
            rows[name][win]={reg:{m:metrics(np,outs[name,m][ix],truth[m][ix],lo,hi) for m in MEASURES} for reg,(lo,hi) in regions.items()}
    outcomes=[]
    for an,bn in (('A1','B1'),('A2','B2')):
        detail=all(detail_ok(rows[bn][win][reg]['TOTAL']) for win in windows for reg in ('STATIC_CLEAN','ANIM_CLEAN'))
        quality=None if endpoint else True;fail=[]
        if not detail:fail.append('absolute_clean_detail')
        if not endpoint:
            for win in windows:
                for reg in regions:
                    ar,br=rows[an][win][reg],rows[bn][win][reg]
                    if not br['TOTAL']['material_error']<ar['TOTAL']['material_error']:quality=False;fail.append(win+'/'+reg+'/TOTAL/material_no_strict_improvement')
                    for key in ('rmse','temporal_std'):
                        if br['TOTAL'][key]>ar['TOTAL'][key]:quality=False;fail.append(win+'/'+reg+'/TOTAL/'+key)
                    if any(abs(b)>abs(a) for a,b in zip(ar['TOTAL']['bias_rgb'],br['TOTAL']['bias_rgb'])):quality=False;fail.append(win+'/'+reg+'/TOTAL/bias')
        outcomes.append(dict(pair=[an,bn],detail_PASS=detail,quality_PASS=quality,combined_PASS=detail if endpoint else detail and quality,failures=fail))
    yes=[p['combined_PASS'] for p in outcomes]
    hard=[p['detail_PASS'] for p in outcomes]
    status=('REJECT_FIXED_SOURCE_RADIANCE_GUIDE_DETAIL' if not all(hard) else
            ('ENDPOINT_PASS_INCONCLUSIVE_REQUIRE_ALL64' if endpoint else 'ALL64_QUALITY_PASS_BOUNDED_EXPERIMENT_ONLY') if all(yes) else
            'INCONCLUSIVE_COHORT_VARIATION_STOP' if any(yes) else 'REJECT_FIXED_SOURCE_RADIANCE_GUIDE_QUALITY_STOP')
    encoded=np.fromfile(Path(a['truth'])/'TOTAL_source_encoded_half.bin',dtype='<f2').reshape(N,H,W,4).astype(np.float64)[frames]
    encoded_rows={name:{win:{reg:metrics(np,outs[name,'TOTAL'][ix],encoded[ix],lo,hi) for reg,(lo,hi) in regions.items()} for win,ix in windows.items()} for name in ORDER}
    save(d/'score.json',dict(status=status,endpoint_only=endpoint,actual_current_CSO=True,physical_reference='perframe decoded serialized material half S/D times moving RGB L, never changed/averaged',source_encoded_C_reference_diagnostic_only=encoded_rows,frames=frames,windows=windows,regions=regions,rows=rows,pairs=outcomes,repeat_hard_detail_disagreement=len(set(hard))>1,continuation_permitted=endpoint and all(yes),quality_PASS=(not endpoint and all(yes)),no_port_authority=True))

def main():
    if sys.flags.optimize or not __debug__:raise RuntimeError('optimized assertions prohibited')
    import numpy as np
    stage=sys.argv[1];d=Path(sys.argv[2]);assert d.is_dir()
    source_check()
    if stage=='assemble':assembly(np,d)
    elif stage=='qualify_producer':producer(np,d)
    elif stage=='prepare_endpoint':prep_compositions(np,d,[63])
    elif stage=='prepare_remaining':prep_compositions(np,d,list(range(63)))
    elif stage=='score_endpoint':score(np,d,True)
    elif stage=='score_all':score(np,d,False)
    else:raise ValueError(stage)
    save(d/(stage+'_worker_CLOSED.json'),dict(status='CPU_WORKER_CLOSED',PID=os.getpid(),python_EXE=str(Path(sys.executable).resolve()),actual_cwd=str(Path.cwd()),numpy_version=np.__version__,stage=stage,no_GPU_native_compiler_calls=True))
if __name__=='__main__':main()
