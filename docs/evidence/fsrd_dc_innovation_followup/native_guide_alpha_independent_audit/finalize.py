from pathlib import Path
import ast,json,hashlib
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1];TMP=ROOT/'tools_tmp'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
r=read(HERE/'audit.json');proofs=[]
for script,old,new in [('prepare_guide_alpha_wave_continuation_20260930.py','native_guide_alpha_ablation_20260930','native_guide_alpha_wave_continuation_20260930'),
                       ('prepare_guide_alpha_wave_identical_repeat_20260930.py','native_guide_alpha_wave_continuation_20260930','native_guide_alpha_wave_identical_repeat_20260930')]:
    path=TMP/script;before=sha(path);tree=ast.parse(path.read_text());text=(TMP/old/'analyze.py').read_text();operations=[]
    for node in tree.body:
        if not isinstance(node,ast.Assign) or not any(isinstance(t,ast.Name) and t.id=='text' for t in node.targets):continue
        c=node.value
        if isinstance(c,ast.Call) and isinstance(c.func,ast.Attribute) and c.func.attr=='replace' and isinstance(c.func.value,ast.Name) and c.func.value.id=='text':
            args=[ast.literal_eval(a) for a in c.args];assert len(args)==2;operations.append({'old':args[0],'new':args[1],'matched_count':text.count(args[0])});text=text.replace(*args)
    assert text==(TMP/new/'analyze.py').read_text() and before==sha(path)
    proofs.append(dict(generator=str(path),generator_sha256=before,source_driver_sha256=sha(TMP/old/'analyze.py'),derived_driver_sha256=sha(TMP/new/'analyze.py'),replacement_operations=operations,derived_source_exact=True))
identity_pairs=[]
for p in r['wave_pairs']:
    t=p['trajectory'];identity_pairs.append(dict(left=p['left'],right=p['right'],all7_inputs_exact=p['all7_inputs_exact'],outputs_exact=all(v['bytes_exact'] for v in p['outputs'].values()),
                                             first_difference_frame=t['first_difference_frame'],maximum_frame=t['maximum_frame'],changed_frames=t['changed_frames'],
                                             raw6_RGB_RMS=t['raw6_RGB_RMS'],raw8_RGBA_RMS=t['raw8_RGBA_RMS'],raw2_alpha_RMS=t['raw2_alpha_RMS'],
                                             maximum_abs=t['maximum_abs'],maximum_location_frame_y_x_lobeRGBA=t['maximum_abs_location_frame_y_x_lobeRGBA']))
out=dict(status=r['status'],quality_accepted=False,source_audit_sha256=sha(HERE/'audit.json'),new_native_contexts=11,new_RR_calls=704,
         material4_plus_old_all_exact=True,wave_contexts8_including_old=True,wave_pairs28=True,all7_identical_input_pairs=15,nonexact_identical_input_pairs=9,
         maximum_identical_input_per_lobe_RGB_RMS=r['wave_maximum_identical_input_per_lobe_RGB_RMS'],wave_trajectories=identity_pairs,
         statement='Same7input/control variation persists. No guide-alpha cause/effect, output quality, confidence or averaged repair claim.')
(HERE/'compact_report.json').write_text(json.dumps(out,indent=2,allow_nan=False)+'\n')
notes=dict(status='completed_preparation_contract_review',source_audit_sha256=sha(HERE/'audit.json'),AST_generator_reconstruction=proofs,
           initial_failure='Original material4contexts completed. Wave input3uploadcount1 assertion failed before row/variant folders/native launch. Original failed result and run.log preserved.',
           supplemental_import_failure_scope='Root reported first supplemental import ModuleNotFoundError for guard path before any comparison result; corrected sys.path source and run_v2 log were independently read/pinned. This auditor does not infer missing terminal/failed stdout beyond retained artifacts/root report.',
           audit_input_mapping='input0depth41,input1motion10,input2normal24,input3specAlbedo28,input4diffAlbedo28,input5diffuseRGBA10,input6specularRGBA10. All job uploadcounts retained, count1 is immutable resource reuse, not repeated independent observations.',
           raw_units='Separate per-lobeRGB3/alpha1/RGBA4 plus combined6RGB/2alpha/8RGBA. No compose/output-to-truth quality measure. Alpha padding can dilute combinedRGBA RMS.',
           no_authorized_changes_to_producer_or_params=True)
(HERE/'preparation_contract_review.json').write_text(json.dumps(notes,indent=2)+'\n')
assert all(sha(p)==s for p,s in r['source_freeze_before_and_after_all_equal'].items())
files=[{'path':p.name,'bytes':p.stat().st_size,'sha256':sha(p)} for p in sorted(HERE.iterdir()) if p.is_file() and p.name!='completion_manifest.json']
(HERE/'completion_manifest.json').write_text(json.dumps({'status':'complete_frozen','quality_accepted':False,'files':files},indent=2)+'\n')
print(json.dumps({name:sha(HERE/name) for name in ('audit.json','compact_report.json','preparation_contract_review.json','completion_manifest.json')}))
print(json.dumps([p for p in identity_pairs if p['all7_inputs_exact'] and not p['outputs_exact']]))
