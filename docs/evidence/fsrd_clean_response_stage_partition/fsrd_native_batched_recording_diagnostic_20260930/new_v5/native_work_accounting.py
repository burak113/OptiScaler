"""Accounting-only V3. No launcher, pixel parsing, score, or capacity substitution.

The guard supplied by the owned executor proves a current child. A known stdout
terminal is checked against globally reachable pinned CPP counter states; the
journal and index files are independent acceptance evidence, not prerequisites
for recovering direct work counters. V1/V2 remain immutable historical evidence.
"""
from pathlib import Path
import importlib.util,json
V1=Path(__file__).resolve().parent.parent
_spec=importlib.util.spec_from_file_location('_fsrd_frozen_v3_indices',V1/'native_work_accounting_core_v3.py')
_core=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(_core)
indices,artifact=_core.indices,_core.artifact
COUNT_KEYS=('api','queued','completed','observed','executes','signal_attempts','signals','event_attempts','events','wait_attempts','waits')
DIAG_KEYS=('validation_errors','validation_warnings','sdk_errors','sdk_warnings')
FIELDS=set(COUNT_KEYS+DIAG_KEYS+('stage','frame','fence','terminal','context_destroyed','discarded','omitted'))

def _unique(pairs):
    v={}
    for k,x in pairs:
        if k in v:raise ValueError('duplicate JSON key')
        v[k]=x
    return v

def _reject_constant(v):raise ValueError('non-finite JSON constant '+v)
def parse(data):return json.loads(data,object_pairs_hook=_unique,parse_constant=_reject_constant)

def _shape(v):
    return (isinstance(v,dict)and set(v)==FIELDS and isinstance(v['stage'],str)
        and type(v['frame'])is int and type(v['fence'])is int and 0<=v['fence']<=64
        and type(v['terminal'])is bool and type(v['context_destroyed'])is bool
        and all(type(v[k])is int and 0<=v[k]<=0xffffffff for k in COUNT_KEYS+DIAG_KEYS)
        and type(v['discarded'])is int and v['discarded']==0 and type(v['omitted'])is int and v['omitted']==0)

def grammar(k):
    """Exact normal snapshots from CPP 240,273,280,282,285,288-297,306,311."""
    if type(k)is not int or k not in(1,2,4):raise ValueError('unsupported frozen K')
    c={q:0 for q in COUNT_KEYS};out=[]
    def add(stage,frame,fence,terminal=False,destroyed=False):
        out.append({'stage':stage,'frame':frame,'fence':fence,'terminal':terminal,'context_destroyed':destroyed,**c})
    add('context_created',-1,0)
    for begin in range(0,64,k):
        end=begin+k-1;target=begin+k
        for f in range(begin,begin+k):
            c['api']+=1;add('api_ok',f,0);add('list_closed',f,0)
        add('group_recorded',end,0)
        for f in range(begin,begin+k):
            c['queued']+=1;c['executes']+=1;add('execute',f,0)
        for stem,attempt,success in [('signal','signal_attempts','signals'),('event','event_attempts','events'),('wait','wait_attempts','waits')]:
            c[attempt]+=1;add(stem+'_start',end,target);c[success]+=1;add(stem+'_ok',end,target)
        c['completed']+=k;add('group_completed',end,target)
        for f in range(begin,begin+k):c['observed']+=1;add('observed',f,target)
    add('context_destroyed',63,64,True,True);return out

def _normal(v,expected,previous):
    return (_shape(v)and all(v[k]==value for k,value in expected.items())
        and all(v[q]>=previous.get(q,0)for q in DIAG_KEYS)
        and (v['stage']!='context_destroyed'or all(v[q]==0 for q in DIAG_KEYS)))

def _failed_prefix(v,accepted,position,pattern):
    """Strict journal transition, including one increment before a failed sink write."""
    if not _shape(v)or not accepted or accepted[-1]['terminal']:return False
    if (v['stage'],v['frame'],v['terminal'],v['context_destroyed'])!=('failed',-1,True,False):return False
    last=accepted[-1];frontiers=[last]
    if position<len(pattern):frontiers.append(pattern[position])
    return (any(all(v[q]==x[q]for q in COUNT_KEYS)for x in frontiers)
        and v['fence']==v['completed']and all(v[q]>=last[q]for q in DIAG_KEYS))

def _global_terminal(v,pattern):
    """Physical counter authority does not require intact files written after the work.

    The catch at CPP317 can retain any reachable counter tuple: API/Execute,
    signal/event/wait increments precede snapshots, completion follows actual
    fence/device proof before index writes, observation follows its index write.
    Initial all-zero failed is reachable inside diagnostics at242; failure of
    context_created at240 itself is outside this catch and emits no footer.
    """
    if not _shape(v):return False
    if v['stage']=='context_destroyed':return _normal(v,pattern[-1],{})
    if (v['stage'],v['frame'],v['terminal'],v['context_destroyed'])!=('failed',-1,True,False):return False
    return v['fence']==v['completed']and any(all(v[q]==x[q]for q in COUNT_KEYS)for x in pattern)

def _stdout_authority(claims,bad,pattern):
    if bad:return None,False,None
    if len(claims)==1 and _global_terminal(claims[0],pattern):
        v=claims[0];return v,v['stage']=='context_destroyed','globally_reachable_unique_CPP_stdout_terminal'
    # snapshot writes terminal stdout at217 BEFORE checking ledger at218. A
    # failed context_destroyed ledger write is caught at315 and emits failed317.
    # No work/diagnostic collection occurs between these two snapshots. The
    # second false destroyed parameter does not undo DestroyContext at311.
    if len(claims)==2:
        first,last=claims
        if (_global_terminal(first,pattern)and first['stage']=='context_destroyed'
            and _global_terminal(last,pattern)and last['stage']=='failed'
            and all(first[q]==last[q]for q in COUNT_KEYS+DIAG_KEYS)and first['fence']==last['fence']):
            return last,True,'exact_CPP_context_destroyed_then_failed_ledger_write_pair'
    return None,False,None

def derive(folder,guard,case):
    folder=Path(folder);pattern=grammar(case['K']);accepted=[];position=0;issues=[];rejected=[];partial=False;ledger_failed=False
    p=folder/'stage_events.jsonl';raw=p.read_bytes()if p.exists()else b''
    for line_number,line in enumerate(raw.splitlines(keepends=True),1):
        if not line.endswith(b'\n'):
            partial=True;ledger_failed=True;rejected.append({'line':line_number,'reason':'truncated_record'});break
        try:v=parse(line)
        except (ValueError,UnicodeDecodeError,TypeError)as e:
            ledger_failed=True;rejected.append({'line':line_number,'reason':'invalid_JSON','error':str(e)});break
        previous=accepted[-1]if accepted else {}
        if position<len(pattern)and _normal(v,pattern[position],previous):accepted.append(v);position+=1
        elif _failed_prefix(v,accepted,position,pattern):accepted.append(v)
        else:
            ledger_failed=True;rejected.append({'line':line_number,'reason':'stage_frame_fence_flags_or_exact_counter_transition','claim':v});break
    if ledger_failed:issues.append('invalid_or_truncated_ledger_suffix_ignored_for_work_authority')
    full_normal=position==len(pattern)and len(accepted)==len(pattern)and not ledger_failed
    stdout=(folder/'stdout.log').read_bytes()if(folder/'stdout.log').exists()else b''
    stderr=(folder/'stderr.log').read_bytes()if(folder/'stderr.log').exists()else b''
    stdout_claims=[];bad_stdout=False;stderr_claims=[]
    for line in stdout.splitlines(keepends=True):
        if not line.startswith(b'BATCH_COUNTERS '):continue
        try:
            if not line.endswith(b'\n'):raise ValueError('truncated terminal stdout')
            stdout_claims.append(parse(line[len(b'BATCH_COUNTERS '):]))
        except (ValueError,UnicodeDecodeError,TypeError)as e:bad_stdout=True;rejected.append({'channel':'stdout','reason':str(e)})
    for line in stderr.splitlines():
        if line.startswith(b'BATCH_COUNTERS '):
            try:stderr_claims.append(parse(line[len(b'BATCH_COUNTERS '):]))
            except (ValueError,UnicodeDecodeError,TypeError):stderr_claims.append({'malformed':True})
    if stderr_claims:issues.append('stderr_counter_like_claims_not_CPP_authority')
    candidate,destruction_proved,authority=_stdout_authority(stdout_claims,bad_stdout,pattern)
    if (stdout_claims or bad_stdout)and candidate is None:issues.append('stdout_terminal_not_known_unique_or_exact_reachable_pair')
    records={name:indices(folder/name)for name in('recorded_frame_indices.bin','queued_frame_indices.bin','completed_frame_indices.bin','observed_frame_indices.bin')}
    valid={name:r['trailing_bytes']==0 and r['values']==list(range(r['whole_u32_records']))and r['whole_u32_records']<=64 for name,r in records.items()}
    lower={q:(accepted[-1][q]if accepted else 0)for q in COUNT_KEYS}
    if valid['recorded_frame_indices.bin']:lower['api']=max(lower['api'],records['recorded_frame_indices.bin']['whole_u32_records'])
    q=records['queued_frame_indices.bin']['whole_u32_records']
    if valid['queued_frame_indices.bin']and q<=lower['api']:lower['queued']=max(lower['queued'],q);lower['executes']=max(lower['executes'],q)
    n=records['completed_frame_indices.bin']['whole_u32_records'];k=case['K'];required_target=((n+k-1)//k)*k
    if (n and valid['completed_frame_indices.bin']and accepted and required_target<=lower['queued']
        and any(v['stage']=='wait_ok'and v['fence']==required_target for v in accepted)):lower['completed']=max(lower['completed'],n)
    n=records['observed_frame_indices.bin']['whole_u32_records']
    if valid['observed_frame_indices.bin']and n<=lower['completed']:lower['observed']=max(lower['observed'],n)
    # The owned guard opens stdout/stderr with wb only after starting its launch
    # path. Low-RAM/not-launched guards may leave old files untouched. A positive
    # PID AND a guard state reachable after Popen are necessary attribution proof.
    pid=guard.get('child_pid');status=guard.get('status')
    current=type(pid)is int and pid>0 and status in('running','completed','failed_or_terminated')
    attempt=guard.get('executor_launch_attempt',{})
    fresh_unidentified=(status=='guard_evidence_unavailable'and isinstance(attempt,dict)
        and all(attempt.get(q)is True for q in('invocation_started','fresh_runtime_files_verified_absent','case_command_matches','before_guard_call_checkpointed')))
    terminal=candidate if current else None
    if fresh_unidentified:
        # No PID is invented. Fresh runtime files produced after the authenticated
        # executor invocation support physical lower bounds, never exact totals.
        attributed_lower=({q:candidate[q] for q in COUNT_KEYS} if candidate is not None else dict(lower))
        counts=dict(attributed_lower)
        if candidate is not None and any(lower[q]>candidate[q] for q in COUNT_KEYS):
            issues.append('source_prefix_exceeds_globally_reachable_stdout_candidate_counters')
        issues.append('fresh_executor_attempt_physical_lower_bounds_process_identity_and_totals_unknown')
    elif not current:
        issues.append('no_current_owned_child_proof_all_file_claims_unattributed')
        counts={q:0 for q in COUNT_KEYS};attributed_lower={q:0 for q in COUNT_KEYS}
    else:
        attributed_lower={q:terminal[q]for q in COUNT_KEYS}if terminal is not None else dict(lower)
        counts=dict(attributed_lower)
    if terminal is not None:
        if not accepted:issues.append('missing_valid_initial_ledger_despite_trusted_CPP_stdout')
        elif accepted[-1]!=terminal:issues.append('journal_incomplete_or_terminal_disagreement_with_trusted_CPP_stdout')
        if any(lower[q]>terminal[q]for q in COUNT_KEYS):issues.append('source_prefix_exceeds_trusted_CPP_stdout_counters')
        if len(stdout_claims)==2:issues.append('completed_context_then_caught_terminal_ledger_write_failure')
    for name,q in [('recorded_frame_indices.bin','api'),('queued_frame_indices.bin','queued'),('completed_frame_indices.bin','completed'),('observed_frame_indices.bin','observed')]:
        if not valid[name]:issues.append(name+'_not_valid_bounded_source_index_prefix')
        elif terminal is not None and (not records[name]['present']or records[name]['whole_u32_records']!=terminal[q]):issues.append(name+'_vs_trusted_terminal_counter')
    provider_line=any(line.startswith(b'provider=')for line in stdout.splitlines())
    created=current and bool(terminal is not None or accepted or lower['api']>0 or provider_line)
    complete=current and terminal is not None and destruction_proved
    physical_created=created or(fresh_unidentified and bool(candidate is not None or accepted or lower['api']>0 or provider_line))
    physical_complete=complete or(fresh_unidentified and candidate is not None and destruction_proved)
    process_exited=current and type(guard.get('returncode'))is int
    unsubmitted=None if terminal is None else counts['api']-counts['queued']
    abandoned=None if terminal is None or not process_exited else unsubmitted
    return {'schema':'batched-recording-current-child-global-terminal-accounting-v3','case':case['tag'],
        'attempted_owned_child':current,'guard_current_child_proof':{'positive_integer_pid':type(pid)is int and pid>0,'post_Popen_status':status in('running','completed','failed_or_terminated'),'confirmed':current},
        'created_native_context_confirmed':created,'completed_context_final_marker':complete,
        'created_context_physical_lower_bound':int(physical_created),'completed_context_physical_lower_bound':int(physical_complete),
        'fresh_executor_attempt_without_process_identity':fresh_unidentified,
        'counts':counts,'count_authority':authority if terminal is not None else('current_child_valid_source_prefix_lower_bounds_totals_unknown'if current else('fresh_executor_attempt_CPP_physical_lower_bounds_identity_and_totals_unknown'if fresh_unidentified else'no_current_owned_child_file_claims_not_work')),
        'totals_unknown':terminal is None,'terminal_CPP_snapshot':terminal,'stdout_terminal_claims':stdout_claims,'stderr_counter_like_claims':stderr_claims,
        'globally_reachable_stdout_candidate':candidate,'stdout_proves_context_destroyed':destruction_proved,
        'valid_prefix_lower_bounds':attributed_lower,'unattributed_or_secondary_prefix_claims':lower,'stage_events':accepted,'rejected_claims':rejected,
        'registered_stage_pattern_exact':current and full_normal,'event_parse_partial':partial,'ledger_suffix_invalid':ledger_failed,'evidence_disagreements':issues,
        'index_records':records,'valid_index_prefixes':valid,'provider_creation_line_claim':provider_line,
        'successful_not_submitted_records_exact':unsubmitted,'successful_unsubmitted_records_abandoned_on_confirmed_process_exit':abandoned,
        'reported_CPP_discarded':None if terminal is None else terminal['discarded'],'reported_CPP_omitted':None if terminal is None else terminal['omitted'],
        'discard_qualification':'CPP discarded=0 means no explicit skip branch. Exact API-minus-queued is successful unsubmitted recordings; confirmed child exit makes those recordings abandoned. Queued-minus-completed is unproven GPU completion, never a discard/noAPI inference. Unknown totals do not support subtraction of lower bounds as exact abandonment.',
        'unproven_queued_GPU_work_may_have_completed':counts['queued']>counts['completed'],
        'incomplete_child_work_may_exceed_confirmed_counts':(current or fresh_unidentified)and terminal is None,
        'completed_GPU_count_is_confirmed_fence_prefix_only':True,
        'qualification':'Current owned-child guard proof gates all attribution. Known coherent stdout terminal counters are independently validated against globally reachable exact pinned CPP states. Only the concrete ordered complete-then-failed ledger-write pair is an allowed multiple terminal. Missing/corrupt journal/index does not erase direct physical work; it remains disagreement/acceptance evidence. Without trusted stdout, valid source prefixes are lower bounds with unknown totals. Stderr/unknown/impossible/other duplicate terminals never establish authority. Capacities never become observations. Initial context_created write failure is before local catch and may have provider creation line but no terminal.',
        'artifacts':[artifact(folder/name)for name in('stdout.log','stderr.log','stage_events.jsonl','recorded_frame_indices.bin','queued_frame_indices.bin','completed_frame_indices.bin','observed_frame_indices.bin','output_presence.bin','dispatch_controls.bin','diffuse.bin','specular.bin')]}
