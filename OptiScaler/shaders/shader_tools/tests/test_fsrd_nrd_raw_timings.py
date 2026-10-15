"""Required warm actual helper GPU timestamps and original A regression.
No provider/native NRD/FrameRate quality claim. Explicit lead heavy grant for --run.
"""
from pathlib import Path
import argparse,csv,json,os,re,subprocess,time
import numpy as np
import test_fsrd_nrd_raw_native as base
HERE=Path(__file__).resolve().parent;TASK=base.TASK;CHECKS=0

def need(value,name):
    global CHECKS
    CHECKS+=1
    if not value:raise AssertionError(name)

def prepare(output):
    inputs,manifest=base.prepare(output)
    raw=(output/'production_nrd_raw.cpp').read_text();need(raw.count('ResTrack_Dx12::RetainComputeDispatch(')==1,'one exact new callback Retain seam')
    (output/'production_nrd_raw.cpp').write_text(raw.replace('ResTrack_Dx12::RetainComputeDispatch(','RawPrePassRetainComputeDispatch('))
    a=(HERE/'nrd_raw_signal_fixture.cpp').read_text();at=a.index('#undef main');need(a[at:].count('int main(int argc,char** argv)')==1,'original A main body retained after its inner undef')
    (output/'raw_a_fixture_support.cpp').write_text(a[:at]+a[at:].replace('int main(int argc,char** argv)','int RawAStandaloneMain(int argc,char** argv)'))
    b=(HERE/'nrd_raw_prepass_fixture.cpp').read_text();need(b.count('int main(int argc,char** argv)')==1,'B main renamed only in generated support copy')
    (output/'raw_b_fixture_support.cpp').write_text(b.replace('int main(int argc,char** argv)','int RawBStandaloneMain(int argc,char** argv)'))
    timing=output/'timing';timing.mkdir(exist_ok=True)
    for w,h in [(1505,847),(2560,1440)]:
        params=base.legacy.frame(w,h,0);params.update(jitter=(0,0),previous_jitter=(0,0),native_material_guides=True,preserve_native_material_ids=True)
        base.legacy.write_case(timing/f'{w}x{h}',{},params)
    return inputs,manifest,timing

def build(output):
    shader=output/'consumer.cso';subprocess.run([str(base.dxc()),'-T','cs_6_2','-E','CSMain','-O3','-force-rootsig-ver','rootsig_1_0',str(HERE/'nrd_bridge_consumer_fixture.hlsl'),'-Fo',str(shader)],check=True)
    (output/'consumer_shader.h').write_text('const unsigned char ConsumerShaderBytes[] = {'+','.join(str(b) for b in shader.read_bytes())+'};\n')
    exe=output/'nrd_raw_timing_fixture.exe';base.compile_cpp(HERE/'nrd_raw_timing_fixture.cpp',exe,('d3d12.lib','dxgi.lib'),(output,HERE,base.PASS,base.ROOT/'OptiScaler',base.ROOT/'OptiScaler/include',base.ROOT/'external/streamline'));return exe

def run(exe,args,log,marker):
    import psutil
    start=time.monotonic();peak=0
    with log.open('w') as stream:
        proc=subprocess.Popen([str(exe),*map(str,args)],stdout=stream,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW);measured=psutil.Process(proc.pid);measured.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
        while proc.poll() is None:
            try:peak=max(peak,measured.memory_info().rss)
            except psutil.NoSuchProcess:pass
            if peak>int(2.5*1024**3) or time.monotonic()-start>300:proc.kill();proc.wait();raise RuntimeError('timing/regression cap, negative log retained')
            time.sleep(.02)
        code=proc.wait()
    text=log.read_text(errors='replace');print(text,end='');need(code==0,'actual native exit0 '+marker);need('debug_errors=0 debug_warnings=0' in text,'strict native debug0/0 '+marker)
    match=re.search(marker+r'=(\d+)',text);need(match is not None,'actual terminal marker '+marker)
    return {'native_checks':int(match[1]),'seconds':time.monotonic()-start,'peak_resident_bytes':peak,'log':str(log)}

def compare(timing):
    rows=list(csv.DictReader((timing/'raw-timestamps.csv').open()));need(len(rows)==54,'2 resolutions x3 profiles x9 actual measured samples')
    summary=[]
    for w,h in [(1505,847),(2560,1440)]:
        for profile in ['A','B-full','B-checker']:
            selected=[r for r in rows if int(r['width'])==w and int(r['height'])==h and r['profile']==profile];need(len(selected)==9,'exact nine warm samples per scope')
            need([int(r['sample']) for r in selected]==list(range(9)),'no sample selection or omission')
            samples={name:[float(r[name]) for r in selected] for name in ['capture_ms','geometry_ms','decode_ms']}
            need(all(np.isfinite(v) and v>=0 for values in samples.values() for v in values),'finite nonnegative actual GPU durations')
            total=np.array(samples['capture_ms'])+samples['geometry_ms']+samples['decode_ms']
            need(len({r['owned_bytes'] for r in selected})==len({r['owned_slots'] for r in selected})==1,'owned capture pool stable for all timed samples')
            summary.append({'width':w,'height':h,'profile':profile,'samples_ms':samples,'median_ms':{k:float(np.median(v)) for k,v in samples.items()},'total_median_ms':float(np.median(total)),'total_samples_ms':total.tolist(),'capture_helper_owned_allocation_bytes':int(selected[0]['owned_bytes']),'capture_helper_slots':int(selected[0]['owned_slots'])})
    return summary

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run',action='store_true');parser.add_argument('--output',type=Path,default=Path(os.environ.get('FSRD_GPU_TEST_OUTPUT',TASK/'tests/raw-timing')));args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True);inputs,manifest,timing=prepare(args.output)
    if not args.run:print(json.dumps({'checks':CHECKS,'legacy_adapter_checks':base.CHECKS,'resolutions':2,'profiles':3,'warmups':2,'samples':9,'compiler_run':False,'gpu_run':False}));return
    exe=build(args.output);a=run(exe,['--a-regression',inputs],args.output/'a-regression.native.log','PASS raw_native_checks');a['cases']=base.compare(inputs,manifest);a['python_checks']=base.CHECKS;a['independent_material_interval_checks']=base.legacy.CHECKS
    times=run(exe,[timing],args.output/'timing.native.log','PASS raw_timing_checks');summary=compare(timing)
    result={'schema':'fsrd.raw-required-timing.v1','a_regression':a,'timing':times,'measurements':summary,'checks':CHECKS,'executable_sha256':base.digest(exe),'provider_calls':0,'native_nrd_calls':0,'protocol':{'gpu_based_validation':False,'debug_layer':True,'warmups':2,'measured_samples':9,'bindings':'direct-root CB6, native encoding RGB, zero origin; A, B mode2/2, B checker0/1','geometry':'actual new owned geometry variant with native material+raw-roughness guides ON','capture_scope':'whole actual Capture including B owned4Bstatus copy/barriers','decode_scope':'whole actual Decode including native GPUflag capture and owned barriers','excluded':'CPU recording/allocation time, motion-finalize, RR provider, final Commit, title filtering/restoration, game FPS','owned_bytes_scope':'raw helper total cached A+B pool at that point; per-slot B adds64KiB mandatory status READBACK'},'sources':{str(p):base.digest(p) for p in [Path(__file__),HERE/'nrd_raw_timing_fixture.cpp',base.PASS/'FSRDNrdRawSignals_Dx12.cpp',base.PASS/'FSRDNrdBridgePass_Dx12.cpp']}}
    (args.output/'comparison.json').write_text(json.dumps(result,indent=2));print(json.dumps(summary,indent=2));print('PASS raw_timing_python_checks='+str(CHECKS))
if __name__=='__main__':main()
