"""Preserve V1; append an accounting-only V2 executor and before-native freeze."""
from pathlib import Path
import difflib,hashlib,json
HERE=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def identity(p):p=Path(p);return{'path':str(p),'bytes':p.stat().st_size,'sha256':sha(p)}
def save(p,v):
    with Path(p).open('x',encoding='utf-8',newline='\n')as f:json.dump(v,f,indent=2,allow_nan=False);f.write('\n')
def main():
    freeze=json.loads((HERE/'pre_native_freeze.json').read_text())
    for r in freeze['files']+freeze['external_sources']:
        p=Path(r['path']);assert p.stat().st_size==r['bytes']and sha(p)==r['sha256'],str(p)
    assert not(HERE/'evidence/results.json').exists()and not any((HERE/'evidence').rglob('resource_guard.json'))
    original=(HERE/'run_native.py').read_text();text=original;changes=[]
    def replace(old,new,label):
        nonlocal text
        assert text.count(old)==1,label;text=text.replace(old,new);changes.append({'label':label,'before':old,'after':new})
    replace('from native_resource_guard import run_guarded','from native_resource_guard import run_guarded\nfrom native_work_accounting import derive','accounting_module_import')
    replace("    check(freeze['files']);check(freeze['external_sources'])\n    target=HERE/'evidence/results.json'",
            "    check(freeze['files']);check(freeze['external_sources'])\n    supplement=json.loads((HERE/'accounting_v2_pre_native_freeze.json').read_text());check(supplement['files'])\n    target=HERE/'evidence/results.json'",'validate_supplement_before_launch')
    replace("'schema':'discarded-record-H2-actual-native-evidence-v1'","'schema':'discarded-record-H2-actual-native-evidence-v2-accounted-before-validation'",'accounting_schema')
    replace("'successful_API_RR_recordings':0,'queued_RR_dispatches':0,'discarded_RR_recordings':0,'cases':{},'quality_accepted':False,'game_run':False}",
"""'successful_API_RR_recordings':0,'queued_RR_dispatches':0,'discarded_RR_recordings':0,'cases':{},'quality_accepted':False,'game_run':False,
            'attempted_owned_children':0,'created_native_contexts_confirmed':0,'metadata_accepted_native_contexts':0,
            'observed_output_frames_confirmed':0,'incomplete_children_with_unquantified_native_work':0,
            'accounting_qualification':'Native work counters are derived before acceptance from actual stdout and flushed artifacts. Incomplete children may have additional unquantified work; no final marker/zero lower bound is not proof of no native work.'}""",'separate_native_work_and_acceptance_counts')
    replace("            check(freeze['files']);check(freeze['external_sources'])","            check(freeze['files']);check(freeze['external_sources']);check(supplement['files'])",'freeze_every_child')
    replace("            info={'guard':guard};report['cases'][c['tag']]=info;checkpoint()",
"""            accounting=derive(folder,guard,c)
            save(folder/'native_work_accounting.json',accounting)
            info={'guard':guard,'native_work_accounting':accounting,'native_work_accounting_file':identity(folder/'native_work_accounting.json'),'metadata_accepted':False}
            report['cases'][c['tag']]=info
            report['attempted_owned_children']+=int(accounting['attempted_owned_child'])
            report['created_native_contexts_confirmed']+=int(accounting['created_native_context_confirmed'])
            report['completed_native_contexts']+=int(accounting['completed_native_context_final_marker'])
            report['successful_API_RR_recordings']+=accounting['successful_API_RR_recordings_confirmed']
            report['queued_RR_dispatches']+=accounting['queued_RR_dispatches_confirmed_completed']
            report['discarded_RR_recordings']+=accounting['discarded_API_RR_recordings_confirmed']
            report['observed_output_frames_confirmed']+=accounting['observed_output_frames_confirmed']
            report['incomplete_children_with_unquantified_native_work']+=int(accounting['incomplete_child_native_work_may_exceed_confirmed_lower_bounds'])
            checkpoint()""",'account_and_checkpoint_before_any_guard_or_metadata_acceptance')
    replace("            report['completed_native_contexts']+=1;report['successful_API_RR_recordings']+=counts[0];report['queued_RR_dispatches']+=counts[1];report['discarded_RR_recordings']+=counts[2];checkpoint()",
            "            info['metadata_accepted']=True;report['metadata_accepted_native_contexts']+=1;checkpoint()",'acceptance_only_after_assertions_no_double_native_count')
    replace("        check(freeze['files']);check(freeze['external_sources']);report['sources_unchanged']=True",
            "        check(freeze['files']);check(freeze['external_sources']);check(supplement['files']);report['sources_unchanged']=True",'final_supplement_verification')
    with(HERE/'run_native_v2.py').open('x',encoding='utf-8',newline='\n')as f:f.write(text)
    with(HERE/'accounting_v2_driver.diff').open('x',encoding='utf-8',newline='\n')as f:f.write(''.join(difflib.unified_diff(original.splitlines(keepends=True),text.splitlines(keepends=True),fromfile='frozen_run_native_v1',tofile='accounting_only_run_native_v2')))
    supplement={'schema':'discarded-record-H2-accounting-only-pre-native-supplement-v1','status':'prepared_NOT_AUTHORIZED_TO_RUN',
        'original_registration':identity(HERE/'registration.json'),'original_pre_native_freeze':identity(HERE/'pre_native_freeze.json'),
        'preserved_V1_driver':identity(HERE/'run_native.py'),'canonical_future_executor':identity(HERE/'run_native_v2.py'),
        'accounting_module':identity(HERE/'native_work_accounting.py'),'driver_change_whitelist':changes,
        'reason':'V1 aggregate counters advanced after metadata/debug assertions. V2 derives/checkpoints confirmed actual work before guard/debug/control/output acceptance; metadata acceptance is separate.',
        'unchanged':['C++ runner source/executable','all7 inputs for all8 contexts','commands/params/mode order','expected controls/masks/indices','analysis metrics/alignments'],
        'planned_contexts':8,'planned_successful_API_RR_recordings':462,'planned_discarded_API_RR_recordings':4,'planned_queued_RR_dispatches':458,
        'actual_native_contexts':0,'actual_successful_API_RR_recordings':0,'actual_queued_RR_dispatches':0,
        'requires_before_any_native':'Root authorization after original source/preregistration review and bounded V2 accounting review. No launch in this preparation.'}
    save(HERE/'accounting_v2_registration.json',supplement)
    names=('run_native_v2.py','native_work_accounting.py','prepare_accounting_v2.py','accounting_v2_driver.diff','accounting_v2_registration.json','registration.json','pre_native_freeze.json','run_native.py','analyze.py')
    save(HERE/'accounting_v2_pre_native_freeze.json',{'schema':'H2-accounting-V2-before-any-native-byte-freeze-v1','files':[identity(HERE/n)for n in names],
                                                   'actual_native_contexts':0,'actual_successful_API_RR_recordings':0,'actual_queued_RR_dispatches':0})
    print(json.dumps({'V2_registration':identity(HERE/'accounting_v2_registration.json'),'V2_freeze':identity(HERE/'accounting_v2_pre_native_freeze.json'),
                      'V2_executor':identity(HERE/'run_native_v2.py'),'actual_native_contexts':0}),flush=True)
if __name__=='__main__':main()
