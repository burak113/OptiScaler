"""Deterministic unequal-allocation native inputs and CPU expected output.

All support/authority certificates in this generator are synthetic test inputs.
They are deliberately not inferred from native alpha, noisy RGB or material IDs.
"""
from dataclasses import asdict, replace
from pathlib import Path
import argparse
import hashlib
import json
import sys

import numpy as np

from packed_model import Config, Identity, Evidence, Layout, constants, pack, process


def make_case(name='log_d16'):
    rng = np.random.default_rng(20261021)
    active = (13, 9)
    identity = Identity(render_width=31, render_height=29, crop_x=3, crop_y=5)
    if name.endswith('s256'):
        identity = replace(identity, lobe=1, provider_scale=256)
    config = Config(enabled=True, acknowledge_rejected_research=True,
                    representation=int(name.startswith('linear')))
    evidence = Evidence(identity, 1, 1, 1, 1, 3, 20261021)
    dims = ((19, 13), (17, 11), (23, 15))
    arrays = []
    alpha = np.array([0, 0x8000, 0x7e11, 0xfc01, 0x7c01, 0x3c00], np.uint16)
    for width, height in dims:
        a = np.ones((height, width, 4), np.float16)
        a[..., :3] = rng.uniform(.2, .4, (height, width, 1))*np.array([1.05, 1., .96])
        a.view(np.uint16)[..., 3] = np.resize(alpha, (height, width))
        arrays.append(a)
    source, raw, selected = arrays
    selected[:active[1], :active[0]] = raw[:active[1], :active[0]]
    source[:active[1], :active[0], :3] = raw[:active[1], :active[0], :3]*np.array([.9, 1., 1.12], np.float16)
    # Protected RGB one-ULP change, alpha-only mutation, and signed-zero alpha.
    selected.view(np.uint16)[1, 2, 0] ^= np.uint16(1)
    selected.view(np.uint16)[2, 3, 3] ^= np.uint16(1)
    selected.view(np.uint16)[2, 4, 3] = np.uint16(0x8000)
    raw.view(np.uint16)[2, 4, 3] = np.uint16(0)
    depth = np.full((14, 21), 10, np.float32)
    normal = np.full((16, 25), 512 | (512 << 10) | (600 << 20), np.uint32)
    authority = np.ones((17, 27), np.uint32)
    support = np.ones((18, 29), np.uint32)
    authority[3, 4] = 0
    authority[3, 5] = 2  # reserved is unknown, never true by nonzero cast
    support[4, 5] = 0
    support[4, 6] = 0xffffffff
    reset = resized = False
    if name == 'off':
        config = replace(config, enabled=False)
    elif name == 'unacknowledged':
        config = replace(config, acknowledge_rejected_research=False)
    elif name == 'strength0':
        config = replace(config, strength=0.)
    elif name == 'reset':
        reset = True
    elif name == 'resize':
        resized = True
    elif name == 'unknown_authority':
        evidence = replace(evidence, authority_kind=0)
    elif name == 'unknown_support':
        evidence = replace(evidence, support_kind=0)
    elif name == 'post_scale_source':
        evidence = replace(evidence, source_stage=0)
    elif name == 'stale_recording':
        evidence = replace(evidence, identity=replace(identity, recording=identity.recording-1))
    elif name == 'invalid_samples':
        source[1, 1, 0] = np.nan
        source[2, 1, 1] = np.inf
        source[3, 1, 2] = -.1
        raw[1, 7, 0] = np.nan
        raw[2, 7, 1] = np.inf
        selected[1:3, 7] = raw[1:3, 7]
        depth[5, :4] = np.array([np.nan, np.inf, 0., -0.], np.float32)
    elif name == 'signed_depth':
        depth[:, :6] *= -1
    elif name == 'all_unknown_pixels':
        authority.fill(0xffffffff)
        support.fill(0)
    layouts = tuple(Layout(w, h, pitch, offset, offset+pitch*h+512)
                    for (w, h), pitch, offset in zip(dims, (256, 512, 768), (512, 1024, 1536)))
    layouts += (layouts[2],)
    output, diagnostic, decision = process(source, raw, selected, depth, normal, authority, support,
        config=config, identity=identity, evidence=evidence, reset=reset, resized=resized)
    # Non-ready cases are HOST no-dispatch checks. A separate shader fail-safe
    # fixture records Control.x=0 only to check byte transport defensively.
    cb = bytearray(constants(config, identity, layouts))
    if decision != 'Ready':
        cb[48:52] = (0).to_bytes(4, 'little')
    packed = {label: pack(value, layout) for label, value, layout in
              zip(('source', 'raw', 'selected'), (source, raw, selected), layouts)}
    packed['initial_output'] = packed['selected'].copy()
    packed['expected_output'] = pack(output, layouts[3])
    return dict(name=name, config=config, identity=identity, evidence=evidence, reset=reset, resized=resized,
                layouts=layouts, source=source, raw=raw, selected=selected, depth=depth, normal=normal,
                authority=authority, support=support, output=output, diagnostic=diagnostic,
                decision=decision, constants=bytes(cb), packed=packed)


CASES = ('log_d16', 'log_s256', 'linear_d16', 'off', 'unacknowledged', 'strength0',
         'reset', 'resize', 'unknown_authority', 'unknown_support', 'post_scale_source',
         'stale_recording', 'invalid_samples', 'signed_depth', 'all_unknown_pixels')


def write_fixtures(out):
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for name in CASES:
        c = make_case(name)
        directory = out/name
        directory.mkdir(exist_ok=True)
        payloads = {key+'.bin': c[key].tobytes() for key in
                    ('source', 'raw', 'selected', 'depth', 'normal', 'authority', 'support', 'output', 'diagnostic')}
        # Preserve both texture-layout and packed-buffer representations.
        for key, value in c['packed'].items():
            payloads['packed_'+key+'.bin'] = value.tobytes()
        payloads['constants.bin'] = c['constants']
        payloads['constant_upload_256.bin'] = c['constants']+bytes(256-len(c['constants']))
        for filename, data in payloads.items():
            (directory/filename).write_bytes(data)
        sw = c['selected'].view(np.uint16)
        changed = np.any(c['output'] != sw, axis=-1)
        row = dict(name=name, decision=c['decision'], host_dispatch_expected=c['decision']=='Ready',
                   changed_pixels=int(changed.sum()), config=asdict(c['config']), identity=asdict(c['identity']),
                   evidence=asdict(c['evidence']), reset=c['reset'], resized=c['resized'],
                   layouts=[asdict(x) for x in c['layouts']],
                   arrays={key:dict(shape=list(c[key].shape), dtype=c[key].dtype.str)
                           for key in ('source','raw','selected','depth','normal','authority','support','output','diagnostic')},
                   files={filename:hashlib.sha256(data).hexdigest() for filename,data in sorted(payloads.items())})
        (directory/'case.json').write_text(json.dumps(row, indent=2)+'\n', encoding='utf-8')
        rows.append(row)
    manifest = dict(schema='astra10-native-fixtures-v1', seed=20261021,
        compiler_or_gpu_executed=False, quality_accepted=False,
        support='Synthetic certificate; no native support producer is implied.',
        constants_bytes=112, constant_allocation_bytes=256,
        expected_rgb_tolerance='at most 1 half ULP on eligible finite RGB; all protected/alpha/padding exact',
        cases=rows)
    (out/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')
    return manifest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    manifest = write_fixtures(args.output)
    print(json.dumps(dict(cases=len(manifest['cases']), changed_pixels={c['name']:c['changed_pixels'] for c in manifest['cases']},
                         gpu_executed=False, quality_accepted=False), indent=2))


if __name__ == '__main__':
    main()
