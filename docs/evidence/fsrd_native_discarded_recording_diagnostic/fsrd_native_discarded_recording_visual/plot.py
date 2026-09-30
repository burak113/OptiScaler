from pathlib import Path
import hashlib
import json

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / 'fsrd_native_discarded_recording_diagnostic_20260930/raw_comparisons.json'

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

data = json.loads(SOURCE.read_text())
assert data['producer_sha256'] == sha(SOURCE.parent / 'evidence/results.json')
assert len(data['comparisons']) == 28
series = {}
for name, pair in [
    ('baseline_vs_discard', 'round0_baseline__round0_discard24'),
    ('reset25_vs_fresh25', 'round0_discard24_reset25__round0_fresh_tail25'),
    ('baseline_repeat', 'round0_baseline__round1_baseline'),
]:
    aligned = data['comparisons'][pair]['common_source_frame']
    assert all(row['left_source_frame'] == row['right_source_frame'] and
               row['applied_184_bytes_exact'] for row in aligned['frames'])
    series[name] = {
        'pair': pair,
        'source_frames': [row['left_source_frame'] for row in aligned['frames']],
        'RGB_RMS': {lobe: aligned['lobes'][lobe]['RGB']['per_frame_RMS']
                    for lobe in ('diffuse.bin', 'specular.bin')},
    }

fig, axes = plt.subplots(2, 1, figsize=(11, 7.3), sharex=True, constrained_layout=True)
for axis, lobe in zip(axes, ('diffuse.bin', 'specular.bin')):
    for name, label, colour, style in [
        ('baseline_vs_discard', 'Baseline vs record24 discarded', '#b44916', '-'),
        ('reset25_vs_fresh25', 'Discard + RESET25 vs fresh at25', '#11785b', '--'),
        ('baseline_repeat', 'Baseline repeated', '#637181', ':'),
    ]:
        row = series[name]
        axis.plot(row['source_frames'], row['RGB_RMS'][lobe], label=label,
                  color=colour, linestyle=style, linewidth=1.8)
    axis.axvline(24, color='#888888', linestyle=':', linewidth=1)
    axis.set_ylabel(lobe.removesuffix('.bin') + '\nRGB RMS difference')
    axis.grid(alpha=0.2)
    axis.set_ylim(bottom=-0.00013)
axes[0].legend(loc='upper right', frameon=False)
axes[0].annotate('No measured output at frame24', xy=(24, 0.00012),
                 xytext=(4, 0.0022), arrowprops={'arrowstyle': '->', 'color': '#555555'},
                 fontsize=9)
axes[1].set_xlabel('Common observed source frame (frame24 absent from discard arm)')
fig.suptitle('Native discarded-record diagnostic: descriptive raw output differences', fontsize=13)
fig.text(0.5, -0.065,
         '128 x 80 synthetic wave inputs. Whole-frame RGB metrics; no quality/truth score.\n'
         'Baseline/discard also differs in GPU frame24 execution; CPU-record effect is not isolated.\n'
         'RESET25/fresh comparison uses identical applied controls and source frames25..63.',
         ha='center', fontsize=9)
for filename in ('comparison.png', 'comparison.svg', 'plot_data.json', 'completion_manifest.json'):
    assert not (HERE / filename).exists(), 'Preserve completed visualization'
fig.savefig(HERE / 'comparison.png', dpi=150, bbox_inches='tight', facecolor='white')
fig.savefig(HERE / 'comparison.svg', bbox_inches='tight', facecolor='white')
plt.close(fig)
payload = {'schema': 'discarded-record-descriptive-visual-v1',
           'source_path': str(SOURCE), 'source_sha256': sha(SOURCE),
           'created_after_native_and_analysis': True, 'new_native_contexts': 0,
           'quality_accepted': False, 'series': series}
with (HERE / 'plot_data.json').open('x', encoding='utf-8', newline='\n') as stream:
    json.dump(payload, stream, indent=2, allow_nan=False)
    stream.write('\n')
manifest = {'schema': 'discarded-record-visual-completion-v1',
            'source_sha256': sha(SOURCE), 'new_native_contexts': 0, 'quality_accepted': False,
            'files': [{'path': str(path), 'bytes': path.stat().st_size, 'sha256': sha(path)}
                      for path in sorted(HERE.iterdir()) if path.is_file()]}
with (HERE / 'completion_manifest.json').open('x', encoding='utf-8', newline='\n') as stream:
    json.dump(manifest, stream, indent=2, allow_nan=False)
    stream.write('\n')
print(json.dumps({'manifest_sha256': sha(HERE / 'completion_manifest.json'),
                  'files': len(manifest['files']), 'new_native_contexts': 0}))
