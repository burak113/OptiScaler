"""Attribute current alpha allocation on authenticated captured source RGB/guides.

This replays a cropped source with Floor OFF. It does not rerun the captured Joint
path and cannot establish game output quality; the captured RGB is not clean truth.
Replay color/guide uploads use the native harness's RGBA16F format. The live
capture instead reads the game's bound resource formats without this re-upload.
"""
from pathlib import Path
import argparse,hashlib,json,shutil
import numpy as np
from fsrd_alpha_common import GPUWorker,save_json
from fsrd_additive_diagnostics import build_journal,capture_pair,summarize
from probe_fsrd_additive_split import fixture
from fsrd_allocation_models import estimate


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--capture',type=Path,required=True)
    p.add_argument('--metadata',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args(); output=args.output.resolve()
    if output.exists() and any(output.iterdir()): raise ValueError('Use a fresh output directory')
    output.mkdir(parents=True,exist_ok=True)
    snapshot=output/'source_snapshot'; snapshot.mkdir()
    for name in ('probe_fsrd_captured_allocation.py','fsrd_allocation_models.py','fsrd_additive_diagnostics.py'):
        shutil.copy2(Path(__file__).with_name(name),snapshot/name)
    data=fixture('recorded_island',4,0,args.capture,args.metadata)
    meta=json.loads(args.metadata.read_text())
    with np.load(args.capture) as f: raw=f['raw_rgba'].copy()
    raw_identity=next(i for i in meta['images'] if i['name']=='raw_rgba')
    if hashlib.sha256(raw.astype('<f4').tobytes()).hexdigest()!=raw_identity['sha256']:
        raise ValueError('Captured RGB/metadata hash mismatch')
    dirs=build_journal(output)
    overrides=dict(data['overrides'],Flags=(1<<1)|(1<<5)|data['extra_flags'])
    with GPUWorker(output):
        report,fields,packed=capture_pair(output/'gpu_capture',dirs,raw,data['diff'],data['spec'],
            depth=data['depth'],normals=data['normals'],roughness=data['roughness'],
            overrides=overrides,resources=data['resources'])
    # The small upper-left island ROI is the same historical scored region.
    report['island_roi']=[summarize(j,data['region']) for j in fields]
    report['actual_roi_changed_rgb']=[(packed[0][i][...,:3][data['region']]!=
        packed[1][i][...,:3][data['region']]).mean(0).tolist() for i in range(8)]
    report['source_metadata_sha256']=hashlib.sha256(args.metadata.read_bytes()).hexdigest()
    report['source_sha256']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in snapshot.iterdir()}
    report['limitations']=__doc__
    report['model_research']={}
    for mode in ('surface','lobes','surface_overlap','lobes_overlap'):
        shares,active,diag=estimate(raw,data['diff'],data['spec'],data['depth'],data['normals'],data['roughness'],mode)
        np.savez_compressed(output/(mode+'_field.npz'),p=shares,eligible=active,**diag)
        report['model_research'][mode]=dict(eligible_fraction_rgb=active[data['region']].mean(0).tolist(),
            reason_fractions={str(i):(diag['reason'][data['region']]==i).mean(0).tolist() for i in range(9)})
    save_json(output/'results.json',report)
    print(json.dumps(dict(island_roi=report['island_roi'],model_research=report['model_research']),indent=2))


if __name__=='__main__': main()
