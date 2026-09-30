from pathlib import Path
import json,hashlib
import numpy as np
HERE=Path(__file__).resolve().parent;OLD=HERE.parent/'harmonic_response_coefficient_history_feasibility_20260930'
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def strict(m,b):return m['score']['residual_temporal_std']<=b['score']['residual_temporal_std']
def compact_window(m,control):
    return dict(relative_effective=m['relative_gate']['effective_success'],relative_failures=m['relative_gate']['failures'],absolute_all_frames=m['detail_within_5_percent_all_frames'],
        STD=m['score']['residual_temporal_std'],STD_ratio_to_B=m['actual_STD_ratio_to_control'],
        STD_ratio_to_frozen_DC=m['score']['residual_temporal_std']/control['score']['residual_temporal_std'] if control['score']['residual_temporal_std'] else None,
        gain_min=m['absolute_gain_min'],gain_max=m['absolute_gain_max'],phase_max=m['absolute_phase_max'],
        bias_RGB=m['score']['bias_rgb'],invalid_pixels=m['invalid_pixel_fraction'])
def main():
    r=read(HERE/'results.json');old=read(OLD/'results.json');freeze=read(HERE/'pre_score_freeze.json')
    assert all(sha(p)==s for p,s in freeze['sources'].items())
    comparisons=[]
    for row,prior in zip(r['native_rows'],old['native_rows']):
        assert row['scene']==prior['scene'] and row['variants']==prior['variants']
        with np.load(HERE/(row['scene']+'_outputs.npz')) as v2,np.load(OLD/(row['scene']+'_outputs.npz')) as v1:
            assert v2.files==v1.files and all(v2[k].tobytes()==v1[k].tobytes() for k in v2.files)
        diag=dict(row['diagnostics']);eligible=diag.pop('application_eligible');assert diag==prior['diagnostics']
        comparisons.append(dict(scene=row['scene'],valid_input_arrays_and_all_metrics_V1_V2_bitexact=True,new_eligibility_has_no_scored_output_change=True))
    for row,prior in zip(r['known_operator_rows'],old['known_operator_rows']):
        assert row['name']==prior['name'] and row['variants']==prior['variants'] and row['candidate_SHA']==prior['candidate_SHA']
    agreement=dict(status='completed_V1_V2_valid_data_comparison',native_rows=6,known_rows=len(r['known_operator_rows']),all_metrics_and_native_outputs_exact=True,rows=comparisons,
        V1_contract_still_failed=True,V2_invalid_path_selfchecks_passed=True,source_P_TP_constants_scorer_unchanged=True)
    (HERE/'v1_v2_valid_data_comparison.json').write_text(json.dumps(agreement,indent=2)+'\n')
    rows=[]
    for row in r['native_rows']:
        c=row['variants']['candidate'];d=row['variants']['frozen_DC_innovation_safe']
        rows.append(dict(scene=row['scene'],windows={w:compact_window(c[w],d[w]) for w in c},first8_exact_B=row['first8_inactive_exact_B'],
            whole_image_fallback_fraction=row['diagnostics']['application']['atomic_fallback_pixel_fraction'],
            coefficient_history_counts=[f['history_count'] for f in row['diagnostics']['frames']],
            cut_frames=[dict(frame=f['frame'],reasons=f['cut_reasons']) for f in row['diagnostics']['frames'] if f.get('cut_reasons')]))
    counts={}
    for w in ['full','mature','startup_first8','activation8to16','transition24to40']:
        m=[row['variants']['candidate'][w] for row in r['native_rows']]
        counts[w]=dict(rows=6,relative_effective=sum(x['relative_gate']['effective_success'] for x in m),absolute_all_frames=sum(x['detail_within_5_percent_all_frames'] for x in m),
            actual_STD_ratio_le1=sum(x['actual_STD_ratio_to_control'] is not None and x['actual_STD_ratio_to_control']<=1 for x in m),
            relative_AND_absolute_AND_strictSTD=sum(x['relative_gate']['effective_success'] and x['detail_within_5_percent_all_frames'] and x['actual_STD_ratio_to_control'] is not None and x['actual_STD_ratio_to_control']<=1 for x in m))
    known=[]
    for row in r['known_operator_rows']:
        c=row['variants']['candidate'];control=row['variants']['frozen_DC_innovation_safe'];original=row['variants']['original_current_D']
        known.append(dict(name=row['name'],label=row['label'],windows={w:compact_window(c[w],control[w]) for w in c},
            original_current_D_STD_full=original['full']['score']['residual_temporal_std'],original_current_D_STD_mature=original['mature']['score']['residual_temporal_std'],
            candidate_STD_to_original_current_D_mature=c['mature']['score']['residual_temporal_std']/original['mature']['score']['residual_temporal_std'] if original['mature']['score']['residual_temporal_std'] else None,
            zero_original_STD_is_not_a_free_noise_pass=True))
    report=dict(status='completed_contract_repaired_bounded_failed_general_feasibility',quality_accepted=False,new_native_contexts=0,new_P_or_TP=False,
        V1_contract_failure_preserved=True,V2_model_SHA=sha(HERE/'model.py'),V2_freeze_SHA=sha(HERE/'pre_score_freeze.json'),V2_results_SHA=sha(HERE/'results.json'),
        selfchecks=len(read(HERE/'selfcheck_results.json')['checks']),counts=counts,native_rows=rows,known_operator_rows=known,known_operator_count=len(known),
        limits=['All6fullabsolutefail; first8baselineunchanged. Matureweakgainbelow.95 remains although actualSTD improves.',
            'Small mature gains over DC control are not native independence or game quality acceptance.',
            'Source phase law fails for static response with moving source; slow true response ramps and source illumination drift can lag.',
            'Endogenous exactB/D cancellation can be destroyed; current dense orth residual preserves signal and noise.',
            'Other7+22 native coverage absent; knownoperator controls do not fill it. No pseudoSE/confidence or parametersearch.'])
    (HERE/'compact_report.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    assert all(sha(p)==s for p,s in freeze['sources'].items())
    files=[dict(path=str(p),sha256=sha(p),bytes=p.stat().st_size) for p in sorted(HERE.iterdir()) if p.is_file() and p.name not in ('completion_manifest.json','finalize.log')]
    oldfiles=[dict(path=str(p),sha256=sha(p),bytes=p.stat().st_size) for p in sorted(OLD.iterdir()) if p.is_file()]
    manifest=dict(schema='V2-coefficient-history-completion-manifest',status='frozen_completed_failed_general_feasibility',quality_accepted=False,
        pre_post_reference_hashes_equal=True,files=files,V1_preserved_contract_failed_files=oldfiles,new_native_contexts=0)
    (HERE/'completion_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(dict(counts=counts,compact_SHA=sha(HERE/'compact_report.json'),manifest_SHA=sha(HERE/'completion_manifest.json')),indent=2))
if __name__=='__main__':main()
