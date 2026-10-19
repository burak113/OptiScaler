"""Actual production lighting-validation DXIL vs the RR Lab input-only detector, plus isolated pass timings.
The SDK timing creates a signed context but records no RR dispatch. All quality replays use RR Lab.
"""
import argparse,ctypes,importlib.util,json,os,re,shutil,subprocess,sys,time
from pathlib import Path
import numpy as np
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[3]
sys.path[:0]=[str(HERE.parent),str(HERE),'E:/FSRD/rrlab']
from fsrd_toolchain import compile_cpp,dxc
from rrlab.captures import Capture
from rrlab.fixtures import Step,Freeze
from rrlab.fixtures23 import LocalPulse23
from rrlab.runner import roi_controls

def build(out):
    (out/'pch.h').write_text('#pragma once\n')
    shader=out/'consumer.cso'
    subprocess.run([str(dxc()),'-T','cs_6_2','-E','CSMain','-O3','-force-rootsig-ver','rootsig_1_0',str(HERE/'nrd_bridge_consumer_fixture.hlsl'),'-Fo',str(shader)],check=True)
    (out/'consumer_shader.h').write_text('const unsigned char ConsumerShaderBytes[] = {'+','.join(map(str,shader.read_bytes()))+'};\n')
    exe=out/'temporal_control.exe';os.environ['FSRD_CPP_CACHE']=str(out/'cache')
    compile_cpp(HERE/'fsrd_temporal_control.cpp',exe,['d3d12.lib','dxgi.lib','d3dcompiler.lib'],
                [out,HERE,ROOT/'OptiScaler',ROOT/'OptiScaler/include',ROOT/'external/streamline',ROOT/'external/FidelityFX-SDK/ffx-api/include/ffx_api'])
    return exe

def hook():
    p=Path('E:/FSRD/rrlab/hooks/23_antilag_v20.py');s=importlib.util.spec_from_file_location('actual_reference',p)
    m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def case(exe,out,name,c):
    folder=out/name;folder.mkdir();data=folder/'data';data.mkdir();result=folder/'gpu';result.mkdir()
    paths=[data/(n+'.bin') for n in ['diff','spec','motion','depth']]
    files=[p.open('wb') for p in paths];controls=[];reference=[];stats=[];mod=hook();rot,tr=c.motion()
    for i in range(c.n):
        m=c.img(i,'input_motion');m[...,0]*=c.RW/c.W;m[...,1]*=c.RH/c.H
        expected=mod.motion(c,i,m.copy()).astype('f2')
        reference.append(expected[...,2].copy())
        stats.append((mod._s['mean'].copy(),mod._s['var'].copy(),mod._s['fast'].copy()))
        for f,n in zip(files[:2],['input_diffuse','input_specular']):f.write(c.raw(i,n))
        files[2].write(m.astype('f2').tobytes());files[3].write(c.depth(i).astype('f4').tobytes())
        a=roi_controls(c,i);qyy=np.float32(np.linalg.inv(a[24:40].reshape(4,4).astype(np.float64))[1,1])
        controls.append(f'{int(c.controls(i)[44])} {int(rot[i]>.1 or tr[i]>.0015)} {int(bool(c.controls(i)[45]&1))} {c.requested_tuning()[5]:.9g} {qyy:.9g} {a[41]:.9g}')
    for f in files:f.close()
    ctrl=data/'controls.txt';ctrl.write_text('\n'.join(controls)+'\n')
    job=folder/'job.txt';job.write_text(f'{c.W} {c.H} {c.n}\n'+'\n'.join('"'+p.as_posix()+'"' for p in paths+[ctrl,result])+'\n')
    start=time.perf_counter();r=subprocess.run([str(exe),str(job)],capture_output=True,text=True,timeout=240,creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS)
    (folder/'native.log').write_text(r.stdout+r.stderr);print(r.stdout+r.stderr,flush=True);r.check_returncode()
    assert 'debug_errors=0 debug_warnings=0' in r.stdout
    actual=np.memmap(result/'motion.bin',mode='r',dtype='f2',shape=(c.n,c.H,c.W,4))
    mismatch=0;unchanged_words=0;selected=0;examples=[]
    for i in range(c.n):
        original=c.img(i,'input_motion');original[...,0]*=c.RW/c.W;original[...,1]*=c.RH/c.H
        original=original.astype('f2')
        assert np.array_equal(actual[i][...,[0,1,3]].view('u2'),original[...,[0,1,3]].view('u2')),f'{name} frame{i}: motion RG/alpha changed'
        diff=actual[i,...,2].view('u2')!=reference[i].view('u2');count=int(diff.sum());mismatch+=count
        if count and len(examples)<8:examples.append(dict(frame=i,count=count,xy=np.argwhere(diff)[:8].tolist()))
        selected+=int((actual[i,...,2]!=original[...,2]).sum());unchanged_words+=c.W*c.H*3
    summary=dict(case=name,capture=c.uuid,frames=c.n,mismatch_pixels=mismatch,total_pixels=c.n*c.H*c.W,
                 selected_pixel_frames=selected,exact_RG_alpha_words=unchanged_words,examples=examples,seconds=time.perf_counter()-start)
    (folder/'comparison.json').write_text(json.dumps(summary,indent=1));print(json.dumps(summary),flush=True)
    assert mismatch==0,f'{name}: production GPU vs RR Lab reset decisions differ; inspect comparison.json'
    # Keep small diagnostic arrays and summaries. Input staging and full motion readbacks are regenerable.
    del actual
    shutil.rmtree(data);(result/'motion.bin').unlink()
    return summary

def main():
    p=argparse.ArgumentParser();p.add_argument('--case',default='local',choices=['local','dim','bright','static','turn','holdout','freeze','negative','near','pulse','pulse16','phase','local2','diffuse-only','specular-only','opposing-lobes','edge-corner','edge-heavy','edge-full65x63','edge-full63x65','edge-full65x65','all','apply-cutoffs','timing','timing-real','event-timing','motion-timing','lifetime','alias']);a=p.parse_args()
    out=Path(os.environ['FSRD_GPU_TEST_OUTPUT']);out.mkdir(parents=True,exist_ok=True);exe=build(out)
    if a.case=='apply-cutoffs':
        r=subprocess.run([str(exe),'--apply-cutoffs'],capture_output=True,text=True,timeout=240,creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS)
        (out/'apply-cutoffs.log').write_text(r.stdout+r.stderr);print(r.stdout+r.stderr);r.check_returncode()
        assert 'debug_errors=0 debug_warnings=0' in r.stdout
        assert 'PASS isolated Apply cutoffs cases=51' in r.stdout
        return
    if a.case=='alias':
        r=subprocess.run([str(exe),'--alias'],capture_output=True,text=True,timeout=240,creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS)
        (out/'alias.log').write_text(r.stdout+r.stderr);print(r.stdout+r.stderr);r.check_returncode()
        assert 'debug_errors=0 debug_warnings=0' in r.stdout
        assert 'PASS canonical/private G3 motion commit alias protection' in r.stdout
        return
    if a.case=='lifetime':
        r=subprocess.run([str(exe),'--lifetime',str(out/'retained')],capture_output=True,text=True,timeout=240,creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS)
        (out/'lifetime.log').write_text(r.stdout+r.stderr);print(r.stdout+r.stderr);r.check_returncode()
        assert 'debug_errors=0 debug_warnings=0' in r.stdout
        assert 'generations=2 independent_history_images=6 independent_change_maps=2 independent_support_maps=2' in r.stdout
        return
    if a.case=='motion-timing':
        rows=[]
        for name in ['f2ef375f','daa670e9','d6d2a083']:
            c=Capture(name)
            for i in range(c.n):
                current=c.camera(i);previous=c.camera(max(0,i-1))
                valid=i>0 and c.frames[i]['frame_parameters'].get('previous_valid',False) and not bool(c.controls(i)[45]&1)
                rows.append(np.concatenate([previous[2].ravel(),current[2].ravel(),current[0],current[1],[float(valid)]]).astype('f4'))
        pairs=out/'camera-pairs.bin';np.stack(rows).tofile(pairs)
        (out/'motion-timing-scope.json').write_text(json.dumps(dict(captured_pairs=len(rows),captures=['f2ef375f','daa670e9','d6d2a083'],
            included='production CameraTurnDegrees + translation sqrt + NextMotionStability + actual SDK key2 update/check',
            excluded='wrapper locking, frame/resource bookkeeping, immutable snapshot copy; no GPU dispatch'),indent=1))
        r=subprocess.run([str(exe),'--motion-timing',str(pairs)],capture_output=True,text=True,timeout=240,creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS)
        (out/'motion-timing.log').write_text(r.stdout+r.stderr);print(r.stdout+r.stderr);r.check_returncode()
        assert len([x for x in r.stdout.splitlines() if x.startswith('motion_stability_timing ')])==2
        assert 'debug_errors=0 debug_warnings=0' in r.stdout
        return
    if a.case=='event-timing':
        c=Capture('c7294a8e');command=[str(exe),'--event-timing'];staging=[];records={}
        for w,h in [(1505,847),(2560,1440)]:
            folder=out/f'event-captured-{w}x{h}';folder.mkdir();staging.append(folder);command.append(str(folder))
            iy=np.minimum(np.arange(h)*c.H//h,c.H-1);ix=np.minimum(np.arange(w)*c.W//w,c.W-1)
            rawfields={}
            for target,source,dt,ch in [('spec','input_specular','f2',4),('diff','input_diffuse','f2',4),
                ('motion','input_motion','f2',4),('depth','input_depth','f4',1),('normals','input_normal_roughness','u4',1),
                ('spec_albedo','input_specular_albedo','u1',4),('diff_albedo','input_diffuse_albedo','u1',4)]:
                a=np.frombuffer(c.raw(0,source),dt).reshape(c.H,c.W,ch)[iy[:,None],ix[None,:]].copy()
                if target=='motion':a[...,:3]=0
                rawfields[target]=a
            records[f'{w}x{h}']={}
            for name,gain in [('base',1.),('bright',2.),('dim',.5)]:
                sub=folder/name;sub.mkdir();record={}
                for target,a in rawfields.items():
                    v=a.copy();clipped=0
                    if target in ('spec','diff'):
                        f=v.astype('f4');f[...,:3]*=gain;clipped=int(np.count_nonzero(f[...,:3]>65504))
                        f[...,:3]=np.minimum(f[...,:3],65504);v=f.astype('f2')
                        assert np.array_equal(v[...,3].view('u2'),a[...,3].view('u2'))
                    assert np.isfinite(v).all() if v.dtype.kind=='f' else True
                    payload=v.tobytes();(sub/(target+'.bin')).write_bytes(payload)
                    record[target]={'sha256':__import__('hashlib').sha256(payload).hexdigest(),'clipped_rgb':clipped}
                records[f'{w}x{h}'][name]=record
        scope={'capture':c.uuid,'source_frame':0,'input_hashes':records,'warm':32,'trials_per_phase':20,'first_trials_excluded':4,
            'phase_order':'rotated still/bright/dim per trial','measured_frame':{'still':35,'bright':33,'dim':35},'fixture_controls':[.1,.6703613,65504],
            'motion':'xyz explicitly zeroed consistently for fixed geometry, alpha retained',
            'scope':'isolated production guard only; fixed real lighting with synthetic gain steps; nearest resize only at2560; no RR dispatch or game FPS',
            'timestamps':'natural transition and measured pass share submission; outer + per-pass, diagnostic copies/fences excluded; CPU includes query markers'}
        (out/'event-timing-scope.json').write_text(json.dumps(scope,indent=1))
        r=subprocess.run(command,capture_output=True,text=True,timeout=240,creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS)
        (out/'event-timing.log').write_text(r.stdout+r.stderr);print(r.stdout+r.stderr);r.check_returncode()
        assert 'debug_errors=0 debug_warnings=0' in r.stdout
        assert len([x for x in r.stdout.splitlines() if x.startswith('guard_event_summary ')])==6
        for folder in staging:shutil.rmtree(folder)
        return
    if a.case in ('timing','timing-real'):
        command=[str(exe),'--timing'];staging=[]
        if a.case=='timing-real':
            c=Capture('c7294a8e');command=[str(exe),'--timing-files']
            for w,h in [(1505,847),(2560,1440)]:
                folder=out/f'captured-{w}x{h}';folder.mkdir();staging.append(folder);command.append(str(folder))
                iy=np.minimum(np.arange(h)*c.H//h,c.H-1);ix=np.minimum(np.arange(w)*c.W//w,c.W-1)
                for target,source,dt,ch in [('spec','input_specular','f2',4),('diff','input_diffuse','f2',4),
                    ('motion','input_motion','f2',4),('depth','input_depth','f4',1),('normals','input_normal_roughness','u4',1),
                    ('spec_albedo','input_specular_albedo','u1',4),('diff_albedo','input_diffuse_albedo','u1',4)]:
                    raw=np.frombuffer(c.raw(0,source),dt).reshape(c.H,c.W,ch)
                    raw[iy[:,None],ix[None,:]].tofile(folder/(target+'.bin'))
            (out/'timing-scope.json').write_text(json.dumps(dict(capture=c.uuid,source_frame=0,
                method='published real-input words; nearest resize only at 2560x1440; fixed in time; 16 retained motion slots; no RR or in-game FPS measurement'),indent=1))
        r=subprocess.run(command,capture_output=True,text=True,timeout=240,creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS)
        (out/'timing.log').write_text(r.stdout+r.stderr);print(r.stdout+r.stderr);r.check_returncode()
        assert len([x for x in r.stdout.splitlines() if x.startswith('lighting_guard_timing ')])==2
        assert 'debug_errors=0 debug_warnings=0' in r.stdout
        for folder in staging:shutil.rmtree(folder)
        return
    def signed_guard_only(near=False):
        # Pure guard-input stress test, not a physically reconstructed RR quality fixture.
        c=Step('d6d2a083',48,3.,(0,300,128,550));original_depth=c.depth
        c.depth=(lambda i:np.full_like(original_depth(i),.02)) if near else (lambda i:-original_depth(i))
        c.uuid+='#guard-near-depth-only' if near else '#guard-negative-depth-only'
        return c
    def lobe_step(kind):
        # Guard-only wiring falsifier: independent lobe evidence must not cross into the other lobe.
        src=Capture('d6d2a083');c=Step(src,48,3.,(0,300,128,550));both=c.raw
        def raw(i,name):
            if kind=='diffuse-only' and name=='input_specular':return src.raw(i,name)
            if kind=='specular-only' and name=='input_diffuse':return src.raw(i,name)
            if kind=='opposing-lobes' and name=='input_specular':
                return Step(src,48,.5,(0,300,128,550)).raw(i,name)
            return both(i,name)
        c.raw=raw;c.uuid+='#guard-'+kind
        return c
    class GuardOnlyEdge:
        # Arithmetic/lifetime fixture only, never an AMD RR quality replay.
        def __init__(self,label,w,h,kind,gain):
            self.W,self.H,self.n=w,h,64;self.kind,self.gain=kind,gain
            self.source=Capture('d6d2a083')
            self.RW,self.RH,self.X0,self.Y0=self.source.RW,self.source.RH,self.source.X0,300
            self.uuid='#guard-only-'+label
        def motion(self):return np.zeros(self.n),np.zeros(self.n)
        def requested_tuning(self):return self.source.requested_tuning()
        def controls(self,i):
            u=self.source.controls(0).copy();u[44]=i;u[45]&=np.uint32(0xfffffffe);return u
        def depth(self,i):return np.full((self.H,self.W),-10,np.float32)
        def raw(self,i,name):
            a=np.zeros((self.H,self.W,4),np.float16)
            if name=='input_motion':a[...,3]=1
            elif name in ('input_diffuse','input_specular'):
                a[...,:3]=1 if name=='input_diffuse' else .25;a[...,3]=5
                selected=np.zeros((self.H,self.W),bool)
                if self.kind=='corner':selected[-1,-1]=True
                elif self.kind=='heavy':
                    selected[32:self.H:8,-1]=True
                    if name=='input_diffuse':a[selected,:3]=100
                else:selected[:]=True
                if i>=32 and (name=='input_diffuse' or self.kind=='full'):
                    a[selected,:3]=(a[selected,:3].astype(np.float32)*self.gain).astype(np.float16)
            else:raise ValueError(name)
            return a.tobytes()
        def img(self,i,name):return np.frombuffer(self.raw(i,name),np.float16).reshape(self.H,self.W,4).astype(np.float32)
    cases={'edge-corner':lambda:GuardOnlyEdge('corner65x65',65,65,'corner',.5),
           'edge-heavy':lambda:GuardOnlyEdge('heavy65x63',65,63,'heavy',.1),
           'edge-full65x63':lambda:GuardOnlyEdge('full65x63',65,63,'full',.5),
           'edge-full63x65':lambda:GuardOnlyEdge('full63x65',63,65,'full',2.),
           'edge-full65x65':lambda:GuardOnlyEdge('full65x65',65,65,'full',2.),
           'diffuse-only':lambda:lobe_step('diffuse-only'),'specular-only':lambda:lobe_step('specular-only'),
           'opposing-lobes':lambda:lobe_step('opposing-lobes'),'phase':lambda:Step('d6d2a083',48,2.,(13,307,109,563)),
           'local2':lambda:Step('d6d2a083',48,2.,(0,300,128,550)),
           'pulse16':lambda:LocalPulse23(period=16),'pulse':lambda:LocalPulse23(period=8),'negative':lambda:signed_guard_only(),'near':lambda:signed_guard_only(True),'local':lambda:Step('d6d2a083',48,3.,(0,300,128,550)),
           'dim':lambda:Step('d6d2a083',48,.5),'bright':lambda:Step('d6d2a083',48,2.),
           'static':lambda:Capture('d6d2a083'),'turn':lambda:Capture('06fadf38'),
           'holdout':lambda:Capture('14ef3b0d'),'freeze':lambda:Freeze('d6d2a083',40,128,step_at=48,gain=.5)}
    rows=[case(exe,out,k,f()) for k,f in cases.items() if a.case in (k,'all')]
    (out/'result.json').write_text(json.dumps(dict(passed=True,cases=rows),indent=1))
    print('PASS cases='+str(len(rows))+' mismatch_pixels='+str(sum(x['mismatch_pixels'] for x in rows)),flush=True)
if __name__=='__main__':main()
