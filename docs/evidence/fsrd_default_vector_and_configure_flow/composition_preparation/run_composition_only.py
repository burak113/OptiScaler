"""Future exact frozen composition jobs only; CPU preparation never invokes this entry."""
from pathlib import Path
import argparse,os,json,hashlib
import numpy as np
from helper_work_accounting import accounting
from helper_guard_evidence import load_guard_best_effort
HERE=Path(__file__).resolve().parent
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb')as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def read(p):return json.loads(Path(p).read_text())
def save(p,o):Path(p).write_text(json.dumps(o,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def verify(records):
 for r in records:
  p=Path(r['path']);assert p.stat().st_size==r['bytes']and sha(p)==r['sha256'],str(p)
def runtime_paths(reg):
 return [HERE/'execution_results.json',HERE/'composition_metrics.json',HERE/'composed_sequences.npz']+[Path(j['job']).parent/n for j in reg['jobs']for n in('resource_guard.json','stdout.log','stderr.log')]+[Path(o['path'])for j in reg['jobs']for o in j['outputs']]
def refuse_existing(reg):
 existing=[str(p)for p in runtime_paths(reg)if p.exists()]
 if existing:raise ValueError('Preserve existing runtime; no retry: '+json.dumps(existing))
def main():
 p=argparse.ArgumentParser();p.add_argument('--execute-composition-only',action='store_true',required=True);p.parse_args()
 frozen=read(HERE/'pre_execution_freeze.json');verify(frozen['owned']);verify(frozen['external_sources'])
 reg=read(HERE/'registration.json');assert reg['status']=='PREPARED_CPU_ONLY_NO_COMPOSITION_GPU_AUTHORIZATION'
 assert len(reg['jobs'])==reg['planned_only_helper_jobs']==64*len(reg['representative_order']) and [(j['frame'],j['arm'])for j in reg['jobs']]==[(f,a)for f in range(64)for a in reg['representative_order']]
 assert reg['native_postgate_pinned']and reg['root_receipt_pinned'] # Finalization only after both actual pins.
 refuse_existing(reg)
 temp=(HERE/'execution_TEMP').resolve();assert temp.drive.upper()=='F:'and HERE.resolve()in temp.parents;temp.mkdir(exist_ok=False)
 os.environ['TMP']=str(temp);os.environ['TEMP']=str(temp);os.environ['OPENBLAS_NUM_THREADS']='1'
 target=HERE/'execution_results.json'
 report=dict(status='running_composition_only',jobs=[],executor_job_invocations_started=0,helper_children_lower_bound=0,confirmed_shader_dispatches_lower_bound=0,confirmed_fence_completions_lower_bound=0,exact_helper_total=0,exact_shader_dispatch_total=0,metadata_accepted_jobs=0,observed_replay_accepted_frames=0,inherited_prior_observed_replay_passed_frames=64,completed_accepted_jobs=0,actual_new_native_contexts=0,actual_new_native_API=0,quality_accepted=False,game_run=False,logical_native_cohorts=reg['logical_order'],actual_composed_representatives=reg['representative_order'],omitted_composition_metrics_inherited=reg['trace_selection'],environment=dict(TMP=str(temp),TEMP=str(temp),OPENBLAS_NUM_THREADS='1'),count_qualification='Source-qualified repetition1 helper shader work; post-fence marker and child evidence precede metadata/replay acceptance. No SDK call. Missing proof retains unknown totals/lowerbounds.')
 save(target,report)
 from native_resource_guard import run_guarded
 try:
  for job in reg['jobs']:
   verify(frozen['owned']);verify(frozen['external_sources']);folder=Path(job['job']).parent
   verify(job['inputs']);verify([job['CB']]) # Exact inherited fixed inputs checked before child.
   assert not any((folder/n).exists()for n in('resource_guard.json','stdout.log','stderr.log'))and not any(Path(o['path']).exists()for o in job['outputs'])
   assert Path(os.environ['TMP']).resolve()==temp==Path(os.environ['TEMP']).resolve()
   report['executor_job_invocations_started']+=1;save(target,report)
   returned={};error=None
   try:returned=run_guarded([str(HERE/'fsrd_gpu_runner.exe'),job['job']],folder,timeout=240,maximum_working_set=2*1024**3,minimum_available_memory=1024**3,interval=.2)
   except BaseException as e:error=type(e).__name__+': '+str(e)
   guard,error,artifact=load_guard_best_effort(folder,returned,error)
   work=accounting(folder,job['outputs'],guard,error,fresh_scope_authenticated=True)
   row=dict(frame=job['frame'],arm=job['arm'],guard=guard,guard_artifact=artifact,work=work,metadata_accepted=False,observed_replay_accepted=None,completed_accepted=False)
   report['jobs'].append(row)
   report['helper_children_lower_bound']+=work['confirmed_helper_children_lower_bound']
   report['confirmed_shader_dispatches_lower_bound']+=work['confirmed_shader_dispatches_lower_bound']
   report['confirmed_fence_completions_lower_bound']+=work['confirmed_fence_completions_lower_bound']
   report['exact_helper_total']=sum(r['work']['exact_helper_child_total']for r in report['jobs'])if all(r['work']['exact_helper_child_total']is not None for r in report['jobs'])else None
   report['exact_shader_dispatch_total']=sum(r['work']['exact_shader_dispatch_total']for r in report['jobs'])if all(r['work']['exact_shader_dispatch_total']is not None for r in report['jobs'])else None
   save(target,report) # Actual physical work is preserved BEFORE every strict gate.
   if error:raise RuntimeError(error)
   if not work['metadata_accepted']:raise RuntimeError('Helper metadata/diagnostics gate failed; physical work retained')
   row['metadata_accepted']=True;report['metadata_accepted_jobs']+=1;save(target,report)
   # All three raw outputs retained; only consumed output-color RGB is finite/radiance checked.
   color=np.fromfile(job['outputs'][0]['path'],'<f2').reshape(80,128,4)
   row['consumed_color_RGB_finite']=bool(np.isfinite(color[...,:3]).all())
   row['consumed_color_RGB_valid_range']=bool(np.all((color[...,:3]>=0)&(color[...,:3]<=65504)))
   row['color_alpha_policy']='Actual shader bytes retained; no caller alpha repair or native-alpha preservation claim.'
   save(target,report)
   if not row['consumed_color_RGB_finite']:raise RuntimeError('Composed color RGB nonfinite; no fabricated replacement')
   row['completed_accepted']=True;report['completed_accepted_jobs']+=1;save(target,report)
  verify(frozen['owned']);verify(frozen['external_sources'])
  assert report['metadata_accepted_jobs']==report['completed_accepted_jobs']==report['exact_helper_total']==report['exact_shader_dispatch_total']==reg['planned_only_helper_jobs'] and report['observed_replay_accepted_frames']==0
  report['status']='completed_composition_only_awaiting_independent_review_not_quality_accepted';save(target,report)
 except BaseException as e:
  report.update(status='failed_preserved_composition_only_no_retry',error=type(e).__name__+': '+str(e));save(target,report);raise
if __name__=='__main__':main()
