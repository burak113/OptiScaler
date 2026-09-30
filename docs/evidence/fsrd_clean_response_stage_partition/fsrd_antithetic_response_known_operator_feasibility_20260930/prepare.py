"""Pin and retain all original24 source pairs before bounded domain evaluation."""
from pathlib import Path
import hashlib,importlib.util,json,sys
import numpy as np
sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent;BASE=HERE.parent;OLD=BASE/'harmonic_reconstruction_endpoint_history_feasibility_20260930'
def read(p):return json.loads(Path(p).read_text())
def ident(p):
 b=Path(p).read_bytes();return dict(path=str(p),bytes=len(b),sha256=hashlib.sha256(b).hexdigest())
def save(n,d):
 with(HERE/n).open('x',encoding='utf-8',newline='\n')as f:json.dump(d,f,indent=2,allow_nan=False);f.write('\n')
def main():
 assert not(HERE/'pre_evaluation_freeze.json').exists()
 sources=[OLD/n for n in ['known_operators.py','frozen_operator_helpers.py','model.py','analyze.py','preregistration.json','completion_manifest.json','pre_score_freeze.json']]
 sources+=[BASE/'source_continuous_harmonic_feasibility_20260930/analyze.py',BASE/'harmonic_response_dc_innovation_feasibility_20260930/model.py',BASE/'fsrd_weak_response_antithetic_concept_20260930.txt']
 pins=read(OLD/'pre_score_freeze.json')['sources']
 for p in sources:
  if str(p)in pins:assert ident(p)['sha256']==pins[str(p)]
 sys.path.insert(0,str(OLD));sp=importlib.util.spec_from_file_location('antithetic_original24_bank',OLD/'known_operators.py');bank=importlib.util.module_from_spec(sp);sp.loader.exec_module(bank);cases=list(bank.cases());assert len(cases)==24
 # Keep endpoint helper references bound to its original model while the new
 # selfchecks import our distinct source-law module by its conventional name.
 sys.path.insert(0,str(HERE));sys.modules.pop('model',None)
 from selfchecks import run
 save('selfcheck_results.json',run())
 entries=[];(HERE/'retained_inputs').mkdir()
 for i,c in enumerate(cases):
  p=HERE/'retained_inputs'/f'{i:02d}_{c["name"]}.npz'
  arrays={k:c[k]for k in ['raw','P','TP','B','active','controls','truth']}
  if c.get('exposure')is not None:arrays['exposure']=c['exposure']
  np.savez_compressed(p,**arrays)
  entries.append(dict(index=i,name=c['name'],label=c['label'],arrays=ident(p),array_hashes={k:hashlib.sha256(np.ascontiguousarray(v).tobytes()).hexdigest()for k,v in arrays.items()},metadata_retained=dict(diag=c['diag'],descriptors=c['descriptors'],exposure_present='exposure'in arrays)))
 prereg=dict(status='FROZEN_BOUNDED_SOURCE_MIRROR_DOMAIN_NO_T_M_EXTENSION',equation='M=2*P-O; E=P+0.5*(T(O)-T(M))',P_law=dict(history=16,current_inclusive=True,first8_each_epoch='exactraw passthrough; history fed from firstframe',reset_jitter_exposure='exact observed change cuts; absent exposure unknown',invalid_metadata_source='exactraw unchanged bits, inactive, history clear',no_clipping=True),old24_bank_contract=dict(original_case_names=[r['name']for r in entries],preserved_oldP_TP_B=True,raw_only_feeds_newP=True,missing='No callable input-to-response operator T exists. produce assigns P=source,TP=P-observedD,B=truth-cleanD; same-input responses may differ. T(M) is unspecified.',antithetic_quality_score='N/A_missing_operator_extension_not_zero_or_pass',old_scorers='Pinned unchanged; not executed because antithetic response undefined.'),separate_algebra_functions=['T(X)=X','T(X)=a*X+b with explicitly fixed RGB a,b','T(X)=X^2'],separate_algebra_not_original24_quality=True,domain=[0,65504],native_feasibility='Unmet for any negative/nonfinite/overflow M; metadata invalid also unsupported; never clip/replace and pass',limits=['P lag/current double-use and estimated center invalidate oracle expansion/unbiasedness claims.','Unknown RGB/time/nativehistory/guide covariance; no independence/confidence proof.','No Tclean, guide, truth, baseline or future enters source estimator.','Signed math checks are not valid radiance SDK input demonstrations.','No actual6native response inference and no SDK/GPU launch plan.'],quality_accepted=False,actual_GPU_native_build_scores=0)
 save('preregistration.json',prereg);save('source_case_manifest.json',dict(source_pins=[ident(p)for p in sources],cases=entries,original24_exactcasebank=True))
 files=[ident(HERE/n)for n in ['model.py','selfchecks.py','prepare.py','analyze.py','selfcheck_results.json','preregistration.json','source_case_manifest.json']]+[r['arrays']for r in entries]
 save('pre_evaluation_freeze.json',dict(files=files,external_sources=[ident(p)for p in sources],self_entry_excluded=True,actual_GPU_native_build_scores=0,status='READY_FOR_ONCE_BOUNDED_DOMAIN_EVALUATION_NO_QUALITY_SCORING'))
 print(json.dumps(dict(status='PREPARED_FROZEN_SOURCE_DOMAIN_ONLY',cases=24,freeze=ident(HERE/'pre_evaluation_freeze.json'))))
if __name__=='__main__':main()
