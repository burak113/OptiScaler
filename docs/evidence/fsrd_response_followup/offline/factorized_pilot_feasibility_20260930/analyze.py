"""Authenticated fixture reconstruction and source-pilot feasibility only."""
from pathlib import Path
import ast,importlib.util,json,sys
import numpy as np
from prototype import make_factorized_pilot,BLENDS

ROOT=Path(__file__).resolve().parents[2]
REFERENCE=ROOT/'tools_tmp/delta_history_offline_20260930/analyze.py'
spec=importlib.util.spec_from_file_location('reference',REFERENCE);ref=importlib.util.module_from_spec(spec);spec.loader.exec_module(ref)
from fsrd_response_soft_pilot import make_soft_temporal_spectral_pilot


def snapshot_fixture(root,report):
    ns={'np':np};hashes={}
    for filename,function in (('fsrd_alpha_common.py','rgba'),('probe_fsrd_statistical_resolve.py','fixture'),('probe_fsrd_response_calibration.py','research_fixture')):
        path=root/'source_snapshot'/filename;actual=ref.digest(path)
        if actual!=report['source_sha256'][filename]:raise ValueError('Frozen fixture snapshot SHA mismatch')
        hashes[filename]=actual
        tree=ast.parse(path.read_text());node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==function)
        exec(compile(ast.Module(body=[node],type_ignores=[]),str(path),'exec'),ns)
    return ns['research_fixture'],hashes


def regenerate(scene,report,fixture):
    w,h=report['size'];frames=report['frames'];seed=report['seed']
    data=fixture(scene,w,h,frames,seed);rng=np.random.default_rng(seed+6131)
    noise=rng.normal(0,report['noise_sigma'],data['truth'].shape)
    observed=(data['truth']+noise).astype(np.float16).astype(np.float32)
    if scene=='persistent_shared_bias':
        y,x=np.indices((h,w));common=.015*np.sin(.33*x+.13*y)[...,None]*np.array([1,.8,.6])
        observed=(observed+common).astype(np.float16).astype(np.float32)
        data['spec'][...,:3]=(.2+.5*common+rng.normal(0,.0002,data['truth'].shape)).astype(np.float16).astype(np.float32)
    if scene=='guide_noise':data['spec'][...,:3]=(.2+.5*(observed-data['truth'])).astype(np.float16).astype(np.float32)
    return observed,data


def self_checks():
    rng=np.random.default_rng(710);y,x=np.indices((24,32));shape=.03*np.sin(2*np.pi*(3*x/32+2*y/24))
    raw=.2+shape[None,...,None]+rng.normal(0,.012,(24,24,32,3))
    diff=np.broadcast_to(.3+shape[None,...,None],raw.shape).copy();spec=np.full_like(raw,.05)
    ctrl=np.zeros((len(raw),3));ctrl[0,0]=1
    for blend in BLENDS:
        p,a,d=make_factorized_pilot(raw,diff,spec,ctrl,blend)
        qraw=raw.copy();qraw[18:]+=.1;q,_,_=make_factorized_pilot(qraw,diff,spec,ctrl,blend)
        np.testing.assert_array_equal(p[:18],q[:18]);assert max(f['residual_history_count'] for f in d['frames'])<=16
        cc=ctrl.copy();cc[10,0]=1;cc[17:,1:]=[.25,.125]
        p,a,d=make_factorized_pilot(raw,diff,spec,cc,blend)
        for i in (0,10,17):
            alone,_,_=make_factorized_pilot(raw[i:i+1],diff[i:i+1],spec[i:i+1],ctrl[:1],blend)
            np.testing.assert_array_equal(p[i],alone[0]);assert d['frames'][i]['guide_history_count']==0
        np.testing.assert_allclose(p.mean((1,2)),raw.mean((1,2)),atol=1e-14)
        constant=np.full_like(raw,.2);fake=np.broadcast_to(.15+.15*(x>16)[None,...,None],raw.shape).copy()
        p,a,_=make_factorized_pilot(constant,fake,spec,ctrl,blend)
        np.testing.assert_allclose(p,constant,atol=1e-14);assert a.all()
        no=np.zeros_like(raw);p,_,_=make_factorized_pilot(raw,no,no,ctrl,blend)
        q,_,_=make_soft_temporal_spectral_pilot(raw,ctrl);np.testing.assert_allclose(p,q,atol=1e-14)
        bad=diff.copy();bad[12]=np.nan;p,a,d=make_factorized_pilot(raw,bad,spec,ctrl,blend)
        assert d['frames'][12]['guide_fit']['reason']=='invalid_guides_spectral_only';assert np.isfinite(p).all()
    return dict(no_future=True,reset_jitter_fresh_equivalence=True,bounded_history=True,current_DC=True,
        false_guide_constant_source_not_copied=True,unrepresented_guide_matches_spectral=True,invalid_guides_spectral_path=True)


def moments(p,truth):
    m=ref.score(p,truth,None);g=[x for x in m['contrast_gain'] if x is not None];phase=[x for x in m['phase_error_radians'] if x is not None]
    return dict(score=m,absolute_gain_min=min(g) if g else None,absolute_gain_mean=float(np.mean(g)) if g else None,
        absolute_gain_max=max(g) if g else None,absolute_phase_max=max(phase) if phase else None,
        detail_within_5_percent_all_frames=bool(all(.95<=x<=1.05 for x in g)) if g else None)


def main():
    output=Path(__file__).with_name('results.json')
    if output.exists():raise ValueError('Preserve prior feasibility')
    folder=ref.EVIDENCE/'response_temporal_spectral_alpha_holdout';rp=folder/'results.json';rh=ref.digest(rp);native=json.loads(rp.read_text())
    fixture,hashes=snapshot_fixture(folder,native)
    report=dict(schema='factorized-source-pilot-feasibility-v1',quality_accepted=False,native_measured=False,
        native_response_reused=False,game_run=False,runtime_implemented=False,script_sha256=ref.digest(__file__),
        prototype_sha256=ref.digest(Path(__file__).with_name('prototype.py')),frozen_fixture_sources=hashes,
        frozen_soft_pilot_sha256=ref.digest(ref.TESTS/'fsrd_response_soft_pilot.py'),metric_source_sha256=ref.digest(ref.TESTS/'probe_fsrd_statistical_resolve.py'),
        self_checks=self_checks(),source_inputs=['raw RGB','diffuse/specular guide RGB','native reset/jitter controls','preregistered blend'],
        limitations=['Only source pilot is scored; new native T(P) is unavailable and never substituted.',
            'Frozen alpha holdout reuse is post-hoc, not independent pilot validation.',
            'Truth is used only by authenticated fixture construction/match and score calls, never estimator.',
            'Absolute detail metrics are separate from relative quality gates.',
            'Spatial noise independence/single-surface correlation and persistent bias cannot be proved by fitting.'],rows=[])
    for row in native['rows']:
        scene=row['scene'];sp=folder/scene/'sequences.npz';cp=folder/scene/'observed/frame_controls.txt';sh=ref.digest(sp);ch=ref.digest(cp)
        observed,data=regenerate(scene,native,fixture)
        with np.load(sp) as saved:
            if not np.array_equal(observed,saved['observed']) or not np.array_equal(data['truth'],saved['clean_reference']):raise ValueError('Frozen observed/reference fixture mismatch')
            controls=ref.controls_from_native(cp,len(observed));np.testing.assert_array_equal(controls,data['controls'])
            candidates={};diagnostics={};soft,sa,sd=make_soft_temporal_spectral_pilot(observed,controls)
            candidates['soft_reference']=(soft,sa);diagnostics['soft_reference']=sd
            for blend in BLENDS:
                p,a,d=make_factorized_pilot(observed,data['diff'][...,:3],data['spec'][...,:3],controls,blend)
                candidates[blend]=(p,a);diagnostics[blend]=d
            metrics={}
            for name,(p,active) in candidates.items():
                p=p.astype(np.float16).astype(np.float32)
                metrics[name]=dict(active_fraction=float(active.mean()),full=moments(p,saved['clean_reference']),
                    mature=moments(p[-16:],saved['clean_reference'][-16:]))
            # Guides were constructed from authenticated fixture sources. Their
            # bytes are recorded; original upload guide arrays were not stored.
            guide_hashes={name:__import__('hashlib').sha256(data[name][...,:3].astype('<f4').tobytes()).hexdigest() for name in ('diff','spec')}
        unchanged=ref.digest(rp)==rh and ref.digest(sp)==sh and ref.digest(cp)==ch;assert unchanged
        report['rows'].append(dict(scene=scene,source_files_unchanged=unchanged,
            authenticated_observed_truth_controls_exact_match=True,guide_generation='Frozen authenticated snapshot + saved seed; RGB upload arrays not retained separately',
            regenerated_guide_rgb_sha256=guide_hashes,provenance=dict(native_report_sha256=rh,native_sequences_sha256=sh,native_controls_sha256=ch),
            diagnostics=diagnostics,metrics=metrics))
        print(scene,{name:dict(std=v['mature']['score']['residual_temporal_std'],rmse=v['mature']['score']['rmse'],gain=v['mature']['absolute_gain_mean'],phase=v['mature']['absolute_phase_max']) for name,v in metrics.items()},flush=True)
    report['status']='completed_source_pilot_feasibility_not_native_solution'
    output.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')


if __name__=='__main__':main()
