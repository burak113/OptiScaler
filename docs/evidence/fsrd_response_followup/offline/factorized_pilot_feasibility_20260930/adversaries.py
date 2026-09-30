"""Preregistered correlated-guide and false-guide counterexample families.

Shared spatial noise is observationally interchangeable with real guide-linked
detail. Scoring truth is unavailable to the estimator and never passed to it.
"""
from pathlib import Path
import hashlib,json
import numpy as np
from prototype import make_factorized_pilot,BLENDS
from analyze import moments,make_soft_temporal_spectral_pilot

folder=Path(__file__).resolve().parent
output=folder/'adversaries.json'
if output.exists():raise ValueError('Preserve previous counterexamples')
rng=np.random.default_rng(43197);frames,h,w=32,64,96
controls=np.zeros((frames,3));controls[0,0]=1
bias=rng.normal(0,.012,(h,w,3))
# Static spatial bias is shared between the source and guide in all frames.
truth=np.full((frames,h,w,3),.2)
common=truth+bias[None]
spec=np.broadcast_to(.2+.5*bias[None],common.shape).copy()
diff=np.full_like(common,.2)
families={'persistent_spatial_noise_shared_with_guide':(common,diff,spec,truth)}
# Genuine Nyquist source detail with an unrelated spatial guide island.
y,x=np.indices((h,w));signal=.001*(2*((x+y)%2)-1)
truth=np.broadcast_to(.2+signal[None,...,None],(frames,h,w,3)).copy()
raw=truth+rng.normal(0,.012,truth.shape)
island=((x-w*.45)**2+(y-h*.55)**2)<(h*.15)**2
false=np.broadcast_to(.15+.3*island[None,...,None],raw.shape).copy()
families['weak_true_nyquist_unrelated_false_guide']=(raw,false,np.full_like(raw,.05),truth)
report=dict(schema='factorized-source-pilot-counterexamples-v1',quality_accepted=False,native_measured=False,
    prototype_sha256=hashlib.sha256((folder/'prototype.py').read_bytes()).hexdigest(),
    script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),rows=[])
for name,(raw,diff,spec,truth) in families.items():
    variants={};soft,active,_=make_soft_temporal_spectral_pilot(raw,controls)
    variants['soft_reference']=(soft,active)
    for blend in BLENDS:
        p,active,_=make_factorized_pilot(raw,diff,spec,controls,blend);variants[blend]=(p,active)
    metrics={n:dict(full=moments(p,truth),mature=moments(p[-16:],truth[-16:]),active_fraction=float(a.mean())) for n,(p,a) in variants.items()}
    report['rows'].append(dict(family=name,metrics=metrics,truth_used_for_scoring_only=True))
    print(name,{n:dict(rmse=m['mature']['score']['rmse'],std=m['mature']['score']['residual_temporal_std'],gain=m['mature']['absolute_gain_mean']) for n,m in metrics.items()})
report['status']='completed_counterexamples_not_solution'
output.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
