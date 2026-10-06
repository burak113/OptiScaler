"""Feed actual Floor DXIL reference outputs into actual AMD RR as a virtual albedo.

This is an offline experiment, not a production pipeline change. Ground truth is
used by metrics and the explicitly named oracle control only. Floor gets noisy
radiance, constant albedo, depth and normals. No RR result is needed to make its
filtered reference. No additional handover or Floor base is added after RR.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import subprocess

import numpy as np
import probe_fsrd_real_rr as rr


def audit_shaders(pre, out):
    """Recompile sources independently and require the exact tested bytecode."""
    audit = out/'shader_audit'
    audit.mkdir(parents=True, exist_ok=True)
    dxc = Path(os.environ.get('FSRD_DXC',
        'C:/Program Files (x86)/Windows Kits/10/bin/10.0.26100.0/x64/dxc.exe'))
    hashes = {}
    for name in ('FSRDFloorSeed', 'FSRDFloor', 'FSRDOutputComp'):
        compiled = audit/(name+'.cso')
        cmd = [str(dxc), '-T', 'cs_6_2', '-E', 'CSMain', '-enable-16bit-types',
               '-O3', '-Qstrip_debug', '-Qstrip_reflect', '-Fo', str(compiled),
               str(pre/(name+'.hlsl'))]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        (audit/(name+'.log')).write_text(proc.stdout+proc.stderr, encoding='utf-8')
        if proc.returncode:
            raise RuntimeError('Shader compilation failed: '+name+'\n'+proc.stdout+proc.stderr)
        expected = (pre/(name+'_Shader.cso')).read_bytes()
        if compiled.read_bytes() != expected:
            raise RuntimeError('Production bytecode does not match current source: '+name)
        hashes[name] = hashlib.sha256(expected).hexdigest()
    return hashes


def reference_sequence(t, p, observed, directory, include_base=False):
    """Only observed RGB + constant geometry/material enter production shaders."""
    n, h, w, _ = observed.shape
    depth = np.full((h, w), 10, np.float32)
    albedo = t.rgba(w, h, (.5, .5, .5))
    normal = t.rgba(w, h, (0, 0, -1))
    packed = t.rgba(w, h, (1, 1, .1), 1/3)
    zero = t.rgba(w, h, (0, 0, 0))
    values = dict(DstTexSize=[w,h,1/w,1/h], DetailPreservation=1.0,
                  NoiseSuppression=.75, FloorHandoverAnchorClamp=4., FloorHandoverCorrelationMix=1.)
    outputs = dict(seed=[], reference=[])
    if include_base:
        outputs['floor_base'] = []
    start = len(t.timings)
    for f in range(n):
        colour = rr.rgba(observed[f])
        base, z, surface, seed = t.seed(colour, depth, normal, albedo)
        comp_inputs = [zero, albedo, zero, albedo, zero, packed, seed, z]
        reference = p.dispatch(values, comp_inputs, 'reference')
        # Detect accidental post-RR dependency: candidate must be identical with
        # a radically different reconstructed colour. No clean truth is supplied.
        if f in (0, n-1):
            alternate = list(comp_inputs)
            alternate[2] = t.rgba(w,h,(4.,.01,2.))
            check = p.dispatch(values, alternate, 'reference')
            if not np.array_equal(reference, check):
                raise RuntimeError('DetailReference depends on RR; cannot use it before RR')
        if np.any(seed[...,3]<0):
            raise RuntimeError('Unsupported/routed seed in controlled planar fixture')
        outputs['seed'].append(seed[...,:3])
        outputs['reference'].append(reference[...,:3])
        if include_base:
            outputs['floor_base'].append(t.filter_floor(base,z,surface,albedo)[...,:3])
        if (f+1) % 8 == 0:
            print(f'Floor {directory.name}: {f+1}/{n} frames', flush=True)
    outputs = {k: np.stack(v) for k,v in outputs.items()}
    for key, array in outputs.items():
        if not np.all(np.isfinite(array)) or np.any(array<0):
            raise RuntimeError('Invalid candidate: '+key)
    np.savez_compressed(directory/'floor_sequences.npz', **outputs)
    (directory/'floor_dispatches.json').write_text(json.dumps(t.timings[start:],indent=2),encoding='utf-8')
    return outputs


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--frames',type=int,default=64)
    ap.add_argument('--suite',choices=['smoke','full'],default='full')
    ap.add_argument('--reuse-floor',action='store_true',help='Use existing shader readbacks only if source and input hashes match')
    args=ap.parse_args()
    out=args.output.resolve()
    if out.drive.upper()!='F:' or args.frames<4:
        raise ValueError('F: output and at least four frames required')
    out.mkdir(parents=True,exist_ok=True)
    temp=out/'temp'; temp.mkdir(exist_ok=True)
    os.environ.update(TEMP=str(temp),TMP=str(temp),FSRD_VS_ROOT='F:/VisualStudio',
                      FSRD_GPU_TEST_OUTPUT=str(out/'floor_dispatches'))
    import run_fsrd_gpu_tests as t
    import fsrd_stage_probe as p
    t.build_runner()
    exe=out/'fsrd_rr_runner.exe'
    rr.compile_cpp(rr.HERE/'fsrd_rr_runner.cpp',exe,('d3d12.lib','dxgi.lib'))
    shader_hashes=audit_shaders(t.PRE, out)
    sources=[dict(name='fine_static',motion='static',noise='fine'),
             dict(name='fine_untracked',motion='untracked',noise='fine'),
             dict(name='coarse_static',motion='static',noise='coarse'),
             dict(name='clean_static',motion='static',noise='none')]
    if args.suite=='smoke': sources=sources[:1]
    report=dict(frames=args.frames,dimensions=[rr.W,rr.H],dll=str(rr.DLL),
                dll_sha256=hashlib.sha256(rr.DLL.read_bytes()).hexdigest(),
                shader_hashes=shader_hashes,reference_requires_rr=False,
                floor_settings=dict(noise=.75,detail=1.0,anchor=4,mix=1),datasets=[])
    for source in sources:
        d=out/source['name']; d.mkdir(exist_ok=True)
        clean,noisy=rr.sequence(args.frames,source['motion'],source['noise'])
        input_hash=hashlib.sha256(noisy.tobytes()).hexdigest()
        provenance=dict(observed_sha256=input_hash,shader_hashes=shader_hashes,frames=args.frames,
                        settings=report['floor_settings'],geometry='flat z10 normal -Z, constant .5 albedo, original zero rough')
        if args.reuse_floor and (d/'floor_sequences.npz').exists():
            if json.loads((d/'provenance.json').read_text()) != provenance:
                raise RuntimeError('Stale Floor cache '+source['name'])
            with np.load(d/'floor_sequences.npz') as data: refs={k:data[k].copy() for k in data.files}
        else:
            refs=reference_sequence(t,p,noisy,d,include_base=source['name']=='fine_static')
            (d/'provenance.json').write_text(json.dumps(provenance,indent=2),encoding='utf-8')
        np.savez_compressed(d/'inputs.npz',clean=clean,noisy=noisy)
        record=dict(source=source,reference_metrics={},runs=[])
        for name, array in refs.items():
            record['reference_metrics'][name]=rr.metrics(array,array,clean,noisy,noisy,source['motion'])
        carriers=dict(flat=np.full_like(noisy,128/255.),white=np.ones_like(noisy),
                      oracle=clean,noisy=noisy,**refs)
        for kind, carrier in carriers.items():
            # Literal bounded virtual albedo, no oracle-derived scaling or pixels.
            a=np.round(np.clip(carrier,.008,1)*255)/255.
            for signal in ('dd','is'):
                case=dict(signal=signal,albedo=kind,path='demod',roughness=.1,
                          material=1,motion=source['motion'],noise=source['noise'])
                folder=d/(signal+'_'+kind)
                job,result,_,_,raw,factor,skip,_=rr.prepare_case(folder,case,args.frames,
                    inputs=(clean,noisy),albedo_override=a)
                proc=subprocess.run([str(exe),str(job)],cwd=folder,capture_output=True,text=True)
                (folder/'runner.log').write_text(proc.stdout+proc.stderr,encoding='utf-8')
                if proc.returncode:
                    raise RuntimeError(proc.stdout+proc.stderr)
                denoised=np.fromfile(result,dtype='<f2').astype(np.float32).reshape(args.frames,rr.H,rr.W,4)[...,:3]
                final=denoised*factor+skip
                metrics=rr.metrics(final,denoised,clean,noisy,raw,source['motion'])
                if not metrics['finite'] or np.any(final<0):
                    raise RuntimeError('Invalid real RR result')
                if f'dispatches={args.frames} validation_errors=0 validation_warnings=0 sdk_errors=0 sdk_warnings=0' not in proc.stdout:
                    raise RuntimeError('RR validation was not clean: '+proc.stdout+proc.stderr)
                # The matching factor and Skip close identity to half-storage precision.
                closure=float(np.max(np.abs(raw*factor+skip-noisy)))
                if closure > .003:
                    raise RuntimeError('Demod-remod closure failed')
                np.savez_compressed(folder/'preview.npz',clean=clean[-1],noisy=noisy[-1],
                    carrier=carrier[-1],albedo=a[-1],result=final[-1],mean_result=final[args.frames//2:].mean(0))
                record['runs'].append(dict(carrier=kind,signal=signal,metrics=metrics,
                    identity_max_error=closure,case=case,log=proc.stdout.strip()))
                print(source['name'],signal,kind,
                      f'noise={metrics["quiet_error_ratio"]} contrast={metrics["structure_contrast_ratio"]:.4f} rmse={metrics["output_rmse"]:.5f}',flush=True)
        report['datasets'].append(record)
        (out/'results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print('Completed:',out/'results.json',flush=True)


if __name__=='__main__':
    main()
