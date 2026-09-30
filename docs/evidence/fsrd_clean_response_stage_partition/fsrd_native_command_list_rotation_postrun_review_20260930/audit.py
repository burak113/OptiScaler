"""Read-only independent actual rotation stages and raw outputs; CPU only, no device calls."""
from pathlib import Path
import sys,ast,json,hashlib,struct,itertools,shlex
sys.dont_write_bytecode=True
import numpy as np
HERE=Path(__file__).resolve().parent;TMP=HERE.parent;ROOT=TMP.parent
P=TMP/'fsrd_native_command_list_rotation_preparation_20260930'
PRE=TMP/'fsrd_native_command_list_rotation_prelaunch_review_20260930'
B=TMP/'fsrd_native_batched_recording_diagnostic_20260930/new_v5'
COUNT=('api','queued','completed','observed','executes','signal_attempts','signals','event_attempts','events','wait_attempts','waits')
DIAG=('validation_errors','validation_warnings','sdk_errors','sdk_warnings','discarded','omitted')
def path(v):
 p=Path(v);return p if p.is_absolute()else ROOT/p
def identity(p):
 p=path(p).resolve();h=hashlib.sha256()
 with p.open('rb')as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return dict(path=str(p),bytes=p.stat().st_size,sha256=h.hexdigest())
def verify(r):
 a=identity(r['path']);assert(a['bytes'],a['sha256'])==(r['bytes'],r['sha256']),r['path']
def decode(raw):
 def unique(pairs):
  d={}
  for k,v in pairs:assert k not in d,'duplicate key';d[k]=v
  return d
 return json.loads(raw,object_pairs_hook=unique,parse_constant=lambda x:(_ for _ in()).throw(ValueError(x)))
def read(p):return decode(path(p).read_bytes())
def save(n,o):
 with(HERE/n).open('x',encoding='utf-8',newline='\n')as f:json.dump(o,f,indent=2,allow_nan=False);f.write('\n')
def dedup(records):
 out={}
 for r in records:
  key=str(path(r['path']).resolve()).lower()
  if key in out:assert(out[key]['bytes'],out[key]['sha256'])==(r['bytes'],r['sha256'])
  out[key]=dict(path=str(path(r['path']).resolve()),bytes=r['bytes'],sha256=r['sha256'])
 return list(out.values())
def metrics(a,b):
 r=dict(RGBA_bits_exact=bool(np.array_equal(a.view('<u2'),b.view('<u2'))),RGB_bits_exact=bool(np.array_equal(a[...,:3].view('<u2'),b[...,:3].view('<u2'))),all_finite=bool(np.isfinite(a).all()and np.isfinite(b).all()))
 for label,sl in[('RGB',slice(0,3)),('alpha',slice(3,4)),('RGBA',slice(None))]:
  d=a[...,sl].astype(np.float64)-b[...,sl].astype(np.float64);sq=d*d
  r[label]=dict(RMS=float(np.sqrt(sq.mean())),max_abs=float(np.abs(d).max()),changed_fraction=float(np.count_nonzero(d)/d.size),per_frame_RMS=np.sqrt(sq.mean(axis=(1,2,3))).tolist())
 return r
def masks(a,b):
 changed=a.view('<u2')!=b.view('<u2');rgb=np.any(changed[...,:3],axis=-1);frames=[]
 for f in range(64):
  y,x=np.nonzero(rgb[f]);frames.append(dict(source_frame=f,RGB_bit_changed_pixels=len(x),RGB_changed_bbox_inclusive_xy=[int(x.min()),int(y.min()),int(x.max()),int(y.max())]if len(x)else None,changed_values_per_channel={c:int(changed[f,...,i].sum())for i,c in enumerate('RGBA')}))
 ids=np.flatnonzero(np.any(rgb,axis=(1,2))).tolist()
 return dict(first_changed_source_frame=ids[0]if ids else None,last_changed_source_frame=ids[-1]if ids else None,changed_source_frame_ids=ids,per_frame=frames,alpha_bits_exact=not bool(changed[...,3].any()))
def main():
 auth_path=TMP/'fsrd_native_rotation_root_authorization_20260930.json';tool_path=TMP/'fsrd_native_rotation_root_tool_observations_20260930.json'
 assert identity(auth_path)['sha256']=='477d18a294504e6e7d7cb8612ee19c66e8d842ac192d7fa2a4b5fa7cea647ae5'
 assert identity(tool_path)['sha256']=='b083d9158315b8be831315ec550a4fb8916884ff97169b3a35e195cda1a63a5f'
 auth=read(auth_path);assert auth['status']=='ROOT_AUTHORIZED_EXACT_NATIVE_K1_ROTATION_ONCE'
 ready=read(P/'prelaunch_ready_manifest.json');freeze=read(P/'pre_native_freeze.json');review=read(PRE/'completion_manifest.json');reg=read(P/'registration.json')
 records=ready['files']+ready['external_sources']+freeze['files']+freeze['external_sources']+review['files']+review.get('external_sources',review.get('external_records',[]))+auth['exact_preparation_pins']+[auth[k]for k in('independent_review','independent_review_manifest','root_verifier','root_streaming_pin_library')]+[identity(auth_path),identity(tool_path),identity(P/'prelaunch_ready_manifest.json'),identity(PRE/'completion_manifest.json')]
 for r in records:verify(r)
 assert(len(ready['files']),len(ready['external_sources']),len(freeze['files']),len(freeze['external_sources']))==(212,492,211,492)
 source=read(P/'cpp_whitelist.json');verify(source['before']);verify(source['after']);rebuilt=path(source['before']['path']).read_text()
 for item in source['replacements']:assert rebuilt.count(item['before'])==1;rebuilt=rebuilt.replace(item['before'],item['after'])
 assert rebuilt==path(source['after']['path']).read_text()
 run=read(P/'evidence/results.json');producer_metrics=read(P/'raw_comparisons.json')
 assert run['status']=='completed_native_K1_command_list_rotation_not_solution_V5_accounting'
 assert run['accepted_contexts']==run['created_contexts_confirmed']==run['completed_contexts_confirmed']==run['attempted_owned_children']==4
 assert run['unknown_total_children']==0 and run['counts']=={q:256 for q in COUNT}
 assert producer_metrics['producer_sha256']==identity(P/'evidence/results.json')['sha256']
 batchreg=read(B/'registration.json');batchrun=read(B/'evidence/results.json');batch_by={c['tag']:c for c in batchreg['cases']}
 prior_names=['round0_K1','round1_K1','round0_K2'];prior_cases={k:batch_by[k]for k in prior_names}
 for tag,c in prior_cases.items():
  assert batchrun['cases'][tag]['accepted']
  for r in c['inputs']:verify(r)
  for n in('dispatch_controls.bin','diffuse.bin','specular.bin'):
   p=Path(c['native_runtime_folder'])/n;records.append(identity(p))
   if n!='dispatch_controls.bin':assert identity(p)['sha256']==batchrun['cases'][tag]['lobes'][n]['sha256']
 records.extend(identity(B/n)for n in('registration.json','evidence/results.json','raw_comparisons.json'))
 records.extend([identity(TMP/'fsrd_native_batched_recording_post_native_audit_20260930/audit.py'),identity(TMP/'fsrd_native_batched_recording_post_native_audit_20260930/audit.json'),identity(TMP/'fsrd_native_batched_recording_post_native_audit_20260930/completion_manifest.json')])
 for c in reg['cases']:
  for folder in(Path(c['native_runtime_folder']),P/'evidence'/c['tag']):
   if folder.exists():records.extend(identity(p)for p in folder.rglob('*')if p.is_file())
 records.extend(identity(P/n)for n in('evidence/results.json','raw_comparisons.json','cpp_whitelist.json'))
 before=dedup(records)
 save('audit_plan.json',dict(chronology='Post-run CPU plan before independent raw-output recomputation; not a pre-native registration.',current_contexts=4,current_source_aligned_pairs=6,current_lobes_per_pair=2,prior_batch_reference_pairs=6,prior_batch_reference_cases=prior_names,root_authorization=identity(auth_path),root_tool_observations=identity(tool_path),actual_new_native_API_GPU_build_quality_scores=0))
 save('before_audit_freeze.json',dict(records=before,actual_new_native_API_GPU=0))
 trace_source=TMP/'fsrd_native_batched_recording_post_native_audit_20260930/audit.py'
 # Reuse only an independently authored pure expected event grammar, never its executable main.
 scope={'COUNT':COUNT,'DIAG':DIAG};node=next(n for n in ast.parse(trace_source.read_text()).body if isinstance(n,ast.FunctionDef)and n.name=='expected_trace');exec(compile(ast.Module(body=[node],type_ignores=[]),str(trace_source),'exec'),scope)
 expected=scope['expected_trace'](1);arrays={};controls={};cases={};count={q:0 for q in COUNT}
 for c in reg['cases']:
  tag=c['tag'];folder=Path(c['native_runtime_folder']);reported=run['cases'][tag];assert c['K']==1 and c['pool_rotation']in(1,4)
  assert c['command'][2:]==['1',str(c['pool_rotation'])]and folder==Path(c['command'][1]).parent==Path(reported['native_runtime_folder'])and reported['accepted']
  guard=read(folder/'resource_guard.json');assert guard['args']==c['command']and guard['status']=='completed'and guard['returncode']==0 and type(guard['child_pid'])is int and guard['child_pid']>0
  assert guard['timeout_seconds']==240 and guard['maximum_working_set_bytes']==2147483648 and guard['minimum_available_memory_bytes']==1073741824 and guard['sample_interval_seconds']==.2
  assert guard['elapsed_seconds']<=240 and guard['peak_observed_working_set_bytes']<=2147483648 and guard['minimum_observed_available_bytes']>=1073741824 and not guard['terminated_owned_child']
  assert reported['guard']['child_pid']==guard['child_pid']and not reported['guard']['guard_load_evidence']['errors']
  ledger=[decode(line)for line in(folder/'stage_events.jsonl').read_bytes().splitlines()];assert ledger==expected
  stdout=(folder/'stdout.log').read_bytes();stderr=(folder/'stderr.log').read_bytes();assert stderr==b''and b'debug_layer=1'in stdout
  terminal=[decode(line[len(b'BATCH_COUNTERS '):])for line in stdout.splitlines()if line.startswith(b'BATCH_COUNTERS ')];assert terminal==[expected[-1]]
  footer=terminal[0];assert reported['accounting']['terminal_CPP_snapshot']==footer
  assert b'RR_recordings=64 queued_RR_dispatches=64 discarded_RR_recordings=0 validation_errors=0 validation_warnings=0 sdk_errors=0 sdk_warnings=0'in stdout.splitlines()
  for q in COUNT:count[q]+=footer[q]
  ids=struct.pack('<64I',*range(64))
  for n in('recorded_frame_indices.bin','queued_frame_indices.bin','completed_frame_indices.bin','observed_frame_indices.bin'):assert(folder/n).read_bytes()==ids
  assert(folder/'output_presence.bin').read_bytes()==bytes([1])*64
  packet=(folder/'dispatch_controls.bin').read_bytes();assert packet==path(c['expected_controls']['path']).read_bytes()and len(packet)==64*184
  assert [struct.unpack_from('<II',packet,i*184)for i in range(64)]==[(i,3 if i==0 else 2)for i in range(64)];controls[tag]=packet
  for r in c['inputs']:verify(r)
  inputs=[shlex.split(x)for x in(folder/'job.txt').read_text().splitlines()]
  assert [(int(row[1]),int(row[2]))for row in inputs[1:8]]==[(41,1),(10,1),(24,1),(28,1),(28,1),(10,64),(10,64)]
  arrays[tag]={};lobes={}
  for n in('diffuse.bin','specular.bin'):
   record=identity(folder/n);assert record['bytes']==5242880 and record['sha256']==reported['lobes'][n]['sha256']
   a=np.fromfile(folder/n,'<f2').reshape(64,80,128,4);assert np.isfinite(a[...,:3]).all();arrays[tag][n]=a
   lobes[n]=dict(record=record,shape=list(a.shape),consumed_RGB_finite=True,alpha_half_bit_values=list(map(int,np.unique(a[...,3].view('<u2')))))
  cases[tag]=dict(pool_rotation=c['pool_rotation'],K=1,guard_child_pid=guard['child_pid'],counts={q:footer[q]for q in COUNT},diagnostics={q:footer[q]for q in DIAG},registered_actual_stage_ledger_exact=True,ledger_rows=len(ledger),guard=identity(folder/'resource_guard.json'),source_control184=identity(folder/'dispatch_controls.bin'),all64indices_presence_exact=True,all7_input_formats_counts_pins_exact=True,lobes=lobes)
 assert count==run['counts']=={q:256 for q in COUNT}
 comparisons={};maskrows={}
 for left,right in itertools.combinations(reg['mode_order'],2):
  assert controls[left]==controls[right];key=left+'__'+right
  pair=dict(source_frame_indices=list(range(64)),applied_184_bytes_exact_all_frames=True,lobes={n:metrics(arrays[left][n],arrays[right][n])for n in('diffuse.bin','specular.bin')})
  assert pair==producer_metrics['comparisons'][key];comparisons[key]=pair;maskrows[key]={n:masks(arrays[left][n],arrays[right][n])for n in('diffuse.bin','specular.bin')}
 assert len(comparisons)==len(producer_metrics['comparisons'])==6
 assert all(m['RGBA_bits_exact']and m['RGB_bits_exact']for pair in comparisons.values()for m in pair['lobes'].values())
 prior_arrays={};references={}
 for tag,c in prior_cases.items():
  folder=Path(c['native_runtime_folder']);packet=(folder/'dispatch_controls.bin').read_bytes()
  assert all(packet==p for p in controls.values())
  for current in reg['cases']:
   assert [(i['DXGI_format'],i['uploads'],i['bytes'],i['sha256'])for i in c['inputs']]==[(i['DXGI_format'],i['uploads'],i['bytes'],i['sha256'])for i in current['inputs']]
  prior_arrays[tag]={n:np.fromfile(folder/n,'<f2').reshape(64,80,128,4)for n in('diffuse.bin','specular.bin')}
  references[tag]=dict(inputs7_full_payload_formats_counts_exact_to_current=True,applied184_controls_all64_exact_to_current=True,prior_native_context_counted_as_new=False,source_frame_ids=list(range(64)),native_lobes={n:identity(folder/n)for n in('diffuse.bin','specular.bin')})
 cross={};cross_masks={}
 for current in(c['tag']for c in reg['cases']if c['pool_rotation']==4):
  for old in prior_names:
   key=current+'__prior_'+old;cross[key]=dict(source_frame_ids=list(range(64)),inputs7_and_applied184_all_frames_exact=True,lobes={n:metrics(arrays[current][n],prior_arrays[old][n])for n in('diffuse.bin','specular.bin')});cross_masks[key]={n:masks(arrays[current][n],prior_arrays[old][n])for n in('diffuse.bin','specular.bin')}
 assert len(cross)==6
 save('independent_raw_comparisons.json',dict(current_six_pairs=comparisons,all12_metrics_exact_to_frozen_analyzer=True,prior_batch_six_descriptive_P4_pairs=cross,prior_reference_contract=references,no_new_native_API_GPU=True,no_quality_score=True))
 save('RGB_alpha_change_masks.json',dict(current=maskrows,prior_batch_P4=cross_masks,raw_bit_coordinate_mask_counts=True,semantic_or_quality_classification=False,actual_new_native_API_GPU=0))
 for r in before:verify(r)
 save('after_audit_freeze.json',dict(all_before_records_byte_exact=True,record_count=len(before),records=[identity(r['path'])for r in before],actual_new_native_API_GPU=0))
 oldsrc=identity(TMP/'fsrd_native_batched_recording_diagnostic_20260930/fsrd_rr_batch.cpp');oldexe=identity(TMP/'fsrd_native_batched_recording_diagnostic_20260930/fsrd_rr_batch.exe');verify(reg['source']);verify(reg['binary'])
 report=dict(status='PASSED_NATIVE_COMMAND_LIST_ROTATION_CPU_POSTREVIEW',blocking_findings=[],root_authorization=identity(auth_path),root_tool_observations=identity(tool_path),producer_results=identity(P/'evidence/results.json'),producer_analysis=identity(P/'raw_comparisons.json'),ready=identity(P/'prelaunch_ready_manifest.json'),freeze=identity(P/'pre_native_freeze.json'),independent_prelaunch_review=identity(PRE/'review.json'),independent_prelaunch_seal=identity(PRE/'completion_manifest.json'),preparation_records_verified=dict(ready_files=212,ready_external=492,freeze_files=211,freeze_external=492),source_whitelist_reconstruction_exact=True,before_after_record_count=len(before),actual=dict(created_contexts=4,fully_completed_contexts=4,accepted_contexts=4,successful_API_RR=256,queued_logical_RR=256,fence_completed_logical_RR=256,observed_logical_RR=256,Execute_calls=256,Signal_event_wait_attempts_and_successes={q:256 for q in COUNT[5:]},discarded_successful_records=0,no_API_omissions=0,SDK_shader_dispatches='opaque; not inferred'),cases=cases,current_six_pairs_both_lobes_RGBA_RGB_bit_exact=True,all12_metric_records_exact_to_frozen_analyzer=True,current_RGB_alpha_change_masks_all_zero=True,prior_batch_reference_pairs=6,prior_batch_descriptive_results={k:{n:dict(RGBA_bits_exact=m['RGBA_bits_exact'],RGB_bits_exact=m['RGB_bits_exact'],RGB_RMS=m['RGB']['RMS'],RGB_max_abs=m['RGB']['max_abs'],first_changed_source_frame=cross_masks[k][n]['first_changed_source_frame'],last_changed_source_frame=cross_masks[k][n]['last_changed_source_frame'],alpha_RMS=m['alpha']['RMS'])for n,m in v['lobes'].items()}for k,v in cross.items()},current_source=reg['source'],current_binary=reg['binary'],prior_batch_source=oldsrc,prior_batch_binary=oldexe,actual_new_review_native_API_GPU_build_quality_scores=0,quality_accepted=False,game_run=False,limitations=['P1 versus P4 varies the selected list/allocator modulo while both create four objects and use K1 serial Execute/fence/wait cadence with identical pinned external inputs/controls. Equality is conditional evidence in this exact four-context run.','Current P4 versus historical batch output is descriptive only: current C++ adds argument parsing and a modulo-selection branch, EXE/build differ, and process/time/cohort differs despite all seven input payloads/formats/upload counts and all184 control bytes matching.','Current equality does not erase or invalidate the prior independently authenticated K1 nonrepeat differences, establish universal determinism, prove private SDK lifetime safety or rule out a mechanism/game stain cause.','SDK private descriptors/constant-buffer/history scheduling remain opaque. No quality score, truth threshold, game acceptance or new native execution belongs to this CPU audit.'])
 save('review.json',report)
 save('compact.json',dict(status=report['status'],review=identity(HERE/'review.json'),actual=report['actual'],current_all6pairs_12lobes_bit_exact=True,source_aligned_frames=64,all_diagnostics_zero=True,before_after_records=len(before),prior_batch_P4_pairs=6,actual_new_review_native_API_GPU=0,quality_accepted=False))
 owned=[identity(p)for p in sorted(HERE.rglob('*'))if p.is_file()and p.name!='completion_manifest.json']
 manifest=dict(files=owned,external_records=before,self_entry_excluded=True,status=report['status'],actual_new_review_native_API_GPU=0)
 save('completion_manifest.json',manifest)
 for r in owned+before:verify(r)
 assert all(path(r['path']).resolve()!=(HERE/'completion_manifest.json').resolve()for r in owned+before)
 print(json.dumps(dict(status=report['status'],review=identity(HERE/'review.json'),manifest=identity(HERE/'completion_manifest.json'),owned_records=len(owned),external_records=len(before),actual=report['actual'],current_six_pairs_bit_exact=True,cross_cohort=report['prior_batch_descriptive_results'],new_review_native_GPU=0)))
if __name__=='__main__':main()
