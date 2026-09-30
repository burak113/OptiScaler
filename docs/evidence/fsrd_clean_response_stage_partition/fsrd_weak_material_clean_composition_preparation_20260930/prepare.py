"""CPU-only composition job preparation after independently reviewed actual clean native bytes."""
from pathlib import Path
import json,hashlib,shutil,ast,struct,shlex
from map_source import ROOT,TMP,HERE,OLD,E,W,CONV,NATIVE,GATE,TEST,PRE,IFMT,OFMT,BPP,identity,load,save,tokens
def clone(p,q):
 p=Path(p);q=Path(q);q.parent.mkdir(parents=True,exist_ok=True);assert not q.exists(),str(q)
 shutil.copyfile(p,q);assert p.read_bytes()==q.read_bytes();return identity(p)
def quoted(p):return '"'+Path(p).resolve().as_posix()+'"'
def verify(r):
 a=identity(r['path']);assert(a['bytes'],a['sha256'])==(r['bytes'],r['sha256']),r['path']
def main():
 assert not(HERE/'registration.json').exists(),'Preserve preparation'
 mapping=load(HERE/'source_mapping.json');assert mapping['status']=='PASSED_CPU_FROZEN_COMPOSITION_SOURCE_MAPPING'
 sources=load(HERE/'source_mapping_pins.json')['records']
 for r in sources:verify(r)
 for n in('FSRDOutputComp_Shader.cso','FSRDOutputComp.hlsl','FSRDPreprocessCommon.hlsli','FSRDFloorCommon.hlsli'):sources.append(clone(PRE/n,HERE/'frozen_shader'/n))
 sources.append(clone(E/'fsrd_gpu_runner.exe',HERE/'fsrd_gpu_runner.exe'))
 sources.append(clone(E/'fsrd_gpu_runner.build.cmd',HERE/'historical_gpu_runner.build.cmd'))
 sources.append(clone(CONV/'current_gpu_runner_source.cpp',HERE/'helper_source_reference.cpp'))
 sources.append(clone(CONV/'native_resource_guard.py',HERE/'native_resource_guard.py'))
 assert identity(HERE/'native_resource_guard.py')['sha256']=='b70e18d0f13963e0250c371171933429446cf304041c9a16d971e9898d211814'
 sources.append(clone(CONV/'conversion_work_accounting_v2.py',HERE/'helper_work_accounting.py'))
 v4path=CONV/'run_conversion_only_v4.py';v4=v4path.read_text();node=next(n for n in ast.parse(v4).body if isinstance(n,ast.FunctionDef)and n.name=='load_guard_best_effort')
 excerpt='from pathlib import Path\nimport json,hashlib\n'+ast.get_source_segment(v4,node)+'\n'
 (HERE/'helper_guard_evidence.py').write_text(excerpt,encoding='utf-8',newline='\n')
 save('mature_accounting_source_reuse.json',dict(parser_before=identity(CONV/'conversion_work_accounting_v2.py'),parser_owned=identity(HERE/'helper_work_accounting.py'),parser_byte_exact=True,guard_loader_before=identity(v4path),guard_loader_function='load_guard_best_effort',guard_loader_source_lines=[node.lineno,node.end_lineno],guard_loader_exact_AST_excerpt=True,old_V4_CPU_checks=identity(CONV/'accounting_v4_CPU_checks.json'),old_independent_ready=identity(TMP/'fsrd_weak_material_clean_converter_prelaunch_review_v4_20260930/completion_ready_manifest.json'),current_helper_source_reference=identity(HERE/'helper_source_reference.cpp'),historical_compiled_EXE=identity(HERE/'fsrd_gpu_runner.exe'),compilation_provenance_qualification='Exact historical EXE clone plus current pinned source read; no newly compiled linkage claim.',actual_GPU_native_build=0))
 sources.extend([identity(CONV/'accounting_v4_CPU_checks.json'),identity(TMP/'fsrd_weak_material_clean_converter_prelaunch_review_v4_20260930/completion_ready_manifest.json')])
 scorer_files=[TEST/'fsrd_alpha_common.py',TEST/'probe_fsrd_additive_split.py',TEST/'probe_fsrd_statistical_resolve.py',TMP/'factorized_pilot_feasibility_20260930/analyze.py',TMP/'phase_aligned_pilot_feasibility_20260930/analyze.py']
 phase_result=load(TMP/'phase_aligned_pilot_feasibility_20260930/results.json')
 assert identity(scorer_files[2])['sha256']==phase_result['metric_sha256']
 assert identity(scorer_files[3])['sha256']==phase_result['authenticated_helper_sha256']
 assert identity(scorer_files[4])['sha256']==phase_result['script_sha256']
 metric_records=[];extract=[]
 for p,name in zip(scorer_files,['LUMA','blur','score','moments','detail']):
  sources.append(clone(p,HERE/'frozen_metric_sources'/f'{name}_source.py'));target=HERE/'frozen_metric_sources'/f'{name}_source.py'
  metric_records.append(identity(target));extract.append(dict(source=str(target),name=name))
 sources.append(identity(TMP/'phase_aligned_pilot_feasibility_20260930/results.json'))
 save('analysis_plan.json',dict(fixed_windows=dict(full=list(range(64)),mature=list(range(48,64)),startup_first8=list(range(8)),activation8to16=list(range(8,16))),references=['raw_constructed_truth','quantized_raw_reference'],same_exact_frozen_detail_score_AST=True,metric_source_records=metric_records,metric_function_extraction=extract,descriptive_all_RGB_DC_beta=True,beta_atom=[64,-40],beta_ROI='5-pixel interior; centered real rank1 Nyquist atom, same frozen raw-quantization design',rank1_sign_phase_not_continuous_quadrature=True,oldB_four_windows_exact_required_before_new_metrics=True,comparators=['oldB','oldTP','old_observed','old_pilot','raw_constructed_truth','quantized_raw_reference'],output_RGBA_repeat_and_RGB_alpha_bits_retained=True,model_or_scorer_changed=False,quality_accepted=False,actual_GPU_native=0))
 native_reg=load(NATIVE/'registration.json');native_cases={x['tag']:x for x in native_reg['cases']}
 original_controls=(W/'observed/dispatch_controls.bin').read_bytes()
 for tag,c in native_cases.items():
  p=Path(c['job']).parent/'dispatch_controls.bin';assert p.read_bytes()==original_controls;sources.append(identity(p))
 jobs=[];template_checks=[];input_sources=[]
 for frame in range(64):
  original=E/'persisted_shader_jobs'/f'{768+frame}_FSRDOutputComp';template=HERE/'historical_templates'/f'{frame:02d}'
  for p in sorted(original.iterdir()):
   if p.is_file():sources.append(clone(p,template/p.name))
  clean_conv=CONV/'planned_jobs'/f'{frame:02d}'/'clean';clean=HERE/'frozen_clean_converter'/f'{frame:02d}'
  for output in(3,4,5,6,7):sources.append(clone(clean_conv/f'out{output}.bin',clean/f'out{output}.bin'))
  for arm in('observed_control','C0','C1'):
   folder=HERE/'planned_jobs'/f'{frame:02d}'/arm;folder.mkdir(parents=True,exist_ok=False)
   paths=[template/f'in{i}.bin'for i in range(11)]
   if arm!='observed_control':
    native_folder=Path(native_cases[arm]['job']).parent
    for slot,lobe in((0,'specular.bin'),(2,'diffuse.bin')):
     source=native_folder/lobe;data=source.read_bytes();stride=80*128*8;piece=data[frame*stride:(frame+1)*stride]
     assert len(data)==64*stride and len(piece)==stride
     p=folder/f'in{slot}.bin';p.write_bytes(piece);paths[slot]=p
     input_sources.append(dict(frame=frame,arm=arm,slot=slot,source=identity(source),offset=frame*stride,bytes=stride,payload=identity(p),operation='Exact actual native fullRGBA byte slice; no encoding/remodulation/alpha repair.'))
    for slot,out in{1:4,3:5,4:6,5:3,6:7}.items():paths[slot]=clean/f'out{out}.bin'
   for i,fmt in enumerate(IFMT):assert paths[i].stat().st_size==128*80*BPP[fmt]
   outputs=[dict(slot=i,path=str((folder/f'out{i}.bin').resolve()),bytes=128*80*BPP[fmt],format=fmt)for i,fmt in enumerate(OFMT)]
   if arm=='observed_control':
    for out in outputs:out['historical_expected']=identity(template/f"out{out['slot']}.bin")
   text=[f'{quoted(HERE/"frozen_shader/FSRDOutputComp_Shader.cso")} {quoted(template/"cb.bin")} 128 80 11 3 1']
   text += [f'{quoted(p)} 128 80 {fmt}'for p,fmt in zip(paths,IFMT)]
   text += [f'{quoted(o["path"])} 128 80 {o["format"]}'for o in outputs]
   (folder/'job.txt').write_text('\n'.join(text)+'\n',encoding='utf-8',newline='\n')
   assert not any(Path(o['path']).exists()for o in outputs)
   parsed=tokens(folder/'job.txt');assert len(parsed)==15 and parsed[0][2:]==['128','80','11','3','1']
   expected=[template/f'in{i}.bin'for i in range(11)]
   if arm=='observed_control':assert all(Path(row[0]).read_bytes()==expected[i].read_bytes()for i,row in enumerate(parsed[1:12]))
   jobs.append(dict(frame=frame,arm=arm,job=str((folder/'job.txt').resolve()),command=[str((HERE/'fsrd_gpu_runner.exe').resolve()),str((folder/'job.txt').resolve())],inputs=[dict(slot=i,format=fmt,**identity(p))for i,(p,fmt)in enumerate(zip(paths,IFMT))],CB=identity(template/'cb.bin'),outputs=outputs,repetitions=1,explicit_shader_Dispatches_planned_only=1))
  template_checks.append(dict(frame=frame,exact_original_CB=True,exact_observed11_inputs=True,observed3_replay_required=True,clean_native_lobe_slices_full_RGBA=True,clean_converter_guides_actual_bytes=True,other_depth_motion_history_metadata_immutable=True))
 save('actual_clean_native_lobe_slice_provenance.json',dict(records=input_sources,controls184_exact_to_observed=True,actual_GPU_native=0))
 sources=list({r['path'].lower():r for r in sources}.values())
 limits=['Genuine composition is only produced by future helper dispatch through the pinned original CSO; no CPU remodulation or oldB+oldP-oldTP construction substitutes for Tclean.','Fresh helper/device perjob differs from original reusable server-worker cadence. Every observed all3-output replay must pass bit-exact before clean arms of that frame; mismatch stops immediately without threshold or retry.','Clean constructed radiance and its FP16 quantized raw encoding are distinct scoring references. Clean SDK response is not physical ground truth or a quality acceptance oracle.','Tclean vs oldB/oldTP also differs in source noise/distribution and opaque context history. Two clean repeats do not establish game behavior, statistical independence/confidence, or a SDK/private storage mechanism.','Native and composition alpha bytes are retained descriptively; no claim that SDK output alpha preserves its inputs. Composition history remains disabled exactly as in original templates.','Nyquist beta/DC is a frozen signed rank1 descriptive decomposition; sign phase is not a continuous off-grid quadrature estimate. Frozen full64/mature16/startup/activation scorer and thresholds are unchanged.']
 reg=dict(schema='weak-material-genuine-clean-composition192-CPU-preparation-v1',status='PREPARED_CPU_ONLY_NO_COMPOSITION_GPU_AUTHORIZATION',post_native_gate=mapping['post_native_gate'],post_native_final_seal=mapping['post_native_final_seal'],source_mapping=identity(HERE/'source_mapping.json'),jobs=jobs,template_checks=template_checks,planned_only_helper_jobs=192,planned_only_explicit_helper_shader_Dispatches=192,planned_only_observed_replay_frames=64,planned_only_UAV_output_files=576,actual_helper_jobs=0,actual_shader_Dispatches=0,actual_native_contexts=0,actual_native_API=0,actual_builds=0,mode_order='frame0..63 observed_control,C0,C1',guard=dict(timeout_seconds=240,maximum_working_set_bytes=2147483648,minimum_available_memory_bytes=1073741824,sample_interval_seconds=.2,only_sequential_owned_children=True,no_other_process_kills=True),frozen_helper=identity(HERE/'fsrd_gpu_runner.exe'),frozen_guard=identity(HERE/'native_resource_guard.py'),frozen_CSO=identity(HERE/'frozen_shader/FSRDOutputComp_Shader.cso'),metric_source_records=metric_records,metric_function_extraction=extract,source_sequences=identity(W/'sequences.npz'),quantized_raw_reference=identity(TMP/'fsrd_weak_material_clean_response_design_20260930/quantized_clean_raw_RGBA16_FLOAT.bin'),original_report=identity(E/'results.json'),root_authorization_required_after_independent_prelaunch_review=True,quality_accepted=False,game_run=False,limitations=limits)
 save('registration.json',reg)
 save('external_source_pins.json',dict(records=sources,actual_GPU_native=0))
 print(json.dumps(dict(status=reg['status'],jobs=len(jobs),outputs=576,external_source_records=len(sources),actual_GPU_native_build=0)))
if __name__=='__main__':main()
