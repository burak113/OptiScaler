"""Bounded, read-only evidence for the native Recon -> AMD signal contract.

Numeric A categories do not identify rays: zero is not labelled 'miss', and a
negative marker is the AMD inactive convention, not an environment-hit oracle.
Only published Recon u0/u1 snapshots with exact title/root hashes are loaded.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
from pathlib import Path

import numpy as np

CAPTURES = ('3a443dbc5490c7708e2304aeb914d572',
            'fbb771d08b5e48b98f4954d45799f455',
            '8428f1ccbcc37b3d2f888d82890fb29d',
            '65a96b75fcf97c51322e80b81c6007a1')
RECON = 'ec37e0d8a2672d515a807ce0712737c1b186adfebf5530dd260d2b624877771e'
ROOT = 'bcb5f3454f596992f694f54ddb53e0f6b0ac7a9d976e8a49d1fc9ddab6a6eb70'
SCHEMA = 'fsrd-nrd-rr-native-signal-contract-v1'


def require(value, message):
    if not value:
        raise AssertionError(message)


def sha(value):
    return hashlib.sha256(value).hexdigest()


def alpha_statistics(rgba):
    """Preserve half words while separately reporting numeric categories."""
    rgba = np.asarray(rgba)
    require(rgba.dtype == np.dtype('<f2') and rgba.ndim == 3 and rgba.shape[-1] == 4,
            'original little-endian RGBA16F signal required')
    alpha = rgba[..., 3].astype(np.float32)
    words = rgba[..., 3].copy().view('<u2')
    rgb = rgba[..., :3].astype(np.float32)
    finite = np.isfinite(alpha)
    positive = finite & (alpha > 0)
    zero = finite & (alpha == 0)
    negative = finite & (alpha < 0)
    energy = np.any(rgb > 0, axis=-1)
    valid = alpha[finite]
    result = dict(texels=int(alpha.size), finite=int(finite.sum()),
                  positive=int(positive.sum()), negative=int(negative.sum()),
                  positive_zero=int((words == 0).sum()), negative_zero=int((words == 0x8000).sum()),
                  half_max65504=int((alpha == 65504).sum()), nonfinite=int((~finite).sum()),
                  zero_with_nonzero_rgb=int((zero & energy).sum()),
                  negative_with_nonzero_rgb=int((negative & energy).sum()),
                  positive_with_nonzero_rgb=int((positive & energy).sum()),
                  rgb_nonfinite_components=int((~np.isfinite(rgb)).sum()),
                  rgb_negative_components=int((rgb < 0).sum()))
    result['alpha_quantiles'] = dict(zip(('min', 'p01', 'p50', 'p90', 'p99', 'p999', 'max'),
        map(float, np.quantile(valid, (0, .01, .5, .9, .99, .999, 1))))) if valid.size else None
    result['numeric_partition_complete'] = int(positive.sum()+zero.sum()+negative.sum()+(~finite).sum()) == alpha.size
    return result


def _load_published(directory, image):
    relative = Path(image['file'])
    require(not relative.is_absolute() and '..' not in relative.parts, 'published relative payload path')
    data = (directory/relative).read_bytes()
    require(len(data) == image['bytes'] and sha(data) == image['sha256'], 'published payload bytes/hash')
    width, height = image['extent']
    require(image['dxgi_format'] == 10 and len(data) == width*height*8, 'unmodified RGBA16F payload extent')
    return np.frombuffer(data, dtype='<f2').reshape(height, width, 4)


def audit_capture(directory):
    # One manifest is live at a time. No payload before publication validation.
    path = directory/'capture.json'
    data = path.read_bytes()
    manifest_hash = sha(data)
    manifest_bytes = len(data)
    manifest = json.loads(data)
    del data
    published = manifest.get('manifest_published_frames', 0)
    require(isinstance(published, int) and published >= 0, 'explicit publication boundary')
    require(manifest.get('payload_ordinal_unit') == 'command_list_recording', 'ordinal unit is not a temporal frame')
    result = dict(capture=directory.name, manifest_sha256=manifest_hash, manifest_bytes=manifest_bytes,
                  published_recordings=published, complete=manifest.get('complete'),
                  temporal_sequence_proved=False, signals=[],
                  source_units_proved=False, secondary_miss_marker_proved=False,
                  normal_space_proved=False, native_consumer_encoding_flag_proved=False)
    passes = {(cl['id'], p['local_pass']): p for cl in manifest.get('command_lists', []) for p in cl.get('passes', [])
              if p.get('kind') == 'Dispatch' and p.get('pso', {}).get('shader_hashes', {}).get('CS') == RECON}
    for frame in manifest.get('frames', []):
        ordinal = frame['ordinal']
        if ordinal >= published:
            continue
        require(ordinal >= 0 and frame.get('cpu_snapshot_immutable') and frame.get('gpu_submission_verified'),
                'only immutable verified published recording')
        list_id = frame['list_id']
        for (pass_list, local_pass), dispatch in passes.items():
            if pass_list != list_id:
                continue
            require(dispatch.get('root_signature_sha256') == ROOT, 'attested canonical native root layout')
            views = sorted((v for v in dispatch['writes'] if v.get('root_parameter') == 5 and v.get('kind') == 1),
                           key=lambda v: v['descriptor_index'])
            require(len(views) == 5 and [v['descriptor_index']-views[0]['descriptor_index'] for v in views] == list(range(5)),
                    'complete native root5 contiguous UAV table, exact u0/u1 offsets')
            # Full Recon DXIL attestation proves writes to u0/u1. Extra bound UAVs
            # are deliberately NOT treated as writes by this analysis.
            for slot, name in ((0, 'spec'), (1, 'diff')):
                view = views[slot]
                key = f'p{local_pass}_r{view["resource"]}s0'
                images = [i for i in frame['images'] if i['name'] == key]
                if not images:
                    result['signals'].append(dict(signal=name, published=False, local_pass=local_pass,
                                                  resource=view['resource'], reason='exact Recon u0/u1 image absent'))
                    continue
                require(len(images) == 1 and view['subresource'] == 0 and view['view_format'] == 10,
                        'one exact unaliased Recon output image')
                image = images[0]
                statistics = alpha_statistics(_load_published(directory, image))
                result['signals'].append(dict(signal=name, ordinal=ordinal, published=True,
                    local_pass=local_pass, resource=view['resource'], descriptor_slot=slot,
                    shader_sha256=RECON, file=image['file'], payload_sha256=image['sha256'],
                    extent=image['extent'], statistics=statistics))
    del manifest
    gc.collect()
    return result


def audit(root, output):
    results = [audit_capture(root/name) for name in CAPTURES]
    document = dict(schema=SCHEMA, captures=results,
        interpretation='numeric A statistics only; native Recon is a weighted source metric, not proof of world units or active/miss semantics',
        published_recordings_are_temporal_frames=False,
        amd_sample='secondary miss retains finite65504; actual secondary hit stores world distance; negative public-API A means inactive',
        policy='preserve every finite native A (including zero/negative); nonfinite fallback+0; no guessed miss conversion',
        gpu_executed=False, compiler_executed=False)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=2)+'\n', encoding='utf-8')
    return document


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.root, args.output)
    for capture in result['captures']:
        print(capture['capture'], 'published=', capture['published_recordings'])
        for signal in capture['signals']:
            print(signal['signal'], signal.get('statistics', signal.get('reason')))
