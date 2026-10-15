"""Fixed-parameter CPU feasibility on the sealed15e world oracle, BEFORE RR.

Reference/outlier/reveal masks are metrics only, never conditioner inputs.
No shader compilation or GPU/provider execution is performed by this script.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

import numpy as np

from fsrd_nrd_rr_workarounds import Parameters, condition

CHECKS = 0


def require(value, reason):
    global CHECKS
    CHECKS += 1
    if not value:
        raise AssertionError(reason)


def digest(value):
    return hashlib.sha256(value).hexdigest()


def load(directory, info):
    name = Path(info['file'])
    require(name.name == str(name), 'sealed basename only')
    value = (directory/name).read_bytes()
    require(len(value) == info['bytes'] and digest(value) == info['sha256'], 'sealed immutable payload length/hash')
    data = np.frombuffer(value, dtype=np.dtype(info['dtype'])).reshape(info['shape'])
    return data


def metric(value, reference, mask):
    rgb = value[..., :3].astype(np.float64)
    reference = reference.astype(np.float64)
    error = rgb-reference
    count = int(np.count_nonzero(mask))
    if not count:
        return dict(pixels=0, squared_rgb_error=0.0, squared_opponent_chroma_error=0.0,
                    signed_rgb_error_sum=[0.0, 0.0, 0.0])
    co_cg = np.stack(((error[..., 0]-error[..., 2])*.5,
                     (-error[..., 0]+2*error[..., 1]-error[..., 2])*.25), axis=-1)
    return dict(pixels=count, squared_rgb_error=float(np.sum(error[mask]**2)),
                squared_opponent_chroma_error=float(np.sum(co_cg[mask]**2)),
                signed_rgb_error_sum=np.sum(error[mask], axis=0).tolist())


def aggregate(rows):
    output = {}
    for candidate in ('raw', 'one-history', 'two-histories'):
        output[candidate] = {}
        for signal in ('spec', 'diff'):
            values = [row['signals'][signal][candidate] for row in rows]
            regions = {}
            for region in ('interior', 'newly_revealed', 'reveal_age1to8', 'reveal_age9to16'):
                masks = [value[region] for value in values]
                pixels = sum(mask['pixels'] for mask in masks)
                if not pixels:
                    regions[region] = dict(pixels=0)
                    continue
                rgb_error = sum(mask['squared_rgb_error'] for mask in masks)
                chroma_error = sum(mask['squared_opponent_chroma_error'] for mask in masks)
                regions[region] = dict(pixels=pixels, rgb_rmse=float(np.sqrt(rgb_error/(3*pixels))),
                    opponent_chroma_rmse=float(np.sqrt(chroma_error/(2*pixels))),
                    rgb_bias=(np.sum([mask['signed_rgb_error_sum'] for mask in masks], axis=0)/pixels).tolist())
            counts = ('admitted', 'outliers', 'admitted_known_outliers', 'admitted_other_samples', 'admitted_newly_revealed')
            output[candidate][signal] = dict(regions=regions,
                **{count:sum(value['counts'][count] for value in values) for count in counts})
    return output


def run(root, destination):
    manifest_bytes = (root/'sequence.json').read_bytes()
    manifest = json.loads(manifest_bytes)
    require(manifest['schema'] == 'fsrd-world-surface-motion-quality-v1', 'independent world oracle schema')
    require(len(manifest['frames']) == manifest['submitted_frames'] == 64, 'complete prescribed64-frame history')
    parameters = Parameters()  # Fixed before loading truth. No threshold search.
    histories = {'spec': [], 'diff': []}
    rows = []
    for item in manifest['frames']:
        directory = root/item['directory']
        names = ('spec', 'diff', 'depth', 'normals', 'motion_surface', 'reference_spec', 'reference_diff',
                 'outliers_spec', 'outliers_diff', 'reveal_age', 'interior')
        data = {name:load(directory, item['payloads'][name]) for name in names}
        interior = data['interior'] != 0
        ages = data['reveal_age']
        masks = dict(interior=interior, newly_revealed=interior & (ages == 0),
                     reveal_age1to8=interior & (ages >= 1) & (ages <= 8),
                     reveal_age9to16=interior & (ages >= 9) & (ages <= 16))
        row = dict(frame=item['frame'], signals={})
        if item['reset']:
            histories = {'spec': [], 'diff': []}
        for signal in ('spec', 'diff'):
            source = data[signal]
            # Only these four current/raw history resources reach the filter.
            current = dict(signal=source, depth=data['depth'], normals=data['normals'], motion=data['motion_surface'])
            history = histories[signal]
            previous = history[-1] if history else None
            older = history[-2] if len(history) > 1 else None
            outputs = {'raw':(source, np.zeros(source.shape, dtype='<u4'))}
            outputs['one-history'] = condition(current, previous, older, mode=1, parameters=parameters)
            outputs['two-histories'] = condition(current, previous, older, mode=2, parameters=parameters)
            reference = data['reference_'+signal]
            outliers = data['outliers_'+signal] != 0
            row['signals'][signal] = {}
            for name, (value, gate) in outputs.items():
                require(np.array_equal(value[..., 3].copy().view('<u2'), source[..., 3].copy().view('<u2')),
                        'entire finite positive hit-alpha input remains bit exact')
                require(np.all(np.isfinite(value)) and np.all(value[..., :3] >= 0), 'finite nonnegative conditioned RGB')
                admitted = ((gate[..., 0] & 64) != 0) & interior
                stats = {region:metric(value, reference, mask) for region, mask in masks.items()}
                stats['counts'] = dict(admitted=int(admitted.sum()), outliers=int((outliers & interior).sum()),
                    admitted_known_outliers=int((admitted & outliers).sum()),
                    admitted_other_samples=int((admitted & ~outliers).sum()),
                    admitted_newly_revealed=int((admitted & (ages == 0)).sum()))
                row['signals'][signal][name] = stats
            require(digest(source.tobytes()) == item['payloads'][signal]['sha256'], 'source signals never modified')
            histories[signal] = (history+[current])[-2:]
        rows.append(row)
    result = dict(schema='fsrd-pre-rr-chroma-feasibility-v1', checks=CHECKS,
        input_manifest_sha256=digest(manifest_bytes), parameters=asdict(parameters),
        cpu_model_sha256=digest(Path(__file__).with_name('fsrd_nrd_rr_workarounds.py').read_bytes()),
        gpu_executed=False, compiler_executed=False, signed_provider_executed=False,
        metrics_scope='CPU-conditioned noisy input BEFORE RR, not final RR quality or game imagery',
        no_reference_or_annotation_in_admission=True, fixed_candidates_without_parameter_search=True,
        summaries=aggregate(rows), frames=rows)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k != 'frames'}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(args.inputs, args.output)
