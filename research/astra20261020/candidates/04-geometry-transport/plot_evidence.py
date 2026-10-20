"""Optional static report figures; matplotlib is not needed for CPU test suites."""
from pathlib import Path
import argparse
import json
import numpy as np

HERE=Path(__file__).resolve().parent


def run(evidence):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    evidence=Path(evidence)
    with np.load(evidence/'phase_example.npz',allow_pickle=False) as z:
        fields={k:z[k] for k in z.files}
    fig,axes=plt.subplots(2,2,figsize=(11,9),layout='constrained')
    fig.suptitle('Analytic CPU boundary witness | 67 x 53 | angle 17 deg | phase 3.25 px',fontsize=14)
    for ax,key,title in zip(axes.flat,['truth','bilinear','supported','support_mass'],
            ['Per-pixel gain target','Ordinary bilinear','Certified support reconstruction','Accepted interpolation mass']):
        limits=(0,1) if key=='support_mass' else (.8,1)
        im=ax.imshow(fields[key],vmin=limits[0],vmax=limits[1],cmap='viridis',interpolation='nearest')
        ax.contour(fields['protected'],levels=[.5],colors=['#ef4444'],linewidths=.8)
        ax.set_title(title,fontsize=12);ax.set_xlabel('Local pixel x');ax.set_ylabel('Local pixel y')
        fig.colorbar(im,ax=ax,shrink=.8)
    fig.savefig(evidence/'boundary_witness.png',dpi=160)
    plt.close(fig)
    data=json.loads((evidence/'experiments.json').read_text())['temporal']['seeds']
    names=list(data)
    fig,axes=plt.subplots(1,2,figsize=(11,4.8),layout='constrained')
    for ax,metric,title in zip(axes,['matched_eligible_flicker_error_rms','matched_isolated_gain_noise_std'],
                                ['Flicker error at matched correction dose','Isolated gain-noise deviation at matched dose']):
        values=[100*data[s]['variants']['supported'][metric]/data[s]['variants']['bilinear'][metric] for s in names]
        ax.bar(names,values,color='#c55a38',width=.62)
        ax.axhline(100,color='#111827',linestyle='--',linewidth=1,label='Bilinear = 100')
        for i,v in enumerate(values):ax.text(i,v+1.5,f'{v:.1f}',ha='center',fontsize=11)
        ax.set_ylim(0,135);ax.set_title(title,fontsize=11);ax.set_xlabel('Independent injected-noise seed')
        ax.set_ylabel('Relative error (lower is better)');ax.legend(loc='upper left',fontsize=9)
    fig.suptitle('Negative temporal result | 48 chronological synthetic frames per seed',fontsize=13)
    fig.savefig(evidence/'temporal_tradeoff.png',dpi=160)
    plt.close(fig)
    return {'matplotlib':matplotlib.__version__,'figures':['boundary_witness.png','temporal_tradeoff.png']}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--evidence',type=Path,default=HERE/'evidence')
    args=parser.parse_args();print(json.dumps(run(args.evidence)))
