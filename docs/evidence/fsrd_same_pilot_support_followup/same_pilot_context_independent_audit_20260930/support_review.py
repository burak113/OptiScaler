"""Independent no-truth AST-hook and support covariance identity review."""
from pathlib import Path
import ast,hashlib,importlib.util,json
import numpy as np
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
PRODUCER=ROOT/'tools_tmp/significant_phase_support_decomposition_20260930'
PROTO=ROOT/'tools_tmp/significant_phase_pilot_feasibility_20260930/significant_pilot.py'
SOURCE=ROOT/'tools_tmp/native_significant_phase_initial_20260930/evidence'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text())
class RemoveHook(ast.NodeTransformer):
    def visit_Expr(self,node):
        if isinstance(node.value,ast.Call) and isinstance(node.value.func,ast.Name) and node.value.func.id=='_readonly_snapshot':return None
        return self.generic_visit(node)
class AddOwnHook(ast.NodeTransformer):
    def visit_Expr(self,node):
        self.generic_visit(node)
        v=node.value
        if isinstance(v,ast.Call) and isinstance(v.func,ast.Attribute) and isinstance(v.func.value,ast.Name) and v.func.value.id=='records' and v.func.attr=='append':
            return [node,ast.Expr(ast.Call(ast.Name('_audit_snapshot',ast.Load()),[ast.Name(n,ast.Load()) for n in ('i','selected','keep')],[]))]
        return node
def main():
    if (HERE/'support_review.json').exists():raise ValueError('Preserve review')
    r=read(PRODUCER/'results.json'); assert r['status']=='completed_diagnostic_not_solution'
    assert sha(PRODUCER/'analyze.py')==r['script_sha256'] and sha(PRODUCER/'instrumented_source.py')==r['instrumented_source_sha256']
    assert sha(PROTO)==r['prototype_sha256'] and sha(SOURCE/'results.json')==r['source_report_sha256']
    orig=ast.parse(PROTO.read_text()); removed=RemoveHook().visit(ast.parse((PRODUCER/'instrumented_source.py').read_text()))
    assert ast.dump(orig,include_attributes=False)==ast.dump(removed,include_attributes=False)
    snapshots=[]
    def capture(i,selected,keep):snapshots.append((i,selected.copy(),keep.copy()))
    ns={'_audit_snapshot':capture};tree=ast.fix_missing_locations(AddOwnHook().visit(ast.parse(PROTO.read_text())))
    exec(compile(tree,'independent-readonly-hook','exec'),ns)
    spec=importlib.util.spec_from_file_location('immutable_phase_for_review',PROTO);old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
    results=[]
    for row in r['rows']:
        scene=row['scene'];sp=SOURCE/scene/'sequences.npz';cp=SOURCE/scene/'observed/frame_controls.txt'
        assert sha(sp)==row['sequences_sha256'] and sha(cp)==row['controls_sha256']
        with np.load(sp) as z:raw=z['observed'].copy();saved=z['pilot'].copy();sa=z['active'].copy()
        ctrl=np.loadtxt(cp,ndmin=2);snapshots.clear()
        p,a,d=ns['make_significant_phase_pilot'](raw,ctrl);direct,da,dd=old.make_significant_phase_pilot(raw,ctrl)
        np.testing.assert_array_equal(p,direct);np.testing.assert_array_equal(a,da);assert d==dd
        np.testing.assert_array_equal(p.astype('f2').astype('f4'),saved);np.testing.assert_array_equal(a,sa)
        assert a.all() and len(snapshots)==64
        h,w=p.shape[1:3];windows={}
        for label,start in [('full',0),('mature',48)]:
            masks=np.stack([z[2] for z in snapshots[start:]]); first=masks[0]
            A=np.stack([np.fft.irfft2(z[1]*first[...,None]*(h*w),s=(h,w),axes=(0,1)) for z in snapshots[start:]])
            B=p[start:]-A;Q=saved[start:].astype(float)-p[start:]
            np.testing.assert_allclose(A+B+Q,saved[start:],rtol=0,atol=1e-16)
            components=np.stack([A,B,Q])[:,:,5:-5,5:-5];centered=components-components.mean(1,keepdims=True)
            flat=centered.reshape(3,-1);cov=flat@flat.T/flat.shape[1]
            target=saved[start:,5:-5,5:-5].astype(float);target-=target.mean(0,keepdims=True);var=float(np.mean(target**2))
            expected=row['windows'][label];np.testing.assert_allclose(cov,expected['component_covariance_matrix'],rtol=1e-11,atol=1e-22)
            np.testing.assert_allclose(cov.sum(),var,rtol=1e-12,atol=1e-22)
            count=masks.sum((1,2));changes=int(np.any(masks!=first,0).sum());adj=float(np.count_nonzero(masks[1:]!=masks[:-1],axis=(1,2)).mean())
            assert changes==expected['changed_at_least_once_frequencies'] and count.min()==expected['support_count_min'] and count.max()==expected['support_count_max']
            assert adj==expected['mean_adjacent_mask_changes']
            np.testing.assert_allclose(var,expected['actual_temporal_variance'],rtol=1e-12,atol=1e-22)
            records=d['frames'][start:]
            phase=float(np.mean([z['retained_used_phase_frequencies'] for z in records]));innovation=float(np.mean([z['retained_innovation_frequencies'] for z in records]))
            assert phase==expected['mature_or_full_used_phase_mean'] and innovation==expected['mature_or_full_innovation_mean']
            windows[label]=dict(reference_frame=start,component_covariance_matrix=cov.tolist(),actual_variance=var,identity_error=float(abs(cov.sum()-var)),
                support_min=int(count.min()),support_max=int(count.max()),support_mean=float(count.mean()),changed_at_least_once=changes,
                adjacent_change_mean=adj,retained_phase_mean=phase,retained_innovation_mean=innovation)
        results.append(dict(scene=scene,saved_source_and_pilot_hash_exact=True,unhooked_vs_independent_hook_P_active_diagnostics_exact=True,windows=windows))
        print(scene,'support review pass',windows['mature']['changed_at_least_once'],flush=True)
    out=dict(schema='support-decomposition-independent-review-v1',status='completed_diagnostic_not_solution',quality_accepted=False,
        producer_result_sha256=sha(PRODUCER/'results.json'),producer_script_sha256=r['script_sha256'],prototype_sha256=sha(PROTO),
        producer_instrumented_source_sha256=r['instrumented_source_sha256'],audit_source_sha256=sha(__file__),
        removing_only_observer_call_restores_original_AST_exact=True,truth_fields_not_read=True,new_GPU_calls=0,rows=results,
        conclusions=['Static mature material/wave/reset support changes occur while retained phase use is0 and retained innovation rare/0',
            'Changing-support B variance is descriptively large; B also includes real weak details and covariance, so B/total is not a causal noise fraction',
            'First-window support atframe48 is an algebra reference, not clean/safe support or a proposed filter',
            'A includes genuine signal, noisy coefficients and settling; exact A+B+Q identity does not label errors',
            'Variance is fullRGB5px interior70x118, temporal64/16; sqrtvariance differs from meanpixelSTD acceptancegate',
            'No changedP/nativeT(P) substitution, production change, confidence, image quality acceptance or game fix'])
    (HERE/'support_review.json').write_text(json.dumps(out,indent=2,allow_nan=False)+'\n');print('support review SHA',sha(HERE/'support_review.json'),flush=True)
if __name__=='__main__':main()
