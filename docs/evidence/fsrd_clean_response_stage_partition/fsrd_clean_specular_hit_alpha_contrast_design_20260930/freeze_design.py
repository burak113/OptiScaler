"""CPU-only design seal. Does not write treatment payloads or import executors."""
from pathlib import Path
import hashlib,json,struct
ROOT=Path('F:/OptiRevelations/OptiScaler-ffxD-alpha')
HERE=Path(__file__).resolve().parent
N=ROOT/'tools_tmp/fsrd_weak_material_clean_native_preparation_20260930'
S=ROOT/'tools_tmp/fsrd_weak_material_clean_native_semantic_audit_20260930'
def ident(p):
    p=Path(p);b=p.read_bytes();return dict(path=str(p.resolve()),bytes=len(b),sha256=hashlib.sha256(b).hexdigest())
def save(n,v):
    with (HERE/n).open('x',encoding='utf-8')as f:json.dump(v,f,indent=2,allow_nan=False);f.write('\n')
def read(p):return json.loads(Path(p).read_text())
assert not(HERE/'completion_manifest.json').exists(),'Preserve sealed design.'
paths=[S/'audit.json',S/'report.md',S/'completion_manifest.json',N/'registration.json',N/'frozen_runner/source_reference.cpp',
       N/'frozen_runner/fsrd_rr_runner.exe',N/'native_resource_guard.py',N/'native_work_accounting.py',N/'executor_evidence.py',
       N/'planned_native/C0/job.txt',N/'planned_native/C0/dispatch_controls.bin',N/'planned_native/C0/frame_controls.txt',
       ROOT/'external/FidelityFX-SDK-v2/Kits/FidelityFX/denoisers/include/ffx_denoiser.h',
       ROOT/'external/FidelityFX-SDK-v2/Kits/FidelityFX/signedbin/amd_fidelityfx_denoiser_dx12.dll',
       ROOT/'tools_tmp/fsrd_weak_material_clean_native_postrun_review_20260930/review.json',
       ROOT/'tools_tmp/fsrd_weak_material_clean_roundtrip_preparation_20260930/design.txt']
paths += [N/'inputs'/f'input{i}.bin' for i in range(7)]
pins=[ident(p)for p in paths]
assert ident(S/'completion_manifest.json')['sha256']=='19b462d8f3debca527bcf003d5951fa5c87811a2309d0b0b2b4826343ab9f546'
reg=read(N/'registration.json')
assert reg['source_reference']['sha256']=='f6cfbecc4704d7f4f891f5c2ae88baf69546a316a9738ed03da0413d6ef0d077'
assert reg['runner']['sha256']=='3427689a4764380f885545c353250277e4d71944d3310c8a17b3cbba0f3c21d2'
assert reg['guard']['sha256']=='b70e18d0f13963e0250c371171933429446cf304041c9a16d971e9898d211814'
raw=(N/'inputs/input6.bin').read_bytes()
assert len(raw)==128*80*8 and all(raw[i+6:i+8]==b'\x00\x00'for i in range(0,len(raw),8))
assert struct.pack('<e',10.)==b'\x00I'
controls=(N/'planned_native/C0/dispatch_controls.bin').read_bytes()
assert len(controls)==64*184 and [struct.unpack_from('<II',controls,i*184)for i in range(64)]==[(i,3 if i==0 else 2)for i in range(64)]
save('source_pins.json',dict(records=pins,scope='Minimal exact source/cohort references; no mass clones or law framework.',before_after_exact=True))
save('protocol_design.json',dict(schema='clean-specular-hit-alpha-contrast-DESIGN_ONLY',status='FROZEN_DESIGN_NOT_PREPARATION_OR_EXECUTION_AUTHORIZATION',
    actual_new_work=dict(native_contexts=0,SDK_API=0,GPU_jobs=0,builds=0,models=0,scores=0),
    preparation_gate=dict(required='Genuine converter/composer roundtrip partition independently reviewed and sealed; root rationale for remaining native sensitivity question.',
        status='NOT_ESTABLISHED_BY_THIS_DESIGN',if_roundtrip_accounts_for_bias='Reconsider native contrast before preparation; no new threshold.'),
    order=[dict(tag=t,specular_A=a,frames=64)for t,a in [('A0_r0',0),('A10_r0',10),('A10_r1',10),('A0_r1',0)]],
    planned_only_if_complete=dict(contexts=4,successful_API=256,queued_RR=256,Execute=256,Signal=256,event=256,wait=256,completed_GPU_RR=256,observed_pair_frames=256),
    exact_treatment=dict(field='input6 RGBA16_FLOAT A only',A0_half_bits=0,A10_half_bits=0x4900,
        positive_value_semantics='Primary view-depth proxy +10, explicitly NOT a traced secondary-ray length.',
        pixel_alpha_words=128*80,upload_count=1,RGB_halfwords='Must preserve existing input6 RGB exact.',
        other_inputs='Inputs0..5 full RGBA bytes exact; input formats/upload counts unchanged.'),
    invariants=dict(original_CPP=reg['source_reference'],original_EXE=reg['runner'],provider=reg['provider'],guard=reg['guard'],
        tuning_values=reg['six_tuning_values'],controls184=ident(N/'planned_native/C0/dispatch_controls.bin'),
        inputs=[ident(N/'inputs'/f'input{i}.bin')for i in range(7)],source_indices=list(range(64)),
        same_output_initialization_and_command_list_lifecycle=True,camera_correction_bundled=False),
    public_contract=dict(indirect_specular_input_A='Ray hit distance, not confidence/normalized signal.',
        strictly_positive_minimum_documented=False,private_zero_handling_known=False,positive_proxy_proves_traced_distance=False),
    future_reporting=dict(raw_all_context_pairs=6,lobes=2,source_aligned_frames=64,within_dose_repeats_separate=True,
        descriptive_RGBA_RGB_alpha=True,physical_work_vs_acceptance_separate=True,
        composition_required_before_quality=True,raw_truth_vs_quantized_reference_separate=True,
        no_threshold_model_or_scorer_changes=True,no_automatic_retry=True),
    conclusion='Valid bounded sensitivity diagnostic under known serialized-field contract; cannot prove physical lobe validity, API violation, production fix or private mechanism.',
    frozen_protocol=ident(HERE/'protocol.md'),source_pins=ident(HERE/'source_pins.json'),no_executor_or_treatment_payload_prepared=True))
assert all(ident(r['path'])==r for r in pins)
files=[ident(p)for p in sorted(HERE.iterdir())if p.is_file()]
save('completion_manifest.json',dict(schema='self-excluded-design-completion',files=files,external_records=pins,self_entry_excluded=True,
    status='FROZEN_DESIGN_NOT_PREPARATION_OR_EXECUTION_AUTHORIZATION',actual_new_native_GPU_build_scores=0,before_after_pins_exact=True))
print(json.dumps(dict(protocol=ident(HERE/'protocol_design.json'),manifest=ident(HERE/'completion_manifest.json'),owned_files=len(files),external_records=len(pins),actual_native_GPU_build_scores=0)))
