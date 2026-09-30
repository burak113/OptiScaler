"""Static scientific visualization of retained identical-input native variation."""
from pathlib import Path
import hashlib,json
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT=Path(__file__).resolve().parents[2];HERE=Path(__file__).resolve().parent
SOURCE=ROOT/'tools_tmp/native_guide_alpha_wave_continuation_20260930/evidence/wave'
AUDIT=ROOT/'tools_tmp/native_guide_alpha_independent_audit_20260930/audit.json'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 if (HERE/'manifest.json').exists():raise ValueError('Preserve figure')
 assert sha(AUDIT)=='dd58d1b81702d4dfa60b375e695fa4646b8c04668b37180220614f4b65e93a4e'
 a=SOURCE/'original';b=SOURCE/'source_alpha';pins={str(AUDIT):sha(AUDIT),str(HERE/'render.py'):sha(HERE/'render.py')}
 for i in range(7):assert sha(a/f'input{i}.bin')==sha(b/f'input{i}.bin')
 assert sha(a/'dispatch_controls.bin')==sha(b/'dispatch_controls.bin')
 for p in list(a.glob('input*.bin'))+list(b.glob('input*.bin'))+[a/'dispatch_controls.bin',b/'dispatch_controls.bin']:
  pins[str(p)]=sha(p)
 deltas={}
 for name in ('diffuse','specular'):
  left=a/(name+'.bin');right=b/(name+'.bin');pins[str(left)]=sha(left);pins[str(right)]=sha(right)
  aa=np.fromfile(left,'<f2').reshape(64,80,128,4).astype(float);bb=np.fromfile(right,'<f2').reshape(64,80,128,4).astype(float)
  assert np.isfinite(aa).all()and np.isfinite(bb).all();assert np.array_equal(aa[...,3],bb[...,3])
  deltas[name]=np.sqrt(np.mean((aa[...,:3]-bb[...,:3])**2,axis=-1))
 # Descriptive frames from already audited maxima; no candidate or quality selection.
 frames=(7,59);limit=max(float(d[frame].max())for d in deltas.values()for frame in frames)
 fig=plt.figure(figsize=(10,8),layout='constrained');grid=fig.add_gridspec(3,2,height_ratios=(1,1,.85))
 for row,frame in enumerate(frames):
  for column,(name,d)in enumerate(deltas.items()):
   ax=fig.add_subplot(grid[row,column]);im=ax.imshow(d[frame],cmap='magma',vmin=0,vmax=limit,origin='upper')
   ax.set_title(f'{name.capitalize()} RGB difference RMS, frame {frame}');ax.set_xlabel('x pixel');ax.set_ylabel('y pixel')
 fig.colorbar(im,ax=fig.axes[:4],label='Per-pixel RGB RMS (raw FP16 radiance)',shrink=.8)
 ax=fig.add_subplot(grid[2,:])
 for name,d in deltas.items():ax.plot(np.arange(64),np.sqrt(np.mean(d*d,axis=(1,2))),label=name)
 ax.set_xlabel('Frame index');ax.set_ylabel('Whole-frame RGB RMS');ax.grid(alpha=.25);ax.legend()
 fig.suptitle('Synthetic wave: identical inputs, different fresh native contexts\nOriginal versus same-byte source-alpha control; diagnostic, not game-quality evidence',fontsize=12)
 p=HERE/'identical_input_native_variation.png';fig.savefig(p,dpi=150);plt.close(fig)
 assert all(sha(Path(p))==v for p,v in pins.items())
 result={'schema':'retained-native-identical-input-static-scientific-visual-v1','quality_accepted':False,
  'new_native_contexts':0,'source_pins':pins,'frames':[7,59],
  'selection':'Previously audited largest temporal/global pixel differences, descriptive only',
  'all7_inputs_and_controls_exact':True,'outputs':{p.name:sha(p)}}
 (HERE/'manifest.json').write_text(json.dumps(result,indent=2)+'\n');print(p)
if __name__=='__main__':main()
