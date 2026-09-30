"""Once-only frozen source/mirror domain checks. No undefined T(M) quality score."""
from pathlib import Path
import hashlib,json
import numpy as np
from model import source_mean,mirror,domain
HERE=Path(__file__).resolve().parent
def read(p):return json.loads(Path(p).read_text())
def ident(p):
 b=Path(p).read_bytes();return dict(path=str(p),bytes=len(b),sha256=hashlib.sha256(b).hexdigest())
def verify(r):a=ident(r['path']);assert(a['bytes'],a['sha256'])==(r['bytes'],r['sha256']),r['path']
def save(n,d):
 with(HERE/n).open('x',encoding='utf-8',newline='\n')as f:json.dump(d,f,indent=2,allow_nan=False);f.write('\n')
def main():
 assert not(HERE/'results.json').exists(),'Preserve completed result'
 freeze=read(HERE/'pre_evaluation_freeze.json');pins=freeze['files']+freeze['external_sources']
 for r in pins:verify(r)
 rows=[];(HERE/'retained_source_mirrors').mkdir()
 for c in read(HERE/'source_case_manifest.json')['cases']:
  with np.load(c['arrays']['path'])as z:
   O=z['raw'];ctrl=z['controls'];exp=z['exposure']if'exposure'in z.files else None
   for k,h in c['array_hashes'].items():assert hashlib.sha256(np.ascontiguousarray(z[k]).tobytes()).hexdigest()==h
   P,active,diag=source_mean(O,ctrl,exp);M=mirror(O,P)
   p=HERE/'retained_source_mirrors'/f'{c["index"]:02d}_{c["name"]}.npz';np.savez_compressed(p,P16=P,mirror=M,active=active)
   states=diag['frames'];invalid_metadata=sum(not r['metadata_valid']for r in states);dO,dP,dM=domain(O),domain(P),domain(M)
   rows.append(dict(name=c['name'],source_and_original_pairs_retained=c['arrays'],new_source_mirror_arrays=ident(p),source_SHA=c['array_hashes']['raw'],controls_SHA=c['array_hashes']['controls'],source_domain=dO,pilot_domain=dP,mirror_domain=dM,metadata_invalid_frames=invalid_metadata,active_frames=int(active.sum()),passthrough_frames=int((~active).sum()),passthrough_exact_raw_bits=P[~active].tobytes()==O[~active].tobytes(),source_diagnostics=diag,native_domain_feasibility_met=bool(dO['native_radiance_domain_met']and dP['native_radiance_domain_met']and dM['native_radiance_domain_met']and invalid_metadata==0),antithetic_quality_score=None,quality_score_status='N/A_T_M_unspecified_original24_operator_extension_missing',quality_accepted=False))
 for r in pins:verify(r)
 result=dict(status='COMPLETED_SOURCE_MIRROR_DOMAIN_FEASIBILITY_ANTITHETIC_RESPONSE_UNIDENTIFIED',rows=rows,quality_accepted=False,new_SDK_API=0,new_GPU_build=0,new_scores=0,source_pins_pre_post_unchanged=True,missing_response='All24 originalcases lackT(M); no invented mirrorresponse/affineextension orzeroqualitypass.',domain_met_count=sum(r['native_domain_feasibility_met']for r in rows),negative_mirror_case_count=sum(r['mirror_domain']['negative_finite_channel_elements']>0 for r in rows),nonfinite_mirror_case_count=sum(r['mirror_domain']['nonfinite_channel_elements']>0 for r in rows))
 save('results.json',result)
 compact=dict(status=result['status'],original_cases=24,antithetic_quality_score_NA_cases=24,native_domain_met_cases=result['domain_met_count'],mirror_negative_cases=result['negative_mirror_case_count'],mirror_nonfinite_cases=result['nonfinite_mirror_case_count'],metadata_unsupported_cases=[r['name']for r in rows if r['metadata_invalid_frames']],selfchecks_status=read(HERE/'selfcheck_results.json')['status'],identity_no_noise_benefit=True,retained_actual_input_and_P_M_array_sets=48,quality_accepted=False,new_SDK_GPU_build_scores=0,limits=read(HERE/'preregistration.json')['limits'])
 save('compact_report.json',compact)
 files=[ident(p)for p in sorted(HERE.rglob('*'))if p.is_file()and '__pycache__'not in p.parts]
 save('completion_manifest.json',dict(files=files,external_sources=freeze['external_sources'],self_entry_excluded=True,status='SEALED_SOURCE_DOMAIN_ONLY_OPERATOR_EXTENSION_GAP',actual_SDK_GPU_build_scores=0))
 print(json.dumps(compact));print(json.dumps({n:ident(HERE/n)for n in ['pre_evaluation_freeze.json','results.json','compact_report.json','completion_manifest.json']}))
if __name__=='__main__':main()
