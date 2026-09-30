"""Pure filesystem/metadata helpers; no launcher or native imports."""
from pathlib import Path
import hashlib,json

RUNTIME_NAMES=('resource_guard.json','stdout.log','stderr.log','stage_events.jsonl',
    'recorded_frame_indices.bin','queued_frame_indices.bin','completed_frame_indices.bin',
    'observed_frame_indices.bin','output_presence.bin','dispatch_controls.bin',
    'diffuse.bin','specular.bin','native_work_accounting.json','executor_attempt.json')

def fresh_runtime(folder):
    records=[{'path':str(Path(folder)/n),'absent':not(Path(folder)/n).exists()}for n in RUNTIME_NAMES]
    return {'files':records,'all_absent':all(r['absent']for r in records)}

def _valid_guard(v,command):
    if not isinstance(v,dict):return False
    try:json.dumps(v,allow_nan=False)
    except (TypeError,ValueError):return False
    if v.get('status')not in('not_launched','not_launched_low_available_memory','running','completed','failed_or_terminated'):return False
    pid=v.get('child_pid');code=v.get('returncode')
    if pid is not None and(type(pid)is not int or pid<=0):return False
    if code is not None and type(code)is not int:return False
    if v['status']in('not_launched','not_launched_low_available_memory')and(pid is not None or code is not None):return False
    if v['status']in('running','completed','failed_or_terminated')and pid is None:return False
    if v['status']=='completed'and code!=0:return False
    if v['status']=='failed_or_terminated'and code is None:return False
    if 'args'in v and v['args']!=list(map(str,command)):return False
    return True

def _unique(pairs):
    value={}
    for k,v in pairs:
        if k in value:raise ValueError('duplicate JSON key')
        value[k]=v
    return value

def _finite(v):raise ValueError('non-finite JSON constant '+v)

def safe_guard_load(folder,attempt,command,returned=None):
    """Never throw while recovering physical work after a guard exception.

    Retain raw bytes/hash/read/parse/shape errors. A valid directly returned
    owned-guard object can recover PID even if its disk marker is damaged.
    Missing/bad marker with no valid return leaves process identity unknown.
    Valid direct return is canonical in both directions. Without it, a valid
    explicit no-child marker cannot be overridden by file claims.
    """
    p=Path(folder)/'resource_guard.json';e={'path':str(p),'present':p.exists(),'bytes':None,'sha256':None,'errors':[]}
    value=None
    try:
        raw=p.read_bytes();e.update(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
        try:value=json.loads(raw,object_pairs_hook=_unique,parse_constant=_finite)
        except (ValueError,UnicodeDecodeError,TypeError)as x:e['errors'].append('parse: '+type(x).__name__+': '+str(x))
    except OSError as x:e['errors'].append('read: '+type(x).__name__+': '+str(x))
    stored_valid=_valid_guard(value,command);returned_valid=_valid_guard(returned,command)
    if value is not None and not stored_valid:e['errors'].append('stored_guard_not_valid_dict_shape_status_pid_returncode_or_command')
    e.update(stored_guard_claim=value,stored_guard_valid=stored_valid,returned_guard_valid=returned_valid)
    if returned is not None and not returned_valid:e['errors'].append('returned_guard_not_valid')
    if returned_valid:
        guard=dict(returned);e['authority']='direct_owned_guard_return'
        if stored_valid and returned!=value:e['errors'].append('returned_guard_vs_stored_guard_conflict')
    elif stored_valid:guard=dict(value);e['authority']='valid_fresh_owned_guard_marker'
    else:
        guard={'status':'guard_evidence_unavailable','child_pid':None,'returncode':None}
        e['authority']='fresh_executor_attempt_only_process_identity_unknown'
    guard['executor_launch_attempt']=attempt;guard['guard_load_evidence']=e
    return guard
