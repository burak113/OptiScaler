from pathlib import Path
import hashlib,json
HERE=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
r=json.loads((HERE/'results.json').read_text());groups={}
for group,key in [('source_rows','source_proxy_DC_innovation'),('adversaries','source_proxy_DC_innovation'),('saved_native_rows','new_final_DC_innovation_safe')]:
    rows=[]
    for row in r[group]:
        z=row.get('result',row);v=z['variants'][key];windows={}
        for name,m in v.items():
            if m.get('unscorable_nonfinite'):windows[name]=m;continue
            windows[name]=dict(relative=m['relative_gate'],actual_STD_ratio=m['actual_STD_ratio_to_control'],STD=m['score']['residual_temporal_std'],mean_variance=m['mean_temporal_variance'],
                              gain_min=m['absolute_gain_min'],gain_max=m['absolute_gain_max'],phase_max=m['absolute_phase_max'],absolute_detail=m['per_frame_absolute_detail_pass'],
                              gain_failing_frames=m['absolute_gain_failing_frames'],phase_failing_frames=m['absolute_phase_failing_frames'],invalid_pixels=m['invalid_pixel_fraction'])
        d=z['target_diagnostics'];cuts=[f['frame'] for f in d['frames'] if f.get('innovation')]
        rows.append(dict(scene=row['scene'],windows=windows,DC_innovation_frames=cuts,invalid_target_frames=[f['frame'] for f in d['frames'] if not f['valid']],
                         max_target_history=max(f.get('history_used_including_current',0) for f in d['frames']),source_target_metrics=z['target_metrics']))
    totals={}
    for window in ('full','mature','startup_first8','activation8to16'):
        scored=[q['windows'][window] for q in rows if not q['windows'][window].get('unscorable_nonfinite')]
        totals[window]=dict(scored=len(scored),unscorable=len(rows)-len(scored),relative_nonregression=sum(x['relative']['nonregression'] for x in scored),effective=sum(x['relative']['effective_success'] for x in scored),
                            absolute_detail=sum(x['absolute_detail'] for x in scored),strict_STD_nonincrease=sum(x['actual_STD_ratio'] is not None and x['actual_STD_ratio']<=1 for x in scored))
    groups[group]=dict(label='actual_saved_matching_native_postcompose_no_new_native' if group=='saved_native_rows' else 'source_proxy_only_not_native',candidate=key,totals=totals,rows=rows)
out=dict(status=r['status'],quality_accepted=False,source_results_sha256=sha(HERE/'results.json'),groups=groups,
         conclusions=['Same matching measured P/T(P) reused only for saved6 scenes; no fresh native dispatch. Source13+22 does not supply missing native coverage.',
                      'Final DC target changes no nonDC model before rounding/fallback, so prior startup/weak/moving-detail failures remain.',
                      'Nominal source-mean innovation cannot distinguish illumination from spatially shared artifacts; source-adaptive IID uncertainty is not confidence.'])
(HERE/'compact_report.json').write_text(json.dumps(out,indent=2,allow_nan=False)+'\n')
for key,g in groups.items():print(key,g['totals'])
print('compact SHA',sha(HERE/'compact_report.json'))
