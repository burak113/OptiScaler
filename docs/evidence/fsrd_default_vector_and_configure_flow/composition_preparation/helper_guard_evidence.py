from pathlib import Path
import json,hashlib
def load_guard_best_effort(folder,returned_guard,monitor_error):
    path=Path(folder)/'resource_guard.json';artifact=dict(path=str(path),exists=path.exists(),sha256=None,bytes=None,read_error=None,parse_error=None,returned_guard_claim=returned_guard,stored_guard_claim=None,returned_stored_conflict=False,authority=None)
    known_status=('not_launched','not_launched_low_available_memory','running','completed','failed_or_terminated')
    returned_valid=isinstance(returned_guard,dict) and returned_guard.get('status') in known_status
    guard=returned_guard if returned_valid else {}
    stored=None
    errors=[]
    if not isinstance(returned_guard,dict):errors.append('returned guard root is not a dict')
    elif returned_guard and not returned_valid:errors.append('returned guard status is invalid')
    if path.exists():
        stage='read'
        try:
            raw=path.read_bytes();artifact.update(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
            stage='parse'
            parsed=json.loads(raw.decode('utf-8'))
            artifact['stored_guard_claim']=parsed
            if not isinstance(parsed,dict):raise ValueError('stored guard root is not a dict')
            if parsed.get('status') not in known_status:raise ValueError('stored guard status is invalid')
            stored=parsed
        except Exception as e:
            artifact[stage+'_error']=type(e).__name__+': '+str(e);errors.append(artifact[stage+'_error'])
    else:
        errors.append('guard file absent; totals unknown')
    if returned_valid:
        guard=returned_guard;artifact['authority']='direct_returned_guard'
        if stored is not None and stored!=returned_guard:
            artifact['returned_stored_conflict']=True;errors.append('returned guard and stored guard disagree; direct returned authority retained')
    elif stored is not None:
        guard=stored;artifact['authority']='stored_guard_after_absent_valid_return'
    else:
        guard={};artifact['authority']='no_valid_guard_fresh_marker_lowerbounds_only'
    combined='; '.join(([monitor_error] if monitor_error else [])+errors) or None
    return guard,combined,artifact
