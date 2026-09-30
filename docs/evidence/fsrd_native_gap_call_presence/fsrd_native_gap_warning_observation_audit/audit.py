"""Independent CPU-only audit of preserved first two native gap controls."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,re,struct,shlex,itertools
import numpy as np
ROOT=Path('F:/OptiRevelations/OptiScaler-ffxD-alpha/tools_tmp')
P=ROOT/'fsrd_native_gap_cpu_record_control_20260930';H=ROOT/'fsrd_native_discarded_recording_diagnostic_20260930'
OUT=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def ident(p):p=Path(p);return {'path':str(p),'bytes':p.stat().st_size,'sha256':sha(p)}
def load(p):return json.loads(Path(p).read_text())
def save(n,v):
    with(OUT/n).open('x',encoding='utf-8',newline='\n')as f:json.dump(v,f,indent=2,allow_nan=False);f.write('\n')
def check(rs):
    for r in rs:assert ident(r['path'])==r,r['path']
def ints(p):b=Path(p).read_bytes();assert len(b)%4==0;return list(struct.unpack('<'+'I'*(len(b)//4),b))
pre=load(P/'pre_native_freeze.json');check(pre['files']);check(pre['external_sources'])
reg=load(P/'registration.json');rep=load(P/'evidence/results.json');hrep=load(H/'evidence/results.json')
assert rep['status']=='failed_preserved' and rep['error']=='AssertionError: ordinary D3D12/SDK diagnostics'
assert list(rep['cases'])==['round0_record_discard24','round0_no_api24']
pins=[ident(P/'evidence/results.json'),ident(H/'evidence/results.json'),ident(P/'registration.json'),ident(P/'pre_native_freeze.json')]
cases={c['tag']:c for c in reg['cases']};arrays={};frames={};packets={};new=[];snapshot=[];total=np.zeros(4,dtype=int)
for tag,item in rep['cases'].items():
    folder=P/'evidence'/tag;c=cases[tag];noapi=c['no_api_frame']==24
    stdout=(folder/'stdout.log').read_text();stderr=(folder/'stderr.log').read_text()
    match=re.search(r'RR_recordings=(\d+) queued_RR_dispatches=(\d+) discarded_RR_recordings=(\d+) validation_errors=(\d+) validation_warnings=(\d+) sdk_errors=(\d+) sdk_warnings=(\d+) no_API_omissions=(\d+)',stdout)
    assert match;footer=list(map(int,match.groups()))
    assert footer==([63,63,0,0,0,0,1,1]if noapi else[64,63,1,0,0,0,0,0])
    assert stderr==('SDK: Frame index jump detected. Resetting...\n'if noapi else'')
    guard=load(folder/'resource_guard.json');assert guard==item['guard']
    assert guard['status']=='completed' and guard['returncode']==0 and not guard['terminated_owned_child']
    assert [guard[k]for k in ['timeout_seconds','maximum_working_set_bytes','minimum_available_memory_bytes']]==[240,2147483648,1073741824]
    ri=ints(folder/'recorded_frame_indices.bin');oi=ints(folder/'observed_frame_indices.bin');ni=ints(folder/'omitted_API_frame_indices.bin')
    assert ri==c['source_frame_indices'] and oi==c['observed_frame_indices'] and ni==c['omitted_API_frame_indices']
    assert oi==[f for f in range(64)if f!=24] and (folder/'output_presence.bin').read_bytes()==bytes(c['output_presence_mask'])
    control=(folder/'dispatch_controls.bin').read_bytes();assert control==(folder/'expected_applied_dispatch_controls.bin').read_bytes()
    packets[tag]={f:control[i*184:(i+1)*184]for i,f in enumerate(ri)}
    for f,b in packets[tag].items():assert struct.unpack_from('<IIII',b)==(f,3 if f==0 else 2,128,80)
    queued=b''.join(packets[tag][f]for f in oi)
    assert queued==(folder/'expected_queued_dispatch_controls.bin').read_bytes()
    if noapi:assert not(folder/'queued_dispatch_controls.bin').exists()
    else:assert (folder/'queued_dispatch_controls.bin').read_bytes()==queued
    (OUT/(tag+'_derived_queued_controls.bin')).write_bytes(queued)
    for inp in c['inputs']:assert ident(inp['path'])=={k:inp[k]for k in ['path','bytes','sha256']}
    assert [i['uploads']for i in c['inputs']]==[1,1,1,1,1,64,64]
    rows=[shlex.split(x)for x in(folder/'job.txt').read_text().splitlines()]
    assert list(map(int,rows[0][:8]))==[128,80,64,2,32,0,1,0]
    assert Path(rows[0][8])==Path(reg['dll']['path'])
    assert sha(reg['dll']['path'])==reg['dll']['sha256']
    assert 'provider=unavailable from direct effect DLL id=0 version_query_result=6' in stdout
    assert 'debug_layer=1' in stdout
    arrays[tag]={}
    for name in ['diffuse.bin','specular.bin']:
        p=folder/name;assert p.stat().st_size==63*80*128*4*2
        a=np.fromfile(p,'<f2').reshape(63,80,128,4);assert np.isfinite(a).all()
        arrays[tag][name]=a
        if not noapi:assert sha(p)==item['lobes'][name]['sha256']
    accounting=load(folder/'native_work_accounting.json');assert accounting==item['native_work_accounting']
    assert not accounting['totals_unknown'] and accounting['completed_native_context_final_marker']
    assert not accounting['evidence_disagreements']
    expected=[footer[0],footer[1],footer[2],footer[7]]
    assert [accounting[k]for k in ['successful_API_RR_recordings_confirmed','queued_RR_dispatches_confirmed_completed','discarded_API_RR_recordings_confirmed','no_API_omissions_confirmed']]==expected
    total+=expected;frames[tag]=oi
    snapshot.extend(ident(p)for p in sorted(folder.iterdir())if p.is_file())
    new.append({'tag':tag,'footer':footer,'metadata_accepted':item['metadata_accepted'],'native_completed':True,'guard':guard,
        'derived_queued_controls':ident(OUT/(tag+'_derived_queued_controls.bin')),'stderr_literal':stderr,'raw_lobes':[ident(folder/n)for n in arrays[tag]],
        'SDK_warning_is_not_D3D_warning_or_error':True,'sourceframe24_absent_output_no_fabrication':True})
assert total.tolist()==[127,126,1,1]
assert [rep[k]for k in ['completed_native_contexts','successful_API_RR_recordings','queued_RR_dispatches','discarded_RR_recordings','no_API_omissions','metadata_accepted_native_contexts']]==[2,127,126,1,1,1]
assert packets['round0_record_discard24']|{} # nonempty
assert all(packets['round0_record_discard24'][f]==packets['round0_no_api24'][f]for f in frames['round0_no_api24'])
assert [sha(cases['round0_record_discard24']['inputs'][i]['path'])for i in range(7)]==[sha(cases['round0_no_api24']['inputs'][i]['path'])for i in range(7)]
for tag in cases:
    if tag not in rep['cases']:assert not(P/'evidence'/tag/'resource_guard.json').exists() and not(P/'evidence'/tag/'diffuse.bin').exists()
for tag in ['round0_baseline','round0_discard24','round0_discard24_reset25','round0_fresh_tail25','round1_fresh_tail25']:
    folder=H/'evidence'/tag;info=hrep['cases'][tag];frames[tag]=ints(folder/'observed_frame_indices.bin')
    ri=ints(folder/'recorded_frame_indices.bin');b=(folder/'dispatch_controls.bin').read_bytes();packets[tag]={f:b[i*184:(i+1)*184]for i,f in enumerate(ri)}
    arrays[tag]={}
    for n in ['diffuse.bin','specular.bin']:
        assert sha(folder/n)==info['lobes'][n]['sha256'];a=np.fromfile(folder/n,'<f2').reshape(len(frames[tag]),80,128,4)
        assert np.isfinite(a).all();arrays[tag][n]=a;snapshot.append(ident(folder/n))
    snapshot.extend(ident(folder/n)for n in ['observed_frame_indices.bin','recorded_frame_indices.bin','dispatch_controls.bin'])
def metric(a,b,ids):
    result={'RGBA_bits_exact':np.array_equal(a.view('<u2'),b.view('<u2')),'RGB_bits_exact':np.array_equal(a[...,:3].view('<u2'),b[...,:3].view('<u2'))}
    for label,s in [('RGB',slice(0,3)),('alpha',slice(3,4)),('RGBA',slice(None))]:
        d=a[...,s].astype('float64')-b[...,s].astype('float64');per=np.sqrt(np.mean(d*d,axis=(1,2,3)));nonzero=np.flatnonzero(per)
        result[label]={'RMS':float(np.sqrt(np.mean(d*d))),'max_abs':float(np.max(np.abs(d))), 'changed_fraction':float(np.mean(d!=0)),
            'first_changed_source_frame':ids[int(nonzero[0])]if len(nonzero)else None,'per_source_frame_RMS':dict(zip(map(str,ids),map(float,per))),
            'max_RMS_source_frame':ids[int(np.argmax(per))]if len(nonzero)else None}
    return result
comparisons={}
lefts=list(rep['cases'])
pairs=[(lefts[0],lefts[1])]+[(t,r)for t in lefts for r in arrays if r not in lefts]
for l,r in pairs:
    common=sorted(set(frames[l])&set(frames[r]));entry={}
    for label,ids in [('all_common_source',common),('prefix0_23',[f for f in common if f<24]),('tail25_63',[f for f in common if f>=25])]:
        if not ids:continue
        ia=[frames[l].index(f)for f in ids];ib=[frames[r].index(f)for f in ids]
        entry[label]={'source_indices':ids,'actual_control_184_equality_by_source':{str(f):packets[l][f]==packets[r][f]for f in ids},
            'lobes':{n:metric(arrays[l][n][ia],arrays[r][n][ib],ids)for n in arrays[l]}}
    comparisons[l+'__'+r]=entry
save('independent_comparisons.json',comparisons)
check(pre['files']);check(pre['external_sources']);check(pins);check(snapshot)
report={'schema':'matched-gap-first-warning-independent-audit-v1','UTC':datetime.now(timezone.utc).isoformat(),'status':'completed_preserved_first_two_warning_observation_not_solution',
    'actual_counts':{'completed_contexts':2,'successful_API_records':127,'queued_completed_RR':126,'SDK_discard':1,'noAPI_omission':1,'metadata_accepted_contexts':1},
    'new_native_GPU_build_calls':0,'source_pre_and_post_pins':pins,'all_current_evidence_and_reference_hashes':snapshot,'cases':new,
    'remaining_six_have_not_run':True,'matched_all7_inputs_and_actual_queued_184controls':True,'comparisons':ident(OUT/'independent_comparisons.json'),
    'warning_scope':'Actual noAPI24 arm reports exactly one SDK warning: Frame index jump detected. Resetting... . This is an observed diagnostic, not an SDK error or D3D warning. Applied flags/source indices remain byte-authenticated; warning indicates SDK may change effective history despite identical queued application controls. No warning timestamp pinpoints its exact emitting API call in retained stderr.',
    'causal_qualification':'Successful record24/discard versus noAPI24 contrasts API presence while queued GPU inputs match. Warning/internal reset is a plausible measured mediator of any tail difference, not evidence of a universal SDK contract, game trigger, visual quality, or stain cause. H2 comparisons use different isolated runner binary and context and are descriptive.',
    'report_rejection_does_not_erase_completed_work':True,'quality_accepted':False,'general_fix':False}
save('audit.json',report)
save('completion_manifest.json',{'files':[ident(p)for p in sorted(OUT.rglob('*'))if p.is_file()],'producer_files_changed':False,'native_GPU_calls':0})
print(json.dumps({'audit':ident(OUT/'audit.json'),'manifest':ident(OUT/'completion_manifest.json'), 'pair_tail_summary':{key:{n:e['tail25_63']['lobes'][n]['RGB']['RMS']for n in arrays[lefts[0]]}for key,e in comparisons.items()}}))
