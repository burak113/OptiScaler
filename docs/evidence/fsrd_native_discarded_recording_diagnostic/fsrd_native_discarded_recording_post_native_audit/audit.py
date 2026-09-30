"""CPU-only independent raw H2 audit; no native/helper execution."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,itertools,json,struct,re,shlex
import numpy as np
ROOT=Path('F:/OptiRevelations/OptiScaler-ffxD-alpha/tools_tmp')
P=ROOT/'fsrd_native_discarded_recording_diagnostic_20260930'
OUT=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def identity(p):
    p=Path(p);return {'path':str(p),'bytes':p.stat().st_size,'sha256':sha(p)}
def load(p):return json.loads(Path(p).read_text())
def save(name,v):
    with(OUT/name).open('x',encoding='utf-8',newline='\n')as f:json.dump(v,f,indent=2,allow_nan=False);f.write('\n')
def check(items):
    for item in items:assert identity(item['path'])==item,item['path']
def u32(p):
    b=Path(p).read_bytes();assert len(b)%4==0;return list(struct.unpack('<'+'I'*(len(b)//4),b))
def metric(a,b):
    aa=a.view('<u2');bb=b.view('<u2')
    r={'RGBA_bits_exact':bool((aa==bb).all()),'RGB_bits_exact':bool((aa[...,:3]==bb[...,:3]).all()),
       'all_finite':bool(np.isfinite(a).all()and np.isfinite(b).all())}
    for select,label in [(slice(0,3),'RGB'),(slice(3,4),'alpha'),(slice(None),'RGBA')]:
        d=a[...,select].astype('f8')-b[...,select].astype('f8');sq=d*d
        r[label]={'RMS':float(np.sqrt(sq.sum()/sq.size)),'max_abs':float(np.abs(d).max()),
                  'changed_fraction':float(np.count_nonzero(d)/d.size),
                  'per_frame_RMS':[float(np.sqrt(x.sum()/x.size))for x in sq]}
    return r
def detail(a,b,frames):
    r=metric(a,b);bits=(a.view('<u2')!=b.view('<u2'))
    changed=np.any(bits[...,:3],axis=(1,2,3))
    r['changed_RGB_source_frames']=[f for f,c in zip(frames,changed)if c]
    r['first_changed_RGB_source_frame']=next(iter(r['changed_RGB_source_frames']),None)
    return r
def compare_json(a,b,path=''):
    if isinstance(a,dict):
        assert a.keys()==b.keys(),path
        for k in a:compare_json(a[k],b[k],path+'/'+k)
    elif isinstance(a,list):
        assert len(a)==len(b),path
        for i,(x,y)in enumerate(zip(a,b)):compare_json(x,y,path+'/'+str(i))
    elif isinstance(a,float):assert np.isclose(a,b,rtol=1e-13,atol=1e-18), (path,a,b)
    else:assert a==b,(path,a,b)

reg=load(P/'registration.json');report=load(P/'evidence/results.json')
assert report['status']=='completed_H2_native_record_discard_diagnostic_not_solution'
assert [report[k]for k in ['completed_native_contexts','successful_API_RR_recordings','queued_RR_dispatches','discarded_RR_recordings']]==[8,462,458,4]
pin_names=['registration.json','pre_native_freeze.json','accounting_v2_pre_native_freeze.json','accounting_v3_pre_native_freeze.json','evidence/results.json','raw_comparisons.json']
pins=[identity(P/n)for n in pin_names]
for name in ['pre_native_freeze.json','accounting_v2_pre_native_freeze.json','accounting_v3_pre_native_freeze.json']:
    frozen=load(P/name);check(frozen['files']);check(frozen.get('external_sources',[]))
prep=load(P/'preparation_completion_manifest_v3.json');check(prep['files'])
pre_review=load(ROOT/'fsrd_native_discarded_recording_review_20260930/producer_final_seal_review.json')
assert pre_review['native_has_not_run']
old=Path(reg['source_frozen_wave_P']);old_id=load(old/'amd_context_identity.json')
for name,h in old_id['inputs'].items():assert sha(old/name)==h
old_controls=(old/'dispatch_controls.bin').read_bytes();assert sha(old/'dispatch_controls.bin')==old_id['applied_dispatch_sha256']
for name,h in old_id['output_sha256'].items():assert sha(old/name)==h
old_job=[shlex.split(x)for x in(old/'job.txt').read_text().splitlines()]
arrays={};controls={};indices={};case_rows=[];pids=[]
recorded_count=queued_count=discarded_count=0;peak=0;min_free=[]
for c in reg['cases']:
    tag=c['tag'];folder=P/'evidence'/tag;measured=report['cases'][tag]
    check(measured['files']);check(c['inputs'] if False else [{k:item[k]for k in ['path','bytes','sha256']}for item in c['inputs']])
    guard=load(folder/'resource_guard.json');assert guard==measured['guard']
    assert guard['status']=='completed' and guard['returncode']==0 and not guard['terminated_owned_child']
    assert guard['args']==c['command'] and guard['child_pid'] is not None
    assert (guard['timeout_seconds'],guard['maximum_working_set_bytes'],guard['minimum_available_memory_bytes'])==(240,2**31,2**30)
    pids.append(guard['child_pid']);peak=max(peak,guard['peak_observed_working_set_bytes']);min_free.append(guard['minimum_observed_available_bytes'])
    log=(folder/'stdout.log').read_text();stderr=(folder/'stderr.log').read_bytes();assert not stderr
    assert 'adapter=AMD Radeon RX 9070' in log and 'debug_layer=1' in log
    assert 'requested_api=4202496' in log and 'version_query_result=6' in log
    assert str(Path(reg['dll']['path'])) in log
    footer=re.findall(r'RR_recordings=(\d+) queued_RR_dispatches=(\d+) discarded_RR_recordings=(\d+) validation_errors=(\d+) validation_warnings=(\d+) sdk_errors=(\d+) sdk_warnings=(\d+)',log)
    assert len(footer)==1;counts=list(map(int,footer[0]))
    assert counts==[c['frames_recorded'],c['frames_queued'],c['frames_discarded'],0,0,0,0]
    if c['skip_frame']==24:
        assert 'discarded_recording source_frame=24 previous_submitted_source_frame=23 previous_completed_fence=24 external_state_shadow_restored=1 queued=0 observed_output=0' in log
    else:assert 'discarded_recording source_frame=' not in log
    applied=(folder/'dispatch_controls.bin').read_bytes();assert applied==(folder/'expected_applied_dispatch_controls.bin').read_bytes()
    assert len(applied)==184*c['frames_recorded']
    recorded=u32(folder/'recorded_frame_indices.bin');observed=u32(folder/'observed_frame_indices.bin')
    presence=(folder/'output_presence.bin').read_bytes()
    assert recorded==c['source_frame_indices'] and observed==c['observed_frame_indices']
    assert presence==(folder/'expected_output_presence.bin').read_bytes()==bytes(c['output_presence_mask'])
    assert observed==[f for f,on in zip(recorded,presence)if on]
    assert (24 not in observed)==(c['skip_frame']==24 or c['source_frame_start']==25)
    indices[tag]=observed;controls[tag]={f:applied[i*184:(i+1)*184]for i,f in enumerate(recorded)}
    for i,f in enumerate(recorded):assert struct.unpack_from('<I',applied,i*184)[0]==f
    for j,item in enumerate(c['inputs']):
        fmt=item['DXGI_format'];bpp=8 if fmt==10 else 4;old_data=Path(old_job[j+1][0]).read_bytes()
        expected=old_data[25*128*80*bpp:]if c['source_frame_start']==25 and int(old_job[j+1][2])==64 else old_data
        assert Path(item['path']).read_bytes()==expected
    expected=bytearray(old_controls[25*184:]if c['source_frame_start']==25 else old_controls)
    if c['source_frame_start']==25:struct.pack_into('<I',expected,4,struct.unpack_from('<I',expected,4)[0]|1)
    elif c['recovery_reset_frame']==25:struct.pack_into('<I',expected,25*184+4,struct.unpack_from('<I',expected,25*184+4)[0]|1)
    assert applied==bytes(expected)
    accounting=load(folder/'native_work_accounting.json');assert accounting==measured['native_work_accounting']
    assert accounting['final_CPP_footer_valid'] and not accounting['totals_unknown'] and not accounting['evidence_disagreements']
    assert accounting['counter_authority']=='valid_bounded_final_CPP_footer_under_pinned_source'
    assert [accounting[k]for k in ['successful_API_RR_recordings_confirmed','queued_RR_dispatches_confirmed_completed','discarded_API_RR_recordings_confirmed']]==counts[:3]
    assert measured['metadata_accepted']
    arrays[tag]={}
    for name in ['diffuse.bin','specular.bin']:
        raw=folder/name;assert raw.stat().st_size==c['expected_raw_lobe_bytes']==len(observed)*128*80*8
        assert identity(raw)=={k:measured['lobes'][name][k]for k in ['path','bytes','sha256']}
        a=np.fromfile(raw,'<f2').reshape(len(observed),80,128,4);assert np.isfinite(a).all();arrays[tag][name]=a
    case_rows.append({'tag':tag,'API_recordings':counts[0],'queued_RR':counts[1],'discarded':counts[2],
        'presence_zeros':presence.count(0),'actual_observed_source_indices':observed,'actual_recorded_source_indices':recorded,
        'applied_controls':identity(folder/'dispatch_controls.bin'),'guard':identity(folder/'resource_guard.json'),
        'lobe_hashes':{name:sha(folder/name)for name in arrays[tag]},'all_error_warning_counts_zero':True,
        'input_upload_counts':[item['uploads']for item in c['inputs']],
        'alpha_unique_values':{name:np.unique(a[...,3]).astype(float).tolist()for name,a in arrays[tag].items()}})
    recorded_count+=counts[0];queued_count+=counts[1];discarded_count+=counts[2]
assert len(set(pids))==8 and (recorded_count,queued_count,discarded_count)==(462,458,4)

comparisons={};compact_pairs={}
for left,right in itertools.combinations(reg['mode_order'],2):
    lidx=indices[left];ridx=indices[right];common=sorted(set(lidx)&set(ridx))
    label=left+'__'+right;comparisons[label]={};compact_pairs[label]={}
    for mode,pairs in [('submitted_ordinal',list(zip(lidx,ridx))),('common_source_frame',[(f,f)for f in common])]:
        frame_meta=[{'left_source_frame':a,'right_source_frame':b,'left_submitted_ordinal':lidx.index(a),'right_submitted_ordinal':ridx.index(b),
              'left_flags':struct.unpack_from('<I',controls[left][a],4)[0],'right_flags':struct.unpack_from('<I',controls[right][b],4)[0],
              'applied_184_bytes_exact':controls[left][a]==controls[right][b]}for a,b in pairs]
        la=[lidx.index(a)for a,b in pairs];ra=[ridx.index(b)for a,b in pairs]
        lobes={name:metric(arrays[left][name][la],arrays[right][name][ra])for name in arrays[left]}
        comparisons[label][mode]={'frames':frame_meta,'lobes':lobes}
        compact_pairs[label][mode]={'frames_compared':len(pairs),'all_controls_exact':all(m['applied_184_bytes_exact']for m in frame_meta),
           'all_source_frames_equal':all(a==b for a,b in pairs),
           'lobes':{name:{'RGB_bits_exact':v['RGB_bits_exact'],'RGBA_bits_exact':v['RGBA_bits_exact'],
                          'RGB_RMS':v['RGB']['RMS'],'RGBA_RMS':v['RGBA']['RMS'],
                          'first_changed_left_source_frame':next((pairs[i][0]for i,x in enumerate(v['RGB']['per_frame_RMS'])if x>0),None)}for name,v in lobes.items()}}
assert len(comparisons)==28
producer=load(P/'raw_comparisons.json');compare_json(comparisons,producer['comparisons'])
save('independent_pair_metrics.json',{'schema':'independent-H2-all-pair-raw-metrics-v1','comparisons':comparisons,
 'pairs':28,'alignments_per_pair':2,'lobes_per_alignment':2,'producer_metrics_match':True,'own_GPU_native_calls':0})

repeat=[];reset_fresh=[];early=[];drop_summary=[]
for kind in ['baseline','discard24','discard24_reset25','fresh_tail25']:
    l='round0_'+kind;r='round1_'+kind;key=l+'__'+r if l+'__'+r in compact_pairs else r+'__'+l
    repeat.append({'kind':kind,**compact_pairs[key]['common_source_frame']})
for reset in ['round0_discard24_reset25','round1_discard24_reset25']:
    for fresh in ['round0_fresh_tail25','round1_fresh_tail25']:
        f=list(range(25,64));lr=[indices[reset].index(x)for x in f];rr=[indices[fresh].index(x)for x in f]
        assert all(controls[reset][x]==controls[fresh][x]for x in f)
        row={'reset':reset,'fresh':fresh,'matched_source_frames':f,'all184_controls_exact':True,'lobes':{}}
        for name in arrays[reset]:
            left=arrays[reset][name][lr];right=arrays[fresh][name][rr]
            m=metric(left,right);row['lobes'][name]=m
            assert m['RGBA_bits_exact']
            assert (P/'evidence'/reset/name).read_bytes()[24*128*80*8:]==(P/'evidence'/fresh/name).read_bytes()
        reset_fresh.append(row)
full=[tag for tag in reg['mode_order']if 'fresh_tail'not in tag]
for l,r in itertools.combinations(full,2):
    f=list(range(24));la=[indices[l].index(x)for x in f];ra=[indices[r].index(x)for x in f]
    early.append({'left':l,'right':r,'source_frames':[0,23],
        'all184_controls_exact':all(controls[l][x]==controls[r][x]for x in f),
        'lobes':{name:detail(arrays[l][name][la],arrays[r][name][ra],f)for name in arrays[l]}})
for baseline in ['round0_baseline','round1_baseline']:
    for other in ['round0_discard24','round1_discard24','round0_discard24_reset25','round1_discard24_reset25']:
        f=[x for x in indices[other]if x>=25]
        la=[indices[baseline].index(x)for x in f];ra=[indices[other].index(x)for x in f]
        drop_summary.append({'baseline':baseline,'other':other,'source_frames':f,
             'all184_controls_exact':all(controls[baseline][x]==controls[other][x]for x in f),
             'control_difference_source_frames':[x for x in f if controls[baseline][x]!=controls[other][x]],
             'lobes':{name:detail(arrays[baseline][name][la],arrays[other][name][ra],f)for name in arrays[baseline]}})
old_compare=[]
old_arrays={name:np.fromfile(old/name,'<f2').reshape(64,80,128,4)for name in ['diffuse.bin','specular.bin']}
for tag in full:
    for lo,hi in [(0,23),(25,63)]:
        f=list(range(lo,hi+1));ii=[indices[tag].index(x)for x in f]
        old_compare.append({'new_context':tag,'source_interval':[lo,hi],
            'new_vs_old_wrapper_binary_equal':False,'old_wrapper_SHA':old_id['runner_sha256'],
            'new_wrapper_SHA':reg['new_binary']['sha256'],
            'all184_controls_exact':all(controls[tag][x]==old_controls[x*184:(x+1)*184]for x in f),
            'lobes':{name:detail(arrays[tag][name][ii],old_arrays[name][f],f)for name in old_arrays}})
save('trajectory_checks.json',{'schema':'independent-H2-repeats-prefix-drop-recovery-v1','arm_repeats':repeat,
 'new_contexts_first0_23':early,'baseline_vs_later_drop_and_reset':drop_summary,'reset25_vs_fresh25_all_four_pairs':reset_fresh,
 'older_original_context_reference_comparison':old_compare,'quality_accepted':False})
check(prep['files']);assert pins==[identity(item['path'])for item in pins]
assert not report['quality_accepted'] and not report['game_run']
audit={'schema':'independent-H2-post-native-audit-v1','utc':datetime.now(timezone.utc).isoformat(),
 'status':'completed_independent_native_diagnostic_audit_not_solution','producer_report':identity(P/'evidence/results.json'),
 'prelaunch_seal':identity(ROOT/'fsrd_native_discarded_recording_review_20260930/producer_final_seal_review.json'),
 'preparation_manifest_entries_verified':len(prep['files']),'actual_contexts':8,'successful_API_RR_recordings':462,
 'completed_queued_RR_dispatch_frames':458,'discarded_recordings_not_queued':4,
 'queued_count_units':'Logical SDK dispatch-containing frames submitted and completed; private SDK shader/kernel count is not measured.',
 'all8_guard_exit_codes_zero':True,'all_D3D_SDK_errors_warnings_zero':True,'all56_input_files_and184_controls_verified':True,
 'all_missing_source24_outputs_absent_no_zero_fill':True,'all_four_reset25_vs_fresh25_tail_pairs_RGBA_bitexact':True,
 'all28_pairs_two_alignments_two_lobes_metrics_match_producer':True,'cases':case_rows,'arm_repeats':repeat,
 'first0_23_all_new_context_pairs_RGBA_exact':all(v['RGBA_bits_exact']for row in early for v in row['lobes'].values()),
 'prefix_comparison_pairs':15,'native_child_peak_working_set_bytes':peak,'minimum_sampled_available_bytes':min(min_free),
 'compact_pairs':compact_pairs,'pair_metrics':identity(OUT/'independent_pair_metrics.json'),'trajectories':identity(OUT/'trajectory_checks.json'),
 'qualifications':[
  'Baseline versus discard changes both missing GPU sourceframe24/history update and successful CPU SDK recording24 state advancement. No no-API24 control has been measured; differences do not isolate CPU bookkeeping as cause.',
  'Reset25 versus fresh-tail25 control+39-source-frame lobes are bitexact in all four measured crosspairs. Whole output hashes differ because reset arms retain24 prefix frames0..23; measured suffix bytes themselves are exact.',
  'Submitted ordinal alignment after the gap can compare different logical sourceframes. Source-frame intersections and184-byte control matching are separately retained; discarded24 never enters output comparisons.',
  'Header/API inspection supplied no discard-safe rollback guarantee. This synthetic frozen waveP diagnostic is not game scheduling, production failure path, truth/quality or stain cause evidence.',
  'Provider version query is unavailable with result6/id0; requested API4202496 and exact directly loaded DLL hash are verified, rather than claiming a queried provider version.',
  'Older original source-context output uses pinned wrapperB3427689..., while this isolated H2 wrapper is22cc5cb0...; those old/new reference comparisons preserve the binary difference and cannot be treated as a one-control same-binary test.',
  'Alpha bytes are reported separately. They are raw destination-channel observations, not an input-hit-alpha preservation or quality claim.'
 ],'source_pins_pre_and_post':pins,'own_GPU_native_build_calls':0,'quality_accepted':False,'game_cause_claim':False}
save('audit.json',audit)
save('completion_manifest.json',{'schema':'immutable-H2-post-native-independent-audit-completion-v1',
 'status':audit['status'],'own_GPU_native_build_calls':0,'files':[identity(p)for p in sorted(OUT.rglob('*'))if p.is_file()]})
print(json.dumps({'audit':identity(OUT/'audit.json'),'manifest':identity(OUT/'completion_manifest.json'),
 'prefix0_23_all_new_pairs_RGBA_exact':audit['first0_23_all_new_context_pairs_RGBA_exact'],
 'arm_repeat_RGBA_exact':{r['kind']:all(v['RGBA_bits_exact']for v in r['lobes'].values())for r in repeat},
 'drop_RMS':[{ 'baseline':r['baseline'],'other':r['other'],
              'lobes':{name:{'RMS':v['RGB']['RMS'],'first':v['first_changed_RGB_source_frame']}for name,v in r['lobes'].items()}}for r in drop_summary]}))
