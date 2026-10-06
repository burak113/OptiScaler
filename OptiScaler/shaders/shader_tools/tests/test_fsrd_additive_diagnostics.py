"""GPU contracts for RGB attribution and the live ROI capture shader."""
from pathlib import Path
import hashlib, json, shutil, subprocess, os
import numpy as np
import run_fsrd_gpu_tests as t
from fsrd_alpha_common import GPUWorker,convert,rgba,save_json
from fsrd_additive_diagnostics import build_journal,journal,FIELDS
from inspect_fsrd_additive_capture import LIVE_FIELDS,read_live
from test_fsrd_additive_split import fit_oracle
from probe_fsrd_allocation_models import build_field_shader


def run():
    os.environ.pop('FSRD_LOSSLESS_BASELINE',None)
    output=Path(os.environ.get('FSRD_GPU_TEST_OUTPUT',str(t.ROOT/'tools_tmp/alpha_channel_contracts_final'))).resolve()
    output.mkdir(parents=True,exist_ok=True)
    dirs=build_journal(output)
    fielddir=build_field_shader(output)
    live=output/'live'; live.mkdir(exist_ok=True)
    for src in t.PRE.glob('*.hlsl*'): shutil.copy2(src,live/src.name)
    shutil.copy2(t.PRE/'RRTraceAdditive_Shader.cso',live/'FSRDInputConvAdditive_Shader.cso')
    checks=[]
    def check(name,passed,**values):
        checks.append(dict(name=name,passed=bool(passed),**values))
        print(('PASS ' if passed else 'FAIL ')+name,values,flush=True)
    h,w=29,43; y,x=np.indices((h,w)); pattern=((x+2*y)%7)/6
    d=rgba((.07+.4*pattern)[...,None]*np.array([.7,.85,1.]))
    s=t.rgba(w,h,(13/255,16/255,21/255))
    raw=rgba((d[...,:3]+s[...,:3])*[.45,.38,.32]+[.08,.07,.055])
    with GPUWorker(output):
        j=journal(dirs,raw,d,s,1)
        p=convert(raw,d,s,1,kernel='additive')
        for center in ((0,0),(14,21),(28,42)):
            share,accepted=fit_oracle(raw,d,s,center,1)
            check('journal independent fit '+str(center),np.array_equal(j['eligible'][center]>0,accepted)
                  and np.max(abs(share-j['p'][center]))<2e-5)
        check('actual transfer equals R delta-p',np.max(abs(j['transferred_rgb']-j['eligible_rgb']*j['delta_p']))<1e-7)
        check('data and prior weights bounded',np.all((j['data_weight']>=0)&(j['data_weight']<=1)))
        check('journal signal reconciles production DXIL',np.max(abs(j['specular_signal']-p[0][...,:3]))<=.001,
              maximum=float(np.max(abs(j['specular_signal']-p[0][...,:3]))))
        j0=journal(dirs,raw,d,s,0)
        check('zero strength transfers nothing',not np.any(j0['transferred_rgb']) and not np.any(j0['delta_p']))
        check('counterfactual retains identical fit evidence',np.array_equal(j0['eligible'],j['eligible']) and np.array_equal(j0['ridge_slope'],j['ridge_slope']))
        bad=s.copy(); bad[...,0]=1/255
        jc=journal(dirs,raw,d,bad,1)
        check('red unsafe minimum identified independently',np.all(jc['rejected'][...,0].astype(int)&8) and not np.any(jc['eligible'][...,0]))
        check('safe green blue remain independently eligible',np.mean(jc['eligible'][...,1:])>.9)
        flat=t.rgba(w,h,(.2,.2,.2))
        jf=journal(dirs,raw,flat,s,1)
        check('flat support reports lack of data',np.all(jf['rejected'].astype(int)&64) and not np.any(jf['eligible']))
        textured=s.copy(); textured[::2,:,:3]*=2
        jt=journal(dirs,raw,d,textured,1)
        check('patterned specular reports variation rejection',np.all(jt['rejected'].astype(int)&32) and not np.any(jt['eligible']))
        small=journal(dirs,raw[:3,:3],d[:3,:3],s[:3,:3],1)
        check('small footprint distinguishes unevaluated intercept',np.all(small['rejected'].astype(int)&4) and not np.any(small['evaluated'].astype(int)&512))
        floor=rgba(raw[...,:3]*.35)
        floorj=journal(dirs,raw,d,s,1,floor=floor)
        floorp=convert(raw,d,s,1,kernel='additive',floor=floor)
        check('Floor accounting separates eligible residual from spatial floor',
              np.max(abs(floorj['eligible_rgb']+floorj['spatial_floor_rgb']-floorj['raw_rgb']))<1e-6
              and np.mean(floorj['spatial_floor_rgb'])>0)
        check('Floor transfer is applied to the residual only',
              np.max(abs(floorj['transferred_rgb']-floorj['eligible_rgb']*floorj['delta_p']))<1e-7)
        check('Floor Skip journal reconciles stored production output',
              np.max(abs(floorj['skip_rgb']-floorp[6][...,:3]))<.001)
        # Same live bytecode, full-resource source coords, odd/partial ROI extent.
        live_fields=[]
        for strength in (0,1):
            values=[]
            for page in range(6):
                values.extend(convert(raw,d,s,strength,kernel='additive',directory=live,
                    size=(19,13),output_formats=[2]*8,
                    overrides=dict(DstTexSize=[w,h,1/w,1/h],InspectorChannel=page,
                                   InspectorScale=8,DebugDepthMax=8)))
            live_fields.append({name:v[...,:3] for name,v in zip(LIVE_FIELDS,values)})
        for index,strength in enumerate((0,1)):
            ref=j0 if strength==0 else j
            for name in FIELDS:
                if name=='settings': continue
                error=float(np.max(abs(live_fields[index][name]-ref[name][8:21,8:27])))
                check(f'live ROI strength{strength} {name}',error<=max(2e-5,float(np.max(abs(ref[name])))*2e-5),maximum=error)
        check('live source guides preserve ROI values',np.array_equal(live_fields[1]['source_diffuse'],d[8:21,8:27,:3].astype(np.float16).astype(np.float32)))
        check('live stored guides reproduce UNORM quantization',
              np.max(abs(live_fields[1]['stored_specular']-p[4][8:21,8:27,:3]))<1e-7)
        # A rejected model is a true same-kernel no-op, not apparent quality gained
        # from a differently compiled baseline or a different rounding path.
        field=np.zeros_like(raw)
        a=convert(raw,d,s,0,directory=fielddir,kernel='additive',resources={17:field})
        b=convert(raw,d,s,1,directory=fielddir,kernel='additive',resources={17:field})
        check('rejected field preserves every stored channel across endpoints',all(np.array_equal(x,y) for x,y in zip(a,b)))
        field[...,:3]=.75; field[...,3]=1
        c=convert(raw,d,s,1,directory=fielddir,kernel='additive',resources={17:field})
        check('research field changes only the selected RGB allocation',np.any(c[0][...,0]!=b[0][...,0])
              and np.array_equal(c[0][...,1:3],b[0][...,1:3]) and np.array_equal(c[1][...,1:3],b[1][...,1:3]))
        for page in (0,3,4,5):
            edge=convert(raw,d,s,1,directory=live,kernel='additive',size=(11,5),output_formats=[2]*8,
                overrides=dict(DstTexSize=[w,h,1/w,1/h],InspectorChannel=page,InspectorScale=32,DebugDepthMax=24))
            for slot,value in enumerate(edge):
                name=LIVE_FIELDS[page*8+slot]
                if name in j and name!='settings':
                    ref=j[name][24:,32:]
                    check('live partial render-edge '+name,np.max(abs(value[...,:3]-ref))<=max(2e-5,float(np.max(abs(ref)))*2e-5))
    report=dict(checks=checks,dispatches=t.timings,passed=all(c['passed'] for c in checks),
                live_shader_sha256=hashlib.sha256((t.PRE/'RRTraceAdditive_Shader.cso').read_bytes()).hexdigest())
    save_json(output/'results.json',report)
    if not report['passed']: raise SystemExit(1)


if __name__=='__main__': run()
