"""CPU conformance and immutable four-arm current-camera conversion spec."""
import hashlib,json,math
from pathlib import Path
import numpy as np
from fixture import make_fixture,homogeneous,normalized,reconstruct,project,oct_decode
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def maxabs(a,b):return float(np.max(abs(np.asarray(a)-b)))
def angle(a,b):return np.arccos(np.clip(np.sum(normalized(a)*normalized(b),-1),-1,1))
def half_tolerance(a):
    a=np.asarray(a,np.float16)
    return np.maximum(abs(np.nextafter(a,np.float16(np.inf)).astype(float)-a),abs(a.astype(float)-np.nextafter(a,np.float16(-np.inf)).astype(float)))+1e-5
PRE=ROOT/'OptiScaler/shaders/fsrd_preprocess/precompile';TESTS=ROOT/'OptiScaler/shaders/shader_tools/tests'
sources=[PRE/name for name in ('FSRDInputConv.hlsl','FSRDInputConv_Shader.cso','FSRDInputConvAdditive.hlsl','FSRDInputConvAdditive_Shader.cso','FSRDPreprocessCommon.hlsli')]
sources += [TESTS/'fsrd_alpha_common.py',TESTS/'run_fsrd_gpu_tests.py',ROOT/'external/FidelityFX-SDK-v2/Kits/FidelityFX/denoisers/include/ffx_denoiser.h']
text=(PRE/'FSRDInputConv.hlsl').read_text()
assert 'mul((float3x3)InvViewMatrix, worldSurfaceNormal.xyz)' in text
assert '? prevViewSpacePos.z - viewSpacePos.z' in text and 'float3(uv, inDepth)' in text
result=dict(schema='current-camera-plane-four-arm-cpu-conformance-v1',analysis_sha256=sha(__file__),fixture_source_sha256=sha(HERE/'fixture.py'),
    CPU_only=True,new_GPU_calls=0,native_RR_dispatches=0,quality_accepted=False,matrices_first_consumed_float32=True,
    camera_spec=dict(current_rotation_Y_radians=.17,current_world_position=[.3,.1,-.2],previous_rotation_Y_radians=.15,previous_world_position=[.29,.1,-.2],
        world_plane_Z=10.,world_normal=[0,0,-1],perspective_FovLH_radians=math.pi/3,near=.1,far=1000.,size=[128,80],roughness=.1),
    source_identities=[dict(path=str(p),sha256=sha(p)) for p in sources],arms=[],scope=[])
arms={}
for depth_mode in ('linear','hardware'):
    for normal_space in ('world','view'):
        f=make_fixture(depth_mode,normal_space);name=f'{depth_mode}_{normal_space}'
        assert all(f[k].dtype==np.float32 for k in ('current_view_matrix','previous_view_matrix','inverse_view_matrix','projection_matrix','inverse_projection_matrix'))
        current_view=f['current_view_matrix'].astype(float);inverse_view=f['inverse_view_matrix'].astype(float)
        projection=f['projection_matrix'].astype(float);inverse_projection=f['inverse_projection_matrix'].astype(float)
        world=f['world_points'];current=f['current_view_points'];previous=f['previous_view_points'];uv=f['current_uv']
        # World-plane pinhole route and full homogeneous inverse route close.
        homogeneous_closure=maxabs(homogeneous(current)@inverse_view,homogeneous(world));assert homogeneous_closure<2e-6
        plane_error=maxabs(world[...,2],10.);assert plane_error==0
        y,x=np.indices((80,128));pixel_uv=np.stack(((x+.5)/128,(y+.5)/80),-1)
        pixel_closure=maxabs(uv,pixel_uv);assert pixel_closure<1e-14
        prev_uv,prev_hardware=project(previous,projection)
        np.testing.assert_array_equal(prev_uv,f['previous_uv'])
        prev_ray=reconstruct(prev_uv,previous[...,2],inverse_projection,True)
        prev_world=homogeneous(prev_ray)@np.linalg.inv(f['previous_view_matrix'].astype(float))
        previous_world_closure=maxabs(prev_world,homogeneous(world));assert previous_world_closure<2e-6
        # CPU prediction must honor the consumed normal's FP16 storage.
        normal_error=float(angle(f['expected_converter_world_normal'],f['world_normal']).max());assert normal_error<1e-4
        packed_normal_error=float(angle(f['expected_world_normal_after_R10'],f['world_normal']).max());assert packed_normal_error<.003
        view_normal_exact=normalized(f['view_normal']@inverse_view[:3,:3]);normal_transform_closure=maxabs(view_normal_exact,f['world_normal']);assert normal_transform_closure<1e-7
        world_normal_as_column=inverse_view[:3,:3].T@f['view_normal'];np.testing.assert_allclose(normalized(world_normal_as_column),view_normal_exact,atol=1e-16)
        # Camera/world same-point depth delta, independently from plane point.
        np.testing.assert_array_equal((homogeneous(world)@f['previous_view_matrix'].astype(float))[...,2]-current[...,2],f['physical_mvz'])
        expected=f['expected_converter_motion_fp16'].astype(float)
        physical_error=abs(expected[...,2]-f['physical_mvz']);physical_pred_pass=bool(np.all(physical_error<=half_tolerance(f['physical_mvz'])))
        assert physical_pred_pass
        assert np.all(np.isfinite(expected)) and np.all(expected[...,3]==1)
        # A missing normals-view-space flag leaves the camera rotation in world normals.
        wrong_normal_angle=float(angle(f['view_normal'].astype(np.float16).astype(float),f['world_normal']));assert wrong_normal_angle>.16
        file=HERE/(name+'.npz');assert not file.exists()
        np.savez_compressed(file,**{k:v for k,v in f.items() if isinstance(v,np.ndarray)})
        result['arms'].append(dict(name=name,depth_mode=depth_mode,normal_space=normal_space,payload_path=str(file),payload_sha256=sha(file),overrides=f['overrides'],
            plane_error=plane_error,pinhole_pixel_uv_closure=pixel_closure,current_homogeneous_world_closure_max=homogeneous_closure,
            previous_ray_world_closure_max=previous_world_closure,current_normal_transform_closure_max=normal_transform_closure,
            consumed_FP16_normal_world_angular_error_rad_max=normal_error,expected_R10_normal_world_angular_error_rad_max=packed_normal_error,
            missing_view_normal_flag_counterexample_angle_rad=wrong_normal_angle,
            current_linear_depth_range=[float(current[...,2].min()),float(current[...,2].max())],input_depth_range=[float(f['depth'].min()),float(f['depth'].max())],
            physical_MVZ_range=[float(f['physical_mvz'].min()),float(f['physical_mvz'].max())],
            expected_physical_MVZ_all_pixel_FP16_tolerance_pass=physical_pred_pass,expected_physical_MVZ_max_error=float(physical_error.max()),
            spec_alpha_expected_range=[float(f['expected_specular_alpha_fp16'].min()),float(f['expected_specular_alpha_fp16'].max())],diffuse_alpha_expected=65504.))
        arms[name]=f
for space in ('world','view'):
    a,b=arms['linear_'+space],arms['hardware_'+space]
    for k in ('world_points','current_uv','previous_uv','normals','roughness','motion','raw','diff','spec'):np.testing.assert_array_equal(a[k],b[k])
for depth in ('linear','hardware'):
    a,b=arms[depth+'_world'],arms[depth+'_view']
    for k in ('world_points','depth','motion','current_uv','previous_uv','raw','diff','spec','roughness'):np.testing.assert_array_equal(a[k],b[k])
    np.testing.assert_array_equal(a['expected_converter_motion_fp16'],b['expected_converter_motion_fp16'])
result['GPU_conversion_spec']=dict(total_conversion_dispatches=8,native_RR_dispatches=0,
    calls='Four saved arms x strength0/1. convert(raw,diff,spec,strength,depth=depth,normals=normals,roughness=roughness,motion=motion,overrides=row.overrides,kernel=auto,directory=t.PRE). Retain actual CB/input/output/job/stdout before _dispatch cleanup.',
    actual_PSO_by_auto_source_condition={'0':'FSRDInputConv','1':'FSRDInputConvAdditive'},
    input_geometry='R32 depth; FP16 canonical PreviousUV-CurrentUV MV XY; FP16 normal either world or current view; R32 roughness .1. No resource overrides/floor/bias/emissive/jitter. InvView/InvProj/PrevView float32 matrices supplied from manifest.',
    expected_motion='Packed[2] XY must equal consumed input FP16 XY exactly; alpha1. MVZ compare all pixels to expected_converter_motion_fp16 and independent physical_mvz using max neighboring FP16 ulp +1e-5.',
    expected_normals='Packed[3] compare decoded oct 3D world normal angle to [0,0,-1] <=.003rad; compare normal oct/R10 pre-storage reference with 1/1023+1e-4 only when not crossing oct atlas seam. Ideal -Z lies at atlas corner: raw UV equality across normal-space arms is not the sole conformance test.',
    alpha='Packed[0] specular alpha compare per-pixel to expected_specular_alpha_fp16 with one FP16 ulp+1e-5; tracking fullyopen at roughness.1. Packed[1] diffuse alpha exact65504.',
    native_camera_optional='Current view_matrix and projection_matrix are supplied as provenance only. No native RR dispatch in this study; hardware input depth must never be passed as RR signed-linear depth.')
result['scope']=['Tests nonidentity CURRENT inverse view normal transform and current/previous translated-camera same-world-point MVZ, separately from previous-only fixture.',
    'Hardware-depth arm is the defensive direct hardware-depth GetViewSpacePos branch. Production FloorSeed supplies canonical signed-linear depth; this does not claim all title depth paths were validated.',
    'Matrices model specified rigid cameras rounded to float32. Quantized inverse matrices have small recorded closure residuals; do not treat rounded rotations as mathematically exact orthogonal matrices.',
    'No native RR behavior, game history, stain/wave fix, or cause of earlier static same-input native context variation is inferred.']
out=HERE/'results.json';assert not out.exists();out.write_text(json.dumps(result,indent=2)+'\n')
print('results_sha256',sha(out))
for row in result['arms']:print(row['name'],'linearZ',row['current_linear_depth_range'],'MVZ',row['physical_MVZ_range'],'normalerr',row['consumed_FP16_normal_world_angular_error_rad_max'],'physicalhalfmax',row['expected_physical_MVZ_max_error'])
