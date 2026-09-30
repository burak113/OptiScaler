"""Scientific native-output plots. Relative and absolute failures stay visible."""
from pathlib import Path
import hashlib,json
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT=Path(__file__).resolve().parents[1]
CROOT=Path('C:/Users/burak/.codex/visualizations/2026/09/29/01a0eeeb-48a8-7733-add1-58a3bd1f37ce')
OUT=ROOT/'docs/evidence/fsrd_response_followup_figures'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
    if OUT.exists():raise ValueError('Preserve previous figures')
    reports={n:json.loads((CROOT/f'response_soft_temporal{suffix}_alpha_fresh/results.json').read_text())
        for n,suffix in ((16,''),(64,'_long'))}
    if any(r['status']!='completed_research_not_solution' for r in reports.values()):raise ValueError('Wait for complete matrices')
    OUT.mkdir(parents=True)
    provenance=dict(script_sha256=sha(__file__),native_quality_accepted=False,game_run=False,reports={},arrays=[])
    for n,r in reports.items():
        provenance['reports'][str(n)]=sha(CROOT/('response_soft_temporal'+('_long' if n==64 else '')+'_alpha_fresh')/'results.json')
    scenes=('material','wave','reset','weak_material')
    fig,axes=plt.subplots(2,2,figsize=(11,7),constrained_layout=True)
    x=np.arange(len(scenes));colors=['#6686a7','#e39a2d','#16817a']
    for j,(label,color) in enumerate(zip(('native baseline','history 16','history 64'),colors)):
        values=[]
        for scene in scenes:
            row=next(r for r in reports[64 if j!=1 else 16]['rows'] if r['scene']==scene)
            values.append((row['baseline_mature'] if j==0 else row['variants']['soft_temporal_dc_current_safe']['mature'])['residual_temporal_std'])
        axes[0,0].bar(x+(j-1)*.24,np.array(values)*1e3,width=.24,color=color,label=label)
    axes[0,0].set_xticks(x,scenes);axes[0,0].set_ylabel('Mature residual temporal STD × 1000');axes[0,0].legend(fontsize=8)
    for n,color in ((16,colors[1]),(64,colors[2])):
        weak=next(r for r in reports[n]['rows'] if r['scene']=='weak_material')['variants']['soft_temporal_dc_current_safe']
        axes[0,1].plot(weak['full']['contrast_gain'],label=f'history {n}',color=color)
        light=next(r for r in reports[n]['rows'] if r['scene']=='lighting_step')['variants']['soft_temporal_dc_current_safe']
        axes[1,0].plot(light['full']['contrast_gain'],label=f'history {n}',color=color)
        row=next(r for r in reports[n]['rows'] if r['scene']=='wave')
        folder=Path(row.get('evidence_directory') or CROOT/f'response_soft_temporal{ "_long" if n==64 else ""}_alpha_fresh'/'wave')
        p=folder/'sequences.npz';before=sha(p)
        with np.load(p) as a:
            value=a['soft_temporal_dc_current_safe'];truth=a['clean_reference'];baseline=a['baseline']
            if n==64:
                axes[1,1].plot(truth[-16:,40,:,0].mean(0),color='black',label='synthetic clean reference',lw=2)
                axes[1,1].plot(baseline[-16:,40,:,0].mean(0),color=colors[0],label='native baseline')
            axes[1,1].plot(value[-16:,40,:,0].mean(0),color=color,label=f'history {n}',alpha=.85)
        if sha(p)!=before:raise ValueError('Source array changed')
        provenance['arrays'].append(dict(path=str(p),sha256=before))
    for ax,title in ((axes[0,1],'Weak material: absolute per-frame gain'),(axes[1,0],'Textured lighting: absolute per-frame gain')):
        ax.axhspan(.95,1.05,color='#6aa678',alpha=.15,label='±5% detail interval');ax.axhline(1,color='gray',lw=.6)
        ax.set_title(title,fontsize=10);ax.set_xlabel('Frame');ax.set_ylabel('Gain versus clean reference');ax.legend(fontsize=8)
    axes[1,1].set_title('Stationary wave: mature red-channel row 40',fontsize=10)
    axes[1,1].set_xlabel('Pixel x');axes[1,1].set_ylabel('Linear radiance');axes[1,1].legend(fontsize=8)
    fig.suptitle('Fresh native alpha research — synthetic radiance, split 1, seed 920531\nQuality remains unaccepted; lighting null divergence and shared bias require diagnosis',fontsize=12)
    png=OUT/'native_history_comparison.png';fig.savefig(png,dpi=150);plt.close(fig)
    provenance['figure_sha256']=sha(png)
    (OUT/'provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
    print(str(png))
if __name__=='__main__':main()
