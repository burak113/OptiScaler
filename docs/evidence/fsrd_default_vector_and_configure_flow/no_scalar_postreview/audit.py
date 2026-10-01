"""Independent saved-byte postreview only. No producer module, SDK, GPU, or scorer calls."""
import os
os.environ['OPENBLAS_NUM_THREADS'] = '1'
import hashlib, itertools, json, pathlib, re, struct, subprocess, sys
sys.dont_write_bytecode = True
import numpy as np

ROOT = pathlib.Path(r'F:/OptiRevelations/OptiScaler-ffxD-alpha')
HERE = pathlib.Path(__file__).resolve().parent
P = ROOT / 'tools_tmp/fsrd_clean_no_scalar_vs_explicit_defaults_preparation_20261001'
PRE = ROOT / 'tools_tmp/fsrd_clean_no_scalar_vs_explicit_defaults_prelaunch_review_20261001'
AUTH = ROOT / 'tools_tmp/fsrd_no_scalar_vs_explicit_defaults_root_authorization_20261001.json'
RECEIPT = ROOT / 'tools_tmp/fsrd_no_scalar_vs_explicit_defaults_root_tool_observations_20261001.json'
KEYS = ['api','queued','executes','signals','events','waits','completed_GPU','observed_readback_pairs']
ORDER = ['ExplicitAMD_r0','NoScalar_r0','NoScalar_r1','ExplicitAMD_r1']
LOBES = ['diffuse.bin','specular.bin']
EXPECTED_BITS = [1008981770,1065353216,1065353216,1199562752,1112014848,0]
FIXED = {
    P/'registration.json': '7c13f28ec5d96f92b34b017fc6d636732ca509aeb54dc41c17768a2d7a82cd1a',
    P/'pre_native_freeze.json': '3842b4c47ec1cd8f860a73676ce6205b4decadb9819625015407dad5e950039d',
    P/'readiness.json': '7355db4a38f159d047f2ca215bb65695431fa87d3029b56d39eab121357fa4aa',
    P/'preparation_completion_manifest.json': 'bba113b252aca4cfc479b52b1bc115a0406a90f60dc5e3eb82a245c7de611a7d',
    PRE/'review.json': 'f45336dd5d3e3ee62249dbeb60e9dd355e793737642a984c37f474357e78c5e8',
    PRE/'completion_manifest.json': 'f3b05b404b9cc5f006031274bb08d101da61c4349622d27622c128cea1fab29c',
    AUTH: 'ffa7a2e40d7b31cd0f56baed837f64c54c75182bc5b8cd57117030ab325b5e4b',
    RECEIPT: 'd303b193e3957c06890367bf814c4b74a06c9eecb1512392503d5ab6d926d064',
    P/'execution_results.json': 'd084520f4a07f09e1faec6224ac3481acb0a0f94d5449f843f84f7db0242bb12',
    P/'raw_comparisons.json': 'ddb971547ddeaf42c4854bc2b878ad1ca52654729df5921b41d6836ef907555a',
}

def path(p):
    p = pathlib.Path(p)
    return p if p.is_absolute() else ROOT/p

def pin(p):
    p = path(p)
    b = p.read_bytes()
    return dict(path=str(p),bytes=len(b),sha256=hashlib.sha256(b).hexdigest())

def read(p):
    def unique(pairs):
        d = {}
        for k,v in pairs:
            assert k not in d, ('duplicate JSON key',p,k)
            d[k] = v
        return d
    return json.loads(path(p).read_text(encoding='utf-8-sig'), object_pairs_hook=unique)

def save(n,d):
    with (HERE/n).open('x',encoding='utf-8',newline='\n') as f:
        json.dump(d,f,indent=2,allow_nan=False); f.write('\n')

all_verified = {}
def verify(r):
    got = pin(r['path'])
    assert got['bytes']==r['bytes'] and got['sha256']==r['sha256'], ('pin mismatch',r,got)
    k = str(path(r['path'])).lower()
    if k in all_verified:
        assert all_verified[k] == got, ('conflicting claims',r)
    all_verified[k] = got
    return got

def nested_pins(d):
    if isinstance(d,dict):
        if all(k in d for k in ('path','bytes','sha256')) and d['sha256'] is not None:
            verify(d)
        for v in d.values(): nested_pins(v)
    elif isinstance(d,list):
        for v in d: nested_pins(v)

def seal(p,owned,external,expected):
    d = read(p)
    assert (len(d[owned]),len(d[external])) == expected
    assert d.get('self_excluded',d.get('self_entry_excluded')) is True
    records = d[owned]+d[external]
    assert all(path(r['path']) != path(p) for r in records)
    for r in records: verify(r)
    return dict(manifest=pin(p),owned_records=len(d[owned]),external_records=len(d[external]),
                unique_listed_paths=len({str(path(r['path'])).lower() for r in records}),all_exact=True)

for p,s in FIXED.items():
    got = pin(p); assert got['sha256']==s
    verify(got)
reg,run,raw,auth,receipt = [read(p) for p in [P/'registration.json',P/'execution_results.json',P/'raw_comparisons.json',AUTH,RECEIPT]]
assert reg['fixed_order']==ORDER and [c['tuning'] for c in reg['cases']]==[1,0,0,1]
assert auth['status']=='ROOT_AUTHORIZED_FOUR_FRESH_NO_SCALAR_VS_EXPLICIT_DEFAULTS_CONTEXTS_ONCE'
assert auth['fixed_order']==ORDER and auth['absent_runtime_paths']==63 and auth['no_retries'] is True
assert not auth['composition_GPU_authorized'] and not auth['quality_accepted']
assert read(PRE/'review.json')['blocking_findings']==[]
assert read(PRE/'review.json')['status']=='READY_FOR_ROOT_FOUR_NO_SCALAR_VS_EXPLICIT_DEFAULTS_NATIVE_AUTHORIZATION'
preparation = seal(P/'preparation_completion_manifest.json','records','external_sources',(77,46))
freeze = seal(P/'pre_native_freeze.json','files','external_sources',(75,46))
prelaunch = seal(PRE/'completion_manifest.json','files','external_records',(18,28))
inheritance = [seal(reg[k]['path'],o,'external_records',counts) for k,o,counts in [
    ('completed_vector_native_seal','files',(11,39)),
    ('completed_vector_composition_seal','files',(15,30)),
    ('actual_default_query_seal','owned',(8,13))]]
for r in (reg,auth,receipt,run): nested_pins(r)
assert receipt['generator']['sha256']=='9046f2f575ae2f2cad8cdb5f35cefe08015c6e2225590f4a7f41216df7a450c8'
before = dict(all_verified)
head_before = subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
save('identity_before.json',dict(HEAD=head_before,preparation=preparation,freeze=freeze,prelaunch=prelaunch,
    inherited_seals=inheritance,total_unique_verified_files=len(before),
    inheritance='Listed identities expanded and verified once; manifests retained as compact authority instead of duplicating pin tables.',
    all_exact=True,actual_review_calls=dict(native=0,GPU=0,build=0,scorer=0,producer_analyzer=0,CPU_law_reruns=0)))

# Reconstruct the one permitted scalar-file source hunk; retain the original B342 lifecycle.
cpp = path(reg['source_reference']['path']).read_bytes()
original_path = ROOT/'OptiScaler/shaders/shader_tools/tests/fsrd_rr_runner.cpp'
original = original_path.read_bytes()
old = b'        const float values[]={.1f,.5f,.5f,40000.f,40.f,.5f};\r\n'
new = (b'        float values[6]{};\r\n'
       b'        std::ifstream valuesFile(std::filesystem::path(argv[1]).parent_path()/"tuning_values.bin",std::ios::binary);\r\n'
       b'        valuesFile.read(reinterpret_cast<char*>(values),sizeof(values));\r\n'
       b'        if(!valuesFile||valuesFile.peek()!=std::char_traits<char>::eof()) throw std::runtime_error("tuning_values.bin must contain exactly six float32 values");\r\n'
       b'        for(float value:values) if(!std::isfinite(value)) throw std::runtime_error("nonfinite tuning value");\r\n')
assert cpp.count(new)==1 and original.count(old)==1 and cpp.replace(new,old)==original
assert hashlib.sha256(original).hexdigest()=='f6cfbecc4704d7f4f891f5c2ae88baf69546a316a9738ed03da0413d6ef0d077'
assert reg['runner']['sha256']=='bf9774a1e83855590f5b254163953898690431a73b859235e41bd79121ac5ebf'
assert reg['provider']['sha256']=='48f1e5888ba6a0a3d59a98b9751e37c392b0f7b8c223d0082d5c1f40642879d3'
text = cpp.decode()
assert text.index('if(tuning)') < text.index('float values[6]') < text.index('api.Configure(&context,&c.header)')
assert text.index('ff(api.Dispatch(&context') < text.index('queue->ExecuteCommandLists(1,lists)') < text.index('queue->Signal(fence.Get(),frame+1)')
assert text.index('WaitForSingleObject(event,60000)') < text.index('"readback"') < text.index('ff(api.DestroyContext(&context') < text.index('std::cout<<"dispatches="')
assert 'auto versionResult=api.Query(&context,&version.header);' in text
assert 'ff(api.Configure(nullptr,&logging.header),"global debug")' in text
assert text.count('api.Query(')==1 and text.count('api.Dispatch(')==1

assert run['contexts_created_confirmed']==run['contexts_completed_confirmed']==run['executor_invocations']==run['accepted_contexts']==4
assert run['totals_unknown_children']==0 and run['counts']==dict.fromkeys(KEYS,256)
assert not run['quality_accepted'] and not run['game_run'] and run['composition_GPU_jobs']==0
assert [j['tag'] for j in run['jobs']]==ORDER
assert receipt['metadata_errors']==[] and receipt['accepted_complete_evidence'] is True
assert receipt['actual_new_source_counts']==dict.fromkeys(KEYS,256)
assert receipt['actual_new_counts_exact'] is True and receipt['new_totals_unknown'] is False
assert receipt['informational_provider_version_Query_actual_return_codes']==[6]*4
assert receipt['informational_provider_version_Query_actual_successes']==0
assert receipt['scalar_Configure_calls_source_derived']==receipt['scalar_Configure_success_lowerbound']==12
assert receipt['global_debug_Configure_calls_source_derived']==4
assert receipt['default_scalar_Query_during_contrast']==0
assert [r['chunk'] for r in receipt['tool_observations']]==['8e7ae8','978ce5']
assert all(r['exit_code']==0 for r in receipt['tool_observations'])
assert len(receipt['actual_child_artifacts'])==32

footer = re.compile(rb'^dispatches=(\d+) validation_errors=(\d+) validation_warnings=(\d+) sdk_errors=(\d+) sdk_warnings=(\d+)\r?\n$',re.M)
provider = re.compile(rb'^provider=.* version_query_result=(\d+) requested_api=(\d+)\r?\n$',re.M)
arrays,contexts,runtime = {},[],[]
control_common = None
for c,j,rr in zip(reg['cases'],run['jobs'],receipt['per_context']):
    assert c['tag']==j['tag']==rr['tag'] and j['accepted'] is True and rr['accepted'] is True and rr['errors']==[]
    folder = path(c['job']).parent
    joblines = path(c['job']).read_text().splitlines()
    assert len(joblines)==9
    tokens = re.findall(r'"[^"]*"|\S+',joblines[0])
    assert len(tokens)==9 and [int(v) for v in tokens[:8]]==[128,80,64,2,32,0,c['tuning'],0]
    for line,inp,fmt,frames in zip(joblines[1:8],c['inputs'],c['formats'],c['upload_counts']):
        vals=re.findall(r'"[^"]*"|\S+',line)
        assert len(vals)==3 and path(vals[0].strip('"'))==path(inp['path']) and [int(v) for v in vals[1:]]==[fmt,frames]
    assert c['formats']==[41,10,24,28,28,10,10] and c['upload_counts']==[1]*7
    assert not (folder/'camera.txt').exists() and not c['camera_override_present']
    side=path(c['tuning_sidecar']['path']).read_bytes()
    assert len(side)==24 and list(struct.unpack('<6I',side))==EXPECTED_BITS
    assert c['sidecar_native_consumed']==bool(c['tuning']) and c['NoScalar_active_internal_settings_known'] is False
    attempt=read(folder/'executor_attempt.json'); stored=read(folder/'resource_guard.json'); g=j['guard']; work=read(folder/'native_work_accounting.json')
    assert attempt==g['executor_launch_attempt'] and work==j['work']==rr['physical_work']
    assert all(attempt[k] is True for k in ['invocation_started','fresh_runtime_files_verified_absent','case_command_matches','before_guard_call_checkpointed'])
    assert attempt['command']==c['command']==stored['args']==g['args']
    assert len(attempt['preflight']['files'])==14 and attempt['preflight']['all_absent'] is True
    assert all(x['absent'] is True and path(x['path']).parent==folder for x in attempt['preflight']['files'])
    load=g['guard_load_evidence']
    assert load['authority']=='direct_owned_guard_return' and load['errors']==[] and load['stored_guard_valid'] and load['returned_guard_valid']
    assert load['stored_guard_claim']==stored
    assert {k:g[k] for k in stored}==stored
    assert g['status']=='completed' and type(g['child_pid']) is int and g['child_pid']>0 and g['returncode']==0
    assert not g['terminated_owned_child'] and g['termination_reason'] is None and j['guard_error'] is None
    assert (g['timeout_seconds'],g['maximum_working_set_bytes'],g['minimum_available_memory_bytes'],g['sample_interval_seconds'])==(240,2*1024**3,1024**3,.2)
    assert g['initial_available_bytes']>=1024**3 and g['minimum_observed_available_bytes']>=1024**3 and g['peak_observed_working_set_bytes']<=2*1024**3
    assert g['elapsed_seconds']<240
    temp=path(c['child_TEMP_TMP']); assert temp.is_dir() and temp.drive.lower()=='f:'
    assert temp.parent==P/'execution_TEMP' and temp.name==c['tag']
    assert attempt['child_environment']==j['child_environment']==dict(TMP=str(temp),TEMP=str(temp))
    stdout=(folder/'stdout.log').read_bytes(); stderr=(folder/'stderr.log').read_bytes()
    ft=footer.findall(stdout); pv=provider.findall(stdout)
    assert ft==[(b'64',b'0',b'0',b'0',b'0')] and not footer.findall(stderr) and stderr==b''
    assert len(stdout.splitlines())==4 and stdout.splitlines()[0].startswith(b'adapter=') and stdout.splitlines()[0].endswith(b'debug_layer=1')
    assert pv==[(b'6',b'4202496')]
    assert work['counts']==dict.fromkeys(KEYS,64) and work['exact_totals'] is True and work['totals_unknown'] is False
    assert work['created_context_confirmed'] and work['completed_context_confirmed'] and work['evidence_disagreements']==[]
    assert work['successful_not_submitted_exact']==work['discarded_or_omitted_exact']==0
    assert rr['informational_provider_version_Query_return_code_actual']==6 and rr['informational_provider_version_Query_successes_actual']==0
    source_nonrr=dict(scalar_Configure=6*c['tuning'],global_debug_Configure=1,informational_version_Query=1,default_scalar_Query=0)
    assert j['source_qualified_nonRR_calls_if_complete']==source_nonrr
    assert rr['source_derived_after_fullfooter']['scalar_Configure']==6*c['tuning']
    controls=(folder/'dispatch_controls.bin').read_bytes()
    assert controls==path(c['expected_applied_controls']['path']).read_bytes() and len(controls)==64*184
    assert [struct.unpack_from('<II',controls,184*i) for i in range(64)]==[(i,3 if i==0 else 2) for i in range(64)]
    assert c['source_frame_indices']==list(range(64))
    if control_common is None: control_common=controls
    assert controls==control_common
    arrays[c['tag']]={}
    alpha={}
    for n in LOBES:
        b=(folder/n).read_bytes(); assert len(b)==64*80*128*4*2
        arr=np.frombuffer(b,'<f2').reshape(64,80,128,4)
        assert np.isfinite(arr[...,:3]).all() and np.all(arr.view('<u2')[...,3]==0)
        arrays[c['tag']][n]=arr; alpha[n]=dict(all_positive_zero_bits=True,pixels=64*80*128)
        assert j['outputs'][n]['observed_source_frame_indices']==list(range(64)) and j['outputs'][n]['RGB_finite'] is True
    names=['resource_guard.json','stdout.log','stderr.log','dispatch_controls.bin','diffuse.bin','specular.bin','native_work_accounting.json','executor_attempt.json']
    runtime += [pin(folder/n) for n in names]
    absent=[n for n in ['stage_events.jsonl','recorded_frame_indices.bin','queued_frame_indices.bin','completed_frame_indices.bin','observed_frame_indices.bin','output_presence.bin'] if not (folder/n).exists()]
    assert len(absent)==6
    contexts.append(dict(tag=c['tag'],tuning=c['tuning'],created=1,successful_Destroy=1,counts=dict.fromkeys(KEYS,64),accepted=True,totals_unknown=False,
        authority='Pinned unique64 stdout terminal after completed serial loop and successful DestroyContext; current-child guard and actual readback bytes independently checked.',
        child_pid=g['child_pid'],guard_direct_stored_equal=True,guard_resource_bounds_pass=True,TEMP_TMP=str(temp),
        diagnostics=dict(D3D_errors=0,D3D_warnings=0,SDK_callback_errors=0,SDK_callback_warnings=0,stderr_bytes=0),
        source_qualified_nonRR=source_nonrr,provider_version_Query_actual_rc=6,provider_version_Query_success=0,
        control_records=64,controls_bytes=11776,controls_exact=True,flags=[3]+[2]*63,source_frames=list(range(64)),alpha=alpha,
        absent_B342_nonemitted_journals=absent))

runtime += [pin(P/'execution_results.json'),pin(P/'raw_comparisons.json')]
assert len(runtime)==34 and {str(path(r['path'])).lower() for r in runtime[:-2]}=={str(path(r['path'])).lower() for r in receipt['actual_child_artifacts']}
save('runtime_manifest.json',dict(records=runtime,total_records=34,actual_child_records=32,self_excluded=True,read_only_source_artifacts=True))

def metric(a,b):
    # Same frozen metric formula, independently implemented against saved buffers only.
    abits=a.view('<u2'); bbits=b.view('<u2')
    delta=a[...,:3].astype(np.float64)-b[...,:3].astype(np.float64)
    return dict(RGBA_bits_exact=bool(np.array_equal(abits,bbits)),RGB_bits_exact=bool(np.array_equal(abits[...,:3],bbits[...,:3])),
        alpha_bits_exact=bool(np.array_equal(abits[...,3],bbits[...,3])),RGB_RMS=float(np.sqrt(np.mean(delta*delta))),
        RGB_max_abs=float(np.max(np.abs(delta))),RGB_per_source_frame_RMS=np.sqrt(np.mean(delta*delta,axis=(1,2,3))).tolist(),
        RGB_per_source_frame_bits_exact=[bool(np.array_equal(abits[i,...,:3],bbits[i,...,:3])) for i in range(64)])

def changed(a,b,m):
    unequal=a.view('<u2')!=b.view('<u2'); ids=np.flatnonzero(~np.array(m['RGB_per_source_frame_bits_exact']))
    return dict(first_changed_source_frame=int(ids[0]) if len(ids) else None,last_changed_source_frame=int(ids[-1]) if len(ids) else None,
        changed_source_frames=ids.tolist(),changed_RGB_component_counts=[int(unequal[...,i].sum()) for i in range(3)],
        changed_alpha_components=int(unequal[...,3].sum()))

assert raw['execution_sha256']==pin(P/'execution_results.json')['sha256'] and raw['source_frame_indices']==list(range(64))
assert raw['pair_count']==6 and raw['historical_pair_count']==16 and raw['lobe_comparison_count']==12
assert raw['quality_scores'] is None and raw['composition_results'] is None and raw['quality_accepted'] is False and raw['new_native_GPU']==0
pair_records=[]
for (a,b),reported,summary in zip(itertools.combinations(ORDER,2),raw['pairs'],receipt['raw_pair_summaries']):
    assert reported['left']==summary['left']==a and reported['right']==summary['right']==b
    assert reported['same_actual_controls184'] is True
    entry=dict(left=a,right=b,kind=reported['kind'],lobes={},changed={})
    for n in LOBES:
        m=metric(arrays[a][n],arrays[b][n]); assert m==reported['lobes'][n]
        assert {k:m[k] for k in summary['lobes'][n]}==summary['lobes'][n]
        entry['lobes'][n]=m;entry['changed'][n]=changed(arrays[a][n],arrays[b][n],m)
    pair_records.append(entry)
historical=[]
hist_prep=ROOT/'tools_tmp/fsrd_clean_fork_vs_sdk_defaults_preparation_20261001'
oldreg=read(hist_prep/'registration.json')
assert pin(path(oldreg['runner']['path']))['sha256']==reg['runner']['sha256']
old_cases={c['tag']:c for c in oldreg['cases']}
cursor=0
for old in reg['historical_completed_vector_references']:
    tag=old['tag']; oldc=old_cases[tag]
    assert [i['sha256'] for i in oldc['inputs']]==[i['sha256'] for i in reg['cases'][0]['inputs']]
    old_controls=(path(oldc['job']).parent/'dispatch_controls.bin').read_bytes(); assert old_controls==control_common
    old_outputs={n:np.frombuffer(path(old['outputs'][n]['path']).read_bytes(),'<f2').reshape(64,80,128,4) for n in LOBES}
    for c in reg['cases']:
        reported=raw['historical_completed_vector_comparisons'][cursor]; summary=receipt['historical_completed_vector_cohort_summaries'][cursor]; cursor+=1
        assert reported['current']==summary['left']==c['tag'] and reported['historical']==summary['right']==tag
        assert reported['historical_scalar_calls']==6 and reported['kind']=='completed_vector_historical_cohort_qualified'
        entry=dict(current=c['tag'],historical=tag,historical_scalar_vector=old['tuning_vector'],lobes={},changed={})
        for n in LOBES:
            m=metric(arrays[c['tag']][n],old_outputs[n]); assert m==reported['lobes'][n]
            assert {k:m[k] for k in summary['lobes'][n]}==summary['lobes'][n]
            entry['lobes'][n]=m;entry['changed'][n]=changed(arrays[c['tag']][n],old_outputs[n],m)
        historical.append(entry)
assert cursor==16
save('independent_raw_comparisons.json',dict(schema='saved-byte-independent-44-lobe-metrics',current_pairs=pair_records,historical_pairs=historical,
    source_frames=list(range(64)),metric_dictionary_count=44,producer_and_root_summary_exact=True,
    historical_qualification='Same pinned common EXE, seven input bytes and actual184 controls verified. Separate fresh process/context/time cohort; old Fork vector differs, and NoScalar active state is unknown.',
    no_model_no_quality_score_no_producer_analyzer=True))

after={k:pin(v['path']) for k,v in before.items()}
assert after==before
head_after=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
assert head_after==head_before
save('identity_after.json',dict(HEAD=head_after,total_unique_verified_files=len(after),all_exact_to_before=True,changed_files=[],
    preparation_unique_files=123,prelaunch_listed_records=46,inherited_native_listed_records=50,inherited_composition_listed_records=45,inherited_query_listed_records=21,
    audit_scope='Independent reads and saved raw arithmetic only; all producer/preparation/prelaunch/root/source identities checked before and after.'))
assert all(not m['RGBA_bits_exact'] and not m['RGB_bits_exact'] and m['alpha_bits_exact'] for e in pair_records+historical for m in e['lobes'].values())
all_current_rms=[m['RGB_RMS'] for e in pair_records for m in e['lobes'].values()]
save('review.json',dict(status='PASSED_NO_SCALAR_VS_EXPLICIT_DEFAULTS_NATIVE_RAW_EVIDENCE_REVIEW',blocking_findings=[],
    owned_folder=str(HERE),actual_review_calls=dict(native=0,GPU=0,build=0,scorer=0,producer_analyzer=0,CPU_law_reruns=0),
    root_authorization=pin(AUTH),root_receipt=pin(RECEIPT),root_receipt_generator=receipt['generator'],
    preparation=preparation,freeze=freeze,prelaunch=prelaunch,inherited_seal_verifications=inheritance,
    source_authority=dict(source=reg['source_reference'],EXE=reg['runner'],provider=reg['provider'],inverse_original_B342_exact=True,
        original_source=pin(original_path),production_source=reg['production_CPP_pin'],HEAD_before=head_before,HEAD_after=head_after),
    actual_new=dict(contexts_created=4,contexts_successfully_destroyed=4,contexts_completed=4,accepted_contexts=4,unknown_contexts=0,
        counts=dict.fromkeys(KEYS,256),scalar_Configure_successes_sourcequalified=12,global_debug_Configure_successes_sourcequalified=4,
        informational_provider_version_Query_calls_returns_sourcequalified=4,informational_provider_version_Query_actual_rcs=[6]*4,
        informational_provider_version_Query_successes=0,default_scalar_Query_calls=0,composition_GPU=0,quality_accepted=False),
    contexts=contexts,root_tool_observations=receipt['tool_observations'],
    metrics=dict(current_pairs=6,current_lobe_metrics=12,historical_pairs=16,historical_lobe_metrics=32,total_dictionary_count=44,
        all_recomputed_exact_to_producer=True,all_root_summaries_exact=True,all_current_full64_RGB_RGBA_pairs_nonexact=True,
        all_historical_full64_RGB_RGBA_pairs_nonexact=True,all_alpha_pairs_exact_positive_zero=True,
        current_RGB_RMS_min=min(all_current_rms),current_RGB_RMS_max=max(all_current_rms),current_RGB_max_abs=.0009765625,
        detailed_metrics=pin(HERE/'independent_raw_comparisons.json')),
    root_cumulative_totals=receipt['cumulative_totals'],root_prior_totals_qualification='Prior totals carried from frozen root receipt; only new4/256 independently reconstructed here.',
    conclusions=[
        'Both ExplicitAMD repeats and NoScalar repeats differ in raw RGB. Between-policy differences are of the same observed scale as within-policy differences; this cohort does not isolate a scalar-Configure policy effect.',
        'No current output matches any historical full64 lobe bit for bit. Historical comparisons preserve process/time-cohort and scalar-vector differences.',
        'NoScalar does not consume the24-byte sidecar. Its active private internal settings remain unknown; absence of a large raw contrast does not establish equivalence of internal settings.',
        'Every applied184-byte packet is exact across four current contexts and historical cohorts; successful64 footer after Destroy supports physical source counts independently of metadata acceptance.',
        'Informational provider-version Query rc6 is retained as non-success, not a default-scalar Query failure. The previous measured six successful default Queries are a separate context.'],
    limits=[
        'Original B342 has no per-frame API journal/GetCompletedValue log; complete footer source reachability, fresh positive child guard, and full saved readbacks establish this completed cohort. Missing-footer partial-work limitations remain inherited.',
        'Source-qualified Configure/caller RR/queue stage counts are not an independent private SDK shader-dispatch count. No claim about provider internal GPU activity or private settings.',
        'Explicit six queried values versus no scalar Configure is a constructed clean-fixture policy contrast, not whole production UseAmdDefaults flow: validation2 versus Release0, key7/proxy/cache flow remain different.',
        'Raw demodulated lobes are not composed color or a physical truth oracle. No new composition, quality score, settings change, production fix, game outcome, or parameter causality measured.',
        'Protected preparation/prelaunch/source/root artifacts and historical failures were read unchanged. Root receipt is documentary tool observation; actual child logs/guards/buffers are separately pinned.']))
print(json.dumps(dict(status='PASS',contexts=4,RR_API=256,queued=256,current_pairs=6,historical_pairs=16,lobe_metrics=44,
    total_unique_before_after_files=len(before),all_metrics_exact=True,within_policy_repeats_bitexact=False,native_GPU_build_scorer_review_calls=0)))
