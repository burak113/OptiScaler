"""Engineering diagnostic: actual mature STD, not RMSE or acceptance score."""
from pathlib import Path
import hashlib,json
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT=Path(__file__).resolve().parents[1]
DEST=ROOT/'tools_tmp/phase_response_followup_plot_20260930'

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
    if DEST.exists():raise ValueError('Preserve prior artifact')
    a=ROOT/'tools_tmp/native_significant_phase_independent_audit_20260930/compact_report.json'
    b=ROOT/'tools_tmp/response_global_dc_offline_20260930/results.json'
    native={r['scene']:r for r in json.loads(a.read_text())['rows']}
    model={r['scene']:r for r in json.loads(b.read_text())['rows']}
    scenes=['material','wave','weak_material','reset'];x=np.arange(4)
    values=[np.array([native[s]['baseline_mature_STD'] for s in scenes]),
        np.array([native[s]['actual_mature_STD'] for s in scenes]),
        np.array([model[s]['variants']['global_dc_dc_current_safe']['mature']['residual_temporal_std'] for s in scenes])]
    fig,ax=plt.subplots(figsize=(11,5.4),layout='constrained')
    colors=['#406287','#D07235','#32887A']
    for j,(v,label,color) in enumerate(zip(values,['Native baseline','Significant phase + current DC','Global-DC response fit (posthoc)'],colors)):
        bars=ax.bar(x+(j-1)*.24,v*1e3,width=.23,label=label,color=color)
        ax.bar_label(bars,labels=[f'{q:.3f}' for q in v*1e3],padding=3,fontsize=9)
    ax.set_xticks(x,scenes);ax.set_ylim(0,max(v.max() for v in values)*1e3*1.18)
    ax.set_ylabel('Mean pixel temporal STD of RGB residual × 1000')
    ax.set_title('Mature frames 48–63: the correction still adds temporal noise',loc='left',pad=18)
    ax.legend(frameon=False,loc='upper left',fontsize=9);ax.grid(axis='y',alpha=.2);ax.set_axisbelow(True)
    fig.text(.02,.008,'128×80 synthetic inputs; actual fresh AMD P response. No game-quality acceptance. Lower is better.',fontsize=9,color='#555555')
    DEST.mkdir();png=DEST/'mature_residual_noise.png';fig.savefig(png,dpi=150);plt.close(fig)
    (DEST/'provenance.json').write_text(json.dumps(dict(script_sha256=sha(__file__),sources=[dict(path=str(p),sha256=sha(p)) for p in (a,b)],
        image_sha256=sha(png),native_contexts=18,native_RR_dispatches=1152,new_GPU_calls=0,quality_accepted=False),indent=2)+'\n')
    print(str(png))
if __name__=='__main__':main()
