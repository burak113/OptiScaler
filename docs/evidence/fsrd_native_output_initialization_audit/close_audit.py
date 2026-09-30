"""Append an explicit input-alpha qualification without rewriting frozen reports."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib,json
HERE=Path(__file__).resolve().parent
def identity(p):
    return {'path':str(p),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
def save(name,value):
    with (HERE/name).open('x',encoding='utf-8',newline='\n') as f:
        json.dump(value,f,indent=2,allow_nan=False);f.write('\n')
old=json.loads((HERE/'completion_manifest.json').read_text())
for r in old['files']:
    p=Path(r['path']);v=identity(p)
    assert v['bytes']==r['bytes'] and v['sha256']==r['sha256']
audit=json.loads((HERE/'audit.json').read_text())
all_outputs=[v for c in audit['contexts'].values() for v in c['outputs'].values()]
assert {tuple((v['input_alpha_min'],v['input_alpha_max'])) for v in all_outputs}=={(65504.,65504.),(0.,0.)}
sentinel=[v for k,c in audit['contexts'].items() if int(k[-1])>=4 for v in c['outputs'].values()]
assert len(sentinel)==8 and all(v['output_equals_input_alpha_fraction']==0 for v in sentinel)
addendum={'schema':'independent-audit-input-alpha-qualification-addendum-v1',
          'utc':datetime.now(timezone.utc).isoformat(),'audit':identity(HERE/'audit.json'),
          'original_reports_rewritten':False,
          'direct_diffuse_input_alpha':[65504,65504],'indirect_specular_input_alpha':[0,0],
          'sentinel_context_output_alpha':17,'all_sentinel_output_pixels_disagree_with_input_alpha':True,
          'normal_specular_input_output_zero_equality':'Observed equality of two zero-valued arrays cannot distinguish input copying, no destination write, or a same-value store.',
          'contract_field_qualification':'The audit.json input_alpha_copy_not_observed boolean is false because it tests that every input/output alpha equality fraction is zero. This strict all-context predicate is not a kernel-copying conclusion. The sentinel contexts disprove unconditional input-alpha copying for this experiment and show empirical destination-alpha retention; they do not establish a general alpha contract.',
          'audit_method_erratum':audit['audit_method_erratum'],
          'original_source_Git_newline_qualification':audit['source']['original_Git_newline_qualification'],
          'new_native_contexts':0,'new_native_RR_calls':0,'quality_accepted':False}
save('qualification_addendum.json',addendum)
compact=json.loads((HERE/'compact.json').read_text())
compact['schema']='native-output-initialization-independent-compact-v2'
compact['qualification_addendum']=identity(HERE/'qualification_addendum.json')
compact['qualifications'] += [addendum['normal_specular_input_output_zero_equality'],
                             addendum['contract_field_qualification'],
                             addendum['original_source_Git_newline_qualification'],
                             'The initial audit source-byte comparison failed on existing CRLF/LF normalization; the preserved v2 audit checks normalized Git source plus the pinned working bytes and passed.']
save('compact_v2.json',compact)
files=[identity(p) for p in sorted(HERE.iterdir()) if p.is_file()]
save('completion_manifest_v2.json',{'schema':'immutable-independent-audit-completion-v2',
     'status':'completed_passed_with_qualifications','head':audit['head'],
     'canonical_compact':identity(HERE/'compact_v2.json'),'full_audit':identity(HERE/'audit.json'),
     'new_native_contexts':0,'new_native_RR_calls':0,'quality_accepted':False,
     'files':files,'working_reports_unchanged':True})
print(json.dumps({'compact_v2':identity(HERE/'compact_v2.json'),
                  'completion_manifest_v2':identity(HERE/'completion_manifest_v2.json'),
                  'frozen_package_files':len(files)}))
