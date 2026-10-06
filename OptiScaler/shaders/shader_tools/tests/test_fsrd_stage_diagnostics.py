"""GPU contracts for stage diagnostics, plus repeatable small/large screen probes.

Metrics characterize the current algorithm; they are not new image-quality passes.
Optional --baseline checks normal-output parity against an explicitly saved CSO.
"""
import argparse
import json
from pathlib import Path

import numpy as np
import run_fsrd_gpu_tests as t
import fsrd_stage_probe as p
from test_fsrd_panel_recovery import blur


def fixture(scale, noisy):
    w, h = 97, 67  # Deliberately partial thread groups.
    y, x = np.indices((h, w))
    target = t.rgba(w, h, (.36, .42, .48))
    glyph = np.array([[1,0,1,0,1,1,1,0,1,1,0],
                      [1,0,1,0,1,0,0,0,1,0,1],
                      [1,1,1,0,1,1,0,0,1,1,0],
                      [1,0,1,0,1,0,0,0,1,0,1],
                      [1,0,1,0,1,1,1,0,1,0,1]], dtype=bool)
    glyph = np.repeat(np.repeat(glyph, scale, 0), scale, 1)
    ink = np.zeros((h,w), dtype=bool)
    oy, ox = (h-glyph.shape[0])//2, (w-glyph.shape[1])//2
    ink[oy:oy+glyph.shape[0],ox:ox+glyph.shape[1]] = glyph
    target[ink,:3] = (.08,.18,.72)
    # Colour transitions are genuine glyphs, not luminance-only white text.
    target[ink & (x > w//2),:3] = (.75,.12,.18)
    colour = target.copy()
    if noisy:
        rng = np.random.default_rng(912 + scale)
        colour[...,:3] += rng.normal(0,.04,(h,w,3))
        colour[...,:3] += (.06*np.sin(x*.19)*np.sin(y*.27))[...,None]
        colour[...,:3] = np.maximum(colour[...,:3],0)
    floor, depth, guide, reference = t.seed(colour)
    rr = blur(target, 3)
    inputs = [t.rgba(w,h,(0,0,0)),t.rgba(w,h,(1,1,1)),rr,t.rgba(w,h,(1,1,1)),
              t.rgba(w,h,(0,0,0)),t.rgba(w,h,(.5,.5,.1),1/3),reference,depth]
    values = {'DstTexSize':[w,h,1/w,1/h], 'DetailPreservation':1.0,
              'FloorHandoverAnchorClamp':4,
              'FloorHandoverCorrelationMix':1}
    return values, inputs, target, colour, ink


def run(baseline=None):
    t.OUT = t.OUT.parent/'stage_diagnostics'
    t.OUT.mkdir(parents=True, exist_ok=True)
    t.build_runner()
    measurements = []
    parity = []
    for scale in (1,3):
        for noisy in (False,True):
            label = f'{"small" if scale == 1 else "large"}_{"noisy" if noisy else "clean"}'
            values, inputs, target, colour, ink = fixture(scale,noisy)
            folder = t.OUT/label; folder.mkdir(exist_ok=True)
            provenance = 'Synthetic current animated texture; synthetic blurred RR. No AMD model.'
            p.save_inputs(folder/'inputs.npz',values,inputs,provenance,truth=target,raw=colour,ink=ink)
            loaded_values, loaded_inputs, metadata = p.load_inputs(folder/'inputs.npz')
            t.check(label+' input replay round trip', loaded_values == values and
                    all(np.array_equal(a,b) for a,b in zip(inputs,loaded_inputs)))
            s = p.probe(loaded_values, loaded_inputs, folder, provenance)
            t.check(label+' final debug equals normal output exactly',np.array_equal(s['composition'],s['normal']))
            t.check(label+' seed debug is stored seed',np.array_equal(s['seed'][...,:3],inputs[6][...,:3]))
            t.check(label+' zero-rough eligibility explicit',np.all(s['eligibility'][...,:3]==1))
            t.check(label+' controls stay bounded',all(np.all((s[name][...,:3]>=0)&(s[name][...,:3]<=1))
                                                       for name in ('weights','limits','confidence')))
            product = np.prod(s['weights'][...,:3],axis=2)
            error = float(np.max(np.abs(product-s['confidence'][...,0])))
            t.check(label+' three permissions explain confidence',error<.001,error=error)
            # Independent public blend contract, using actual readbacks. FP16
            # intermediate outputs need a small tolerance against the FP32 blend.
            expected = s['reconstructed'][...,:3] + np.clip(values['DetailPreservation'],0,1)*product[...,None]*\
                       (s['anchor'][...,:3]-s['reconstructed'][...,:3])
            # Additional chromatic contrast is reported separately; it does not
            # silently change the established three base handover permissions.
            rr_luma=s['reconstructed'][...,:3] @ np.array([.2126,.7152,.0722])
            encoded=s['chroma_recovery'][...,:3]
            t.check(label+' chroma diagnostic does not saturate this fixture',np.all((encoded>0)&(encoded<1)))
            expected += (encoded-.5)*np.maximum(rr_luma,1e-3)[...,None]
            encoded_luma=s['luma_recovery'][...,:3]
            t.check(label+' luma diagnostic does not saturate this fixture',
                    np.all((encoded_luma>0)&(encoded_luma<1)))
            expected += (encoded_luma-.5)*np.maximum(rr_luma,1e-3)[...,None]
            error = float(np.max(np.abs(expected-s['before_clamp'][...,:3])))
            t.check(label+' candidate and permissions explain pre-clamp colour',error<.0015,error=error)
            t.check(label+' positive radiance and finite stages',all(np.all(np.isfinite(a)) and np.min(a[...,:3])>=0
                                                                    for a in s.values()))
            rows = {}
            # Error around glyphs includes their background/halos; large margins
            # cannot swamp the small-screen score. It is not an in-game metric.
            yy,xx = np.where(ink)
            roi = (slice(yy.min()-2,yy.max()+3),slice(xx.min()-2,xx.max()+3),slice(0,3))
            for name in ('seed','reference','reconstructed','box_anchor','anchor','before_clamp','composition'):
                delta = s[name][roi]-target[roi]
                rows[name] = {'glyph_rmse':float(np.sqrt(np.mean(delta*delta)))}
            t.check(label+' reference preserves seed without spatial averaging',np.array_equal(s['reference'],s['seed']))
            measurements.append({'fixture':label,'metrics':rows,
                                 'mean_seed_sigma_on_ink':float(np.mean(inputs[6][ink,3])),
                                 'ink_mean_permissions_rgb':np.mean(s['weights'][ink,:3],axis=0).tolist(),
                                 'ink_mean_limit_fractions_rgb':np.mean(s['limits'][ink,:3],axis=0).tolist()})
            if baseline:
                old = p.dispatch(values,inputs,directory=baseline)
                error = float(np.max(np.abs(s['normal']-old)))
                t.check(label+' checkpoint normal-output parity',np.array_equal(s['normal'],old),max_error=error)
                parity.append({'fixture':label,'max_error':error})

    values, inputs, _, _, _ = fixture(1,True)
    original_values, original_inputs = dict(values),list(inputs)
    rr = p.dispatch(values,inputs,'reconstructed')
    for label,detail,routed,ordinary in [('zero detail',0,False,False),
                                        ('explicitly routed',.35,True,False),
                                        ('ordinary material',.35,False,True)]:
        values = dict(original_values,DetailPreservation=detail); inputs=list(original_inputs)
        if routed:
            inputs[6]=inputs[6].copy();inputs[6][...,3]=-1
        if ordinary:
            inputs[5]=inputs[5].copy();inputs[5][...,3]=0
        normal=p.dispatch(values,inputs)
        final=p.dispatch(values,inputs,'composition')
        t.check(label+' debug final equals normal',np.array_equal(normal,final))
        eligibility=p.dispatch(values,inputs,'eligibility')
        expected=(0 if ordinary else 1, 0 if routed else 1, float(np.float16(detail)))
        t.check(label+' eligibility explains domain',np.allclose(eligibility[...,:3],expected,rtol=0,atol=.00025))
        if routed or ordinary or detail==0:
            t.check(label+' contributes no correction',np.array_equal(final,rr))
        if routed or ordinary or detail==0:
            t.check(label+' has no additional chroma correction',
                    np.all(p.dispatch(values,inputs,'chroma_recovery')[...,:3]==.5))
            t.check(label+' has no additional luma correction',
                    np.all(p.dispatch(values,inputs,'luma_recovery')[...,:3]==.5))
        if routed or ordinary:
            weights=p.dispatch(values,inputs,'weights')
            t.check(label+' has no zero-rough handover permissions',np.all(weights[...,:3]==0))
        if routed:
            for stage in ('seed','reference','box_anchor','anchor','limits'):
                t.check(label+' '+stage+' black',np.all(p.dispatch(values,inputs,stage)[...,:3]==0))
        if baseline:
            old=p.dispatch(values,inputs,directory=baseline)
            t.check(label+' checkpoint parity',np.array_equal(normal,old))
    # A flat RR anchor is a deliberate adversarial example: it must show the
    # candidate being restricted even when this erases real new screen texture.
    inputs=list(original_inputs);inputs[2]=t.rgba(97,67,(.4,.4,.4))
    values=dict(original_values)
    anchored=p.dispatch(values,inputs,'anchor')
    t.check('flat RR Anchor visibly pins candidate',np.max(np.abs(anchored[...,:3]-.4))<.001)
    limits=p.dispatch(values,inputs,'limits')
    t.check('flat RR Anchor loss is visible',np.mean(limits[...,:3][...,0])>.8)
    values['FloorHandoverAnchorClamp']=0
    ref=p.dispatch(values,inputs,'reference');anchor=p.dispatch(values,inputs,'anchor')
    t.check('Anchor zero removes both constraints exactly',np.array_equal(ref,anchor))
    limits=p.dispatch(values,inputs,'limits')
    t.check('disabled Anchor has zero restriction display',np.all(limits[...,:2]==0))
    values['FloorHandoverCorrelationMix']=0
    weights=p.dispatch(values,inputs,'weights')
    t.check('Mix zero grants full correlation permission',np.all(weights[...,2]==1))
    (t.OUT/'measurements.json').write_text(json.dumps({'measurements':measurements,'parity':parity,
        'limitations':'Synthetic blurred RR; metrics characterize stages, not game quality or an improvement.'},indent=2))
    (t.OUT/'results.json').write_text(json.dumps({'checks':t.checks,'dispatches':t.timings},indent=2))
    assert all(c['passed'] for c in t.checks),'stage diagnostics regression'


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline',type=Path)
    args=parser.parse_args()
    run(args.baseline)
