"""Preserve the first audit and correct its source newline comparison only."""
from pathlib import Path
import hashlib, json
HERE=Path(__file__).resolve().parent
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
source=HERE/'audit.py'
failure={'schema':'independent-audit-attempt1-failure-v1','script_sha256':sha(source),
         'observed_tool_returncode':1,
         'observed_exception':'AssertionError: original source untouched in HEAD',
         'observed_location':'audit.py main line 299; require(git show original HEAD blob == original working bytes)',
         'qualification':'The original working runner has the frozen CRLF bytes and pinned SHA; its pre-existing Git source blob has LF bytes. Attempt 1 therefore used an overly strict physical-byte equality for this source. All raw metrics and archive checks reached before this source check passed. This is an audit-method failure, not a native/producer failure.',
         'repair':'Audit v2 compares normalized source content to HEAD, confirms source git diff is empty, and retains the exact original working SHA. Existing preregistration, baseline freeze, source diff and failed audit.py remain untouched.',
         'native_contexts_added':0,'native_RR_calls_added':0}
with (HERE/'audit_attempt1_failure.json').open('x',encoding='utf-8',newline='\n') as f:
    json.dump(failure,f,indent=2);f.write('\n')
text=source.read_text()
old="    save('baseline_pre_freeze.json',{'schema':'audit-baseline-pre-freeze-v1','files':supplement})"
new="    require(readj(HERE/'baseline_pre_freeze.json')=={'schema':'audit-baseline-pre-freeze-v1','files':supplement},'preserved baseline preregistration exact')"
assert text.count(old)==1;text=text.replace(old,new)
old="    with (HERE/'source_whitelist.diff').open('x',encoding='utf-8',newline='\\n') as s: s.write(diff)"
new="    require((HERE/'source_whitelist.diff').read_text()==diff,'preserved source whitelist exact')"
assert text.count(old)==1;text=text.replace(old,new)
old="    require(git('show',HEAD+':'+ORIGINAL.relative_to(ROOT).as_posix())==ORIGINAL.read_bytes(),'original source untouched in HEAD')"
new="""    original_blob=git('show',HEAD+':'+ORIGINAL.relative_to(ROOT).as_posix())
    require(original_blob.decode().replace('\\r\\n','\\n')==ORIGINAL.read_text(),'original normalized source untouched in HEAD')
    require(git('diff','--',ORIGINAL.relative_to(ROOT).as_posix())==b'','original working source pristine')
    result['source']['original_Git_blob_sha256']=hashlib.sha256(original_blob).hexdigest()
    result['source']['original_working_bytes_sha256']=sha(ORIGINAL)
    result['source']['original_Git_newline_qualification']='Original source working bytes are pinned CRLF; its pre-existing Git blob is LF. Normalized source content and pristine Git diff are verified. The archive uses -text and is checked by physical byte equality.'
    result['audit_method_erratum']=readj(HERE/'audit_attempt1_failure.json')"""
assert text.count(old)==1;text=text.replace(old,new)
old="    text=shader.read_text()"
new="""    text=shader.read_text()
    require('OutColor[p] = half4(FloorRadiance(output), 1);' in text,'ordinary composition output alpha1')
    require('float3(InIndirectSpecular[p].rgb)' in text and 'float3(InDirectDiffuse[p].rgb)' in text,'ordinary native lobe RGB consumption')
    require('if (IsSet(FLAGS_RAW_SOURCE_BLIT))' in text,'separate raw source path')"""
assert text.count(old)==1;text=text.replace(old,new)
with (HERE/'audit_v2.py').open('x',encoding='utf-8',newline='\n') as f: f.write(text)
print(json.dumps({'preserved_attempt1_script_sha256':sha(source),'failure_record_sha256':sha(HERE/'audit_attempt1_failure.json'),'audit_v2_sha256':sha(HERE/'audit_v2.py')}))
