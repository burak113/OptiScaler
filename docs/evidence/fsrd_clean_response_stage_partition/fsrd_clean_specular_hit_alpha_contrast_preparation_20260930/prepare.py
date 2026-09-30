"""CPU-only exact-byte preparation. Never loads SDK or invokes an SDK/device EXE."""
from pathlib import Path
import ast,difflib,hashlib,json,shlex,struct,subprocess,sys
sys.dont_write_bytecode=True
ROOT=Path('F:/OptiRevelations/OptiScaler-ffxD-alpha');HERE=Path(__file__).resolve().parent
OLD=ROOT/'tools_tmp/fsrd_weak_material_clean_native_preparation_20260930'
DESIGN=ROOT/'tools_tmp/fsrd_clean_specular_hit_alpha_contrast_design_20260930'
POST=ROOT/'tools_tmp/fsrd_weak_material_clean_native_postrun_review_20260930'
RPOST=ROOT/'tools_tmp/fsrd_weak_material_clean_roundtrip_postrun_review_20260930'
def ident(p):
    p=Path(p);b=p.read_bytes();return dict(path=str(p.resolve()),bytes=len(b),sha256=hashlib.sha256(b).hexdigest())
def read(p):return json.loads(Path(p).read_text())
def write(p,b):
    with Path(p).open('xb')as f:f.write(b)
def save(p,v):write(p,(json.dumps(v,indent=2,allow_nan=False)+'\n').encode())
def clone(a,b):write(b,Path(a).read_bytes());assert ident(a)['sha256']==ident(b)['sha256']
def q(p):return '"'+Path(p).resolve().as_posix()+'"'
def verify(rs):
    for r in rs:assert ident(r['path'])==r,r['path']
def rewrite_once(text,a,b):assert text.count(a)==1,a;return text.replace(a,b)
def main():
    assert not(HERE/'registration.json').exists(),'Preserve any existing preparation; do not repeat.'
    design=read(DESIGN/'protocol_design.json');assert design['actual_new_work']==dict(native_contexts=0,SDK_API=0,GPU_jobs=0,builds=0,models=0,scores=0)
    assert ident(DESIGN/'completion_manifest.json')['sha256']=='74d3bc3bf5b5902ee91af645c55b2187e00df1eac93ca2e62854cb722e8f0fd1'
    original=read(OLD/'registration.json');post=read(POST/'review.json')
    assert post['status']=='PASSED_CLEAN_NATIVE_RAW_EVIDENCE_REVIEW'and not post['blocking_findings']
    assert ident(POST/'completion_manifest_final.json')['sha256']=='9d231d55386869cdcd72d6e1095bf7548f42bbc3d4d990922fabb971f3cb18c1'
    assert ident(RPOST/'review.json')['sha256']=='781527903c10be0e17291a766c07db040d564b23b70aeeeded766f74d62bc97d'
    assert ident(RPOST/'completion_manifest.json')['sha256']=='200230c6abf03940cc2d4ee0c784503fbcbc41c93378386eebb0ecdc2dbb09fc'
    rpost=read(RPOST/'review.json');assert rpost['status']=='PASSED_CLEAN_ROUNDTRIP_EVIDENCE_AND_EXACT_SINGLETON_METRIC_REVIEW'and not rpost['blocking_findings']
    verify([original[k]for k in('source_reference','runner','provider','guard')])
    verify(original['cases'][0]['inputs']);verify(design['invariants']['inputs'])
    assert original['source_reference']['sha256']=='f6cfbecc4704d7f4f891f5c2ae88baf69546a316a9738ed03da0413d6ef0d077'
    assert original['runner']['sha256']=='3427689a4764380f885545c353250277e4d71944d3310c8a17b3cbba0f3c21d2'
    assert original['provider']['sha256']=='48f1e5888ba6a0a3d59a98b9751e37c392b0f7b8c223d0082d5c1f40642879d3'
    assert original['guard']['sha256']=='b70e18d0f13963e0250c371171933429446cf304041c9a16d971e9898d211814'
    formats=[41,10,24,28,28,10,10];bpp=[4,8,4,4,4,8,8]
    raw=[(OLD/'inputs'/f'input{i}.bin').read_bytes()for i in range(7)]
    assert [len(v)for v in raw]==[128*80*b for b in bpp]
    assert original['input_upload_counts']==[1]*7
    positive=bytearray(raw[6]);assert struct.pack('<e',10.)==b'\x00I'
    for p in range(128*80):
        i=p*8;assert raw[6][i+6:i+8]==b'\x00\x00';positive[i+6:i+8]=b'\x00I'
    assert all(positive[p*8:p*8+6]==raw[6][p*8:p*8+6]for p in range(128*80))
    assert sum(a!=b for a,b in zip(positive,raw[6]))==128*80
    payload=HERE/'payloads';payload.mkdir(exist_ok=False);positive_path=payload/'input6_A10.bin';write(positive_path,positive)
    controls=(OLD/'planned_native/C0/dispatch_controls.bin').read_bytes()
    assert len(controls)==64*184 and [struct.unpack_from('<II',controls,f*184)for f in range(64)]==[(f,3 if f==0 else 2)for f in range(64)]
    oldrows=[shlex.split(x)for x in(OLD/'planned_native/C0/job.txt').read_text().splitlines()]
    assert oldrows[0][:8]==['128','80','64','2','32','0','1','0']
    planned=HERE/'planned_native';planned.mkdir(exist_ok=False);cases=[];matches=[]
    for tag,dose in [('A0_r0',0),('A10_r0',10),('A10_r1',10),('A0_r1',0)]:
        f=planned/tag;f.mkdir();clone(OLD/'planned_native/C0/frame_controls.txt',f/'frame_controls.txt');write(f/'expected_applied_dispatch_controls.bin',controls)
        paths=[OLD/'inputs'/f'input{i}.bin'for i in range(7)]
        if dose==10:paths[6]=positive_path
        header=' '.join(oldrows[0][:8])+' '+q(Path(original['provider']['path']))
        lines=[header]+[f'{q(p)} {fmt} 1'for p,fmt in zip(paths,formats)]+[q(f/'diffuse.bin')+' '+q(f/'specular.bin')]
        write(f/'job.txt',('\n'.join(lines)+'\n').encode())
        assert all(paths[i].read_bytes()==raw[i]for i in range(6))
        assert paths[6].read_bytes()==(raw[6]if dose==0 else positive)
        cases.append(dict(tag=tag,specular_input_A=dose,job=str(f/'job.txt'),command=[original['runner']['path'],str(f/'job.txt')],
            source_frame_indices=list(range(64)),expected_controls=ident(f/'expected_applied_dispatch_controls.bin'),
            expected_output_bytes_per_lobe=64*128*80*8,inputs=[ident(p)for p in paths],input_upload_counts=[1]*7,camera_override='absent'))
        matches.append(dict(tag=tag,input6_RGB_byte_exact=True,other6_full_RGBA_byte_exact=True,controls184_exact=True,
            input6_alpha_half_bits=0 if dose==0 else 0x4900,alpha_pixels=128*80,changed_byte_offsets='For A10: 8*p+7 only; all A halfwords become0x4900.',
            output_parents_exist=f.is_dir(),camera_override_absent=not(f/'camera.txt').exists()))
    for name in('native_resource_guard.py','native_work_accounting.py','executor_evidence.py','check_accounting_cpu.py'):clone(OLD/name,HERE/name)
    olddriver=(OLD/'run_native.py').read_text();newdriver=olddriver
    for a,b in [('--execute-clean-native','--execute-native'),('genuine-clean-two-fresh-contexts-native-raw-only','clean-specular-hit-alpha-four-fresh-contexts-native-raw-only'),
        ('==2 and report[\'totals_unknown_children\']','==4 and report[\'totals_unknown_children\']'),('all(v==128 for v in report[\'counts\'].values())','all(v==256 for v in report[\'counts\'].values())'),
        ('completed_clean_native_raw_only_not_composed_not_quality_accepted','completed_specular_alpha_native_raw_only_not_composed_not_quality_accepted')]:newdriver=rewrite_once(newdriver,a,b)
    newdriver=newdriver.replace('Frozen future clean-only native executor. Preparation never imports/calls main.','Frozen future alpha-contrast executor. Root must verify sealed R/RZ gates and authorize; preparation never calls main.')
    write(HERE/'run_native.py',newdriver.encode());write(HERE/'executor_adaptation.diff',''.join(difflib.unified_diff(olddriver.splitlines(True),newdriver.splitlines(True),fromfile='reviewed_clean_native/run_native.py',tofile='alpha_contrast/run_native.py')).encode())
    for p in HERE.glob('*.py'):ast.parse(p.read_text(),filename=str(p))
    # Existing exact twelve B342 metadata-only laws; no SDK/device executable.
    check=subprocess.run([sys.executable,'-B',str(HERE/'check_accounting_cpu.py')],cwd=HERE,capture_output=True)
    write(HERE/'CPU_checks.stdout.bin',check.stdout);write(HERE/'CPU_checks.stderr.bin',check.stderr)
    save(HERE/'CPU_checks_result.json',dict(command=[sys.executable,'-B',str(HERE/'check_accounting_cpu.py')],returncode=check.returncode,
        stdout=ident(HERE/'CPU_checks.stdout.bin'),stderr=ident(HERE/'CPU_checks.stderr.bin'),SIMULATED_only=True,actual_native_GPU_build_scores=0))
    assert check.returncode==0,'Preserve any failed preparation.'
    from executor_evidence import fresh_runtime
    assert all(fresh_runtime(Path(c['job']).parent)['all_absent']for c in cases)
    temp=HERE/'execution_TEMP';temp.mkdir(exist_ok=False);quarantine=HERE/'quarantine';quarantine.mkdir(exist_ok=False)
    assert temp.resolve().drive.upper()=='F:'and HERE in temp.resolve().parents
    runtime=dict(cases=[dict(tag=c['tag'],preflight=fresh_runtime(Path(c['job']).parent))for c in cases],
        result_absent=not(HERE/'execution_results.json').exists(),analysis_absent=not(HERE/'raw_comparisons.json').exists(),
        runtime_parent_dirs_created=True,owned_F_TEMP=str(temp.resolve()),quarantine_empty=True,
        policy='Reject stale paths, preserve failures in place; no overwrite, moves, cleanup, automatic retry or quarantine of other processes/files.')
    save(HERE/'payload_and_runtime_verification.json',dict(mutation_checks=matches,runtime=runtime,
        guard_source_exact=True,accounting_and_guard_load_byte_exact=True,existing_12_SIMULATED_contracts_passed=True,actual_native_GPU_build_scores=0))
    sources=[DESIGN/'protocol_design.json',DESIGN/'completion_manifest.json',POST/'completion_manifest_final.json',RPOST/'review.json',RPOST/'completion_manifest.json',OLD/'registration.json',OLD/'input_provenance.json',OLD/'run_native.py',OLD/'analyze_raw_cpu.py',
        OLD/'planned_native/C0/job.txt',OLD/'planned_native/C0/frame_controls.txt',OLD/'planned_native/C0/dispatch_controls.bin']
    sources+=[Path(original[k]['path'])for k in('source_reference','runner','provider','guard')]
    sources+=[OLD/name for name in('native_work_accounting.py','executor_evidence.py','check_accounting_cpu.py')]
    sources+=[OLD/'inputs'/f'input{i}.bin'for i in range(7)]
    external=[ident(p)for p in dict.fromkeys(sources)];verify(external)
    save(HERE/'source_reuse.json',dict(expanded_reviewed_provenance_manifest=ident(POST/'completion_manifest_final.json'),
        expanded_tables_copied=False,exact_law_modules=[dict(name=n,source=ident(OLD/n),clone=ident(HERE/n),byte_exact=True)for n in('native_resource_guard.py','native_work_accounting.py','executor_evidence.py','check_accounting_cpu.py')],
        historical_EXE_source_provenance_qualification='Original B342 EXE identity retained; source reference is not a newly proven historical build provenance.',
        partial_accounting_qualification='B342 complete footer follows DestroyContext; no trusted footer leaves qualified actual readback-prefix lowerbounds with unknown totals. Controls written before API prove no success. No explicit intermediate SDK success journal; do not invent context/call counts for unobserved pre-readback work. Current-child/canonical-return/fresh missing-guard constraints retained.'))
    registration=dict(schema='clean-specular-hit-alpha-four-fresh-preregistration',status='PREPARED_CPU_ONLY_NOT_AUTHORIZED_NATIVE',
        design=ident(DESIGN/'protocol_design.json'),cases=cases,fixed_order=[c['tag']for c in cases],
        source_reference=original['source_reference'],runner=original['runner'],provider=original['provider'],guard=ident(HERE/'native_resource_guard.py'),
        six_tuning_values=original['six_tuning_values'],input_formats=formats,input_upload_counts=[1]*7,
        planned_only_if_all_completed=dict(contexts=4,successful_API=256,queued_RR=256,Execute=256,Signal=256,event=256,wait=256,completed_GPU_RR=256,observed_pair_frames=256),
        current_actual=dict(native_contexts=0,SDK_API=0,GPU_jobs=0,builds=0,models=0,scores=0),
        pending_external_execution_gates=dict(R=dict(status='PASSED_SEALED',review=ident(RPOST/'review.json'),seal=ident(RPOST/'completion_manifest.json')),
            RZ='Actual CSO diffuse-alpha0 roundtrip control independent postreview and seal must pass.',
            reconsideration='If reviewed direct roundtrip accounts for gain/DC departure, document whether new native dose remains warranted.',root_authorization='Separate immutable root authorization after these gates and independent preparation review.',
            gate_status='R_PASSED_RZ_PENDING_NOT_READ_OR_ASSUMED_PASSED',executor_gate_enforcement='Root preauthorization verifier must pin/validate gate seals; CLI flag is not gate evidence.'),
        treatment='input6 alpha+0 vs FP16+10bits0x4900 only; +10 is view-depth proxy, NOT traced ray length. No ray-validity/API-violation/private-zero assertion.',
        guards=dict(timeout_seconds=240,maximum_working_set_bytes=2*1024**3,minimum_available_memory_bytes=1024**3,sample_interval_seconds=.2,TEMP_TMP=str(temp.resolve()),single_owned_sequential_child=True),
        strict_diagnostics='SDK/D3D ordinary errors/warnings expected zero; retain actual diagnostics and all failed work before acceptance, no warning allowlist or retries.',
        analysis_plan=ident(HERE/'analyze_raw_cpu.py'),quality_accepted=False,composition_authorized=False,
        output_alpha='Raw descriptive bits only; consumed RGB finite gate, no outputA quality/finiteness gate.',
        same_original_serial_lifecycle_output_initialization=True,no_other_source_EXE_or_input_change=True)
    save(HERE/'registration.json',registration)
    files=lambda:[ident(p)for p in sorted(HERE.rglob('*'))if p.is_file()and '__pycache__'not in p.parts]
    save(HERE/'pre_native_freeze.json',dict(schema='alpha-contrast-pre-native-freeze',files=files(),external_sources=external,self_entry_excluded=True,actual_native_GPU_build_scores=0))
    save(HERE/'prelaunch_ready_manifest.json',dict(schema='alpha-contrast-conditional-preparation-ready',files=files(),external_sources=external,self_entry_excluded=True,
        status='READY_FOR_INDEPENDENT_PREPARATION_REVIEW_R_RZ_ROOT_EXECUTION_GATES_PENDING',actual_native_GPU_build_scores=0,
        all4_runtime_cases_fresh=True,not_execution_authorization=True))
    verify(external)
    print(json.dumps(dict(registration=ident(HERE/'registration.json'),freeze=ident(HERE/'pre_native_freeze.json'),ready=ident(HERE/'prelaunch_ready_manifest.json'),external_records=len(external),actual_native_GPU_build_scores=0)))
if __name__=='__main__':main()
