"""One fresh root-authorized stage. No compiler, retry or automatic next stage."""
from pathlib import Path
import json, os, re, sys, time
from common import *

def normal_terminal(g,stored,argv):
    return (g==stored and g['actual_CLOSED'] is True and g['child_pid'] is not None and
            isinstance(g['child_pid'],int) and g['child_pid']>0 and isinstance(g['returncode'],int) and
            g['status']==('completed' if g['returncode']==0 else 'failed_or_terminated') and
            not g['terminated_owned_child'] and 'monitor_error' not in g and
            g['args']==list(map(str,argv)) and g['working_directory']==str(ROOT))

def main():
    stage,authpath=sys.argv[1:];assert stage in PREREQS
    a=authorize(stage,authpath);assert not (RUNTIME/stage).exists(),'once-only namespace exists'
    RUNTIME.mkdir(exist_ok=True);d=RUNTIME/stage;d.mkdir()
    # Exact reviewed guard imported only inside the authorized root driver.
    from native_resource_guard import run_guarded
    before=[record(r['path']) for r in load(HERE/'source_freeze.json')['records']+assets()['records']]
    prereq=[]
    for pr in a['prerequisites']:
        previous=load(pr['path']);prereq += previous['outputs']+previous['prerequisite_pins']+[pr]
    prereq=list({r['path']:r for r in prereq}.values())
    for r in prereq:check(r)
    report=dict(stage=stage,status='RUNNING',stage_PASS=False,all_children_CLOSED=False,
                root_authority=record(authpath),actual_driver_PID=os.getpid(),children=[],
                before=before,prerequisite_pins=prereq,outputs=[],actual_helper_children=0,
                actual_RR_dispatches=0,actual_GPU_shader_dispatches=0,
                qualified_RR_contexts=0,failed_prefix_work_unknown=False)
    def checkpoint():
        # This driver-owned record may update; no child-owned file is hashed while open.
        (d/'execution_results.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    def child(argv,tag,kind):
        cd=d/'guards'/tag;cd.mkdir(parents=True);temp=cd/'TEMP';temp.mkdir()
        env=os.environ.copy();env.update(TEMP=str(temp),TMP=str(temp),PYTHONOPTIMIZE='0',PYTHONNOUSERSITE='1')
        for name in ('CL','_CL_','LINK','_LINK_'):env.pop(name,None)
        c=dict(tag=tag,kind=kind,argv=list(map(str,argv)),actual_CLOSED=False,child_pid=None,
               guard=None,ordinary_terminal_qualified=False,completed_dispatches=None);report['children'].append(c);checkpoint()
        try:g=run_guarded(argv,cd,ROOT,env,time.monotonic()+240)
        except BaseException:
            report['failed_prefix_work_unknown']=True;checkpoint();raise
        c.update(actual_CLOSED=g['actual_CLOSED'],child_pid=g['child_pid'],guard=g)
        if kind=='gpu' and g['child_pid'] is not None:report['actual_helper_children']+=1
        checkpoint()
        assert g['actual_CLOSED'] is True,'unknown child closure; no artifact reads'
        stored=load(cd/'resource_guard.json');assert g==stored
        if not normal_terminal(g,stored,argv):
            report['failed_prefix_work_unknown']=True;checkpoint()
            raise RuntimeError('nonordinary terminal; no child log/output reads or hashes')
        c['ordinary_terminal_qualified']=True;checkpoint()
        # Closed failure may have a valid work footer: preserve it before qualification.
        if g['child_pid'] is not None:
            stdout=(cd/'stdout.log').read_text(encoding='utf-8',errors='replace')
            stderr=(cd/'stderr.log').read_text(encoding='utf-8',errors='replace')
            if kind=='native':
                counts=re.findall(r'(?m)^dispatches=(\d+) validation_errors=(\d+) validation_warnings=(\d+) sdk_errors=(\d+) sdk_warnings=(\d+)$',stdout)
                if len(counts)==1:
                    c['completed_dispatches']=int(counts[0][0]);report['actual_RR_dispatches']+=c['completed_dispatches']
                else:report['failed_prefix_work_unknown']=True
            elif kind=='gpu':
                if len(re.findall(r'(?m)^validation_errors=\d+ validation_warnings=\d+$',stdout))==1:
                    c['completed_dispatches']=1;report['actual_GPU_shader_dispatches']+=1
                else:report['failed_prefix_work_unknown']=True
            checkpoint()
        assert g['returncode']==0,'ordinary child completed with failure returncode'
        assert not stderr.strip(),'ordinary stderr diagnostics'
        if kind in ('gpu','native'):
            assert 'RX 9070' in stdout and len(re.findall(r'\bdebug_layer=1\b',stdout))==1
            if kind=='native':
                assert counts==[('64','0','0','0','0')]
                assert len(re.findall(r'\bversion_query_result=6\b',stdout))==1,'unexpected provider query status'
                report['qualified_RR_contexts']+=1
            else:assert len(re.findall(r'(?m)^validation_errors=0 validation_warnings=0$',stdout))==1
        c['stdout']=record(cd/'stdout.log');c['stderr']=record(cd/'stderr.log');c['guard_record']=record(cd/'resource_guard.json')
        checkpoint();return stdout
    def cpu(action):
        child([sys.executable,'-B',str(HERE/'worker.py'),action,str(d)],action,'cpu')
        c=load(d/(action+'_worker_CLOSED.json'));g=report['children'][-1]['guard']
        assert c['PID']==g['child_pid'] and c['python_EXE']==str(Path(sys.executable).resolve()) and c['actual_cwd']==str(ROOT)
        assert c['numpy_version']==a['numpy_version'],'runtime version differs frozen root authority'
    try:
        if stage=='assemble':cpu('assemble')
        elif stage=='produce':
            rows=load(RUNTIME/'assemble'/'assembly.json')['converter_jobs']
            for row in rows:
                check(row['job'])
                for r in row['inputs']:check(r)
                assert all(not Path(r['path']).exists() for r in row['outputs'])
                child([item('helper')['path'],row['job']['path']],f'convert_{row["frame"]:02d}','gpu')
                for r in row['outputs']:assert Path(r['path']).stat().st_size==r['bytes']
            cpu('qualify_producer')
        elif stage=='native':
            p=load(RUNTIME/'produce'/'producer.json');assert [c['tag'] for c in p['cases']]==list(ORDER)
            expected=Path(item('expected_controls')['path']).read_bytes()
            for case in p['cases']:
                for r in case['inputs']+[case['job'],case['config'],case['frame_controls']]:check(r)
                for r in case['outputs']:
                    op=Path(r['path']);assert not op.exists();op.parent.mkdir(parents=True,exist_ok=True)
                assert not Path(case['controls_path']).exists()
                child([item('runner')['path'],case['job']['path']],case['tag'],'native')
                assert Path(case['controls_path']).read_bytes()==expected
                for r in case['outputs']:assert Path(r['path']).stat().st_size==r['bytes']
        elif stage in ('endpoint','remaining'):
            if stage=='remaining':assert load(RUNTIME/'score_endpoint'/'score.json')['continuation_permitted'] is True
            cpu('prepare_'+stage)
            tasks=load(d/'composition_jobs.json')['jobs'];assert len(tasks)==(4 if stage=='endpoint' else 252)
            for task in tasks:
                for r in task['inputs']+[task['job']]:check(r)
                assert all(not Path(r['path']).exists() for r in task['outputs'])
                child([item('helper')['path'],task['job']['path']],f'{task["tag"]}_{task["frame"]:02d}_{task["mode"]}','gpu')
                for r in task['outputs']:assert Path(r['path']).stat().st_size==r['bytes']
        elif stage in ('score_endpoint','score_all'):cpu(stage)
        # No before/after identity weakening even when a quality rejection is expected.
        for r in before+prereq:check(r)
        report['after_SOURCE_inputs_equal']=True
        report['all_children_CLOSED']=all(c['actual_CLOSED'] is True for c in report['children'])
        assert report['all_children_CLOSED']
        report['stage_PASS']=True;report['status']='CLOSED_QUALIFIED_'+stage.upper()
        if stage.startswith('score_'):
            scored=load(d/'score.json');report['decision']=scored['status']
            report['stage_PASS']=scored['continuation_permitted'] if stage=='score_endpoint' else scored['quality_PASS']
            report['status']='CLOSED_ACTUAL_SCORE_'+scored['status']
    except BaseException as e:
        report['status']='FAILED_STOP_NO_RETRY';report['error']=type(e).__name__+': '+str(e)
        report['all_children_CLOSED']=all(c['actual_CLOSED'] is True for c in report['children'])
        checkpoint()
        # No child files are read or hashed on unknown closure.
        if report['all_children_CLOSED'] and all(c['ordinary_terminal_qualified'] for c in report['children']):
            report['closed_diagnostic_files']=[record(p) for p in d.rglob('*') if p.is_file() and p.name!='execution_results.json']
        save(result(stage),report);return 1
    # Include outputs created in prior-stage job directories only after their child CLOSED.
    paths=[p for p in d.rglob('*') if p.is_file() and p.name not in ('result.json','execution_results.json')]
    if stage=='produce':paths += [Path(o['path']) for r in rows for o in r['outputs']]
    if stage=='native':paths += [Path(c['controls_path']) for c in p['cases']]
    report['outputs']=[record(p0) for p0 in sorted(set(paths))]
    checkpoint();save(result(stage),report);return 0
if __name__=='__main__':sys.exit(main())
