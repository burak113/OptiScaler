"""Actual B native shader fixture; --run requires explicit lead compiler/GPU grant."""
from pathlib import Path
import argparse,hashlib,itertools,json,os,re,subprocess,sys,time
import numpy as np
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import test_fsrd_nrd_raw_native as base
import test_fsrd_nrd_raw_prepass as independent
legacy=base.legacy;TASK=base.TASK;CHECKS=0

def need(value,name):
    global CHECKS
    CHECKS+=1
    if not value:raise AssertionError(name)

def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def prepare(output):
    # Preserve exactly the original production include/audit adapter and its assertions.
    base.prepare(output)
    raw=(output/'production_nrd_raw.cpp').read_text()
    need(raw.count('ResTrack_Dx12::RetainComputeDispatch(')==1,'exact single application Retain seam only')
    (output/'production_nrd_raw.cpp').write_text(raw.replace('ResTrack_Dx12::RetainComputeDispatch(','RawPrePassRetainComputeDispatch('))
    original=(HERE/'nrd_raw_signal_fixture.cpp').read_text();at=original.index('#undef main')
    need(original[at:].count('int main(int argc,char** argv)')==1,'standalone A main after inner undef only')
    (output/'raw_a_fixture_support.cpp').write_text(original[:at]+original[at:].replace('int main(int argc,char** argv)','int RawAStandaloneMain(int argc,char** argv)'))
    rng=np.random.default_rng(0x15B);sample=rng.uniform(.125,2,(8,12,4)).astype('<f2');normal=np.full((6,9,2),.5);z=np.ones((6,9),'f4')*5;z[:,5:]=100
    for mode in [0,1,2]:
        scalar,active=independent.reconstruct(sample,9,6,(1,2),mode,1,True,normal,z)
        batch,batch_active=reference_grid(sample,9,6,(1,2),mode,1,True,normal,z)
        need(np.array_equal(active,batch_active) and np.array_equal(scalar.view('<u2'),batch.view('<u2')),'independent scalar and batch interpolation references bit-exact')
    root=output/'prepass-inputs';root.mkdir(exist_ok=True);w=h=128;y,x=np.mgrid[:h,:w]
    rows=[]
    for dm,sm,phase,table,encoded in itertools.product(range(3),range(3),range(2),range(2),range(2)):
        i=len(rows);origin=[(0,0),(1,0),(3,2)][i%3];rows.append(dict(diff_mode=dm,spec_mode=sm,phase=phase,table=table,flag=(0 if not encoded else [1,0x80000000,0x7fc00000][i%3]),word=(36 if (i//3)%2 else 303),origin=origin,rect=[w,h],source_size=[w+8,h+4],material=0))
    for key,value in [('mode',[3,2]),('rect',[0x43000000,h]),('origin',[-1,0]),('origin',[0x7fffffff,0]),('size',[32,h+4])]:
        row=dict(diff_mode=0,spec_mode=1,phase=1,table=len(rows)%2,flag=1,word=36,origin=[0,0],rect=[w,h],source_size=[w+8,h+4],material=0)
        if key=='mode':row['diff_mode'],row['spec_mode']=value
        elif key=='rect':row['rect']=value
        elif key=='origin':row['origin']=value
        else:row['source_size']=value
        rows.append(row)
    for material in [1,2]:rows.append(dict(diff_mode=0,spec_mode=2,phase=1,table=material%2,flag=1,word=303,origin=[3,2],rect=[w,h],source_size=[w+8,h+4],material=material))
    for phase in [0,1]:rows.append(dict(diff_mode=0,spec_mode=0,phase=phase,table=phase,flag=0,word=303 if phase==0 else 36,origin=[0,0],rect=[w,h],source_size=[w+8,h+4],material=0,provider_control=True))
    for i,row in enumerate(rows):
        row['name']=f'b{i:02d}';path=root/row['name'];sw,sh=row['source_size'];sy,sx=np.mgrid[:sh,:sw]
        # Asymmetric signed chroma plus alternating finite native inactive/signed-zero alpha.
        raw_spec=np.empty((sh,sw,4),'<f2');raw_diff=raw_spec.copy()
        raw_spec[...,0]=.5+(sx%9)/16;raw_spec[...,1]=((sx+2*sy)%7-3)/32;raw_spec[...,2]=((sx+sy)%5-2)/32
        raw_diff[...,0]=.625+(sy%11)/32;raw_diff[...,1]=((2*sx+sy)%9-4)/32;raw_diff[...,2]=((sx+3*sy)%7-3)/32
        alpha=np.array([0.,-0.,-1.,.125,.5,2.,7.,31.],'<f2')
        raw_spec[...,3]=alpha[(sx+sy)%8];raw_diff[...,3]=alpha[(2*sx+sy+1)%8]
        raw_spec[0,0,:3]=[np.nan,np.inf,-np.inf];raw_diff[0,1,:3]=[-0.,-.5,np.nan]
        raw_spec[1,1,3]=np.nan;raw_diff[1,2,3]=np.inf
        if row.get('provider_control'):
            # A bounded synthetic input-reconstruction control, not an attested
            # physical BSDF/native-title ray oracle. Positive assigned hitA5/7.
            reference_spec=np.stack((.4+.2*(sx%9)/9,.25+.15*(sy%7)/7,.3+.1*((sx+sy)%11)/11),-1).astype('f4')
            reference_diff=np.stack((.25+.15*(sy%9)/9,.5+.1*(sx%7)/7,.35+.2*((sx+2*sy)%13)/13),-1).astype('f4')
            rng=np.random.default_rng(0x15BCB2026);noise=rng.choice([.5,1.5],(sh,sw,1)).astype('f4')
            raw_spec[...,:3]=(reference_spec*noise).astype('<f2');raw_spec[...,3]=5
            raw_diff[...,:3]=(reference_diff*noise).astype('<f2');raw_diff[...,3]=7
        # Padding outside any supported source centre is poisoned; source bytes may never change.
        raw_spec[:,-3:,:3]=[17,3,-5];raw_diff[-2:,:,:3]=[19,-7,9]
        nr=legacy.packed_nr(np.stack((.45+.08*x/(w-1),.47+.05*y/(h-1),.12+.5*((x+y)%13)/13,((x//16+y//16)%4)/3),-1))
        depth=(1+(x+2*y)%61).astype('<f4');depth[:,w//2:]+=100;depth[:2,:2]=0
        motion=np.zeros((h,w,4),'<f2');motion[...,3]=1
        material=np.stack(((x%11+.5)/12,(y%13+.5)/14,((x+y)%7+.5)/8,((x//8+y//8)%3)*.5),-1).astype('<f2')
        rough=np.ones((h,w),'<f2');rough[(x+2*y)%7==0]=np.nan
        params=legacy.frame(w,h,0);params.update(jitter=(0,0),previous_jitter=(0,0),native_material_guides=bool(row['material']),preserve_native_material_ids=True)
        dummy=np.zeros((h,w,4),'<f2');legacy.write_case(path,{'spec':dummy,'diff':dummy,'nr':nr,'depth':depth,'motion':motion,'material':material,'material_roughness':rough},params)
        raw_spec.tofile(path/'raw_spec.bin');raw_diff.tofile(path/'raw_diff.bin')
        if row.get('provider_control'):
            reference_spec.tofile(path/'reference_source_spec.bin');reference_diff.tofile(path/'reference_source_diff.bin')
        row['status']=independent.state(w,h,tuple(row['origin']),tuple(row['rect']),(row['diff_mode'],row['spec_mode']),((sw,sh),(sw,sh)))
    lines=[]
    for r in rows:
        fields=[r['name'],*r['origin'],*r['rect'],r['diff_mode'],r['spec_mode'],r['phase'],r['table'],r['word'],r['flag'],r['material'],*r['source_size'],r['status']]
        lines.append(' '.join(map(str,fields)))
    (root/'prepass-cases.txt').write_text(f'{len(rows)} {w} {h}\n'+'\n'.join(lines)+'\n')
    manifest={'schema':'fsrd.raw-prepass-helper-native.v1','width':w,'height':h,'cases':rows,'payload_sha256':{str(p.relative_to(root)):digest(p) for p in sorted(root.rglob('*.bin'))},'scope':'current raw input reconstruction only; no native NRD/provider execution/game quality evidence'}
    (root/'manifest.json').write_text(json.dumps(manifest,indent=2));need(len(rows)==81,'72 known combinations +5 error statuses +2 material cases +2 positive-alpha provider controls')
    return root,manifest

def build(output):
    shader=output/'consumer.cso'
    subprocess.run([str(base.dxc()),'-T','cs_6_2','-E','CSMain','-O3','-force-rootsig-ver','rootsig_1_0',str(HERE/'nrd_bridge_consumer_fixture.hlsl'),'-Fo',str(shader)],check=True)
    (output/'consumer_shader.h').write_text('const unsigned char ConsumerShaderBytes[] = {'+','.join(str(b) for b in shader.read_bytes())+'};\n')
    exe=output/'nrd_raw_prepass_fixture.exe';base.compile_cpp(HERE/'nrd_raw_prepass_fixture.cpp',exe,('d3d12.lib','dxgi.lib'),(output,HERE,base.PASS,base.ROOT/'OptiScaler',base.ROOT/'OptiScaler/include',base.ROOT/'external/streamline'));return exe

def native(exe,inputs,output):
    import psutil
    start=time.monotonic();peak=0;log=output/'prepass.native.log'
    with log.open('w') as stream:
        proc=subprocess.Popen([str(exe),str(inputs)],stdout=stream,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW);measured=psutil.Process(proc.pid);measured.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
        while proc.poll() is None:
            try:peak=max(peak,measured.memory_info().rss)
            except psutil.NoSuchProcess:pass
            if peak>int(2.5*1024**3) or time.monotonic()-start>300:proc.kill();proc.wait();raise RuntimeError('B native memory/time cap; negative log retained')
            time.sleep(.02)
        rc=proc.wait()
    text=log.read_text(errors='replace');print(text,end='');need(rc==0,'B actual native exit0');need('debug_errors=0 debug_warnings=0' in text,'B strict debug errors/warnings0')
    match=re.search(r'PASS raw_prepass_native_checks=(\d+) provider_calls=0 native_nrd_calls=0',text);need(match is not None,'B no-provider terminal marker')
    return {'native_checks':int(match[1]),'seconds':time.monotonic()-start,'peak_resident_bytes':peak,'executable_sha256':digest(exe),'log':str(log)}

def reference_grid(source,width,height,origin,mode,phase,encoding,normals,depth):
    yy,xx=np.mgrid[:height,:width];sx=(xx+origin[0])>>(mode!=2);sy=yy+origin[1]
    native=source[sy,sx].astype('f4');y,co,cg=np.moveaxis(native[...,:3],-1,0)
    with np.errstate(invalid='ignore'):
        rgb=np.stack((y-cg+co,y+cg,y-cg-co),-1) if encoding else native[...,:3]
    rgb=np.where(np.isfinite(rgb),np.clip(rgb,0,65504),0);rgb=np.where(rgb==0,np.float32(0),rgb)
    plain=np.concatenate((rgb,np.where(np.isfinite(native[...,3:4]),native[...,3:4],0)),axis=-1).astype('<f2')
    active=np.ones((height,width),bool) if mode==2 else ((xx^yy^phase)&1)==mode
    if mode==2:return plain,active
    # Independent FP64 batch evaluation of the scalar geometric definition.
    xy=2*(normals.astype('f8')-.5);normal=np.concatenate((xy,(1-np.abs(xy).sum(-1))[...,None]),-1)
    t=np.maximum(-normal[...,2],0);normal[...,:2]+=np.where(normal[...,:2]>=0,-t[...,None],t[...,None]);normal/=np.sqrt((normal*normal).sum(-1))[...,None]
    left=np.maximum(xx-1,0);right=np.minimum(xx+1,width-1)
    def weights(q):
        alignment=np.clip((normal*normal[yy,q]).sum(-1),0,1);a=np.abs(depth).astype('f8');z=np.abs(depth[yy,q]).astype('f8')
        return alignment**2/(1+np.abs(a-z)/np.maximum(np.maximum(a,z),1e-6))
    wl,wr=weights(left),weights(right);a,b=plain[yy,left].astype('f8'),plain[yy,right].astype('f8');total=wl+wr
    value=np.divide(a*wl[...,None]+b*wr[...,None],total[...,None],out=np.zeros_like(a),where=total[...,None]>0)
    fallback=np.abs(depth[yy,left]-depth)<=np.abs(depth[yy,right]-depth);value=np.where((total==0)[...,None],np.where(fallback[...,None],a,b),value)
    value=np.where((xx==0)[...,None],b,value);value=np.where((xx==width-1)[...,None],a,value)
    return np.where(active[...,None],plain,value.astype('<f2')),active

def half_ulp(value):
    with np.errstate(over='ignore'):
        up=np.nextafter(value,np.float16(np.inf)).astype('f4');down=np.nextafter(value,np.float16(-np.inf)).astype('f4')
    return np.maximum(up-value.astype('f4'),value.astype('f4')-down)

def compare(root,manifest):
    h,w=manifest['height'],manifest['width'];rows=[];traced_alpha=set();mode_pairs=set();max_half_ulp=0
    for case in manifest['cases']:
        path=root/case['name'];ox,oy=case['origin'];sw,sh=case['source_size'];status=case['status']
        raw=np.fromfile(path/'raw_owned.bin','<u2');header=raw[:768].view('<u4');packed=raw[768:].reshape(h,w,8)
        expected=np.zeros(384,'<u4');expected[0]=status;expected[114:116]=[ox&0xffffffff,oy&0xffffffff];expected[118:120]=case['rect'];expected[129:131]=[case['phase'],np.array([65504.],'<f4').view('<u4')[0]];expected[144:146]=[case['diff_mode'],case['spec_mode']]
        need(np.array_equal(header,expected),'only exact B operands/status in owned header, UINT rect bits retained')
        nr=np.fromfile(path/'out_nr.bin','<u4').reshape(h,w);normals=np.stack((nr&1023,(nr>>10)&1023),-1).astype('f8')/1023
        depth=np.fromfile(path/'out_depth.bin','<f4').reshape(h,w);need(np.isfinite(depth).all(),'B owned guide depth finite')
        for lobe,mode,offset in [('spec',case['spec_mode'],0),('diff',case['diff_mode'],4)]:
            source=np.fromfile(path/f'raw_{lobe}.bin','<f2').reshape(sh,sw,4);out=np.fromfile(path/f'out_{lobe}.bin','<f2').reshape(h,w,4)
            need(np.array_equal(np.fromfile(path/f'source_{lobe}_after.bin','<u2'),source.view('<u2').ravel()),'B source full allocation/padding bytes unchanged')
            need(np.isfinite(out).all(),'all B reconstructed RR inputs finite')
            if status:
                need(np.all(packed==0),'invalid GPU operands produce zero raw payload before any source sample');need(np.all(out.view('<u2')==0),'invalid GPU operands produce canonical finite zero RR input');continue
            yy,xx=np.mgrid[:h,:w];sx=(xx+ox)>>(mode!=2);sy=yy+oy;expected_raw=source[sy,sx].view('<u2');finite=(expected_raw&0x7c00)!=0x7c00
            need(np.array_equal(packed[...,offset:offset+4][finite],expected_raw[finite]),'actual raw address map finite RGBA words exact before codec')
            need(np.all((packed[...,offset:offset+4][~finite]&0x7c00)==0x7c00),'raw malformed category survives until decoder')
            reference,active=reference_grid(source,w,h,(ox,oy),mode,case['phase'],case['flag']!=0,normals,depth)
            need(np.array_equal(out[active].view('<u2'),reference[active].view('<u2')),'EVERY traced RGBA exact incl signed chroma/finite native alpha±0')
            traced_alpha.update(int(z) for z in reference[active,3].view('<u2'))
            if mode==2:need(np.array_equal(out.view('<u2'),reference.view('<u2')),'mode2 full output exact plain decoder with no reconstruction')
            else:
                # New interpolation test only: independent FP64 geometry vs FP32 normal
                # normalization can round at an adjacent half word. Exact traced tests above
                # have zero tolerance; only the reconstructed values get one half ULP.
                difference=np.abs(out[~active].astype('f4')-reference[~active].astype('f4'));ulp=half_ulp(reference[~active])
                need(np.all(difference<=ulp),'untraced geometry-only interpolation within one final-half ULP')
                max_half_ulp=max(max_half_ulp,float(np.max(difference/np.maximum(ulp,2**-24))))
        flag=np.fromfile(path/'encoding_flag.bin','<u4')[303];need(int(flag)==case['flag'],'B executed uint native303/36 flag after postrecord CB update')
        if not status:
            original_nr=np.fromfile(path/'nr.bin','<u4').reshape(h,w);original_z=np.fromfile(path/'depth.bin','<f4').reshape(h,w)
            expected_nr=base.shifted(original_nr,ox,oy);z=base.shifted(original_z,ox,oy);need(np.array_equal(nr,expected_nr),'B geometry native source origin exact')
            epsilon=np.array([0x358637bd],'<u4').view('<f4')[0];positive=np.fromfile(path/'positive_viewz.bin','<f4').reshape(h,w)
            need(np.array_equal(positive,np.maximum(np.abs(z),epsilon)),'B positive ViewZ matches guide-only native expression without color filter')
            mode_pairs.add((case['diff_mode'],case['spec_mode']))
        motion=np.fromfile(path/'out_motion.bin','<f2').reshape(h,w,4);need(np.all(motion[...,:3]==0)&np.all(motion[...,3]==1),'B current Temporal motion deferred independently of lighting')
        alb={key:np.fromfile(path/f'out_{key}.bin','u1').reshape(h,w,4) for key in ['spec_albedo','diff_albedo']}
        if not case['material']:need(np.all(alb['spec_albedo'][...,:3]==255)&np.all(alb['diff_albedo'][...,:3]==255),'B white guides exact')
        else:
            material=base.shifted(np.fromfile(path/'material.bin','<f2').reshape(h,w,4),ox,oy);rough=base.shifted(np.fromfile(path/'material_roughness.bin','<f2').reshape(h,w),ox,oy);fake_nr=nr.copy();valid=np.zeros((h,w),bool);valid[:h-oy,:w-ox]=True
            if case['material']==2:fake_nr=(fake_nr&~np.uint32(1023<<20))|np.uint32(1023<<20)
            oracle=legacy.material_guide_bounds({'nr':fake_nr,'material':material},alb)
            for key,bounds in [('spec_albedo','spec_bounds'),('diff_albedo','diff_bounds')]:
                known=oracle['known']&valid
                if key=='spec_albedo' and case['material']==2:known&=np.isfinite(rough)
                actual=alb[key][...,:3].astype('f8')/255;lo,hi=oracle[bounds];need(np.all((actual[known]>=lo[known])&(actual[known]<=hi[known])),'B nonzero-origin material guide independent interval')
                fallback=(~oracle['known'])&valid
                if key=='spec_albedo' and case['material']==2:fallback|=~np.isfinite(rough)&valid
                need(np.all(alb[key][fallback,:3]==255),'B invalid material exact white fallback')
        rows.append({'case':case['name'],'diff_mode':case['diff_mode'],'spec_mode':case['spec_mode'],'status':status,'origin':case['origin']})
    need(mode_pairs==set(itertools.product(range(3),range(3))),'all nine independent native signal mode pairs actually exercised')
    need({0,0x8000}<=traced_alpha,'both native traced alpha signed-zero words exercised exactly')
    return {'cases':rows,'max_reconstructed_half_ulp_error':max_half_ulp,'traced_alpha_words':sorted(traced_alpha)}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run',action='store_true');parser.add_argument('--compare-only',action='store_true');parser.add_argument('--output',type=Path,default=Path(os.environ.get('FSRD_GPU_TEST_OUTPUT',TASK/'tests/raw-prepass-native')));args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    if args.compare_only:root=args.output/'prepass-inputs';manifest=json.loads((root/'manifest.json').read_text());result={}
    else:
        root,manifest=prepare(args.output)
        if not args.run:print(json.dumps({'prepared_cases':len(manifest['cases']),'checks':CHECKS,'adapter_checks':base.CHECKS,'compiler_run':False,'gpu_run':False}));return
        result=native(build(args.output),root,args.output)
    result.update(compare(root,manifest));result.update(python_checks=CHECKS,reference_checks=independent.CHECKS,material_interval_checks=legacy.CHECKS,scope='actual owned B helper only; provider/native NRD calls0; not title activation or game quality',input_manifest_sha256=digest(root/'manifest.json'),sources={str(p):digest(p) for p in [Path(__file__),HERE/'nrd_raw_prepass_fixture.cpp',base.PASS/'FSRDNrdRawSignals_Dx12.cpp',base.PASS/'FSRDNrdBridgePass_Dx12.cpp']})
    (args.output/'prepass-comparison.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
if __name__=='__main__':main()
