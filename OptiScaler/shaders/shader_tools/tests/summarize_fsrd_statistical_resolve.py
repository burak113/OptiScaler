"""Compact authenticated evidence from completed post-RR AMD studies."""
from pathlib import Path
import argparse, hashlib, json, re
import numpy as np
from fsrd_alpha_common import save_json
from fsrd_quality_contours import island_contours,contour_gate


def summarize(directory):
    root=Path(directory);report=json.loads((root/'results.json').read_text())
    if report['status']!='completed': raise ValueError('Incomplete study')
    if hashlib.sha256((root/'field_shader/FSRDInputConvAdditive_Shader.cso').read_bytes()).hexdigest()!=report['field_shader_sha256']:
        raise ValueError('Changed allocation shader')
    for name,digest in report['source_sha256'].items():
        if hashlib.sha256((root/'source_snapshot'/name).read_bytes()).hexdigest()!=digest:
            raise ValueError('Changed source snapshot: '+name)
    rows=[];native_contexts=[]
    expected=set(report.get('comparison_models',['legacy','additive','allocator','guide_only','same_frame_rr','independent_rr']))
    for scene in report['results']:
        if {m['model'] for m in scene['models']}!=expected: raise ValueError('Missing comparison')
        folder=root/scene['scene'];base_identity=None
        for manifest in sorted(folder.glob('*/amd_context_identity.json')):
            identity=json.loads(manifest.read_text())
            context=manifest.parent
            controls=(context/'dispatch_controls.bin').read_bytes()
            if len(controls)!=184*report['frames'] or hashlib.sha256(controls).hexdigest()!=identity['applied_dispatch_sha256']:
                raise ValueError('Invalid native applied controls: '+str(context))
            log=(context/'runner.log').read_text()
            counts=re.search(r'dispatches=(\d+) validation_errors=(\d+) validation_warnings=(\d+) sdk_errors=(\d+) sdk_warnings=(\d+)',log)
            if not counts or 'debug_layer=1' not in log or any(map(int,counts.groups()[1:])) or int(counts[1])!=report['frames']:
                raise ValueError('Invalid native validation: '+str(context))
            native_contexts.append(dict(scene=scene['scene'],context=context.name,dispatches=int(counts[1]),
                manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
                log_sha256=hashlib.sha256((context/'runner.log').read_bytes()).hexdigest()))
        if len(list(folder.glob('*/amd_context_identity.json')))!=report['null_repeats']+6:
            raise ValueError('Missing AMD context')
        sequence=folder/'sequences.npz'
        sequence_digest=hashlib.sha256(sequence.read_bytes()).hexdigest()
        with np.load(sequence) as saved:
            contours={m:island_contours(saved[m],saved['truth']) for m in expected} if scene['scene'].startswith('fake_') else {}
            late_noise={m:{str(count):float(np.std((saved[m]-saved['truth'])[-count:,5:-5,5:-5],axis=0).mean())
                          for count in (4,8)} for m in expected}
        for name in ['legacy']+[f'null_{i}' for i in range(1,report['null_repeats'])]:
            identity=json.loads((folder/name/'amd_context_identity.json').read_text())
            controls=(folder/name/'dispatch_controls.bin').read_bytes()
            if hashlib.sha256(controls).hexdigest()!=identity['applied_dispatch_sha256']:
                raise ValueError('Changed applied controls')
            identity.pop('output_sha256')
            if base_identity is None: base_identity=identity
            elif identity!=base_identity: raise ValueError('Null mismatch')
        for model in scene['models']:
            fit=model['fit'] or []
            extra=contour_gate(contours[model['model']],contours['legacy'],*report['size']) if contours else None
            rows.append(dict(scene=scene['scene'],model=model['model'],metrics=model['metrics'],
                activity=model['activity'],acceptance=model['acceptance'],
                sequences_sha256=sequence_digest,supplemental_final_window_temporal_error_std=late_noise[model['model']],
                full_roi_contour=contours.get(model['model']),additional_contour_gate=extra,
                effective_success_with_contour_gate=bool(model['acceptance'] and model['acceptance']['effective_success'] and (extra is None or extra['passed'])),
                eligible_measured_success=bool(model['acceptance'] and model['acceptance'].get('eligible_for_promotion', True)
                    and model['acceptance']['effective_success'] and (extra is None or extra['passed'])),
                frame_activity=[f['activity'] for f in fit],
                mean_confidence_rgb=np.mean([f['confidence_rgb'] for f in fit],axis=0).tolist() if fit else None,
                mean_rejection={key:float(np.mean([f['reason_fraction'][key] for f in fit])) for key in map(str,range(10))} if fit else None))
    first=root/report['results'][0]['scene']/'legacy/runner.log'
    hardware=[line for line in first.read_text().splitlines() if line.startswith(('adapter=','provider=','dispatches='))]
    return dict(size=report['size'],frames=report['frames'],seed=report['seed'],hardware=hardware,
        result_sha256=hashlib.sha256((root/'results.json').read_bytes()).hexdigest(),
        source_sha256=report['source_sha256'],production_shaders=report['production_shaders'],
        field_shader_sha256=report['field_shader_sha256'],
        null_contexts={s['scene']:s['null_contexts'] for s in report['results']},
        native_contexts=native_contexts,amd_dispatches=sum(c['dispatches'] for c in native_contexts),
        results=rows,limitations=report['limitations'],quality_accepted=False)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--studies',type=Path,nargs='+',required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();studies=[summarize(d) for d in a.studies]
    sources=('summarize_fsrd_statistical_resolve.py','fsrd_quality_contours.py')
    save_json(a.output,dict(schema='post-rr-resolve-evidence-v1',studies=studies,quality_accepted=False,
        post_assessment_source_sha256={n:hashlib.sha256(Path(__file__).with_name(n).read_bytes()).hexdigest() for n in sources}))
    for study in studies:
        print(study['size'],'comparisons',len(study['results']),flush=True)


if __name__=='__main__': main()
