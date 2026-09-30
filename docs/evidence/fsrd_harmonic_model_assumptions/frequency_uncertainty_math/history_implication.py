"""Derived component-level static history implication; not final-pilot risk."""
from pathlib import Path
import hashlib
import json
import math

HERE=Path(__file__).resolve().parent
source=HERE/'results.json'
records=json.loads(source.read_text())
rows=[]
for row in records['rows']:
    if row['frequency_information_status']!='invertible_local_oracle':continue
    for count in (1,16,41,56,64):
        conditional=row['nominal_conditional_current_atom_RMS']/math.sqrt(count)
        common=row['nominal_extra_current_atom_RMS_from_frequency']
        rows.append({'case':row['case'],'independent_current_coefficient_observations':count,
            'frequency_learning_independent_prior_observations':8,
            'nominal_conditional_average_atom_RMS':conditional,
            'common_fixed_frequency_firstorder_atom_RMS':common,
            'common_frequency_variance_over_conditional_mean':(common/conditional)**2,
            'total_component_local_RMS_over_conditional_mean':math.sqrt(1+(common/conditional)**2)})
result={'schema':'harmonic-fixed-frequency-component-history-implication-v1',
    'status':'completed_exact_derived_oracle_math_not_estimator', 'quality_accepted':False,
    'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
    'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    'assumptions':['Static physical atom and fixed learned frequency from disjoint past8 frames',
        'Independent current coefficient fits with known IID covariance, no phase innovation or model selection',
        'The same frequency perturbation is common to every coefficient fit; its firstorder prediction error does not average down'],
    'limitations':['This is the atom component, not combined final pilot variance',
        'Residual equals source minus current fitted atom; its common error is anticorrelated and can cancel the atom error in a consistent final reconstruction',
        'Actual selected-frequency/colored uncertainty is absent; no measured estimator/native quality claim',
        'Counts41 and56 correspond only to possible history lengths after frame8 activation in a64-frame fixture'],
    'rows':rows}
(HERE/'history_implication_results.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
print(json.dumps({'rows':len(rows),'source_sha256':result['source_sha256'],
    'one_offgrid_n56_variance_ratio':next(r['common_frequency_variance_over_conditional_mean'] for r in rows if r['case']=='one_offgrid' and r['independent_current_coefficient_observations']==56)},indent=2))
