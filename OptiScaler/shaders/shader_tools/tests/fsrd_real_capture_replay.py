"""Replay live-game ROI sequences through production Floor, signed AMD RR and Bleed.

The capture's ROI is explicit: this tool never calls a crop a full-frame replay.
It retains one native RR context and every frame's matrices, jitter, camera delta,
depth bounds and motion scale. No synthetic RR or repeated single-frame inputs
are used. An optional --reset-frame is an injected reset probe, not a captured
camera cut. Metrics use the late raw temporal mean as a stationary-scene proxy;
they are not ground-truth disocclusion or texture-quality gates.

Set TEMP/TMP and FSRD_CPP_CACHE to a drive with free space. Example:
  python fsrd_real_capture_replay.py --capture TRACE/UUID --shader-dir SNAPSHOT
      --output E:/FSRD/run --cases 0:0 0:1 1:0 1:1 --frames 128
  python fsrd_real_capture_replay.py --inventory TRACE --output E:/FSRD/inventory

reserve_data is excluded before traversal and rejected even as an explicit path.
"""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import os
import re
import struct
import subprocess
import sys
import time

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(HERE.parent))
from fsrd_toolchain import compile_cpp
import fsrd_floor_rr_replay as native

spec = importlib.util.spec_from_file_location('capture_mirrors', HERE.parent / 'verify_fsrd_mirrors.py')
mirror = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mirror)
MARKERS = dict(FSRDFloorSeed='CB_Median', FSRDFloor='CB_Analysis', FSRDInputConv='CB_Packing',
               FSRDOutputComp='CB_Comp', FSRDAlbedoTrustEvidence='CB_AlbedoTrust',
               FSRDAlbedoTrustPropagate='CB_AlbedoTrust')


def safe_path(value):
    path = Path(value).resolve()
    if any(part.lower() == 'reserve_data' for part in path.parts):
        raise ValueError('reserve_data holdout must not be accessed')
    return path


def digest(path):
    return native._sha256(path)


def camera_crop(extent, roi):
    fw, fh = extent
    w, h = roi['extent']; x, y = roi['origin']
    crop = np.eye(4, dtype=np.float64)
    crop[0, 0], crop[1, 1] = w / fw, h / fh
    crop[0, 3], crop[1, 3] = (2*x+w) / fw - 1, 1 - (2*y+h) / fh
    return crop


def inspect_capture(path, payload=False, limit=None):
    path = safe_path(path)
    manifest = json.loads((path / 'capture.json').read_text(encoding='utf-8'))
    if manifest.get('source') != 'live_game_gpu':
        raise ValueError('a live_game_gpu capture is required')
    frames = manifest['frames'][:limit]
    if not frames or [f['ordinal'] for f in frames] != list(range(len(frames))):
        raise ValueError('capture must publish a nonempty contiguous ordinal prefix')
    if any(not f.get('gpu_submission_verified') or not f.get('gpu_completed') for f in frames):
        raise ValueError('capture frame lacks verified GPU submission/completion')
    if any(f['context_id']!=frames[0]['context_id'] for f in frames) or any(
            b['native_frame_index']!=a['native_frame_index']+1 for a,b in zip(frames,frames[1:])):
        raise ValueError('capture context/native frame history is not contiguous')
    extent, roi = manifest['render_extent'], manifest['roi']
    if roi.get('space') != 'render_pixels_fixed':
        raise ValueError('unsupported capture ROI space')
    w, h = roi['extent']; x, y = roi['origin']
    if not (0 <= x and 0 <= y and 0 < w <= extent[0]-x and 0 < h <= extent[1]-y):
        raise ValueError('ROI lies outside render extent')
    controls = [f['controls'] for f in frames]
    views = np.asarray([c['view'] for c in controls], np.float32).reshape(-1, 4, 4)
    row = dict(capture=str(path), capture_uuid=manifest['capture_uuid'], schema=manifest['schema'],
               complete=manifest['complete'], frames=len(frames), render_extent=extent, roi=roi,
               full_frame=(roi['extent'] == extent and roi['origin'] == [0, 0]),
               original_reset_frames=[i for i, f in enumerate(frames) if f['reset']],
               elapsed_capture_seconds=(frames[-1]['recording_qpc']-frames[0]['recording_qpc']) / manifest['qpc_frequency'],
               maximum_camera_delta=float(np.max(np.abs([c['camera_delta'] for c in controls]))),
               maximum_rotation_change=float(np.max(np.abs(views[:, :3]-views[0, :3]))),
               settings=frames[0]['settings'], capture_manifest_sha256=digest(path / 'capture.json'),
               limitation='Fixed ROI; missing off-ROI history and neighbours. A reset at replay frame 0 starts fresh history.')
    if not payload:
        return row
    arrays = {}
    authenticated=[]
    layouts = dict(raw_color=('<f2', 4), raw_normals=('<f2', 4), raw_motion=('<f2', 4),
                   raw_depth=('<f4', 1), raw_specular_hit_distance=('<f4', 1),
                   raw_diffuse_albedo=('u1', 4), raw_specular_albedo=('u1', 4), raw_bias_mask=('u1', 1),
                   native_full1=('<f2', 4))
    for name, (dtype, channels) in layouts.items():
        shape = (h, w, channels) if channels != 1 else (h, w)
        data=[]
        for f in frames:
            descriptions={e['name']:e for e in f['images']+f.get('diagnostics',[]) if e.get('file')}
            info=descriptions.get(name)
            if info is None:raise ValueError(f'capture frame {f["ordinal"]} lacks provenance for {name}')
            file=safe_path(path/info['file'])
            if not file.is_relative_to(path):raise ValueError('capture payload escapes capture directory')
            blob=file.read_bytes()
            if len(blob)!=info['bytes'] or hashlib.sha256(blob).hexdigest()!=info['sha256']:
                raise ValueError('capture payload hash/size mismatch: '+str(file))
            data.append(np.frombuffer(blob,dtype).reshape(shape))
            authenticated.append(dict(file=info['file'],sha256=info['sha256']))
        arrays[name]=np.stack(data)
    for f in frames:
        for key in ('conversion_constants','floor_seed_constants'):
            info=f[key];file=safe_path(path/info['file'])
            if not file.is_relative_to(path):raise ValueError('capture constants escape capture directory')
            if file.stat().st_size!=info['bytes'] or digest(file)!=info['sha256']:
                raise ValueError('capture constant hash/size mismatch: '+str(file))
            authenticated.append(dict(file=info['file'],sha256=info['sha256']))
    arrays['frame_metadata'] = frames
    arrays['extent'], arrays['roi'] = extent, roi
    arrays['capture'] = path
    row['payload_unique_raw_frames'] = len({hashlib.sha256(a.tobytes()).hexdigest() for a in arrays['raw_color']})
    row['input_mode'] = 'genuine_captured_sequence'
    row['authenticated_payload_files']=authenticated
    return row, arrays


class Constants:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.cache = {}

    def fields(self, shader):
        if shader not in self.cache:
            source = (self.directory / (shader+'.hlsl')).read_text(encoding='utf-8')
            body = mirror.brace_body(source, 'cbuffer '+MARKERS[shader])
            fields, size = mirror.hlsl_cbuffer_fields(body, shader)
            if mirror.errors:
                raise ValueError(mirror.errors)
            result = []
            for name, _, offset, length in fields:
                kind = re.search(r'\b(\w+)\s+'+re.escape(name)+r'\s*;', body)[1]
                fmt = 'I' if kind.startswith('uint') else 'i' if kind.startswith('int') else 'f'
                result.append((name, offset, length, fmt))
            self.cache[shader] = result, size
        return self.cache[shader]

    def unpack(self, shader, blob):
        fields, size = self.fields(shader)
        if len(blob) < size:
            raise ValueError(f'captured {shader} constants {len(blob)} bytes smaller than ABI {size}')
        return {name: list(struct.unpack_from('<'+fmt*(length//4), blob, offset))
                for name, offset, length, fmt in fields}

    def pack(self, shader, values):
        fields, size = self.fields(shader)
        blob = bytearray(size)
        for name, offset, length, fmt in fields:
            if name not in values:
                continue
            value = values[name]
            value = [value] if np.isscalar(value) else np.asarray(value).ravel().tolist()
            if len(value)*4 != length:
                raise ValueError(f'constant {name} byte count mismatch')
            struct.pack_into('<'+fmt*len(value), blob, offset, *value)
        return blob


class Gpu:
    def __init__(self, work, shaders, executable):
        self.work = safe_path(work)
        self.work.mkdir(parents=True, exist_ok=True)
        self.shaders, self.executable = Path(shaders), Path(executable)
        self.constants, self.records = Constants(shaders), []
        self.stderr = (self.work/'gpu_stderr.log').open('w', encoding='utf-8')
        self.worker = subprocess.Popen([str(executable), '--server'], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=self.stderr, text=True, bufsize=1)

    def dispatch(self, shader, values, inputs, outputs, size, schema=None):
        w, h = size
        cb = self.work/'constants.bin'
        cb.write_bytes(self.constants.pack(schema or shader, values))
        lines = [f'"{(self.shaders/(shader+"_Shader.cso")).as_posix()}" "{cb.as_posix()}" '
                 f'{w} {h} {len(inputs)} {len(outputs)} 1']
        types = {10: ('<f2', 4), 41: ('<f4', 1), 28: ('u1', 4), 24: ('<u4', 1),
                 34: ('<f2', 2), 16: ('<f4', 2), 61: ('u1', 1), 3: ('<u4', 4)}
        for index, (value, fmt) in enumerate(inputs):
            array = np.asarray(value)
            dtype, channels = types[fmt]
            expected = (h, w) + (() if channels == 1 else (channels,))
            if array.shape != expected:
                raise ValueError(f'{shader} input {index} shape {array.shape} expected {expected}')
            path = self.work/f'in{index}.bin'
            np.ascontiguousarray(array, dtype=dtype).tofile(path)
            lines.append(f'"{path.as_posix()}" {w} {h} {fmt}')
        for index, fmt in enumerate(outputs):
            lines.append(f'"{(self.work / ("out"+str(index)+".bin")).as_posix()}" {w} {h} {fmt}')
        job = self.work/'job.txt'
        job.write_text('\n'.join(lines)+'\n', encoding='utf-8')
        started = time.monotonic()
        self.worker.stdin.write(str(job)+'\n'); self.worker.stdin.flush()
        log = []
        for line in self.worker.stdout:
            if line.startswith('job_complete='):
                code = int(line.split('=', 1)[1]); break
            log.append(line)
        else:
            raise RuntimeError('GPU worker exited; inspect '+str(self.work/'gpu_stderr.log'))
        log = ''.join(log)
        if code or not re.search(r'validation_errors=0 validation_warnings=0\b', log):
            raise RuntimeError(f'{shader} GPU job failed\n{log}')
        self.records.append(dict(shader=shader, shader_sha256=digest(self.shaders/(shader+'_Shader.cso')),
                                 seconds=time.monotonic()-started, log=log, constants_sha256=digest(cb),
                                 applied_constants=self.constants.unpack(schema or shader,cb.read_bytes()),
                                 formats=dict(inputs=[fmt for _, fmt in inputs], outputs=outputs)))
        result = []
        for index, fmt in enumerate(outputs):
            dtype, channels = types[fmt]
            shape = (h, w) + (() if channels == 1 else (channels,))
            result.append(np.fromfile(self.work/f'out{index}.bin', dtype).reshape(shape).copy())
        return result

    def close(self):
        self.worker.stdin.close()
        self.worker.wait(timeout=30)
        self.stderr.close()
        (self.work/'gpu_dispatches.json').write_text(json.dumps(self.records, indent=2)+'\n')


def floor_step_sequence(mode='full'):
    if mode == 'full':return (1,2,4,8,16)
    if mode == 'fast':return (1,2,16)
    raise ValueError('Floor steps must be full or fast')


def floor_producer_profile(floor=True, floor_steps='full'):
    steps=list(floor_step_sequence(floor_steps))
    return dict(floor_steps_mode=floor_steps,configured_floor_pass_steps=steps,
        floor_pass_steps=steps if floor else [],floor_enabled=bool(floor),
        floor_pass_policy='Explicit '+floor_steps+' Floor override, not inferred from capture settings')


def preprocessing_cache_identity(provenance, hashes, floor, bleed, floor_steps='full'):
    return dict(capture_manifest_sha256=provenance['capture_manifest_sha256'],frames=provenance['frames'],
        floor=int(floor),bleed=int(bleed),shader_hashes=hashes,floor_steps_mode=floor_steps,
        floor_pass_steps=floor_producer_profile(floor,floor_steps)['floor_pass_steps'])


def preprocessing_cache_matches(recorded, expected):
    # Original authenticated caches predate the choice and explicitly used full5.
    # Preserve them only for full; absent or partial metadata never grants fast.
    keys=('floor_steps_mode','floor_pass_steps')
    if not any(k in recorded for k in keys):
        return expected['floor_steps_mode']=='full' and recorded=={k:v for k,v in expected.items() if k not in keys}
    return all(k in recorded for k in keys) and recorded==expected


def preprocess(cap, gpu, floor, bleed, recovery_mask=3, floor_steps='full'):
    steps=floor_step_sequence(floor_steps)
    w, h = cap['roi']['extent']; size = (w, h)
    crop = camera_crop(cap['extent'], cap['roi'])
    zero = np.zeros((h, w, 4), np.float16); scalar = np.zeros((h, w), np.float32)
    records = []
    for index, metadata in enumerate(cap['frame_metadata']):
        frame = cap['capture']/'frames'/str(metadata['ordinal'])
        values = gpu.constants.unpack('FSRDFloorSeed', (frame/'floor_seed_constants.bin').read_bytes())
        if int(values['Flags'][0]) & ~3:
            raise ValueError('capture Seed needs a title depth resource this replay does not provide')
        inv = np.asarray(values['InvProjMatrix']).reshape(4, 4).T
        values['InvProjMatrix'] = (inv@crop).astype(np.float32).T.ravel()
        values.update(RenderSize=[w, h, 1/w, 1/h], FloorEnabled=int(floor),
                      InputBase=[0]*4, NormalBase=[0]*2, TitleDepthBase=[0]*2, AlbedoBase=[0]*2)
        seed, depth, gradient, reference, model = gpu.dispatch('FSRDFloorSeed', values,
            [(cap['raw_color'][index],10), (cap['raw_normals'][index],10), (cap['raw_depth'][index],41),
             (scalar,41), (cap['raw_diffuse_albedo'][index],28)], [10,41,10,10,10], size)
        base = seed
        if floor:
            for step in steps:
                base, model = gpu.dispatch('FSRDFloor', dict(DstTexSize=[w,h,1/w,1/h],StepSize=step,AlbedoBase=[0,0]),
                    [(base,10),(depth,41),(gradient,10),(cap['raw_diffuse_albedo'][index],28),
                     (reference,10),(model,10)], [10,10],size)
        values = gpu.constants.unpack('FSRDInputConv', (frame/'conversion_constants.bin').read_bytes())
        supported_flags=(1<<1)|(1<<2)|(1<<3)|(1<<4)|(1<<5)|(1<<7)|(1<<8)|(1<<11)|(1<<15)
        original_flags=int(values['Flags'][0])
        if original_flags & ~supported_flags:
            raise ValueError(f'capture conversion flags {original_flags:#x} require unsupported optional/routing inputs')
        if not original_flags & (1<<2) or not original_flags & (1<<5):
            raise ValueError('replay requires packed title roughness and an indirect-specular main signal')
        inv = np.asarray(values['InvProjMatrix']).reshape(4,4).T
        values['InvProjMatrix'] = (inv@crop).astype(np.float32).T.ravel()
        transform = values['MotionTransform']; transform[0] *= cap['extent'][0]/w; transform[1] *= cap['extent'][1]/h
        # Seed now owns canonical signed-linear depth, even though these older
        # captures stored the pre-canonical conversion flag (hardware depth).
        flags = (original_flags & ~(1<<7)) | (1<<1)
        if floor: flags |= 1<<7
        if bleed: flags |= 1<<28
        if index==0 or metadata['reset']:
            values['PrevViewMatrix']=metadata['controls']['view']
            values['JitterOffsets'][2:]=values['JitterOffsets'][:2]
        values.update(DstTexSize=[w,h,1/w,1/h], MotionInputSize=[w,h,1/w,1/h], MotionTransform=transform,
                      Flags=flags, RecoveryMask=recovery_mask, FloorDetailPreservation=1,
                      SpecularAlbedoDemodulation=1, DiffuseAlbedoModulation=1,
                      **{f'InputBase{i}':[0]*4 for i in range(6)})
        packed = gpu.dispatch('FSRDInputConv', values,
            [(cap['raw_color'][index],10),(depth,41),(cap['raw_motion'][index],10),(cap['raw_normals'][index],10),
             (scalar,41),(cap['raw_specular_hit_distance'][index],41),(cap['raw_diffuse_albedo'][index],28),
             (cap['raw_specular_albedo'][index],28),(cap['raw_bias_mask'][index],61),(base,10),(zero,10),
             (zero,10),(zero,10),(zero,10),(scalar,41),(scalar,41),(reference,10),(model,10)],
            [10,10,10,24,28,28,10,10,10,10],size)
        records.append([seed,base,depth,reference,model]+packed)
        if index%16==0: print(f'preprocess floor={int(floor)} bleed={int(bleed)} frame={index}/{len(cap["frame_metadata"])}',flush=True)
    names = ['seed','floor','depth','reference','model','specular','diffuse','motion','normals',
             'specular_albedo','diffuse_albedo','skip','detail','direct_specular','indirect_diffuse']
    return {name:np.stack([r[index] for r in records]) for index,name in enumerate(names)}


def replay(cap, packed, folder, executable, bleed, reset_frames):
    controls = [f['controls'] for f in cap['frame_metadata']]
    crop = camera_crop(cap['extent'], cap['roi'])
    projections = np.asarray([c['projection'] for c in controls],np.float64).reshape(-1,4,4)@np.linalg.inv(crop).T
    resets = np.asarray([int(f['reset']) for f in cap['frame_metadata']],np.uint32)
    for frame in reset_frames:
        if not 0 <= frame < len(resets): raise ValueError('injected reset frame outside capture')
        resets[frame]=1
    resets[0]=1
    camera_deltas=np.asarray([c['camera_delta'] for c in controls],np.float32)
    camera_deltas[resets!=0]=0
    scales = np.asarray([c['motion_vector_scale']+[1] if len(c['motion_vector_scale'])==2 else c['motion_vector_scale'] for c in controls])
    # Conversion emits canonical ROI UV motion, so the captured RR scale is kept.
    inputs = dict(diffuse=packed['diffuse'],specular=packed['specular'],depth=packed['depth'],motion=packed['motion'],
                  normals=packed['normals'],diffuse_albedo=packed['diffuse_albedo'],specular_albedo=packed['specular_albedo'],
                  resets=resets,jitters=np.asarray([c['jitter'] for c in controls]),
                  view=np.asarray([c['view'] for c in controls]).reshape(-1,4,4),projection=projections,
                  depth_bounds=np.asarray([c['depth_bounds'] for c in controls]),
                  camera_position_delta=camera_deltas,motion_vector_scale=scales)
    if bleed:
        inputs.update(direct_specular=packed['direct_specular'],indirect_diffuse=packed['indirect_diffuse'])
    return native.run_rr(folder,**inputs,executable=executable)


def compose(cap, packed, rr, gpu, bleed, full_witness, recovery=1, floor=True,
            composition_shader='FSRDOutputComp', cached_trust=None,
            recovery_mask=3, spatial_temporal_mask=2):
    w,h=cap['roi']['extent']; size=(w,h); n=len(packed['depth'])
    zero=np.zeros((h,w,4),np.float16); uintzero=np.zeros((h,w,4),np.uint32)
    history=np.full((h,w,4),-1,np.float16); history_metadata=uintzero.copy()
    history_valid=False
    if cached_trust is not None:
        cached_trust=np.asarray(cached_trust)
        if cached_trust.shape!=(n,h,w,2) or not np.isfinite(cached_trust).all():
            raise ValueError('cached trust must be finite [frames,height,width,2]')
    reset_frames=set(rr['metadata']['reset_frames'])
    if not 0<=recovery<=1 or recovery_mask&~7 or spatial_temporal_mask&~recovery_mask:
        raise ValueError('invalid recovery strength/selection/noise-method mask')
    detail_preservation=float(recovery) if floor else 0.0
    write_history=bool(detail_preservation>0 and recovery_mask)
    out=[]; votes=[]
    for frame in range(n):
        trust=np.zeros((h,w,2),np.float16)
        if bleed and cached_trust is not None:
            trust=cached_trust[frame].astype(np.float16)
        elif bleed:
            trust=gpu.dispatch('FSRDAlbedoTrustEvidence',dict(DstTexSize=[w,h,1/w,1/h],StepSize=0,
                Flags=(1<<1) if full_witness else 0,DemodDivisorFloor=.008),
                [(rr['direct_specular'][frame],10),(rr['diffuse'][frame],10),(packed['specular_albedo'][frame],28),
                 (packed['diffuse_albedo'][frame],28),(packed['skip'][frame],10),(packed['depth'][frame],41),
                 (packed['normals'][frame],24),(packed['direct_specular'][frame],10),(rr['indirect_diffuse'][frame],10),
                 (packed['specular'][frame],10),(packed['diffuse'][frame],10)], [34],size)[0]
            for step in (1,2,4,8,16,32):
                trust=gpu.dispatch('FSRDAlbedoTrustPropagate',dict(DstTexSize=[w,h,1/w,1/h],StepSize=step),
                    [(trust,34),(packed['depth'][frame],41),(packed['normals'][frame],24)],[34],size)[0]
        flags=(1<<3) | ((1<<8) if bleed else 0)
        reset=frame in reset_frames
        current_jitter=np.asarray(cap['frame_metadata'][frame]['controls']['jitter'],np.float32)
        previous_jitter=(current_jitter if reset or frame==0 else
                         np.asarray(cap['frame_metadata'][frame-1]['controls']['jitter'],np.float32))
        values=dict(DstTexSize=[w,h,1/w,1/h],Flags=flags,DetailPreservation=detail_preservation,
                    RecoveryMask=recovery_mask,SpatialTemporalMask=spatial_temporal_mask,
                    FloorHandoverAnchorClamp=4,FloorHandoverCorrelationMix=1,SourceUvScale=[1,1],SourceUvOffset=[0,0],
                    HistoryValid=int(write_history and history_valid and not reset),
                    HistoryJitterDelta=previous_jitter-current_jitter,WriteHistory=int(write_history),
                    SpecularAlbedoDemodulation=1,DiffuseAlbedoModulation=1,LumaRecovery=1,ChromaRecovery=1,
                    UnsupportedAlbedoRecovery=int(bleed),DemodDivisorFloor=.008)
        image,new_history,new_metadata=gpu.dispatch(composition_shader,values,
            [(rr['specular'][frame],10),(packed['specular_albedo'][frame],28),(rr['diffuse'][frame],10),
             (packed['diffuse_albedo'][frame],28),(packed['skip'][frame],10),(packed['normals'][frame],24),
             (packed['detail'][frame],10),(packed['depth'][frame],41),(packed['motion'][frame],10),(history,10),(history_metadata,3),
             (rr['direct_specular'][frame] if bleed else zero,10),(packed['direct_specular'][frame],10),(trust,34),
             (rr['indirect_diffuse'][frame] if bleed else zero,10),(packed['specular'][frame],10),
             (packed['diffuse'][frame],10)],[10,10,3],size,schema='FSRDOutputComp')
        if write_history:
            history,history_metadata=new_history,new_metadata
            history_valid=True
        out.append(image);votes.append(trust)
    return np.stack(out),np.stack(votes)


def luminance(a):
    return np.asarray(a,np.float32)[...,:3]@np.array([.2126,.7152,.0722],np.float32)


def box(a,r=2):
    p=np.pad(np.asarray(a,np.float64),r,mode='edge')
    c=np.pad(p.cumsum(0).cumsum(1),((1,0),(1,0)))
    k=2*r+1
    return (c[k:,k:]-c[:-k,k:]-c[k:,:-k]+c[:-k,:-k])/(k*k)


def composition_profile(floor=True,recovery=1,recovery_mask=3,spatial_temporal_mask=2,floor_steps='full'):
    producer=floor_producer_profile(floor,floor_steps)
    return dict(provenance='Explicit current-production-default recovery override; capture settings describe comparator, not this profile.',
        DetailPreservation=float(recovery) if floor else 0.,RecoveryMask=recovery_mask,
        SpatialTemporalMask=spatial_temporal_mask,LumaRecovery=1.,ChromaRecovery=1.,
        shader='Generic mixed flat Full Anchor / specular Light; diffuse disabled',
        floor_pass_steps=producer['floor_pass_steps'],floor_steps_mode=floor_steps,
        floor_pass_policy=producer['floor_pass_policy'])


def recovery_eligibility(packed,mask=3,method=2):
    if 'specular_albedo' not in packed:return dict(available=False)
    classes=(packed['normals']>>30)&3
    spec=packed['specular_albedo'][...,:3].astype(np.float32)
    diffuse=packed['diffuse_albedo'][...,:3].astype(np.float32)
    material=spec+diffuse;share=spec/np.maximum(material,1e-4)
    flat=((classes==1)&bool(mask&1));valid=material>0
    selected_spec=(~flat)&bool(mask&2)&((share*valid)>0).any(-1)
    selected_diffuse=(~flat)&bool(mask&4)&(((1-share)*valid)>0).any(-1)
    return dict(available=True,normal_class_fractions={str(i):float((classes==i).mean()) for i in range(4)},
        selected_flat_fraction=float(flat.mean()),selected_specular_fraction=float(selected_spec.mean()),
        selected_diffuse_fraction=float(selected_diffuse.mean()),
        selected_any_lobe_fraction=float((flat|selected_spec|selected_diffuse).mean()),
        flat_filtered=bool(method&1),specular_filtered=bool(method&2),diffuse_filtered=bool(method&4),
        limitation='Selection eligibility only; it does not prove a nonzero recovery correction.')


def measure(cap,packed,image,trust,reset_frames,recovery_mask=3,spatial_temporal_mask=2):
    raw=np.asarray(cap['raw_color'],np.float32)[...,:3]
    proxy=raw[len(raw)//2:].mean(0); target=luminance(proxy)
    mask=np.zeros(target.shape,bool);mask[8:-8,8:-8]=True
    luma=luminance(image); denom=np.maximum(target,.01)
    rgb=np.asarray(image,np.float32)[...,:3]
    chroma=rgb/np.maximum(rgb.sum(-1,keepdims=True),1e-5)
    detail=target-box(target); detail_energy=np.mean(detail[mask]**2)
    model=packed['model'].astype(np.float32); ref=packed['reference'].astype(np.float32)
    noisy=(model[...,3]>=.5)&(model[...,3]<2)&(ref[...,3]>=0)
    represented=(model[...,:3]>-99)
    all_channels=noisy&represented.all(-1);partial=noisy&represented.any(-1)&~represented.all(-1)
    residual_zero=(packed['specular'][...,:3]==0).all(-1)&(packed['diffuse'][...,:3]==0).all(-1)
    mass=trust[...,1].astype(np.float32)
    ratio=np.divide(trust[...,0].astype(np.float32),np.maximum(mass,1e-5))
    windows={}
    target_mean=max(float(target[mask].mean()),1e-5)
    raw_luma=luminance(raw)

    def window(start,end):
        mean=luma[start:end].mean(0)
        high=mean-box(mean)
        return dict(temporal_luma_sd_relative=float(np.mean(luma[start:end].std(0)[mask]/denom[mask])),
            global_temporal_luma_sd_relative=float(luma[start:end].std(0)[mask].mean()/target_mean),
            raw_temporal_luma_sd_relative=float(raw_luma[start:end].std(0)[mask].mean()/target_mean),
            temporal_noise_remaining_ratio=float(luma[start:end].std(0)[mask].mean()/max(raw_luma[start:end].std(0)[mask].mean(),1e-8)),
            consecutive_luma_delta_rms_relative=float(np.sqrt(np.mean(((np.diff(luma[start:end],axis=0)/denom)[:,mask])**2))) if end-start>1 else None,
            mean_luma_proxy_bias_relative=float(np.mean((mean[mask]-target[mask])/denom[mask])),
            texture_proxy_projection=float(np.mean(high[mask]*detail[mask])/max(detail_energy,1e-12)),
            severe_dark_tail_fraction=float(np.mean(luma[start:end][:,mask] < .25*target[mask])),
            temporal_chroma_sd_mean=float(chroma[start:end].std(0)[mask].mean()),
            trust_ratio_mean=float(ratio[start:end][:,mask].mean()))

    for start,end in ((0,4),(4,16),(16,32),(32,64),(64,len(raw))):
        if start>=len(raw):continue
        end=min(end,len(raw)); windows[f'{start}:{end}']=window(start,end)
    reset_indices=sorted({0,*reset_frames,*[i for i,f in enumerate(cap['frame_metadata']) if f['reset']]})
    reset_windows={}
    for ordinal,reset in enumerate(reset_indices):
        end_reset=reset_indices[ordinal+1] if ordinal+1<len(reset_indices) else len(raw)
        measurements={}
        for first,last in ((0,1),(1,4),(4,8),(8,16),(16,32)):
            start,end=reset+first,min(reset+last,end_reset)
            if start<end:measurements[f'+{first}:+{end-reset}']=dict(frames=[start,end],**window(start,end))
        reset_windows[str(reset)]=measurements
    relative_error=(luma-target)/denom
    frame_delta=np.sqrt(np.mean(((np.diff(luma,axis=0)/denom)[:,mask])**2,axis=1))
    reference_by_model={}
    for name,selection in (('all_rgb',all_channels),('partial_rgb',partial)):
        if selection.any():reference_by_model[name]=np.quantile(ref[...,3][selection],[0,.1,.5,.9,.99,1]).tolist()
    motion_pixels=np.linalg.norm(packed['motion'][...,:2].astype(np.float32)*np.array([target.shape[1],target.shape[0]]),axis=-1)
    return dict(metric_reference='Late raw temporal mean: stationary-scene proxy, not clean truth; crop borders excluded by 8px.',
        resets=dict(captured=[i for i,f in enumerate(cap['frame_metadata']) if f['reset']],replay_start=[0],injected=reset_frames),
        windows=windows,reset_relative_windows=reset_windows,
        recovery_lobe_eligibility=recovery_eligibility(packed,recovery_mask,spatial_temporal_mask),
        per_frame_proxy_metrics=dict(mean_luma_bias_relative=relative_error[:,mask].mean(1).tolist(),
            luma_proxy_rmse_relative=np.sqrt(np.mean(relative_error[:,mask]**2,axis=1)).tolist(),
            severe_dark_tail_fraction=(luma[:,mask]<.25*target[mask]).mean(1).tolist(),
            consecutive_luma_delta_rms_relative=[None,*frame_delta.tolist()]),
        all_channel_noise_model_fraction=float(all_channels.mean()),partial_channel_noise_model_fraction=float(partial.mean()),
        zero_main_residual_fraction_on_all_channel_models=float(residual_zero[all_channels].mean()) if all_channels.any() else None,
        reference_sigma_quantiles=np.quantile(ref[...,3],[0,.1,.5,.9,.99,1]).tolist(),
        reference_sigma_quantiles_by_model=reference_by_model,
        captured_motion_pixel_quantiles=np.quantile(motion_pixels,[0,.5,.9,.99,1]).tolist(),
        reference_bypassed_fraction=float((ref[...,3]<0).mean()),
        trust_nonzero_mass_fraction=float((mass>0).mean()),trust_nonfinite_fraction=float((~np.isfinite(trust)).mean()),
        output_nonfinite_fraction=float((~np.isfinite(image)).mean()),
        authentic_camera_turn_or_disocclusion_verified=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    source=parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--inventory',type=Path);source.add_argument('--capture',type=Path)
    parser.add_argument('--shader-dir',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--frames',type=int,default=128)
    parser.add_argument('--cases',nargs='+',default=['0:0','0:1','1:0','1:1'])
    parser.add_argument('--reset-frame',type=int,action='append',default=[])
    parser.add_argument('--floor-steps',choices=('full','fast'),default='full',help='Floor producer: full1/2/4/8/16 or runtime Fast1/2/16; default preserves full5 replays')
    parser.add_argument('--full-witness',action='store_true',help='Candidate bit1; baseline must omit it')
    parser.add_argument('--packed-dir',type=Path,help='Reuse authenticated preprocessing from a prior run, useful for reset-only probes')
    parser.add_argument('--build-only',action='store_true')
    args=parser.parse_args()
    output=safe_path(args.output);output.mkdir(parents=True,exist_ok=True)
    if args.inventory:
        root=safe_path(args.inventory)
        # Do not enumerate or recurse inside the reserved holdout.
        rows=[inspect_capture(p) for p in sorted(root.iterdir())
              if p.name.lower()!='reserve_data' and p.is_dir() and (p/'capture.json').is_file()]
        (output/'capture_inventory.json').write_text(json.dumps(rows,indent=2)+'\n')
        print(json.dumps([{k:r[k] for k in ('capture_uuid','frames','full_frame','original_reset_frames')} for r in rows],indent=2))
        return
    if args.shader_dir is None:parser.error('--shader-dir required for replay')
    shaders=safe_path(args.shader_dir)
    os.environ.setdefault('FSRD_VS_ROOT','F:/VisualStudio')
    gpu_exe=output/'build/fsrd_gpu_runner.exe';gpu_exe.parent.mkdir(parents=True,exist_ok=True)
    compile_cpp(HERE/'fsrd_gpu_runner.cpp',gpu_exe,('d3d12.lib','dxgi.lib'))
    rr_exe=native.build_native(output/'build/fsrd_floor_rr_replay.exe')
    if args.build_only:
        print('build_only=passed');return
    provenance,cap=inspect_capture(args.capture,True,args.frames)
    provenance['replay_producer_configuration']=floor_producer_profile(True,args.floor_steps)
    (output/'capture_provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
    shader_hashes={p.name:digest(p) for p in shaders.iterdir() if p.suffix in ('.cso','.hlsl','.hlsli')}
    (output/'shader_provenance.json').write_text(json.dumps(shader_hashes,indent=2)+'\n')
    result={}
    for case in args.cases:
        floor,bleed=[int(v) for v in case.split(':')]
        if floor not in (0,1) or bleed not in (0,1):raise ValueError('cases must be Floor:Bleed binary pairs')
        folder=output/f'floor{floor}_bleed{bleed}';folder.mkdir(exist_ok=True)
        cache_root=safe_path(args.packed_dir) if args.packed_dir else output
        cache=cache_root/f'packed_floor{floor}_bleed{bleed}.npz'
        cache_identity=preprocessing_cache_identity(provenance,shader_hashes,floor,bleed,args.floor_steps)
        cache_manifest=cache.with_suffix('.json')
        if cache.is_file():
            identity=json.loads(cache_manifest.read_text()) if cache_manifest.is_file() else {}
            cache_sha256=identity.pop('npz_sha256',None)
            if not preprocessing_cache_matches(identity,cache_identity) or cache_sha256!=digest(cache):
                raise ValueError('preprocessing cache identity differs or lacks a manifest: '+str(cache))
            with np.load(cache,allow_pickle=False) as archive:packed={k:archive[k] for k in archive.files}
        else:
            gpu=Gpu(output/f'preprocess_floor{floor}_bleed{bleed}',shaders,gpu_exe)
            try:packed=preprocess(cap,gpu,bool(floor),bool(bleed),floor_steps=args.floor_steps)
            finally:gpu.close()
            np.savez_compressed(cache,**packed)
            cache_manifest.write_text(json.dumps(dict(cache_identity,npz_sha256=digest(cache)),indent=2)+'\n')
        # A capture normally begins inside an existing game history. Replay and
        # injected resets must instead use current view/jitter as previous inputs.
        # Reconvert only those frames; the authenticated ordinary-frame cache is
        # reusable between no-reset and reset probes without losing provenance.
        patch_frames=sorted({0,*args.reset_frame,*provenance['original_reset_frames']})
        gpu=Gpu(folder/'reset_control_preprocess',shaders,gpu_exe)
        try:
            for frame in patch_frames:
                if not 0<=frame<provenance['frames']:raise ValueError('reset frame outside sequence')
                single={k:(v[frame:frame+1] if isinstance(v,np.ndarray) else v) for k,v in cap.items()}
                single['frame_metadata']=[cap['frame_metadata'][frame]]
                corrected=preprocess(single,gpu,bool(floor),bool(bleed),floor_steps=args.floor_steps)
                for name,array in corrected.items():packed[name][frame]=array[0]
        finally:gpu.close()
        (folder/'reset_control_patch.json').write_text(json.dumps(dict(frames=patch_frames,
            producer=floor_producer_profile(bool(floor),args.floor_steps),
            policy='current view/jitter as previous on reset; native cameraPositionDelta=0; composition history invalid'),indent=2)+'\n')
        rr=replay(cap,packed,folder/'rr',rr_exe,bool(bleed),args.reset_frame)
        gpu=Gpu(folder/'composition',shaders,gpu_exe)
        try:image,trust=compose(cap,packed,rr,gpu,bool(bleed),args.full_witness,floor=bool(floor))
        finally:gpu.close()
        np.savez_compressed(folder/'final.npz',image=image,trust=trust)
        metrics=measure(cap,packed,image,trust,args.reset_frame)
        metrics['composition_history']=dict(enabled=bool(floor),write_history=bool(floor),
                                             invalidated_frames=patch_frames,successful_frame_commit=True)
        metrics['composition_profile']=composition_profile(bool(floor),floor_steps=args.floor_steps)
        metrics['floor_producer']=floor_producer_profile(bool(floor),args.floor_steps)
        metrics['native_metadata']=str(folder/'rr/metadata.json')
        (folder/'metrics.json').write_text(json.dumps(metrics,indent=2)+'\n')
        result[case]=metrics
        (output/'results.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(dict(case=case,native_dispatches=rr['metadata']['counters'],metrics=metrics),indent=2),flush=True)
    if shader_hashes != {p.name:digest(p) for p in shaders.iterdir() if p.suffix in ('.cso','.hlsl','.hlsli')}:
        raise RuntimeError('shader snapshot changed during replay')


if __name__=='__main__':
    main()
