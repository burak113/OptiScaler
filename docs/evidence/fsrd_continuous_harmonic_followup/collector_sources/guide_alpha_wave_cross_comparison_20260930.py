from pathlib import Path
import hashlib,importlib.util,json,itertools,sys
ROOT=Path(__file__).resolve().parents[1]
pkg=ROOT/'tools_tmp/native_guide_alpha_wave_identical_repeat_20260930'
sys.path.insert(0,str(pkg))
target=pkg/'cross_comparison.json'
if target.exists():raise ValueError('Preserve diagnostic')
spec=importlib.util.spec_from_file_location('fixed_compare',pkg/'analyze.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
orig=ROOT/'tools_tmp/native_continuous_harmonic_remaining_20260930/evidence/wave/harmonic_pilot'
abl=ROOT/'tools_tmp/native_guide_alpha_wave_continuation_20260930/evidence/wave'
contexts={'old_original':orig,**{name:abl/name for name in ('original','zero','one','source_alpha')},
          **{name:pkg/'evidence/wave'/name for name in ('repeat0','repeat1','repeat2')}}
data={'schema':'guide-alpha-wave-all-retained-context-comparison-v1','quality_accepted':False,
      'diagnostic_only':True,'new_native_contexts':0,'native_RR_calls':0,'pairs':[],'contexts':{}}
for name,p in contexts.items():
    data['contexts'][name]={'inputs':{f'input{i}.bin':m.sha(p/f'input{i}.bin')for i in range(7)},
      'controls':m.sha(p/'dispatch_controls.bin'),'outputs':{f:m.sha(p/f)for f in ('diffuse.bin','specular.bin')}}
for a,b in itertools.combinations(contexts,2):
    x,y=data['contexts'][a],data['contexts'][b]
    data['pairs'].append({'left':a,'right':b,'all7_inputs_exact':x['inputs']==y['inputs'],'controls_exact':x['controls']==y['controls'],
      'outputs':{f:m.compare(contexts[a]/f,contexts[b]/f) for f in ('diffuse.bin','specular.bin')}})
target.write_text(json.dumps(data,indent=2,allow_nan=False)+'\n')
summary={'contexts':len(contexts),'pairs':len(data['pairs']),
 'identical_input_pairs':sum(p['all7_inputs_exact']for p in data['pairs']),
 'nonexact_identical_input_pairs':sum(p['all7_inputs_exact'] and not all(v['bytes_exact']for v in p['outputs'].values())for p in data['pairs']),
 'maximum_identical_input_RGB_RMS':max(v['RGB']['rms']for p in data['pairs']if p['all7_inputs_exact']for v in p['outputs'].values()),
 'result_sha256':m.sha(target)}
(pkg/'cross_comparison_compact.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps(summary,indent=2))
