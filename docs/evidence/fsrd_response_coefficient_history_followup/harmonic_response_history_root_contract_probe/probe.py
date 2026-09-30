from pathlib import Path
import hashlib,importlib.util,json
import numpy as np
ROOT=Path(__file__).resolve().parents[2];HERE=Path(__file__).resolve().parent
PATH=ROOT/'tools_tmp/harmonic_response_coefficient_history_feasibility_20260930/model.py'
def main():
 target=HERE/'probe.json'
 if target.exists():raise ValueError('Preserve probe')
 digest=hashlib.sha256(PATH.read_bytes()).hexdigest();assert digest=='84c710ae293e102091d15f70fb08d33edd5ebe1c5a10397c2845303d37e809f0'
 s=importlib.util.spec_from_file_location('independent_contract_probe',PATH);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
 raw=np.full((1,13,13,3),.3,np.float32);P=raw.copy();P[0,0,0,0]=np.nan;TP=raw.copy();B=np.full_like(raw,.2)
 ctrl=np.array([[1.,0,0]]);diag={'frames':[{'epoch_start':0,'atom_diagnostics':[]}]}
 out,d,pre=m.make_response_history(raw,P,TP,B,np.ones(1,bool),ctrl,diag,[None])
 result={'schema':'independent-response-history-invalid-P-contract-probe-v1','quality_accepted':False,
  'model_sha256':digest,'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
  'raw_RGB':raw[0,0,0].tolist(),'baseline_RGB':B[0,0,0].tolist(),'output_RGB':out[0,0,0].tolist(),
  'invalid_P_pixel':[0,0,0,0],'invalid_value':'NaN','active':True,'reset':True,
  'pre_DC_candidate_exact_baseline':pre.tobytes()==B.tobytes(),'final_output_exact_baseline':out.tobytes()==B.tobytes(),
  'reported_reason':d['frames'][0]['reason'],
  'finding':'Exact-baseline branch still eligible for final source-DC shift; final output violates branch contract',
  'new_native_contexts':0,'new_native_RR_calls':0}
 assert result['pre_DC_candidate_exact_baseline']and not result['final_output_exact_baseline']
 target.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
if __name__=='__main__':main()
