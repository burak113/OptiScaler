"""Source-only pilot DC conditioning experiment. No runtime quality claim.

The old temporal pilot keeps a noisy current DC in every frame. This variant
lets only DC follow the same nominal three-RMS innovation criterion. Non-DC
appearance remains the old source-only temporal pilot. Final composition DC
conservation is deliberately a separate operator.
"""
import numpy as np
from fsrd_response_pilot import make_temporal_spectral_pilot


def make_dc_conditioned_pilot(raw, controls, history=16):
    c=np.asarray(raw,float);ctrl=np.asarray(controls,float)
    pilot,active,base=make_temporal_spectral_pilot(c,ctrl,history)
    result=pilot.copy();past=[];sigmas=[];records=[]
    n=c.shape[1]*c.shape[2]
    for i,record in enumerate(base['frames']):
        if record['reset'] or record['jitter_changed']:
            past.clear();sigmas.clear()
        current=c[i].mean((0,1),dtype=np.float64)
        sigma=record['nominal_iid_pixel_sigma']
        m=len(past);innovation=False;threshold=None
        if m:
            prior=np.mean(past,axis=0)
            prior_variance=sum(s*s for s in sigmas)/(m*m)
            threshold=3*np.sqrt(sigma*sigma+prior_variance)/np.sqrt(n)
            innovation=bool(np.any(abs(current-prior)>threshold))
            target=current if innovation else (sum(past)+current)/(m+1)
        else:
            target=current
        candidate=pilot[i]+(target-current)
        valid=bool(active[i] and np.isfinite(candidate).all() and
                   candidate.min()>=0 and candidate.max()<=65504)
        if valid:
            result[i]=candidate
        else:
            result[i]=c[i];active[i]=False
        records.append(dict(frame=i,epoch_start=record['epoch_start'],
            preceding_observations=m,total_observations=m+1,
            nominal_source_pixel_sigma=sigma,nominal_dc_innovation_threshold=threshold,
            dc_innovation=innovation,source_mean_rgb=current.tolist(),target_mean_rgb=target.tolist(),
            active=valid,unclamped_minimum=float(candidate.min()),unclamped_maximum=float(candidate.max())))
        past.append(current);sigmas.append(sigma)
        if len(past)>=history:past.pop(0);sigmas.pop(0)
    return result,active,dict(schema='fsrd-dc-conditioned-temporal-pilot-research-v1',
        history=history,active_frames=int(active.sum()),frames=records,
        epoch_start_by_frame=base['epoch_start_by_frame'],non_dc_pilot_diagnostics=base,
        quality_accepted=False,no_clean_truth_input=True,runtime_implemented=False,
        dc_innovation_rms_multiplier=3.,source_domain='Current and past observed RGB only',
        limitations=['Source spatial/temporal independence is a nominal assumption, not established in game.',
            'Subthreshold true global light changes can lag; output current-DC is a separate constraint.',
            'Correlated source noise and dense texture invalidate the nominal variance.',
            'Non-DC pilot retains its old threshold-crossing and slow-phase limitations.',
            'Invalid signed prediction falls back to current RGB for the entire frame, without clipping.',
            'No native/model/game/cost acceptance from CPU tests alone.'])
