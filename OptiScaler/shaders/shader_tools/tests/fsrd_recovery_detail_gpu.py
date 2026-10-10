"""Isolated RecoveryDetail GPU job adapter. No shared runner/build/host edits.

Importing this module is CPU-only. Instantiate Dispatcher only after the parent
assigns the GPU slot; it uses the existing diagnostic D3D12 runner unchanged.
"""
from pathlib import Path
import hashlib
import importlib.util
import json
import re
import struct
import numpy as np

ROOT = Path(__file__).resolve().parents[4]
PRE = ROOT / "OptiScaler/shaders/fsrd_preprocess/precompile"
PREFIX = "FSRDRecoveryDetail"
# CB bytes, input DXGI formats, output DXGI formats, real shader group dimensions.
SCHEMAS = {
    "Horizontal": (48, [10, 10, 28], [2, 2], (128, 1, 1)),
    "Accumulate": (48, [2, 2, 2, 2, 2, 41, 24, 10], [2, 2, 2], (1, 128, 1)),
    "DCGroups": (48, [2, 2, 2, 2, 2, 2, 10], [2, 2, 2, 2], (8, 8, 1)),
    "DCGlobal": (16, [2, 2], [2], (8, 8, 1)),
    "ScaleGroups": (32, [2, 2, 10, 2, 2], [2], (8, 8, 1)),
    "ScaleGlobal": (16, [2], [2], (8, 8, 1)),
    "Apply": (32, [10, 2, 2, 2, 2, 2], [10], (8, 8, 1)),
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def mirror_module():
    spec = importlib.util.spec_from_file_location("recovery_detail_mirrors",
        ROOT / "OptiScaler/shaders/shader_tools/verify_fsrd_mirrors.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def constants(suffix, values, directory=PRE):
    text = (directory / (PREFIX + suffix + ".hlsl")).read_text(encoding="utf-8")
    mirror = mirror_module()
    body = mirror.brace_body(text, "cbuffer CB_Detail" + suffix)
    fields, size = mirror.hlsl_cbuffer_fields(body, PREFIX + suffix)
    if mirror.errors or size != SCHEMAS[suffix][0]:
        raise AssertionError((suffix, size, mirror.errors))
    unknown = set(values)-{name for name, _, _, _ in fields}
    if unknown:
        raise ValueError("Unknown CB field: " + repr(unknown))
    blob = bytearray(size)
    for name, _, offset, length in fields:
        if name not in values:
            continue
        value = values[name]
        if np.isscalar(value):
            value = [value]
        ty = re.search(r"\b(\w+)\s+"+re.escape(name)+r"\s*;", body)[1]
        fmt = "I" if ty.startswith("uint") else ("i" if ty.startswith("int") else "f")
        encoded = struct.pack("<"+fmt*len(value), *value)
        if len(encoded) != length:
            raise ValueError((name, length, len(encoded)))
        blob[offset:offset+length] = encoded
    return blob


def stored(array, fmt):
    array = np.asarray(array)
    # Capture normals are already original packed R10 bits; preserve them.
    if fmt == 24 and array.ndim == 2 and array.dtype == np.uint32:
        return array.astype("<u4", copy=False)
    if array.ndim == 2:
        array = array[..., None]
    if fmt == 41:
        return array[..., 0].astype("<f4")
    if array.shape[-1] < 4:
        array = np.pad(array, ((0, 0), (0, 0), (0, 4-array.shape[-1])))
    if fmt == 10:
        return array.astype("<f2")
    if fmt == 2:
        return array.astype("<f4")
    if fmt == 28:
        return array if array.dtype == np.uint8 else np.rint(np.clip(array, 0, 1)*255).astype(np.uint8)
    if fmt == 24:
        values = np.rint(np.clip(array, 0, 1)*[1023, 1023, 1023, 3]).astype(np.uint32)
        return values[..., 0] | (values[..., 1] << 10) | (values[..., 2] << 20) | (values[..., 3] << 30)
    raise ValueError("Unsupported texture format: " + str(fmt))


class Dispatcher:
    def __init__(self, output, directory=PRE):
        self.output = Path(output).resolve()
        self.output.relative_to((ROOT / "tools_tmp").resolve())
        self.output.mkdir(parents=True, exist_ok=True)
        self.directory = directory
        self.counter = 0
        self.timings = []
        # Lazy import is deliberate: CPU imports/ABI tests never start GPU work.
        import run_fsrd_gpu_tests as runner
        self.runner = runner
        runner.OUT = self.output / "worker"
        runner.OUT.mkdir(exist_ok=True)
        runner.runner = runner.OUT / "fsrd_gpu_runner.exe"
        runner.build_runner()
        self.sources = {str(p): sha(p) for suffix in SCHEMAS for p in
            (directory / (PREFIX+suffix+ext) for ext in (".hlsl", "_Shader.cso"))}
        self.sources[str(directory / (PREFIX+"Common.hlsli"))] = sha(directory / (PREFIX+"Common.hlsli"))

    def dispatch(self, suffix, values, inputs, groups, output_sizes, repetitions=1):
        _, input_formats, output_formats, _ = SCHEMAS[suffix]
        if len(inputs) != len(input_formats) or len(output_sizes) != len(output_formats):
            raise ValueError("Descriptor count mismatch: " + suffix)
        shader = PREFIX + suffix
        job_root = self.output / f"{self.counter:05}_{shader}"
        self.counter += 1
        job_root.mkdir(exist_ok=False)
        cb = job_root / "cb.bin"
        cb.write_bytes(constants(suffix, values, self.directory))
        # Existing runner divides job size by 8. Encoding 8*groupCount launches
        # the requested groups for this shader's actual 128x1/1x128/8x8 topology.
        # Logical extents stay in DstTexSize and each explicit output record.
        records = [f'{json.dumps(str(self.directory/(shader+"_Shader.cso")))} '
                   f'{json.dumps(str(cb))} {groups[0]*8} {groups[1]*8} '
                   f'{len(inputs)} {len(output_formats)} {repetitions}']
        for i, (array, fmt) in enumerate(zip(inputs, input_formats)):
            array = np.asarray(array)
            path = job_root / f"in{i}.bin"
            stored(array, fmt).tofile(path)
            records.append(f'{json.dumps(str(path))} {array.shape[1]} {array.shape[0]} {fmt}')
        for i, (fmt, size) in enumerate(zip(output_formats, output_sizes)):
            records.append(f'{json.dumps(str(job_root/f"out{i}.bin"))} {size[0]} {size[1]} {fmt}')
        job = job_root / "job.txt"
        job.write_text("\n".join(records), encoding="utf-8")
        result = self.runner.run_runner(job)
        (job_root / "runner.log").write_text(result.stdout+result.stderr, encoding="utf-8")
        if (result.returncode or "debug_layer=1" not in result.stdout or
            "validation_errors=0 validation_warnings=0" not in result.stdout):
            raise RuntimeError(shader+"\n"+result.stdout+result.stderr)
        times = dict(re.findall(r"(\w+)=([\d.eE+-]+)", result.stdout))
        adapter = re.search(r"adapter=(.+)", result.stdout)
        self.timings.append(dict(shader=shader, groups=groups, repetitions=repetitions,
            shader_sha256=self.sources[str(self.directory/(shader+"_Shader.cso"))],
            adapter=adapter[1].strip() if adapter else None, **times))
        outputs = []
        for i, (fmt, size) in enumerate(zip(output_formats, output_sizes)):
            array = np.fromfile(job_root / f"out{i}.bin", dtype="<f2" if fmt == 10 else "<f4")
            array = array.reshape(size[1], size[0], 4).astype(np.float32)
            if not np.all(np.isfinite(array)):
                raise AssertionError(shader+" produced nonfinite output")
            outputs.append(array)
        # Only generated staging bytes inside this owned job directory are removed.
        for path in job_root.glob("in*.bin"):
            path.unlink()
        for path in job_root.glob("out*.bin"):
            path.unlink()
        return outputs

    def close(self):
        self.runner._close_worker(self.runner.runner)
        finish = {path: sha(path) for path in self.sources}
        unchanged = finish == self.sources
        (self.output / "source_trace.json").write_text(json.dumps(dict(
            start=self.sources, finish=finish, unchanged=unchanged), indent=2))
        (self.output / "dispatches.json").write_text(json.dumps(self.timings, indent=2))
        if not unchanged:
            raise AssertionError("Shader sources/artifacts changed during GPU replay")


class DetailState:
    def __init__(self, dispatcher, width, height, response=.1):
        self.dispatcher = dispatcher
        self.width, self.height, self.response = width, height, response
        self.size = (width, height)
        self.constants = [width, height, 1/width, 1/height]
        self.groups = ((width+7)//8, (height+7)//8)
        self.valid = False
        self.history = {lobe: [np.zeros((height, width, 4), np.float32) for _ in range(3)]
                        for lobe in ("specular", "diffuse")}
        self.last = {}

    def step(self, signals, denoised, albedo, base, depth, normal, motion,
             strengths=(1., 1.), reset=False, jitter=(0., 0.), debug=0, modulation=(1., 1.)):
        dispatch = self.dispatcher.dispatch
        for index, lobe in enumerate(("specular", "diffuse")):
            horizontal = dispatch("Horizontal", dict(DstTexSize=self.constants,
                SmallRadius=3, LargeRadius=40, Flags=0, AlbedoModulation=modulation[index]),
                [signals[index], denoised[index], albedo[index]],
                ((self.width+127)//128, self.height), [self.size, self.size])
            self.history[lobe] = dispatch("Accumulate", dict(DstTexSize=self.constants,
                HistoryJitterDelta=jitter, HistoryValid=int(self.valid and not reset),
                Response=self.response, DepthRelativeTolerance=.03, NormalDotMinimum=.95,
                MinimumAge=8, MinimumEffectiveCount=8.),
                [*horizontal, *self.history[lobe], depth, normal, motion],
                (self.width, (self.height+127)//128), [self.size]*3)
        self.valid = True
        mask = int(strengths[0] > 0) | (int(strengths[1] > 0) << 1)
        raw_spec, raw_diffuse, summary_spec, summary_diffuse = dispatch("DCGroups",
            dict(DstTexSize=self.constants, SpecularStrength=strengths[0],
                 DiffuseStrength=strengths[1], K=2., MinimumAge=8,
                 MinimumEffectiveCount=8., LobeMask=mask),
            [*self.history["specular"], *self.history["diffuse"], base], self.groups,
            [self.size, self.size, (self.groups[0]*2, self.groups[1]), (self.groups[0]*2, self.groups[1])])
        global_cb = dict(GroupSize=self.groups, GroupCount=self.groups[0]*self.groups[1])
        dc = dispatch("DCGlobal", global_cb, [summary_spec, summary_diffuse], (1, 1), [(2, 2)])[0]
        one = np.ones((1, 1, 4), np.float32)
        inputs = [raw_spec, raw_diffuse, base, dc, one]
        lobe_min = dispatch("ScaleGroups", dict(DstTexSize=self.constants, Stage=0),
                            inputs, self.groups, [self.groups])[0]
        lobe_scales = dispatch("ScaleGlobal", global_cb, [lobe_min], (1, 1), [(1, 1)])[0]
        inputs[-1] = lobe_scales
        sum_min = dispatch("ScaleGroups", dict(DstTexSize=self.constants, Stage=1),
                           inputs, self.groups, [self.groups])[0]
        sum_scale = dispatch("ScaleGlobal", global_cb, [sum_min], (1, 1), [(1, 1)])[0]
        self.last = dict(spec=raw_spec, diffuse=raw_diffuse, dc=dc,
                         lobe_scales=lobe_scales, sum_scale=sum_scale)
        return dispatch("Apply", dict(DstTexSize=self.constants, Debug=debug, LobeMask=mask),
            [base, raw_spec, raw_diffuse, dc, lobe_scales, sum_scale], self.groups, [self.size])[0]
