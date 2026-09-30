from pathlib import Path
import json,hashlib
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
r=read(HERE/'results.json');freeze=read(HERE/'pre_score_freeze.json');assert all(sha(p)==s for p,s in freeze['sources'].items())
checks=[]
for row in r['saved_native_rows']:
    E=ROOT/'tools_tmp'/('native_continuous_harmonic_fresh_retry_20260930' if row['scene']=='material' else 'native_continuous_harmonic_remaining_20260930')/'evidence'
    original=next(x for x in read(E/'results.json')['rows'] if x['scene']==row['scene'])
    for name,variant in original['variants'].items():
        for window,m in variant['metrics'].items():
            now=row['variants'][name][window]
            for key in ('score','absolute_gain_min','absolute_gain_mean','absolute_gain_max','absolute_phase_max','absolute_gain_failing_frames','absolute_phase_failing_frames','per_frame_absolute_detail_pass','relative_gate'):
                assert now[key]==m[key],(row['scene'],name,window,key)
            assert now['actual_STD_ratio_to_control']==m['actual_STD_ratio_to_native_baseline']
    checks.append({'scene':row['scene'],'original_six_variants_all_four_windows_score_absolute_relative_and_STD_bitexact':True,'original_report_sha256':sha(E/'results.json')})
(HERE/'original_control_consistency.json').write_text(json.dumps({'status':'passed','rows':checks,'results_sha256':sha(HERE/'results.json')},indent=2)+'\n')
notes={'status':'complete_frozen','quality_accepted':False,'model_and_rules_unchanged_after_freeze':True,
       'preparation_issue':'A python -c shell quoting SyntaxError occurred before writing adversary_generator.py or any score. Explicit prepare.py AST derivation replaced that shell text; original constructors/noise/seed retained.',
       'source_stage':'13 authenticated families plus22 frozen adversaries, source-only target and same unchanged harmonic P proxy. Actual matching native stage6 only, posthoc and no new RR/GPU.',
       'source_invalid_qualification':'Source proxy safe application rejects an invalid raw baseline. Signed/overflow adversaries retain safe_error and target invalid frames; unsafe proxy score/relative counts are comparisons only, not radiance acceptance. Metrics can score finite invalid radiance outside the5px ROI; whole-image invalid fractions remain reported.',
       'safe_errors':[{'scene':x['scene'],'error':x['result']['safe_error']} for x in r['adversaries'] if x['result']['safe_error']],
       'mandatory_limits':'Full/mature mean-pixel temporalSTD versus mean temporal variance are separate. All full absolute native detail failures remain; current-uniform shift cannot fix nonDC startup/dense/weak/phase. TargetSE is plug-in nominal only.',
       'supplementary_checks':'Executed only after frozen main results, fixed module, no scores/thresholds changed. Quiet noise decrease nominal example; slow trueDC drift lag and spatially shared artifact79cuts/currenttargetexact counterexamples preserved.',
       'no_game_or_native_claim':True}
(HERE/'execution_notes.json').write_text(json.dumps(notes,indent=2)+'\n')
files=[{'path':p.name,'bytes':p.stat().st_size,'sha256':sha(p)} for p in sorted(HERE.iterdir()) if p.is_file() and p.name!='completion_manifest.json']
(HERE/'completion_manifest.json').write_text(json.dumps({'status':'complete_frozen','quality_accepted':False,'files':files},indent=2)+'\n')
print(json.dumps({name:sha(HERE/name) for name in ('results.json','compact_report.json','original_control_consistency.json','completion_manifest.json')}))
