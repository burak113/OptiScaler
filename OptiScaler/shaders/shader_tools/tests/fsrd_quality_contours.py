"""Full-ROI contour diagnostic for constant-truth synthetic island controls.

The original radial-profile score stopped at radius 2 and missed support-shaped
boxes farther away. Keep original scores; this is an additional conservative gate
introduced after visual inspection, not a retroactively preregistered criterion.
"""
import numpy as np


def island_contours(output, truth, threshold=.002):
    out,clean=np.asarray(output,float),np.asarray(truth,float)
    if (out.shape!=clean.shape or out.ndim!=4 or out.shape[-1]!=3 or not len(out) or
        not np.isfinite(out).all() or not np.isfinite(clean).all()):
        raise ValueError('Expected matching finite frame sequences')
    _,h,w,_=out.shape;y,x=np.indices((h,w))
    radius=np.sqrt(((x-.4*w)/(.12*w))**2+((y-.54*h)/(.16*h))**2)
    roi=(x>=5)&(x<w-5)&(y>=5)&(y<h-5)
    exterior=roi&(radius>3)
    if exterior.sum()<16 or not np.isfinite(threshold) or threshold<=0:
        raise ValueError('Insufficient exterior reference or invalid threshold')
    # Uniform RGB bias has its own gate. Remove only the measured far-exterior
    # offset to isolate spatial contour shape, equally for candidate and baseline.
    error=(out[-4:]-clean[-4:]).mean(0)
    offset=np.median(error[exterior],axis=0)
    localized=error-offset
    mask=roi&(np.max(abs(localized),axis=-1)>threshold)
    return dict(threshold=threshold,final_frames=min(4,len(out)),
        exterior_offset_rgb=offset.tolist(),affected_pixels=int(mask.sum()),
        outside_pixels=int(np.sum(mask&(radius>1.5))),
        radius95=float(np.quantile(radius[mask],.95)) if mask.any() else 0.)


def contour_gate(candidate,baseline,w,h):
    extra=candidate['outside_pixels']-baseline['outside_pixels']
    radius_budget=2/min(.12*w,.16*h) # Two pixels at the shorter island radius.
    failed=(extra>max(4,int(.001*(w-10)*(h-10))) or
            candidate['radius95']>baseline['radius95']+radius_budget)
    return dict(passed=not failed,extra_outside_pixels=extra,radius_budget=radius_budget,
        note='Additional conservative post-inspection gate; original measurements retained.')
