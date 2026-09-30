"""CPU-only authentication of the actual frozen composition graph; no helper launch."""
from pathlib import Path
import json,hashlib,shlex,struct
import numpy as np
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1];TMP=ROOT/'tools_tmp'
OLD=TMP/'native_continuous_harmonic_remaining_20260930';E=OLD/'evidence';W=E/'weak_material'
CONV=TMP/'fsrd_weak_material_clean_converter_preparation_20260930'
NATIVE=TMP/'fsrd_weak_material_clean_native_preparation_20260930'
GATE=TMP/'fsrd_weak_material_clean_native_postrun_review_20260930'
TEST=ROOT/'OptiScaler/shaders/shader_tools/tests';PRE=ROOT/'OptiScaler/shaders/fsrd_preprocess/precompile'
IFMT=[10,28,10,28,10,24,10,41,10,10,3];OFMT=[10,10,3];BPP={10:8,28:4,24:4,41:4,3:16}
def identity(p):
 p=Path(p).resolve();h=hashlib.sha256()
 with p.open('rb')as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return dict(path=str(p),bytes=p.stat().st_size,sha256=h.hexdigest())
def load(p):return json.loads(Path(p).read_text())
def save(n,o):
 with(HERE/n).open('x',encoding='utf-8',newline='\n')as f:json.dump(o,f,indent=2,allow_nan=False);f.write('\n')
def tokens(p):return[shlex.split(line)for line in Path(p).read_text().splitlines()]
def run_mapping():
 assert not(HERE/'source_mapping.json').exists(),'Preserve earlier mapping attempt'
 assert identity(GATE/'review.json')['sha256']=='0d7dcda2d476ce0223cf16d3d24214c5f0a6c9d903fb9e992402e4da115eef07'
 assert identity(GATE/'completion_manifest_final.json')['sha256']=='9d231d55386869cdcd72d6e1095bf7548f42bbc3d4d990922fabb971f3cb18c1'
 gate=load(GATE/'review.json');assert gate['status']=='PASSED_CLEAN_NATIVE_RAW_EVIDENCE_REVIEW'and gate['blocking_findings']==[]
 assert identity(NATIVE/'execution_results.json')['sha256']=='0b7f697b7b628a1fec0029c671432aefa94b150221b6cae52482a416383643f7'
 assert identity(NATIVE/'raw_comparisons.json')['sha256']=='ccd4c695431010cc9d884ab9b12b4df48907ae09f65776729e43f56e57f58395'
 manifests=load(E/'persisted_shader_jobs/manifest.json');entry={x['job_name']:x for x in manifests['jobs']}
 oldreport=load(E/'results.json');shaderpins=oldreport['production_shaders']
 assert identity(PRE/'FSRDOutputComp_Shader.cso')['sha256']==shaderpins['FSRDOutputComp_Shader.cso']
 for n in('FSRDOutputComp.hlsl','FSRDPreprocessCommon.hlsli','FSRDFloorCommon.hlsli'):assert identity(PRE/n)['sha256']==shaderpins[n]
 with np.load(W/'sequences.npz')as z:baseline=z['baseline'].copy()
 native_reg=load(NATIVE/'registration.json');native_case={x['tag']:x for x in native_reg['cases']}
 obs={n:(W/'observed'/n).read_bytes()for n in('diffuse.bin','specular.bin')}
 sources=[identity(p)for p in(E/'results.json',E/'persisted_shader_jobs/manifest.json',OLD/'pre_native_freeze.json',OLD/'analyze.py',OLD/'evidence/source_snapshot/analyze.py',TEST/'fsrd_alpha_common.py',TEST/'run_fsrd_gpu_tests.py',TEST/'fsrd_gpu_runner.cpp',E/'fsrd_gpu_runner.exe',E/'fsrd_gpu_runner.build.cmd',W/'sequences.npz',GATE/'review.json',GATE/'completion_manifest_final.json',NATIVE/'execution_results.json',NATIVE/'raw_comparisons.json',NATIVE/'registration.json',CONV/'execution_results_v4.json',CONV/'pre_execution_freeze.json',CONV/'run_conversion_only_v4.py',CONV/'conversion_work_accounting_v2.py',CONV/'native_resource_guard.py')]
 freeze=load(OLD/'pre_native_freeze.json')['sources']
 for p in(OLD/'analyze.py',TEST/'fsrd_alpha_common.py',TEST/'run_fsrd_gpu_tests.py'):
  assert identity(p)['sha256']==next(h for path,h in freeze.items()if Path(path)==p)
 assert(OLD/'analyze.py').read_bytes()==(OLD/'evidence/source_snapshot/analyze.py').read_bytes()
 for n in('FSRDOutputComp_Shader.cso','FSRDOutputComp.hlsl','FSRDPreprocessCommon.hlsli','FSRDFloorCommon.hlsli'):sources.append(identity(PRE/n))
 cb_expect=bytearray(96)
 struct.pack_into('<4f',cb_expect,0,128,80,1/128,1/80)
 for i,v in[(4,8),(6,1)]:struct.pack_into('<I',cb_expect,i*4,v)
 for i,v in[(7,4),(12,1),(17,1),(18,1),(20,1),(21,1)]:struct.pack_into('<f',cb_expect,i*4,v)
 frames=[]
 for frame in range(64):
  name=f'{768+frame}_FSRDOutputComp';orig=E/'persisted_shader_jobs'/name;r=entry[name]
  for x in r['files']:
   p=orig/x['name'];a=identity(p);assert a['bytes']==x['size']and a['sha256']==x['sha256'];sources.append(a)
  assert identity(orig/'runner.log')['sha256']==r['runner_log_sha256'];sources.append(identity(orig/'runner.log'))
  job=tokens(orig/'job.txt');assert job[0][2:]==['128','80','11','3','1']and Path(job[0][0]).name=='FSRDOutputComp_Shader.cso'
  assert len(job)==15 and all(list(map(int,row[1:]))==[128,80,fmt]for row,fmt in zip(job[1:12],IFMT))and all(list(map(int,row[1:]))==[128,80,fmt]for row,fmt in zip(job[12:],OFMT))
  assert(orig/'cb.bin').read_bytes()==bytes(cb_expect)
  stride=128*80*8
  assert(orig/'in0.bin').read_bytes()==obs['specular.bin'][frame*stride:(frame+1)*stride]
  assert(orig/'in2.bin').read_bytes()==obs['diffuse.bin'][frame*stride:(frame+1)*stride]
  observed_conv=E/'persisted_shader_jobs'/f'{640+frame}_FSRDInputConvAdditive'
  clean_conv=CONV/'planned_jobs'/f'{frame:02d}'/'clean'
  map_packed={1:4,3:5,4:6,5:3,6:7}
  for srv,uav in map_packed.items():
   assert(orig/f'in{srv}.bin').read_bytes()==(observed_conv/f'out{uav}.bin').read_bytes(),(frame,srv,uav)
   sources.append(identity(clean_conv/f'out{uav}.bin'))
   assert(clean_conv/f'out{uav}.bin').stat().st_size==128*80*BPP[IFMT[srv]]
  depth=(NATIVE/'inputs/input0.bin').read_bytes();assert(orig/'in7.bin').read_bytes()==depth
  assert np.array_equal(np.fromfile(orig/'in8.bin','<u2'),np.zeros(80*128*4,dtype='<u2'))
  assert np.array_equal(np.fromfile(orig/'in9.bin','<f2'),np.full(80*128*4,-1,dtype='<f2'))
  assert np.array_equal(np.fromfile(orig/'in10.bin','<u4'),np.zeros(80*128*4,dtype='<u4'))
  actual=np.fromfile(orig/'out0.bin','<f2').reshape(80,128,4)
  assert np.array_equal(actual[...,:3].astype('<f4'),baseline[frame]),frame
  for tag in('C0','C1'):
   d=Path(native_case[tag]['job']).parent
   for n in('diffuse.bin','specular.bin'):
    p=d/n;assert p.stat().st_size==64*stride;sources.append(identity(p))
  frames.append(dict(frame=frame,template_name=name,CB_exact_fixed96=True,all11_formats_exact=True,all3_UAV_formats_exact=True,observed_native_lobes_full_RGBA_exact=True,observed_converter_mapping_full_bytes_exact=True,observed_output0_RGB_exact_old_baseline=True,clean_converter_output_paths={str(s):str(clean_conv/f'out{u}.bin')for s,u in map_packed.items()},immutable_depth_motion_history_metadata_exact=True))
 sources=list({r['path'].lower():r for r in sources}.values())
 slots=[dict(slot=0,role='InIndirectSpecular',format=10,observed='old observed native specular frame bytes',clean='C0 or C1 actual native specular frame bytes, full RGBA retained'),dict(slot=1,role='InSpecularAlbedo',format=28,observed='observed converter out4',clean='actual clean converter out4 inclA'),dict(slot=2,role='InDirectDiffuse',format=10,observed='old observed native diffuse frame bytes',clean='C0 or C1 actual native diffuse frame bytes, full RGBA retained'),dict(slot=3,role='InDiffuseAlbedo',format=28,observed='observed converter out5',clean='actual clean converter out5 inclA'),dict(slot=4,role='InSkipSignal',format=10,observed='observed converter out6',clean='actual clean converter out6 fullRGBA'),dict(slot=5,role='InNormals',format=24,observed='observed converter out3',clean='actual clean converter out3 all packed normal/alpha bits'),dict(slot=6,role='InDetailReference',format=10,observed='observed converter out7',clean='actual clean converter out7 fullRGBA; not CPU reference remodulation'),dict(slot=7,role='InLinearDepth',format=41,observed='original compose template in7',clean='same original in7; exact to actual clean native input0'),dict(slot=8,role='InMotion',format=10,observed='original zero motion RGBA16F',clean='same immutable original template bytes'),dict(slot=9,role='InDecisionHistory',format=10,observed='original allminus1 RGBA16F sentinel',clean='same immutable original template bytes; HistoryValid0/WriteHistory0'),dict(slot=10,role='InHistoryMetadata',format=3,observed='original allzero RGBA32_UINT',clean='same immutable original template bytes')]
 report=dict(status='PASSED_CPU_FROZEN_COMPOSITION_SOURCE_MAPPING',post_native_gate=identity(GATE/'review.json'),post_native_final_seal=identity(GATE/'completion_manifest_final.json'),frames=frames,SRV_mapping=slots,CB=dict(bytes=96,DstTexSize=[128,80,1/128,1/80],Flags=8,DetailPreservation=0,RecoveryMask=1,FloorHandoverAnchorClamp=4,SourceUvScale=[0,0],SourceUvOffset=[0,0],FloorHandoverCorrelationMix=1,HistoryValid=0,HistoryJitterDelta=[0,0],WriteHistory=0,SpecularAlbedoDemodulation=1,DiffuseAlbedoModulation=1,SpatialTemporalMask=0,LumaRecovery=1,ChromaRecovery=1,padding=[0,0]),UAVs=[dict(slot=i,format=f,role=n)for i,(f,n)in enumerate(zip(OFMT,['OutColor','OutDecisionHistory','OutHistoryMetadata']))],planned_order='frame0..63: observed_control,C0,C1;192 fresh repetition1 helper jobs, all3 outputs retained',helper_cadence_qualification='Historical templates ran through reusable server worker. New helper freshprocess/device perjob cadence is allowed only if each observed all3 outputs bitreplays original before either clean arm. Any mismatch stops without retry or threshold.',native_API_new=0,composition_GPU_actual=0,no_CPU_composition=True,quality_accepted=False)
 save('source_mapping.json',report);save('source_mapping_pins.json',dict(records=sources,self_entry_excluded=True,actual_GPU_native_build=0))
 print(json.dumps(dict(status=report['status'],frames=64,SRVs=11,UAVs=3,CB_bytes=96,source_pins=len(sources),new_GPU_native=0)))
if __name__=='__main__':run_mapping()
