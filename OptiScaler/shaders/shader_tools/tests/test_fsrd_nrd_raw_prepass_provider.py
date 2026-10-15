"""Signed SDK CB-vs-owned-input-reconstruction control, reusing sealed R5 EXE.
No native NRD, physical-BSDF/native-title quality, or improvement claim.
"""
from pathlib import Path
import argparse,hashlib,json,os,re,subprocess,sys,time
import numpy as np
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE))
import test_fsrd_nrd_raw_native as raw
TASK=raw.TASK;CHECKS=0
R5=Path('F:/FSRD/sol_batch/15-nrd-ghosting/tests/checkerboard-provider-r5')
R5REPORT=Path('E:/FSRD/sol_batch/15-nrd-ghosting/tests/checkerboard-provider-r5/checkerboard-probe.json')

def need(value,name):
    global CHECKS
    CHECKS+=1
    if not value:raise AssertionError(name)
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def prepare(native_output,output):
    need(output.resolve().is_relative_to(TASK.resolve()),'task-local output only')
    root=native_output/'prepass-inputs';manifest=json.loads((root/'manifest.json').read_text());native=json.loads((native_output/'prepass-comparison.json').read_text())
    need(native['native_checks']>0 and len(native['cases'])==81,'actual successful 81-case B helper output required')
    for name,sha in manifest['payload_sha256'].items():need(digest(root/name)==sha,'immutable raw input '+name)
    controls=sorted((r for r in manifest['cases'] if r.get('provider_control')),key=lambda r:r['phase']);need(len(controls)==2 and [r['phase'] for r in controls]==[0,1],'exact paired native phases')
    paths=[root/r['name'] for r in controls];w,h=manifest['width'],manifest['height'];frames=32
    for name in ['raw_spec.bin','raw_diff.bin','out_depth.bin','out_motion.bin','out_nr.bin','out_spec_albedo.bin','out_diff_albedo.bin','reference_source_spec.bin','reference_source_diff.bin']:
        need(digest(paths[0]/name)==digest(paths[1]/name),'both native phases have identical source/geometry '+name)
    old=json.loads(R5REPORT.read_text());exe=R5/'checkerboard_probe_runner.exe';provider=Path(old['provider_path'])
    need(digest(exe)==old['executable_sha256'],'exact sealed already-tested R5 executable')
    need(digest(R5/'checkerboard_probe_runner.cpp')==old['generated_runner_sha256'],'sealed real API source unchanged')
    need(digest(provider)==old['provider_sha256']=='48f1e5888ba6a0a3d59a98b9751e37c392b0f7b8c223d0082d5c1f40642879d3','exact installed signed AMD1.2 provider')
    output.mkdir(parents=True,exist_ok=True);jobs=[];input_seals={};references={}
    for variant in ['sdk-packed','owned-reconstructed']:
        directory=output/variant;directory.mkdir(exist_ok=True)
        guide_files=[('depth.bin','out_depth.bin',41),('motion.bin','out_motion.bin',10),('normal.bin','out_nr.bin',24),('spec_albedo.bin','out_spec_albedo.bin',28),('diff_albedo.bin','out_diff_albedo.bin',28)]
        lines=[]
        for name,source,fmt in guide_files:
            target=directory/name;target.write_bytes((paths[0]/source).read_bytes());lines.append(f'"{target.as_posix()}" {fmt} 1')
        for lobe,hit in [('diff',7),('spec',5)]:
            two=[]
            for case,path in zip(controls,paths):
                own=np.fromfile(path/f'out_{lobe}.bin','<f2').reshape(h,w,4);need(np.isfinite(own).all(),'actual owned decoded RR input finite')
                need(np.all(own[...,3]==hit),'positive assigned native hit parameter exact before SDK')
                if variant=='owned-reconstructed':two.append(own);continue
                sw,sh=case['source_size'];source=np.fromfile(path/f'raw_{lobe}.bin','<f2').reshape(sh,sw,4)
                packed=np.full((h,w,4),[37,3,9,hit],'<f2')
                for y in range(h):
                    xs=2*np.arange(w//2)+((y^case['phase'])&1)
                    packed[y,:w//2]=source[y,xs//2]
                    need(np.array_equal(packed[y,:w//2].view('<u2'),own[y,xs].view('<u2')),'SDK packed traced samples bit-exact to actual owned shader traced output')
                two.append(packed)
            sequence=np.stack([two[frame&1] for frame in range(frames)])
            target=directory/f'{lobe}.bin';sequence.tofile(target);lines.append(f'"{target.as_posix()}" 10 {frames}')
            if variant=='sdk-packed':
                case=controls[0];sw,sh=case['source_size'];source=np.fromfile(paths[0]/f'reference_source_{lobe}.bin','<f4').reshape(sh,sw,3);yy,xx=np.mgrid[:h,:w];references[lobe]=source[yy,xx//2]
        # Matrices use the SAME shared production GetRRMatrix transpose convention.
        params=raw.legacy.frame(w,h,0);camera=[*params['view'].T.ravel(),*params['projection'].T.ravel(),0,0,params['near'],params['far']]
        (directory/'camera.txt').write_text(' '.join(str(float(v)) for v in camera))
        job=directory/'job.txt';job.write_text(f'{w} {h} {frames} 2 32 0 1 0 "{provider.as_posix()}"\n'+'\n'.join(lines)+f'\n"{(directory/"out_diff.bin").as_posix()}"\n"{(directory/"out_spec.bin").as_posix()}"\n')
        jobs.append((variant,job))
        input_seals[variant]={str(p.relative_to(directory)):digest(p) for p in directory.iterdir() if p.is_file()}
    for name,_,_ in guide_files:need(input_seals['sdk-packed'][name]==input_seals['owned-reconstructed'][name],'guide bytes same across actual SDK histories '+name)
    need(input_seals['sdk-packed']['camera.txt']==input_seals['owned-reconstructed']['camera.txt'],'camera/bounds bytes identical')
    state={'schema':'fsrd.raw-prepass-sdk-control.v1','width':w,'height':h,'frames':frames,'executable':str(exe),'executable_sha256':digest(exe),'source_sha256':old['generated_runner_sha256'],'provider_path':str(provider),'provider_sha256':digest(provider),'source_input_manifest_sha256':digest(root/'manifest.json'),'source_native_comparison_sha256':digest(native_output/'prepass-comparison.json'),'input_sha256':input_seals,'configured_values_key_order':['disocclusion','normal','stability','maxRadiance','clipStd','gaussian'],'configured_values':[.1,.5,.5,40000,40,.5],'checkerboard':{'sdk-packed':{'flags':34,'diff_origin':'frame&1','spec_origin':'frame&1','padding':'full physical allocation right half RGB poison37/3/9, alpha positive'},'owned-reconstructed':{'flags':0,'diff_origin':0,'spec_origin':0}},'scope':'Two fresh histories; positive assigned toy hit parameters5/7. Same sparse traced inputs and all guides/settings, different declared input reconstruction. Synthetic texture-field diagnostic, not physical BSDF/native-title quality, NRD ground truth or production performance. No provider repeat-variance estimate.'}
    (output/'prepared.json').write_text(json.dumps(state,indent=2));return exe,jobs,state,references

def run_one(exe,variant,job):
    import psutil
    env=os.environ.copy();env.pop('FSRD_CB_PACKED',None)
    if variant=='sdk-packed':env['FSRD_CB_PACKED']='1'
    log=job.parent/'native.log';start=time.monotonic();peak=0
    with log.open('w') as stream:
        proc=subprocess.Popen([str(exe),str(job)],stdout=stream,stderr=subprocess.STDOUT,env=env,creationflags=subprocess.CREATE_NO_WINDOW);process=psutil.Process(proc.pid);process.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
        while proc.poll() is None:
            try:peak=max(peak,process.memory_info().rss)
            except psutil.NoSuchProcess:pass
            if peak>int(2.5*1024**3) or time.monotonic()-start>120:proc.kill();proc.wait();raise RuntimeError('SDK control cap, negative log preserved')
            time.sleep(.02)
        rc=proc.wait()
    text=log.read_text(errors='replace');print(text,end='');need(rc==0,'actual signed control exit0 '+variant)
    need('dispatches=32 validation_errors=0 validation_warnings=0 sdk_errors=0 sdk_warnings=0' in text,'strict actual D3D/SDK debug0/0 '+variant)
    return {'seconds':time.monotonic()-start,'peak_resident_bytes':peak,'dispatches':32,'log':str(log)}

def compare(output,state,references):
    w,h,n=state['width'],state['height'],state['frames'];rows={};arrays={}
    for variant in state['input_sha256']:
        rows[variant]={};arrays[variant]={}
        for lobe in ['spec','diff']:
            source=output/variant/f'out_{lobe}.bin';value=np.fromfile(source,'<f2').reshape(n,h,w,4).astype('f4');need(np.isfinite(value[...,:3]).all(),'actual SDK RGB finite '+variant+lobe);arrays[variant][lobe]=value[...,:3]
            selected=value[16:,8:-8,8:-8,:3].astype('f8');reference=references[lobe][None,8:-8,8:-8];error=selected-reference
            y=selected@np.array([.2126,.7152,.0722]);chroma=selected-y[...,None];ref_chroma=reference-(reference@np.array([.2126,.7152,.0722]))[...,None]
            rows[variant][lobe]={'toy_field_rmse':float(np.sqrt(np.mean(error**2))),'toy_field_chroma_rmse':float(np.sqrt(np.mean((chroma-ref_chroma)**2))),'mean_rgb':selected.mean((0,1,2)).tolist(),'stage_alpha_finite_fraction_diagnostic_only':float(np.isfinite(value[...,3]).mean()),'output_sha256':digest(source)}
    for lobe in ['spec','diff']:
        a=arrays['sdk-packed'][lobe][16:,8:-8,8:-8];b=arrays['owned-reconstructed'][lobe][16:,8:-8,8:-8]
        rows.setdefault('between_actual_SDK_outputs',{})[lobe]={'rgb_rmse':float(np.sqrt(np.mean((a-b).astype('f8')**2))),'mean_rgb_delta_owned_minus_packed':(b-a).mean((0,1,2)).astype(float).tolist()}
    need((output/'sdk-packed/dispatch_controls.bin').read_bytes()==(output/'owned-reconstructed/dispatch_controls.bin').read_bytes(),'all actual184B per-frame camera/reset/scale/control packets identical')
    need(digest(Path(state['executable']))==state['executable_sha256'] and digest(Path(state['provider_path']))==state['provider_sha256'],'executable/provider unchanged after both histories')
    return rows

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run',action='store_true');parser.add_argument('--native-output',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();exe,jobs,state,refs=prepare(args.native_output,args.output)
    if not args.run:print(json.dumps({'checks':CHECKS,'prepared_histories':2,'compiler_run':False,'gpu_run':False}));return
    results={variant:run_one(exe,variant,job) for variant,job in jobs};state.update(results=results,measurements=compare(args.output,state,refs),checks=CHECKS,provider_calls=64,context_create_destroy_balance='2 fresh process contexts/2 successful destroys',compiler_run=False)
    (args.output/'comparison.json').write_text(json.dumps(state,indent=2));print(json.dumps(state['measurements'],indent=2));print('PASS signed_checker_control_checks='+str(CHECKS)+' provider_calls=64')
if __name__=='__main__':main()
