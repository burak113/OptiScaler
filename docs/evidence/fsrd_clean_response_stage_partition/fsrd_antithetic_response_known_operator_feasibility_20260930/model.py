"""Frozen observed-only P16 and exact antithetic algebra; no response estimator."""
import numpy as np
HISTORY=16
WARMUP=8
def source_mean(raw,controls,exposure=None):
    x=np.asarray(raw);c=np.asarray(controls)
    if x.ndim!=4 or x.shape[-1]!=3 or c.shape!=(len(x),3):raise ValueError('source/control shape')
    ex=None if exposure is None else np.asarray(exposure)
    if ex is not None and ex.shape!=(len(x),):raise ValueError('exposure shape')
    P=x.copy();active=np.zeros(len(x),bool);records=[];past=[];previous=None;epoch=0
    for i,current in enumerate(x):
        metadata_valid=bool(np.isfinite(c[i]).all() and c[i,0] in (0,1) and (ex is None or (np.isfinite(ex[i]) and ex[i]>0)))
        source_valid=bool(np.isfinite(current).all() and np.all(current>=0) and np.all(current<=65504))
        state=tuple(c[i,1:])+(tuple() if ex is None else (float(ex[i]),))
        if not metadata_valid or not source_valid:
            past=[];previous=None;epoch=i+1
            records.append(dict(frame=i,epoch_start=i,active=False,history_count=0,reason='invalid_metadata_or_source_exact_raw_clear',metadata_valid=metadata_valid,source_valid=source_valid))
            continue
        cut=bool(i==0 or c[i,0]==1 or previous is None or state!=previous)
        if cut:past=[];epoch=i
        previous=state;past.append(current.astype(np.float64,copy=True));past=past[-HISTORY:]
        if i-epoch<WARMUP:
            reason='first8_epoch_exact_raw_history_fed'
        else:
            mean=np.mean(np.stack(past),axis=0)
            if np.isfinite(mean).all() and np.all(mean>=0) and np.all(mean<=65504):
                P[i]=mean;active[i]=True;reason='causal_current_inclusive16_mean'
            else:
                past=[];previous=None;epoch=i+1;reason='invalid_mean_exact_raw_clear'
        records.append(dict(frame=i,epoch_start=epoch,active=bool(active[i]),history_count=len(past),reason=reason,metadata_valid=metadata_valid,source_valid=source_valid,cut=cut))
    return P,active,dict(history=HISTORY,warmup=WARMUP,exposure='unknown_absent' if ex is None else 'observed_exact_change_cut',frames=records)
def mirror(raw,P):return 2*np.asarray(P)-np.asarray(raw)
def antithetic(P,TO,TM):return np.asarray(P)+.5*(np.asarray(TO)-np.asarray(TM))
def domain(a):
    a=np.asarray(a);finite=np.isfinite(a);invalid=~np.all(finite&(a>=0)&(a<=65504),axis=-1)
    return dict(nonfinite_channel_elements=int(np.count_nonzero(~finite)),negative_finite_channel_elements=int(np.count_nonzero(finite&(a<0))),overflow_finite_channel_elements=int(np.count_nonzero(finite&(a>65504))),invalid_RGB_pixels=int(invalid.sum()),invalid_frames=int(np.count_nonzero(invalid.reshape(len(a),-1).any(1))),per_frame_invalid_RGB_pixels=invalid.reshape(len(a),-1).sum(1).tolist(),native_radiance_domain_met=bool(not invalid.any()))
