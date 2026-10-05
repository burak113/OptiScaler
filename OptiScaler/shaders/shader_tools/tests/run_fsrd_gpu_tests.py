"""Execute production DXIL on the local D3D12 GPU with synthetic inputs.

python OptiScaler/shaders/shader_tools/tests/run_fsrd_gpu_tests.py
Requires MSVC, Windows SDK and numpy. Outputs live in tools_tmp/floor_rewrite/gpu_tests.
"""
from pathlib import Path
import atexit
import importlib.util
import hashlib
import json
import os
import re
import struct
import subprocess
import sys
import types
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fsrd_toolchain import compile_cpp
from fsrd_references import reference

ROOT = Path(__file__).resolve().parents[4]
PRE = ROOT / 'OptiScaler/shaders/fsrd_preprocess/precompile'
OUT = Path(os.environ.get('FSRD_GPU_TEST_OUTPUT', str(ROOT / 'tools_tmp/floor_rewrite/gpu_tests')))
OUT.mkdir(parents=True, exist_ok=True)
spec = importlib.util.spec_from_file_location('mirrors', ROOT/'OptiScaler/shaders/shader_tools/verify_fsrd_mirrors.py')
mirror = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mirror)
runner = OUT/'fsrd_gpu_runner.exe'
source = Path(__file__).with_name('fsrd_gpu_runner.cpp')

def build_runner():
    # compile_cpp reuses a build only for identical source, included files and toolchain;
    # an executable from another checkout cannot satisfy validation by its mtime.
    # A worker still running the old file would lock it, so stop that one first.
    _close_worker(runner)
    compile_cpp(source, runner, ('d3d12.lib', 'dxgi.lib'))


class _RunnerWorker:
    """One `fsrd_gpu_runner --server` per executable and test process.

    The runner keeps only its device, queue and compiled pipelines between jobs. Every
    job still creates, uploads and reads back its own resources, waits for the GPU and
    reports its own D3D12 validation counts, exactly as a separate process would.
    """
    def __init__(self, executable):
        self.log_path = OUT/f'gpu_worker_{os.getpid()}_{id(self)}.stderr.log'
        self.log = self.log_path.open('w', encoding='utf-8')
        self.process = subprocess.Popen([str(executable), '--server'], stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=self.log, text=True, bufsize=1)

    def run(self, job):
        start = self.log_path.stat().st_size
        lines, code = [], None
        try:
            self.process.stdin.write(str(job) + '\n')
            self.process.stdin.flush()
            for line in self.process.stdout:
                if line.startswith('job_complete='):
                    code = int(line.split('=', 1)[1])
                    break
                lines.append(line)
        except OSError:
            pass
        if code is None:
            code = self.process.wait() or 1
        self.log.flush()
        with self.log_path.open('r', encoding='utf-8', errors='replace') as stream:
            stream.seek(start)
            stderr = stream.read()
        return subprocess.CompletedProcess([str(job)], code, ''.join(lines), stderr)

    def close(self):
        try:
            self.process.stdin.close()
            self.process.wait(timeout=30)
        except Exception:
            self.process.kill()
        self.log.close()


_workers = {}

def _close_worker(executable):
    worker = _workers.pop(str(Path(executable).resolve()), None)
    if worker: worker.close()

@atexit.register
def _close_workers():
    for key in list(_workers):
        _close_worker(key)

def run_runner(job):
    # A suite that replaced this module's subprocess (fsrd_alpha_common.GPUWorker) or
    # FSRD_GPU_RUNNER_WORKER=0 keeps the original one-process-per-job execution.
    if os.environ.get('FSRD_GPU_RUNNER_WORKER', '1') == '0' or not isinstance(subprocess, types.ModuleType):
        return subprocess.run([str(runner), str(job)], capture_output=True, text=True)
    key = str(Path(runner).resolve())
    worker = _workers.get(key)
    if worker is None or worker.process.poll() is not None:
        if worker: _close_worker(key)
        worker = _workers[key] = _RunnerWorker(runner)
    result = worker.run(job)
    if result.returncode:
        # The server exits after a failed job; the next dispatch starts a fresh one.
        _close_worker(key)
    elif os.environ.get('FSRD_GPU_RUNNER_CROSSCHECK') == '1':
        # Proof mode for runner changes: the same job in a fresh process with freshly
        # created resources must write byte-identical outputs.
        outputs = sorted(Path(job).parent.glob('out*.bin'))
        pooled = [p.read_bytes() for p in outputs]
        fresh = subprocess.run([str(runner), str(job)], capture_output=True, text=True)
        if fresh.returncode or pooled != [p.read_bytes() for p in outputs]:
            raise AssertionError(f'worker and fresh-process outputs differ for {job}')
    return result

def constants(shader, values, directory=PRE):
    shader = 'FSRDInputConv' if shader == 'FSRDInputConvAdditive' else shader
    values = dict(values)
    if shader in ('FSRDInputConv', 'FSRDOutputComp') and directory == PRE:
        values.setdefault('SpecularAlbedoDemodulation', 1.0)
        values.setdefault('DiffuseAlbedoModulation', 1.0)
        values.setdefault('RecoveryMask', 1)
    # Exercise production defaults, not silently zero-initialized new controls.
    if shader == 'FSRDOutputComp' and directory == PRE:
        values.setdefault('FloorHandoverAnchorClamp', 4.0)
        values.setdefault('FloorHandoverCorrelationMix', 1.0)
        values.setdefault('LumaRecovery', 1.0)
        values.setdefault('ChromaRecovery', 1.0)
    text = (directory/(shader+'.hlsl')).read_text(encoding='utf-8')
    marker = {'FSRDFloorSeed':'CB_Median','FSRDFloor':'CB_Analysis','FSRDInputConv':'CB_Packing','FSRDOutputComp':'CB_Comp',
              'FSRDAlbedoTrustEvidence':'CB_AlbedoTrust','FSRDAlbedoTrustPropagate':'CB_AlbedoTrust'}[shader]
    body = mirror.brace_body(text,'cbuffer '+marker)
    fields, size = mirror.hlsl_cbuffer_fields(body, shader)
    assert not mirror.errors, mirror.errors
    # Pinned historical shaders may still have the retired user control. Give
    # those shaders their original default, never a silently zero-filled value.
    if Path(directory).resolve() != PRE.resolve() and any(f[0]=='NoiseSuppression' for f in fields):
        values.setdefault('NoiseSuppression', .75)
    blob = bytearray(size)
    for name, _, offset, length in fields:
        if name not in values: continue
        value = values[name]
        if np.isscalar(value): value = [value]
        ty = re.search(r'\b(\w+)\s+'+re.escape(name)+r'\s*;',body)[1]
        fmt = 'I' if ty.startswith('uint') else ('i' if ty.startswith('int') else 'f')
        data = struct.pack('<'+fmt*len(value), *value)
        assert len(data) == length,(name,length,len(data))
        blob[offset:offset+length] = data
    return blob

counter = 0
timings = []
def _dispatch(shader, values, inputs, output_formats, size, directory=PRE, repetitions=1):
    global counter
    schema = 'FSRDInputConv' if shader == 'FSRDInputConvAdditive' else shader
    w,h = size
    requested_outputs = len(output_formats)
    inputs = list(inputs)
    output_formats = list(output_formats)
    adaptive_conv = schema == 'FSRDInputConv' and 'InDemodMask' in (directory/(schema+'.hlsl')).read_text()
    adaptive_comp = shader == 'FSRDOutputComp' and 'InEffectiveSpecAlbedo' in (directory/(shader+'.hlsl')).read_text()
    if adaptive_conv:
        if len(inputs) == 17:
            inputs += [rgba(w,h,(0,0,0))]
        # Bind the complete production UAV table even for a prepass that only
        # writes u0. The scratch output is RGBA16F; the effective guide is UNORM8.
        production_outputs = [10,10,10,24,28,28,10,10,28]
        output_formats += production_outputs[len(output_formats):]
    # Unsupported-albedo recovery adds u8 to conversion. Callers written for the eight
    # original outputs still bind the complete production UAV table.
    direct_conv = schema == 'FSRDInputConv' and 'OutDirectSpecular' in (directory/(schema+'.hlsl')).read_text()
    if direct_conv and not adaptive_conv and len(output_formats) == 8:
        output_formats += [10]
    temporal_comp = shader == 'FSRDOutputComp' and 'InHistoryMetadata' in (directory/(shader+'.hlsl')).read_text()
    trust_comp = shader == 'FSRDOutputComp' and 'InAlbedoTrust' in (directory/(shader+'.hlsl')).read_text()
    if temporal_comp:
        if len(inputs) == 8:
            inputs += [rgba(w,h,(0,0,0)), rgba(w,h,(-1,-1,-1),-1),
                       np.zeros((h,w,4),np.uint32)]
        if len(output_formats) == 1:
            output_formats += [10,3]
    if trust_comp and len(inputs) == 11:
        # Recovery disabled by default: its three inputs are bound but never read.
        inputs += [rgba(w,h,(0,0,0)), rgba(w,h,(0,0,0)), np.zeros((h,w,2),np.float32)]
    multi_comp = shader == 'FSRDOutputComp' and 'InIndirectDiffuseDenoised' in (directory/(shader+'.hlsl')).read_text()
    if multi_comp and len(inputs) == 14:
        inputs += [rgba(w,h,(0,0,0))]
    # Recovery's per-lobe Skip accounting reads the main RR inputs. Zero inputs carry no
    # divisor-floor loss, which is the previous accounting exactly.
    loss_comp = shader == 'FSRDOutputComp' and 'InDirectDiffuseSignal' in (directory/(shader+'.hlsl')).read_text()
    if loss_comp and len(inputs) == 15:
        inputs += [rgba(w,h,(0,0,0)), rgba(w,h,(0,0,0))]
    if shader == 'FSRDAlbedoTrustEvidence' and len(inputs) == 8:
        inputs += [rgba(w,h,(0,0,0))]
    loss_evidence = shader == 'FSRDAlbedoTrustEvidence' and 'InDirectDiffuseSignal' in (directory/(shader+'.hlsl')).read_text()
    if loss_evidence and len(inputs) == 9:
        inputs += [rgba(w,h,(0,0,0)), rgba(w,h,(0,0,0))]
    if adaptive_comp and len(inputs) == 11:
        inputs += [rgba(w,h,(1,1,1))]
    if shader == 'FSRDOutputComp' and 'InRawSpecular' in (directory/(shader+'.hlsl')).read_text() and len(inputs) == 12:
        inputs += [inputs[0]]
    d=OUT/f'{counter:03}_{shader}';counter+=1;d.mkdir(exist_ok=True)
    cb=d/'cb.bin';cb.write_bytes(constants(shader,values,directory))
    records=[f'{json.dumps(str(directory/(shader+"_Shader.cso")))} {json.dumps(str(cb))} {w} {h} {len(inputs)} {len(output_formats)} {repetitions}']
    # Internal formats match the production resources. External title inputs use a
    # documented RGBA16_FLOAT/R32_FLOAT fixture (actual title formats may differ).
    formats = {
        'FSRDFloorSeed': [10,10,41,41,10],
        'FSRDFloor': [10,41,10,10],
        'FSRDInputConv': [10,41,10,10,41,41,10,10,41,10,10,10,10,10,41,41,10,10],
        'FSRDOutputComp': ([10,28,10,28,10,24,10,41,10,10,3,10,10,16,10] + ([10,10] if loss_comp else []) if trust_comp else
                           [10,28,10,28,10,24,10,41,10,10,3,28,10] if temporal_comp else
                          [10,28,10,28,10,24,10,41] if len(inputs)==8 else
                           [10,28,10,28,10,10,10,24,10]),
        'FSRDAlbedoTrustEvidence': [10,10,28,28,10,41,24,10,10] + ([10,10] if loss_evidence else []),
        'FSRDAlbedoTrustPropagate': [16,41,24],
    }[schema]
    for i,a in enumerate(inputs):
        a=np.asarray(a,dtype=np.uint32 if formats[i]==3 else np.float32)
        if a.ndim == 2: a=np.repeat(a[...,None],4,axis=2)
        if a.shape[2] < 4: a=np.pad(a,((0,0),(0,0),(0,4-a.shape[2])))
        fmt=formats[i]
        if fmt==10: stored=a.astype('<f2')
        elif fmt==3: stored=a.astype('<u4')
        elif fmt==41: stored=a[...,0].astype('<f4')
        elif fmt==16: stored=a[...,:2].astype('<f4')
        elif fmt==28: stored=np.rint(np.clip(a,0,1)*255).astype(np.uint8)
        elif fmt==24:
            u=np.rint(np.clip(a,0,1)*[1023,1023,1023,3]).astype(np.uint32)
            stored=u[...,0] | (u[...,1]<<10) | (u[...,2]<<20) | (u[...,3]<<30)
        else: raise ValueError(fmt)
        p=d/f'in{i}.bin';stored.tofile(p)
        records.append(f'{json.dumps(str(p))} {a.shape[1]} {a.shape[0]} {fmt}')
    for i,fmt in enumerate(output_formats):records.append(f'{json.dumps(str(d/f"out{i}.bin"))} {w} {h} {fmt}')
    job=d/'job.txt';job.write_text('\n'.join(records))
    result=run_runner(job)
    if result.returncode: raise RuntimeError(shader+'\n'+result.stdout+result.stderr)
    times=dict(re.findall(r'(\w+)=([\d.eE+-]+)',result.stdout))
    adapter=re.search(r'adapter=(.+)',result.stdout)
    if adapter: times['adapter']=adapter[1].strip()
    timings.append({'shader':shader,'size':size,'repetitions':repetitions,
                    'shader_sha256':hashlib.sha256((directory/(shader+'_Shader.cso')).read_bytes()).hexdigest(),
                    **times})
    result=[]
    for i,fmt in enumerate(output_formats):
        p=d/f'out{i}.bin'
        if fmt==10:a=np.fromfile(p,dtype='<f2').reshape(h,w,4).astype(np.float32)
        elif fmt==3:a=np.fromfile(p,dtype='<u4').reshape(h,w,4)
        elif fmt==2:a=np.fromfile(p,dtype='<f4').reshape(h,w,4)
        elif fmt==41:a=np.fromfile(p,dtype='<f4').reshape(h,w)
        elif fmt==16:a=np.fromfile(p,dtype='<f4').reshape(h,w,2)
        elif fmt==28:a=np.fromfile(p,dtype=np.uint8).reshape(h,w,4).astype(np.float32)/255
        elif fmt==24:
            packed=np.fromfile(p,dtype='<u4').reshape(h,w)
            a=np.stack([(packed&1023)/1023,((packed>>10)&1023)/1023,((packed>>20)&1023)/1023,((packed>>30)&3)/3],axis=2).astype(np.float32)
        else:raise ValueError(fmt)
        if i < requested_outputs:
            assert np.all(np.isfinite(a)), f'{shader} produced NaN/Inf'
        result.append(a)
    # Raw staging data is reproducible, and HDR inputs can be hundreds of MB per
    # job. Keep the result metrics rather than accumulating every upload/readback.
    for staging in d.glob('*.bin'):
        staging.unlink()
    return result[:requested_outputs]

def dispatch(shader, values, inputs, output_formats, size, directory=PRE, repetitions=1):
    result = _dispatch(shader, values, inputs, output_formats, size, directory, repetitions)
    # Opt-in lossless optimization gate. Re-run the exact inputs/constants with
    # frozen pre-change production DXIL; never approximate the shader in Python.
    baseline = os.environ.get('FSRD_LOSSLESS_BASELINE')
    if baseline and Path(directory).resolve() == PRE.resolve():
        baseline = Path(baseline).resolve()
        if baseline == PRE.resolve():
            raise ValueError('Lossless baseline must be a separate frozen directory')
        cb = dict(values)
        # constants() supplies these defaults only to the current directory.
        # A lossless A/B must serialize the same effective controls to the frozen
        # shader too; zero-filled baseline controls compare different algorithms.
        if shader in ('FSRDInputConv', 'FSRDOutputComp'):
            cb.setdefault('SpecularAlbedoDemodulation', 1.0)
            cb.setdefault('DiffuseAlbedoModulation', 1.0)
            cb.setdefault('RecoveryMask', 1)
        if shader == 'FSRDOutputComp':
            cb.setdefault('FloorHandoverAnchorClamp', 4.0)
            cb.setdefault('FloorHandoverCorrelationMix', 1.0)
            cb.setdefault('LumaRecovery', 1.0)
            cb.setdefault('ChromaRecovery', 1.0)
        old = _dispatch(shader, cb, inputs, output_formats, size, baseline, 1)
        differences = []
        for i, (a, b) in enumerate(zip(old, result)):
            changed = a != b
            if np.any(changed):
                differences.append(dict(output=i, changed=int(np.count_nonzero(changed)),
                                        maximum=float(np.abs(a-b)[changed].max())))
        check(f'lossless {shader} dispatch {counter} {size}', not differences,
              differences=differences)
        if differences:
            raise AssertionError(f'{shader} changed stored output: {differences}')
    return result

def rgba(w,h,rgb,alpha=0):
    a=np.zeros((h,w,4),np.float32);a[...,:3]=rgb;a[...,3]=alpha;return a

def seed(color, depth=None, normal=None, albedo=None, enabled=True, base=(0,0), logical=None):
    h,w=color.shape[:2];lw,lh=logical or (w,h)
    depth=depth if depth is not None else np.ones((h,w),np.float32)*10
    normal=normal if normal is not None else rgba(w,h,(0,0,1))
    albedo=albedo if albedo is not None else rgba(w,h,(.5,.5,.5))
    values={'InvProjMatrix':np.eye(4).ravel(),'RenderSize':[lw,lh,1/lw,1/lh], 'NearPlane':.1,'FarPlane':1000,
        'Flags':1,'InputBase':[*base,*base],'NormalBase':base,'AlbedoBase':base,'FloorEnabled':int(enabled)}
    return dispatch('FSRDFloorSeed',values,[color,normal,depth,depth,albedo],[10,41,10,10],(lw,lh))

def filter_floor(floor,depth,guide,albedo):
    h,w=floor.shape[:2]
    for step in (1,2,4,8,16):
        floor=dispatch('FSRDFloor',{'DstTexSize':[w,h,1/w,1/h],'StepSize':step},[floor,depth,guide,albedo],[10],(w,h))[0]
    return floor

def compose(rr,reference,depth,normal,albedo,detail=1.0,anchor=4,mix=1):
    h,w=rr.shape[:2];zero=np.zeros_like(rr)
    return dispatch('FSRDOutputComp',{'DstTexSize':[w,h,1/w,1/h],'DetailPreservation':detail,'FloorHandoverAnchorClamp':anchor,'FloorHandoverCorrelationMix':mix},
        [zero,zero,rr,rgba(w,h,(1,1,1)),zero,normal,reference,depth],[10],(w,h))[0]

checks=[]
# Measurements worth recording without a pass/fail: documented consequences of a design
# choice, which the packaging script and the handoff report carry forward.
records=[]

def skip(name):
    records.append({'status': 'skipped', 'name': name})
    print('SKIP '+name, flush=True)
def check(name, condition, **metrics):
    checks.append({'name':name,'passed':bool(condition),**metrics})
    print(('PASS' if condition else 'FAIL')+' '+name+' '+str(metrics),flush=True)

def run():
    build_runner()
    w,h=17,13
    for label,level in [('black',0),('dim',1e-5),('constant',.2),('hdr',12000)]:
        c=rgba(w,h,(level,level,level))
        f,z,g,r=seed(c)
        error=float(np.max(np.abs(r[...,:3]-c[...,:3])))
        check(label+' reference DC',error<=max(1e-7,level*.002),error=error)
        filtered=filter_floor(f,z,g,rgba(w,h,(.5,.5,.5)))
        check(label+' floor DC',np.max(np.abs(filtered[...,:3]-c[...,:3]))<=max(1e-7,level*.002))
    for axis in ('vertical','horizontal','diagonal'):
        c=rgba(w,h,(.02,.02,.02))
        if axis=='vertical':c[:,w//2,:3]=1
        elif axis=='horizontal':c[h//2,:,:3]=1
        else:
            for y in range(h):c[y,min(y+2,w-1),:3]=1
        r=seed(c)[3]
        crop=(slice(2,-2),slice(2,-2),slice(0,3))
        error=float(np.max(np.abs(r[crop]-c[crop])))
        check(axis+' 1px reference',error<=.05,error=error)
    for label,impulse in [('white',(100,100,100)),('red',(100,0,0))]:
        c=rgba(w,h,(.2,.2,.2));c[h//2,w//2,:3]=impulse
        r=seed(c)[3];error=float(np.max(np.abs(r[h//2,w//2,:3]-.2)))
        check(label+' firefly removed',error<.01,error=error)
    c=rgba(w,h,(.2,.2,.2));c[h//2:h//2+2,w//2:w//2+2,:3]=100
    r=seed(c)[3];check('2x2 firefly cluster removed',np.max(r[...,:3])<1,maximum=float(np.max(r[...,:3])))
    c=rgba(w,h,(.2,.2,.2));c[:,w//2:,:3]=5
    z=np.ones((h,w),np.float32)*10;z[:,w//2:]=20
    r=seed(c,depth=z)[3];check('depth boundary no bleed',np.max(np.abs(r[...,:3]-c[...,:3]))<.01)
    a=rgba(w,h,(.1,.1,.1));a[:,w//2:,:3]=.8
    r=seed(c,albedo=a)[3];check('material boundary no bleed',np.max(np.abs(r[...,:3]-c[...,:3]))<.01)
    n=rgba(w,h,(0,0,1));n[:,w//2:,:3]=(1,0,0)
    f,z,g,r=seed(c,normal=n)
    filtered=filter_floor(f,z,g,rgba(w,h,(.5,.5,.5)))
    check('normal boundary no bleed through five passes',np.max(np.abs(filtered[...,:3]-c[...,:3]))<.01)
    slope=10+np.indices((h,w),dtype=np.float32)[1]*.25
    f,z,g,r=seed(rgba(w,h,(.4,.4,.4)),depth=slope)
    check('sloping plane depth and gradient',np.max(np.abs(z-slope))<1e-5 and
          np.max(np.abs(g[2:-2,2:-2,0]-.25))<.001 and np.max(np.abs(g[...,1]))<.001)
    for size in [(1,1),(1,9),(9,1),(7,5)]:
        tw,th=size
        f,z,g,r=seed(rgba(tw,th,(.25,.25,.25)))
        f=filter_floor(f,z,g,rgba(tw,th,(.5,.5,.5)))
        # Clamped copies of the same texel cannot prove independent support.
        # Degenerate extents may reduce Floor; the remainder belongs to RR.
        check(f'tiny/partial groups {size}',np.all(f[...,:3]>=0) and
              np.max(f[...,:3])<=.251 and np.max(np.abs(r[...,:3]-.25))<.001 and
              (size!=(1,1) or (np.all(f[...,:3]==0) and r[0,0,3]<0)))
    c=rgba(w+6,h+6,(8,1,4));c[3:3+h,3:3+w,:3]=.2
    r=seed(c,base=(3,3),logical=(w,h))[3];check('nonzero subrect',np.max(np.abs(r[...,:3]-.2))<.001)
    f,z,g,r=seed(rgba(w,h,(1,1,1)),enabled=False)
    check('disabled retains depth only',np.all(f==0) and np.all(r==0) and np.all(z==10))
    c=rgba(w,h,(.2,.2,.2));c[2,2,:3]=[np.nan,np.inf,-np.inf]
    seed(c);check('invalid radiance remains finite',True)
    rng=np.random.default_rng(771)
    c=rgba(65,49,(1,1,1));c[...,:3]+=rng.normal(0,.12,c[...,:3].shape)
    f,z,g,r=seed(c);f=filter_floor(f,z,g,rgba(65,49,(.5,.5,.5)))
    before=float(np.std(c[4:-4,4:-4,:3]));after=float(np.std(f[4:-4,4:-4,:3]))
    check('flat field spatial noise reduced',after<before*.75,input_std=before,floor_std=after)
    # Composition must preserve RR exactly when detail is disabled, unsupported, or bypassed.
    rr=rgba(w,h,(.3,.4,.5));ref=rgba(w,h,(.6,.1,.9),1)
    n=rgba(w,h,(.5,.5,.5),1/3);z=np.ones((h,w),np.float32)*10;a=rgba(w,h,(.5,.5,.5))
    for label,detail,sigma in [('detail off',0,0),('noisy reference',.35,100),('routed reference',.35,-1)]:
        ref[...,3]=sigma
        out=compose(rr,ref,z,n,a,detail)
        check(label+' leaves RR unchanged',np.max(np.abs(out[...,:3]-rr[...,:3]))<.001)
    for axis in ('horizontal','vertical','diagonal'):
        sharp=rgba(w,h,(.1,.1,.1))
        if axis=='horizontal':sharp[h//2,:,:3]=1
        elif axis=='vertical':sharp[:,w//2,:3]=1
        else:
            for y in range(h):sharp[y,min(y+2,w-1),:3]=1
        out=compose(sharp,seed(sharp)[3],z,n,a)
        error=float(np.max(np.abs(out[2:-2,2:-2,:3]-sharp[2:-2,2:-2,:3])))
        check(axis+' sharp RR not amplified',error<.045,error=error)
    for sigma in (0,10):
        ref=rgba(w,h,(.1,.1,.1),sigma);ref[:,w//2,:3]=1
        # This is a selected-screen fixture. Disable Anchor here to isolate
        # the uncertainty gate, rather than demand a line outside
        # the constant RR anchor's intentionally zero-width interval.
        out=compose(rgba(w,h,(.1,.1,.1)),ref,z,n,a,anchor=0,mix=0)
        center=float(out[h//2,w//2,0]);minimum=float(np.min(out[...,:3]))
        check(f'detail correction supported only sigma={sigma}',
              (center>.15 if sigma==0 else abs(center-.1)<.001) and minimum>=.099,
              center=center,minimum=minimum)
    # Real packing shader with an identity RR checks the full split, including crossing.
    for enabled in (False,True):
        for bias in (0,.5,1):
            c=rgba(w,h,(.15,.35,.7));c[:,w//2:,:3]*=2
            floor=rgba(w,h,(.2,.3,.9));reference=rgba(w,h,(.2,.3,.9),.1)
            normal=rgba(w,h,(0,0,1));rough=np.ones((h,w),np.float32)*.5
            spec=rgba(w,h,(.1,.1,.1));diff=rgba(w,h,(.5,.5,.5));zero=rgba(w,h,(0,0,0))
            vals={'InvViewMatrix':np.eye(4).ravel(),'InvProjMatrix':np.eye(4).ravel(),'PrevViewMatrix':np.eye(4).ravel(),
                'DstTexSize':[w,h,1/w,1/h],'MotionInputSize':[w,h,1/w,1/h],'MotionTransform':[1,1,0,0],
                'NearPlane':.1,'FarPlane':1000,'FloorDetailPreservation':.35,
                'Flags':(1<<1)|(1<<15)|((1<<7) if enabled else 0),'DemodDivisorFloor':.008,'BiasMaskStrength':1}
            packed=dispatch('FSRDInputConv',vals,[c,z,zero,normal,rough,z,diff,spec,rgba(w,h,(bias,bias,bias)),floor,zero,zero,zero,zero,z,zero,reference],
                [10,10,10,24,28,28,10,10],(w,h))
            out=dispatch('FSRDOutputComp',{'DstTexSize':[w,h,1/w,1/h],'DetailPreservation':0},
                [packed[0],packed[4],packed[1],packed[5],packed[6],packed[3],packed[7],z],[10],(w,h))[0]
            expected=c[...,:3]+(1-bias)*np.maximum((floor[...,:3] if enabled else 0)-c[...,:3],0)
            error=float(np.max(np.abs(expected-out[...,:3])))
            check(f'identity closure floor={enabled} bias={bias}',error<.003,error=error)
            if bias>0:check(f'bias={bias} blocks detail',np.all(packed[7][...,3]<0))
    # Dark/invalid albedo must follow the same split; it must not grant raw bypass
    # or detail permission by itself. The unrepresentable residual remains in skip.
    for value in (0,.001,np.nan):
        diff=rgba(w,h,(value,value,value));spec=diff.copy()
        vals['Flags']=(1<<1)|(1<<7);vals['FloorDetailPreservation']=.35
        packed=dispatch('FSRDInputConv',vals,
            [c,z,zero,normal,rough,z,diff,spec,zero,floor,zero,zero,zero,zero,z,zero,reference],
            [10,10,10,24,28,28,10,10],(w,h))
        out=dispatch('FSRDOutputComp',{'DstTexSize':[w,h,1/w,1/h],'DetailPreservation':0},
            [packed[0],packed[4],packed[1],packed[5],packed[6],packed[3],packed[7],z],[10],(w,h))[0]
        expected=np.maximum(c[...,:3],floor[...,:3])
        check(f'dark/invalid albedo closure {value}',np.max(np.abs(expected-out[...,:3]))<.003)
    report={'checks':checks,'dispatches':timings,'production_shader_tests':True}
    (OUT/'results.json').write_text(json.dumps(report,indent=2))
    assert all(c['passed'] for c in checks), 'GPU regression failures; see results.json'
    print(f'{len(checks)} checks passed; {len(timings)} production shader dispatches')

if __name__=='__main__':run()
