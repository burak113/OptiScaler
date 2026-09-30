"""Read-only accounting for exact B342 serial64 runner; no launcher/native import."""
from pathlib import Path
import hashlib,re
FRAME_BYTES=128*80*8
KEYS=('api','queued','executes','signals','events','waits','completed_GPU','observed_readback_pairs')
FOOTER=re.compile(rb'dispatches=(0|[1-9][0-9]*) validation_errors=(0|[1-9][0-9]*) validation_warnings=(0|[1-9][0-9]*) sdk_errors=(0|[1-9][0-9]*) sdk_warnings=(0|[1-9][0-9]*)')

def artifact(p):
    p=Path(p)
    try:
        raw=p.read_bytes();return {'path':str(p),'present':True,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()},raw
    except OSError as e:return {'path':str(p),'present':p.exists(),'bytes':None,'sha256':None,'read_error':type(e).__name__+': '+str(e)},b''

def derive(folder,guard):
    folder=Path(folder);artifacts=[];data={}
    for n in('stdout.log','stderr.log','dispatch_controls.bin','diffuse.bin','specular.bin'):
        meta,raw=artifact(folder/n);artifacts.append(meta);data[n]=raw
    lines=data['stdout.log'].splitlines(keepends=True);claims=[v for v in lines if v.startswith(b'dispatches=')]
    stderr_claims=[v.decode(errors='backslashreplace')for v in data['stderr.log'].splitlines()if v.startswith(b'dispatches=')]
    terminal=None
    if len(claims)==1 and claims[0].endswith(b'\n'):
        match=FOOTER.fullmatch(claims[0].rstrip(b'\r\n'))
        if match:
            v=list(map(int,match.groups()))
            # The source emits frames only AFTER all64 successful loops and
            # DestroyContext. No shorter terminal exists for these pinned jobs.
            if v[0]==64 and all(x<=0xffffffff for x in v[1:]):terminal=dict(zip(('dispatches','validation_errors','validation_warnings','sdk_errors','sdk_warnings'),v))
    pid=guard.get('child_pid');status=guard.get('status');current=type(pid)is int and pid>0 and status in('running','completed','failed_or_terminated')
    attempt=guard.get('executor_launch_attempt',{})
    fresh_unknown=status=='guard_evidence_unavailable'and isinstance(attempt,dict)and all(attempt.get(k)is True for k in('invocation_started','fresh_runtime_files_verified_absent','case_command_matches','before_guard_call_checkpointed'))
    prefix={}
    for n in('diffuse.bin','specular.bin'):
        b=data[n];meta=next(r for r in artifacts if Path(r['path']).name==n)
        prefix[n]={'whole_frames':len(b)//FRAME_BYTES if meta['bytes']is not None and len(b)<=64*FRAME_BYTES else 0,
            'trailing_bytes':len(b)%FRAME_BYTES,'within_capacity':meta['bytes']is not None and len(b)<=64*FRAME_BYTES}
    # Output writes occur after successful API, Execute, Signal/event/wait and
    # device check (source192,200-208). One lobe can be written before the other.
    # Controls are serialized BEFORE API192 and never prove successful API.
    gpu_lower=max(v['whole_frames']for v in prefix.values());paired_lower=min(v['whole_frames']for v in prefix.values())
    legal_terminal=terminal is not None;exact=current and legal_terminal
    attributable=current or fresh_unknown
    counts={k:0 for k in KEYS}
    if attributable:
        if legal_terminal:counts={k:64 for k in KEYS}
        else:counts={k:gpu_lower for k in KEYS};counts['observed_readback_pairs']=paired_lower
    provider_claim=any(v.startswith(b'provider=')and v.endswith(b'\n')for v in lines)
    created=current and(provider_claim or legal_terminal or gpu_lower>0)
    complete=current and legal_terminal
    disagreements=[]
    if not attributable and(any(data.values())or terminal is not None):disagreements.append('no_current_child_claims_not_work')
    if claims and not legal_terminal:disagreements.append('stdout_footer_unknown_truncated_duplicate_or_impossible')
    if stderr_claims:disagreements.append('stderr_footer_claims_not_authority')
    if fresh_unknown:disagreements.append('fresh_attempt_physical_lowerbounds_process_identity_and_totals_unknown')
    if legal_terminal:
        for n,v in prefix.items():
            if v['whole_frames']!=64 or v['trailing_bytes']or not v['within_capacity']:disagreements.append(n+'_vs_trusted_completed_footer')
    return {'schema':'B342-pinned-serial64-native-physical-work-before-metadata','counts':counts,'exact_totals':exact,'totals_unknown':not exact,
        'attempted_owned_child':current,'created_context_confirmed':bool(created),'completed_context_confirmed':bool(complete),
        'created_context_physical_lowerbound':int(created or(fresh_unknown and(provider_claim or legal_terminal or gpu_lower>0))),
        'completed_context_physical_lowerbound':int(complete or(fresh_unknown and legal_terminal)),
        'terminal_stdout_claim':terminal,'stdout_footer_claims':[v.decode(errors='backslashreplace')for v in claims],'stderr_footer_claims':stderr_claims,
        'output_prefix_claims':prefix,'applied_controls_whole_records':len(data['dispatch_controls.bin'])//184,'controls_never_API_success_proof':True,
        'evidence_disagreements':disagreements,'artifacts':artifacts,
        'successful_not_submitted_exact':0 if exact else None,'discarded_or_omitted_exact':0 if exact else None,
        'authority':'exact_source_terminal_after_full_loop_DestroyContext'if exact else('fresh_or_current_source_readback_or_terminal_physical_lowerbounds_totals_unknown'if attributable else'no_current_child'),
        'limits':'Source interpretation is bounded to byte-pinned B342 EXE and serial64 job header. Unique64 footer is only emitted after all64 loops and DestroyContext. Missing footer yields qualified lowerbounds from actually written readback prefixes; controls-before-API are never success counts. Fresh unidentified terminal is a lowerbound, not exact totals. Unseen queued/inflight work may exceed prefix; never infer discards from missing outputs. Historical EXE has no per-frame API journal or GetCompletedValue log; no new compilation provenance claim.'}
