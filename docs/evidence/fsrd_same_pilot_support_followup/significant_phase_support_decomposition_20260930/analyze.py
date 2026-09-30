"""Read-only AST hook: exact saved P support/mean/FP16 variance diagnostic."""
from pathlib import Path
import ast,hashlib,importlib.util,json
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/'tools_tmp/native_significant_phase_initial_20260930/evidence'
PROTO=ROOT/'tools_tmp/significant_phase_pilot_feasibility_20260930/significant_pilot.py'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
class Hook(ast.NodeTransformer):
    def visit_Expr(self,node):
        self.generic_visit(node)
        call=node.value
        if isinstance(call,ast.Call) and isinstance(call.func,ast.Attribute) and isinstance(call.func.value,ast.Name) and call.func.value.id=='records' and call.func.attr=='append':
            return [node,ast.Expr(ast.Call(ast.Name('_readonly_snapshot',ast.Load()),
                [ast.Name(s,ast.Load()) for s in ('i','selected','keep','innovation','used')],[]))]
        return node
def centered(a):return a-a.mean(0,keepdims=True)
def main():
    dest=Path(__file__).with_name('results.json')
    if dest.exists():raise ValueError('Preserve evidence')
    text=PROTO.read_text();tree=ast.fix_missing_locations(Hook().visit(ast.parse(text)))
    transformed=ast.unparse(tree)+'\n';Path(__file__).with_name('instrumented_source.py').write_text(transformed)
    ns={};snapshots=[]
    def snapshot(i,selected,keep,innovation,used):
        snapshots.append(dict(frame=i,selected=selected.copy(),keep=keep.copy(),innovation=innovation.copy(),used=used.copy()))
    ns['_readonly_snapshot']=snapshot;exec(compile(tree,str(PROTO),'exec'),ns)
    spec=importlib.util.spec_from_file_location('unchanged_pilot',PROTO)
    original=importlib.util.module_from_spec(spec);spec.loader.exec_module(original)
    rp=SOURCE/'results.json';rh=sha(rp);report=dict(schema='significant-phase-support-coefficient-quantization-posthoc-v1',
        status='running',script_sha256=sha(__file__),prototype_sha256=sha(PROTO),source_report_sha256=rh,
        instrumented_source_sha256=sha(Path(__file__).with_name('instrumented_source.py')),
        quality_accepted=False,new_GPU_calls=0,estimator_implemented=False,rows=[],limitations=[
            'Descriptive posthoc decomposition, not a new pilot or old T(P) reuse with changed P.',
            'Window first support is a reference for algebra, not identified clean support.',
            'Mask contribution may include legitimate weak features and covariance; it is not a false-support fraction.',
            'Mean-coefficient contribution also includes genuine signal/noise/settling; no clean truth read.',
            'RMS is sqrt(mean variance), not the mean pixel STD quality gate.'])
    for scene in ('material','wave','reset'):
        sp=SOURCE/scene/'sequences.npz';sh=sha(sp);cp=SOURCE/scene/'observed/frame_controls.txt';ch=sha(cp)
        with np.load(sp) as a:raw=a['observed'].copy();saved=a['pilot'].copy();saved_active=a['active'].copy()
        ctrl=np.loadtxt(cp,ndmin=2);snapshots.clear()
        pilot,active,diag=ns['make_significant_phase_pilot'](raw,ctrl)
        direct,da,dd=original.make_significant_phase_pilot(raw,ctrl)
        np.testing.assert_array_equal(pilot,direct);np.testing.assert_array_equal(active,da);assert diag==dd
        np.testing.assert_array_equal(pilot.astype(np.float16).astype(np.float32),saved)
        np.testing.assert_array_equal(active,saved_active);assert active.all() and len(snapshots)==len(raw)
        h,w=raw.shape[1:3];n=h*w;windows={}
        for label,start in [('full',0),('mature',48)]:
            masks=np.stack([s['keep'] for s in snapshots[start:]])
            fixed=masks[0]
            coeff=np.stack([np.fft.irfft2(s['selected']*fixed[...,None]*n,s=(h,w),axes=(0,1)) for s in snapshots[start:]])
            dynamic=pilot[start:]-coeff;quant=saved[start:].astype(float)-pilot[start:]
            components=np.stack([coeff,dynamic,quant])[:,:,5:-5,5:-5]
            cen=components-components.mean(1,keepdims=True)
            cov=np.einsum('rtxyc,stxyc->rs',cen,cen)/(np.prod(cen.shape[1:]))
            target=centered(saved[start:,5:-5,5:-5].astype(float));actual=float(np.mean(target**2))
            np.testing.assert_allclose(cov.sum(),actual,rtol=1e-12,atol=1e-22)
            np.testing.assert_allclose(components.sum(0),saved[start:,5:-5,5:-5],rtol=0,atol=1e-16)
            records=diag['frames'][start:]
            windows[label]=dict(first_frame=start,components=['coefficients_on_first_window_support','changing_support_relative_to_first','FP16_rounding'],
                component_covariance_matrix=cov.tolist(),actual_temporal_variance=actual,
                covariance_identity_error=abs(cov.sum()-actual),support_count_min=int(masks.sum((1,2)).min()),
                support_count_max=int(masks.sum((1,2)).max()),support_count_mean=float(masks.sum((1,2)).mean()),
                mean_adjacent_mask_changes=float(np.count_nonzero(masks[1:]!=masks[:-1],axis=(1,2)).mean()),
                changed_at_least_once_frequencies=int(np.any(masks!=fixed,axis=0).sum()),
                mature_or_full_used_phase_mean=float(np.mean([r['retained_used_phase_frequencies'] for r in records])),
                mature_or_full_innovation_mean=float(np.mean([r['retained_innovation_frequencies'] for r in records])))
        assert sha(sp)==sh and sha(cp)==ch and sha(PROTO)==report['prototype_sha256']
        report['rows'].append(dict(scene=scene,sequences_sha256=sh,controls_sha256=ch,unmodified_vs_hooked_return_exact=True,
            saved_FP16_pilot_exact=True,windows=windows))
        print(scene,windows['mature'],flush=True)
    assert sha(rp)==rh
    report['status']='completed_diagnostic_not_solution';dest.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
if __name__=='__main__':main()
