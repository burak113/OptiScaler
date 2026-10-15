"""NEW ABBA repeatability closure of the sealed colored V8 WHITE/BOTH pair.

CPU validation by default. --run needs a separate parent GPU grant and the
shared lead_ops lock. Exactly256 additional actual signed dispatches, no probe,
no compiler/model/oracle/guide change. Context order: WHITE1,BOTH1,BOTH2,WHITE2.
Existing frozen source/data and the original8-run result are never overwritten.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import struct
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import numpy as np

import fsrd_nrd_rr_albedo_pair_compare as pair
import fsrd_nrd_rr_ggx_uncertainty as uncertainty
import fsrd_nrd_rr_material_compare as signed
import fsrd_nrd_rr_material_quality as files
import fsrd_nrd_rr_mirror_oracle as scene


EXE_SHA='b4e0e2b81379ad9b4c48d00bf78820766bfc9f512c4e35fd1a5feab8897b38fb'
ORDER=(('AB','white'),('AB','both'),('BA','both'),('BA','white'))
CHECKS=0


def need(condition,message):
    global CHECKS
    CHECKS+=1
    if not bool(condition):
        raise AssertionError(message)


def validate(case,old_results,settings,executable):
    name,manifest=pair.validate(case)
    need(tuple(manifest['views'])==('white','diffuse-only','specular-only','both'),'exact original four-way source; run only predeclared white/both subset')
    prior=json.loads((old_results/'runs.json').read_bytes())
    digest=files.file_sha(case/name)
    for candidate in ('white','both'):
        need(prior['runs'][pair.identity(manifest)+'-'+candidate]['input_manifest_sha256']==digest,'same immutable native guide/input/reference provenance as original negative run')
    words=list(struct.unpack('<8I',struct.pack('<8f',*[float(v) for v in settings.read_text().split()])))
    need(words==prior['probe']['effective_words'],'exact eight frozen queried SDK settings; no adaptive/tuned control change')
    need(files.file_sha(executable)==EXE_SHA==prior['executable_sha256'],'same exact prebuilt real-wrapper executable, no backend/route swap')
    need(files.file_sha(signed.DLL)==signed.DLL_SHA==prior['provider_dll_sha256'],'same exact installed signed AMD1.2 DLL')
    return name,manifest,words


def execute(case,name,manifest,words,settings,executable,output):
    need(not output.exists() and output.resolve().is_relative_to(scene.BASE.resolve()),'fresh task-scoped ABBA result, preserve all prior measurements')
    output.mkdir(parents=True)
    canonical_settings=output/'same-effective-settings.txt'
    files.immutable(canonical_settings,settings.read_bytes())
    groups={'AB':{},'BA':{}}
    order=[]
    for index,(group,candidate) in enumerate(ORDER):
        key=pair.identity(manifest)+'-'+candidate
        destination=output/group/key
        destination.parent.mkdir(parents=True,exist_ok=True)
        native=signed.native(executable,Path(manifest['views'][candidate]),destination,canonical_settings)
        need(native['effective_words']==words and native['default_words']==words,'all fresh contexts use identical frozen defaults/effective controls')
        native.update(input_case=str(case),input_manifest_sha256=files.file_sha(case/name),candidate=candidate,outputs={})
        for frame in manifest['frames']:
            folder=destination/frame['directory']
            need(files.file_sha(folder/'motion.bin')==frame['payloads']['motion']['sha256'],'actual GPU primary motion stays byte-identical')
            native['outputs'][str(frame['frame'])]={}
            for signal,alpha in (('spec',.75),('diff',2.)):
                path=folder/(signal+'.bin')
                value=np.fromfile(path,'<f2').reshape(128,128,4)
                need(np.isfinite(value).all() and np.all(value[...,3]==np.float16(alpha)),'actual output finite with exact original borrowed-title alpha')
                native['outputs'][str(frame['frame'])][signal]=files.file_sha(path)
        files.write_json(destination/'native-result.json',native)
        groups[group][key]=native
        order.append(dict(index=index,group=group,candidate=candidate,directory=str(destination),checks=native['checks']))
    for group,runs in groups.items():
        files.write_json(output/group/'runs.json',dict(schema='native-albedo-abba-two-context-pair',runs=runs,
            effective_words=words,source_manifest_sha256=files.file_sha(case/name),
            executable_sha256=EXE_SHA,provider_dll_sha256=signed.DLL_SHA,
            no_new_probe=True,prior_default_probe_reused=True))
    result=dict(schema='native-albedo-abba-signed-runs',order=order,groups=groups,
        prepared_manifest_sha256=files.file_sha(case/name),settings_sha256=files.file_sha(canonical_settings),
        effective_words=words,executable_sha256=EXE_SHA,provider_dll_sha256=signed.DLL_SHA,
        driver_source_sha256=files.file_sha(Path(__file__)),native_calls=256,
        checks=CHECKS,source_checks=pair.CHECKS,payload_checks=files.CHECKS,
        no_new_probe=True,compiler_executed=False,gpu_executed=True)
    files.write_json(output/'runs.json',result)
    return result


def read_output(output,info,group,candidate,manifest,frame,signal):
    key=pair.identity(manifest)+'-'+candidate
    record=info['groups'][group][key]
    path=output/group/key/frame['directory']/(signal+'.bin')
    need(files.file_sha(path)==record['outputs'][str(frame['frame'])][signal],'sealed raw actual ABBA provider output before repeatability analysis')
    return np.fromfile(path,'<f2').reshape(128,128,4)[...,:3]


def analyze(case,name,manifest,output):
    info=json.loads((output/'runs.json').read_bytes())
    need(info['prepared_manifest_sha256']==files.file_sha(case/name),'ABBA input/reference manifest identity')
    # The existing comparer accepts an explicit candidate subset in memory;
    # the original four-way manifest on disk and all its source hashes stay
    # unchanged. Both paired comparisons retain its full per-frame metric and
    # cross-reference gradient/ref-noise logic.
    subset=dict(manifest,views={n:manifest['views'][n] for n in ('white','both')})
    pair_results={group:pair.compare([(case,name,subset)],output/group) for group in ('AB','BA')}
    comparisons={(b,w):{s:[] for s in ('spec','diff','combined')} for b in ('AB','BA') for w in ('AB','BA')}
    repeats={c:{s:dict(squared=0.,count=0,max_abs=0.) for s in ('spec','diff','combined')} for c in ('white','both')}
    mismatch={c:{s:0 for s in ('spec','diff')} for c in ('white','both')}
    crop=np.s_[16:112,16:112,:3]
    for frame in manifest['frames']:
        data=pair.load(case,manifest,frame,('qs_current','qd_current','reference_spec_a','reference_spec_b','reference_diff'))
        factors={s:np.rint(data['q'+('s' if s=='spec' else 'd')+'_current'].astype(np.float64)*255)/255 for s in ('spec','diff')}
        physical={}
        for group,candidate in ORDER:
            raw={s:read_output(output,info,group,candidate,manifest,frame,s) for s in ('spec','diff')}
            physical[group,candidate]={s:raw[s].astype(np.float64)*factors[s] for s in ('spec','diff')}
            physical[group,candidate]['combined']=physical[group,candidate]['spec']+physical[group,candidate]['diff']
        for candidate in ('white','both'):
            for signal in ('spec','diff','combined'):
                delta=(physical['AB',candidate][signal]-physical['BA',candidate][signal])[crop]
                total=repeats[candidate][signal]
                total['squared']+=float(np.sum(delta*delta));total['count']+=delta.size
                total['max_abs']=max(total['max_abs'],float(np.max(abs(delta))))
            for signal in ('spec','diff'):
                left=read_output(output,info,'AB',candidate,manifest,frame,signal)[crop].copy().view('<u2')
                right=read_output(output,info,'BA',candidate,manifest,frame,signal)[crop].copy().view('<u2')
                mismatch[candidate][signal]+=int(np.count_nonzero(left!=right))
        for (b,w),domains in comparisons.items():
            for signal in domains:
                r_a,r_b=(data['reference_spec_a'],data['reference_spec_b']) if signal=='spec' else (data['reference_diff'],data['reference_diff'])
                if signal=='combined':
                    r_a=data['reference_spec_a'].astype(np.float64)+data['reference_diff']
                    r_b=data['reference_spec_b'].astype(np.float64)+data['reference_diff']
                domains[signal].append(uncertainty.paired_mse(physical[b,'both'][signal],physical[w,'white'][signal],r_a,r_b,manifest['comparison_crop']))
    for candidate,domains in repeats.items():
        for signal,row in domains.items():
            row['physical_roi_rgb_rmse']=float(np.sqrt(row['squared']/row['count']))
            if signal in mismatch[candidate]:row['mismatched_raw_half_words']=mismatch[candidate][signal]
    summaries={f'B{1 if b=="AB" else 2}-W{1 if w=="AB" else 2}':{s:uncertainty.summarize_paired(rows) for s,rows in domains.items()} for (b,w),domains in comparisons.items()}
    ranges={}
    for signal in ('spec','diff','combined'):
        ranges[signal]={replica:dict(min_delta=min(v[signal]['replicas'][replica]['mean_paired_mse_delta'] for v in summaries.values()),
            max_delta=max(v[signal]['replicas'][replica]['mean_paired_mse_delta'] for v in summaries.values())) for replica in ('a','b')}
    result=dict(schema='native-albedo-abba-repeatability-comparison',native_runs=info,
        paired_order_results={g:str(output/g/'comparison.json') for g in pair_results},
        physical_repeat_spread=repeats,all_four_cross_run_effects=summaries,cross_run_effect_ranges=ranges,
        contexts_per_condition=2,ordering='WHITE1,BOTH1,BOTH2,WHITE2',
        temporal_block_intervals_cover_context_repeat_variance=False,
        caveat='n=2 fresh contexts per condition: descriptive spread and all four contrasts, not a population confidence interval or guarantee',
        original_negative_run_not_replaced=True,settings_or_inputs_retuned=False,
        checks=CHECKS,source_checks=pair.CHECKS,payload_checks=files.CHECKS,
        compiler_executed=False,gpu_executed=True)
    files.write_json(output/'comparison.json',result)
    print(json.dumps(dict(checks=CHECKS,source_checks=pair.CHECKS,payload_checks=files.CHECKS,
        physical_repeat_spread=repeats,cross_run_effect_ranges=ranges,contexts_per_condition=2),indent=2))
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--case',type=Path,required=True)
    p.add_argument('--prior-results',type=Path,required=True)
    p.add_argument('--settings',type=Path,required=True)
    p.add_argument('--native-exe',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--run',action='store_true')
    p.add_argument('--analyze-existing',action='store_true')
    a=p.parse_args()
    name,manifest,words=validate(a.case,a.prior_results,a.settings,a.native_exe)
    if a.run:execute(a.case,name,manifest,words,a.settings,a.native_exe,a.output)
    if a.run or a.analyze_existing:analyze(a.case,name,manifest,a.output)
    else:print(json.dumps(dict(validated=True,ordering=ORDER,planned_native_calls=256,
        checks=CHECKS,source_checks=pair.CHECKS,payload_checks=files.CHECKS,compiler_executed=False,gpu_executed=False),indent=2))
