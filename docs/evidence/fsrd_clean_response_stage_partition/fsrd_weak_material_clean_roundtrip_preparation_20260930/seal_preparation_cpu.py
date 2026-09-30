"""One CPU-only final seal. Does not import scorer, launcher or helper runtime."""
from pathlib import Path
import ast, hashlib, json, struct

HERE = Path(__file__).resolve().parent

def record(path):
    p = Path(path)
    return dict(path=str(p.resolve()), bytes=p.stat().st_size,
                sha256=hashlib.sha256(p.read_bytes()).hexdigest())

def write(name, value):
    with (HERE / name).open('x', encoding='utf-8', newline='\n') as f:
        json.dump(value, f, indent=2, allow_nan=False)
        f.write('\n')

reg = json.loads((HERE / 'registration.json').read_text())
checks = json.loads((HERE / 'CPU_checks.json').read_text())
proof = json.loads((HERE / 'graph_identity_proof.json').read_text())
external = json.loads((HERE / 'external_source_pins.json').read_text())['records']
assert checks['SIMULATED_passed'] == 6 and checks['SIMULATED_failed'] == 0
assert checks['actual_helper_GPU_native_build_model_trials_scores'] == 0
assert checks['probe_body_byte_exact_to_existing']
assert checks['mature_parser_guard_resource_guard_EXE_byte_exact']
assert proof['unique_complete_graphs'] == 1
assert proof['raw_constructed_truth_all64_byte_identical']
assert [(j['frame'], j['arm']) for j in reg['jobs']] == [(0, 'R0'), (0, 'R1')]
for r in external:
    assert record(r['path']) == r, r['path']
for p in HERE.glob('*.py'):
    ast.parse(p.read_text(encoding='utf-8'))
runtime = [HERE / n for n in ('execution_results.json', 'roundtrip_metrics.json',
                             'roundtrip_sequences.npz', 'execution_TEMP')]
for j in reg['jobs']:
    folder = Path(j['job']).parent
    runtime += [folder / n for n in ('stdout.log', 'stderr.log', 'resource_guard.json')]
    runtime += [Path(o['path']) for o in j['outputs']]
    assert folder.is_dir()
    assert sorted(p.name for p in folder.iterdir()) == ['job.txt']
assert not any(p.exists() for p in runtime)
cb = (HERE / 'payloads/cb.bin').read_bytes()
assert len(cb) == 96
assert struct.unpack_from('<I', cb, 16)[0] == 8
assert struct.unpack_from('<f', cb, 20)[0] == 0
assert struct.unpack_from('<I', cb, 52)[0] == 0
assert struct.unpack_from('<I', cb, 64)[0] == 0

write('analysis_plan.json', dict(
    status='FROZEN_FUTURE_ANALYSIS_NOT_EXECUTED',
    actual_roundtrip_observations_planned=2, complete_graph_classes=1,
    order=['R0', 'R1'], no_new_SDK_calls=True,
    single_frame_scores='Each actual R0/R1 output-color RGB scored once against raw constructed truth frame0 and encoded raw q with byte-identical frozen LUMA/blur/score/moments/detail functions. Gain/DC/RMSE retained; unchanged singleton temporal fields explicitly non-inferential.',
    directional_R_minus_q='Actual one-frame converter+composition roundtrip minus encoded raw, retaining signed interior DC and existing signed rank-one Nyquist coefficient, descriptive RGB RMS/max only.',
    repeat_control='Retain and compare full serialized/RGB/alpha bits for all three actual output buffers. No replacement or alpha repair.',
    SDK_comparison_condition='Only if all3 R0/R1 buffers bit-identical and all64 full11SRV+CB graphs byte-identical; static R0 broadcast is a reference, never 64 measured roundtrip frames or a temporal variance estimate.',
    directional_T_minus_R='Prior measured C0/C1 64-frame SDK+composition output minus static R0 reference. Source/process/context/private-provider qualified; does not identify pure SDK error or game cause.',
    previous_T_metrics='Original frozen scorer and windows full/mature-last16/startup-first8/activation8to16 remain unchanged against original raw truth and quantized raw. Historical oldB four-window checks are pinned and repeated only by the future analyzer.',
    scores_model_trials_GPU_native_build_run_in_preparation=0,
    thresholds_changed=False, model_fitting=False, filtering=False,
    all_three_outputs_retained=True, quality_accepted=False,
    alpha_qualification='Actual converter specular A=0 and diffuse A=65504 remain untouched. Prior SDK output A=0 differs for diffuse. Frozen composition active Flags8/detail0/history0/writeHistory0 uses t0/t2 RGB and writes color A=1; no general native-alpha preservation or auxiliary-output shader-write claim.',
    provenance_qualification='Copied historical CSO/EXE identities and prior exact observed replays retained. Source inspection is a reference, not a new compile proving source-to-historical-EXE equivalence.',
    source_references=[dict(**record(HERE/'frozen_shader/FSRDOutputComp.hlsl'),
                           lines=[38,40,137,139,141,665,676,680,681],
                           meaning='t0/t2 half4 resources, RGB reconstruction, raw-blit guard, detail fast path and write-history guard'),
                       record(HERE/'frozen_shader/FSRDOutputComp_Shader.cso'),
                       record(HERE/'helper_source_reference.cpp'),
                       record(HERE/'fsrd_gpu_runner.exe')],
    semantic_limit='Specular input A is a hit-distance field, not confidence. The retained zero does not prove traced-ray provenance or a private-provider zero treatment. No camera/hit-A correction is inferred or applied.',
    future_authorization='Independent CPU prelaunch review and explicit root execution authorization still required. No retry or silent runtime overwrite.'
))

seal_names = {'pre_execution_freeze.json', 'readiness.json', 'completion_manifest.json'}
assert not any((HERE / n).exists() for n in seal_names)
owned = [record(p) for p in sorted(HERE.rglob('*')) if p.is_file()
         and p.name not in seal_names]
write('pre_execution_freeze.json', dict(
    status='FROZEN_CPU_PREPARATION_NO_GPU_AUTHORIZATION',
    owned=owned, external_sources=external,
    self_excluded=True, runtime_paths_expected_absent=[str(p) for p in runtime],
    native_API=0, helper_GPU_dispatches=0, builds=0, scores=0,
    planned_helpers_only_if_completed=2, planned_explicit_shader_dispatches_only_if_completed=2,
    planned_new_SDK_API=0, planned_output_files_only_if_completed=6))
write('readiness.json', dict(
    status='READY_FOR_INDEPENDENT_ROUNDTRIP_PRELAUNCH_REVIEW_NOT_EXECUTION_AUTHORIZATION',
    blockers=[], registration=record(HERE/'registration.json'),
    freeze=record(HERE/'pre_execution_freeze.json'),
    CPU_checks=record(HERE/'CPU_checks.json'),
    future_analysis=record(HERE/'analysis_plan.json'),
    graph_classes=1, all64_full11SRV_CB_bytes_equal=True,
    actual_preparation_helper_GPU_native_build_scores=0,
    inherited_SIMULATED_checks_passed=6,
    all_runtime_targets_absent=True,
    commands_after_independent_review_and_root_authorization_only=[
        'python -B run_roundtrip_only.py --execute-roundtrip-only',
        'python -B analyze_roundtrip_cpu.py --analyze-roundtrip'],
    python_runtime_read_only='F:/OptiRevelations/OptiScaler/tools_tmp/albedo_stage1_venv/Scripts/python.exe',
    limitations=reg['limitations']))
manifest_records = [record(p) for p in sorted(HERE.rglob('*')) if p.is_file()
                    and p.name != 'completion_manifest.json']
write('completion_manifest.json', dict(
    status='SEALED_CPU_PREPARATION_AWAITING_INDEPENDENT_REVIEW',
    records=manifest_records, self_excluded=True,
    external_source_record_count=len(external),
    external_source_manifest=record(HERE/'external_source_pins.json'),
    prior_CPU_failure_preserved=record(HERE/'initial_CPU_runtime_failure.json'),
    runtime_absence_verified=True, no_GPU_native_build_scores=True))
for n in ('registration.json','pre_execution_freeze.json','readiness.json','completion_manifest.json'):
    print(json.dumps(record(HERE/n)))
