"""Replay saved composition inputs through the production diagnostic views.

This is an offline D3D12 replay, not an in-game capture hook. The fixture tests
write the same input bundle this command reads. Arrays are linear, render-sized,
pre-upscaler data, never screenshots or tone-mapped display colours.

python fsrd_stage_probe.py --input inputs.npz --output F:/.../probe
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

import numpy as np
import run_fsrd_gpu_tests as t

INPUTS = ('specular', 'specular_albedo', 'diffuse', 'diffuse_albedo',
          'skip', 'normal', 'reference', 'depth')
STAGES = {
    'seed': 'DETAIL_SEED',
    'reference': 'DETAIL_REFERENCE',
    'reconstructed': 'RECONSTRUCTED_COLOR',
    'box_anchor': 'DETAIL_BOX_ANCHORED',
    'anchor': 'DETAIL_ANCHORED',
    'weights': 'HANDOVER_WEIGHTS',
    'confidence': 'DETAIL_CONFIDENCE',
    'limits': 'HANDOVER_LIMITS',
    'before_clamp': 'COMPOSITION_BEFORE_CLAMP',
    'composition': 'COMPOSITION_FINAL',
    'skip': 'SKIP_SIGNAL',
    'eligibility': 'HANDOVER_ELIGIBILITY',
    'chroma_recovery': 'CHROMA_RECOVERY',
    'luma_recovery': 'LUMA_RECOVERY',
}


def save_inputs(path, values, inputs, provenance, **extras):
    metadata = {'schema': 1, 'constants': values, 'provenance': provenance,
                'formats': [10, 28, 10, 28, 10, 24, 10, 41]}
    encoded = np.frombuffer(json.dumps(metadata).encode('utf-8'), dtype=np.uint8)
    np.savez_compressed(path, metadata_utf8=encoded, **dict(zip(INPUTS, inputs)), **extras)


def load_inputs(path):
    with np.load(path, allow_pickle=False) as data:
        metadata = json.loads(data['metadata_utf8'].tobytes().decode('utf-8'))
        if metadata['schema'] != 1 or metadata['formats'] != [10, 28, 10, 28, 10, 24, 10, 41]:
            raise ValueError('Unsupported composition input schema or formats')
        values = metadata['constants']
        w, h = map(int, values['DstTexSize'][:2])
        if w <= 0 or h <= 0:
            raise ValueError('Empty logical extent')
        inputs = [data[name].copy() for name in INPUTS]
        for name, array in zip(INPUTS, inputs):
            expected = (h, w) if name == 'depth' else (h, w, 4)
            if array.shape != expected or not np.all(np.isfinite(array)):
                raise ValueError(f'{name}: expected finite {expected}, got {array.shape}')
        return values, inputs, metadata


def flags(name):
    source = (t.PRE/'FSRDOutputComp.hlsl').read_text(encoding='utf-8')
    match = re.search(r'#define FLAGS_DEBUG_'+STAGES[name]+r' \((\d+) << 17 \| FLAGS_DEBUG\)', source)
    if match is None:
        raise ValueError('Unmapped production debug mode: '+name)
    return (int(match[1]) << 17) | (1 << 16)


def dispatch(values, inputs, stage=None, directory=None):
    values = dict(values)
    # Preserve all signal flags, replace only the debug selection. No source blit.
    if int(values.get('Flags', 0)) & 3:
        raise ValueError('A source blit is not a composition capture')
    values['Flags'] = int(values.get('Flags', 0)) & ~(0xff << 16)
    if stage is not None:
        values['Flags'] |= flags(stage)
    size = tuple(map(int, values['DstTexSize'][:2]))
    return t.dispatch('FSRDOutputComp', values, inputs, [10], size,
                      directory=directory or t.PRE)[0]


def probe(values, inputs, out, provenance):
    out.mkdir(parents=True, exist_ok=True)
    start = len(t.timings)
    stages = {stage: dispatch(values, inputs, stage) for stage in STAGES}
    stages['normal'] = dispatch(values, inputs)
    np.savez_compressed(out/'stages.npz', **stages)
    manifest = {
        'provenance': provenance, 'constants': values,
        'shader_sha256': hashlib.sha256((t.PRE/'FSRDOutputComp_Shader.cso').read_bytes()).hexdigest(),
        'dispatches': t.timings[start:],
        'weights_rgb': ['structure permission', 'difference exceeds noise permission',
                        'correlation permission (1 - mix * agreement)'],
        'limits_rgb': ['box Anchor change fraction', 'colour Anchor change fraction',
                       'final supported-range change fraction'],
        'eligibility_rgb': ['selected handover material (original albedo evidence)', 'reference is not routed/invalid',
                            'linear Floor Recovery strength'],
        'limit_fraction': 'saturate(length(before-after) / max(length(before-reconstructed), 1e-6))',
        'chroma_recovery': 'saturate(0.5 + signed additional chromatic correction / max(RR luminance, 1e-3)); '
                           'neutral grey is zero; before the final supported-range clamp.',
        'luma_recovery': 'saturate(0.5 + signed additional luminance correction / max(RR luminance, 1e-3)); '
                         'neutral grey is zero; before the final supported-range clamp.',
        'limitations': 'No AMD model or upscaler execution. All stages replay exactly the same inputs. '
                        'Display views are live in-game, not a frozen capture. '
                        'Limits show bounded change fractions, not lost radiance or quality.',
    }
    (out/'probe.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return stages


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        parser.error('Use a new or empty output directory')
    values, inputs, metadata = load_inputs(args.input)
    args.output.mkdir(parents=True, exist_ok=True)
    t.OUT = args.output/'dispatches'
    t.OUT.mkdir()
    t.runner = t.OUT/'fsrd_gpu_runner.exe'
    t.build_runner()
    probe(values, inputs, args.output, metadata['provenance'])
    print(args.output/'probe.json')


if __name__ == '__main__':
    main()
