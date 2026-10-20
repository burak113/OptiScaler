"""Score frozen independent predictions after the private label key is revealed."""
from pathlib import Path
import hashlib
import json

HERE=Path(__file__).resolve().parent
PREDICTION_SHA='89285b452a6d77d81c27f8a4d9b16afb64dc94fbba9d26a9f6f3173e301f9406'
KEY_SHA='5c69f858b3364f9d2ae4d3215d6d902ac05708a93b76e373f3e81fd682d881a0'

# This maps the reviewer's mechanism vocabulary to broad observable classes.
# It does not upgrade a qualified prediction into an exact physical cause.
CLASS_MAP={
    'selected_stage_stale_support':'selected_stage_tail',
    'sparse_source_correct_motion':'sparse_source_no_motion_blame',
    'surface_mv_bias':'transport_error',
    'clean_control':'no_detected_support_error',
    'virtual_correspondence_mismatch':'virtual_correspondence_error',
    'delayed_or_misplaced_source_support':'source_support_error',
    'multiplicative_level_only':'no_detected_support_error',
    'alternating_surface_motion_error':'transport_error',
    'raw_rr_stage_stale_support':'provider_stage_tail',
    'untrusted_geometry_witness':'non_identifiable',
    'zero_hit_distance_clean_observations':'no_detected_support_error',
    'missing_independent_support_witness':'non_identifiable',
    'observation_equivalent_undetermined':'non_identifiable',
}


def main():
    predictions=HERE/'BLIND_PREDICTIONS.json'
    revealed=HERE.parent/'evidence/blind_labels_revealed.json'
    assert hashlib.sha256(predictions.read_bytes()).hexdigest()==PREDICTION_SHA
    assert hashlib.sha256(revealed.read_bytes()).hexdigest()==KEY_SHA
    p=json.loads(predictions.read_text());truth=json.loads(revealed.read_text())
    rows=[]
    for row in p['cases']:
        key=truth[row['case_id']]
        disposition=CLASS_MAP[row['prediction']]
        rows.append({'case_id':row['case_id'],'frozen_prediction':row['prediction'],
            'prediction_status':row['status'],'injected_cause':key['cause'],
            'expected_observable_class':key['expected'],'predicted_observable_class':disposition,
            'broad_class_consistent':disposition==key['expected'],'heldout':key['heldout'],
            'prediction_limit':row['limits']})
    positive=[r for r in rows if r['prediction_status']!='abstain']
    abstained=[r for r in rows if r['prediction_status']=='abstain']
    out={'schema':'job06.independent_blind_scoring.v1','executor':'independent_skeptical_reviewer',
         'gpu_executed':False,'prediction_sha256':PREDICTION_SHA,'revealed_key_sha256':KEY_SHA,
         'identified_or_qualified_cases':len(positive),
         'identified_broad_classes_consistent':sum(r['broad_class_consistent'] for r in positive),
         'explicit_abstentions':len(abstained),
         'abstentions_consistent':sum(r['broad_class_consistent'] for r in abstained),
         'incorrect_broad_class_claims':sum(not r['broad_class_consistent'] for r in rows),
         'heldout_identified_cases':sum(r['heldout'] for r in positive),
         'observation_equivalent_cases_are_not_independent_trials':True,
         'cases':rows,
         'limitations':[
             'Broad observable classes match; this is not 14 independently identified physical causes.',
             'The two identical-observation cases are one abstention stress test, not independent captures.',
             'The alternating transport residual is compatible with jitter error or alternating MV bias; missing convention metadata prevents exact causality.',
             'Source misplacement is observable before RR; the raw estimator and exact delay mechanism are not uniquely determined.',
             'Zero hit distance prevents physical virtual projection even though synthetic virtual identities are independently provided.',
             'Game clips lack the independent analytic support and identity witnesses used by the identifiable synthetic cases.',
         ]}
    (HERE/'BLIND_SCORE.json').write_text(json.dumps(out,indent=2,allow_nan=False)+'\n')
    print(json.dumps({k:v for k,v in out.items() if k not in ('cases','limitations')},indent=2))


if __name__=='__main__':
    main()
