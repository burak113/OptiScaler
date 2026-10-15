"""Validate, replay and score NEW corrected V7 / colored physical V8 pairs.

Default is CPU validation. --run requires a parent-granted shared GPU slot via
lead_ops/run_task_test.py and an explicitly hashed prebuilt real RRWrapper EXE.
No compiler, production mutation, albedo/noisy bypass or recovery is used.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import struct
import sys

# Standalone lead_ops invocation does not inherit a caller's shader_tools path.
# The reused real-wrapper limiter imports fsrd_toolchain from this parent.
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))

import numpy as np

import fsrd_nrd_rr_colored_ggx_oracle as colored
import fsrd_nrd_rr_corrected_qs_views as corrected
import fsrd_nrd_rr_ggx_audit_compare as detail
import fsrd_nrd_rr_ggx_oracle as transport
import fsrd_nrd_rr_ggx_uncertainty as uncertainty
import fsrd_nrd_rr_ggx_views as frozen
import fsrd_nrd_rr_material_compare as signed
import fsrd_nrd_rr_material_quality as files
import fsrd_nrd_rr_mirror_oracle as scene


CHECKS=0


def need(condition,message):
    global CHECKS
    CHECKS+=1
    if not bool(condition):
        raise AssertionError(message)


def read_manifest(case):
    name='colored-ggx-sequence.json' if (case/'colored-ggx-sequence.json').exists() else 'ggx-sequence.json'
    manifest=json.loads((case/name).read_bytes())
    need(manifest['schema'] in (colored.SCHEMA,corrected.SCHEMA),'explicit corrected oracle lineage; never relabel frozen wrong-guide inputs')
    return name,manifest


def identity(manifest):
    return 'colored-v8-g31-b124' if manifest['schema']==colored.SCHEMA else 'corrected-v7-r'+str(manifest['code'])


def load(case,manifest,frame,names=None):
    if manifest['schema']==corrected.SCHEMA:
        return corrected.load_frame(case,manifest,frame,names)
    names=frame['payloads'] if names is None else names
    payload_case=Path(manifest.get('payload_case',case))
    return {n:files.load(payload_case/'dataset'/frame['directory'],frame['payloads'][n]) for n in names}


def native_field(manifest,candidate,signal):
    if not signal.endswith('_albedo'):
        return signal
    if manifest['schema']==corrected.SCHEMA:
        return 'white_spec_albedo' if candidate=='white' and signal=='spec_albedo' else signal
    enabled=candidate in ('both','actual',('specular-only' if signal=='spec_albedo' else 'diffuse-only'))
    return signal if enabled else 'white_albedo'


def four_way(source,destination):
    """New view-only sealed manifest; preserve original two-view V8 evidence."""
    source,destination=Path(source),Path(destination)
    name,manifest=validate(source)
    need(manifest['schema']==colored.SCHEMA,'four-way extension only from complete physical colored V8')
    need(not destination.exists() and destination.resolve().is_relative_to(scene.BASE.resolve()),'fresh task-local view manifest, never overwrite source evidence')
    views={'white':manifest['views']['white'],'diffuse-only':str(destination/'views/diffuse-only'),
        'specular-only':str(destination/'views/specular-only'),'both':manifest['views']['actual']}
    for candidate in ('diffuse-only','specular-only'):
        view=Path(views[candidate])
        files.immutable(view/'native-replay.txt',(source/'native-replay.txt').read_bytes())
        for frame in manifest['frames']:
            for signal in corrected.NATIVE:
                field=native_field(manifest,candidate,signal)
                origin=source/'dataset'/frame['directory']/frame['payloads'][field]['file']
                corrected.link_immutable(view/frame['directory']/(signal+'.bin'),origin)
    result=dict(manifest,views=views,candidates=list(views),payload_case=str(source),
        parent_manifest_sha256=files.file_sha(source/name),parent_manifest=str(source/name),
        view_extension_source_sha256=files.file_sha(Path(__file__)),
        source_files={**manifest['source_files'],str(Path(__file__)):files.file_sha(Path(__file__))},
        candidate_axis='four fresh histories: white, diffuse-only, specular-only, both; ONLY declared albedo RGB changes',
        view_extension='hardlinks/canonical views only, no physical re-integration or source signal transformation')
    files.immutable(destination/'colored-ggx-sequence.json',(json.dumps(result,indent=2,allow_nan=False)+'\n').encode())
    print(json.dumps(dict(manifest=str(destination/'colored-ggx-sequence.json'),sha256=files.file_sha(destination/'colored-ggx-sequence.json'),
        checks=CHECKS,sealed_payload_checks=files.CHECKS,physical_integration_repeated=False,gpu_executed=False,compiler_executed=False),indent=2))
    return result


def validate(case):
    name,manifest=read_manifest(case)
    need(len(manifest['frames'])==manifest['submitted_frames']==64,'complete fixed64-frame temporal history')
    expected=tuple(manifest.get('candidates',('white','actual'))) if manifest['schema']==colored.SCHEMA else ('white','correct')
    need(expected in (('white','actual'),('white','correct'),('white','diffuse-only','specular-only','both')),'predeclared supported guide axes')
    need(tuple(manifest['views'])==expected,'both prescribed candidates, including all negative/identity controls')
    for path,digest in manifest['source_files'].items():
        need(files.file_sha(path)==digest,'all exact frozen transport/material source bytes')
    if manifest['schema']==corrected.SCHEMA:
        need(files.file_sha(Path(manifest['physical_case'])/'ggx-sequence.json')==manifest['physical_manifest_sha256'],'unchanged original physical F1 reference lineage')
    else:
        need(manifest['guide_native_g8']==31 and manifest['rr_normal_r10_code']==124 and not manifest['zero_roughness_used'],
             'native-style positive G8/half/R10 quantization explicitly declared')
        if 'parent_manifest' in manifest:
            need(files.file_sha(manifest['parent_manifest'])==manifest['parent_manifest_sha256'],'four-way views retain exact original colored physical/demod manifest')
    first_view=Path(manifest['views']['white'])
    for view in manifest['views'].values():
        need(files.file_sha(Path(view)/'native-replay.txt')==manifest['native_replay']['sha256'],'exact same complete camera/jitter table')
    for index,frame in enumerate(manifest['frames']):
        need(frame['frame']==index+2,'unaltered SL/reset/sample sequence')
        data=load(case,manifest,frame)
        need(all(np.isfinite(v).all() for v in data.values()),'all references and actual native payloads finite')
        need(np.all(data['spec'][...,3]>0) and np.all(data['diff'][...,3]>0),'actual noisy first-hit/miss distances remain positive')
        code=manifest.get('rr_normal_r10_code',manifest.get('code'))
        need(code>0 and np.all(((data['normals']>>20)&1023)==code),'all provider roughness is strictly positive; no zero-filter bypass')
        for candidate,path in manifest['views'].items():
            view=Path(path)/frame['directory']
            for signal in corrected.NATIVE:
                field=native_field(manifest,candidate,signal)
                need(files.file_sha(view/(signal+'.bin'))==frame['payloads'][field]['sha256'],'every seven uploaded inputs match the sealed candidate bytes')
                if not signal.endswith('_albedo'):
                    need(files.file_sha(view/(signal+'.bin'))==files.file_sha(first_view/frame['directory']/(signal+'.bin')),
                         'candidate changes no noisy RGB/A, motion, normal or depth bytes')
            for signal in ('spec','diff'):
                rgba=np.fromfile(view/(signal+'_albedo.bin'),'u1').reshape(128,128,4)
                need(np.array_equal(rgba[...,3],data[signal+'_albedo'][...,3]),'unused albedo alpha not a second candidate axis')
        if manifest['schema']==colored.SCHEMA:
            for signal in ('spec','diff'):
                need(np.array_equal(data[signal][...,3].copy().view('<u2'),data['physical_'+signal][...,3].copy().view('<u2')),
                     'one synthetic demod preserves every physical hit-distance half word')
    return name,manifest


def execute(cases,output,executable,expected_sha):
    need(output.resolve().is_relative_to(scene.BASE.resolve()) and not output.exists(),'fresh task-scoped signed result directory; preserve all earlier failures')
    need(expected_sha and files.file_sha(executable)==expected_sha,'explicit exact already-built production-wrapper fixture EXE; never compile silently')
    need(files.file_sha(signed.DLL)==signed.DLL_SHA,'actual installed signed AMD1.2 DLL hash')
    output.mkdir(parents=True)
    probe=signed.native(executable,Path(cases[0][2]['views']['white']),output/'defaults-probe')
    settings=output/'common-effective-settings.txt'
    values=struct.unpack('<8f',struct.pack('<8I',*probe['effective_words']))
    settings.write_text(' '.join(format(float(v),'.9g') for v in values)+'\n',encoding='ascii')
    runs={}
    for case,name,manifest in cases:
        for candidate,view in manifest['views'].items():
            key=identity(manifest)+'-'+candidate
            need(key not in runs,'every full candidate history has a unique sealed result')
            run=signed.native(executable,Path(view),output/key,settings)
            need(run['effective_words']==probe['effective_words'] and run['default_words']==probe['default_words'],
                 'physically fresh contexts use bit-identical eight SDK controls/defaults')
            run.update(input_case=str(case),input_manifest_sha256=files.file_sha(case/name),candidate=candidate,outputs={})
            for frame in manifest['frames']:
                folder=output/key/frame['directory']
                need(files.file_sha(folder/'motion.bin')==frame['payloads']['motion']['sha256'],'actual GPU surface motion exact, not a different correspondence hypothesis')
                run['outputs'][str(frame['frame'])]={}
                for signal,alpha in (('spec',.75),('diff',2.)):
                    path=folder/(signal+'.bin')
                    value=np.fromfile(path,'<f2').reshape(128,128,4)
                    need(np.isfinite(value).all() and np.all(value[...,3]==np.float16(alpha)),'actual committed output finite with exact original opaque title alpha')
                    run['outputs'][str(frame['frame'])][signal]=files.file_sha(path)
            files.write_json(output/key/'native-result.json',run)
            files.write_json(output/key/'runs.json',dict(schema='corrected-albedo-one-case-signed-runs',
                prepared_manifest_sha256=run['input_manifest_sha256'],input_case=str(case),runs={candidate:run}))
            runs[key]=run
    result=dict(schema='corrected-albedo-signed-runs-v7-v8',runs=runs,probe=probe,
        executable_sha256=expected_sha,provider_dll_sha256=signed.DLL_SHA,
        no_compilation=True,gpu_executed=True,checks=CHECKS,sealed_payload_checks=files.CHECKS)
    files.write_json(output/'runs.json',result)
    return result


def ghosts(data,geometry,previous_diff,previous_age,is_colored):
    """Analysis-only stale history in current material units.

    RR stores demodulated light. Preserve old visibility-source factors when
    decoding old physical ghosts, then multiply CURRENT factors at Consumer.
    Metal1's physical diffuse0/Qd0 has the declared old unit-direct extension;
    carry that extension with its cohort instead of inventing a divide by0.
    """
    if not is_colored:
        return dict(spec=data['ghost_spec'].astype(np.float64),diff=data['ghost_diff'].astype(np.float64))
    old_qs=np.rint(data['ghost_qs'].astype(np.float64)*255)/255
    old_qd=np.rint(data['ghost_qd'].astype(np.float64)*255)/255
    spec=data['ghost_spec'].astype(np.float64)/old_qs
    diffuse=np.zeros_like(spec)
    age=data['reveal_age']
    new=age==0
    carried=(age>0)&(age<=32)
    if previous_diff is not None:
        sy,sx=geometry['sy'],geometry['sx']
        need(np.all(previous_age[sy[carried],sx[carried]].astype(int)+1==age[carried]),'analysis stale-diffuse extension follows same historical cohort')
        diffuse[carried]=previous_diff[sy[carried],sx[carried]]
    else:
        need(not new.any() and not carried.any(),'no fabricated pre-reset ghost')
    if new.any():
        value=geometry['previous_visible']['diff'][new].copy()
        np.divide(data['ghost_diff'][new].astype(np.float64),old_qd[new],out=value,where=old_qd[new]>0)
        diffuse[new]=value
    return dict(spec=spec,diff=diffuse)


def compare(cases,output):
    run_info=json.loads((output/'runs.json').read_bytes())
    camera=transport.camera_api()
    results={}
    for case,name,manifest in cases:
        key=identity(manifest)
        candidates=list(manifest['views'])
        frames=[]
        pairs={n:{s:[] for s in ('spec','diff','combined')} for n in candidates if n!='white'}
        grad={n:{d:[] for d in ('physical','demod_same_material')} for n in ('noisy_input',)+tuple(candidates)}
        previous_diff=previous_age=None
        physical_manifest=None
        if manifest['schema']==corrected.SCHEMA:
            physical_case=Path(manifest['physical_case'])
            physical_manifest=json.loads((physical_case/'ggx-sequence.json').read_bytes())
        for index,frame in enumerate(manifest['frames']):
            data=load(case,manifest,frame)
            colored_case=manifest['schema']==colored.SCHEMA
            physical=data if colored_case else frozen.load_frame(physical_case,physical_manifest,physical_manifest['frames'][index],
                ('reference_spec','reference_spec_a','reference_spec_b','reference_diff'))
            factors=dict(spec=np.rint(data['qs_current'].astype(np.float64)*255)/255,
                diff=np.rint(data['qd_current'].astype(np.float64)*255)/255 if colored_case else 1.)
            geometry=transport.frame_geometry(index,camera)
            old=ghosts(data,geometry,previous_diff,previous_age,colored_case)
            previous_diff,previous_age=old['diff'],data['reveal_age']
            lights={'noisy_input':{s:data[s][...,:3].astype(np.float64) for s in ('spec','diff')}}
            for candidate in candidates:
                run=run_info['runs'][key+'-'+candidate]
                need(run['input_manifest_sha256']==files.file_sha(case/name),'actual signed outputs belong to exactly this immutable guide pair')
                lights[candidate]={}
                for signal in ('spec','diff'):
                    path=output/(key+'-'+candidate)/frame['directory']/(signal+'.bin')
                    need(files.file_sha(path)==run['outputs'][str(frame['frame'])][signal],'sealed actual-provider output integrity before analysis')
                    lights[candidate][signal]=np.fromfile(path,'<f2').reshape(128,128,4)[...,:3].astype(np.float64)
            refs={s:physical['reference_'+s].astype(np.float64) for s in ('spec','diff')}
            ref_pair=[physical['reference_spec_'+s].astype(np.float64) for s in ('a','b')]
            row=dict(frame=frame['frame'],domains={s:{} for s in ('spec','diff','combined')})
            for candidate,signals in lights.items():
                remod={s:signals[s]*factors[s] for s in ('spec','diff')}
                for signal in ('spec','diff','combined'):
                    value=remod[signal] if signal!='combined' else remod['spec']+remod['diff']
                    reference=refs[signal] if signal!='combined' else refs['spec']+refs['diff']
                    ghost=old[signal]*factors[signal] if signal!='combined' else old['spec']*factors['spec']+old['diff']*factors['diff']
                    row['domains'][signal][candidate]=camera['metrics'](value,reference,data['reveal_age'],ghost,manifest['comparison_crop'])
                crop=np.s_[16:112,16:112]
                ids=data['material_id'] if colored_case else data['object']
                grad[candidate]['physical'].append(detail.gradients(remod['spec'][crop],ref_pair[0][crop],ref_pair[1][crop]))
                grad[candidate]['demod_same_material'].append(detail.gradients(signals['spec'][crop],
                    (ref_pair[0]/factors['spec'])[crop],(ref_pair[1]/factors['spec'])[crop],ids[crop]))
            for active,domains in pairs.items():
                for signal in domains:
                    baseline=lights['white']['spec']*factors['spec'] if signal=='spec' else lights['white']['diff']*factors['diff']
                    candidate=lights[active]['spec']*factors['spec'] if signal=='spec' else lights[active]['diff']*factors['diff']
                    r_a,r_b=ref_pair if signal=='spec' else (refs['diff'],refs['diff'])
                    if signal=='combined':
                        baseline+=lights['white']['spec']*factors['spec']
                        candidate+=lights[active]['spec']*factors['spec']
                        r_a,r_b=ref_pair[0]+refs['diff'],ref_pair[1]+refs['diff']
                    pairs[active][signal].append(uncertainty.paired_mse(candidate,baseline,r_a,r_b,manifest['comparison_crop']))
            frames.append(row)
        results[key]=dict(input_case=str(case),input_manifest_sha256=files.file_sha(case/name),
            summaries=signed.summarize(frames,['noisy_input']+candidates),
            candidate_minus_white_paired_mse={n:{s:uncertainty.summarize_paired(rows) for s,rows in domains.items()} for n,domains in pairs.items()},
            gradients={n:{d:detail.summarize(rows) for d,rows in domains.items()} for n,domains in grad.items()},frames=frames,
            identity_pair=manifest.get('identity_pair',False),colored_material=colored_case,
            guide_hardware_quantization_verified=False,
            no_improvement_assertion=True,reference_uncertainty='two independent256spp references; temporal blocks do not measure provider run-to-run nondeterminism',
            physical_gradient_caveat='colored material edges contribute contrast; demod same-material gradient separately excludes those adjacent pairs')
    result=dict(schema='corrected-albedo-signed-comparison-v7-v8',cases=results,native_runs=run_info,
        checks=CHECKS,sealed_payload_checks=files.CHECKS,gpu_executed=True,compiler_executed=False,
        no_native_nrd_pair=True,game_quality_or_fps_claimed=False,all_noisy_lighting_through_rr=True,
        consumer_scope='actual GPU fixture verifies RGBcodec/opaquealpha and factor64; synthetic Q remodulation metrics are explicit CPU analysis, not native compositor-LUT execution')
    files.write_json(output/'comparison.json',result)
    print(json.dumps({k:{n:v for n,v in case.items() if n!='frames'} for k,case in results.items()},indent=2))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case',type=Path,action='append',required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--native-exe',type=Path)
    parser.add_argument('--native-exe-sha')
    parser.add_argument('--run',action='store_true')
    parser.add_argument('--prepare-four-way',action='store_true')
    parser.add_argument('--analyze-existing',action='store_true')
    args=parser.parse_args()
    if args.prepare_four_way:
        need(len(args.case)==1 and not args.run and not args.analyze_existing,'isolated CPU-only view extension')
        four_way(args.case[0],args.output)
        raise SystemExit(0)
    cases=[(case,*validate(case)) for case in args.case]
    if args.run:
        need(args.native_exe is not None,'explicit prebuilt native harness required')
        execute(cases,args.output,args.native_exe,args.native_exe_sha)
    if args.run or args.analyze_existing:
        compare(cases,args.output)
    else:
        print(json.dumps(dict(validated=[identity(m) for _,_,m in cases],checks=CHECKS,
            sealed_payload_checks=files.CHECKS,gpu_executed=False,compiler_executed=False),indent=2))
