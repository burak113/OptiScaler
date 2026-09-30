"""Independent CPU/hash/raw audit: two V1 plus six post-observation V2 children."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,itertools,re,struct,shlex
import numpy as np
ROOT=Path('F:/OptiRevelations/OptiScaler-ffxD-alpha/tools_tmp')
P=ROOT/'fsrd_native_gap_cpu_record_control_20260930';H=ROOT/'fsrd_native_discarded_recording_diagnostic_20260930';OUT=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def ident(p):p=Path(p);return {'path':str(p),'bytes':p.stat().st_size,'sha256':sha(p)}
def load(p):return json.loads(Path(p).read_text())
def save(n,v):
    with(OUT/n).open('x',encoding='utf-8',newline='\n')as f:json.dump(v,f,indent=2,allow_nan=False);f.write('\n')
def check(rs):
    for r in rs:assert ident(r['path'])==r,r['path']
def ids(p):b=Path(p).read_bytes();assert len(b)%4==0;return list(struct.unpack('<'+'I'*(len(b)//4),b))
def verify_same(a,b,path=''):
    if isinstance(a,dict):
        assert a.keys()==b.keys(),path
        for k in a:verify_same(a[k],b[k],path+'/'+k)
    elif isinstance(a,list):
        assert len(a)==len(b),path
        for i,(x,y)in enumerate(zip(a,b)):verify_same(x,y,path+'/'+str(i))
    elif isinstance(a,float):assert abs(a-b)<=1e-15,path
    else:assert a==b,path
old=load(P/'evidence/results.json');new=load(P/'evidence/remaining_v2_results.json');reg=load(P/'registration.json')
partial=load(P/'partial_v1_inspection.json');href=load(H/'evidence/results.json')
assert old['status']=='failed_preserved' and old['metadata_accepted_native_contexts']==1
assert new['status']=='completed_matched_gap_CPU_record_remaining_V2_diagnostic_not_solution' and new['metadata_accepted_native_contexts']==6
fields=['completed_native_contexts','successful_API_RR_recordings','queued_RR_dispatches','discarded_RR_recordings','no_API_omissions']
assert [old[k]for k in fields]==[2,127,126,1,1] and [new[k]for k in fields]==[6,381,378,3,3]
assert list(old['cases'])==reg['mode_order'][:2] and list(new['cases'])==reg['mode_order'][2:]
assert new['previous_V1_results_sha256']==sha(P/'evidence/results.json')
seal=load(P/'remaining_v2_preparation_completion_manifest.json');check(seal['files']);check(seal['external_sources'])
pins=[ident(P/n)for n in ['evidence/results.json','evidence/remaining_v2_results.json','partial_v1_inspection.json','remaining_v2_preparation_completion_manifest.json','registration.json','fsrd_rr_gap_control.exe','analyze_combined_v2.py','combined_v2_raw_comparisons.json']]
assert sha(P/'combined_v2_raw_comparisons.json')=='de173ad9835bf784bad4abfea8ee5cc9cc1c9d7c80cdba1fa1b78cfd2999287f'
producer=load(P/'combined_v2_raw_comparisons.json');arrays={};frames={};controls={};row=[];snapshots=[];groups={};totals=np.zeros(4,dtype=int);warnings=0
for c in reg['cases']:
    tag=c['tag'];is_old=tag in old['cases'];info=(old if is_old else new)['cases'][tag];data=partial['cases'][tag]if is_old else info
    folder=P/'evidence'/tag;noapi=c['no_api_frame']==24;reset=c['recovery_reset_frame']==25
    stdout=(folder/'stdout.log').read_text();stderr=(folder/'stderr.log').read_bytes()
    match=re.search(r'RR_recordings=(\d+) queued_RR_dispatches=(\d+) discarded_RR_recordings=(\d+) validation_errors=(\d+) validation_warnings=(\d+) sdk_errors=(\d+) sdk_warnings=(\d+) no_API_omissions=(\d+)',stdout)
    assert match;counts=list(map(int,match.groups()));warn=1 if noapi and not reset else 0
    assert counts==[63 if noapi else 64,63,0 if noapi else 1,0,0,0,warn,1 if noapi else 0]
    assert stderr==(b'SDK: Frame index jump detected. Resetting...\r\n'if warn else b'')
    warnings+=warn;totals+=np.array([counts[i]for i in [0,1,2,7]])
    guard=load(folder/'resource_guard.json');assert guard==info['guard']
    assert guard['status']=='completed' and guard['returncode']==0 and not guard['terminated_owned_child']
    assert guard['args']==c['command'] and [guard[k]for k in ['timeout_seconds','maximum_working_set_bytes','minimum_available_memory_bytes']]==[240,2147483648,1073741824]
    assert 'debug_layer=1'in stdout and 'provider=unavailable from direct effect DLL id=0 version_query_result=6 requested_api=4202496'in stdout
    ri=ids(folder/'recorded_frame_indices.bin');oi=ids(folder/'observed_frame_indices.bin');ni=ids(folder/'omitted_API_frame_indices.bin')
    assert ri==c['source_frame_indices'] and oi==c['observed_frame_indices'] and ni==c['omitted_API_frame_indices']
    assert oi==[f for f in range(64)if f!=24] and (folder/'output_presence.bin').read_bytes()==bytes(c['output_presence_mask'])
    rawcontrol=(folder/'dispatch_controls.bin').read_bytes();assert rawcontrol==(folder/'expected_applied_dispatch_controls.bin').read_bytes()
    controls[tag]={f:rawcontrol[i*184:(i+1)*184]for i,f in enumerate(ri)}
    for f,b in controls[tag].items():assert struct.unpack_from('<IIII',b)==(f,3 if f==0 or reset and f==25 else 2,128,80)
    queued=b''.join(controls[tag][f]for f in oi);assert queued==(folder/'expected_queued_dispatch_controls.bin').read_bytes()
    if is_old and noapi:assert not(folder/'queued_dispatch_controls.bin').exists();(OUT/(tag+'_derived_queued_controls.bin')).write_bytes(queued)
    else:assert queued==(folder/'queued_dispatch_controls.bin').read_bytes()
    inputhashes=[];job=[shlex.split(x)for x in(folder/'job.txt').read_text().splitlines()]
    assert list(map(int,job[0][:8]))==[128,80,64,2,32,0,1,0]
    assert Path(job[0][8])==Path(reg['dll']['path']) and ident(reg['dll']['path'])==reg['dll']
    for i,inp in enumerate(c['inputs']):
        assert ident(inp['path'])=={k:inp[k]for k in ['path','bytes','sha256']}
        assert inp['DXGI_format']==int(job[i+1][1]) and inp['uploads']==int(job[i+1][2])
        inputhashes.append(inp['sha256'])
    assert [i['uploads']for i in c['inputs']]==[1,1,1,1,1,64,64]
    if groups:assert inputhashes==next(iter(groups.values()))['inputhashes']
    if reset in groups:assert queued==groups[reset]['queued']
    else:groups[reset]={'inputhashes':inputhashes,'queued':queued}
    arrays[tag]={};frames[tag]=oi
    for n in ['diffuse.bin','specular.bin']:
        p=folder/n;assert p.stat().st_size==63*80*128*4*2 and sha(p)==data['lobes'][n]['sha256']
        a=np.fromfile(p,'<f2').reshape(63,80,128,4);assert np.isfinite(a).all();arrays[tag][n]=a
    account=load(folder/'native_work_accounting.json');assert account==info['native_work_accounting']
    assert not account['totals_unknown'] and account['completed_native_context_final_marker'] and not account['evidence_disagreements']
    assert [account[k]for k in ['successful_API_RR_recordings_confirmed','queued_RR_dispatches_confirmed_completed','discarded_API_RR_recordings_confirmed','no_API_omissions_confirmed']]==[counts[i]for i in [0,1,2,7]]
    if not is_old:
        retained=info['diagnostic_warning_admissibility'];assert retained['actual_SDK_warning_count']==warn and retained['diagnostic_retention_admissible'] and not retained['quality_accepted']
    snapshots.extend(ident(p)for p in sorted(folder.iterdir())if p.is_file())
    row.append({'tag':tag,'origin':'original_V1'if is_old else'remaining_V2','counts':counts,'metadata_accepted_under_own_rule':info['metadata_accepted'],
        'actual_warning_bytes_hex':stderr.hex(),'all63_output_frames_finite':True,'source25_flags':3 if reset else 2,'source24_output_absent':True,'guard':guard})
assert totals.tolist()==[508,504,4,4] and warnings==2
def metrics(a,b):
    result={'RGBA_bits_exact':bool(np.array_equal(a.view('<u2'),b.view('<u2'))),'RGB_bits_exact':bool(np.array_equal(a[...,:3].view('<u2'),b[...,:3].view('<u2'))),'all_finite':bool(np.isfinite(a).all()and np.isfinite(b).all())}
    for label,s in [('RGB',slice(0,3)),('alpha',slice(3,4)),('RGBA',slice(None))]:
        diff=a[...,s].astype(np.float64)-b[...,s].astype(np.float64)
        result[label]={'RMS':float(np.sqrt(np.mean(diff**2))),'max_abs':float(np.max(np.abs(diff))),'changed_fraction':float(np.count_nonzero(diff)/diff.size),
            'per_frame_RMS':[float(np.sqrt(np.mean(frame**2)))for frame in diff]}
    return result
comparisons={};exactpairs=0
for left,right in itertools.combinations(reg['mode_order'],2):
    aa=frames[left];bb=frames[right];entry={}
    for label,pairs in [('submitted_ordinal',list(zip(aa,bb))),('common_source_frame',[(f,f)for f in sorted(set(aa)&set(bb))])]:
        metadata=[{'left_source_frame':a,'right_source_frame':b,'left_submitted_ordinal':aa.index(a),'right_submitted_ordinal':bb.index(b),
            'left_flags':struct.unpack_from('<I',controls[left][a],4)[0],'right_flags':struct.unpack_from('<I',controls[right][b],4)[0],'applied_184_bytes_exact':controls[left][a]==controls[right][b]}for a,b in pairs]
        entry[label]={'frames':metadata,'lobes':{n:metrics(arrays[left][n][[aa.index(a)for a,b in pairs]],arrays[right][n][[bb.index(b)for a,b in pairs]])for n in arrays[left]}}
    key=left+'__'+right;verify_same(entry,producer['comparisons'][key],key);comparisons[key]=entry
    exactpairs+=int(all(m['RGBA_bits_exact']for m in entry['common_source_frame']['lobes'].values()))
assert len(comparisons)==28 and exactpairs==16
save('independent_pair_metrics.json',comparisons)
# Prior H2 references are old measurements, different isolated runner binary.
refs=['round0_baseline','round0_discard24','round0_discard24_reset25','round0_fresh_tail25','round1_fresh_tail25'];refarrays={};refindices={};refcontrols={}
for tag in refs:
    f=H/'evidence'/tag;refindices[tag]=ids(f/'observed_frame_indices.bin');ri=ids(f/'recorded_frame_indices.bin');raw=(f/'dispatch_controls.bin').read_bytes();refcontrols[tag]={s:raw[i*184:(i+1)*184]for i,s in enumerate(ri)}
    refarrays[tag]={}
    for n in ['diffuse.bin','specular.bin']:
        assert sha(f/n)==href['cases'][tag]['lobes'][n]['sha256'];refarrays[tag][n]=np.fromfile(f/n,'<f2').reshape(len(refindices[tag]),80,128,4);snapshots.append(ident(f/n))
    snapshots.extend(ident(f/n)for n in ['observed_frame_indices.bin','recorded_frame_indices.bin','dispatch_controls.bin'])
refchecks={};repeatchecks={}
for tag in reg['mode_order']:
    for ref in refs:
        common=sorted(set(frames[tag])&set(refindices[ref]));r={}
        for label,selection in [('prefix0_23',[f for f in common if f<24]),('tail25_63',[f for f in common if f>=25])]:
            if not selection:continue
            r[label]={'source_indices':selection,'184_control_exact':[controls[tag][f]==refcontrols[ref][f]for f in selection],
                'lobes':{n:metrics(arrays[tag][n][[frames[tag].index(f)for f in selection]],refarrays[ref][n][[refindices[ref].index(f)for f in selection]])for n in arrays[tag]}}
        refchecks[tag+'__old_'+ref]=r
for c in reg['cases']:
    if c['tag'].startswith('round0_'):
        right=c['tag'].replace('round0_','round1_');left=c['tag'];key=left+'__'+right if left+'__'+right in comparisons else right+'__'+left
        repeatchecks[key]=all(x['RGBA_bits_exact']for x in comparisons[key]['common_source_frame']['lobes'].values());assert repeatchecks[key]
save('reference_and_repeat_checks.json',{'old_H2_contexts_counted_as_new':False,'round_repeats':repeatchecks,'reference_checks':refchecks})
check(seal['files']);check(seal['external_sources']);check(pins);check(snapshots)
save('audit.json',{'schema':'matched-gap-full-independent-post-native-audit-v2','UTC':datetime.now(timezone.utc).isoformat(),'status':'completed_full_sdk_call_presence_diagnostic_not_solution',
 'new_native_GPU_build_calls':0,'original_V1_counts':[2,127,126,1,1],'original_V1_metadata_accepted_contexts':1,'original_V1_status':'failed_preserved',
 'remaining_V2_counts':[6,381,378,3,3],'remaining_V2_diagnostic_metadata_accepted_contexts':6,'combined_actual_counts':[8,508,504,4,4],
 'actual_SDK_warning_count':2,'cases':row,'all56_input_files_actual_indices_presence184controls_rawsizes_finiteness_authenticated':True,
 'all28_pairs2alignments2lobes_independently_recomputed_match_producer':True,'RGBA_exact_pairs':16,'RGBA_nonexact_pairs':12,'all4_withinarm_round_repeats_exact':True,
 'pair_metrics':ident(OUT/'independent_pair_metrics.json'),'reference_and_repeat_checks':ident(OUT/'reference_and_repeat_checks.json'),
 'source_pre_post_pins':pins,'evidence_and_reference_hashes':snapshots,
 'interpretation':'Two nonreset record/discard contexts match each other and old H2 discard. The six noAPI or explicitRESET25 contexts form another exact-output group; their tails match old H2 RESET25/fresh-tail. All comparable prefix0..23 outputs exact. noAPI without explicitRESET reports the known SDK warning; noAPI with RESET25 reports none. Application flags25 differ2vs3 across automatic/manual groups, so identical raw tails do not identify opaque mechanism or universal policy.',
 'chronology':'V1 rejected warning after2 completed children; original accepted1 stays. Later V2 post-observation diagnostic retention accepts only six remaining. Combined8 are actual measurements, not eight V1 zero-warning successes.',
 'qualifications':['SDK warning has no emitting-frame timestamp; next25 association is inferred.','Old H2 comparisons use distinct isolated binary/context and are descriptive.','Logical queued RR counts are submitted completed SDK-containing frames, not private shader dispatch counts.','No truth/image-quality/game trigger or general stain/wave solution established; static synthetic wave/camera/jitter scope.'],
 'quality_accepted':False,'game_run':False})
save('completion_manifest.json',{'files':[ident(p)for p in sorted(OUT.rglob('*'))if p.is_file()],'producer_changed':False,'native_GPU_calls':0})
print(json.dumps({'audit':ident(OUT/'audit.json'),'manifest':ident(OUT/'completion_manifest.json'),'counts':[8,508,504,4,4],'warnings':warnings,'exact_pairs':exactpairs}))
