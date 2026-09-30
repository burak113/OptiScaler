"""Scientific diagnostic: observed repeat variation, not quality confidence."""
from pathlib import Path
import hashlib,json
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'tools_tmp/held_normal_followup_plot_20260930'
if OUT.exists():raise ValueError('Preserve plot package')
OUT.mkdir()
paths=[ROOT/'tools_tmp/frozen_source_context_repeat_20260930/evidence/results.json',
       ROOT/'tools_tmp/oct_corner_native_equivalence_20260930/evidence/results.json']
reports=[json.loads(p.read_text()) for p in paths]
fig,axes=plt.subplots(2,1,figsize=(9,7),sharex=True,layout='constrained')
for row in reports[0]['pairwise']:
    axes[0].plot(row['RGB']['frame_rms'],label=f"{row['first']}/{row['second']}",lw=1)
axes[0].set_title('Seven held inputs: six pairs of four native contexts')
axes[0].set_ylabel('Native lobe RGB RMS difference')
axes[0].legend(ncol=6,fontsize=8)
for arm,color in [('baseline','black'),('opposite_constant','#c84937'),('opposite_step','#287b9e')]:
    rows=[r['RGB']['frame_rms'] for r in reports[1]['within_arm'] if r['arm']==arm]
    axes[1].plot(np.max(rows,axis=0),label=f'{arm}: max observed within-arm pair',color=color)
cross=[r['RGB']['frame_rms'] for r in reports[1]['cross_arm'] if r['arm']=='opposite_step']
axes[1].plot(np.max(cross,axis=0),label='step vs baseline: max observed pair',color='#70a93d',linestyle='--')
axes[1].axvline(32,color='.5',lw=1,linestyle=':',label='normal representation step')
axes[1].set_title('Equivalent local/sample oct normals; four contexts per arm')
axes[1].set_xlabel('Frame');axes[1].set_ylabel('Native lobe RGB RMS difference');axes[1].legend(fontsize=8)
for ax in axes:ax.grid(alpha=.2);ax.ticklabel_format(axis='y',style='sci',scilimits=(0,0))
fig.suptitle('Observed context variation persists with held inputs\nOct representation step matches baseline in this fixture',fontsize=12)
path=OUT/'held_inputs_and_oct_repeat.png';fig.savefig(path,dpi=150);plt.close(fig)
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
(OUT/'provenance.json').write_text(json.dumps(dict(script_sha256=sha(__file__),
    inputs=[dict(path=str(p),sha256=sha(p)) for p in paths],output_sha256=sha(path),
    quality_accepted=False,interpretation='Observed maxima are descriptive, not population confidence bounds.'),indent=2)+'\n')
print(path)
