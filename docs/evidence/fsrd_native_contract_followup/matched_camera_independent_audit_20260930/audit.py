"""Read-only two-frame matched-camera payload/derivation audit, no GPU."""
import ast,hashlib,json
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
CASE=ROOT/'tools_tmp/matched_camera_input_contract_20260930'
STUDY=CASE/'evidence';HERE=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
rp=STUDY/'results.json';before=sha(rp);r=json.loads(rp.read_text())
assert r['status']=='completed_input_control_not_native_quality' and r['native_dispatches']==0
assert sha(CASE/'analyze.py')==r['script_sha256']
derivation=json.loads((CASE/'source_derivation.json').read_text())
assert sha(CASE/'generate.py')==derivation['generator_sha256']
assert sha(CASE/'analyze.py')==derivation['generated_sha256']
assert sha(Path(derivation['source']))==derivation['source_sha256']
tree=ast.parse((CASE/'generate.py').read_text())
assignment=next(node for node in tree.body if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='changes' for t in node.targets))
changes=ast.literal_eval(assignment.value)
text=Path(derivation['source']).read_text()
for old,new in changes:
    assert text.count(old)==1
    text=text.replace(old,new,1)
assert text==(CASE/'analyze.py').read_text()
camera_review=ROOT/'tools_tmp/synthetic_camera_contract_review_20260930/review.json'
review=json.loads(camera_review.read_text())

# Verify the recorded inverse really inverts the default native row-vector camera.
# Exact matrix bytes are pinned by the source report's actual dispatch projection hash;
# this CPU check proves the analytic geometry within float32 tolerances, not an SDK call.
inverse=np.asarray(r['inverse_projection'],dtype=np.float32).reshape(4,4)
sy=np.float32(1/np.tan(np.pi/6));sx=np.float32(sy/np.float32(128/80))
native=np.array([[sx,0,0,0],[0,sy,0,0],[0,0,np.float32(1000/999.9),1],
                 [0,0,np.float32(-.1*1000/999.9),0]],np.float32)
closure=native.astype(float)@inverse.astype(float)
np.testing.assert_allclose(closure,np.eye(4),rtol=0,atol=2e-6)
formats=[41,10,24,28,28,10,10];bytes_per_pixel=[4,8,4,4,4,8,8]
audit=dict(schema='matched-camera-two-frame-independent-audit-v1',analysis_sha256=sha(__file__),
    report_sha256=before,generator_sha256=sha(CASE/'generate.py'),derived_script_sha256=sha(CASE/'analyze.py'),
    source_derivation_sha256=sha(CASE/'source_derivation.json'),derivation_reproduced_exact_text=True,
    prior_camera_review_sha256=sha(camera_review),native_dispatches=0,quality_accepted=False,
    inverse_projection_default_native_closure_max_error=float(np.max(np.abs(closure-np.eye(4)))),
    native_projection_hash_as_recorded=r['native_projection_sha256'],frames=[],
    native_input_formats_by_slot=formats,limitations=[
        'Only original lighting fixture frames0/32,128x80,linear-depth/staticidentityview,roughness.55 tested.',
        'Inverse matrix stored in report; actual projection hash is recorded by source script from applied dispatch bytes atoffset120. This audit separately verifies analytic inverse closure, not new native consumption.',
        'Seven consumed-format input bytes are retained and independently compared; no new RR contexts or quality test.',
        'Do not generalize two-frame identity to all13families, all64frames, moving cameras, hardwaredepth, different normals/roughness, or captured game history.',
        'Payload equality rules out this inverse-projection change as an input-difference explanation for these two frames only; it does not determine native context variability cause.'])
for frame in (0,32):
    old=next(x for x in r['frames'] if x['frame']==frame and not x['matched_inverse_projection'])
    new=next(x for x in r['frames'] if x['frame']==frame and x['matched_inverse_projection'])
    slots=[]
    for slot in range(7):
        a=STUDY/f'frame_{frame}_matched_0_input{slot}.bin';b=STUDY/f'frame_{frame}_matched_1_input{slot}.bin'
        da,db=a.read_bytes(),b.read_bytes()
        assert len(da)==len(db)==128*80*bytes_per_pixel[slot]
        assert sha(a)==old['native_input_sha256'][str(slot)] and sha(b)==new['native_input_sha256'][str(slot)]
        assert da==db
        slots.append(dict(slot=slot,DXGI_format=formats[slot],byte_count=len(da),old_sha256=sha(a),new_sha256=sha(b),exact_bytes_equal=True))
    for matched,item in ((False,old),(True,new)):
        payload=STUDY/f'packed_frame_{frame}_matched_{int(matched)}.npz';assert sha(payload)==item['payload_sha256']
        with np.load(payload) as data:
            for name,slot in (('specular',6),('diffuse',5)):
                value=data[name];assert value.shape==(80,128,4) and np.isfinite(value).all()
                raw=value.astype('<f2').tobytes()
                assert hashlib.sha256(raw).hexdigest()==item[name]['rgba_fp16_sha256']
                assert raw==(STUDY/f'frame_{frame}_matched_{int(matched)}_input{slot}.bin').read_bytes()
                expected=0 if name=='specular' else 65504
                assert np.all(value[...,3]==expected)
    comparison=next(x for x in r['comparisons'] if x['frame']==frame)
    assert comparison['all_seven_input_hashes_equal'] and comparison['differing_slots']==[]
    audit['frames'].append(dict(frame=frame,slots=slots,all_seven_hashes_and_bytes_equal=True,
        packed_diffuse_specular_FP16_reconstructs_native_format_payload_exactly=True,
        spec_input_alpha_exact=0,diff_input_alpha_exact=65504))
audit['dataflow_confirmation']=[
    'GetViewSpacePos linear-depth path changesXY with InvProj, explicitly restoresZ=inDepth. Current native input0 linearZ is fixed.',
    'World normal normalization/octencoding and input roughness.55 do not consume projection. Input2 bytes agree.',
    'Current/previous viewidentity preserveZ through worldpoint reprojection; motionZ0/input1 agree despite reconstructedXY difference.',
    'Additive guide fit consumes reconstructedZ, normal androughness, not fullXY position.',
    'SpecularRGB share/divisor/remod uses quantized suppliedalbedos. No implemented view-dependent Fresnel/NoV term; NoV is only a source reflectance comment.',
    'Specular fallback raydistance depends onabsZ, then tracking SoftBelow(.55,.30,.15)=0. Input6alpha0 verified; diffusemissinghit65504/input5 verified.',
    'Thus all7 native-format fields, including RGBguides/radiance and geometry, are equal in both measuredframepairs.']
assert sha(rp)==before
audit['all_original_evidence_unchanged']=True
out=HERE/'audit.json';assert not out.exists();out.write_text(json.dumps(audit,indent=2)+'\n');print('audit_sha256',sha(out))
