"""Independent bounded CPU audit. Reads producer only; no native/helper/build/scorer."""
from pathlib import Path
import ast,hashlib,itertools,json,shlex,shutil,struct,subprocess,sys
import numpy as np
sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
PREP=HERE.parent/'fsrd_clean_specular_hit_alpha_contrast_preparation_20260930'
OLD=HERE.parent/'fsrd_weak_material_clean_native_preparation_20260930'
EXPECTED={'prelaunch_ready_manifest.json':'8fa973050ac156ef3895e9c7e9deaf61fe0dfa3552626d8d0eb9eaea5c1d2295','completion_manifest.json':'b025ca512ceb2f8a89633346aa41d60633116d295e851967fa874f78355bc81d','registration.json':'fb300d09a738fed1b946b0e14c64c91a2c73c1f9eebe418aed1cd069d12237b2','pre_native_freeze.json':'5afd215fc53a4175dbca1063fb735afb8eede838727abb9cb336a86b0cbb6ae3'}
def rec(p):
 p=Path(p).resolve();h=hashlib.sha256()
 with p.open('rb')as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return dict(path=str(p),bytes=p.stat().st_size,sha256=h.hexdigest())
def read(p):return json.loads(Path(p).read_text())
def save(n,v):
 with(HERE/n).open('x',encoding='utf-8',newline='\n')as f:json.dump(v,f,indent=2,allow_nan=False);f.write('\n')
def gather(obj,records):
 if isinstance(obj,dict):
  if all(k in obj for k in('path','bytes','sha256'))and isinstance(obj['path'],str)and isinstance(obj['bytes'],int)and isinstance(obj['sha256'],str):
   r={k:obj[k]for k in('path','bytes','sha256')};p=str(Path(r['path']).resolve());r['path']=p
   if p in records:assert records[p]==r,'Conflicting source pin '+p
   records[p]=r
  for v in obj.values():gather(v,records)
 elif isinstance(obj,list):
  for v in obj:gather(v,records)

report=dict(status='REVIEW_RUNNING_CPU_ONLY',blocking_findings=[],checks={},actual_new_native_GPU_build_scores=0,
 reviewer_IO_qualification='Initial read used guessed producer readiness.json and returned file missing. Correct sealed artifact is prelaunch_ready_manifest.json; reviewer lookup error only, no producer mutation or launch.')
try:
 for n,h in EXPECTED.items():assert rec(PREP/n)['sha256']==h,n
 reg=read(PREP/'registration.json');freeze=read(PREP/'pre_native_freeze.json');ready=read(PREP/'prelaunch_ready_manifest.json');completion=read(PREP/'completion_manifest.json');reuse=read(PREP/'source_reuse.json')
 assert reg['status']=='PREPARED_CPU_ONLY_NOT_AUTHORIZED_NATIVE'
 records={}
 for obj in(reg,freeze,ready,completion,reuse):gather(obj,records)
 expanded_path=Path(reuse['expanded_reviewed_provenance_manifest']['path'])
 expanded=read(expanded_path);gather(expanded,records) # Existing expanded manifest read once; unique bytes verified once.
 for p,r in records.items():assert rec(p)==r,p
 before_digest=hashlib.sha256(json.dumps(sorted(records.values(),key=lambda r:r['path']),sort_keys=True).encode()).hexdigest()
 report['source_verification']=dict(unique_records=len(records),existing_expanded_manifest=rec(expanded_path),expanded_manifest_reads=1,table_not_duplicated=True,unique_index_sha256=before_digest)
 report['checks']['producer_expected_seals_and_unique_sources_before']=True
 for obj,n in((freeze,'pre_native_freeze.json'),(ready,'prelaunch_ready_manifest.json'),(completion,'completion_manifest.json')):
  assert not any(Path(r['path']).resolve()==(PREP/n).resolve()for r in obj['files']),n+' self entry'
 assert reg['fixed_order']==['A0_r0','A10_r0','A10_r1','A0_r1']
 assert [c['tag']for c in reg['cases']]==reg['fixed_order']
 assert [c['specular_input_A']for c in reg['cases']]==[0,10,10,0]
 assert reg['input_formats']==[41,10,24,28,28,10,10]and reg['input_upload_counts']==[1]*7
 assert reg['six_tuning_values']==[.1,.5,.5,40000.,40.,.5]
 assert reg['runner']['sha256']=='3427689a4764380f885545c353250277e4d71944d3310c8a17b3cbba0f3c21d2'
 assert reg['source_reference']['sha256']=='f6cfbecc4704d7f4f891f5c2ae88baf69546a316a9738ed03da0413d6ef0d077'
 assert reg['provider']['sha256']=='48f1e5888ba6a0a3d59a98b9751e37c392b0f7b8c223d0082d5c1f40642879d3'
 originals=[(OLD/'inputs'/f'input{i}.bin').read_bytes()for i in range(7)]
 assert list(map(len,originals))==[40960,81920,40960,40960,40960,81920,81920]
 original_words=np.frombuffer(originals[6],'<u2').reshape(80,128,4);assert np.all(original_words[...,3]==0)
 expected_controls=(OLD/'planned_native/C0/dispatch_controls.bin').read_bytes();assert len(expected_controls)==64*184
 for f in range(64):
  packet=expected_controls[f*184:(f+1)*184]
  assert struct.unpack_from('<II',packet)==(f,3 if f==0 else 2)
  assert struct.unpack_from('<II',packet,8)==(128,80)
  assert struct.unpack_from('<3f',packet,16)==(1.,1.,1.)
  assert struct.unpack_from('<3f',packet,28)==(0.,0.,0.)
  assert struct.unpack_from('<2f',packet,40)==(0.,0.)
  assert struct.unpack_from('<2f',packet,48)==(0.,1024.)
 controls_text=(OLD/'planned_native/C0/frame_controls.txt').read_bytes()
 mutations=[];runtime=[]
 runtime_names=('resource_guard.json','stdout.log','stderr.log','stage_events.jsonl','recorded_frame_indices.bin','queued_frame_indices.bin','completed_frame_indices.bin','observed_frame_indices.bin','output_presence.bin','dispatch_controls.bin','diffuse.bin','specular.bin','native_work_accounting.json','executor_attempt.json')
 for c in reg['cases']:
  folder=Path(c['job']).parent;rows=[shlex.split(x)for x in Path(c['job']).read_text().splitlines()]
  assert c['command']==[reg['runner']['path'],c['job']]and folder.is_dir()
  assert len(rows)==9 and rows[0][:8]==['128','80','64','2','32','0','1','0']and Path(rows[0][8]).resolve()==Path(reg['provider']['path']).resolve()
  assert [int(r[1])for r in rows[1:8]]==reg['input_formats']and[int(r[2])for r in rows[1:8]]==[1]*7
  assert rows[8]==[str(folder/'diffuse.bin').replace('\\','/'),str(folder/'specular.bin').replace('\\','/')]
  assert c['source_frame_indices']==list(range(64))and c['input_upload_counts']==[1]*7 and c['camera_override']=='absent'
  assert not(folder/'camera.txt').exists()
  assert(folder/'frame_controls.txt').read_bytes()==controls_text
  assert(folder/'expected_applied_dispatch_controls.bin').read_bytes()==expected_controls
  assert rec(folder/'expected_applied_dispatch_controls.bin')==c['expected_controls']
  actual=[Path(r[0]).read_bytes()for r in rows[1:8]]
  assert actual[:6]==originals[:6]
  for r,row in zip(c['inputs'],rows[1:8]):assert rec(row[0])==r
  words=np.frombuffer(actual[6],'<u2').reshape(80,128,4)
  assert words[...,:3].tobytes()==original_words[...,:3].tobytes()
  assert np.all(words[...,3]==(0 if c['specular_input_A']==0 else 0x4900))
  changed=np.flatnonzero(np.frombuffer(actual[6],'u1')!=np.frombuffer(originals[6],'u1'))
  if c['specular_input_A']==0:assert len(changed)==0
  else:assert np.array_equal(changed,np.arange(10240)*8+7)
  mutations.append(dict(tag=c['tag'],dose=c['specular_input_A'],input6_RGB_exact=True,other6_full_bytes_exact=True,changed_bytes=len(changed),controls64x184_exact=True))
  for n in runtime_names:
   p=folder/n;assert not p.exists(),str(p);runtime.append(str(p))
  assert sorted(p.name for p in folder.iterdir())==['expected_applied_dispatch_controls.bin','frame_controls.txt','job.txt']
 for n in('execution_results.json','raw_comparisons.json'):assert not(PREP/n).exists()
 for n in('execution_TEMP','quarantine'):
  p=(PREP/n).resolve();assert p.is_dir()and not any(p.iterdir())and p.drive.upper()=='F:'and PREP.resolve()in p.parents
 assert reg['guards']==dict(timeout_seconds=240,maximum_working_set_bytes=2147483648,minimum_available_memory_bytes=1073741824,sample_interval_seconds=.2,TEMP_TMP=str((PREP/'execution_TEMP').resolve()),single_owned_sequential_child=True)
 report['checks'].update(only_input6_A_mutation=True,full7_formats_counts_bytes=True,all256_expected184_controls_and_flags_exact=True,four_fresh_order_0_10_10_0=True,owned_F_TEMP_empty=True,all56_runtime_targets_absent=True)
 report['payload_summary']=mutations
 # No producer program imports: reconstruct the exact permitted adapter diff.
 olddriver=(OLD/'run_native.py').read_text();expected=olddriver
 for a,b in[('--execute-clean-native','--execute-native'),('genuine-clean-two-fresh-contexts-native-raw-only','clean-specular-hit-alpha-four-fresh-contexts-native-raw-only'),("==2 and report['totals_unknown_children']","==4 and report['totals_unknown_children']"),("all(v==128 for v in report['counts'].values())","all(v==256 for v in report['counts'].values())"),('completed_clean_native_raw_only_not_composed_not_quality_accepted','completed_specular_alpha_native_raw_only_not_composed_not_quality_accepted')]:
  assert expected.count(a)==1,a;expected=expected.replace(a,b)
 expected=expected.replace('Frozen future clean-only native executor. Preparation never imports/calls main.','Frozen future alpha-contrast executor. Root must verify sealed R/RZ gates and authorize; preparation never calls main.')
 driver=(PREP/'run_native.py').read_text();assert expected==driver
 assert driver.index('checkpoint() # physical work')<driver.index('if error:raise')<driver.index("assert not guard['guard_load_evidence']['errors']")
 assert driver.index("fresh_runtime(Path(c['job']).parent)")<driver.index('from native_resource_guard import run_guarded')
 for n in('native_resource_guard.py','native_work_accounting.py','executor_evidence.py','check_accounting_cpu.py'):assert(PREP/n).read_bytes()==(OLD/n).read_bytes()
 for p in PREP.glob('*.py'):ast.parse(p.read_text(),filename=str(p))
 analyzer=(PREP/'analyze_raw_cpu.py').read_text();assert 'itertools.combinations'in analyzer and "quality_scores=None"in analyzer and 'composition_results=None'in analyzer and "'within_dose_repeat'"in analyzer
 assert 'np.broadcast_to'not in analyzer and 'score('not in analyzer
 report['checks'].update(EXE_provider_source_unchanged=True,all4_accounting_modules_byte_exact=True,executor_exact_whitelist_only=True,physical_work_checkpoint_before_metadata=True,analyzer_6pairs12lobes_descriptive_only=True)
 # Twelve existing metadata-only probes replayed using exact copies in review ownership.
 replay=HERE/'SIMULATED_replay';replay.mkdir(exist_ok=False)
 for n in('native_work_accounting.py','executor_evidence.py','check_accounting_cpu.py'):shutil.copyfile(PREP/n,replay/n)
 proc=subprocess.run([sys.executable,'-B',str(replay/'check_accounting_cpu.py')],cwd=replay,capture_output=True)
 (HERE/'SIMULATED_replay.stdout.bin').write_bytes(proc.stdout);(HERE/'SIMULATED_replay.stderr.bin').write_bytes(proc.stderr)
 assert proc.returncode==0,proc.stderr.decode(errors='replace')
 result=read(replay/'CPU_accounting_checks.json');assert len(result['checks'])==12 and result['all_passed']and all(c['passed']for c in result['checks'])
 producer_tests=read(PREP/'CPU_accounting_checks.json');assert[c['name']for c in result['checks']]==[c['name']for c in producer_tests['checks']]
 # Results contain path-derived artifact hashes/paths, so compare core contracts only.
 core=('counts','exact_totals','totals_unknown','created_context_confirmed','completed_context_confirmed','created_context_physical_lowerbound','completed_context_physical_lowerbound','terminal_stdout_claim','evidence_disagreements','authority')
 for x,y in zip(result['checks'],producer_tests['checks']):
  for k in core:assert x['result'][k]==y['result'][k],x['name']+':'+k
 report['checks']['existing12_SIM_independent_replay_passed']=True
 report['SIM_replay']=dict(probes=12,passed=12,native_GPU_build_scores=0,result=rec(replay/'CPU_accounting_checks.json'),stdout=rec(HERE/'SIMULATED_replay.stdout.bin'),stderr=rec(HERE/'SIMULATED_replay.stderr.bin'))
 for p,r in records.items():assert rec(p)==r,p
 for p in runtime:assert not Path(p).exists(),p
 for n,h in EXPECTED.items():assert rec(PREP/n)['sha256']==h,n
 report['checks']['all_unique_sources_and_runtime_absence_stable_after']=True
 report['producer_seals']={n:rec(PREP/n)for n in EXPECTED}
 report['status']='READY_FOR_ROOT_SPECULAR_HIT_ALPHA_CONTRAST_AUTHORIZATION_SUBJECT_TO_FINAL_RZ_GATE'
 report['required_external_gates']=dict(R='PASSED_SEALED_AND_PINNED_IN_PREPARATION',RZ='Final independent RZ postreview and completion seal must be passed and pinned by separate immutable root preauthorization; this audit does not assume that pass.',root_authorization='Root must verify R/RZ/prelaunch seals and reconsideration before executing; CLI flag and preparation READY do not enforce these external gates by themselves.')
 report['planned_only_if_completed']=reg['planned_only_if_all_completed']
 report['limits']=['+10 is a view-depth proxy, not traced ray length; no positive minimum or private-provider zero contract is established.','Public indirect specular A is hit distance; changing only A tests native sensitivity for this synthetic cohort, not API violation or game cause.','B342 source is a byte-pinned historical reference; no new build/source-to-EXE equivalence is proved. Original serial lifecycle/output initialization remains unchanged.','Unique legal stdout64 footer after full loop/DestroyContext provides source-qualified physical totals under current child evidence; warnings/errors remain acceptance blockers after work checkpoint. Missing footer only proves readback-prefix lowerbounds, not unseen API/queued/discard totals. Controls precede API and never prove success.','Fresh unknown guard retains physical lowerbounds with process identity/exact totals unknown; explicit no-child and canonical direct-return contradictions remain conservative.','No composition or quality scores are planned by this raw native contrast; all6 pair12lobe RGB/RGBA output comparisons are descriptive.']
except BaseException as e:
 report['status']='BLOCKED_PRELAUNCH_REVIEW';report['blocking_findings'].append(type(e).__name__+': '+str(e))
save('review.json',report)
print(json.dumps(dict(status=report['status'],blockers=report['blocking_findings'],review=rec(HERE/'review.json'))))
if report['blocking_findings']:raise SystemExit(1)
