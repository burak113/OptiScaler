"""Independent saved-byte RZ evidence review; no executable, device, or scorer call."""
from pathlib import Path
import hashlib, importlib.util, itertools, json, shlex, sys
import numpy as np
sys.dont_write_bytecode = True
HERE=Path(__file__).resolve().parent
BASE=HERE.parent
PREP=BASE/'fsrd_clean_roundtrip_diffuse_alpha_zero_preparation_20260930'
PRE=BASE/'fsrd_clean_roundtrip_diffuse_alpha_zero_prelaunch_review_20260930'
OLD=BASE/'fsrd_weak_material_clean_roundtrip_preparation_20260930'
def read(p): return json.loads(Path(p).read_text())
def ident(p):
 p=Path(p); h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''): h.update(b)
 return dict(path=str(p),bytes=p.stat().st_size,sha256=h.hexdigest())
def verify(r):
 a=ident(r['path']); assert (a['bytes'],a['sha256'])==(r['bytes'],r['sha256']),r['path']; return a
def save(n,d):
 with (HERE/n).open('x',encoding='utf-8',newline='\n') as f: json.dump(d,f,indent=2,allow_nan=False);f.write('\n')
def module(n,p):
 s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def main():
 assert not (HERE/'review.json').exists(), 'Preserve any prior attempt'
 pm=read(PRE/'completion_manifest.json')
 assert ident(PRE/'completion_manifest.json')['sha256']=='c7c9d714e1cafd60f79f3477b480bc5b8988eb494f6f93410275ff1633a7cd93'
 assert ident(PRE/'review.json')['sha256']=='c73f8d28ca97fa80a251b7635b517ef74908ead08de9a514b5c04970cddfa394'
 assert read(PRE/'review.json')['blocking_findings']==[]
 direct={}
 for r in pm['files']+pm['external_sources']:
  a=verify(r);direct[a['path']]=a
 direct[str(PRE/'completion_manifest.json')]=ident(PRE/'completion_manifest.json')
 inherited=pm['inherited_source_manifests']; assert len(inherited)==1
 anchor=inherited[0];verify(anchor);expanded=read(anchor['path'])[anchor['records_key']]
 assert len(expanded)==anchor['record_count']==2252
 for r in expanded:verify(r)
 pins={
 'fsrd_diffuse_alpha_zero_root_tool_observations_20260930.json':'c0dde96a9a4dc8f886c58e6965fb55f5f24107bc8c51c4090013d6c3b48da0ee',
 'fsrd_diffuse_alpha_zero_root_authorization_20260930.json':'b8799dbc80ec0f8a9d0f0dd9be042a9cd6df3b2cd652cada6e488f18ba22a503',
 'fsrd_diffuse_alpha_zero_root_preflight_attempt1_20260930.json':'89f7e7ce95fdb0377e8bd6bc2da3cc5aa6d5fd66fa024becf6ebabe239995483'}
 for n,h in pins.items():
  a=ident(BASE/n);assert a['sha256']==h;direct[a['path']]=a
 obs=read(BASE/'fsrd_diffuse_alpha_zero_root_tool_observations_20260930.json')
 auth=read(BASE/'fsrd_diffuse_alpha_zero_root_authorization_20260930.json')
 failed=read(BASE/'fsrd_diffuse_alpha_zero_root_preflight_attempt1_20260930.json')
 assert failed['tool_chunk']=='95d296' and failed['actual_new_GPU_helpers_native_API']==0 and failed['producer_or_review_changes'] is False
 assert 'KeyError: repetitions' in failed['error']
 for r in auth['exact_preparation_pins']+[auth['root_verifier'],obs['execution'],obs['comparison']]:
  a=verify(r);direct[a['path']]=a
 attempt=BASE/'authorize_fsrd_diffuse_alpha_zero_20260930_attempt1.py';direct[str(attempt)]=ident(attempt)
 assert [x['exit_code'] for x in obs['observed_tools']]==[1,0,0,0]
 reg=read(PREP/'registration.json');execution=read(PREP/'execution_results.json');comparison=read(PREP/'alpha_zero_comparison.json')
 assert len(execution['jobs'])==len(reg['jobs'])==2
 law=module('RZ_post_law',PREP/'helper_work_accounting.py')
 guardlaw=module('RZ_post_guard',PREP/'helper_guard_evidence.py')
 workrows=[]
 for j,row in zip(reg['jobs'],execution['jobs']):
  assert row['arm']==j['arm']
  folder=Path(j['job']).parent
  lines=[shlex.split(x) for x in Path(j['job']).read_text().splitlines()]
  assert lines[0][2:]==['128','80','11','3','1']
  assert len(lines)==15 and len(j['outputs'])==3
  guard,error,artifact=guardlaw.load_guard_best_effort(folder,row['guard_artifact']['returned_guard_claim'],None)
  assert guard==row['guard']==read(folder/'resource_guard.json')
  assert error is None and artifact==row['guard_artifact'] and not artifact['returned_stored_conflict']
  work=law.accounting(folder,j['outputs'],guard,error,fresh_scope_authenticated=True)
  assert work==row['work']
  assert work['exact_helper_child_total']==work['exact_shader_dispatch_total']==work['confirmed_fence_completions_lower_bound']==1
  assert work['metadata_accepted'] and work['explicit_post_fence_stdout_proof'] and row['completed_accepted']
  assert work['fields']['diagnostic']==dict(errors=0,warnings=0) and work['fields']['timing']['debug_layer']==1
  assert (folder/'stderr.log').read_bytes()==b'' and guard['returncode']==0
  assert guard['timeout_seconds']==240 and guard['maximum_working_set_bytes']==2**31 and guard['minimum_available_memory_bytes']==2**30
  for n in ['resource_guard.json','stdout.log','stderr.log']+[f'out{i}.bin' for i in range(3)]:
   a=ident(folder/n);direct[a['path']]=a
  workrows.append(dict(arm=j['arm'],PID=guard['child_pid'],helper=1,explicit_post_fence_dispatch=1,metadata_accepted=True,diagnostic_errors=0,diagnostic_warnings=0,guard_authority=artifact['authority'],stdout_sha256=work['stdout_sha256'],stderr_sha256=work['stderr_sha256']))
 for k in ['executor_job_invocations_started','helper_children_lower_bound','confirmed_shader_dispatches_lower_bound','confirmed_fence_completions_lower_bound','exact_helper_total','exact_shader_dispatch_total','metadata_accepted_jobs','completed_accepted_jobs']:assert execution[k]==2,k
 assert execution['actual_new_native_contexts']==execution['actual_new_native_API']==0
 temp=PREP/'execution_TEMP';assert Path(execution['environment']['TMP']).resolve()==Path(execution['environment']['TEMP']).resolve()==temp.resolve() and PREP.resolve() in temp.resolve().parents
 assert execution['environment']['OPENBLAS_NUM_THREADS']=='1'
 arms=('RZ0','RZ1','R0','R1');arrays={}
 for arm in arms:
  arrays[arm]=[]
  for i,r in enumerate(comparison['output_records'][arm]):
   a=verify(r);direct[a['path']]=a
   b=Path(r['path']).read_bytes();assert len(b)==[81920,81920,163840][i]
   arrays[arm].append(np.frombuffer(b,'<u2' if i<2 else '<u4').reshape(80,128,4))
 pairs=[]
 for a,b in itertools.combinations(arms,2):
  outputs=[]
  for i,(x,y) in enumerate(zip(arrays[a],arrays[b])):
   outputs.append(dict(slot=i,format=10 if i<2 else 3,full_RGBA_serialized_bits_exact=x.tobytes()==y.tobytes(),RGB_bits_exact=x[...,:3].tobytes()==y[...,:3].tobytes(),alpha_bits_exact=x[...,3].tobytes()==y[...,3].tobytes(),differing_channel_elements=int(np.count_nonzero(x!=y))))
  pairs.append(dict(arms=[a,b],outputs=outputs))
 assert pairs==comparison['pairs'] and len(pairs)==6
 assert all(o['full_RGBA_serialized_bits_exact'] and o['RGB_bits_exact'] and o['alpha_bits_exact'] and o['differing_channel_elements']==0 for p in pairs for o in p['outputs'])
 assert comparison['new_SDK_API']==comparison['new_scores']==0 and comparison['no_64_measured_series']
 before=list(direct.values())
 for r in before+expanded:verify(r)
 unique=len({str(Path(r['path']).resolve()).lower() for r in before+expanded})
 limits=[
 'Two new helper observations of one static full graph, plus two historical observations; not a measured64-frame roundtrip series.',
 'Actual pinned CSO colorRGB is unchanged for this graph when t2 diffuseA65504 becomes positive0. This closes this graph alphaRGB confound only; it does not establish privateSDK, general shader, or game correctness.',
 'All auxiliary buffers are bit-exact, but WriteHistory0 active-path auxiliary UAVs may be unwritten; byte equality is not proof of writes or semantic validity.',
 'Timing is post-fence in the pinned source reference; historical EXE and CSO bytes are authenticated, but no fresh compile linkage is invented.',
 'No scoring/model/threshold changes or new scoring calls; output sizes alone are not dispatch proof.'
 ]
 report=dict(status='PASSED_DIFFUSE_ALPHA_ZERO_RAW_EVIDENCE_REVIEW',blocking_findings=[],physical_new_work=dict(helper_children=2,explicit_helper_Dispatches=2,post_fence_helpers=2,metadata_accepted_jobs=2,outputs=6,new_SDK_contexts=0,new_SDK_API=0),source_validation=dict(direct_pre_post=len(before),inherited_pre_post=2252,expanded_unique=unique,prelaunch_producer_and_review_stable=True,inherited_manifest_pinned_once=True),root_chronology=dict(initial_CPU_preflight_error=failed,then_corrected_authorization=True,producer_unchanged=True,once_original_bits_analyzer_observed=True,no_separate_analyzer_log_claim=True),work=workrows,pairs=pairs,color_RGB_alpha_caveat_closed_for_this_static_graph=True,limitations=limits,quality_accepted=False,game_run=False,review_actual_GPU_native_build_score=0)
 save('review.json',report)
 save('compact.json',dict(status=report['status'],blocking_findings=[],physical_new_work=report['physical_new_work'],source_validation=report['source_validation'],unordered_pairs=6,output_comparisons=18,all_RGBA_RGB_alpha_bits_exact=True,differing_channel_elements=0,limitations=limits,quality_accepted=False))
 save('completion_manifest.json',dict(status='SEALED_INDEPENDENT_RZ_POSTREVIEW',files=[ident(HERE/n) for n in ['review_cpu.py','review.json','compact.json']],external_sources=before,inherited_source_manifests=inherited,expanded_unique_record_count=unique,self_entry_excluded=True,review_actual_GPU_native_build_score=0))
 print(json.dumps(dict(status=report['status'],direct=len(before),inherited=2252,expanded_unique=unique,files=3,review=ident(HERE/'review.json'),compact=ident(HERE/'compact.json'),manifest=ident(HERE/'completion_manifest.json'))))
if __name__=='__main__':main()
