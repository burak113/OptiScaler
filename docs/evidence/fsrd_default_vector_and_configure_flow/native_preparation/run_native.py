"""Frozen future scalar-vector contrast executor. Root must verify query and preparation seals and authorize; preparation never calls main."""
from pathlib import Path
import argparse,hashlib,json,os,struct,sys
sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
from executor_evidence import fresh_runtime,safe_guard_load
from native_work_accounting import derive,KEYS

def ident(p):
    p=Path(p);return {'path':str(p.resolve()),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
def save(p,v):
    with Path(p).open('w',encoding='utf-8',newline='\n')as f:json.dump(v,f,indent=2,allow_nan=False);f.write('\n')
def verify(records):
    for r in records:assert ident(r['path'])==r,r['path']
def verify_tuning(c):
    p=Path(c['job']).parent/'tuning_values.bin';raw=p.read_bytes()
    assert len(raw)==24 and list(struct.unpack('<6I',raw))==c['tuning_float32_bits'],'Frozen sidecar exact length/bits'
    assert ident(p)==c['tuning_sidecar'],'Frozen sidecar identity'

def main():
    arg=argparse.ArgumentParser();arg.add_argument('--execute-native',action='store_true',required=True);arg.parse_args()
    reg=json.loads((HERE/'registration.json').read_text());freeze=json.loads((HERE/'pre_native_freeze.json').read_text())
    verify(freeze['files']);verify(freeze['external_sources'])
    assert reg['status']=='PREPARED_CPU_ONLY_NOT_AUTHORIZED_NATIVE'
    result=HERE/'execution_results.json';assert not result.exists(),'No native retry/result overwrite'
    for c in reg['cases']:
        verify_tuning(c)
        assert fresh_runtime(Path(c['job']).parent)['all_absent'],'No prior runtime allowed'
    temp=(HERE/'execution_TEMP').resolve();assert temp.drive.upper()=='F:'and HERE in temp.parents
    temp.mkdir(exist_ok=True);os.environ['TMP']=str(temp);os.environ['TEMP']=str(temp)
    report={'schema':'clean-fork-versus-public-default-vector-four-fresh-contexts-native-raw-only','status':'running','jobs':[],'contexts_created_confirmed':0,'contexts_completed_confirmed':0,
        'executor_invocations':0,'counts':{k:0 for k in KEYS},'totals_unknown_children':0,'accepted_contexts':0,'composition_GPU_jobs':0,'old_B_TP_new_native':0,
        'quality_accepted':False,'game_run':False,'owned_child_environment':{'TMP':str(temp),'TEMP':str(temp)}}
    def checkpoint():save(result,report)
    checkpoint()
    from native_resource_guard import run_guarded
    try:
        for c in reg['cases']:
            verify(freeze['files']);verify(freeze['external_sources']);folder=Path(c['job']).parent
            verify_tuning(c) # exact sidecar bytes/bits/length before this owned child
            preflight=fresh_runtime(folder);assert preflight['all_absent']
            attempt={'invocation_started':True,'fresh_runtime_files_verified_absent':True,'case_command_matches':True,'before_guard_call_checkpointed':True,'command':c['command'],'preflight':preflight}
            save(folder/'executor_attempt.json',attempt);report['executor_invocations']+=1;checkpoint()
            returned=None;error=None
            try:returned=run_guarded(c['command'],folder,timeout=240,maximum_working_set=2*1024**3,minimum_available_memory=1024**3,interval=.2)
            except BaseException as e:error=type(e).__name__+': '+str(e)
            guard=safe_guard_load(folder,attempt,c['command'],returned);work=derive(folder,guard)
            save(folder/'native_work_accounting.json',work)
            row={'tag':c['tag'],'guard':guard,'work':work,'guard_error':error,'accepted':False,'runtime_folder':str(folder)};report['jobs'].append(row)
            report['contexts_created_confirmed']+=int(work['created_context_confirmed']);report['contexts_completed_confirmed']+=int(work['completed_context_confirmed'])
            report['totals_unknown_children']+=int(work['totals_unknown'])
            for k in KEYS:report['counts'][k]+=work['counts'][k]
            checkpoint() # physical work before monitor, diagnostic, output/controls acceptance
            if error:raise RuntimeError(error)
            assert not guard['guard_load_evidence']['errors'],'Guard evidence rejected; work preserved'
            assert guard['status']=='completed'and guard['returncode']==0 and not guard.get('terminated_owned_child')
            assert work['exact_totals']and work['completed_context_confirmed']and not work['evidence_disagreements']
            footer=work['terminal_stdout_claim'];assert all(footer[k]==0 for k in('validation_errors','validation_warnings','sdk_errors','sdk_warnings'))
            stdout=(folder/'stdout.log').read_bytes();stderr=(folder/'stderr.log').read_bytes()
            assert stderr==b'','Unexpected ordinary/SDK warning/error: stop without anticipation amendment'
            assert any(v.startswith(b'adapter=')and v.endswith(b'debug_layer=1')for v in stdout.splitlines())
            assert(folder/'dispatch_controls.bin').read_bytes()==(folder/'expected_applied_dispatch_controls.bin').read_bytes()
            import numpy as np
            outputs={}
            for name in('diffuse.bin','specular.bin'):
                q=folder/name;assert q.stat().st_size==64*128*80*8
                data=np.fromfile(q,'<f2').reshape(64,80,128,4)
                assert np.isfinite(data[...,:3]).all(),'Nonfinite consumed native RGB'
                outputs[name]={**ident(q),'observed_source_frame_indices':list(range(64)),'RGB_finite':True,'output_A_retained_not_consumed_or_finite_gate':True}
            row.update(accepted=True,outputs=outputs,controls=ident(folder/'dispatch_controls.bin'));report['accepted_contexts']+=1;checkpoint()
        verify(freeze['files']);verify(freeze['external_sources'])
        assert report['accepted_contexts']==report['contexts_created_confirmed']==report['contexts_completed_confirmed']==4 and report['totals_unknown_children']==0
        assert all(v==256 for v in report['counts'].values())
        report['status']='completed_fork_versus_defaults_native_raw_only_not_composed_not_quality_accepted';checkpoint()
    except BaseException as e:
        report.update(status='failed_preserved_no_retry',error=type(e).__name__+': '+str(e));checkpoint();raise
if __name__=='__main__':main()
