"""Small test-only helpers for the additive split; production DXIL does the math."""
from pathlib import Path
import hashlib
import json
import subprocess
from types import SimpleNamespace
import numpy as np
import run_fsrd_gpu_tests as t

BASE = '56e1af15ee9fd6d57daac12e240159eac1c3df8e'
SHADER_PATH = 'OptiScaler/shaders/fsrd_preprocess/precompile'
LUMA = np.array([.2126, .7152, .0722], np.float32)
CONV_FORMATS = [10, 10, 10, 24, 28, 28, 10, 10]


def frozen_identity(directory):
    """Reject current-as-baseline and authenticate original sources to the base commit."""
    directory = Path(directory).resolve()
    if directory == t.PRE.resolve():
        raise ValueError('Baseline must be separate, frozen base artifacts')
    records = {}
    for name in ('FSRDFloorSeed', 'FSRDFloor', 'FSRDInputConv', 'FSRDOutputComp'):
        path = directory / (name + '.hlsl')
        original = subprocess.check_output(['git', 'show', f'{BASE}:{SHADER_PATH}/{path.name}'], cwd=t.ROOT)
        # Checkout CRLF conversion is not a source change.
        if original.replace(b'\r\n', b'\n') != path.read_bytes().replace(b'\r\n', b'\n'):
            raise ValueError(f'{path} is not genuine {BASE} source')
        cso = directory / (name + '_Shader.cso')
        original_dxil = subprocess.check_output(['git', 'show', f'{BASE}:{SHADER_PATH}/{cso.name}'], cwd=t.ROOT)
        if original_dxil != cso.read_bytes():
            raise ValueError(f'{cso} is not genuine {BASE} DXIL')
        records[name] = dict(source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                             dxil_sha256=hashlib.sha256(cso.read_bytes()).hexdigest())
    for name in ('FSRDFloorSeed', 'FSRDFloor', 'FSRDOutputComp'):
        if (directory / (name + '_Shader.cso')).read_bytes() != (t.PRE / (name + '_Shader.cso')).read_bytes():
            raise ValueError(f'Unrelated production shader changed: {name}')
    return dict(commit=BASE, directory=str(directory), shaders=records)


def extract_baseline(output):
    directory = Path(output)/'frozen_base'
    directory.mkdir(parents=True, exist_ok=True)
    paths = subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', BASE, SHADER_PATH],
                                    cwd=t.ROOT, text=True).splitlines()
    for path in paths:
        if Path(path).suffix in ('.hlsl', '.hlsli', '.cso'):
            (directory/Path(path).name).write_bytes(subprocess.check_output(['git', 'show', f'{BASE}:{path}'], cwd=t.ROOT))
    return directory


class GPUWorker:
    """Use the existing --server mode, checking every job's D3D12 diagnostics."""
    def __init__(self, output):
        output = Path(output).resolve()
        output.mkdir(parents=True, exist_ok=True)
        t.OUT = output / 'shader_jobs'
        t.OUT.mkdir(exist_ok=True)
        t.runner = output / 'fsrd_gpu_runner.exe'
        t.build_runner()
        self.original = t.subprocess
        self.stderr = (output / 'gpu_worker_stderr.log').open('w', encoding='utf-8')
        self.worker = subprocess.Popen([str(t.runner), '--server'], stdin=subprocess.PIPE,
                                       stdout=subprocess.PIPE, stderr=self.stderr, text=True, bufsize=1)
        t.subprocess = SimpleNamespace(run=self.run)

    def run(self, args, **kwargs):
        if str(args[0]) != str(t.runner):
            return self.original.run(args, **kwargs)
        self.worker.stdin.write(str(args[1]) + '\n')
        self.worker.stdin.flush()
        lines = []
        while True:
            line = self.worker.stdout.readline()
            if not line:
                raise RuntimeError('GPU worker stopped; see gpu_worker_stderr.log')
            if line.startswith('job_complete='):
                code = int(line.split('=')[1])
                break
            lines.append(line)
        log = ''.join(lines)
        if code or 'debug_layer=1' not in log or 'validation_errors=0 validation_warnings=0' not in log:
            raise RuntimeError(log + '; see gpu_worker_stderr.log')
        return subprocess.CompletedProcess(args, code, log, '')

    def close(self):
        t.subprocess = self.original
        self.worker.stdin.close()
        self.worker.wait(timeout=30)
        self.stderr.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def rgba(rgb, alpha=0):
    rgb = np.asarray(rgb, np.float32)
    if rgb.ndim == 2:
        rgb = np.repeat(rgb[..., None], 3, axis=-1)
    return np.concatenate((rgb, np.full((*rgb.shape[:-1], 1), alpha, np.float32)), axis=-1)


def conversion_cb(w, h, strength=0, floor=False, indirect=True, **overrides):
    cb = dict(InvViewMatrix=np.eye(4).ravel(), InvProjMatrix=np.eye(4).ravel(),
              PrevViewMatrix=np.eye(4).ravel(), DstTexSize=[w, h, 1/w, 1/h],
              MotionInputSize=[w, h, 1/w, 1/h], MotionTransform=[1, 1, 0, 0],
              NearPlane=.1, FarPlane=10000, FloorDetailPreservation=1,
              Flags=(1 << 1) | ((1 << 5) if indirect else 0) | ((1 << 7) if floor else 0),
              DemodDivisorFloor=.008, BiasMaskStrength=1, SpecularAlbedoDemodulation=1,
              DiffuseAlbedoModulation=1, RecoveryMask=1, AdditiveLightSplit=strength)
    cb.update(overrides)
    return cb


def convert(raw, diff, spec, strength=0, *, directory=t.PRE, depth=None, normals=None,
            roughness=None, floor=None, reference=None, motion=None, overrides=None,
            size=None, origins=None, resources=None, kernel='auto', output_formats=None):
    h, w = raw.shape[:2]
    lw, lh = size or (w, h)
    zero = np.zeros((h, w, 4), np.float32)
    depth = np.full((h, w), 10, np.float32) if depth is None else depth
    normals = t.rgba(w, h, (0, 0, -1)) if normals is None else normals
    roughness = np.full((h, w), .55, np.float32) if roughness is None else roughness
    floor_enabled = floor is not None
    cb = conversion_cb(lw, lh, strength, floor_enabled, **(overrides or {}))
    applied = float(cb['AdditiveLightSplit'])
    applied = min(max(applied, 0), 1) if np.isfinite(applied) else 0.0
    cb['AdditiveLightSplit'] = applied
    if origins:
        cb.update(origins)
    inputs = [raw, depth, zero if motion is None else motion, normals, roughness, depth,
              diff, spec, zero, zero if floor is None else floor, zero, zero, zero, zero,
              depth, zero, raw if reference is None else reference]
    for slot, array in (resources or {}).items():
        if slot == len(inputs):
            inputs.append(array)
        else:
            inputs[slot] = array
    # Mirror the production PSO selection. Original DXIL at applied strength0
    # protects every stored channel from enabled-path compiler reassociation.
    # Historical frozen directories keep their original shader basename.
    if kernel not in ('auto', 'original', 'additive'):
        raise ValueError('Unknown conversion kernel: '+kernel)
    # Explicit additive0 is a test-only reference for enabled-kernel rejection
    # arithmetic; it must not be mistaken for production's disabled PSO.
    shader = ('FSRDInputConvAdditive' if kernel == 'additive' or
              (kernel == 'auto' and applied > 0 and Path(directory).resolve() == t.PRE.resolve())
              else 'FSRDInputConv')
    return t.dispatch(shader, cb, inputs, CONV_FORMATS if output_formats is None else output_formats,
                      (lw, lh), directory=directory)


def compose(packed, spec=None, diff=None, *, directory=t.PRE, depth=None, detail=1,
            spec_strength=1, diff_strength=1):
    h, w = packed[0].shape[:2]
    depth = np.full((h, w), 10, np.float32) if depth is None else depth
    cb = dict(DstTexSize=[w, h, 1/w, 1/h], Flags=1 << 3, DetailPreservation=detail,
              SpecularAlbedoDemodulation=spec_strength, DiffuseAlbedoModulation=diff_strength,
              RecoveryMask=1, FloorHandoverAnchorClamp=4, FloorHandoverCorrelationMix=1,
              LumaRecovery=1, ChromaRecovery=1)
    return t.dispatch('FSRDOutputComp', cb,
                      [packed[0] if spec is None else spec, packed[4],
                       packed[1] if diff is None else diff, packed[5], packed[6],
                       packed[3], packed[7], depth], [10], (w, h), directory=directory)[0]


def seed_frame(raw, diff, depth, normals, directory, overrides=None):
    h, w = raw.shape[:2]
    values = dict(InvProjMatrix=np.eye(4).ravel(), RenderSize=[w, h, 1/w, 1/h],
                  NearPlane=.1, FarPlane=10000, Flags=1, FloorEnabled=1)
    for key in ('InvProjMatrix', 'NearPlane', 'FarPlane'):
        if key in (overrides or {}):
            values[key] = overrides[key]
    if 'JitterOffsets' in (overrides or {}):
        values['CurrentJitter'] = overrides['JitterOffsets'][:2]
    floor, linear, guide, reference = t.dispatch('FSRDFloorSeed', values,
        [raw, normals, depth, depth, diff], [10, 41, 10, 10], (w, h), directory=directory)
    for step in (1, 2, 4, 8, 16):
        floor = t.dispatch('FSRDFloor', dict(DstTexSize=[w, h, 1/w, 1/h], StepSize=step),
                           [floor, linear, guide, diff], [10], (w, h), directory=directory)[0]
    return floor, linear, reference


def shader_identity(directory):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(Path(directory).iterdir()) if p.suffix in ('.cso', '.hlsl', '.hlsli')}


def save_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False), encoding='utf-8')
