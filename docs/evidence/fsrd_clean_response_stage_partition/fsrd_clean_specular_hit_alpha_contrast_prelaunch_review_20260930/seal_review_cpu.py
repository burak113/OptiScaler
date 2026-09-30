"""Seal bounded independent review; no producer changes or runtime execution."""
from pathlib import Path
import hashlib,json
HERE=Path(__file__).resolve().parent
PREP=HERE.parent/'fsrd_clean_specular_hit_alpha_contrast_preparation_20260930'
def rec(p):
 p=Path(p).resolve();return dict(path=str(p),bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest())
def save(n,v):
 with(HERE/n).open('x',encoding='utf-8',newline='\n')as f:json.dump(v,f,indent=2,allow_nan=False);f.write('\n')
review=json.loads((HERE/'review.json').read_text())
assert review['status']=='READY_FOR_ROOT_SPECULAR_HIT_ALPHA_CONTRAST_AUTHORIZATION_SUBJECT_TO_FINAL_RZ_GATE'and not review['blocking_findings']
reg=json.loads((PREP/'registration.json').read_text())
pins=[dict(**rec(reg['source_reference']['path']),lines=[43,81,99,106,111,115,117,120,144,150,154,163,164,166,178,184,188,192,200,201,202,203,208,220,221,222],meaning='ExactB342 job parsing/provider load/configuration, input mapping/staticuploads, appliedcontrols-before-API, serialfence/readback and terminal-after-destroy'),
      rec(reg['runner']['path']),rec(reg['provider']['path']),
      dict(**rec(PREP/'run_native.py'),meaning='Exact bounded adapter diff; physical work checkpoint before guard/diagnostic/output gates; external R/RZ/root authorization is a separate policy gate'),
      rec(PREP/'native_work_accounting.py'),rec(PREP/'executor_evidence.py'),rec(PREP/'native_resource_guard.py'),rec(PREP/'analyze_raw_cpu.py')]
save('source_pins.json',dict(records=pins,producer_seals=review['producer_seals'],expanded_provenance=review['source_verification'],table_not_duplicated=True))
save('compact.json',dict(status=review['status'],blocking_findings=[],review=rec(HERE/'review.json'),
 unique_sources_verified_stable=review['source_verification']['unique_records'],
 existing_SIM_independently_replayed=12,all56_runtime_targets_absent=True,
 treatment='Only SDKinput6 FP16 A+0/+10(0x4900); RGB+other6fullinputs+64x184 controls exact. +10view-depth proxy, not traced ray.',
 order=['A0_r0','A10_r0','A10_r1','A0_r1'],planned_only_if_completed=review['planned_only_if_completed'],
 required_gates=review['required_external_gates'],actual_new_native_GPU_build_scores=0,
 limitations='No private-zero/minimum contract, historical compiler equivalence, quality, composition or game-cause claim. Source-qualified exact legal footer versus unknown prefix lowerbounds unchanged.',
 reviewer_lookup_error_preserved=review['reviewer_IO_qualification']))
files=[rec(p)for p in sorted(HERE.rglob('*'))if p.is_file()and p.name!='completion_manifest.json']
save('completion_manifest.json',dict(status='SEALED_INDEPENDENT_CPU_PRELAUNCH_REVIEW',files=files,self_entry_excluded=True,
 producer_seals=review['producer_seals'],not_execution_authorization=True,required_final_RZ_gate=True,actual_new_native_GPU_build_scores=0))
for n in('review.json','compact.json','source_pins.json','completion_manifest.json'):print(json.dumps(rec(HERE/n)))
