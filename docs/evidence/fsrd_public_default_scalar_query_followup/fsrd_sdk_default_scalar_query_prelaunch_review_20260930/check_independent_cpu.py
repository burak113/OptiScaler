"""Eight bounded SIMULATED fixed-probe regressions; no SDK or launcher."""
from pathlib import Path
import json,sys
sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE/'SIMULATED_REPLAY'))
from check_query_cpu import make
from query_accounting import derive
YES=dict(child_pid=123,status='completed',returncode=0)
FAILED=dict(child_pid=123,status='failed_or_terminated',returncode=1)
root=HERE/'SIMULATED_INDEPENDENT';root.mkdir()
rows=[]
def event(v):return b'QUERY_EVENT '+json.dumps(v).encode()+b'\n'
def decoded(line):return json.loads(line[len(b'QUERY_EVENT '):])
def test(n,lines,raw,g,predicate):
 p=root/n;p.mkdir();(p/'stdout.log').write_bytes(b''.join(lines));(p/'stderr.log').write_bytes(b'');(p/'query_values.bin').write_bytes(raw)
 r=derive(p,g);assert predicate(r),n;rows.append(dict(name=n,SIMULATED=True,passed=True,result=r))
complete,raw=make()
bad=complete.copy();v=decoded(bad[-1]);v['rr_dispatch']=64;bad[-1]=event(v)
test('impossible_RR64_never_work',bad,raw,YES,lambda r:not r['accepted']and r['totals_unknown']and r['counts_lower_bound']['rr_dispatch']==0 and r['counts_lower_bound']['query_ok']==6)
bad=complete.copy();bad[-1]=bad[-1].replace(b'"v": 1',b'"v": 1, "v": 1',1)
test('duplicate_JSON_key_retains_prior_work',bad,raw,YES,lambda r:not r['accepted']and r['totals_unknown']and r['counts_lower_bound']['query_ok']==6)
bad=complete.copy();bad[-1]=bad[-1][:-3]+b'\n'
test('malformed_JSON_footer_retains_prior_work',bad,raw,YES,lambda r:not r['accepted']and r['totals_unknown']and r['counts_lower_bound']['destroyed']==1)
bad=complete.copy();m=json.loads(bad[1][len(b'QUERY_META '):]);m['width']=129;bad[1]=b'QUERY_META '+json.dumps(m).encode()+b'\n'
test('context_metadata_mismatch_preserves_returned_work',bad,raw,YES,lambda r:not r['accepted']and not r['metadata_source_matches']and r['exact_returned_totals']and r['counts_lower_bound']['query_ok']==6)
test('raw_float_tamper_preserves_returned_work',complete,raw[:-1]+b'\x01',YES,lambda r:not r['accepted']and not r['raw_output_matches_returned_bits']and r['counts_lower_bound']['query_ok']==6)
bad=complete.copy();v=decoded(bad[-1]);v.update(stage='failed',accepted=False,d3d_warnings=1);bad[-1]=event(v)
test('ordinary_warning_rejection_preserves_work',bad,raw,FAILED,lambda r:not r['accepted']and r['exact_returned_totals']and r['counts_lower_bound']['query_ok']==6 and r['terminal_claim']['d3d_warnings']==1)
# Source-reachable failed Create with non-null pointer: no speculative Destroy.
bad=complete[:4];v=decoded(bad[-1]);v.update(rc=6,created=0,ownership_uncertain=True);bad[-1]=event(v)
v.update(seq=3,stage='failed',key=0,rc=0,nonnull=False,bits=0,accepted=False);bad.append(event(v))
test('failed_Create_nonnull_keeps_ownership_uncertain',bad,b'',FAILED,lambda r:not r['accepted']and r['exact_returned_totals']and r['counts_lower_bound']['created']==0 and r['counts_lower_bound']['create_returned']==1 and r['counts_lower_bound']['destroy_entry']==0 and r['terminal_claim']['ownership_uncertain'])
# Source-reachable failed Destroy: exactly one attempt; not successful cleanup.
bad=complete.copy();v=decoded(bad[-2]);v.update(rc=6,nonnull=True,destroyed=0,ownership_uncertain=True);bad[-2]=event(v)
v=decoded(bad[-1]);v.update(stage='failed',accepted=False,destroyed=0,ownership_uncertain=True);bad[-1]=event(v)
test('failed_Destroy_keeps_ownership_uncertain',bad,raw,FAILED,lambda r:not r['accepted']and r['exact_returned_totals']and r['counts_lower_bound']['destroy_entry']==r['counts_lower_bound']['destroy_returned']==1 and r['counts_lower_bound']['destroyed']==0 and r['terminal_claim']['ownership_uncertain'])
with(HERE/'independent_checks.json').open('x',encoding='utf-8',newline='\n')as f:
 json.dump(dict(status='PASSED_BOUNDED_INDEPENDENT_FIXED_PROBE_CHECKS',SIMULATED=True,passed=len(rows),failed=0,rows=rows,actual_SDK_queries=0,actual_native_RR=0,actual_GPU_jobs=0,actual_builds=0,actual_scores=0),f,indent=2);f.write('\n')
print(json.dumps(dict(SIMULATED_checks_passed=len(rows),actual_queries=0)))
