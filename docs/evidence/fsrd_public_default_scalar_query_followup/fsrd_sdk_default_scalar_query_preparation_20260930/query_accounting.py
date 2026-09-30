"""Fixed query-probe stdout grammar only. No SDK import or launcher."""
from pathlib import Path
import hashlib,json,struct
KEYS=(6,1,2,3,4,5)
COUNTERS=('create_entry','create_returned','created','query_entry','query_returned','query_ok','destroy_entry','destroy_returned','destroyed','rr_dispatch','configure','owned_execute')
FIELDS=set(('v','seq','stage','key','rc','nonnull','bits','d3d_errors','d3d_warnings','ownership_uncertain','accepted')+COUNTERS)
def unique(pairs):
 d={}
 for k,v in pairs:
  if k in d:raise ValueError('duplicate key')
  d[k]=v
 return d
def parse(raw):return json.loads(raw,object_pairs_hook=unique,parse_constant=lambda v:(_ for _ in()).throw(ValueError('nonfinite JSON')))
def artifact(p):
 p=Path(p)
 try:b=p.read_bytes();return dict(path=str(p),bytes=len(b),sha256=hashlib.sha256(b).hexdigest(),present=True),b
 except OSError as e:return dict(path=str(p),bytes=None,sha256=None,present=p.exists(),error=type(e).__name__+': '+str(e)),b''
def derive(folder,guard):
 folder=Path(folder);records=[];data={}
 for n in('stdout.log','stderr.log','query_values.bin'):
  r,b=artifact(folder/n);records.append(r);data[n]=b
 count={k:0 for k in COUNTERS};phase='initial';seq=0;ambiguous=False;pending=None;unresolved=False;bits=[];terminal=None;valid=[];errors=[];metas=[]
 for line in data['stdout.log'].splitlines(keepends=True):
  if line.startswith(b'QUERY_META '):
   try:
    assert line.endswith(b'\n');metas.append(parse(line[len(b'QUERY_META '):]))
   except BaseException as e:errors.append('metadata:'+str(e))
   continue
  if not line.startswith(b'QUERY_EVENT '):
   if line.strip():errors.append('unknown_stdout_line')
   continue
  try:
   assert terminal is None,'duplicate_or_after_terminal';assert line.endswith(b'\n'),'truncated_event'
   v=parse(line[len(b'QUERY_EVENT '):]);assert set(v)==FIELDS,'event_fields'
   assert all(type(v[k])is int and 0<=v[k]<=0xffffffff for k in COUNTERS+('v','seq','key','rc','bits','d3d_errors','d3d_warnings')),'integer_fields'
   assert all(type(v[k])is bool for k in('nonnull','ownership_uncertain','accepted')),'boolean_fields'
   assert v['v']==1 and v['seq']==seq,'sequence';stage=v['stage'];next_count=count.copy();next_phase=phase;next_pending=pending;next_ambiguous=ambiguous
   if stage=='boot':assert phase=='initial'and seq==0;next_phase='boot'
   elif stage=='create_start':
    assert phase=='boot';next_count['create_entry']=1;next_phase='create_pending';next_pending='create'
   elif stage=='create_return':
    assert phase=='create_pending'and pending=='create';next_count['create_returned']=1;next_pending=None
    if v['rc']==0 and v['nonnull']:next_count['created']=1;next_phase='live'
    else:next_phase='create_failed';next_ambiguous=v['nonnull']
   elif stage=='query_start':
    assert phase=='live'and count['query_returned']<6 and count['query_ok']==count['query_returned']
    assert v['key']==KEYS[count['query_returned']];next_count['query_entry']+=1;next_phase='query_pending';next_pending='query'
   elif stage=='query_return':
    assert phase=='query_pending'and pending=='query'and v['key']==KEYS[count['query_returned']]
    next_count['query_returned']+=1;next_count['query_ok']+=int(v['rc']==0);next_phase='live'if v['rc']==0 else'query_failed';next_pending=None
   elif stage=='destroy_start':
    assert count['created']==1 and count['destroy_entry']==0 and phase in('live','query_failed','query_pending')
    if pending=='query':unresolved=True
    next_count['destroy_entry']=1;next_phase='destroy_pending';next_pending='destroy'
   elif stage=='destroy_return':
    assert phase=='destroy_pending'and pending=='destroy';next_count['destroy_returned']=1;next_pending=None
    if v['rc']==0:next_count['destroyed']=1
    else:next_ambiguous=True
    next_phase='destroy_returned'
   elif stage in('complete','failed'):
    assert phase!='initial'
    if stage=='complete':
     assert phase=='destroy_returned'and not pending and not unresolved
     assert count['created']==count['destroyed']==1 and count['query_returned']==count['query_ok']==6
     assert v['accepted']and not ambiguous and v['d3d_errors']==v['d3d_warnings']==0
     assert len(bits)==6 and all(b!=0x7fc12345 and (b&0x7f800000)!=0x7f800000 for b in bits),'complete_numeric_source_predicate'
    else:
     assert not v['accepted'];assert not(count['created']and count['destroy_entry']==0),'knownlive_requires_cleanup_entry'
   else:raise ValueError('unknown_stage')
   assert all(v[k]==next_count[k]for k in COUNTERS),'counter_jump_or_inconsistent_stage'
   assert v['ownership_uncertain']==next_ambiguous,'ownership_state'
   assert v['rr_dispatch']==v['configure']==v['owned_execute']==0,'forbidden_work'
   if stage not in('complete','failed'):assert not v['accepted']and v['d3d_errors']==v['d3d_warnings']==0
   if stage not in('query_start','query_return'):assert v['key']==0
   if stage not in('create_return','query_return','destroy_return'):assert v['rc']==0 and not v['nonnull']and v['bits']==0
   if stage!='query_return':assert v['bits']==0
   count=next_count;phase=next_phase;pending=next_pending;ambiguous=next_ambiguous;seq+=1;valid.append(v)
   if stage=='query_return':bits.append(v['bits'])
   if stage in('complete','failed'):terminal=v
  except BaseException as e:
   errors.append('grammar:'+type(e).__name__+': '+str(e));break
 pid=guard.get('child_pid');status=guard.get('status');current=type(pid)is int and pid>0 and status in('running','completed','failed_or_terminated')
 attempt=guard.get('executor_launch_attempt',{})
 fresh=status=='guard_evidence_unavailable'and isinstance(attempt,dict)and all(attempt.get(k)is True for k in('invocation_started','fresh_runtime_files_verified_absent','case_command_matches','before_guard_call_checkpointed'))
 nochild=status in('not_launched','not_launched_low_available_memory')and pid is None
 attributable=current or fresh
 physical=count.copy()if attributable else{k:0 for k in COUNTERS}
 exact=bool(current and terminal is not None and not errors and pending is None and not unresolved and all(count[a]==count[b]for a,b in [('create_entry','create_returned'),('query_entry','query_returned'),('destroy_entry','destroy_returned')]))
 if not attributable and valid:errors.append('claims_without_current_child_not_physical_work')
 if fresh:errors.append('fresh_attempt_process_identity_and_exact_totals_unknown')
 if any(x.startswith(b'QUERY_EVENT ')for x in data['stderr.log'].splitlines()):errors.append('stderr_not_event_authority')
 metadata=False
 if len(metas)==1:
  m=metas[0]
  metadata=all(type(m.get(k))is type(v)and m.get(k)==v for k,v in dict(v=1,api=4202496,width=128,height=80,signals=34,checkerboard=0,create_flags=2,debug_layer=1,provider_path_verified=True,SDK_callback_warning_count_available=False).items())
 else:errors.append('metadata_missing_duplicate')
 raw_expected=b''.join(struct.pack('<I',b)for b in bits);raw_match=data['query_values.bin']==raw_expected and len(bits)==6
 numeric=all(b!=0x7fc12345 and (b&0x7f800000)!=0x7f800000 for b in bits)and len(bits)==6
 accepted=bool(exact and terminal['stage']=='complete'and terminal['accepted']and status=='completed'and guard.get('returncode')==0 and not guard.get('terminated_owned_child')and not guard.get('guard_load_evidence',{}).get('errors')and not errors and metadata and raw_match and numeric and not data['stderr.log'])
 return dict(schema='fixed6-default-query-prefix-v1',counts_lower_bound=physical,exact_returned_totals=exact,totals_unknown=not exact,known_no_child=nochild,current_child_confirmed=current,
  valid_prefix_events=valid,terminal_claim=terminal,unattributed_claimed_counts=count,raw_float_bits=bits,artifacts=records,evidence_errors=errors,
  pending_entry_not_completed_API=pending,unresolved_call_entry=unresolved,metadata_source_matches=metadata,raw_output_matches_returned_bits=raw_match,numeric_metadata_valid=numeric,accepted=accepted,
  limits='Entries are immediate call-boundary markers, not returned/successful API proof. Completedreturn events prove lowerbounds. Missing/corrupt/duplicate terminal or pending-entry gap leaves totalsunknown. Configure/RR/callerExecute structurally0; providerinternalGPU/privatecallbackwarningsunknown. Numeric/output rejection never erases source-qualified physicalwork.')
