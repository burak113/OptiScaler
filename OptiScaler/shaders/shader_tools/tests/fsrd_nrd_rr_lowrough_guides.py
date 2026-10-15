"""Two strictly positive packed-B views of one NEW r80 physical GGX scene.

The only native input difference is B46 versus B80. The hypothesis that the
title's raw code20 was perceptual roughness is explicit and unproved. Physics,
noise, positive real A, chosenQs, both references and primary motion are fixed.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np

import fsrd_nrd_rr_ggx_oracle as oracle
import fsrd_nrd_rr_ggx_views as domain
import fsrd_nrd_rr_material_compare as native_common
import fsrd_nrd_rr_material_quality as sealed


NAMES = ('spec', 'diff', 'depth', 'motion', 'normals', 'spec_albedo', 'diff_albedo')
MASK = np.uint32(1023 << 20)
CODES = (46, 80)


def link(source, destination):
    domain.need(not destination.exists(), 'fresh immutable hardlink target')
    os.link(source, destination)
    domain.need(sealed.file_sha(source) == sealed.file_sha(destination), 'read-only-by-contract hardlink identity')


def prepare(physical_case, output):
    domain.need(not output.exists() and output.resolve().is_relative_to(native_common.TASK.resolve()), 'fresh task-scoped positive-guide views')
    output.mkdir(parents=True)
    raw = 20 / 255.
    factor = np.clip((raw - .04) / (.11 - .04), 0., 1.)
    mapped = raw * factor * factor * (3. - 2. * factor)
    domain.need(int(np.rint(mapped * 1023.)) == 46 and int(np.rint(raw * 1023.)) == 80, 'exact declared UNORM8-to-R10 transfer, both codes positive')
    common = output / 'common-demod'
    domain.derive(physical_case, common)
    manifest = json.loads((common / 'ggx-sequence.json').read_bytes())
    domain.need(manifest['code'] == 80 and manifest['roughness'] == 80 / 1023. and manifest['raw_native_unorm8_code'] == 20,
                'new physical r80 source, never a relabeling of the old r123/r307 references')
    paths = []
    for code in CODES:
        case = output / ('guide-b' + str(code))
        (case / 'dataset').mkdir(parents=True)
        view = case / 'dataset'
        link(common / 'dataset/native-replay.txt', view / 'native-replay.txt')
        frames = []
        for frame in manifest['frames']:
            origin = common / 'dataset' / frame['directory']
            folder = view / frame['directory']
            folder.mkdir()
            for name in sorted((set(frame['derived_names']) | set(NAMES)) - {'normals'}):
                link(origin / frame['payloads'][name]['file'], folder / frame['payloads'][name]['file'])
            normal = sealed.load(physical_case / 'dataset' / frame['directory'], frame['payloads']['normals'])
            changed = ((normal & ~MASK) | np.uint32(code << 20)).astype('<u4')
            domain.need(np.array_equal(changed & ~MASK, normal & ~MASK), 'normal RG and native material A remain bit-exact')
            payloads = dict(frame['payloads'])
            payloads['normals'] = sealed.put(folder, 'normals.bin', changed)
            for name in NAMES:
                if name != 'normals':
                    domain.need(payloads[name] == frame['payloads'][name], 'only roughness B changes; all RGB/A/depth/MV/albedos exact')
            frames.append(dict(frame, payloads=payloads, derived_names=list(frame['derived_names']) + ['normals']))
        result = dict(manifest, frames=frames, views={'lowrough-guide-b' + str(code): str(view)},
            guide_roughness_code=code, guide_roughness=code / 1023.,
            physical_roughness_code=80, common_demod_case=str(common),
            common_demod_manifest_sha256=sealed.file_sha(common / 'ggx-sequence.json'),
            roughness_guide_source_sha256=sealed.file_sha(Path(__file__)),
            guide_axis='only packed normal.B changes, real signal/reference physics stays r80/1023; both candidate B values are strictly positive',
            albedo_guide_axis='unchanged chosenQs belongs to fixed physical material, never recalculated from a deliberately misreported guideB',
            native_raw_perceptual_semantics_proved=False, zero_roughness_used=False)
        sealed.write_json(case / 'ggx-sequence.json', result)
        paths.append(dict(case=str(case), manifest_sha256=sealed.file_sha(case / 'ggx-sequence.json'), guide_roughness_code=code))
    sealed.write_json(output / 'views.json', dict(cases=paths, physical_case=str(physical_case), physical_manifest_sha256=sealed.file_sha(physical_case / 'ggx-sequence.json'),
        source_sha256=sealed.file_sha(Path(__file__)), checks=domain.CHECKS, payload_integrity_checks=sealed.CHECKS,
        gpu_executed=False, compiler_executed=False, raw_perceptual_hypothesis=True))
    print(json.dumps(dict(cases=paths, checks=domain.CHECKS, payload_integrity_checks=sealed.CHECKS), indent=2))


def validate(case):
    manifest = json.loads((case / 'ggx-sequence.json').read_bytes())
    domain.need(manifest['schema'] == domain.DEMOD_SCHEMA and manifest['code'] == manifest['physical_roughness_code'] == 80,
                'strictly declared new physical r80 demod scenario')
    domain.need(manifest['guide_roughness_code'] in CODES and manifest['guide_roughness'] > 0. and not manifest['zero_roughness_used'], 'both measured guide codes are strictly positive')
    domain.need(sealed.file_sha(Path(__file__)) == manifest['roughness_guide_source_sha256'] and sealed.file_sha(Path(domain.__file__)) == manifest['derived_source_sha256'], 'exact frozen domain and guide adapter sources')
    for source, expected in manifest['source_files'].items():
        domain.need(sealed.file_sha(Path(source)) == expected, 'source/math/camera provenance remains immutable')
    physical_case = Path(manifest['physical_case'])
    common_case = Path(manifest['common_demod_case'])
    domain.need(sealed.file_sha(physical_case / 'ggx-sequence.json') == manifest['physical_manifest_sha256'] and sealed.file_sha(common_case / 'ggx-sequence.json') == manifest['common_demod_manifest_sha256'], 'same frozen physical and once-demodulated parents')
    common = json.loads((common_case / 'ggx-sequence.json').read_bytes())
    domain.need(len(manifest['frames']) == manifest['submitted_frames'] == 64 and len(manifest['views']) == 1, 'complete continuous single native view')
    view = Path(next(iter(manifest['views'].values())))
    domain.need(sealed.file_sha(view / 'native-replay.txt') == manifest['native_replay']['sha256'], 'camera/jitter/reset table exact')
    for index, frame in enumerate(manifest['frames']):
        old = common['frames'][index]
        domain.need(frame['frame'] == index + 2 and frame['directory'] == old['directory'], 'same64 physical samples')
        data = domain.load_frame(case, manifest, frame, NAMES + ('reference_spec_a', 'reference_spec_b', 'reference_diff'))
        domain.need(all(np.isfinite(value).all() for value in data.values()) and np.all(data['spec'][..., 3] > 0.), 'all actual inputs finite, real ray-distance alpha positive')
        normal = sealed.load(physical_case / 'dataset' / frame['directory'], old['payloads']['normals'])
        domain.need(np.array_equal(data['normals'] & ~MASK, normal & ~MASK) and np.all(((data['normals'] & MASK) >> 20) == manifest['guide_roughness_code']), 'exact declared B-only word change')
        for name in NAMES:
            domain.need(sealed.file_sha(view / frame['directory'] / (name + '.bin')) == frame['payloads'][name]['sha256'], 'actual native input bytes match manifest')
            if name != 'normals':
                domain.need(frame['payloads'][name] == old['payloads'][name], 'all other native inputs identical across both candidates')
        for name, payload in frame['payloads'].items():
            if name != 'normals':
                domain.need(payload == old['payloads'][name], 'both independent references and every geometry/motion/ghost field unchanged')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--physical-case', type=Path, default=native_common.TASK / 'ggx-lowrough-v6/r80')
    parser.add_argument('--output', type=Path, default=native_common.TASK / 'ggx-lowrough-guides-v6')
    args = parser.parse_args()
    prepare(args.physical_case, args.output)
