"""Independent root checks of frozen source-only prototype; no GPU/truth input."""
from pathlib import Path
import hashlib,importlib.util,inspect,json
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/'tools_tmp/phase_source_dc_normalized_feasibility_20260930'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
    dest=Path(__file__).with_name('review.json')
    if dest.exists():raise ValueError('Preserve review')
    module=SOURCE/'normalized_pilot.py';hashes={p.name:sha(p) for p in SOURCE.iterdir() if p.suffix=='.json' or p.name=='normalized_pilot.py'}
    freeze=json.loads((SOURCE/'pre_score_freeze.json').read_text())
    assert all(sha(SOURCE/name)==value for name,value in freeze['sources'].items())
    spec=importlib.util.spec_from_file_location('candidate',module);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    fn=m.make_dc_normalized_phase_pilot;assert list(inspect.signature(fn).parameters)==['raw','controls']
    rng=np.random.default_rng(594113);y,x=np.indices((8,16));base=.2+.01*np.cos(2*np.pi*x/16+2*np.pi*y/8)
    raw=np.repeat(base[None,...,None],40,axis=0)*np.ones((1,1,1,3))+rng.normal(0,.006,(40,8,16,3))
    ctrl=np.zeros((40,3));ctrl[0,0]=1
    a,act,d=fn(raw,ctrl);changed=raw.copy();changed[21:]+=.08;cc=ctrl.copy();cc[28:,0]=.5
    b,_,_=fn(changed,cc);np.testing.assert_array_equal(a[:21],b[:21])
    pure=np.repeat(base[None,...,None],40,axis=0)*np.array([1.,1.2,.8])
    scale=np.linspace(.6,1.8,40)[:,None,None,None];p,pa,_=fn(pure*scale,ctrl)
    np.testing.assert_allclose(p,pure*scale,rtol=0,atol=1e-14);assert pa.all()
    invalid=raw.copy();invalid[11,...,1]=1e-5;p,pa,diag=fn(invalid,ctrl)
    np.testing.assert_array_equal(p[11],invalid[11]);assert not pa[11] and diag['frames'][12]['preceding_observations']==0
    result=json.loads((SOURCE/'results.json').read_text());assert result['quality_accepted'] is False and result['native_measured'] is False
    assert len(result['rows'])==13 and len(result['counterexamples'])==11
    assert all(sha(SOURCE/name)==value for name,value in hashes.items())
    report=dict(schema='DC-normalized-source-root-independent-review-v1',review_source_sha256=sha(__file__),source_hashes=hashes,
        all_source_files_unchanged=True,no_GPU_calls=True,quality_accepted=False,independent_seed=594113,
        independent_no_future=True,noiseless_multiplicative_closure=True,nearzero_exact_raw_and_fresh_epoch=True,
        estimator_API_only_raw_and_controls=True,source_families=13,adversaries=11,
        math_scope=['qG ratio variance is first-order marginal under numerator/DC independence, not exact proper-complex ratio noise.',
            'Shared denominator induces coefficient covariance and noncircular noise; pooled phase SE remains nominal.',
            'Restoration Cauchy RMS is diagnostic only; current-selected coefficient algebra restores F exactly.',
            'No actual covariance/effective sample count or native response enters estimator; source failures reject general solution.'])
    dest.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(dict(path=str(dest),sha256=sha(dest))))
if __name__=='__main__':main()
