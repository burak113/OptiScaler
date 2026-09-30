"""Fresh guarded native response to a frozen harmonic pilot, all jobs retained."""
from pathlib import Path
import hashlib, importlib.util, json, shutil, sys
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent;DEST=HERE/'evidence'
TESTS=ROOT/'OptiScaler/shaders/shader_tools/tests';sys.path.insert(0,str(TESTS))
OLD=ROOT/'tools_tmp/native_significant_phase_initial_20260930';sys.path.append(str(OLD))
from fsrd_alpha_common import convert,compose,rgba,shader_identity,save_json
from probe_fsrd_additive_split import DLL
from native_helper import run_amd
from capturing_worker import CapturingGPUWorker
from harmonic_pilot import make_continuous_harmonic_pilot
import run_fsrd_gpu_tests as gpu_tests

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod
old=load('frozen_significant_native_fixture',OLD/'probe_significant_phase.py')
cpu=load('frozen_harmonic_CPU_metrics',ROOT/'tools_tmp/source_continuous_harmonic_feasibility_20260930/analyze.py')
EXE=Path('C:/Users/burak/.codex/visualizations/2026/09/29/01a0eeeb-48a8-7733-add1-58a3bd1f37ce/response_soft_temporal_long_alpha_fresh/fsrd_rr_runner.exe')
SCENES=('material','wave','moving_light','weak_material','lighting_step','reset')

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def controls_contract(folder,expected):
    raw=(folder/'dispatch_controls.bin').read_bytes()
    n=len(expected);assert len(raw)==n*184
    records=np.frombuffer(raw,dtype=np.dtype([('header','<u4',(4,)),('values','<f4',(42,))]))
    np.testing.assert_array_equal(records['header'][:,0],np.arange(n))
    np.testing.assert_array_equal(records['header'][:,1],2+expected[:,0].astype('u4'))
    np.testing.assert_array_equal(records['header'][:,2],128);np.testing.assert_array_equal(records['header'][:,3],80)
    np.testing.assert_array_equal(records['values'][:,6:8],expected[:,1:])
    return sha(folder/'dispatch_controls.bin')

def main():
    if DEST.exists():raise ValueError('Preserve previous evidence')
    freeze=json.loads((HERE/'pre_native_freeze.json').read_text())
    assert all(sha(Path(p))==digest for p,digest in freeze['sources'].items())
    assert sha(DLL)=='48f1e5888ba6a0a3d59a98b9751e37c392b0f7b8c223d0082d5c1f40642879d3'
    assert sha(EXE)=='3427689a4764380f885545c353250277e4d71944d3310c8a17b3cbba0f3c21d2'
    assert sha(HERE/'harmonic_pilot.py')=='be66624153a286c6b3299735fc2a1bbf5162ffe24a52d7f9421d1c4b90a52173'
    source_report=json.loads((ROOT/'tools_tmp/source_continuous_harmonic_feasibility_20260930/results.json').read_text())
    assert source_report['status']=='completed_CPU_source_feasibility_not_solution'
    DEST.mkdir();snap=DEST/'source_snapshot';snap.mkdir()
    for path in HERE.iterdir():
        if path.is_file():shutil.copyfile(path,snap/path.name)
    identity=shader_identity(gpu_tests.PRE)
    report={'schema':'continuous-harmonic-fresh-native-response-v1','status':'running',
        'quality_accepted':False,'game_run':False,'runtime_implemented':False,
        'provider_sha256':sha(DLL),'runner_sha256':sha(EXE),'pre_native_freeze':freeze,
        'source_CPU_report_sha256':sha(ROOT/'tools_tmp/source_continuous_harmonic_feasibility_20260930/results.json'),
        'prototype_sha256':sha(HERE/'harmonic_pilot.py'),'production_shaders':identity,
        'fresh_baseline_null_pilot':True,'all_GPU_job_bytes_persisted':True,
        'selected_candidate_before_native':'harmonic_dc_current_safe','completed_native_contexts':0,
        'frames':64,'size':[128,80],'seed':950301,'sigma':.012,'split_strength':1,'rows':[]}
    def save():save_json(DEST/'results.json',report)
    save()
    try:
      with CapturingGPUWorker(DEST):
       for scene in SCENES:
        folder=DEST/scene;folder.mkdir()
        data=old.research_fixture(scene,128,80,64,950301)
        observed=(data['truth']+np.random.default_rng(956432).normal(0,.012,data['truth'].shape)).astype('f2').astype('f4')
        assert np.isfinite(observed).all() and observed.min()>=0
        controls=data['controls'];pilot,active,diag=make_continuous_harmonic_pilot(observed,controls)
        pilot=pilot.astype('f2').astype('f4')
        assert np.isfinite(pilot).all() and pilot.min()>=0
        def pack(color):
            return [convert(rgba(color[i]),data['diff'][i],data['spec'][i],1,
                depth=data['depth'],normals=data['normals'],roughness=data['roughness'],
                motion=data.get('motion',[None]*64)[i],overrides=data.get('overrides'),resources=data.get('resources')) for i in range(64)]
        source_inputs=pack(observed);pilot_inputs=pack(pilot)
        old.assert_counterfactual_contract(source_inputs,pilot_inputs)
        def execute(inputs,name):
            d,s,_=run_amd(folder/name,EXE,inputs,data['depth'],camera=data.get('camera'),frame_controls=controls)
            controls_hash=controls_contract(folder/name,controls)
            composed=np.stack([compose(value,s[i],d[i],depth=data['depth'],detail=0)[...,:3] for i,value in enumerate(inputs)])
            report['completed_native_contexts']+=1;save()
            return composed,controls_hash
        baseline,bc=execute(source_inputs,'observed');repeat,nc=execute(source_inputs,'null_repeat');response,pc=execute(pilot_inputs,'harmonic_pilot')
        assert bc==nc==pc
        identities={name:json.loads((folder/name/'amd_context_identity.json').read_text()) for name in ('observed','null_repeat','harmonic_pilot')}
        assert identities['observed']['inputs']==identities['null_repeat']['inputs']
        blind=baseline+active[:,None,None,None]*(pilot-response)
        epochs=[r['epoch_start'] for r in diag['frames']]
        variants={'harmonic':blind,'harmonic_dc':old.dc_conservation(blind,observed,active,controls,64,epochs),
                  'harmonic_dc_current':old.dc_conservation(blind,observed,active,controls,1)}
        fractions={}
        for name,value in list(variants.items()):
            value,fraction=old.radiance_fallback(value,baseline);variants[name+'_safe']=value;fractions[name+'_safe']=fraction
        null_rms=float(np.sqrt(np.mean((baseline-repeat)**2)))
        scores={}
        base_metrics={}
        for window,sl in [('full',slice(None)),('mature',slice(-16,None)),('startup_first8',slice(0,8)),('activation8to16',slice(8,16))]:
            base_metrics[window]=cpu.first.detail(baseline[sl],data['truth'][sl])
        for name,value in variants.items():
            windows={}
            for window,sl in [('full',slice(None)),('mature',slice(-16,None)),('startup_first8',slice(0,8)),('activation8to16',slice(8,16))]:
                metrics=cpu.first.detail(value[sl],data['truth'][sl]);activity=float(np.mean(abs(value[sl]-baseline[sl])>1e-5))
                metrics['relative_gate']=old.acceptance(metrics['score'],base_metrics[window]['score'],activity,null_rms,scene)
                base_std=base_metrics[window]['score']['residual_temporal_std']
                metrics['actual_STD_ratio_to_native_baseline']=metrics['score']['residual_temporal_std']/base_std if base_std else None
                windows[window]=metrics
            scores[name]={'metrics':windows,'fallback_pixel_fraction':fractions.get(name,0),
                'invalid_pixel_fraction':float(np.mean(~np.all(np.isfinite(value)&(value>=0)&(value<=65504),axis=-1)))}
        np.savez_compressed(folder/'sequences.npz',observed=observed,pilot=pilot,active=active,
            baseline=baseline,null_repeat=repeat,pilot_response=response,clean_reference=data['truth'],**variants)
        report['rows'].append({'scene':scene,'baseline_metrics':base_metrics,'null_rms':null_rms,'variants':scores,
            'pilot_diagnostics':diag,'matched_applied_controls_sha256':bc,'all_nonradiance_counterfactual_inputs_exact':True,
            'observed_null_all7_inputs_exact':True,'sequences_sha256':sha(folder/'sequences.npz'),
            'context_identity_sha256':{name:sha(folder/name/'amd_context_identity.json') for name in identities}})
        assert shader_identity(gpu_tests.PRE)==identity
        save();chosen=scores['harmonic_dc_current_safe']['metrics']
        print(scene,{'mature_STD_ratio':chosen['mature']['actual_STD_ratio_to_native_baseline'],
            'full_absolute_detail':chosen['full']['absolute_detail_pass'],
            'mature_absolute_detail':chosen['mature']['absolute_detail_pass'],
            'full_relative_failures':chosen['full']['relative_gate']['failures']},flush=True)
      assert report['completed_native_contexts']==18 and len(report['rows'])==6
      assert all(sha(Path(p))==digest for p,digest in freeze['sources'].items())
      report.update(status='completed_native_diagnostic_not_solution',native_RR_calls=1152,
          actual_conversion_jobs=768,actual_composition_jobs=1152)
      save()
    except Exception as exc:
      report.update(status='failed_preserved',error=str(exc));save();raise

if __name__=='__main__':main()
