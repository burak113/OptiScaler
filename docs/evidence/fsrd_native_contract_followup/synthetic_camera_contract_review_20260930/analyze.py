"""Local synthetic-camera dataflow review and CPU analytic rays, no GPU."""
import hashlib,json,math
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
shader=ROOT/'OptiScaler/shaders/fsrd_preprocess/precompile/FSRDInputConv.hlsl'
common=shader.with_name('FSRDPreprocessCommon.hlsli')
converter=ROOT/'OptiScaler/shaders/shader_tools/tests/fsrd_alpha_common.py'
runner=converter.with_name('fsrd_rr_runner.cpp')
output_shader=shader.with_name('FSRDOutputComp.hlsl')
text=shader.read_text();assert 'viewSpacePos.z' in text and 'SoftBelow(roughness, 0.30f, 0.15f)' in text
assert 'Fresnel' not in text and 'NoV' in text  # NoV occurs in a source reflectance comment, not an implementation.

def rays(w,h,z=10):
    # CPU row-vector equivalent of HLSL column-major cbuffers + mul(matrix,column),
    # followed by GetViewSpacePos linear-depth ray rescaling at NDC z=.5.
    y,x=np.indices((h,w));ndc=np.stack((2*(x+.5)/w-1,1-2*(y+.5)/h),-1)
    identity=np.concatenate((2*z*ndc,np.full((h,w,1),z)),axis=-1)
    sy=1/math.tan(math.pi/6);sx=sy/(w/h)
    perspective=np.concatenate((ndc/np.array([sx,sy])*z,np.full((h,w,1),z)),axis=-1)
    identity_NoV=z/np.linalg.norm(identity,axis=-1);perspective_NoV=z/np.linalg.norm(perspective,axis=-1)
    # Identity world/view and PrevView make motion-Z delta exactly0 for both rays.
    np.testing.assert_array_equal(identity[...,2],perspective[...,2])
    return dict(size=[w,h],linear_z=z,
        identity_camera_absolute_NoV_range=[float(identity_NoV.min()),float(identity_NoV.max())],
        native_perspective_absolute_NoV_range=[float(perspective_NoV.min()),float(perspective_NoV.max())],
        corner_identity_position=identity[0,0].tolist(),corner_native_position=perspective[0,0].tolist(),
        max_XY_position_difference=float(np.max(np.abs(identity[...,:2]-perspective[...,:2]))),
        linear_Z_equal=True,static_identity_previous_view_depth_delta_zero=True)

alpha_study=ROOT/'tools_tmp/source_alpha_contract_20260930/evidence'
alpha_rp=alpha_study/'results.json';alpha_hash=sha(alpha_rp);alpha=json.loads(alpha_rp.read_text())
assert alpha['native_dispatches']==0
alpha_reauth=[]
for frame in alpha['frames']:
    payload=alpha_study/f"packed_frame_{frame['frame']}.npz";assert sha(payload)==frame['payload_sha256']
    with np.load(payload) as a:
        for name in ('specular','diffuse'):
            value=a[name]
            assert hashlib.sha256(value.astype('<f2').tobytes()).hexdigest()==frame[name]['rgba_fp16_sha256']
            expected=0 if name=='specular' else 65504
            assert np.all(value[...,3]==expected)
    alpha_reauth.append(dict(frame=frame['frame'],payload_sha256=frame['payload_sha256'],specular_alpha_exact=0,diffuse_alpha_exact=65504))
assert sha(alpha_rp)==alpha_hash
result=dict(schema='synthetic-camera-local-contract-review-v1',analysis_sha256=sha(__file__),
    sources=[dict(path=str(p),sha256=sha(p)) for p in (converter,runner,shader,common,output_shader)],
    quality_accepted=False,native_dispatches=0,new_GPU_calls=0,
    analytic_rays=[rays(128,80),rays(96,64)],
    mismatch=dict(conversion='InvView/InvProj/PrevView identity, near=.1 far=10000, signed linear depth',
        native='View identity, PerspectiveFovLH(pi/3,w/h,.1,1000), signed linear depth bounds[0,1024]',
        concrete='XY reconstructed view positions/ray directions disagree. Signed linear Z agrees for current shallow linear-depth fixtures.',
        current_consumed_payload_impact='No demonstrated impact of inverse-projection XY mismatch on current static identity-view fixtures: normals and linear-Z agree, motion-Z remains0; RGB split/remod/demod use supplied quantized albedos and no NoV/Fresnel function. Native RR derives its own view positions from its own perspective.',
        future_boundary='Nonidentity previous/current camera motion, hardware-depth conversion, far-plane classification, view-space normal conversion or a future view-dependent reflectance model can make this mismatch consequential.'),
    dataflow=[
        dict(field='Linear depth',lines=[291,300,304,305],finding='Linear flag forces canonical inDepth Z; identity versus inverse perspective changes XY ray, not clampedZ.'),
        dict(field='Normals/roughness',lines=[879,887,908,911],finding='World normal input normalized and oct encoded. Current defaults use identityview/world-space input; roughness.55 independent ofprojection.'),
        dict(field='Fresnel/specular demod',lines=[729,789,796,1062],finding='NoV appears only in DLSS hemispherical reflectance comment. Current implementation quantizes source specReflectance, stores/remodulates it directly; RGB denominators and split weights contain no Fresnel/NoV evaluation. OutputComp SpecularMultiplier lines129-131 is lerp(1,storedSpecAlbedo,strength).'),
        dict(field='Additive guide fit',lines=[1020],finding='Guide regression neighborhood receives viewSpacePos.z plus original world normal/roughness; no reconstructedXY input is passed.'),
        dict(field='Motion depth',lines=[918,919,982],finding='PrevView(identity)*InvView(identity)*currentPosition preservesZ, so current depth delta remains0 despite XY mismatch.'),
        dict(field='Ray hit',lines=[974,977,934,1159],finding='Absent spec guide fallback uses abs(viewSpacePos.z), sameZ; SoftBelow(.55,.30,.15)=0 makes specularTracking0 and spec inputAlpha0. Diffuse missing-hit sentinel65504. No missing field or required positive-alpha rule is established.')],
    alpha_followup=dict(prior_erratum_path=str(ROOT/'tools_tmp/reset_repeat_independent_audit_20260930/alpha_contract_erratum.json'),
        measurement_report_sha256=alpha_hash,retained_frames_reauthenticated=alpha_reauth,
        conclusion='Actual converted source spec input alpha0 is now directly measured atframes0/32; prior inference became supported only after measurement. Existing native output alpha0 agrees with it. Direct-diffuse inputAlpha65504/outputAlpha0 is not a ray-hit violation: direct signal input alpha is undefined, output Preserved wording is ambiguous and input-copy is explicit only for passthrough.'),
    warranted_controlled_tests=[
        dict(test='Static matched camera conversion invariance',preregister='Keep exact raw/diff/spec/depth/normal/roughness/strength and existing native Perspective camera. Change only converter InvProj to inverse of precisely that row-vector native matrix; retain conversion cb bytes and all7packedinputSHA atframe0/32. No thresholds/pilot tuning.',
            prediction='For current linear-depth identity static .55roughness path, consumed native input payloads should match (aside from any implementation rounding) because reconstructedXY does not enter them. Verify first; native rerun is unnecessary if all7bytes match.'),
        dict(test='Separate nonidentity previous-camera conformance',preregister='Use a physically specified current/previous camera, exact inverse/motion/depth correspondence and low/highroughness cases; compare analytic worldpoint/depthdelta closure. Separate fixture family, not same-input native ablation.',
            prediction='A camera rotation introduces previous-depth dependence onXY; identityInvProj must not stand in for physical inverse perspective there.')],
    cause_boundary='This fixed synthetic-camera mismatch cannot by itself explain same-input/pinned-binary context variation. Native Fresnel/model internals are unavailable locally, and no internal behavior is inferred.',
    captured_boundary='Captured studies already supply verified cropped camera overrides and inverse geometry closure. This review concerns synthetic defaults only.')
out=HERE/'review.json';assert not out.exists();out.write_text(json.dumps(result,indent=2)+'\n')
print('review_sha256',sha(out));print(json.dumps(result['analytic_rays']))
