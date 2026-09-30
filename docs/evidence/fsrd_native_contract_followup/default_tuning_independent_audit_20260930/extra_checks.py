"""Read-only source derivation, retry attestation and descriptive window metrics."""
import ast,itertools
case=STUDY.parent
derivation=json.loads((case/'source_derivation.json').read_text())
assert sha(case/'source_derivation.json')==r['source_derivation_sha256']
assert sha(case/'native_helper.py')==r['native_helper_sha256']==derivation['generated_helper_sha256']
for key,path in [('parent_sha256',Path(derivation['parent_script'])),('function_parent_sha256',Path(derivation['function_parent'])),('generator_sha256',case/'generate.py'),('generated_script_sha256',case/'analyze.py')]:
    assert sha(path)==derivation[key]
tree=ast.parse((case/'generate.py').read_text())
changes=[ast.literal_eval(n.value) for n in ast.walk(tree) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='changes' for t in n.targets)]
assert len(changes)==2
text=Path(derivation['function_parent']).read_text()
node=next(n for n in ast.parse(text).body if isinstance(n,ast.FunctionDef) and n.name=='run_amd')
helper=ast.get_source_segment(text,node)
for old,new in changes[0]:
    assert helper.count(old)==1;helper=helper.replace(old,new,1)
prefix='from pathlib import Path\nfrom probe_fsrd_additive_split import DLL,write_texture,save_json\nimport numpy as np\nimport re,json,hashlib,subprocess\n'
assert (case/'native_helper.py').read_text()==prefix+helper+'\n'
text=Path(derivation['parent_script']).read_text()
for old,new in changes[1]:
    assert text.count(old)==1;text=text.replace(old,new,1)
assert text==(case/'analyze.py').read_text()
retry=json.loads((case/'retry_derivation.json').read_text())
assert sha(case/'generate.py')==retry['new_generator_sha256']
oldcase=ROOT/'tools_tmp/default_tuning_context_repeat_20260930'
assert sha(oldcase/'generate.py')==retry['previous_generator_sha256']
assert (case/'generate.py').read_text()==(oldcase/'generate.py').read_text().replace("hp.write_text('from probe_fsrd_additive_split", "hp.write_text('from pathlib import Path\\nfrom probe_fsrd_additive_split",1)
failure=Path(retry['previous_failure_path']);assert sha(failure)==retry['previous_failure_sha256']
failed=json.loads(failure.read_text());assert failed['completed_native_contexts']==1 and failed['completed_native_dispatches']==64 and not failed['context_in_quality_or_four_repeat_comparison']
for path,identity in failed['retained_files'].items():
    fp=oldcase/path;assert fp.stat().st_size==identity['size'] and sha(fp)==identity['sha256']
query=Path(r['separate_default_query']['path']);assert sha(query)==r['separate_default_query']['sha256']
qr=json.loads(query.read_text());assert qr['keys']==r['separate_default_query']['keys'] and r['separate_default_query']['not_queried_by_pinned_runner']
qa=Path(__file__).with_name('query_audit.json');qav=json.loads(qa.read_text())
audit['source_derivation_verified']=True
audit['source_derivation_sha256']=sha(case/'source_derivation.json')
audit['retry_derivation_sha256']=sha(case/'retry_derivation.json')
audit['extra_checks_sha256']=sha(Path(__file__).with_name('extra_checks.py'))
audit['separate_defaults_query']=dict(report_sha256=sha(query),independent_audit_sha256=sha(qa),keys=qr['keys'],active_values_not_queried_in_repeat_contexts=True)
audit['excluded_metadata_failure']=dict(failure_sha256=sha(failure),native_contexts=1,dispatches=64,excluded_from_four_repeat_comparisons=True,retained_hashes_verified=True)
audit['control']=dict(tuning=0,tuning_values=[],effect_key_configure_count=0,global_debug_configuration_remains=True,seven_inputs_and_184_byte_frame_controls_original_exact=True)

def native_window(a,b,start,stop,channels=slice(None)):
    return float(np.sqrt(sum(np.square(b[k][start:stop,...,channels].astype(np.float64)-a[k][start:stop,...,channels].astype(np.float64)).sum() for k in ('diffuse','specular'))/(2*a['diffuse'][start:stop,...,channels].size)))

comparisons=[]
for name,folder in [('tuning1_noreset','controlled_context_repeat_20260930'),('tuning1_reset32','reset_context_repeat_20260930'),('tuning0_noreset','default_tuning_context_repeat_v2_20260930')]:
    study=ROOT/'tools_tmp'/folder/'evidence';report=study/'results.json';rr=json.loads(report.read_text());values=[]
    assert rr['contexts']==4 and rr['dispatches']==256 and rr['runner_sha256']==r['runner_sha256'] and rr['native_provider_sha256']==r['native_provider_sha256']
    for record in rr['runs']:
        payload=Path(record['retained_payload_path']);assert sha(payload)==record['payload_sha256']
        mp=study/f"repeat_{record['run']}"/'amd_context_identity.json';assert sha(mp)==record['manifest_sha256']
        mm=json.loads(mp.read_text());assert mm['inputs']==reference['inputs']
        with np.load(payload) as pack:
            values.append({key:pack[key].copy() for key in pack.files})
        for lobe in ('diffuse','specular'):
            assert hashlib.sha256(values[-1][lobe].astype('<f2').tobytes()).hexdigest()==mm['output_sha256'][lobe+'.bin']
    pairs=[]
    for i,j in itertools.combinations(range(4),2):
        a,b=values[i],values[j]
        pairs.append(dict(first=i,second=j,
            native_RGBA_full=native_window(a,b,0,64),native_RGB_full=native_window(a,b,0,64,slice(0,3)),native_alpha_full=native_window(a,b,0,64,slice(3,4)),
            native_RGB_pre32=native_window(a,b,0,32,slice(0,3)),native_RGB_from32=native_window(a,b,32,64,slice(0,3)),
            selected_composed_full=metrics(a['selected_composed_rgb'],b['selected_composed_rgb'])['rms'],
            selected_composed_pre32=metrics(a['selected_composed_rgb'][:3],b['selected_composed_rgb'][:3])['rms'],
            selected_composed_from32=metrics(a['selected_composed_rgb'][3:],b['selected_composed_rgb'][3:])['rms']))
    comparisons.append(dict(name=name,report_sha256=sha(report),pairs=pairs,ranges={key:[min(p[key] for p in pairs),max(p[key] for p in pairs)] for key in pairs[0] if key not in ('first','second')}))
audit['descriptive_three_control_samples']=comparisons
audit['nonzero_native_RGB_pairs']=sum(p['native_RGB_both_lobes_rms']>0 for p in audit['pairs'])
audit['limitations']+=['Provider defaults were queried in a separate utility context, not active settings queried in these four contexts.',
    'Tuning0 disables a bundle of six effect Configure calls. This is not a single-key attribution.',
    'Four-context range comparisons are descriptive, not statistical confidence, causation, quality or a production fix.',
    'One native-complete/Python-metadata-failed attempt is preserved and excluded; it is counted separately as 1 context/64 dispatches.']
for comparison in comparisons:print(comparison['name'],comparison['ranges'])
