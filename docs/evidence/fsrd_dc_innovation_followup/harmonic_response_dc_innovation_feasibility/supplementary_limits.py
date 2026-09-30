"""Post-score fixed-model selfchecks; no threshold/model change or tuning."""
from pathlib import Path
import json,hashlib
import numpy as np
from model import make_source_dc_innovation_target
HERE=Path(__file__).resolve().parent;rng=np.random.default_rng(413729)
noise=rng.normal(0,.012,(80,30,40,3)).astype('f4');raw=.2+noise;ctrl=np.zeros((80,3));ctrl[0,0]=1
quiet,V,D=make_source_dc_innovation_target(raw,ctrl);mu=raw[:,5:-5,5:-5].mean((1,2),dtype=float)
assert np.max(np.var(quiet[-16:],axis=0)/np.var(mu[-16:],axis=0))<1
slow=(raw+np.arange(80,dtype='f4')[:,None,None,None]*1e-5).astype('f4');target,V,E=make_source_dc_innovation_target(slow,ctrl)
lag=float(np.mean(target[-16:,0]-(.2+np.arange(64,80)*1e-5)))
assert abs(lag)>1e-5
shared=np.full_like(raw,.2)+np.repeat(noise[...,:1].mean((1,2),keepdims=True),3,axis=-1)
S,V,F=make_source_dc_innovation_target(shared,ctrl)
# A spatially shared RGB fluctuation has nearly zero nonDC FFT noise estimate;
# this nominal IID rule selects current instead of identifying shared noise.
np.testing.assert_allclose(S,shared[:,5:-5,5:-5].mean((1,2),dtype=float),atol=1e-12)
out=dict(status='completed_postscore_fixed_model_limits_no_tuning',model_sha256=hashlib.sha256((HERE/'model.py').read_bytes()).hexdigest(),
         nominal_quiet_IID_target_to_observed_mean_variance_RGB=(np.var(quiet[-16:],axis=0)/np.var(mu[-16:],axis=0)).tolist(),
         slow_true_DC_drift_mature_mean_lag_R=lag,slow_source_mean_innovation_frames=[f['frame'] for f in E['frames'] if f.get('innovation')],
         spatially_shared_RGB_artifact_target_current_exact=True,shared_artifact_innovation_count=sum(bool(f.get('innovation')) for f in F['frames']),
         quality_accepted=False,scope='Counterexamples/selfchecks only; no estimator change or general variance guarantee.')
(HERE/'supplementary_limits.json').write_text(json.dumps(out,indent=2,allow_nan=False)+'\n');print(json.dumps(out))
