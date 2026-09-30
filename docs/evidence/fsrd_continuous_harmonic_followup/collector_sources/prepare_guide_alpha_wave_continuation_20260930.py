from pathlib import Path
import hashlib,json,shutil
ROOT=Path(__file__).resolve().parents[1]
old=ROOT/'tools_tmp/native_guide_alpha_ablation_20260930'
new=ROOT/'tools_tmp/native_guide_alpha_wave_continuation_20260930'
if new.exists():raise ValueError('Preserve continuation')
new.mkdir()
text=(old/'analyze.py').read_text()
text=text.replace("CASES={'material':ROOT/'tools_tmp/native_continuous_harmonic_fresh_retry_20260930/evidence/material',\n       'wave':", "CASES={'wave':")
text=text.replace("native_contexts=8,native_RR_calls=512", "native_contexts=4,native_RR_calls=256")
text=text.replace("assert original_rgba.shape[0]==64\n        source_a=alpha_full(source/'observed')", "assert original_rgba.shape[0] in (1,64)\n        source_a=alpha_full(source/'observed')\n        if original_rgba.shape[0]==1:\n            assert np.array_equal(source_a,np.broadcast_to(source_a[:1],source_a.shape))\n            source_a=source_a[:1]")
text=text.replace("assert report['completed_native_contexts']==8", "assert report['completed_native_contexts']==4")
text=text.replace("{'contexts':8,'RR_calls':512", "{'contexts':4,'RR_calls':256")
(new/'analyze.py').write_text(text)
shutil.copyfile(old/'native_resource_guard.py',new/'native_resource_guard.py')
erratum={'schema':'guide-alpha-upload-dedup-continuation-erratum-v1',
 'original_driver_sha256':hashlib.sha256((old/'analyze.py').read_bytes()).hexdigest(),
 'preserved_original_result_sha256':hashlib.sha256((old/'evidence/results.json').read_bytes()).hexdigest(),
 'completed_original_material_contexts':4,'completed_original_RR_calls':256,
 'failure':'Root driver assumed specguide uploadcount64; wave input3 legitimately has uploadcount1. Failed before wave native launch.',
 'continuation':'Wave4 contexts only; accept originaluploadcount1 or64, require source alpha constant when count1. All job uploadcounts retained, no output replay or parameter change.'}
(new/'continuation_erratum.json').write_text(json.dumps(erratum,indent=2)+'\n')
print(new)
