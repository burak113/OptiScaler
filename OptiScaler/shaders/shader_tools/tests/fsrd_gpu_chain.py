"""Typed resources and jobs for the versioned D3D12 multi-pass test runner.

Only orchestration lives here. Shaders are compiled from current production
sources; buffers, texture arrays and ExecuteIndirect use their real bindings.
"""
from pathlib import Path
import hashlib
import json
import re
import shlex
import subprocess
import time
import numpy as np


FORMATS = {2: (np.dtype('<f4'), 4), 3: (np.dtype('<u4'), 4),
           10: (np.dtype('<f2'), 4), 16: (np.dtype('<f4'), 2), 17: (np.dtype('<u4'), 2),
           24: (np.dtype('<u4'), 1), 28: (np.dtype('u1'), 4),
           34: (np.dtype('<f2'), 2), 41: (np.dtype('<f4'), 1), 42: (np.dtype('<u4'), 1)}


def compile_shader(source, output, defines=()):
    """Fresh compilation with separate wall time and source/include identities."""
    from fsrd_toolchain import dxc
    source, output = Path(source), Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [str(dxc()), '-T', 'cs_6_2', '-E', 'CSMain', '-enable-16bit-types', '-O3',
               '-Qstrip_debug', '-Qstrip_reflect',
               '-I', str(source.parent), '-Fo', str(output), str(source)]
    for define in defines:
        command.extend(['-D', str(define)])
    start = time.perf_counter()
    result = subprocess.run(command, capture_output=True, text=True)
    elapsed = time.perf_counter() - start
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    # Deliberately hash the complete local include set as well as the entrypoint;
    # a stale .cso can never be mistaken for freshly validated production code.
    inputs = {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in [source, *sorted(source.parent.glob('*.hlsli'))]}
    return dict(source=str(source), output=str(output), defines=list(defines),
                compile_seconds=elapsed, source_sha256=inputs,
                dxil_sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
                stdout=result.stdout, stderr=result.stderr)


class ChainJob:
    """Explicit register tables: -1=null 2D, -2=null raw, -3=null array.

    A resource may change SRV/UAV roles between passes, never within a pass.
    Reset passes copy original bytes before Classify; compute passes receive
    barriers and independently timestamped dispatches, including indirect work.
    """
    def __init__(self, directory, runner_module):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.runner = runner_module
        self.resources, self.passes, self.names = [], [], {}

    def _add(self, name, array, format, size, layers, raw, writable, readback):
        if name in self.names:
            raise ValueError('duplicate resource ' + name)
        if raw:
            data = (np.asarray(array, dtype='<u4').tobytes() if array is not None else bytes(size))
            width, height, layers, kind, format = len(data), 1, 1, 0, 0
            if width % 4:
                raise ValueError('raw byte size must be divisible by four')
            shape = (width // 4,)
        else:
            dtype, channels = FORMATS[format]
            if size is None:
                if array is None:
                    raise ValueError('texture size required')
                a = np.asarray(array)
                height, width = a.shape[-3:-1] if channels > 1 else a.shape[-2:]
            else:
                width, height = size
            shape = ((layers,) if layers > 1 else ()) + (height, width) + ((channels,) if channels > 1 else ())
            data = (np.zeros(shape, dtype=dtype) if array is None else np.asarray(array, dtype=dtype)).tobytes()
            expected = int(np.prod(shape)) * dtype.itemsize
            if len(data) != expected:
                raise ValueError(f'{name}: input has {len(data)} bytes, expected {expected}')
            kind = 3 if layers > 1 else 2
        index = len(self.resources)
        path = self.directory / f'in_{index:02d}_{name}.bin'
        path.write_bytes(data)
        output = self.directory / f'out_{index:02d}_{name}.bin' if readback else None
        self.names[name] = index
        self.resources.append(dict(name=name, kind=kind, width=width, height=height,
                                   layers=layers, format=format, writable=bool(writable),
                                   input=path, output=output, shape=shape))
        return name

    def texture(self, name, array=None, format=10, size=None, layers=1,
                writable=False, readback=False):
        return self._add(name, array, format, size, layers, False, writable, readback)

    def raw(self, name, array=None, size=None, writable=False, readback=False):
        return self._add(name, array, 0, size, 1, True, writable, readback)

    def _index(self, value):
        return self.names[value] if isinstance(value, str) else int(value)

    def compute(self, name, shader, constants, srvs, uavs, groups=(1, 1, 1),
                indirect=None, argument_offset=0):
        cb = self.directory / f'cb_{len(self.passes):02d}.bin'
        cb.write_bytes(bytes(constants))
        reads, writes = list(map(self._index, srvs)), list(map(self._index, uavs))
        if set(reads).intersection(writes).difference({-1, -2, -3}):
            raise ValueError('a resource cannot be both SRV and UAV within a pass')
        self.passes.append(dict(name=name, shader=str(Path(shader).resolve()), constants=str(cb),
                                mode=int(indirect is not None), groups=groups,
                                argument=self._index(indirect) if indirect is not None else -1,
                                offset=argument_offset, srvs=reads, uavs=writes))

    def reset(self, name, resources, byte_count=0):
        """Copy initial resource bytes; byte_count=16 matches tile header reset."""
        self.passes.append(dict(name=name, shader='-', constants='-', mode=2,
                                groups=(byte_count, 0, 0), argument=-1, offset=0,
                                srvs=[], uavs=list(map(self._index, resources))))

    def run(self, repetitions=1, warmup=0, keep_staging=False):
        if not 0 <= warmup < repetitions:
            raise ValueError('warmup must be less than repetitions')
        quote = lambda value: json.dumps(str(value))
        lines = ['FSRD_CHAIN_V1', f'{repetitions} {warmup} {len(self.resources)} {len(self.passes)}']
        for r in self.resources:
            lines.append(' '.join([quote(r['name']), str(r['kind']), str(r['width']), str(r['height']),
                                   str(r['layers']), str(r['format']), str(int(r['writable'])),
                                   quote(r['input']), quote(r['output'] or '-')]))
        for p in self.passes:
            lines.append(' '.join([quote(p['name']), quote(p['shader']), quote(p['constants']),
                                   str(p['mode']), *map(str, p['groups']), str(p['argument']), str(p['offset']),
                                   str(len(p['srvs'])), str(len(p['uavs'])),
                                   *map(str, p['srvs']), *map(str, p['uavs'])]))
        job = self.directory / 'chain.txt'
        job.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        start = time.perf_counter()
        result = self.runner.run_runner(job)
        elapsed = time.perf_counter() - start
        (self.directory / 'runner.stdout.txt').write_text(result.stdout, encoding='utf-8')
        (self.directory / 'runner.stderr.txt').write_text(result.stderr, encoding='utf-8')
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        outputs = {}
        for r in self.resources:
            if r['output']:
                dtype = np.dtype('<u4') if r['kind'] == 0 else FORMATS[r['format']][0]
                outputs[r['name']] = np.fromfile(r['output'], dtype=dtype).reshape(r['shape']).copy()
        timings, samples = {}, {}
        for line in result.stdout.splitlines():
            fields = shlex.split(line)
            if fields[:1] == ['chain_timing']:
                timings[fields[1]] = {key: float(value) for key, value in (s.split('=') for s in fields[2:])}
            elif fields[:1] == ['chain_samples']:
                samples[fields[1]] = list(map(float, fields[2:]))
        adapter = re.search(r'^adapter=(.+)$', result.stdout, re.M)
        metadata = dict(adapter=adapter[1] if adapter else None, runner_seconds=elapsed,
                        repetitions=repetitions, warmup=warmup, timings=timings, samples=samples,
                        counters={key: int(value) for key, value in re.findall(r'(\w+)=(\d+)', result.stdout)},
                        formats=[{k: str(v) if isinstance(v, Path) else v for k, v in r.items()}
                                 for r in self.resources], passes=self.passes)
        (self.directory / 'result.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
        if not keep_staging:
            for path in self.directory.glob('*.bin'):
                path.unlink()
        return outputs, metadata
