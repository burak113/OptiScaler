from pathlib import Path
import hashlib,json,shutil
ROOT=Path(__file__).resolve().parents[1]
old=ROOT/'tools_tmp/native_guide_alpha_wave_continuation_20260930'
new=ROOT/'tools_tmp/native_guide_alpha_wave_identical_repeat_20260930'
if new.exists():raise ValueError('Preserve repetition package')
new.mkdir()
text=(old/'analyze.py').read_text()
text=text.replace("VARIANTS=('original','zero','one','source_alpha')", "VARIANTS=('repeat0','repeat1','repeat2')")
text=text.replace("native_contexts=4,native_RR_calls=256", "native_contexts=3,native_RR_calls=192")
text=text.replace("specular-albedo-diagnostic-alpha-raw-native-ablation-v1", "identical-wave-seven-input-fresh-context-repeat-v1")
text=text.replace("specular-albedo alpha only; original RGB byte-identical", "specular-albedo unchanged; all7 input bytes identical")
text=text.replace("if i==3 and variant!='original':", "if False:")
text=text.replace("if i!=3 or variant=='original':assert", "assert")
text=text.replace("only_changed_resource='specular-albedo input3 alpha'", "only_changed_resource=None")
text=text.replace("case_dir/'original'/name", "case_dir/'repeat0'/name")
text=text.replace("assert report['completed_native_contexts']==4", "assert report['completed_native_contexts']==3")
text=text.replace("{'contexts':4,'RR_calls':256", "{'contexts':3,'RR_calls':192")
(new/'analyze.py').write_text(text)
shutil.copyfile(old/'native_resource_guard.py',new/'native_resource_guard.py')
registration={'schema':'wave-identical-context-repeat-registration-v1',
 'reason':'Wave source-alpha matched all7 original bytes but native outputs differed; measure3additional fresh identical contexts without input changes.',
 'source_ablation_result_sha256':hashlib.sha256((old/'evidence/results.json').read_bytes()).hexdigest(),
 'old_driver_sha256':hashlib.sha256((old/'analyze.py').read_bytes()).hexdigest(),
 'native_contexts':3,'RR_calls':192,'parameter_changes':False,'quality_accepted':False,
 'comparison':'All3fresh pairs, each versus4previous wave ablations and oldoriginal, exactinput/controls before output RMS; no averaging/subtracting control variability.'}
(new/'repeat_registration.json').write_text(json.dumps(registration,indent=2)+'\n')
print(new)
