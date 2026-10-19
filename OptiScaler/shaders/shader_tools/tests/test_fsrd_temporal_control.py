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
    p=Path('E:/FSRD/rrlab/hooks/23_antilag_v14.py');s=importlib.util.spec_from_file_location('actual_reference',p)
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
    p=argparse.ArgumentParser();p.add_argument('--case',default='local',choices=['local','dim','bright','static','turn','holdout','freeze','negative','near','pulse','all','timing','timing-real','motion-timing','lifetime','alias']);a=p.parse_args()
    out=Path(os.environ['FSRD_GPU_TEST_OUTPUT']);out.mkdir(parents=True,exist_ok=True);exe=build(out)
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
        assert 'generations=2 independent_history_images=6 independent_change_maps=2' in r.stdout
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
    cases={'pulse':lambda:LocalPulse23(period=8),'negative':lambda:signed_guard_only(),'near':lambda:signed_guard_only(True),'local':lambda:Step('d6d2a083',48,3.,(0,300,128,550)),
           'dim':lambda:Step('d6d2a083',48,.5),'bright':lambda:Step('d6d2a083',48,2.),
           'static':lambda:Capture('d6d2a083'),'turn':lambda:Capture('06fadf38'),
           'holdout':lambda:Capture('14ef3b0d'),'freeze':lambda:Freeze('d6d2a083',40,128,step_at=48,gain=.5)}
    rows=[case(exe,out,k,f()) for k,f in cases.items() if a.case in (k,'all')]
    (out/'result.json').write_text(json.dumps(dict(passed=True,cases=rows),indent=1))
    print('PASS cases='+str(len(rows))+' mismatch_pixels='+str(sum(x['mismatch_pixels'] for x in rows)),flush=True)
if __name__=='__main__':main()
