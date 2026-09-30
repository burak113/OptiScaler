"""Seal the independent saved-array audit and bounded interpretation."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb')as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()
def ident(p):p=Path(p);return dict(path=str(p),bytes=p.stat().st_size,sha256=sha(p))
def read(p):return json.loads(Path(p).read_text())
def save(n,v):
    with(HERE/n).open('x',encoding='utf-8',newline='\n')as f:json.dump(v,f,indent=2,allow_nan=False);f.write('\n')
a=read(HERE/'audit.json');assert a['CPU_saved_array_metric_dicts']==108 and a['total_actual_metric_dict_recomputations_across_attempts']==126
assert a['native_contexts']==a['GPU_jobs']==a['CPU_model_calls']==a['CPU_analyzer_runs']==0
for x in read(HERE/'audit_attempt1_qualification.json')['preserved_attempt1']:assert ident(x['path'])==x
ns={r['scene']:r for r in a['six_native_rows']};ks={r['name']:r for r in a['known24_report_records']}
named=['endogenous_B_D_exact_cancellation','static_source_true_D_ramp_unobservable','moving_source_static_guide_fixed_response','moving_phase_slow_RGB_response_amplitude','persistent_shared_D_bias','phase_qualification_toggle_cut','shared_constant_speed_source_response_phase','subthreshold_illumination_drift']
selection=[]
for name in named:
    r=ks[name]
    selection.append(dict(name=name,candidate={w:r['windows'][w]['candidate']for w in('full','mature')},frozen_V2={w:r['windows'][w]['frozen_V2_delta_history']for w in('full','mature')},
        status='frozen_known_operator_report_evidence_only_no_saved_candidate_numeric_rescore'))
interpretation=dict(schema='endpoint-independent-post-score-compact-interpretation-v1',UTC=datetime.now(timezone.utc).isoformat(),
    status='audited_frozen_result_general_feasibility_not_established',quality_accepted=False,
    numerical_audit=dict(native_saved_candidate_arrays=6,native_saved_candidate_frames=384,first8_exact_B_frames=48,finite_valid_RGB_pixels=3932160,
        final_complete_metric_dict_recomputations=108,prior_incomplete_report_assembly_metric_dict_recomputations=18,total_actual_metric_dict_recomputations=126,
        completion_records=32,external_authorization_review_records=2,corrected_preparation_records=21,corrected_external_source_records=61,before_after_source_pins=61,
        recorded_native_atomic_fallback_fraction=[r['atomic_fallback_pixel_fraction']for r in a['six_native_rows']],
        fallback_qualification='Recorded fallback metadata is authenticated; the fallback/model is not executed by this audit.',
        native_comparator_metric_dictionary_equalities=a['checks']['native_comparator_metric_dicts_equal_previous_V2'],
        known24_input_digest_equalities=144,known24_comparator_metric_dictionary_equalities=360,
        known_candidate_numeric_rescoring=0),
    counts=a['counts'],native_scenes=[dict(scene=r['scene'],full=r['full']['candidate'],mature=r['mature']['candidate'])for r in a['six_native_rows']],
    weak_material=dict(full=ns['weak_material']['full']['candidate'],mature=ns['weak_material']['mature']['candidate'],
        observation='Mature relative gate passes but temporal STD is1.0693300441119584×B and1.086371293027486×V2. Mature gain0.9010875..0.9683867 fails. It is0.9628938616449165×frozenDC STD, so worsening must be qualified by comparator.'),
    known_named_records=selection,
    observations=[
        'Full: relative3/6, strict actualSTD<=B3/6, absoluteGAIN0/6, absolutePHASE4/6, absoluteGAIN_AND_PHASE0/6. All6 preserve first8B; weakmaterial and reset also have later full-window gain failures.',
        'Mature last16: relative6/6, strict actualSTD<=B5/6, absoluteGAIN5/6, absolutePHASE6/6, combined gain/phase5/6. Relative success includes absolute-floor/5% allowance and cannot substitute for strict STD or absolute-detail checks.',
        'Frozen known reports show specific mechanism repairs vsV2: endogenous_B_D_exact_cancellation restores mature gain/phase with RMSE2.606e-16 vs8.524e-4; static_source_true_D_ramp_unobservable restores gain1 instead of0.9375; moving_source_static_guide_fixed_response restores phase/gain and RMSE1.900e-16 vs.00231055. Moving_phase_slow_RGB_response_amplitude also removes the constructed coefficient-lag error.',
        'These repairs align with conditioning current reconstruction C rather than correction D under the registered source-phase/affine-coordinate law. They are bounded constructed examples, not independently rescored saved candidate arrays or universal invariance.',
        'persistent_shared_D_bias is unchanged fromV2: mature gain1.1666667 despite quiet STD and relative success. phase_qualification_toggle_cut still fails gain/phase (phase.0857948>.05). Source phase still need not match reconstruction phase.',
        'shared_constant_speed_source_response_phase newly fails mature gain at1.0574486 whileV2 passes; candidateSTD.000301153 exceedsV2.000107893. This regression cannot be erased by the mechanism repairs.',
        'moving_source_static_guide_fixed_response reports STD/B486.35 because both numerator and baseline variation are around machine precision; the exact strict-STD failure is retained alongside absolute RMSE1.900e-16. No invented floor or replacement ratio.',
        'Subthreshold illumination drift retains the frozenDC bias/STD limitation. Constant/linear endpoint invariance only holds in registered transported coordinates; negative weights, nonlinear acceleration and opaque response history remain limits.',
    ],
    limitations=['24 constructed candidates lack saved output arrays; candidate metric claims there remain frozen reported evidence. Original inputs, names, generator whitelist and comparator records are authenticated without operator/model reruns.',
        'Six posthoc matching native response rows only. Other7source and22source adversaries lack matching nativeTP; no extrapolation to native coverage.',
        'Post-score forensic audit with preserved local assembly failure and correction; it is not a blind new candidate experiment.',
        'No production, model, analyzer or result edit; no native/GPU/build/game or additional model/operator trial. No runtime/game quality or stain/wave cause/solution acceptance.'],
    native_contexts=0,native_API_dispatches=0,GPU_jobs=0,builds=0,CPU_model_calls=0,CPU_analyzer_runs=0,constructed_operator_generator_calls=0)
save('compact_interpretation.json',interpretation)
md='''Independent saved-array audit passed: all108 full/mature metric dictionaries matched the frozen result exactly, all61 source pins matched before/after, and completion/preparation/authorization hashes verified. Six candidate arrays retain first8 baseline bytes, finite valid RGB, matching saved digests and zero recorded fallback. Original6/DC/V2 comparator metrics and all24 constructed-control input records/comparators remain unchanged.

Full-window candidate: relative3/6; strictSTD<=B3/6; gain0/6; phase4/6; gain AND phase0/6. Mature16: relative6/6; strictSTD<=B5/6; gain5/6; phase6/6; gain AND phase5/6. Weak material still worsens matureSTD by6.93% vsB and8.64% vsV2, and fails gain. Relative slack does not establish strict noise reduction.

Reported constructed examples repair V2 cancellation, static-D-ramp and moving-source/static-response mechanisms, but shared bias remains (gain1.1667), phase-toggle remains invalid (phase.08579), and shared constant-speed response develops a gain regression (1.05745). These known candidate arrays were not saved, so those claims are frozen report evidence, not independent numeric rescoring.

The first local audit attempt completed18 material score checks then failed in report assembly; script/log/registration were preserved and the naming-only correction completed108 checks. Total actual metric-dictionary recomputations126, distinct dictionaries108. No estimator/model/analyzer/operator-generation execution and no native/GPU/build/game. General feasibility and runtime quality are not established.
'''
with(HERE/'compact.md').open('x',encoding='utf-8',newline='\n')as f:f.write(md)
external={}
freeze=read(HERE/'post_audit_external_freeze.json')
for x in freeze['before']+[a['producer_result'],a['producer_completion']]:external[x['path']]=x
for x in a['scorer_nodes']:external[x['source']['path']]=x['source']
for r in a['six_native_rows']:
    for k in('source_npz','saved_candidate_npz','saved_V2_npz'):external[r[k]['path']]=r[k]
producer_manifest=read(a['producer_completion']['path'])
for x in producer_manifest['files']+producer_manifest['external_authorization_and_review']:
    p=Path(x['path']);external[str(p)]=ident(p)
for x in external.values():assert ident(x['path'])==x
files=[ident(p)for p in sorted(HERE.rglob('*'))if p.is_file()]
manifest=dict(schema='independent-endpoint-post-score-audit-completion-manifest-v1',UTC=datetime.now(timezone.utc).isoformat(),files=files,
    external_pins=list(external.values()),self_entry_excluded=True,quality_accepted=False,native_API_dispatches=0,GPU_jobs=0,CPU_model_calls=0,CPU_analyzer_runs=0)
save('completion_manifest.json',manifest)
for x in files+list(external.values()):assert ident(x['path'])==x
print(json.dumps(dict(audit=ident(HERE/'audit.json'),compact=ident(HERE/'compact_interpretation.json'),manifest=ident(HERE/'completion_manifest.json'),owned_files=len(files),external_pins=len(external))),flush=True)
