"""CPU-only native-alpha composition preparation; no helper, SDK, build or score calls."""
from pathlib import Path
import ast,difflib,hashlib,json,shlex,struct,subprocess,sys
sys.dont_write_bytecode=True
ROOT=Path('F:/OptiRevelations/OptiScaler-ffxD-alpha');T=ROOT/'tools_tmp';HERE=Path(__file__).resolve().parent
OLD=T/'fsrd_weak_material_clean_composition_preparation_20260930';OP=T/'fsrd_weak_material_clean_composition_postrun_review_20260930'
NATIVE=T/'fsrd_clean_specular_hit_alpha_contrast_preparation_20260930';NP=T/'fsrd_clean_specular_hit_alpha_contrast_postrun_review_20260930'
ARMS=('A0_r0','A10_r0','A0_r1');IFMT=[10,28,10,28,10,24,10,41,10,10,3];OFMT=[10,10,3];BPP={10:8,28:4,24:4,41:4,3:16}
def ident(p):
 p=Path(p);b=p.read_bytes();return dict(path=str(p.resolve()),bytes=len(b),sha256=hashlib.sha256(b).hexdigest())
def read(p):return json.loads(Path(p).read_text())
def write(p,b):
 with Path(p).open('xb')as f:f.write(b)
def save(n,v):write(HERE/n,(json.dumps(v,indent=2,allow_nan=False)+'\n').encode())
def clone(a,b):Path(b).parent.mkdir(parents=True,exist_ok=True);write(b,Path(a).read_bytes());assert ident(a)['sha256']==ident(b)['sha256']
def q(p):return '"'+Path(p).resolve().as_posix()+'"'
def verify(rs):
 for r in rs:
  actual=ident(r['path']);assert all(actual[k]==r[k]for k in('path','bytes','sha256')),r['path']
def change(s,a,b,count=1):assert s.count(a)==count,a;return s.replace(a,b)
def diff(n,a,b):write(HERE/n,''.join(difflib.unified_diff(a.splitlines(True),b.splitlines(True),fromfile='reviewed_clean_composition',tofile='alpha_three_trace_composition')).encode())
def main():
 assert not(HERE/'registration.json').exists(),'Preserve earlier preparation.'
 old=read(OLD/'registration.json');op=read(OP/'review.json');nreg=read(NATIVE/'registration.json');nr=read(NATIVE/'execution_results.json')
 assert op['status']=='PASSED_CLEAN_COMPOSITION_EVIDENCE_AND_EXACT_METRIC_REVIEW'and not op['blocking_findings']
 assert ident(NP/'review.json')['sha256']=='3bf5116b7030bce0ed3a59620c017bebf1b088558a893bddc1779f8d0a53dfad'
 assert ident(NP/'completion_manifest_final.json')['sha256']=='722aedb3f81256afb5015286021c4cf70b695338e16ab34543227e450dcb8ab4'
 ngate=read(NP/'review.json');assert ngate['status']=='PASSED_SPECULAR_HIT_ALPHA_NATIVE_RAW_EVIDENCE_REVIEW'and not ngate['blocking_findings']
 rootobs=T/'fsrd_specular_hit_alpha_root_tool_observations_20260930.json'
 assert ident(rootobs)['sha256']=='53be003c8c0a41695467623fb1a25e5ca82e5bc9d36129493adfbce58ff5182d'
 assert nr['accepted_contexts']==nr['contexts_created_confirmed']==nr['contexts_completed_confirmed']==4 and nr['totals_unknown_children']==0
 assert all(v==256 for v in nr['counts'].values())
 inherited=[OP/'completion_manifest.json',NP/'completion_manifest_final.json']
 sources=[*inherited,OP/'review.json',OP/'compact.json',NP/'review.json',rootobs,NATIVE/'registration.json',NATIVE/'execution_results.json',NATIVE/'raw_comparisons.json',
  OLD/'registration.json',OLD/'readiness.json',OLD/'run_composition_only.py',OLD/'analyze_composed_cpu.py',OLD/'check_preparation_cpu.py',OLD/'source_mapping.json']
 ncases={c['tag']:c for c in nreg['cases']};actual={r['tag']:r for r in nr['jobs']};lobes={}
 controls=(Path(ncases['A0_r0']['job']).parent/'dispatch_controls.bin').read_bytes()
 assert len(controls)==64*184
 for tag,c in ncases.items():
  folder=Path(c['job']).parent;assert(folder/'dispatch_controls.bin').read_bytes()==controls==(folder/'expected_applied_dispatch_controls.bin').read_bytes()
  footer=[v for v in(folder/'stdout.log').read_bytes().splitlines()if v.startswith(b'dispatches=')]
  assert footer==[b'dispatches=64 validation_errors=0 validation_warnings=0 sdk_errors=0 sdk_warnings=0']
  assert actual[tag]['accepted']and actual[tag]['work']['exact_totals']
  lobes[tag]={}
  for name in('diffuse.bin','specular.bin'):
   p=folder/name;verify([actual[tag]['outputs'][name]]);b=p.read_bytes();assert len(b)==64*128*80*8;lobes[tag][name]=b;sources.append(p)
  sources.extend(folder/n for n in('job.txt','stdout.log','stderr.log','dispatch_controls.bin','resource_guard.json','native_work_accounting.json'))
 assert all(lobes['A10_r0'][n]==lobes['A10_r1'][n]for n in('diffuse.bin','specular.bin'))
 assert any(lobes['A0_r0'][n]!=lobes['A0_r1'][n]for n in('diffuse.bin','specular.bin'))
 save('native_trace_selection.json',dict(selected_actual_traces=list(ARMS),excluded_actual_trace='A10_r1',
  exclusion_basis='Saved fullRGBA byte equality of64diffuse and64specular frames to A10_r0.',
  actual_native_source_stage_existing_contexts=4,actual_native_source_stage_existing_API=256,new_native_contexts=0,new_native_API=0,
  equality={n:dict(A10_full64_RGBA_exact=True,left=ident(Path(ncases['A10_r0']['job']).parent/n),right=ident(Path(ncases['A10_r1']['job']).parent/n))for n in('diffuse.bin','specular.bin')},
  qualifier='Only3 traces receive64 actual composition jobs each. No fourth measured composition,256-composition claim, physical-ray inference or64 independent-noise samples. Input equality mapping is qualified; composition process behavior is not measured for A10_r1.'))
 for name in('fsrd_gpu_runner.exe','helper_source_reference.cpp','historical_gpu_runner.build.cmd','helper_work_accounting.py','helper_guard_evidence.py','native_resource_guard.py'):
  clone(OLD/name,HERE/name);sources.append(OLD/name)
 for name in('FSRDOutputComp_Shader.cso','FSRDOutputComp.hlsl','FSRDPreprocessCommon.hlsli','FSRDFloorCommon.hlsli'):
  clone(OLD/'frozen_shader'/name,HERE/'frozen_shader'/name);sources.append(OLD/'frozen_shader'/name)
 assert ident(HERE/'native_resource_guard.py')['sha256']=='b70e18d0f13963e0250c371171933429446cf304041c9a16d971e9898d211814'
 metric_records=[];extract=[]
 for item in old['metric_function_extraction']:
  p=Path(item['source']);target=HERE/'frozen_metric_sources'/p.name;clone(p,target);sources.append(p)
  metric_records.append(ident(target));extract.append(dict(source=str(target),name=item['name']))
 sources.extend(Path(old[k]['path'])for k in('source_sequences','quantized_raw_reference','original_report'))
 oldjobs={(j['frame'],j['arm']):j for j in old['jobs']};jobs=[];mapping=[];stride=128*80*8
 for frame in range(64):
  template=oldjobs[frame,'C0'];rows=[shlex.split(s)for s in Path(template['job']).read_text().splitlines()]
  assert len(rows)==15 and rows[0][2:]==['128','80','11','3','1'];sources.append(Path(template['job']))
  verify(template['inputs']+[template['CB']]);cb=Path(rows[0][1]).read_bytes();assert len(cb)==96
  assert struct.unpack_from('<I',cb,16)[0]==8 and struct.unpack_from('<f',cb,20)[0]==0 and struct.unpack_from('<I',cb,52)[0]==0 and struct.unpack_from('<I',cb,64)[0]==0
  for arm in ARMS:
   folder=HERE/'planned_jobs'/f'{frame:02d}'/arm;folder.mkdir(parents=True,exist_ok=False)
   paths=[Path(r[0])for r in rows[1:12]]
   pieces={}
   for slot,name in((0,'specular.bin'),(2,'diffuse.bin')):
    piece=lobes[arm][name][frame*stride:(frame+1)*stride];p=folder/f'in{slot}.bin';write(p,piece);paths[slot]=p
    pieces[str(slot)]=dict(source=ident(Path(ncases[arm]['job']).parent/name),offset=frame*stride,bytes=stride,payload=ident(p))
   assert all(paths[i].read_bytes()==Path(rows[1+i][0]).read_bytes()for i in range(11)if i not in(0,2))
   outs=[dict(slot=i,path=str((folder/f'out{i}.bin').resolve()),bytes=128*80*BPP[fmt],format=fmt)for i,fmt in enumerate(OFMT)]
   text=[f'{q(HERE/"frozen_shader/FSRDOutputComp_Shader.cso")} {q(Path(rows[0][1]))} 128 80 11 3 1']
   text +=[f'{q(p)} 128 80 {fmt}'for p,fmt in zip(paths,IFMT)];text +=[f'{q(o["path"])} 128 80 {o["format"]}'for o in outs]
   write(folder/'job.txt',('\n'.join(text)+'\n').encode())
   jobs.append(dict(frame=frame,arm=arm,job=str(folder/'job.txt'),command=[str(HERE/'fsrd_gpu_runner.exe'),str(folder/'job.txt')],
    inputs=[dict(slot=i,format=fmt,**ident(p))for i,(p,fmt)in enumerate(zip(paths,IFMT))],CB=ident(Path(rows[0][1])),outputs=outs,repetitions=1,explicit_shader_Dispatches_planned_only=1))
   mapping.append(dict(frame=frame,arm=arm,old_C0_job=ident(Path(template['job'])),changed_SRV_slots=[0,2],all_other9_inputs_fullbyte_exact=True,
    CB96_byte_exact=True,Flags8=True,Detail0=True,HistoryValid0=True,WriteHistory0=True,native_actual_fullRGBA_slices=pieces))
 save('graph_and_lobe_mapping.json',dict(records=mapping,retained_all_original192_composition_jobs=True,old_files_edited=False,new_helper_GPU_native_build_scores=0))
 olddriver=(OLD/'run_composition_only.py').read_text();driver=olddriver
 driver=change(driver,"('observed_control','C0','C1')",repr(ARMS))
 driver=change(driver,' replay_passed=set()\n','')
 driver=change(driver,"   if job['arm']!='observed_control':assert job['frame']in replay_passed,'Observed replay must pass before clean arm'\n",'   verify(job[\'inputs\']);verify([job[\'CB\']]) # Exact inherited fixed inputs checked before child.\n')
 start=driver.index("   if job['arm']=='observed_control':");end=driver.index('   # All three raw outputs retained;',start)
 driver=driver[:start]+driver[end:]
 driver=change(driver," and report['observed_replay_accepted_frames']==64", " and report['observed_replay_accepted_frames']==0")
 driver=change(driver,"observed_replay_accepted_frames=0,completed_accepted_jobs", "observed_replay_accepted_frames=0,inherited_prior_observed_replay_passed_frames=64,completed_accepted_jobs")
 write(HERE/'run_composition_only.py',driver.encode());diff('executor_adaptation.diff',olddriver,driver)
 # Reuse the exact six simulation block. Remove the scorer block, not run it.
 oldcheck=(OLD/'check_preparation_cpu.py').read_text();check=oldcheck
 start=check.index(" scope={'np':np}");end=check.index(" helper=(HERE/'helper_source_reference.cpp')",start);check=check[:start]+check[end:]
 check=change(check," helper=(HERE/'helper_source_reference.cpp')"," assert all(x['passed']for x in checks)\n helper=(HERE/'helper_source_reference.cpp')")
 check=change(check,"driver.index(\"if job['arm']=='observed_control':\")","driver.index(\"if not work['metadata_accepted']\")")
 check=change(check,'frozen_oldB_metric_checks=metric_checks,frozen_oldB_four_windows_exact=True,','frozen_metric_sources_byte_exact=True,scoring_run_now=False,')
 check=change(check,'oldB_metric_windows_exact=4,','scoring_run_now=False,')
 write(HERE/'check_helper_contracts_cpu.py',check.encode());diff('CPU_checker_adaptation.diff',oldcheck,check)
 oldan=(OLD/'analyze_composed_cpu.py').read_text();an=oldan
 an=change(an," and run['observed_replay_accepted_frames']==64"," and run['observed_replay_accepted_frames']==0")
 an=change(an,"('observed_control','C0','C1')",repr(ARMS),count=2)
 an=change(an," assert np.array_equal(arrays['observed_control'],baseline)\n",'')
 an=change(an,"for arm in('C0','C1')",'for arm in'+repr(ARMS))
 # Prior C0/C1 are direct serialized-output references, not extra scored values.
 insertion=""" prior_reg=json.loads(Path(reg['prior_composition_registration']['path']).read_text());sealed=json.loads(Path(reg['prior_composition_final_seal']['path']).read_text())
 pinmap={r['path'].lower():r for r in sealed['files']+sealed['external_records']};prior_raw={}
 for oldarm in('C0','C1'):
  oldjobs=[j for j in prior_reg['jobs']if j['arm']==oldarm];assert [j['frame']for j in oldjobs]==list(range(64));prior_raw[oldarm]=[]
  for i in range(3):
   for j in oldjobs:
    pp=Path(j['outputs'][i]['path']);rr=pinmap[str(pp.resolve()).lower()];assert pp.stat().st_size==rr['bytes']and sha(pp)==rr['sha256']
   prior_raw[oldarm].append(np.stack([np.fromfile(j['outputs'][i]['path'],'<f2'if i<2 else'<u4').reshape(80,128,4)for j in oldjobs]))
 for arm in"""+repr(ARMS)+""":
  for oldarm in('C0','C1'):
   repeats[arm+'__prior_'+oldarm]={f'out{i}':dict(full_serialized_bits_exact=bool(np.array_equal(a.view('<u2')if i<2 else a,b.view('<u2')if i<2 else b)),RGB_bits_exact=bool(np.array_equal(a[...,:3].view('<u2')if i<2 else a[...,:3],b[...,:3].view('<u2')if i<2 else b[...,:3])),alpha_bits_exact=bool(np.array_equal(a[...,3].view('<u2')if i<2 else a[...,3],b[...,3].view('<u2')if i<2 else b[...,3])))for i,(a,b)in enumerate(zip(raw_arrays[arm],prior_raw[oldarm]))}
"""
 an=change(an," np.savez_compressed(HERE/'composed_sequences.npz'",insertion+" np.savez_compressed(HERE/'composed_sequences.npz'")
 an=change(an,'scorer_unchanged=True,new_native_API_GPU=0','scorer_unchanged=True,scored_values9=True,actual_composed_traces3=True,excluded_A10_r1_not_measured=True,new_native_API_GPU=0')
 write(HERE/'analyze_composed_cpu.py',an.encode());diff('analysis_adaptation.diff',oldan,an)
 sources.extend(OLD/n for n in('prepare.py','check_preparation_cpu.py','analysis_plan.json','mature_accounting_source_reuse.json'))
 limitations=['Three actual native traces,192future helperjobs; A10_r1 omitted only by full64rawRGBA equality. No fourth measured composition or independent-noise-sample claim.',
  'A0 native repeats differ and between-dose differences have comparable scale; composition is descriptive, not isolated alpha causation.',
  'Positive specular A10 is a primary-view-depth proxy, not traced secondary-ray length; no API-violation/private-zero/production-fix claim.',
  'Prior64observed all3output replays passed with identicalCSO/helper/template. No new observed replay is scheduled; actual inherited fixed9+CB are checked perjob before launch.',
  'Historical helper EXE identity and current source reference retained; no newly proved historical compilation provenance.',
  'Fixed full64/mature16/startup8/activation8to16 scorers, references and thresholds; signed rank1Nyquist beta/DC is descriptive, not continuous quadrature or physical oracle.',
  'All actual outputs retained; color RGB finite checked, alpha never repaired. No game cause or quality acceptance.']
 reg=dict(schema='three-native-alpha-traces-composition192-CPU-preparation',status='PREPARED_CPU_ONLY_NO_COMPOSITION_GPU_AUTHORIZATION',jobs=jobs,
  post_native_gate=ident(NP/'review.json'),post_native_final_seal=ident(NP/'completion_manifest_final.json'),
  prior_composition_registration=ident(OLD/'registration.json'),prior_composition_final_seal=ident(OP/'completion_manifest.json'),
  inherited_prior_observed_replay=ident(OP/'review.json'),replay_frames_previously_passed=64,new_observed_replay_jobs=0,
  mode_order='frame0..63 A0_r0,A10_r0,A0_r1',planned_only_helper_jobs=192,planned_only_explicit_helper_shader_Dispatches=192,planned_only_UAV_output_files=576,
  actual_helper_jobs=0,actual_shader_Dispatches=0,actual_native_contexts=0,actual_native_API=0,actual_builds=0,actual_scores=0,
  frozen_helper=ident(HERE/'fsrd_gpu_runner.exe'),frozen_guard=ident(HERE/'native_resource_guard.py'),frozen_CSO=ident(HERE/'frozen_shader/FSRDOutputComp_Shader.cso'),
  metric_source_records=metric_records,metric_function_extraction=extract,source_sequences=old['source_sequences'],quantized_raw_reference=old['quantized_raw_reference'],original_report=old['original_report'],
  guard=old['guard'],limitations=limitations,root_authorization_required_after_independent_prelaunch_review=True,quality_accepted=False,game_run=False)
 save('registration.json',reg)
 save('analysis_plan.json',dict(values=['raw_constructed_truth','quantized_raw_reference','oldB','oldTP','old_observed','old_pilot',*ARMS],references=['raw_constructed_truth','quantized_raw_reference'],
  windows=dict(full=list(range(64)),mature=list(range(48,64)),startup_first8=list(range(8)),activation8to16=list(range(8,16))),
  fixed_functions=extract,metric_source_records=metric_records,unchanged_thresholds_no_fit=True,descriptive_STD_ratio_to_oldB=True,signed_rank1_DC_beta=True,
  direct_raw_bits_to_prior_C0_C1=True,scoring_now=False,run_future_once_only_after_all192accepted=True,no_model_trials_or_quality_acceptance=True))
 external=[ident(p)for p in dict.fromkeys(sources)];verify(external);save('external_source_pins.json',dict(records=external,
  inherited_expanded_manifests=[ident(p)for p in inherited],expanded_tables_not_copied=True,
  fixed9_inputs_and_CB_sha_per_job_in_frozen_registration=True,driver_verifies_each_actual_fixed_input_before_child=True))
 for p in HERE.glob('*.py'):ast.parse(p.read_text(),filename=str(p))
 proc=subprocess.run([sys.executable,'-B',str(HERE/'check_helper_contracts_cpu.py')],cwd=HERE,capture_output=True)
 write(HERE/'CPU_checks.stdout.bin',proc.stdout);write(HERE/'CPU_checks.stderr.bin',proc.stderr)
 save('CPU_check_command.json',dict(command=[sys.executable,'-B',str(HERE/'check_helper_contracts_cpu.py')],returncode=proc.returncode,stdout=ident(HERE/'CPU_checks.stdout.bin'),stderr=ident(HERE/'CPU_checks.stderr.bin'),SIMULATED_only=True,new_GPU_native_build_scores=0))
 assert proc.returncode==0,'Preserve failed preparation.'
 print(json.dumps(dict(status=reg['status'],jobs=192,outputs=576,unique_external_sources=len(external),actual_GPU_native_build_scores=0)))
if __name__=='__main__':main()
