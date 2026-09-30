"""Bounded accounting for the pinned repetition=1 shader helper, not SDK work."""
from pathlib import Path
import math,re,hashlib

NUMBER=rb'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?'
TIMING=re.compile(rb'gpu_ms_median=('+NUMBER+rb') gpu_ms_p95=('+NUMBER+rb') debug_layer=([01])')
DIAGNOSTIC=re.compile(rb'validation_errors=(0|[1-9][0-9]{0,9}) validation_warnings=(0|[1-9][0-9]{0,9})')

def file_sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def complete_lines(data):
    # The helper always emits newline. An unterminated tail is retained as a claim, never a proof.
    parts=data.split(b'\n');return [p[:-1] if p.endswith(b'\r') else p for p in parts[:-1]],parts[-1]
def exact_fields(stdout,stderr):
    lines,tail=complete_lines(stdout);errlines,errtail=complete_lines(stderr)
    tc=[x for x in lines if b'gpu_ms_' in x or b'debug_layer=' in x]
    dc=[x for x in lines if b'validation_errors=' in x or b'validation_warnings=' in x]
    claimed_timing=tc+([tail] if b'gpu_ms_' in tail or b'debug_layer=' in tail else [])
    claimed_diag=dc+([tail] if b'validation_errors=' in tail or b'validation_warnings=' in tail else [])
    tm=TIMING.fullmatch(tc[0]) if len(claimed_timing)==1 and len(tc)==1 else None
    timing=None
    if tm:
        values=[float(tm[1]),float(tm[2])]
        if all(math.isfinite(v) and v>=0 for v in values):timing=dict(median_ms=values[0],p95_ms=values[1],debug_layer=int(tm[3]))
    dm=DIAGNOSTIC.fullmatch(dc[0]) if len(claimed_diag)==1 and len(dc)==1 else None
    diag=dict(errors=int(dm[1]),warnings=int(dm[2])) if dm and all(int(dm[i])<=4294967295 for i in (1,2)) else None
    return dict(timing=timing,diagnostic=diag,
        timing_claim_lines=[x.decode('ascii',errors='backslashreplace') for x in claimed_timing],
        diagnostic_claim_lines=[x.decode('ascii',errors='backslashreplace') for x in claimed_diag],
        stderr_marker_claim_lines=[x.decode('ascii',errors='backslashreplace') for x in errlines+[errtail] if b'gpu_ms_' in x or b'debug_layer=' in x or b'validation_errors=' in x or b'validation_warnings=' in x],
        stdout_unterminated_tail=tail.decode('ascii',errors='backslashreplace'),
        timing_grammar_unique_finite_full_line_valid=timing is not None,
        diagnostic_grammar_unique_integer_full_line_valid=diag is not None)

def accounting(folder,outputs,guard,monitor_exception=None,fresh_scope_authenticated=False):
    folder=Path(folder)
    stdout=(folder/'stdout.log').read_bytes() if (folder/'stdout.log').exists() else b''
    stderr=(folder/'stderr.log').read_bytes() if (folder/'stderr.log').exists() else b''
    fields=exact_fields(stdout,stderr)
    rows=[dict(path=o['path'],expected_bytes=o['bytes'],exists=Path(o['path']).exists(),
       actual_bytes=Path(o['path']).stat().st_size if Path(o['path']).exists() else None,
       sha256=file_sha(o['path']) if Path(o['path']).exists() else None) for o in outputs]
    sizes=all(r['exists'] and r['actual_bytes']==r['expected_bytes'] for r in rows)
    pid=guard.get('child_pid');validpid=type(pid) is int and pid>0
    returncode=guard.get('returncode');return_valid=type(returncode) is int
    denied=guard.get('status') in ('not_launched','not_launched_low_available_memory')
    known_no_child=denied and pid is None and returncode is None
    conflicts=[]
    if denied and (validpid or return_valid):conflicts.append('guard_denies_launch_but_records_PID_or_return')
    if known_no_child and (fields['timing_claim_lines'] or any(r['exists'] for r in rows) or stdout or stderr):
        conflicts.append('no_child_guard_with_artifact_or_log_claims_not_current_work')
    if guard and not validpid and not known_no_child:conflicts.append('guard_without_valid_child_identity')
    # Missing guard after a monitor/write exception can retain a fresh authenticated marker.
    # Explicit contradictory/no-child guard never permits logs to override the launch evidence.
    marker_allowed=fresh_scope_authenticated and not denied and not conflicts and (validpid or not guard)
    dispatch_proof=bool(marker_allowed and fields['timing'] is not None)
    launched_lower=int((validpid and not denied and not conflicts) or dispatch_proof)
    terminal=validpid and not conflicts and guard.get('status') in ('completed','failed_or_terminated') and return_valid and monitor_exception is None and not guard.get('terminated_owned_child',False)
    exact_dispatch=0 if known_no_child else (1 if dispatch_proof and terminal else None)
    exact_helper=0 if known_no_child else (1 if validpid and not conflicts else None)
    work=dict(helper_child_PID_claim=pid,helper_returncode_claim=returncode,helper_terminal_return_confirmed=bool(terminal),
        confirmed_helper_children_lower_bound=launched_lower,exact_helper_child_total=exact_helper,
        confirmed_shader_dispatches_lower_bound=int(dispatch_proof),confirmed_fence_completions_lower_bound=int(dispatch_proof),
        exact_shader_dispatch_total=exact_dispatch,partial_dispatch_total_unknown=exact_dispatch is None,
        fresh_scope_authenticated=bool(fresh_scope_authenticated),explicit_post_fence_stdout_proof=dispatch_proof,
        output_sizes_match=sizes,output_sizes_are_not_dispatch_proof=True,outputs=rows,
        fields=fields,evidence_conflicts=conflicts,monitor_exception=monitor_exception,
        stdout_sha256=hashlib.sha256(stdout).hexdigest(),stderr_sha256=hashlib.sha256(stderr).hexdigest(),
        source_scope='Exact pinned repetition1 helper emits timing after fence wait/device check. Source reading is a reference, not new historical EXE compilation proof. No SDK/native work.',
        known_no_child=known_no_child)
    diagnostic_ok=fields['diagnostic'] is not None and fields['diagnostic']==dict(errors=0,warnings=0)
    metadata=bool(terminal and guard.get('status')=='completed' and returncode==0 and dispatch_proof and sizes and diagnostic_ok and fields['timing']['debug_layer']==1 and stderr==b'' and not conflicts)
    work['metadata_accepted']=metadata
    work['strict_match_accepted']=False # updated only after independent byte comparison in driver
    return work
