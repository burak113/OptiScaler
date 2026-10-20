"""Seal a relocatable CPU receipt, data requests and source/evidence checksums.

Run after run_checks.py for a final receipt. --draft permits missing receipts
while authoring; it never emits accepted status. No network or GPU operation.
"""
from pathlib import Path
import argparse
import hashlib
import json
import platform
import re
import subprocess
import sys

import numpy as np

from numerical_contract import __version__

HERE=Path(__file__).resolve().parent
REPO=HERE.parents[3]
BASE='5d7839a930106cf8fe1ba8dbbc6750509e7f26a8'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(name,value):
    (HERE/name).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def read_json(name):
    return json.loads((HERE/name).read_text(encoding='utf-8'))


def api_manifest():
    files=[{'path':p.relative_to(HERE).as_posix(),'sha256':sha(p),'bytes':p.stat().st_size}
           for p in sorted((HERE/'numerical_contract').glob('*.py'))]
    canonical=''.join(row['path']+'\0'+row['sha256']+'\n' for row in files).encode()
    return {'schema':'fsrd.numerical-api.v1','version':__version__,
            'aggregate_recipe':'SHA256 of UTF-8 sorted relative_path + NUL + file_sha256 + LF',
            'aggregate_sha256':hashlib.sha256(canonical).hexdigest(),'files':files}


def blocked_requests(calibration):
    colour=calibration['colour']
    witness=colour['missing_bits_witness']['overlap_constrained_witness']
    pixels=list(dict.fromkeys((x,y) for y,x,c in witness['distinguishing_yxc']))
    gates=colour['profiles']['observed_fraction8']['changed_validity_yx']
    native=[{'capture':r['capture'],'frame':r['frame'],'grid_extent_xy':r['grid_shape'][::-1],
             'fixed_mask_sha256':r['fixed_mask_sha256']} for r in calibration['anchor']['frames']
            if r['group']=='native_policy']
    manifest_path=REPO/'research/astra20261020/portable/anchor/fixtures/manifest.json'
    manifest=json.loads(manifest_path.read_text())
    native_group=next(g for g in manifest['groups'] if g['id']=='native_policy')
    captures={c['capture']:c for c in native_group['captures']}
    for row in native:
        capture=captures[row['capture']]
        row.update(capture_uuid=capture['capture_uuid'],original_render_extent_xy=capture['render'],
                   crop_origin_render_xy=capture['roi'][:2],replay_roi_extent_xy=capture['roi'][2:],
                   extent_authority='frozen anchor manifest, not inferred from floor-divided grid')
    common_provenance=['source capture UUID and original provider frame index',
        'tag/source/CSO/embedded-header/compiler executable and DLL hashes',
        'GPU PCI/vendor/device identifiers, driver, API, resource formats and mip',
        'original allocation and active render extents, crop origin, row pitch and exposure units',
        'exact cbuffer bytes, dispatch order, initialization, UAV barriers and readback fence',
        'little-endian raw payload SHA256; no normalization, exposure change, interpolation or lossy text conversion']
    return {'schema':'fsrd.blocked-data-request.v1','task_id':'01-numerical-contract',
        'gpu_executed':False,'status':'CPU work complete; specific exact-hardware claims remain blocked',
        'provenance_required_for_each_return':common_provenance,'requests':[
        {'id':'D1-colour-unknown-prestore-lobes',
         'missing_observable':'Original pre-UAV raw RR diffuse and specular half payloads, or exact original D+S float32 sum, at 16 distinguishing pixels outside the verified overlap.',
         'why_current_data_cannot_identify':'Rounded colour RGB admits distinct nonnegative half-lobe sums and 357 changed output lanes even after preserving the actual foliage rectangle. The 12288 known pixels are excluded.',
         'hypotheses_distinguished':['The older expected_soft2 gap at these sites comes from absent pre-store lobe low bits.',
             'A remaining source arithmetic/other omitted intermediate still changes the result after the actual bits are restored.'],
         'capture_uuid':'87ee1fba-b8bc-4660-aa3f-d06db7bf863f','frame_sequence':[63],
         'stage':'Original frame-63 raw RR D/S capture before summing and before any RTZ colour-fixture export; unwarped source coordinates.',
         'roles_and_formats':[{'role':'raw_rr_diffuse','format':'RGBA little-endian binary16','logical_stride_bytes':8},
                             {'role':'raw_rr_specular','format':'RGBA little-endian binary16','logical_stride_bytes':8},
                             {'role':'optional original sum used by expected_soft2','format':'RGB little-endian binary32','logical_stride_bytes':12}],
         'units':'Original capture radiance scale; alpha kept as captured metadata, never interpreted as an RGB lane.',
         'render_extent_xy':[1505,847],'colour_crop_origin_render_xy':[496,167],
         'colour_crop_extent_xy':[512,512],'requested_colour_local_xy':[list(p) for p in pixels],
         'requested_render_xy':[[x+496,y+167] for x,y in pixels],
         'known_overlap_colour_local_xyxy':[256,256,448,320],
         'local_extraction':'Read these coordinate-indexed values from the archived unwarped frame; include index table and original source tensor hash. If unavailable, report unavailable rather than copying aligned glass RGB.',
         'core_payload_bytes':len(pixels)*(8+8+12),'maximum_useful_payload_bytes':4096,
         'payload_scope':'Payload maximum excludes a small JSON provenance record. Start with these 16 sites; no full-capture upload requested.',
         'competing_outcomes':['Actual bits remove the selected residuals: attribute those differences to export information loss.',
             'Residuals remain: request only the affected source intermediate next; retain numerical uncertainty.'],
         'completed_without_it':'Exhaustive storage contract, admissible non-identifiability witnesses, verified foliage recovery and all CPU calibration.'},
        {'id':'D2-historical-colour-sampler-gates',
         'missing_observable':'Actual GPU sampled RGBA history, expected-depth float32 and uint validity at the nine CPU-profile distinguishing probe locations, plus the full GPU gate map if needed and exact historical C8 harness identity.',
         'why_current_data_cannot_identify':'The frozen NPZ expected fields are CPU outputs; the historical GPU JSON reports count9 without the raw gate map. Equal count under a fraction8 model does not prove the same GPU decisions.',
         'hypotheses_distinguished':['The recorded device snaps fractions as the selected8bit profile near these depth thresholds.',
             'Different coordinate/staging/rounding behavior produces a different set of gates.'],
         'capture_uuid':'87ee1fba-b8bc-4660-aa3f-d06db7bf863f','frame_sequence':[63],
         'initial_history':'Use the exact published prev_history from the CPU warmup0..62, not invented GPU prehistory.',
         'stage':'Historical C8 Track sampler output before depth gate and before OutHist typed store.',
         'historical_harness_source_revision':None,'historical_harness_cso_sha256':None,
         'historical_harness_note':'These identities are requested. Do not label the current production B4 shader as the old C8 experiment.',
         'render_extent_xy':[1505,847],'crop_origin_render_xy':[496,167],'crop_extent_xy':[512,512],
         'history_grid_extent_xy':[64,64],'requested_grid_yx':gates,
         'probe_coordinate_authority':'CPU observed-fraction8 versus frozen-model differences; these are NOT known historical GPU disagreement locations.',
         'input':'Exact published prev_history/Stats/Motion bytes; export the actual GPU UV and all four tapped coordinates/texels to resolve footprint differences.',
         'output_formats':{'sampled_history':'RGBA binary32,16bytes per grid cell',
                           'expected_depth':'binary32,4bytes','validity':'uint32,4bytes','uv':'float2,8bytes'},
         'units':'Original signed linear depth and full-render pixel motion; do not use crop-sized UV motion.',
         'local_extraction':'Prefer existing archived GPU readback. Otherwise extend the exact historical harness and execute only its controlled frame with the published history; retain an uninstrumented reference pair.',
         'targeted_payload_bytes':len(gates)*(16+4+4+8),'maximum_useful_payload_bytes':131072,
         'payload_scope':'Target9sites plus tap diagnostics first. At most one complete64x64 grid of sampledRGBA+expectedDepth+validity+UV =131072 logical bytes; no full render readback.',
         'competing_outcomes':['Exact sampled/gate map matches named profile: label that observed compiler/device combination only.',
             'Sample values or decisions differ: falsify that emulator at these sites, retain API envelope and record exact new profile.'],
         'completed_without_it':'All6CPU store/sampler combinations, immutable4096cell decisions, stored intermediates, phase sweep and synthetic local request.'},
        {'id':'D3-native-original-atomic-words',
         'missing_observable':'Seven original 32-byte native OutSums buffers after StatsRecall atomics and before Gain reads/reset.',
         'why_current_data_cannot_identify':'Stats/Recall half stores erase pre-store16.16 increments. All7frames have nonsingleton totals under both RNE andRTZ hypotheses. Exact Gain equality over ratio bounds does not identify counters.',
         'hypotheses_distinguished':['Original atomics lie in the RNE/RTZ stored-field bounds and confirm source cap/count/reset/carry behavior.',
             'Different source boundary, mask, units, overflow or capture provenance invalidates one of those conditional envelopes.'],
         'frames':native,'frame_sequence':'Existing isolated calibration frames; preserve their original order within each capture. Do not invent missing ring history.',
         'stage':'FSRDNrdPostMotionAnchorStatsRecall completed; UAV barrier; snapshot before FSRDNrdPostMotionAnchorGain and before host reset.',
         'format':'8 little-endian uint32 words,32bytes per frame',
         'word_layout':['current_low','current_high','recalled_low','recalled_high','count','padding0','padding1','padding2'],
         'units':'Current/recalled integer totals scaled by65536; each included physical level clamped[0,16]. Count is a raw integer.',
         'original_render_extent_xy':[1505,847],'actual_submitted_resource_allocation_extent_xy':None,
         'extent_note':'Each frame entry supplies manifest-reported original render/crop/replay ROI. Actual submitted resource descriptors and cbuffer bytes remain requested. The128x847 ROI has a16x105 grid; do not replace its height by105*8.',
         'known_provenance':{'manifest_sha256':sha(manifest_path),
                             'historical_harness_identity':native_group['harness_identity']},
         'local_extraction':'Prefer archived original atomics. If rerunning, use the original local ring/key inputs and constants; a sum recomputed from the supplied FP16 grids is not this observation.',
         'core_payload_bytes':224,'maximum_useful_payload_bytes':4096,
         'payload_scope':'224 core bytes plus exact relevant cbuffer/control data; provenance JSON separate. Return unavailable if original inputs are absent.',
         'competing_outcomes':['All original totals/counts inside declared bounds: narrow the observed-device profile and retain exact original words.',
             'Any original value outside: reject that bound or provenance assumption and inspect only the offending frame/stage.'],
         'completed_without_it':'Exact integer carry/reset/cap model, exhaustive-bin and randomized bounds, all7conditional ratio envelopes, invariant native Gain endpoints and all140frame Gain calibration.'}
        ]}


def final_result(source_revision,draft):
    calibration=read_json('evidence/calibration.json')
    records=read_json('evidence/run_records.json') if (HERE/'evidence/run_records.json').exists() else []
    if not draft and (len(records)!=16 or not all(r['passed'] for r in records)):
        raise ValueError('final receipt requires all16 acceptance commands at their expected exit codes')
    if not draft and any(r.get('source_revision')!=source_revision for r in records):
        raise ValueError('every final command receipt must identify the requested source revision')
    api=api_manifest();write_json('API_MANIFEST.json',api)
    if not draft and any(r.get('api_aggregate_sha256')!=api['aggregate_sha256'] for r in records):
        raise ValueError('current library bytes do not match the tested API identity')
    write_json('BLOCKED_DATA_REQUEST.json',blocked_requests(calibration))
    log=(HERE/'evidence/candidate_tests.log').read_text() if (HERE/'evidence/candidate_tests.log').exists() else ''
    count_match=re.search(r'Ran (\d+) tests in ([0-9.]+)s',log)
    candidate_count=int(count_match[1]) if count_match else None
    test_runner_seconds=float(count_match[2]) if count_match else None
    data=read_json('evidence/data_inventory.json')
    fixtures=[r['file'] for r in data['archives']]+[r['file'] for r in data['clips']]
    baseline=read_json('evidence/baseline_runs.json')
    evidence=[{'path':p.relative_to(HERE).as_posix(),'bytes':p.stat().st_size,'sha256':sha(p)}
              for p in sorted((HERE/'evidence').iterdir()) if p.is_file()]
    expected_files={'RESULT.json','MANIFEST.sha256'}
    paths={p.relative_to(REPO).as_posix() for p in HERE.rglob('*') if p.is_file()
           and '__pycache__' not in p.parts and p.suffix not in ('.pyc','.pyo')}
    paths|={(HERE/name).relative_to(REPO).as_posix() for name in expected_files}
    risks=[
        {'id':'U1','assumption':'Typed UAV FP16 rule depends on boundary/compiler/device; selected RNE/RTZ models do not prove a universal rule.','request':'GPU_REQUEST storage and Gain cases'},
        {'id':'U2','assumption':'Sampler fraction precision/tie handling/address arithmetic and exact filter operations are device-specific within the documented envelope.','request':'GPU_REQUEST phase/allocation cases; D2'},
        {'id':'U3','assumption':'DXC fast division/contraction/reassociation and device Exp accuracy remain unresolved at17combinedGain cells.','request':'GPU_REQUEST Gain residual diagnostic'},
        {'id':'U4','assumption':'NaN payloads, min/max signed-zero ties and intermediate denormal handling are not established GPU bytes.','request':'GPU_REQUEST typed-store microcases'},
        {'id':'U5','assumption':'Native pre-store atomic totals are absent despite invariant Gain over both stored-field ratio envelopes.','request':'D3'},
        {'id':'U6','assumption':'Unknown-region colour pre-store bits remain non-identifiable after recovering the verified foliage rectangle.','request':'D1'},
        {'id':'U7','assumption':'Historical C8 GPU validity map and exact instrumented harness identity are absent.','request':'D2'},
        {'id':'U8','assumption':'Source Anchor projection half-pixel distinction needs original motion/jitter/projection provenance before any production offset correction.','request':'integration capture constants if proposing such a change; no offset patch here'},
        {'id':'U9','assumption':'The finite-depth adapter has no fresh DXC/device validation; fast-math could alter nonfinite guards.','request':'GPU_REQUEST guard baseline/candidate A/B'},
        {'id':'U10','assumption':'No full upstream ring history, converged ground truth, AMD RR, game image or GPU performance was observed.','request':'job08 local acceptance; not required for using CPU API'},
        {'id':'U11','assumption':'Aligned glass RGB is not inverted to raw frame63; overlap-constrained witnesses are scoped to rounded colour plus verified unwarped foliage observations.','request':'D1 unwarped source values'},
    ]
    return {'schema':'fsrd.numerical-contract-result.v1','task_id':'01-numerical-contract',
        'base_tag':'astra-handoff-20261020','base_tag_object':'1f18416f5b99a0f78e147f362ac436ce2116ed22',
        'resolved_tag_commit':BASE,'audited_production_baseline':'87e8b7ab2a428bd91d3c044decf7d4dbccd8cefd',
        'source_revision':source_revision,'source_revision_scope':'implementation commit; final evidence-only handoff commit has its own PR head SHA',
        'branch':'astra/01-numerical-contract','pull_request_base':'sol/26-integration',
        'contract_version':__version__,'api_aggregate_sha256':api['aggregate_sha256'],
        'executor':'root local Linux CPU; independently authored/reviewed components attributed in evidence documents',
        'development_agents':['representation_contract','sampling_contract','independent_skeptic'],
        'dependency_versions':{'python':platform.python_version(),'numpy':np.__version__,
            'numpy_requirement':'numpy==2.3.5','system':platform.system(),'machine':platform.machine()},
        'seeds':{'storage_and_encoding':20261020,'arithmetic_and_carry':7217,'apply_channels':20261021,
            'sampling':[2026102001,2026102002,2026102003,2026102004,2026102005],
            'finite_guard':2026102031,'independent_rtz_and_adversary':0x01ADA203,
            'independent_development_only_fmaf_crosscheck':0xF32F},
        'input_authority':'frozen tag NPZ/manifests; all allow_pickle=False; generated analytic/seeded data labeled separately',
        'changed_paths':sorted(paths),'production_changed':False,'frozen_reference_changed':False,
        'initial_baseline_commands':baseline,'cpu_commands':records,
        'candidate_tests':{'count':candidate_count,'unittest_elapsed_seconds':test_runner_seconds},
        'command_wall_seconds_total':sum(r['elapsed_seconds'] for r in records) if records else None,
        'artifact_validation':{'checks':883,'generated_headers':107,'fresh_compilations':0,'mode':'--skip-compile'},
        'fixture_hashes':fixtures,'result_hashes':evidence,
        'source_compiler_cso_header_hashes':'evidence/source_inventory.json',
        'fixed_populations':{'colour_history_cells':4096,'colour_rgb_channels':786432,
            'recovered_overlap_pixels':12288,'remaining_colour_pixels':249856,
            'combined_gain_frames':133,'combined_gain_cells':416720,'native_gain_frames':7,'native_gain_cells':26256},
        'measured_comparisons':{'anchor_gain_store':calibration['anchor']['gain_store_intervention']['summary'],
            'native_gain_invariant_across_both_field_ratio_models':calibration['anchor']['gain_store_intervention']['native_gain_invariant_across_rne_and_rtz_field_ratio_bounds'],
            'colour_profile_changed_decisions':{k:v['changed_validity_count'] for k,v in calibration['colour']['profiles'].items()},
            'colour_baseline_soft2_error':calibration['colour']['profiles']['frozen']['vs_exported_expected']['soft2_output'],
            'verified_overlap':calibration['colour']['verified_overlap_recovery'],
            'overlap_constrained_nonidentifiability':calibration['colour']['missing_bits_witness']['overlap_constrained_witness'],
            'encoding':calibration['encoding'],'synthetic_microcases':read_json('evidence/gpu_microcases.json'),
            'finite_guard':{'exhaustive_comparisons':253952,'seeded_comparisons':4096,'changed_finite_decisions':0}},
        'rejected_hypotheses_or_claims':[
            'Changing the final Gain store alone reproduces every recorded combined GPU cell (17 explicit counterexamples).',
            'Rounded full-colour input uniquely identifies every old expected_soft2 output after the observed foliage overlap is fixed (357 admissible differences).',
            'A matching count9 proves matching the same historical GPU gate decisions (actual gate map absent).',
            'The native original atomic buffer can be reconstructed exactly from stored Stats/Recall cells (nonsingleton bounds).',
            'All guide payloads survive the old16-bit normalized half store.',
            'Absent off-crop observations can be supplied by texture-edge clamping.',
            'Arbitrary source-shaped float32 lerp is the universal documented hardware sampler.',
            'The finite source depth predicate necessarily rejects infinite expected depth.'],
        'unresolved_hardware_assumptions':risks,
        'gpu_executed':False,'dxc_compiled':False,'amd_rr_executed':False,'game_observed':False,
        'gpu_timings_ms':None,'gpu_memory_bytes_measured':None,'image_quality_improvement':None,
        'new_candidate_cso_sha256':None,'new_candidate_header_sha256':None,
        'acceptance_status':'draft_not_accepted' if draft else 'cpu_contract_passed_gpu_and_game_unvalidated',
        'recommendation':'keep as research','adapter_recommendation':'default-off local A/B proposal, pending DXC/GPU and job08 acceptance',
        'known_bad_controls':'Five numerical mutants and frozen colour quality gate must exit1; their rejection is required, not a passed quality claim.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-revision')
    parser.add_argument('--draft',action='store_true')
    args=parser.parse_args()
    records=read_json('evidence/run_records.json') if (HERE/'evidence/run_records.json').exists() else []
    recorded_revision=records[0].get('source_revision') if records and not args.draft else None
    revision=args.source_revision or recorded_revision or subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip()
    if not re.fullmatch('[0-9a-f]{40}',revision):
        raise ValueError('source revision must be a concrete full commit SHA')
    result=final_result(revision,args.draft)
    write_json('RESULT.json',result)
    paths=sorted(p for p in HERE.rglob('*') if p.is_file() and p.name!='MANIFEST.sha256'
                 and '__pycache__' not in p.parts and p.suffix not in ('.pyc','.pyo'))
    (HERE/'MANIFEST.sha256').write_text(''.join(sha(p)+'  '+p.relative_to(HERE).as_posix()+'\n' for p in paths),encoding='utf-8')
    print(json.dumps({'acceptance_status':result['acceptance_status'],'source_revision':revision,
                      'api_aggregate_sha256':result['api_aggregate_sha256'],'manifest_files':len(paths)},indent=2))


if __name__=='__main__':main()
