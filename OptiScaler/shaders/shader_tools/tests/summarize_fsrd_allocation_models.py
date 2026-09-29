"""Export compact, auditable evidence without changing the original experiment.

Original decisions are retained beside the assessor with island-only ring gates.
Elapsed research CPU time is deliberately excluded from performance claims.
"""
from pathlib import Path
import argparse
import hashlib
import json
import numpy as np
from fsrd_alpha_common import save_json
from probe_fsrd_allocation_models import SCENES, assess


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    source=args.input/'results.json'
    report=json.loads(source.read_text(encoding='utf-8'))
    models=('baseline','surface_overlap','lobes_overlap')
    expected={(scene,model) for scene in SCENES for model in models}
    actual=[(row['scene'],row['model']) for row in report['results']]
    if len(actual)!=len(expected) or set(actual)!=expected:
        raise ValueError('Expected the complete 11-scene overlapping-model matrix')
    for name,digest in report['source_sha256'].items():
        if hashlib.sha256((args.input/'source_snapshot'/name).read_bytes()).hexdigest()!=digest:
            raise ValueError('Execution source snapshot mismatch: '+name)
    baselines={row['scene']:row['metrics'] for row in report['results'] if row['model']=='baseline'}
    rows=[]
    for row in report['results']:
        metrics=dict(row['metrics'])
        identity_path=args.input/(row['scene']+'_'+row['model'])/'amd_input_identity.json'
        baseline_path=args.input/(row['scene']+'_baseline')/'amd_input_identity.json'
        identity=json.loads(identity_path.read_text())
        baseline_identity=json.loads(baseline_path.read_text())
        metrics['amd_input_sha256']=identity
        metrics['actual_signal_changed']=any(identity[f'input{i}.bin']!=baseline_identity[f'input{i}.bin'] for i in (5,6))
        if len(metrics['frame_rmse'])!=report['frames']:
            raise ValueError('Incomplete frame curve: '+row['scene'])
        item=dict(scene=row['scene'],model=row['model'],metrics=metrics,
                  original_acceptance=row['acceptance'],applicable_acceptance=None)
        if row['model']!='baseline':
            item['applicable_acceptance']=assess(row['scene'],metrics,baselines[row['scene']],report['frames'])
            field_path=args.input/(row['scene']+'_'+row['model'])/f"fit_{report['frames']-1}.npz"
            with np.load(field_path) as field:
                # These eleven synthetic fixtures share the five-pixel scoring inset.
                reason=field['reason'][5:-5,5:-5]
                item['last_field']=dict(sha256=hashlib.sha256(field_path.read_bytes()).hexdigest(),
                    roi_inset_pixels=5,activity_rgb=field['active'][5:-5,5:-5].mean((0,1)).tolist(),
                    reason_fraction_rgb={str(i):(reason==i).mean((0,1)).tolist() for i in range(9)})
        rows.append(item)
    evidence=dict(schema='fsrd-allocation-evidence-v1',status='complete_matrix_data',
        seed=report['seed'],frames=report['frames'],floor=report['floor'],
        variants=len(rows),amd_frames=report['frames']*len(rows),quality_accepted=False,
        original_report_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        execution_source_sha256=report['source_sha256'],
        assessor_sha256=hashlib.sha256(Path(__file__).with_name('probe_fsrd_allocation_models.py').read_bytes()).hexdigest(),
        field_shader_sha256=report['field_shader_sha256'],amd_dll_sha256=report['dll_sha256'],
        interpretation='Mandatory island bias/broad-tone failures prevent promotion. Original ring gates on non-island fixtures are retained as historical data; applicable_acceptance limits ring width to fake_* scenes without changing numerical tolerances. A no-op is never an effective success. Concurrent correctness jobs were used; elapsed times are not performance measurements.',
        results=rows)
    if args.output.exists(): raise ValueError('Refusing to overwrite evidence')
    save_json(args.output,evidence)
    print(json.dumps(dict(variants=len(rows),amd_frames=evidence['amd_frames'],quality_accepted=False)))


if __name__=='__main__': main()
