"""Independent identifiability/geometry counterexamples for research estimates."""
from pathlib import Path
import os
import numpy as np
from fsrd_allocation_models import estimate
from probe_fsrd_allocation_models import scene_data,assess
from fsrd_alpha_common import save_json


def run():
    checks=[]
    def check(name,pass_,**numbers):
        checks.append(dict(name=name,passed=bool(pass_),**numbers))
        print(('PASS ' if pass_ else 'FAIL ')+name,numbers,flush=True)
    def fit(a,mode='lobes'):
        return estimate(a['raw'][0],a['diff'],a['spec'],a['depth'],a['normals'],a['roughness'],mode)
    a=scene_data('fake_specular_clean',4,92813)
    p,m,d=fit(a)
    check('patterned specular is tested with real allocation activity',m[...,0].mean()>.1)
    check('constant diffuse can explain a false specular island',np.median(p[...,0][m[...,0]])<.01)
    po,mo,do=fit(a,'lobes_overlap')
    check('overlap field remains finite and bounded',np.isfinite(po).all() and np.all((po>=0)&(po<=1)))
    check('overlap cannot invent unsupported estimates',np.array_equal(mo,do['support_weight']>0))
    check('noiseless zero coefficients are not rejected as negative roundoff',not np.any(do['reason']==3))
    a=scene_data('collinear',4,92813)
    p,m,d=fit(a)
    check('collinear albedo bases are rejected',not m.any() and np.all(d['reason']==2))
    a=scene_data('wave_constant',4,92813)
    for mode in ('surface','lobes'):
        p,m,d=fit(a,mode)
        check(mode+' does not invent an intercept inside constant guides',not m.any())
    a=scene_data('independent_lobes',4,92813)
    p,m,d=fit(a)
    check('independent material bases remain identifiable',m.mean()>.4 and np.mean(d['rank']==2)>.99)
    a=scene_data('independent_lobes_additive',4,92813)
    p,m,d=fit(a)
    check('third term can be identified without routing it to specular',np.mean(d['additive_rank']==3)>.99
          and np.mean(d['reason']==8)>.95 and m.mean()<.01)
    a=scene_data('lighting_gradient',4,92813)
    p,m,d=fit(a)
    check('significant colored lighting plane competes with material explanation',np.mean(d['reason'][...,0]==5)>.6,
          rejected_fraction=float(np.mean(d['reason'][...,0]==5)))
    for boundary in ('depth','normal','roughness'):
        a=scene_data('independent_lobes',4,92813)
        w=a['depth'].shape[1]; half=w//2
        a['diff'][:,:half,:3]=.2; a['spec'][:,:half,:3]=.05; a['raw'][:,:,:half,:]=.14
        if boundary=='depth': a['depth'][:,half:]=40
        elif boundary=='normal': a['normals'][:,half:,:3]=[1,0,0]
        else: a['roughness'][:,half:]=.05
        p,m,d=fit(a)
        check(boundary+' prevents borrowing material evidence across the surface boundary',not m[:,:half].any())
    baseline=dict(target_rmse=.01,low_frequency_error_rms=.01,quiet_temporal_std=.01,
        broad_tone_rms=.01,bias_rgb=[0,0,0],ring_width_normalized=.1,
        detail_gain_truth_distance=0,frame_rmse=[.01]*64,effect_fraction_rgb=[0,0,0],actual_signal_changed=True)
    candidate=dict(baseline,target_rmse=.005)
    check('better metrics without actual activity cannot pass',
          not assess('fake_diffuse_clean',candidate,baseline,64)['effective_success'])
    candidate=dict(candidate,effect_fraction_rgb=[.2,0,0],ring_width_normalized=.5)
    check('estimated activity cannot substitute for changed AMD signal bytes',
          not assess('material_additive',dict(candidate,actual_signal_changed=False),baseline,64)['active'])
    check('a wider island ring fails despite lower RMSE',
          'ring_width' in assess('fake_specular_clean',candidate,baseline,64)['failures'])
    check('radial width has no ring meaning on material texture',
          'ring_width' not in assess('material_additive',candidate,baseline,64)['failures'])
    candidate=dict(candidate,ring_width_normalized=.1,bias_rgb=[.001,0,0])
    check('one-channel bias cannot hide behind lower aggregate RMSE',
          'signed_rgb_bias' in assess('fake_diffuse_clean',candidate,baseline,64)['failures'])
    early=[.005]*64; early[32]=.03
    candidate=dict(candidate,bias_rgb=[0,0,0],frame_rmse=early)
    check('first transition failure cannot hide in mature history',
          'early_transition' in assess('exposure_additive',candidate,baseline,64)['failures'])
    path=Path(os.environ.get('FSRD_GPU_TEST_OUTPUT','tools_tmp/alpha_model_contracts'))
    path.mkdir(parents=True,exist_ok=True)
    save_json(path/'results.json',dict(checks=len(checks),results=checks,passed=all(c['passed'] for c in checks)))
    if not all(c['passed'] for c in checks): raise SystemExit(1)


if __name__=='__main__': run()
