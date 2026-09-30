"""CPU-only two-job InputConv-output to OutputComp roundtrip preparation; no score/launch."""
from pathlib import Path
import ast,copy,difflib,hashlib,json,shlex,struct,sys
sys.dont_write_bytecode=True
import numpy as np
ROOT=Path('F:/OptiRevelations/OptiScaler-ffxD-alpha');TMP=ROOT/'tools_tmp';HERE=Path(__file__).resolve().parent
COMP=TMP/'fsrd_weak_material_clean_composition_preparation_20260930';CONV=TMP/'fsrd_weak_material_clean_converter_preparation_20260930'
GATE=TMP/'fsrd_weak_material_clean_composition_postrun_review_20260930';FMT=[10,28,10,28,10,24,10,41,10,10,3];OFMT=[10,10,3];BPP={10:8,28:4,24:4,41:4,3:16}
def ident(p):
 p=Path(p).resolve();return dict(path=str(p),bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest())
def read(p):return json.loads(Path(p).read_text())
def write(p,t):
 with Path(p).open('x',encoding='utf-8',newline='\n')as f:f.write(t)
def save(p,v):write(p,json.dumps(v,indent=2,allow_nan=False)+'\n')
def clone(p,q):
 with Path(q).open('xb')as f:f.write(Path(p).read_bytes())
 assert Path(p).read_bytes()==Path(q).read_bytes();return ident(p)
def verify(rs):
 for r in rs:assert ident(r['path'])==r,r['path']
def once(t,a,b):assert t.count(a)==1,a;return t.replace(a,b)
def main():
 assert not(HERE/'registration.json').exists(),'Preserve preparation'
 gate=read(GATE/'review.json');assert gate['status']=='PASSED_CLEAN_COMPOSITION_EVIDENCE_AND_EXACT_METRIC_REVIEW'and not gate['blocking_findings']
 assert ident(GATE/'review.json')['sha256']=='57c97fbecce6711b4e46079a6d18ce354a54c4ea44795a69d3b6aaff27c2caab'
 assert ident(GATE/'completion_manifest.json')['sha256']=='a4236765a7de7b625d7317a8bf6112f8e69db2fb6bdf37c8a4df704b1461e6d8'
 old=read(COMP/'registration.json');freeze=read(COMP/'pre_execution_freeze.json');verify(freeze['owned']);verify(freeze['external_sources'])
 for d in('payloads','frozen_shader','frozen_metric_sources','planned_jobs'):(HERE/d).mkdir(exist_ok=False)
 save(HERE/'initial_CPU_runtime_failure.json',dict(status='preserved_CPU_inspection_import_failure',runtime='C:/Users/burak/AppData/Local/Programs/Python/Python311/python.exe',error='ModuleNotFoundError: No module named numpy',stage='stdin graph inspection import before any data checks',repair='Use exact existing albedo_stage1_venv Python; no package install/source/payload change',actual_native_GPU_build_score=0))
 sources=[ident(GATE/'review.json'),ident(GATE/'completion_manifest.json'),ident(GATE/'compact.json'),ident(COMP/'registration.json'),ident(COMP/'pre_execution_freeze.json'),ident(COMP/'CPU_checks.json'),ident(COMP/'execution_results.json'),ident(COMP/'composition_metrics.json'),ident(COMP/'composed_sequences.npz'),ident(COMP/'source_mapping.json')]
 c0={j['frame']:j for j in old['jobs']if j['arm']=='C0'};assert sorted(c0)==list(range(64))
 first=None;frames=[];alpha=[]
 for frame in range(64):
  j=c0[frame];parsed=[shlex.split(line)for line in Path(j['job']).read_text().splitlines()];assert parsed[0][2:]==['128','80','11','3','1']and len(parsed)==15
  assert [int(x[-1])for x in parsed[1:12]]==FMT and [int(x[-1])for x in parsed[12:15]]==OFMT
  paths=[Path(r['path'])for r in j['inputs']];paths[0]=CONV/'planned_jobs'/f'{frame:02d}'/'clean/out0.bin';paths[2]=CONV/'planned_jobs'/f'{frame:02d}'/'clean/out1.bin'
  raw=[Path(j['CB']['path']).read_bytes()]+[p.read_bytes()for p in paths];assert len(raw[0])==96
  for i,(p,fmt)in enumerate(zip(paths,FMT)):assert len(raw[i+1])==128*80*BPP[fmt]
  if first is None:first=raw;first_paths=paths;first_cb=Path(j['CB']['path'])
  assert raw==first,'Distinct complete graph: cannot silently deduplicate'
  rs=[ident(Path(j['CB']['path']))]+[ident(p)for p in paths];sources.extend(rs)
  frames.append(dict(source_frame=frame,complete_CB_and_11_SRV_bytes_exact_to_frame0=True,CB=rs[0],inputs=[dict(slot=i,format=FMT[i],width=128,height=80,**rs[i+1])for i in range(11)]))
  row={}
  for slot,lobe,out in((0,'specular',0),(2,'diffuse',1)):
   a=np.frombuffer(raw[slot+1],'<u2').reshape(80,128,4)[...,3];native=np.fromfile(j['inputs'][slot]['path'],'<u2').reshape(80,128,4)[...,3]
   row[lobe]=dict(converter_alpha_unique_u16=np.unique(a).tolist(),SDK_output_alpha_unique_u16=np.unique(native).tolist(),alpha_bits_identical=bool(np.array_equal(a,native)))
  assert row['specular']==dict(converter_alpha_unique_u16=[0],SDK_output_alpha_unique_u16=[0],alpha_bits_identical=True)
  assert row['diffuse']==dict(converter_alpha_unique_u16=[31743],SDK_output_alpha_unique_u16=[0],alpha_bits_identical=False)
  alpha.append(dict(source_frame=frame,**row))
 cb=read(COMP/'source_mapping.json')['CB'];assert cb['Flags']==8 and cb['DetailPreservation']==0 and cb['HistoryValid']==cb['WriteHistory']==0
 assert struct.unpack_from('<I',first[0],16)[0]==8 and struct.unpack_from('<f',first[0],20)[0]==0 and struct.unpack_from('<I',first[0],52)[0]==struct.unpack_from('<I',first[0],64)[0]==0
 with np.load(old['source_sequences']['path'])as z:
  truth=z['clean_reference'];assert truth.shape==(64,80,128,3)and all(truth[f].tobytes()==truth[0].tobytes()for f in range(64))
 save(HERE/'graph_identity_proof.json',dict(status='ALL64_COMPLETE_GRAPHS_ONE_BYTE_IDENTICAL_CLASS',frames=frames,unique_complete_graphs=1,raw_constructed_truth_all64_byte_identical=True,
  graph_dimensions=[128,80],CB=cb,format10_passthrough_lobes_compatible=True,alpha_policy=alpha,actual_native_GPU_build_score=0,
  dedup_qualification='Two fresh executions of one complete graph. Future64-frame broadcasting follows proven graph identity; it is not64 new GPU observations.'))
 for p in first_paths:clone(p,HERE/'payloads'/f'in{first_paths.index(p)}.bin')
 clone(first_cb,HERE/'payloads/cb.bin')
 for n in('FSRDOutputComp_Shader.cso','FSRDOutputComp.hlsl','FSRDPreprocessCommon.hlsli','FSRDFloorCommon.hlsli'):sources.append(clone(COMP/'frozen_shader'/n,HERE/'frozen_shader'/n))
 for n in('fsrd_gpu_runner.exe','helper_source_reference.cpp','historical_gpu_runner.build.cmd','native_resource_guard.py','helper_work_accounting.py','helper_guard_evidence.py'):sources.append(clone(COMP/n,HERE/n))
 sources += [ident(CONV/'frozen_shader'/n)for n in('FSRDInputConvAdditive_Shader.cso','FSRDInputConvAdditive.hlsl','FSRDInputConv.hlsl','FSRDPreprocessCommon.hlsli','FSRDAdditiveSplit.hlsli')]
 metrics=[];extract=[]
 for item in old['metric_function_extraction']:
  p=Path(item['source']);q=HERE/'frozen_metric_sources'/p.name;sources.append(clone(p,q));metrics.append(ident(q));extract.append(dict(source=str(q),name=item['name']))
 jobs=[]
 for arm in('R0','R1'):
  folder=HERE/'planned_jobs'/arm;folder.mkdir();inputs=[dict(slot=i,format=fmt,**ident(HERE/'payloads'/f'in{i}.bin'))for i,fmt in enumerate(FMT)]
  outputs=[dict(slot=i,format=fmt,path=str((folder/f'out{i}.bin').resolve()),bytes=128*80*BPP[fmt])for i,fmt in enumerate(OFMT)]
  quote=lambda p:'"'+Path(p).resolve().as_posix()+'"'
  lines=[f'{quote(HERE/"frozen_shader/FSRDOutputComp_Shader.cso")} {quote(HERE/"payloads/cb.bin")} 128 80 11 3 1']+[f'{quote(r["path"])} 128 80 {r["format"]}'for r in inputs+outputs]
  write(folder/'job.txt','\n'.join(lines)+'\n');jobs.append(dict(frame=0,arm=arm,job=str((folder/'job.txt').resolve()),command=[str((HERE/'fsrd_gpu_runner.exe').resolve()),str((folder/'job.txt').resolve())],inputs=inputs,CB=ident(HERE/'payloads/cb.bin'),outputs=outputs,repetitions=1,explicit_shader_Dispatches_planned_only=1,represents_source_frames=list(range(64))))
 # Clone the mature executor; only cohort/CLI/path/status and obsolete observed-replay scheduling change.
 original=(COMP/'run_composition_only.py').read_text();driver=original
 edits=[('--execute-composition-only','--execute-roundtrip-only'),('composition_metrics.json','roundtrip_metrics.json'),('composed_sequences.npz','roundtrip_sequences.npz'),
  ("assert reg['status']=='PREPARED_CPU_ONLY_NO_COMPOSITION_GPU_AUTHORIZATION'","assert reg['status']=='PREPARED_CPU_ONLY_NO_ROUNDTRIP_GPU_AUTHORIZATION'"),
  ("assert len(reg['jobs'])==192 and [(j['frame'],j['arm'])for j in reg['jobs']]==[(f,a)for f in range(64)for a in('observed_control','C0','C1')]","assert len(reg['jobs'])==2 and [(j['frame'],j['arm'])for j in reg['jobs']]==[(0,'R0'),(0,'R1')]"),
  ('running_composition_only','running_roundtrip_only'),('observed_replay_accepted_frames=0','prior_observed_replay_accepted_frames=64'),(' replay_passed=set()\n',''),
  ("   if job['arm']!='observed_control':assert job['frame']in replay_passed,'Observed replay must pass before clean arm'\n",''),
  ('observed_replay_accepted=None','source_graph_dedup_64_proven=True'),
  ("assert report['metadata_accepted_jobs']==report['completed_accepted_jobs']==report['exact_helper_total']==report['exact_shader_dispatch_total']==192 and report['observed_replay_accepted_frames']==64","assert report['metadata_accepted_jobs']==report['completed_accepted_jobs']==report['exact_helper_total']==report['exact_shader_dispatch_total']==2"),
  ('completed_composition_only_awaiting_independent_review_not_quality_accepted','completed_roundtrip_only_awaiting_independent_review_not_quality_accepted'),('failed_preserved_composition_only_no_retry','failed_preserved_roundtrip_only_no_retry')]
 for a,b in edits:
  assert driver.count(a)>=1,a;driver=driver.replace(a,b)
 start=driver.index("   if job['arm']=='observed_control':\n");end=driver.index('   # All three raw outputs retained;',start);removed=driver[start:end];driver=driver[:start]+driver[end:]
 write(HERE/'run_roundtrip_only.py',driver)
 write(HERE/'executor_adaptation.diff',''.join(difflib.unified_diff(original.splitlines(True),driver.splitlines(True),fromfile='frozen_composition192_executor',tofile='two_identical_graph_roundtrip_executor')))
 save(HERE/'accounting_reuse.json',dict(parser_byte_exact=ident(HERE/'helper_work_accounting.py'),guard_loader_byte_exact=ident(HERE/'helper_guard_evidence.py'),resource_guard_byte_exact=ident(HERE/'native_resource_guard.py'),
  mature_parser=ident(COMP/'helper_work_accounting.py'),mature_guard_loader=ident(COMP/'helper_guard_evidence.py'),mature_resource_guard=ident(COMP/'native_resource_guard.py'),old_six_CPU_probes_and_oldB_fourwindows=ident(COMP/'CPU_checks.json'),
  removed_observed_replay_block=removed,executor_replacements=[dict(before=a,after=b)for a,b in edits],actual_checkpoint_before_metadata_preserved=True,source_provenance='Historical helperEXE/current pinned source reference and originalCSO bytes; no fresh compilation/source-to-EXE equivalence claim.',new_GPU_native_build_score=0))
 sources += [ident(COMP/'run_composition_only.py'),ident(COMP/'analyze_composed_cpu.py'),ident(COMP/'check_preparation_cpu.py'),ident(CONV/'planned_jobs/00/clean/job.txt'),ident(CONV/'historical_templates/00/cb.bin'),ident(CONV/'planned_jobs/00/clean/in0.bin')]
 sources += [old[k]for k in('source_sequences','quantized_raw_reference','original_report')]
 sources=list({r['path']:r for r in sources+freeze['external_sources']}.values());verify(sources)
 limitations=['R is actual OutputComp GPU output from captured InputConv fullRGBA lobes and fixed guides. No CPU radiance remodulation substitutes for R.','R-q measures the frozen converter+composition roundtrip relative to encodedraw q; T-R measures the extra opaque SDK path and downstream composition response. This is a directional stage contrast, not a proof of private SDK-only intrinsic error or a causal game result.','The original additive InputConv variant and all settings are frozen. No new calibration, filter, threshold, fit or shader changes are introduced.','Converter diffuse alpha0x7bff versus SDKoutputalpha0 is retained. Frozen flags8/detail0/history0 normal fastpath reads only lobergb and writes coloralpha1. All three output bytes are retained; WriteHistory0 leaves auxiliary UAVs unwritten by that path, so no semantic history claim follows from them.','Two fresh helper/device executions of one byte-identical fullgraph are2 shader dispatches,0 SDK calls. Broadcast to64 validated graph sourceindices is an analytical representation, never64 physical observations.','Source/CSO and helperEXE identities plus64 prior observed replays are pinned; source reading does not newly prove historical compiler equivalence or private-provider implementation.','Rawtruth and quantizedraw references remain distinct; frozen windows/score functions and rank1 signedNyquist DC/beta descriptive method are unchanged. RMS/gain ratios are not additive error terms; pixel/DC/signedbeta differences are directional.']
 reg=dict(schema='weak-material-clean-one-graph-two-repeat-stage-partition-v1',status='PREPARED_CPU_ONLY_NO_ROUNDTRIP_GPU_AUTHORIZATION',prior_composition_independent_gate=ident(GATE/'review.json'),prior_composition_seal=ident(GATE/'completion_manifest.json'),graph_identity_proof=ident(HERE/'graph_identity_proof.json'),jobs=jobs,
  planned_only_helper_jobs=2,planned_only_explicit_helper_shader_Dispatches=2,planned_only_outputs=6,planned_only_SDK_calls=0,source_frame_representation=list(range(64)),physical_graph_count=1,physical_fresh_process_repeats=2,
  guard=old['guard'],frozen_helper=ident(HERE/'fsrd_gpu_runner.exe'),frozen_CSO=ident(HERE/'frozen_shader/FSRDOutputComp_Shader.cso'),CB_settings=cb,metric_source_records=metrics,metric_function_extraction=extract,
  source_sequences=old['source_sequences'],quantized_raw_reference=old['quantized_raw_reference'],original_report=old['original_report'],prior_composed_sequences=ident(COMP/'composed_sequences.npz'),prior_composed_metrics=ident(COMP/'composition_metrics.json'),
  actual_helper_jobs=0,actual_shader_Dispatches=0,actual_native_contexts=0,actual_native_API=0,actual_builds=0,actual_scores=0,model_fitting=False,root_authorization_required_after_independent_prelaunch_review=True,quality_accepted=False,game_run=False,limitations=limitations)
 save(HERE/'registration.json',reg);save(HERE/'external_source_pins.json',dict(records=sources,all_before_current_exact=True,new_GPU_native_build_score=0))
 write(HERE/'design.txt','Two fresh repetition1 OutputComp helper jobs, R0 thenR1, one fullgraph proven identical at all64 source indices. t0=actual clean InputConv out0 specular, t2=out1 diffuse; all other nine SRVs and96CB exactly copied from actual clean composition graph. Diffuse inputalpha65504 is retained versus SDKoutputalpha0; active frozen compositionRGB path ignores those lobe alpha values. Output formats10/10/3 retained fully. No SDK call, new shader, compile, calibration or filter.\n\nFuture partition: q is actual encodedraw reference; R is GPU reconstructed roundtrip; T is prior genuine SDK+composition C0/C1. Report R-q and T-R signed pixel/DC/Nyquistbeta differences and frozen rawtruth/quantizedraw scores without changing functions/windows or fitting. Broadcast one measured graph to validated64 equivalent sourceindices only; actualnew shader count2. Existing priorcomposition192jobs/64replays have independently passed. New independent prelaunch review and root execution authorization are required.\n')
 for p in HERE.rglob('*.py'):ast.parse(p.read_text())
 print(json.dumps(dict(status='two-job_CPU_prepared_no_launch_no_score',jobs=2,unique_graphs=1,external_records=len(sources),registration=ident(HERE/'registration.json'))))
if __name__=='__main__':main()
