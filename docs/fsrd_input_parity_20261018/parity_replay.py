"""Controlled same-frame native/synthetic-composite AMD RR experiment.

All variants keep the same captured controls, alpha, geometry and material guides.
The synthetic composite is reconstructed with the CAPTURED AMD material guides;
this is not a claim that they equal Cyberpunk's late compositor multipliers.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

os.environ['OPENBLAS_NUM_THREADS'] = '2'
os.environ['OMP_NUM_THREADS'] = '2'
os.environ['TEMP'] = os.environ['TMP'] = 'F:/FSRD/tmp'
import numpy as np
import ctypes
ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(),0x4000)
sys.path.insert(0, str(Path(__file__).with_name('reference')))
from cap2 import LUMA, f32
from capture_adapter import Cap, controls
sys.path.insert(0, 'F:/FSRD/sol_batch')
from gpu_lock import gpu_lock

WORK = Path('F:/FSRD/sol_batch/21-input-parity')
OUT = Path('E:/FSRD/sol_batch/21-input-parity')
EXE = WORK/'shared-real/shared_rr.exe'
DLL = 'F:/OptiRevelations/OSA-21-input-parity/external/FidelityFX-SDK-v2/Kits/FidelityFX/signedbin/amd_fidelityfx_loader_dx12.dll'


def replay(c, variant, frames, normal_original=False, scale=256.):
    """Returns two half arrays in game units. File staging is removed after success."""
    if variant.startswith('scale_'):
        scale=float(variant.split('_')[1])
    diff_scale=spec_scale=scale
    if variant.startswith('ds_'):
        diff_scale,spec_scale=map(float,variant.split('_')[1:3])
    production=variant.startswith('gpu_')
    if production:
        diff_scale,spec_scale=map(float,variant.split('_')[1:3])
    mapping_pivot=float(variant.split('_')[1]) if variant.startswith('asinhD_') else None
    if mapping_pivot is not None:
        diff_scale,spec_scale=16.,256.
    cpu_d,cpu_s=(1.,1.) if production else (diff_scale,spec_scale)
    def map_diffuse(rgb,inverse=False):
        l=rgb.astype(np.float64)@LUMA
        target=mapping_pivot*(np.sinh(l/mapping_pivot) if inverse else np.arcsinh(l/mapping_pivot))
        value=rgb*np.divide(target,l,out=np.ones_like(l),where=l!=0)[...,None]
        if not np.isfinite(value).all():raise ValueError('Nonfinite representation roundtrip')
        return value
    out = WORK / ('stage_' + variant)
    out.mkdir(parents=True, exist_ok=True)
    names = ['input_depth','input_motion','input_normal_roughness',
             'input_specular_albedo','input_diffuse_albedo','input_diffuse','input_specular']
    fmts = [41,10,24,28,28,10,10]
    files = {n: open(out / (n+'.bin'), 'wb') for n in names}
    err_sum = 0.
    err_den = 0.
    with open(out / 'controls.bin', 'wb') as cf:
        for i in frames:
            by_name = {im['name']: im for im in c.frames[i]['images']}
            raw = lambda name: (c.dir / by_name[name]['file']).read_bytes()
            d, s = c.img(i,'input_diffuse'), c.img(i,'input_specular')
            ad = c.img(i,'input_diffuse_albedo',np.uint8)/255.
            ass = c.img(i,'input_specular_albedo',np.uint8)/255.
            total = d[...,:3]*ad[...,:3] + s[...,:3]*ass[...,:3]
            if variant.startswith('common'):
                # Physical equality is exact before fp16 rounding, also for a zero guide.
                # Channels with both guides zero have zero composed energy.
                q = ad[...,:3] + ass[...,:3]
                common = total / np.maximum(q,1e-8)
                strength = float(variant.split('_')[1]) if '_' in variant else 1.
                d[...,:3] = (1-strength)*d[...,:3] + strength*common
                s[...,:3] = (1-strength)*s[...,:3] + strength*common
            elif variant.startswith('hitgate'):
                # Isolate the combined route's specular tracking gate. RGB is unchanged.
                r = ((c.img(i,'input_normal_roughness',np.uint32,1)>>20)&1023)/1023.
                t = np.clip((.30-r)/.15,0,1)
                s[...,3] *= t*t*(3-2*t)
            for a,factor in ((d,cpu_d),(s,cpu_s)):
                a[...,:3] = np.minimum(a[...,:3]*factor,65504).astype(np.float16).astype(np.float32)/factor
            recomposed = d[...,:3]*ad[...,:3] + s[...,:3]*ass[...,:3]
            err_sum += float(np.abs(recomposed-total).sum())
            err_den += float(np.abs(total).sum())
            for n in names:
                if n == 'input_motion':
                    m = c.img(i,n)
                    m[...,0] *= c.RW/c.W
                    m[...,1] *= c.RH/c.H
                    if variant.startswith('mvj_') and i>0:
                        now=np.frombuffer(controls(c,i),np.float32)[3:5]
                        previous=np.frombuffer(controls(c,i-1),np.float32)[3:5]
                        m[...,:2]+=float(variant.split('_')[1])*(previous-now)/np.array([c.W,c.H])
                    files[n].write(m.astype(np.float16).tobytes())
                elif n in ('input_diffuse','input_specular'):
                    a = d if n == 'input_diffuse' else s
                    a = a.copy()
                    if mapping_pivot is not None and n=='input_diffuse':
                        a[...,:3]=map_diffuse(a[...,:3])
                    a[...,:3] *= cpu_d if n=='input_diffuse' else cpu_s
                    files[n].write(a.astype(np.float16).tobytes())
                elif n == 'input_normal_roughness' and normal_original:
                    files[n].write(raw('recovery_original_normal_roughness'))
                else:
                    files[n].write(raw(n))
            cf.write(controls(c,i))
    for f in files.values():
        f.close()
    requested = c.frames[frames[0]]['settings']
    tuning = [float(f32(v)) for v in requested['requested_values'][:6]]
    use = int(requested['override_mask'] == 63)
    lines = [f'{c.W} {c.H} {len(frames)} {use} ' + ' '.join(map(str,tuning)) + f' "{DLL}"']
    lines.extend(f'"{(out/(n+".bin")).as_posix()}" {fmt}' for n,fmt in zip(names,fmts))
    lines.append(' '.join(f'"{(out/n).as_posix()}"' for n in ('diff_out.bin','spec_out.bin','controls.bin')))
    lines.append(f'{int(diff_scale)} {int(spec_scale)}' if production else '1 1')
    (out/'job.txt').write_text('\n'.join(lines)+'\n')
    t0=time.perf_counter()
    with gpu_lock('21-input-parity'):
        exe=EXE
        proc=subprocess.run([str(exe),str(out/'job.txt')],capture_output=True,text=True,timeout=240)
    (WORK/f'{c.dir.name[:8]}_{variant}.log').write_text(proc.stdout+proc.stderr)
    if proc.returncode:
        raise RuntimeError(proc.stdout+proc.stderr)
    read=lambda n,factor: (np.fromfile(out/n,np.float16).reshape(len(frames),c.H,c.W,4)[...,:3].astype(np.float32)/factor).astype(np.float16)
    d,s=read('diff_out.bin',cpu_d),read('spec_out.bin',cpu_s)
    if mapping_pivot is not None:
        d=map_diffuse(d.astype(np.float32),inverse=True).astype(np.float16)
    # Only remove this known task staging folder; never touch capture or source files.
    assert out.parent.resolve()==WORK.resolve() and out.name.startswith('stage_')
    shutil.rmtree(out)
    return d,s,{'seconds':time.perf_counter()-t0,'input_composite_relative_l1':err_sum/max(err_den,1e-30),
                'provider_stdout':proc.stdout.strip(),'specular_scale':spec_scale,'diffuse_scale':diff_scale,
                'normal_original':normal_original,'production_scale_pass':production,'asinh_diffuse_pivot':mapping_pivot,
                'composite_error_scope':'before optional asinh representation; scale-only input closure' }


def metrics(c, d, s, eval_frames, mask=None):
    """Descriptive temporal variability; geometry content/jitter can contribute."""
    by_name = {im['name']: im for im in c.frames[0]['images']}
    from bench_util import gaussian
    reference=eval_frames[len(eval_frames)//2]
    z = np.abs(c.img(reference,'input_depth',np.float32,1))
    m=(z>0)&(z<500)
    m[:12]=False; m[-12:]=False; m[:,:12]=False; m[:,-12:]=False
    depth_edge=np.hypot(*np.gradient(np.log(z+1e-4)))>.02
    m &= gaussian(depth_edge.astype(np.float32),1.5)<.05
    if mask is not None:
        m &= mask
    a=[]
    for k in eval_frames:
        ad=c.img(k,'input_diffuse_albedo',np.uint8)[...,:3]/255.
        ass=c.img(k,'input_specular_albedo',np.uint8)[...,:3]/255.
        value=d[k].astype(np.float32)*ad+s[k].astype(np.float32)*ass
        if k!=reference:
            value,valid=c.warp(reference,k,value)
            m &= valid
        a.append(value)
    a=np.stack(a)
    l=a@LUMA
    mean=l.mean(0)
    # Fixed original-input support. Candidate-dependent masks bias comparisons.
    original=c.rgb(reference,'in')@LUMA
    valid=m&(original>np.quantile(original[m],.1))
    cv=l.std(0)/np.maximum(mean,1e-12)
    # Chroma deviation scales RGB to common luminance, avoiding exposure changes.
    chroma=a/np.maximum(l[...,None],1e-12)
    chromastd=chroma.std(0).mean(-1)
    return {'pixels':int(valid.sum()),'frames':list(eval_frames),
            'cv_p50':float(np.median(cv[valid])),'cv_p90':float(np.quantile(cv[valid],.9)),
            'chroma_std_p90':float(np.quantile(chromastd[valid],.9)),
            'mean_luma':float(mean[valid].mean()),
            'mean_detail':float(np.abs(mean-gaussian(mean,1.5))[valid].mean())}


def main():
    cid=sys.argv[1] if len(sys.argv)>1 else 'd6d2a083'
    variants=sys.argv[2:] or ['native','common_1','native2','common_0.5','hitgate']
    c=Cap(cid)
    frames=list(range(c.n))
    # Captured normals preserve identical provider behavior. Recovery is never replayed.
    normal_original=False
    evaluation=list(range(max(0,c.n-24),c.n))
    if cid.startswith('f2ef'):
        evaluation=list(range(34,min(c.n,50)))
    existing=OUT/f'{cid}_results.json'
    results=json.loads(existing.read_text()) if existing.exists() else {}
    for v in variants:
        d,s,metadata=replay(c,v,frames,normal_original)
        np.save(WORK/f'{cid}_{v}_d.npy',d)
        np.save(WORK/f'{cid}_{v}_s.npy',s)
        results[v]={'provider':metadata,'metrics':metrics(c,d,s,evaluation)}
        print(cid,v,json.dumps(results[v]),flush=True)
        (OUT/f'{cid}_{v}.json').write_text(json.dumps(results[v],indent=2))
        (OUT/f'{cid}_results.json').write_text(json.dumps(results,indent=2))

if __name__=='__main__':
    main()
