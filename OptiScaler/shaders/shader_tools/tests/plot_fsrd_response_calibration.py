"""Fixed-scale native response comparisons; synthetic metric truth is labeled."""
from pathlib import Path
import argparse
import json
import textwrap
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--variant',default='constant_flat_guided_dc_current')
    p.add_argument('--scenes',default='fake_diffuse,fake_specular,checker_material,weak_material')
    a=p.parse_args();report=json.loads((a.input/'results.json').read_text())
    if report['status']!='completed_research_not_solution':raise ValueError('Incomplete study')
    scenes=a.scenes.split(',');fig,axes=plt.subplots(len(scenes),4,figsize=(16,3.0*len(scenes)),constrained_layout=True,squeeze=False)
    fig.get_layout_engine().set(rect=(0,.04,1,.96))
    luma=np.array([.2126,.7152,.0722])
    last_image=None
    for r,scene in enumerate(scenes):
        row=next(v for v in report['rows'] if v['scene']==scene)
        with np.load(a.input/scene/'sequences.npz') as z:
            ref=z['clean_reference'][-16:].mean(0);base=z['baseline'][-16:].mean(0);candidate=z[a.variant][-16:].mean(0)
        for ax,title,v in zip(axes[r,:2],('Baseline RGB','Candidate RGB'),(base,candidate)):
            ax.imshow(np.sqrt(np.clip(4*v,0,1)),interpolation='nearest');ax.set_title(scene+'\n'+title,fontsize=10)
        for ax,title,v in zip(axes[r,2:],('Baseline signed error','Candidate signed error'),(base,candidate)):
            last_image=ax.imshow((v-ref)@luma,cmap='coolwarm',vmin=-.02,vmax=.02,interpolation='nearest')
            ax.set_title(title+' · luma')
        for ax in axes[r]:ax.set_xlabel('x (pixels)');ax.set_ylabel('y (pixels)')
        v=row['variants'][a.variant]
        failures=sorted(set(v['full_gate']['failures']+v['mature_gate']['failures']))
        status='FAIL: '+', '.join(failures) if failures else ('PASS / active improvement' if v['full_gate']['effective_success'] and v['mature_gate']['effective_success'] else 'Fallback; no effective fix')
        axes[r,1].set_xlabel('x (pixels)\nFull RMSE: %.6f → %.6f\n%s'%(row['baseline_full']['rmse'],v['full']['rmse'],textwrap.fill(status,34)),fontsize=8)
    fig.colorbar(last_image,ax=axes[:,2:].ravel().tolist(),label='Signed luma error to synthetic clean truth (linear RGB)')
    fig.suptitle(a.variant+' · actual AMD RR, last-16-frame mean\nSynthetic metric truth; no game quality acceptance',fontsize=13)
    fig.text(.01,.001,'Source: native-paired-response-research-v1 · seed %s · %s frames · RGB mapping sqrt(clamp(4 × RGB)); identical signed-error limits.'%(report['seed'],report['frames']),fontsize=8)
    a.output.parent.mkdir(parents=True,exist_ok=True);fig.savefig(a.output,dpi=140);plt.close(fig)


if __name__=='__main__':main()
