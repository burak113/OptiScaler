"""Exact shared-output gate for the runtime composition graph.

Calls production CanSplitTiles and ChoosePipeline through compiled C++; executes
both full-grid PSOs on the same UAVs in either order. Quality only, with no
performance conclusions. A separately pinned Generic comparison is supported by
FSRD_COMPOSITION_GENERIC_BASELINE, with FSRD_LOSSLESS_BASELINE as fallback.
"""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import sys
import time

sys.dont_write_bytecode = True
import numpy as np
import run_fsrd_gpu_tests as t
import test_fsrd_composition_variants as base
from fsrd_alpha_common import GPUWorker
from fsrd_toolchain import compile_cpp

ROOT = Path(__file__).resolve().parents[4]
PRE = ROOT / 'OptiScaler/shaders/fsrd_preprocess/precompile'
SELECTOR_HEADER = ROOT / 'OptiScaler/shaders/fsrd_preprocess/FSRDCompositionVariant.h'
constants = base.constants
base_fixture = base.fixture


def freeze(output):
    directories, identity = base.freeze(output)
    reference = identity['variants']['baseline']['root_signature_sha256']
    for name in ('FSRDOutputCompTileLight', 'FSRDOutputCompTileAnchor'):
        destination = output / 'frozen_shaders' / name
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(PRE / (name + '_Shader.cso'), destination / 'FSRDOutputComp_Shader.cso')
        shutil.copyfile(PRE / 'FSRDOutputComp.hlsl', destination / 'FSRDOutputComp.hlsl')
        signature = base.root_signature(destination / 'FSRDOutputComp_Shader.cso')
        if signature != reference:
            raise ValueError(name + ': graph root signature differs from frozen Generic')
        directories[name] = destination
        identity['variants'][name] = dict(shader_sha256=base.sha(destination / 'FSRDOutputComp_Shader.cso'),
            root_signature_sha256=signature, source_sha256=base.sha(destination / 'FSRDOutputComp.hlsl'))
    return directories, identity


class GraphWorker(GPUWorker):
    def __init__(self, output):
        self.second_shader = ''
        super().__init__(output)

    def run(self, args, **kwargs):
        if str(args[0]) == str(t.runner):
            job = Path(args[1])
            lines = job.read_text().splitlines()
            # Sentinel initialization also requests the production-style graph
            # transitions for the single Generic reference. Default jobs in
            # every existing suite remain on their original runner path.
            lines[0] += ' ' + json.dumps(str(self.second_shader)) + ' 1'
            job.write_text('\n'.join(lines))
        return super().run(args, **kwargs)


def fixture(w, h, scale=1, topology='mixed'):
    inputs = base_fixture(w, h, scale, topology if topology in ('mixed', 'ordinary', 'flat') else 'ordinary')
    normals = inputs[5]
    if topology == 'single_anchor':
        normals[..., 3] = 0
        normals[-1, -1, 3] = 1 / 3
    elif topology == 'tile_edges':
        normals[..., 3] = 0
        normals[0, 0, 3] = 1 / 3
        normals[min(h - 1, 7), min(w - 1, 7), 3] = 1 / 3
        normals[-1, -1, 3] = 1 / 3
    elif topology == 'no_selection':
        normals[..., 3] = 0
        inputs[1][..., :3] = 0
        inputs[3][..., :3] = 0
    elif topology == 'dense_anchor_light':
        y, x = np.indices((h, w))
        normals[..., 3] = np.where((x + y) % 2 == 0, 1 / 3, 0)
    elif topology == 'separated_patches':
        normals[..., 3] = 0
        normals[:max(1, h // 2), :max(1, w // 2), 3] = 1 / 3
        normals[3 * h // 4:, 3 * w // 4:, 3] = 1 / 3
    return inputs


def compare_outputs(a, b):
    changes = []
    for index, (old, new) in enumerate(zip(a, b)):
        changed = old.view(np.uint32) != new.view(np.uint32)
        if np.any(changed):
            changes.append(dict(output=index, changed_channels=int(np.count_nonzero(changed)),
                maximum=float(np.max(np.abs(old.astype(np.float64) - new.astype(np.float64))))))
    return changes


def assert_coverage(outputs, cb):
    # Alpha can differ from one only for the generic raw/debug path, but no
    # legitimate fixture output can equal the finite clear sentinel.
    if np.any(outputs[0] == -8192):
        raise AssertionError('Color contains an untouched clear sentinel')
    history_written = bool(cb['WriteHistory']) and not (cb['Flags'] & 1)
    if history_written:
        if np.any(outputs[1] == -8192) or np.any(outputs[2] == 0xdeadbeef):
            raise AssertionError('History contains an untouched clear sentinel')
    else:
        if not np.all(outputs[1] == -8192) or not np.all(outputs[2] == 0xdeadbeef):
            raise AssertionError('Unused history outputs were modified')


def exercise(check):
    for size in ((1, 1), (1, 9), (9, 1), (7, 5), (17, 13), (41, 25)):
        w, h = size
        cb = constants(w, h, RecoveryMask=3, SpatialTemporalMask=2)
        for scale in (1, 12000):
            for topology in ('ordinary', 'flat', 'mixed', 'single_anchor', 'tile_edges', 'no_selection'):
                inputs = fixture(w, h, scale, topology)
                for reverse in (False, True):
                    check('common_' + topology, cb, inputs, size, reverse=reverse, scale=scale)
    w, h = 41, 25
    for recovery, light in ((3, 1), (7, 1), (7, 2), (7, 3), (7, 4), (7, 5), (7, 6), (6, 2), (6, 4)):
        for scale in (1, 12000):
            inputs = fixture(w, h, scale)
            cb = constants(w, h, RecoveryMask=recovery, SpatialTemporalMask=light)
            for reverse in (False, True):
                check('mixed_masks_' + str(recovery) + '_' + str(light), cb, inputs, (w, h),
                      reverse=reverse, scale=scale)
    controls = [('zero_controls', dict(FloorHandoverAnchorClamp=0, FloorHandoverCorrelationMix=0,
        LumaRecovery=0, ChromaRecovery=0)),
        ('partial_controls', dict(FloorHandoverAnchorClamp=8, FloorHandoverCorrelationMix=.3,
            LumaRecovery=.25, ChromaRecovery=.75)),
        ('max_controls', dict(DetailPreservation=1, FloorHandoverAnchorClamp=16,
            FloorHandoverCorrelationMix=1, LumaRecovery=1, ChromaRecovery=1)),
        ('unsupported_albedo', dict(UnsupportedAlbedoRecovery=1)),
        ('partial_demod', dict(SpecularAlbedoDemodulation=.5, DiffuseAlbedoModulation=.75,
            UnsupportedAlbedoRecovery=1)),
        ('initial_history', dict(HistoryValid=0)),
        ('jitter_history', dict(HistoryJitterDelta=[-.75, .5]))]
    for label, updates in controls:
        for scale in (1, 12000):
            inputs = fixture(w, h, scale)
            cb = constants(w, h, RecoveryMask=3, SpatialTemporalMask=2, **updates)
            for reverse in (False, True):
                check(label, cb, inputs, (w, h), reverse=reverse, scale=scale)
    # Real indirect/direct combinations must preserve the additive specular
    # correction as well as the base signal when choosing either fast graph.
    for flags in (1 << 2, 1 << 3, (1 << 2) | (1 << 3)):
        for recovery, light in ((3, 2), (7, 7)):
            cb = constants(w, h, Flags=flags, RecoveryMask=recovery,
                SpatialTemporalMask=light, UnsupportedAlbedoRecovery=1)
            for reverse in (False, True):
                check('signal_flags_' + str(flags) + '_' + str(light), cb,
                    fixture(w, h), (w, h), reverse=reverse)
    # Extra direct/indirect outputs carry distinct, nonzero radiance. Exercise
    # every specialized graph with them and with either primary lobe disabled.
    for flags in (1 << 6, 1 << 7, (1 << 6) | (1 << 7),
                  (1 << 6) | (1 << 7) | (1 << 2) | (1 << 3), 1 << 4, 1 << 5):
        for recovery, light in ((3, 2), (7, 7), (0, 0)):
            for reverse in (False, True):
                check('multi_signal_flags_' + str(flags) + '_' + str(recovery),
                    constants(w, h, Flags=flags, RecoveryMask=recovery, SpatialTemporalMask=light),
                    fixture(w, h), (w, h), reverse=reverse)
    for topology in ('ordinary', 'flat', 'mixed', 'single_anchor'):
        for reverse in (False, True):
            check('no_history_' + topology, constants(w, h, RecoveryMask=3, SpatialTemporalMask=2,
                WriteHistory=0), fixture(w, h, topology=topology), (w, h), reverse=reverse)
    # These real host selections are unchanged by the split predicate. All
    # three UAVs are compared, including raw/history-off sentinel preservation.
    unchanged = [('legacy_only', dict(RecoveryMask=1, SpatialTemporalMask=0)),
        ('light_only', dict(RecoveryMask=7, SpatialTemporalMask=7)),
        ('no_recovery', dict(RecoveryMask=0, SpatialTemporalMask=7, WriteHistory=0)),
        ('detail_off', dict(RecoveryMask=3, SpatialTemporalMask=2, DetailPreservation=0, WriteHistory=0)),
        ('raw', dict(Flags=1, RecoveryMask=3, SpatialTemporalMask=2)),
        ('scaled_raw', dict(Flags=3, RecoveryMask=3, SpatialTemporalMask=2,
            SourceUvScale=[.75, 1.1], SourceUvOffset=[.125, -.1])),
        ('scale_only', dict(Flags=2, RecoveryMask=3, SpatialTemporalMask=2))]
    for mode in (1, 8, 15, 19, 20, 24):
        unchanged.append(('debug_' + str(mode), dict(Flags=(1 << 16) | (mode << 17), WriteHistory=0,
            RecoveryMask=3, SpatialTemporalMask=2)))
    for label, updates in unchanged:
        cb = constants(w, h, **updates)
        check(label, cb, fixture(w, h), (w, h))
    # Compare real independent ping-pong histories, including method switches.
    for reverse in (False, True):
        inputs = fixture(w, h)
        outputs = check('temporal_initial', constants(w, h, RecoveryMask=3, SpatialTemporalMask=2,
            HistoryValid=0), inputs, (w, h), reverse=reverse)
        for recovery, light in ((7, 7), (3, 2), (7, 0), (7, 3), (3, 2)):
            outputs = check('temporal_switch_' + str(recovery) + '_' + str(light),
                constants(w, h, RecoveryMask=recovery, SpatialTemporalMask=light), inputs,
                (w, h), reverse=reverse, history=outputs)
    # Small images missed the optional cache's coordinate-sensitive failure.
    # Screen the exact split at the real target size before timing acceptance.
    w, h = 1280, 720
    for topology in ('ordinary', 'single_anchor', 'mixed', 'flat', 'dense_anchor_light', 'separated_patches'):
        inputs = fixture(w, h, topology=topology)
        for reverse in (False, True):
            check('large_common_' + topology, constants(w, h, RecoveryMask=3, SpatialTemporalMask=2),
                  inputs, (w, h), reverse=reverse)


def run():
    output = t.OUT.parent / 'composition_graph'
    output.mkdir(parents=True, exist_ok=True)
    directories, identity = freeze(output)
    selector = output / 'fsrd_composition_graph_selection.exe'
    header_hash = base.sha(SELECTOR_HEADER)
    compile_cpp(Path(__file__).with_name('fsrd_composition_graph_selection.cpp'), selector)
    if base.sha(SELECTOR_HEADER) != header_hash:
        raise RuntimeError('Production selector changed during native compilation')
    native = subprocess.run([str(selector)], check=True, capture_output=True, text=True)
    t.check('native composition graph selection contract', True, output=native.stdout.strip())
    records = []

    last_save = [time.monotonic()]
    def save():
        (output / 'results.json').write_text(json.dumps(dict(checks=t.checks, dispatches=t.timings,
            records=records, identity=identity, selector_header_sha256=header_hash,
            performance_measured=False), indent=2), encoding='utf-8')

    try:
        with GraphWorker(output) as worker:
            def check(label, cb, inputs, size, *, reverse=False, history=None, scale=1):
                # The native CLI invokes the same precedence as the real host:
                # CanSplitTiles first, then the existing ChoosePipeline fallback.
                selection = base.selected(selector, cb)
                if selection == 'Split':
                    names = ['FSRDOutputCompTileLight', 'FSRDOutputCompTileAnchor']
                    if reverse:
                        names.reverse()
                    candidate = directories[names[0]]
                    companion = directories[names[1]] / 'FSRDOutputComp_Shader.cso'
                else:
                    candidate, companion = directories[selection], ''
                baseline = directories['baseline']
                old_cb = bytes(t.constants('FSRDOutputComp', cb, baseline))
                if old_cb != bytes(t.constants('FSRDOutputComp', cb, candidate)):
                    raise AssertionError(label + ': graph A/B constants differ')
                captures = {}
                for name, directory, second in [('baseline', baseline, ''), ('candidate', candidate, companion)]:
                    worker.second_shader = second
                    active = list(inputs)
                    if history:
                        active[9:11] = history[name][1:3]
                    captures[name] = t._dispatch('FSRDOutputComp', cb, active, [10, 10, 3], size, directory)
                    dispatch = t.timings[-1]
                    if dispatch.get('graph_dispatches') != str(2 if second else 1):
                        raise AssertionError('Runner did not record the selected runtime graph')
                    if dispatch.get('sentinel_initialized') != '1':
                        raise AssertionError('Graph coverage sentinel was not initialized')
                    dispatch.update(comparison_role=name, quality_only=True,
                        companion_shader_sha256=base.sha(second) if second else None)
                    assert_coverage(captures[name], cb)
                changed = compare_outputs(captures['baseline'], captures['candidate'])
                records.append(dict(case=label, selection=selection, size=list(size), controls=cb,
                    radiance_scale=scale, reverse_order=reverse,
                    cb_sha256=hashlib.sha256(old_cb).hexdigest(), differences=changed))
                t.check('composition graph ' + label, not changed, differences=changed)
                # finally and a failing case always write the report. Rewriting the whole growing
                # report after every passing case was a quadratic share of the suite runtime.
                if changed or time.monotonic() - last_save[0] > 5:
                    save()
                    last_save[0] = time.monotonic()
                if changed:
                    raise AssertionError(label + ': graph changed stored color/history/metadata')
                return captures

            exercise(check)
        if base.sha(SELECTOR_HEADER) != header_hash:
            raise RuntimeError('Production selector changed while the graph gate ran')
    finally:
        save()


if __name__ == '__main__':
    run()
