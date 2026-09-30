"""Independent CPU analytic closure plus frozen conversion-only experiment spec."""
import hashlib,json,math
from pathlib import Path
import numpy as np
from fixture import make_fixture,reconstruct,project,rotation_y
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def maximum(a,b):return float(np.max(np.abs(np.asarray(a)-b)))
sources=[ROOT/'OptiScaler/shaders/fsrd_preprocess/precompile'/s for s in ('FSRDInputConv.hlsl','FSRDInputConv_Shader.cso','FSRDPreprocessCommon.hlsli')]
sources += [ROOT/'OptiScaler/shaders/shader_tools/tests'/s for s in ('fsrd_alpha_common.py','run_fsrd_gpu_tests.py','fsrd_rr_runner.cpp')]
sources += [ROOT/'external/FidelityFX-SDK-v2/Kits/FidelityFX/denoisers/include/ffx_denoiser.h',ROOT/'tools_tmp/synthetic_camera_contract_review_20260930/review.json']
result=dict(schema='rotating-camera-conversion-cpu-conformance-v1',CPU_only=True,GPU_calls=0,native_dispatches=0,quality_accepted=False,
    analysis_sha256=sha(__file__),fixture_source_sha256=sha(HERE/'fixture.py'),sources=[dict(path=str(p),sha256=sha(p)) for p in sources],checks=[],counterexample={},payloads=[])
for roughness in (.1,.55):
    f=make_fixture(roughness)
    consumed_inverse=np.asarray(f['overrides']['InvProjMatrix'],np.float32).reshape(4,4)
    xyz=reconstruct(f['current_uv'],f['depth'],consumed_inverse)
    e1=maximum(xyz,f['world_xyz']);assert e1<2e-6
    previous_depth=f['previous_xyz'][...,2]
    reconstructed_previous=reconstruct(f['previous_uv'],previous_depth,consumed_inverse)
    recovered_world=(np.concatenate((reconstructed_previous,np.ones((80,128,1))),-1)@np.linalg.inv(f['previous_view']))[...,:3]
    e2=maximum(recovered_world,f['world_xyz']);assert e2<2e-6
    u,_=project(f['world_xyz'],f['projection']);assert maximum(u,f['current_uv'])<1e-15
    assert maximum(f['expected_converter_motion_float32'][...,2],f['expected_physical_mvz'])<2e-7
    # Packed normal roughness and external roughness must give same physical fields.
    fp=make_fixture(roughness,packed_roughness=True)
    np.testing.assert_array_equal(fp['expected_normal_before_storage'],f['expected_normal_before_storage'])
    np.testing.assert_array_equal(fp['expected_converter_motion_fp16'],f['expected_converter_motion_fp16'])
    # Low/high roughness cannot change primary MV or depth.
    other=make_fixture(.55 if roughness==.1 else .1)
    np.testing.assert_array_equal(other['expected_converter_motion_fp16'],f['expected_converter_motion_fp16'])
    # Native row-major bytes interpreted as HLSL column-major have expected sign.
    shader_column_matrix=np.asarray(f['overrides']['PrevViewMatrix'],np.float32).reshape(4,4,order='F')
    p=np.array([2.,1.,10.,1.]);np.testing.assert_allclose(shader_column_matrix@p,p@f['previous_view'],rtol=0,atol=0)
    error_wrong_transpose=abs(float((f['previous_view']@p)[2]-(p@f['previous_view'])[2]));assert error_wrong_transpose>.079
    hw=make_fixture(roughness,hardware_depth=True)
    assert maximum(hw['world_xyz'],reconstruct(hw['current_uv'],hw['depth'],consumed_inverse,False))<2e-4 # float32 R32 hardware depth
    jit=make_fixture(roughness,current_jitter=(.25,-.125),previous_jitter=(-.25,.125),jittered_motion=True)
    np.testing.assert_allclose(jit['expected_converter_motion_float32'][...,:2],jit['previous_uv']-jit['current_uv'],atol=1e-8)
    zero=make_fixture(roughness,theta=0.)
    assert maximum(zero['expected_converter_motion_float32'][...,2],0)==0
    record=dict(roughness=roughness,current_pinhole_inverse_closure_max=e1,previous_ray_world_closure_max=e2,
        viewmatrix_wrong_transpose_example_depth_error=error_wrong_transpose,expected_spec_alpha=f['expected_specular_alpha'],expected_diffuse_alpha=f['expected_diffuse_alpha'],
        primary_motion_uv_range=[[float(v.min()),float(v.max())] for v in (f['expected_converter_motion_float32'][...,0],f['expected_converter_motion_float32'][...,1])],
        physical_MVZ_range=[float(f['expected_physical_mvz'].min()),float(f['expected_physical_mvz'].max())],packed_roughness_equivalent=True,jitter_cancellation_closes=True,hardware_depth_closes=True)
    result['checks'].append(record)
    for matched in (True,False):
        v=make_fixture(roughness,matched_projection=matched)
        file=HERE/f'fixture_r{roughness:g}_{"matched" if matched else "identity"}.npz';assert not file.exists()
        np.savez_compressed(file,**{k:value for k,value in v.items() if isinstance(value,np.ndarray)})
        result['payloads'].append(dict(path=str(file),sha256=sha(file),roughness=roughness,matched_inverse_projection=matched,overrides=v['overrides']))

good=make_fixture();bad=make_fixture(matched_projection=False)
np.testing.assert_array_equal(good['motion'],bad['motion']);np.testing.assert_array_equal(good['depth'],bad['depth'])
np.testing.assert_array_equal(good['normals'],bad['normals'])
wrong_mvz=bad['expected_converter_motion_float32'][...,2];physical=good['expected_physical_mvz']
error=wrong_mvz-physical;idx=np.unravel_index(np.argmax(np.abs(error)),error.shape)
assert np.max(abs(error))>.21
result['counterexample']=dict(same_supplied_MVXY_depth_normals_roughness_and_radiance=True,only_InvProjMatrix_differs=True,
    identity_vs_physical_MVZ_RMS=float(np.sqrt(np.mean(error**2))),maximum_absolute_MVZ_error=float(np.max(abs(error))),
    maximum_pixel_y_x=list(map(int,idx)),physical_MVZ_at_peak=float(physical[idx]),identity_MVZ_at_peak=float(wrong_mvz[idx]),
    expected_identity_MVZ_range=[float(wrong_mvz.min()),float(wrong_mvz.max())])
converter=(ROOT/'OptiScaler/shaders/shader_tools/tests/fsrd_alpha_common.py').read_text()
assert "(kernel == 'auto' and applied > 0 and Path(directory).resolve() == t.PRE.resolve())" in converter
assert "else 'FSRDInputConv')" in converter
result['actual_PSO_selection']=dict(source_sha256=sha(ROOT/'OptiScaler/shaders/shader_tools/tests/fsrd_alpha_common.py'),
    default_kernel='auto',current_production_directory=True,strength0='FSRDInputConv: applied=0 does not satisfy applied>0',
    strength1='FSRDInputConvAdditive: applied=1 and current t.PRE satisfy positive-strength auto condition',
    explicit_original='kernel=original always selects FSRDInputConv even if strength is positive; use auto for the proposed split0/1 factorial.',
    caution='Historical alternate directories select FSRDInputConv under auto even with positive strength; record actual current directory and shader identity.')
result['GPU_conversion_spec']=dict(chosen_roughness=.1,size=[128,80],theta_radians=.02,planar_world_Z=10.,current_view='identity',
    matrix_storage='Row-major row-vector bytes; HLSL default column-major interprets same bytes as transpose, matching mul(matrix,column). No -Zpr in compile command.',
    calls='Load matched/identity NPZ raw,diff,spec,depth,normals,roughness,motion and corresponding overrides. Current production directory only: convert(raw,diff,spec,strength,depth=depth,normals=normals,roughness=roughness,motion=motion,overrides=overrides,kernel=auto), strength0 and1 separately: two matrices x two kernels=4 conversion dispatches. No native RR calls.',
    flags_primary=2082,resources='No resource overrides; standard convert slots. Input t1 depth R32 is canonical linear Z, t2 MV RG is PreviousUV-CurrentUV. Separate t4 roughness. Explicit zero jitter.',
    expected_outputs='packed[2] motion RGBA: XY same in both; B differs physically; A=1. packed[3] normal/rough/material independent of previous view and inverse projection. packed[0] indirectspec alpha=10 at .1 and0 at .55, packed[1] directdiff alpha=65504.',
    comparisons='Primary matched/identity only inverse projection changes. Compare geometry and source-input hashes before interpretation. Shader RGB uses unchanged supplied albedo and Z; no implemented NoV/Fresnel, so no predicted RGB camera dependence in this fixture.',
    tolerances='All input matrices first float32 quantized. Compare motion all pixels with |GPU-reference| <= 1 FP16 ulp(reference)+1e-5 absolute to cover float32 arithmetic; alpha exactly1. MVZ additionally compared to independent physical reference with same tolerance. Normal packed R10 channels within 1/1023+1e-4 of pre-storage analytic values. Canonical linear depth exact10. Do not demand CPU64/GPU32 byte equality.',
    optional_controls='theta0 must MVZ0; roughness .55 must same primary motion and specalpha0; packed roughness bit4 and jittered-motion bit256 variants have independent CPU closure. Hardware-depth variant disables bit2 and feeds projected R32 hardware depth, evaluated separately.')
result['limitations']=['Current View=identity does not independently exercise rotating CURRENT view-space normals; previous rotation must not rotate current world normal.',
    'This is an infinite fixed planar world surface with analytic correspondence. Pixels projected beyond previous viewport still have finite canonical MV; no disocclusion/game history quality claims.',
    'MVZ derives previous-camera depth of the same CURRENT world point, not sampling previous depth at destination and not reflecting hit-point motion.',
    'Old static identity-previous-view fixtures have MVZ0 for both inverse projections; this moving-camera counterexample cannot explain previous same-input native context variability.',
    'No GPU or native RR result is claimed. No shader or tracked test was changed.']
out=HERE/'results.json';assert not out.exists();out.write_text(json.dumps(result,indent=2)+'\n')
print('results_sha256',sha(out));print(json.dumps(result['counterexample'],indent=2))
