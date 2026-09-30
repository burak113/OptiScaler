"""Immutable compact archive; every actual payload stays retained and SHA pinned."""
from pathlib import Path
import hashlib,json,shutil,time
ROOT=Path(__file__).resolve().parents[1]
DEST=ROOT/'docs/evidence/fsrd_continuous_harmonic_followup'
PACKAGES=['harmonic_assumptions_independent_audit','source_continuous_harmonic_design',
 'source_continuous_harmonic_feasibility','continuous_harmonic_root_math_review',
 'native_continuous_harmonic_initial','native_continuous_harmonic_fresh_retry',
 'native_continuous_harmonic_remaining','native_continuous_harmonic_independent_audit',
 'harmonic_native_variance_attribution','native_guide_alpha_ablation',
 'native_guide_alpha_wave_continuation','native_guide_alpha_wave_identical_repeat']
EXTRA=['prepare_guide_alpha_wave_continuation_20260930.py','prepare_guide_alpha_wave_identical_repeat_20260930.py',
 'guide_alpha_wave_cross_comparison_20260930.py','collect_fsrd_continuous_harmonic_followup_20260930.py']
def sha(p):
 h=hashlib.sha256()
 with p.open('rb')as f:
  for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
 return h.hexdigest()
if DEST.exists():raise ValueError('Preserve archive; no overwrite')
DEST.mkdir(parents=True)
copied=[];external=[];summaries=[]
def collect(p,rel):
 item={'source':str(p),'bytes':p.stat().st_size,'sha256':sha(p)}
 is_payload=(p.suffix.lower()in('.npz','.npy','.exe','.dll') or
   (p.suffix.lower()=='.bin' and p.name not in('cb.bin','dispatch_controls.bin')))
 if is_payload:
  item['retained_external_payload']=True;external.append(item)
 else:
  target=DEST/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,target)
  assert sha(target)==item['sha256'];item['archive']=rel.as_posix();copied.append(item)
for name in PACKAGES:
 folder=ROOT/'tools_tmp'/(name+'_20260930');assert folder.is_dir()
 files=sorted(p for p in folder.rglob('*')if p.is_file()and'__pycache__'not in p.parts)
 before=(len(copied),len(external))
 for p in files:collect(p,Path(name)/p.relative_to(folder))
 summaries.append({'name':name,'files':len(files),'bytes':sum(p.stat().st_size for p in files),
  'copied_files':len(copied)-before[0],'external_payloads':len(external)-before[1]})
 print(name,summaries[-1]['files'],'files',flush=True)
for name in EXTRA:collect(ROOT/'tools_tmp'/name,Path('collector_sources')/name)
erratum={'schema':'root-guide-alpha-preparation-errors-v1','producer_or_threshold_changed':False,
 'wave_dedup':'First guide-alpha driver incorrectly required64uploads. Material4contexts completed and saved; wave uploadcount1 assertion failed before native launch. Wave-only continuation preserves original uploadcount and sourceA constant check.',
 'cross_comparison_import':'First supplemental import failed ModuleNotFoundError native_resource_guard before any comparison was saved; added local package sys.path. No native output or input changed.',
 'metadata_scope':'Old all_nonradiance_counterfactual_inputs_exact Boolean covers guides RGB, motion, normals and signal rayA. Specular-albedo diagnostic A differed; no fullRGBA byte equality claim.'}
(DEST/'execution_errata.json').write_text(json.dumps(erratum,indent=2)+'\n')
manifest={'schema':'fsrd-continuous-harmonic-followup-evidence-v1',
 'branch':'ffxD-experimental-alpha','base_commit':'e2c767a0f587ee4a1fd0a3383350475c0f118bf5',
 'quality_accepted':False,'runtime_implemented':False,'game_run':False,
 'new_native_contexts':29,'new_native_RR_calls':1856,
 'harmonic_native_contexts':18,'harmonic_native_RR_calls':1152,
 'guide_alpha_and_identical_repeat_contexts':11,'guide_alpha_and_identical_repeat_RR_calls':704,
 'initial_low_memory_attempt_contexts':0,'initial_low_memory_attempt_RR_calls':0,
 'completed_total_contexts':370,'completed_total_RR_calls':19312,
 'completed_actual_conversion_jobs':768,'completed_actual_composition_jobs':1152,
 'initial_conversion_only_jobs':128,'all_actual_GPU_jobs_retained':2048,
 'copied_file_count':len(copied),'copied_files':copied,'external_payload_count':len(external),
 'external_payloads':external,'package_inventory':summaries,
 'archive_scope':'Compact scripts, reports, actual CB/control/job/log bytes. Full actual GPU/native textures and sequence arrays remain immutable at recorded F paths, every file SHA and size pinned.',
 'limitations':['Synthetic diagnostic quality remains rejected; no currentalpha game capture',
 'Guidealpha empirical material result does not imply universal ignored-alpha contract',
 'Wave identical-input native scatter prevents guidealpha causal attribution',
 'Earlier completion counted64RR whose Python metadata step failed remains in cumulative totals']}
(DEST/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
(DEST/'.gitattributes').write_text('* -text\n')
print(json.dumps({'archive':str(DEST),'copied_files':len(copied),'external_payloads':len(external),
 'archive_bytes':sum(p.stat().st_size for p in DEST.rglob('*')if p.is_file()),
 'external_bytes':sum(x['bytes']for x in external),'manifest_sha256':sha(DEST/'manifest.json')},indent=2),flush=True)
