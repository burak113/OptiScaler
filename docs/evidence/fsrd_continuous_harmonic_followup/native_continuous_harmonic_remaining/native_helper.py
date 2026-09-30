from pathlib import Path
from probe_fsrd_additive_split import DLL,write_texture,save_json
from native_resource_guard import run_guarded
import numpy as np
import re,json,hashlib,subprocess
def run_amd(folder, executable, packed, depth, camera=None, frame_controls=None):
    if folder.exists(): raise ValueError('Preserve existing native context folder')
    folder.mkdir(parents=True)
    n = len(packed)
    h, w = depth.shape
    arrays = [depth, np.stack([p[2] for p in packed]), np.stack([p[3] for p in packed]),
              np.stack([p[4] for p in packed]), np.stack([p[5] for p in packed]),
              np.stack([p[1] for p in packed]), np.stack([p[0] for p in packed])]
    formats = [41, 10, 24, 28, 28, 10, 10]
    camera_path = folder/'camera.txt'
    if camera is not None:
        camera_path.write_text(' '.join(map(str, camera))+'\n')
    elif camera_path.exists():
        camera_path.unlink()
    controls_path=folder/'frame_controls.txt'
    if frame_controls is not None:
        controls=np.asarray(frame_controls,float)
        if controls.shape!=(n,3) or not np.isfinite(controls).all() or not np.isin(controls[:,0],[0,1]).all():
            raise ValueError('Expected reset,jitterX,jitterY for each frame')
        controls_path.write_text(''.join(f'{int(r)} {x:.9g} {y:.9g}\n' for r,x,y in controls))
    elif controls_path.exists():
        controls_path.unlink()
    inputs = [folder/f'input{i}.bin' for i in range(7)]
    rows = [write_texture(p, a, fmt) for p, a, fmt in zip(inputs, arrays, formats)]
    save_json(folder/'amd_input_identity.json',
              {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs})
    od, ospec = folder/'diffuse.bin', folder/'specular.bin'
    # The same tuning, reset-on-first-frame, ray flags and DLL for every strength.
    job = folder/'job.txt'
    job.write_text('\n'.join([f'{w} {h} {n} 2 32 0 1 0 "{DLL.as_posix()}"'] + rows +
                             [f'"{od.as_posix()}" "{ospec.as_posix()}"'])+'\n', encoding='utf-8')
    guard = run_guarded([str(executable), str(job)], folder)
    if guard['status'] != 'completed':
        raise RuntimeError('Owned-child guard/native failure; preserved raw logs at '+str(folder))
    proc = subprocess.CompletedProcess([str(executable), str(job)], guard['returncode'],
        (folder/'stdout.log').read_text(encoding='utf-8',errors='replace'),
        (folder/'stderr.log').read_text(encoding='utf-8',errors='replace'))
    log = proc.stdout+proc.stderr
    (folder/'runner.log').write_text(log, encoding='utf-8')
    save_json(folder/'runner_process.json', dict(
        returncode=proc.returncode, returncode_hex=f'0x{proc.returncode & 0xffffffff:08x}',
        runner_sha256=hashlib.sha256(Path(executable).read_bytes()).hexdigest(),
        log_sha256=hashlib.sha256((folder/'runner.log').read_bytes()).hexdigest()))
    if proc.returncode:
        raise RuntimeError(f'Native AMD runner exited {proc.returncode} '
                           f'(0x{proc.returncode & 0xffffffff:08x}); log: {folder / "runner.log"}\n{log}')
    for field in ('validation_errors', 'validation_warnings', 'sdk_errors', 'sdk_warnings'):
        if not re.search(r'\b'+field+r'=0\b', log):
            raise RuntimeError(log)
    if 'debug_layer=1' not in log:
        raise RuntimeError('D3D12 debug layer unavailable')
    def read(path):
        if path.stat().st_size != n*h*w*8:
            raise RuntimeError(f'Truncated {path}')
        return np.fromfile(path, '<f2').reshape(n, h, w, 4).astype(np.float32)
    diff, spec = read(od), read(ospec)
    applied=folder/'dispatch_controls.bin'
    if not applied.exists() or applied.stat().st_size!=n*184:
        raise RuntimeError('Missing/truncated applied AMD dispatch controls')
    save_json(folder/'amd_context_identity.json',dict(
        inputs=json.loads((folder/'amd_input_identity.json').read_text()),
        applied_dispatch_sha256=hashlib.sha256(applied.read_bytes()).hexdigest(),
        dll_sha256=hashlib.sha256(DLL.read_bytes()).hexdigest(),
        runner_sha256=hashlib.sha256(Path(executable).read_bytes()).hexdigest(),
        controls_layout='184 bytes/frame, native Windows little endian: uint32 frame,flags,width,height; float32 motionScale[3],cameraDelta[3],jitter[2],depthBounds[2],view[16],projection[16]',
        dimensions=[w,h],frames=n,signals=[2,32],reset_every=0,tuning=1,passthrough=0,
        tuning_values=[.1,.5,.5,40000.,40.,.5],
        output_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (od,ospec)},
        exposure='No RR exposure field. Source radiance unchanged unless the fixture changes it.'))
    # Retain actual consumed input and output bytes for independent audit.
    return diff, spec, log
