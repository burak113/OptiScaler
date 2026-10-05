"""Exact stored-output gate for composition PSO selection.

Exercises the actual C++ ChoosePipeline used by the host. This is a quality
gate, never a performance benchmark. Uses current Generic DXIL frozen into the
test output, or FSRD_COMPOSITION_GENERIC_BASELINE (FSRD_LOSSLESS_BASELINE fallback)
to compare to an independently pinned Generic directory after Anchor changes.
"""
from pathlib import Path
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import time

sys.dont_write_bytecode = True
import numpy as np
import run_fsrd_gpu_tests as t
from fsrd_alpha_common import GPUWorker
from fsrd_toolchain import compile_cpp

ROOT = Path(__file__).resolve().parents[4]
PRE = ROOT / 'OptiScaler/shaders/fsrd_preprocess/precompile'
SELECTOR_SOURCE = Path(__file__).with_name('fsrd_composition_variant_selection.cpp')
SELECTOR_HEADER = ROOT / 'OptiScaler/shaders/fsrd_preprocess/FSRDCompositionVariant.h'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def root_signature(path):
    data = Path(path).read_bytes()
    if data[:4] != b'DXBC':
        raise ValueError('Composition shader is not a DXIL container')
    for index in range(struct.unpack_from('<I', data, 28)[0]):
        offset = struct.unpack_from('<I', data, 32 + index * 4)[0]
        if data[offset:offset + 4] == b'RTS0':
            size = struct.unpack_from('<I', data, offset + 4)[0]
            return hashlib.sha256(data[offset + 8:offset + 8 + size]).hexdigest()
    raise ValueError('Composition shader has no embedded root signature')


def freeze(output):
    pinned = os.environ.get('FSRD_COMPOSITION_GENERIC_BASELINE') or os.environ.get('FSRD_LOSSLESS_BASELINE')
    baseline = Path(pinned).resolve() if pinned else PRE
    directories = {}
    generic = (PRE / 'FSRDOutputComp.hlsl').read_text(encoding='utf-8')
    marker = 'cbuffer CB_Comp'
    expected_schema = t.mirror.hlsl_cbuffer_fields(t.mirror.brace_body(generic, marker), 'Composition')
    identity = dict(baseline_origin=str(baseline), pinned_baseline=bool(pinned), variants={})
    for label, source, shader in [('baseline', baseline, 'FSRDOutputComp'),
                                  ('FSRDOutputComp', PRE, 'FSRDOutputComp'),
                                  ('FSRDOutputCompLight', PRE, 'FSRDOutputCompLight'),
                                  ('FSRDOutputCompNoRecovery', PRE, 'FSRDOutputCompNoRecovery')]:
        # Every specialized wrapper shares the canonical composition schema.
        # Freeze binaries too: an overlapping build cannot alter an A/B halfway.
        destination = output / 'frozen_shaders' / label
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / (shader + '_Shader.cso'), destination / 'FSRDOutputComp_Shader.cso')
        shutil.copyfile(source / 'FSRDOutputComp.hlsl', destination / 'FSRDOutputComp.hlsl')
        text = (destination / 'FSRDOutputComp.hlsl').read_text(encoding='utf-8')
        schema = t.mirror.hlsl_cbuffer_fields(t.mirror.brace_body(text, marker), 'Composition')
        if t.mirror.errors or schema != expected_schema:
            raise ValueError(label + ': frozen Generic constant-buffer schema differs from current composition')
        identity['variants'][label] = dict(source_sha256=sha(destination / 'FSRDOutputComp.hlsl'),
            shader_sha256=sha(destination / 'FSRDOutputComp_Shader.cso'),
            root_signature_sha256=root_signature(destination / 'FSRDOutputComp_Shader.cso'))
        directories[label] = destination
    signatures = {value['root_signature_sha256'] for value in identity['variants'].values()}
    if len(signatures) != 1:
        raise ValueError('Composition variants must retain exactly the same root signature')
    return directories, identity


def selected(selector, cb):
    # Never mirror selection in Python: execute the actual compiled host helper.
    return subprocess.check_output([str(selector), '--select', str(cb['Flags']),
        str(cb['DetailPreservation']), str(cb['RecoveryMask']), str(cb['SpatialTemporalMask'])], text=True).strip()

def constants(w, h, **updates):
    # Explicitly provide every field to both PSOs: the harness only supplies
    # some defaults when the directory equals the production PRE directory.
    cb = dict(DstTexSize=[w, h, 1 / w, 1 / h], Flags=0, DetailPreservation=.35,
        RecoveryMask=1, FloorHandoverAnchorClamp=4, SourceUvScale=[1, 1], SourceUvOffset=[0, 0],
        FloorHandoverCorrelationMix=1, HistoryValid=1, HistoryJitterDelta=[.125, -.0625],
        WriteHistory=1, SpecularAlbedoDemodulation=1, DiffuseAlbedoModulation=1,
        SpatialTemporalMask=1, LumaRecovery=1, ChromaRecovery=1,
        UnsupportedAlbedoRecovery=0, DemodDivisorFloor=.008)
    cb.update(updates)
    return cb

def fixture(w, h, scale=1, topology='mixed'):
    y, x = np.indices((h, w), dtype=np.float32)
    rng = np.random.default_rng(812924 + w * 31 + h)
    clean = np.empty((h, w, 4), np.float32)
    clean[..., 0] = .5 + .18 * np.sin(x * .31 + y * .17)
    clean[..., 1] = .4 + .13 * np.cos(x * .19 - y * .44)
    clean[..., 2] = .3 + .15 * np.sin(x * .41 + y * .05)
    clean[..., 3] = 0
    rr = clean.copy()
    rr[..., :3] += rng.normal(0, .018, (h, w, 3))
    rr[..., :3] *= scale
    reference = clean.copy()
    reference[..., :3] += rng.normal(0, .012, (h, w, 3))
    reference[..., :3] *= scale
    reference[..., 3] = .027 * scale
    # Includes active, explicitly skipped and noiseless references.
    reference[(x + y) % 17 == 0, 3] = -1
    reference[(x + y) % 13 == 0, 3] = 0
    normal = t.rgba(w, h, (.5, .5, .25))
    normal[..., 0] += .02 * np.sin(x * .13)
    normal[..., 1] += .015 * np.cos(y * .19)
    if topology == 'flat':
        normal[..., 3] = 1 / 3
    elif topology == 'ordinary':
        normal[..., 3] = 0
    else:
        normal[(x // 8 + y // 8) % 3 == 0, 3] = 1 / 3
        normal[(x + y) % 11 == 0, 3] = 2 / 3
        normal[-1, -1, 3] = 1 / 3
    spec = t.rgba(w, h, (.2, .05, .7))
    diff = t.rgba(w, h, (.5, .6, .1))
    diff[..., :3] += (.08 * np.sin(x * .37) + .04 * np.cos(y * .53))[..., None]
    # Mixed RGB lobe shares and absent albedo guides cannot authorize recovery.
    spec[(x + y) % 19 == 0, :3] = 0
    diff[(x + y) % 19 == 0, :3] = 0
    z = (10 + .003 * x + .002 * y).astype(np.float32)
    z[x > w * .65] += 3
    if w > 1:
        z[0, 0] = 0
    motion = t.rgba(w, h, (.25 / w, -.125 / h, 0), 1)
    motion[(x + y) % 23 == 0, 3] = 0
    old_decisions = t.rgba(w, h, (-1, -.5, .5), -1)
    metadata = np.zeros((h, w, 4), np.uint32)
    metadata[..., 0] = z.view(np.uint32)
    metadata[..., 1] = 0x80000000
    direct_signal = t.rgba(w, h, (.15 * scale, .1 * scale, .25 * scale), 1)
    direct_signal[(x + y) % 7 == 0, 3] = 0
    direct_denoised = direct_signal.copy()
    direct_denoised[..., :3] *= .85
    trust = np.empty((h, w, 2), np.float32)
    trust[..., 0] = 2 + .8 * np.sin(x * .17)
    trust[..., 1] = 3 + .7 * np.cos(y * .23)
    indirect = rr.copy()
    diffuse = rr.copy()
    diffuse[..., :3] *= .6
    extra_diffuse = rr.copy()
    extra_diffuse[..., :3] *= .35
    skip = t.rgba(w, h, (.025 * scale, .03 * scale, .02 * scale))
    return [indirect, spec, diffuse, diff, skip, normal, reference, z, motion,
            old_decisions, metadata, direct_denoised, direct_signal, trust, extra_diffuse]


def run():
    output = t.OUT.parent / 'composition_variants'
    output.mkdir(parents=True, exist_ok=True)
    directories, identity = freeze(output)
    selector = output / 'fsrd_composition_variant_selection.exe'
    selector_hash = sha(SELECTOR_HEADER)
    compile_cpp(SELECTOR_SOURCE, selector)
    if sha(SELECTOR_HEADER) != selector_hash:
        raise RuntimeError('Host selector changed during compilation')
    native = subprocess.run([str(selector)], capture_output=True, text=True, check=True)
    t.check('native composition selection contract', True, output=native.stdout.strip())
    records = []

    last_save = [time.monotonic()]
    def save():
        (output / 'results.json').write_text(json.dumps(dict(checks=t.checks, dispatches=t.timings,
            records=records, identity=identity, selector_header_sha256=selector_hash,
            performance_measured=False), indent=2), encoding='utf-8')

    def compare(label, cb, inputs, size, expected=None):
        variant = selected(selector, cb)
        if expected is not None and variant != expected:
            raise AssertionError(label + ': unsafe host PSO selection: ' + variant)
        directory = directories[variant]
        old_cb = bytes(t.constants('FSRDOutputComp', cb, directories['baseline']))
        new_cb = bytes(t.constants('FSRDOutputComp', cb, directory))
        if old_cb != new_cb:
            raise AssertionError(label + ': A/B constants differ')
        formats = [10, 10, 3] if cb['WriteHistory'] else [10]
        old = t._dispatch('FSRDOutputComp', cb, inputs, formats, size, directories['baseline'])
        new = t._dispatch('FSRDOutputComp', cb, inputs, formats, size, directory)
        differences = []
        for index, (a, b) in enumerate(zip(old, new)):
            changed = a.view(np.uint32) != b.view(np.uint32)
            if np.any(changed):
                differences.append(dict(output=index, changed=int(np.count_nonzero(changed)),
                    maximum=float(np.max(np.abs(a.astype(np.float64) - b.astype(np.float64))))))
        records.append(dict(case=label, size=list(size), variant=variant, controls=cb,
                            cb_sha256=hashlib.sha256(old_cb).hexdigest(), differences=differences))
        t.check('composition specialization ' + label, not differences, differences=differences)
        # finally and a failing case always write the report. Rewriting the whole growing
        # report after every passing case was a quadratic share of the suite runtime.
        if differences or time.monotonic() - last_save[0] > 5:
            save()
            last_save[0] = time.monotonic()
        if differences:
            raise AssertionError(label + ': specialization changed stored colour/history/metadata')
        return old, new

    cases = [
        ('light_flat', 'mixed', dict(RecoveryMask=1, SpatialTemporalMask=1), 'FSRDOutputCompLight'),
        ('light_spec_no_controls', 'mixed', dict(RecoveryMask=2, SpatialTemporalMask=2, DetailPreservation=1,
            FloorHandoverAnchorClamp=0, FloorHandoverCorrelationMix=0, LumaRecovery=0, ChromaRecovery=0), 'FSRDOutputCompLight'),
        ('light_diff_partial_controls', 'mixed', dict(RecoveryMask=4, SpatialTemporalMask=4,
            FloorHandoverAnchorClamp=8, FloorHandoverCorrelationMix=.3, LumaRecovery=.25, ChromaRecovery=.75,
            UnsupportedAlbedoRecovery=1, SpecularAlbedoDemodulation=.5, DiffuseAlbedoModulation=.75), 'FSRDOutputCompLight'),
        ('light_all', 'mixed', dict(RecoveryMask=7, SpatialTemporalMask=7, DetailPreservation=1,
            UnsupportedAlbedoRecovery=1), 'FSRDOutputCompLight'),
        ('legacy_only', 'mixed', dict(RecoveryMask=1, SpatialTemporalMask=0), 'FSRDOutputComp'),
        ('mixed_fallback', 'mixed', dict(RecoveryMask=7, SpatialTemporalMask=1), 'FSRDOutputComp'),
        ('common_flat_anchor_spec_light', 'mixed', dict(RecoveryMask=3, SpatialTemporalMask=2), 'FSRDOutputComp'),
        ('common_mixed_no_flat', 'ordinary', dict(RecoveryMask=3, SpatialTemporalMask=2), 'FSRDOutputComp'),
        ('recovery_off', 'mixed', dict(RecoveryMask=0, SpatialTemporalMask=7,
            UnsupportedAlbedoRecovery=1), 'FSRDOutputCompNoRecovery'),
        ('detail_off', 'mixed', dict(RecoveryMask=7, SpatialTemporalMask=7, DetailPreservation=0,
            UnsupportedAlbedoRecovery=1), 'FSRDOutputCompNoRecovery'),
        ('light_four_signals', 'mixed', dict(Flags=(1 << 6) | (1 << 7), RecoveryMask=7,
            SpatialTemporalMask=7), 'FSRDOutputCompLight'),
        ('no_recovery_four_signals', 'mixed', dict(Flags=(1 << 6) | (1 << 7), RecoveryMask=0),
            'FSRDOutputCompNoRecovery'),
    ]
    try:
        with GPUWorker(output):
            for w, h in ((1, 1), (1, 9), (9, 1), (7, 5), (17, 13), (41, 25)):
                for scale in (1, 12000):
                    for label, topology, updates, expected in cases:
                        compare(f'{label}_{w}x{h}_scale{scale}', constants(w, h, **updates),
                                fixture(w, h, scale, topology), (w, h), expected)
            w, h = 41, 25
            inputs = fixture(w, h)
            for mode in (1, 8, 15, 19, 20, 24):
                for detail in (0, .35):
                    cb = constants(w, h, Flags=(1 << 16) | (mode << 17), DetailPreservation=detail,
                        RecoveryMask=7, SpatialTemporalMask=7, UnsupportedAlbedoRecovery=1)
                    compare(f'debug_{mode}_{detail}', cb, inputs, (w, h), 'FSRDOutputComp')
            for label, flags in [('raw_blit', 1), ('scaled_raw_blit', 3),
                                 ('raw_debug_blit', 3 | (1 << 16) | (19 << 17))]:
                # Raw blits never write history; compare the defined colour only.
                compare(label, constants(w, h, Flags=flags, WriteHistory=0, SourceUvScale=[.75, 1.1],
                    SourceUvOffset=[.125, -.1]), inputs, (w, h), 'FSRDOutputComp')
            compare('scale_only_light', constants(w, h, Flags=2, SourceUvScale=[.75, 1.1],
                SourceUvOffset=[.125, -.1]), inputs, (w, h), 'FSRDOutputCompLight')
            for label, updates in [('light_no_history', dict(RecoveryMask=7, SpatialTemporalMask=7)),
                                   ('no_recovery_no_history', dict(RecoveryMask=0))]:
                compare(label, constants(w, h, WriteHistory=0, **updates), inputs, (w, h))
            old, new = compare('temporal_light_initial', constants(w, h, RecoveryMask=7,
                SpatialTemporalMask=7, HistoryValid=0), inputs, (w, h), 'FSRDOutputCompLight')
            for next_mask in (0, 3, 7):
                # The already checked current-frame Light history is a real prior
                # dispatch before a subsequent Anchor/mixed/Light method switch.
                next_inputs = list(inputs)
                next_inputs[9:11] = old[1:3]
                compare('temporal_switch_' + str(next_mask), constants(w, h, RecoveryMask=7,
                    SpatialTemporalMask=next_mask), next_inputs, (w, h))
        if sha(SELECTOR_HEADER) != selector_hash:
            raise RuntimeError('Host selector changed while its quality gate was running')
    finally:
        save()


if __name__ == '__main__':
    run()
