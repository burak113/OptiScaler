"""Seal the bounded read-only semantic audit. No SDK/device/scorer imports."""
from pathlib import Path
import json, hashlib
HERE=Path(__file__).resolve().parent
ROOT=Path('F:/OptiRevelations/OptiScaler-ffxD-alpha')
def ident(p):
    p=Path(p); b=p.read_bytes()
    return dict(path=str(p.resolve()),bytes=len(b),sha256=hashlib.sha256(b).hexdigest())
def load(p): return json.loads(Path(p).read_text())
def save(name,v):
    with (HERE/name).open('x',encoding='utf-8') as f:json.dump(v,f,indent=2,allow_nan=False);f.write('\n')
before=load(HERE/'source_records_before.json'); after=load(HERE/'source_records_after.json')
assert before==after and all(ident(r['path'])==r for r in before)
supp_paths=[ROOT/'external/FidelityFX-SDK-v2/Kits/FidelityFX/api/include/dx12/ffx_api_dx12.h']
supp_paths += [ROOT/'tools_tmp/fsrd_weak_material_clean_converter_preparation_20260930/historical_templates'/f'{i:02d}/cb.bin' for i in range(1,64)]
supp=[ident(p) for p in supp_paths]
save('supplemental_source_records.json',dict(records=supp,reason='Exact native DXGI-to-API format map and all remaining CBs used by field inspection. No producer edits.'))
external=before+supp
assert len({r['path'] for r in external})==len(external)
field=load(HERE/'semantic_field_evidence.json')
assert field['controls']['jitterOffsets']==[0.,0.]
assert field['input_fields'][0]['channels'][0]['distinct_values']==[10.]
assert field['converter_CB']['all64_CB_exact']
assert not field['converter_CB']['native_projection_inverse_matches_converter']
api=ROOT/'external/FidelityFX-SDK-v2/Kits/FidelityFX/denoisers/include/ffx_denoiser.h'
header=api.read_text()
assert 'FFX_DENOISER_DISPATCH_LINEAR_DEPTH' not in header
save('primary_web_crosscheck.json',dict(url='https://gpuopen.com/manuals/fsr_sdk/techniques/denoising/',
    title='FSR Ray Regeneration 1.2.0 | GPUOpen Manuals',method='Narrow official-primary search crosscheck, no private-provider inference.',
    checked_claims=['Depth is signed view-space z, not NDC.','Public dispatch flags RESET and NON_GAMMA_ALBEDO.', 'Technique expects low-sample radiance/occlusion signals.'],
    primary_authority_for_cohort='Pinned local header/docs and actual bytes; online page is supplemental.'))
save('CPU_tool_observation.json',dict(command=[str(ROOT.parent/'OptiScaler/tools_tmp/albedo_stage1_venv/Scripts/python.exe'),'-B',str(HERE/'inspect_semantics.py')],
    tool='exec_command',chunk_id='093b52',exit_code=0,tool_output_observed=True,redirected_console_file=None,
    qualification='Tool result carried the computed field summaries. No separate stdout/stderr capture was created; saved field JSON is the retained data artifact.',
    new_native_GPU_build_scores=0))
save('audit.json',dict(schema='bounded-actual-clean-native-semantic-audit',status='COMPLETED_READ_ONLY_SEMANTIC_AUDIT',
    public_encoding_violations_demonstrated=[],production_fix_established=False,quality_accepted=False,
    actual_new_work=dict(native_contexts=0,SDK_API=0,GPU_jobs=0,builds=0,models=0,quality_scores=0),
    inspected=dict(native_inputs=7,actual_control_packets=128,converter_CB_packets=64,static_reference_frames=64,selected_pinned_external_records=len(external)),
    settled=[
      'Actual native input0 is R32_FLOAT +10 everywhere, matching converter canonical signed-linear depth; not normalized depth.',
      'Native flags3/2 select RESET+NON_GAMMA/ NON_GAMMA; no public LINEAR_DEPTH dispatch flag exists.',
      'API4202496 is version1.2.0. Directdiffuse/indirectspecular flags2/32, no checkerboard reconstruction.',
      'All actual jitter/camera delta/motionRGB are zero; view/projection/control floats static.',
      'Formats, oct normal(-z), roughness562/1023, material0 and linear albedo packing match public declarations.'],
    qualifications=[
      dict(id='camera_projection_inconsistency',observed=True,detail='Converter inverse projection identity/far10000 vs native perspective/far1000; no traced affected consumed RGB in the actual static branch. Fixture qualification, not demonstrated cause/fix.'),
      dict(id='indirect_specular_hit_distance_physical_provenance',observed=True,detail='Input A=0 from roughness tracking times primary-depth fallback, not traced secondary-ray length. Public docs do not state strictly-positive minimum or full zero handling. Numeric packing valid; physical semantics unresolved.'),
      dict(id='synthetic_lobe_and_BRDF_guides',observed=True,detail='Combined radiance allocated by converter; direct/indirect RGB equal, not measured independent lobes. Flat spec guide is constructed, not proven correct view-dependent BRDF.'),
      dict(id='signed_provider_unknown',detail='Pinned DLL48f identity known; model/shader semantics, zero-hit behavior, extra-channel use and unbiased gain/DC contracts unavailable from examined public source.'),
      dict(id='constructed_reference',detail='Static deterministic 128x80 Nyquist checker is an operator-response fixture, not a physical detail oracle.'),
      dict(id='preliminary_NoV_message_correction',detail='Actual albedo-A writer is allocation share. Stale UAV declaration is not the operative data semantics; no NoV claim retained.')],
    evidence=ident(HERE/'semantic_field_evidence.json'),report=ident(HERE/'report.md'),
    before_after_selected_source_hashes_exact=True,primary_web_crosscheck=ident(HERE/'primary_web_crosscheck.json'),
    next_discriminating_steps=['Existing exact converter/composer roundtrip partition, raw vs quantized reference kept separate.',
      'Separately preregister coherent camera + official-sample-style physical BRDF/hit-distance/signal control; isolate changed semantics.'],
    no_new_experiment_or_production_authorization=True))
assert all(ident(r['path'])==r for r in external)
files=[ident(p) for p in sorted(HERE.rglob('*')) if p.is_file() and '__pycache__' not in p.parts]
save('completion_manifest.json',dict(schema='semantic-audit-self-excluded-completion',status='COMPLETED_READ_ONLY_SEMANTIC_AUDIT',
    files=files,external_records=external,self_entry_excluded=True,actual_new_native_GPU_build_scores=0,
    source_before_after_exact=True,no_producer_or_production_edits=True))
print(json.dumps(dict(audit=ident(HERE/'audit.json'),manifest=ident(HERE/'completion_manifest.json'),owned_files=len(files),external_records=len(external),new_native_GPU_build_scores=0)))
