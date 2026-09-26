"""Actual DXIL: noisy animated glyphs, correlated illumination and control sweeps.

RR fixtures are independent clean/blurred estimates, not an emulation of AMD RR.
Archive V8 is kept immutable; both versions receive the same explicit controls.
Anchor=2/Mix=1 is intentionally retained here for historical V9 comparisons.
The small_colour_screen suite tests the user's V10 default Anchor=4/Mix=1.
"""
import json
import numpy as np
import run_fsrd_gpu_tests as t
from test_fsrd_panel_recovery import blur


def run():
    t.OUT = t.OUT.parent / 'patch_handover'
    t.OUT.mkdir(parents=True, exist_ok=True)
    t.build_runner()
    w, h = 81, 65
    y, x = np.indices((h, w))
    rng = np.random.default_rng(9021)
    z = np.full((h, w), 10, np.float32)
    n = t.rgba(w, h, (.5, .5, .1), 1/3)
    a = t.rgba(w, h, (1, 1, 1))
    zero = t.rgba(w, h, (0, 0, 0))
    clean = t.rgba(w, h, (.62, .54, .47))
    # Distinct 5x7 lettering at 1px and 2px scales, not only straight stripes.
    glyphs = ['11111100001111010000100001000010000',
              '11111100001111010000100001000011111',
              '10001100011000110001100010101000100']
    ink = np.zeros((h, w), bool)
    for scale, top in ((1, 12), (2, 35)):
        for i in range(9):
            bits = np.array(list(glyphs[i % 3]), dtype=int).reshape(7, 5)
            bits = np.repeat(np.repeat(bits, scale, 0), scale, 1).astype(bool)
            left = 4+i*8*scale
            if left+5*scale < w:
                ink[top:top+7*scale, left:left+5*scale] = bits
    clean[ink, :3] = (.08, .13, .19)
    crop = (slice(6, -6), slice(6, -6), slice(0, 3))
    flat = (~ink) & (y > 6) & (y < 28) & (x > 6) & (x < w-6)
    # Exclude glyph neighbourhoods from the flat-noise metric.
    for dy in range(-3, 4):
        for dx in range(-3, 4):
            flat &= ~np.roll(np.roll(ink, dy, 0), dx, 1)

    def compose(rr, ref, anchor=2, mix=1, noise=.75, directory=t.PRE, normal=n, depth=z, detail=1.0, flags=0):
        return t.dispatch('FSRDOutputComp', {
            'DstTexSize': [w, h, 1/w, 1/h], 'DetailPreservation': detail,
            'FloorHandoverAnchorClamp': anchor, 'Flags': flags,
            'FloorHandoverCorrelationMix': mix},
            [zero, a, rr, a, zero, normal, ref, depth], [10], (w, h), directory=directory)[0]

    def rms(v, mask=crop):
        return float(np.sqrt(np.mean((v[mask]-clean[mask])**2)))

    def metrics(v):
        return dict(rms=rms(v), flat_rms=float(np.sqrt(np.mean((v[flat, :3]-clean[flat, :3])**2))),
                    ink_rms=float(np.sqrt(np.mean((v[ink, :3]-clean[ink, :3])**2))))

    archive = t.reference('zero_rough_v8')
    if archive is None:
        t.skip('V8 moving glyph, coarse grain and real Skip A/B comparisons')
    fine = clean.copy()
    fine[..., :3] += rng.normal(0, .035, fine[..., :3].shape)
    ref = t.seed(fine)[3]
    t.records.append({'fine_seed_reference': metrics(ref)})
    stale = blur(np.roll(clean, 2, axis=1), 5)
    patch = compose(stale, ref, 0, 0)
    diagnostic = compose(stale, ref, flags=(1 << 16) | (8 << 17))
    t.check('reference diagnostic is unaveraged seed RGB',np.array_equal(diagnostic[...,:3],ref[...,:3]))
    # Reference diagnostics must show the same pre-anchor candidate regardless of
    # detail strength; they are not a separately implemented visual approximation.
    t.check('filtered-reference debug is independent of detail correction strength',
            np.array_equal(diagnostic, compose(stale, ref, detail=0, flags=(1 << 16) | (8 << 17))))
    # NLM was explicitly withdrawn. Keep its noisy-glyph quality result visible;
    # do not claim the former denoising threshold passes after removing it.
    t.records.append(dict(retired_nlm_case='noisy thin lettering, controls off',
                          former_ink_rms_limit=.045, **metrics(patch)))
    # Coarse, spatially correlated, signed fluctuations plus independent fine grain.
    # Several independent seeds represent changing noise with fixed artwork/camera.
    accumulated = {}
    for frame in range(3):
        coarse = t.rgba(w, h, (0, 0, 0))
        coarse[..., :3] = rng.normal(0, 1, coarse[..., :3].shape)
        coarse = blur(coarse, 10)[..., :3]
        coarse *= .10 / np.std(coarse)
        current = clean.copy()
        current[..., :3] = np.maximum(clean[..., :3]+coarse+rng.normal(0, .02, coarse.shape), 0)
        ref = t.seed(current)[3]
        variants = {'off': compose(clean, ref, 0, 0),
                    'anchor': compose(clean, ref, 2, 0),
                    'mix': compose(clean, ref, 0, 1),
                    'both': compose(clean, ref, 2, 1)}
        if archive is not None:
            variants['V8'] = compose(clean, ref, directory=archive)
        for name, output in variants.items():
            accumulated.setdefault(name, []).append(rms(output))
    means = {name: float(np.mean(values)) for name, values in accumulated.items()}
    t.check('unconditional anchor suppresses supported coarse grain', means['anchor'] < means['off']*.8, **means)
    t.check('direct correlation mix suppresses supported coarse grain', means['mix'] < means['off']*.8, **means)
    if archive is not None:
        t.check('combined controls improve correlated grain over V8', means['both'] < means['V8']*.65, **means)
    # Unlike the composition-only fixtures above, retain the actual production
    # Floor + conversion Skip. Ideal residual RR cannot remove anything already
    # routed through Skip; measure that limit instead of silently zeroing Skip.
    from test_fsrd_zero_rough_screen import chain_cb
    f, depth, guide, production_ref = t.seed(current)
    floor = t.filter_floor(f, depth, guide, a)
    packed = t.dispatch('FSRDInputConv', chain_cb(w, h, (1 << 1) | (1 << 7)),
        [current, depth, zero, t.rgba(w,h,(0,0,1)), np.zeros((h,w),np.float32), depth,
         a, a, zero, floor, zero, zero, zero, zero, depth, zero, production_ref],
        [10,10,10,24,28,28,10,10], (w,h))
    residual = zero.copy()
    residual[..., :3] = np.maximum(clean[..., :3]-packed[6][..., :3],0)/np.maximum(packed[5][..., :3],1e-5)
    outputs = {}
    for label, directory in [('V8', archive), ('current', t.PRE)]:
        if directory is None:
            continue
        outputs[label] = t.dispatch('FSRDOutputComp', {
            'DstTexSize':[w,h,1/w,1/h], 'DetailPreservation':1.0, 'FloorHandoverAnchorClamp':2., 'FloorHandoverCorrelationMix':1.},
            [zero,packed[4],residual,packed[5],packed[6],packed[3],packed[7],depth],
            [10],(w,h),directory=directory)[0]
    if archive is not None:
        t.check('coarse grain improvement also holds with real Floor and Skip routing',
                rms(outputs['current']) < rms(outputs['V8'])*.8,
                v8=metrics(outputs['V8']), current=metrics(outputs['current']),
                skip_excess_rms=float(np.sqrt(np.mean(np.maximum(packed[6][...,:3]-clean[...,:3],0)**2))))
    # A spatially constant RR estimate makes a strict positive anchor exact.
    constant = t.rgba(w, h, (.4, .4, .4))
    anchored = compose(constant, ref, .5, 0)
    t.check('positive anchor remains functional despite many similar neighbours',
            float(np.max(np.abs(anchored[..., :3]-.4))) < .001)
    values = [rms(compose(clean, ref, 0, mix)) for mix in (0, .25, .5, .75, 1)]
    t.check('correlation sweep monotonically approaches already-clean RR',
            all(b <= aa+.0001 for aa, b in zip(values, values[1:])), rms_by_mix=values)
    # The clean current artwork may be ahead of RR. Quantify the honest blur cost
    # rather than disabling controls to satisfy an old full-recovery test.
    ref = t.seed(clean)[3]
    t.records.append({'clean_seed_reference': metrics(ref)})
    cost = {name: metrics(compose(stale, ref, anchor, mix))
            for name, anchor, mix in [('off', 0, 0), ('anchor', 2, 0), ('mix', 0, 1), ('both', 2, 1)]}
    t.records.append({'clean_animation_control_tradeoff': cost})
    recovered = compose(stale, ref, 0, 0)
    expected_contrast = float(np.mean(clean[flat, :3])-np.mean(clean[ink, :3]))
    actual_contrast = float(np.mean(recovered[flat, :3])-np.mean(recovered[ink, :3]))
    t.check('zero controls preserve 95 percent clean lettering contrast',
            abs(actual_contrast-expected_contrast) < .05*expected_contrast,
            expected=expected_contrast, actual=actual_contrast, **cost)
    t.check('historical Anchor=2 Mix=1 improves stale RR, with an explicit blur tradeoff',
            cost['both']['rms'] < rms(stale)*.9, stale_rms=rms(stale), **cost)
    # Independent invariants: controls cannot alter detail-disabled reconstruction,
    # routed content or ordinary materials; no extra evidence from another surface.
    off = compose(clean, ref, 0, 0, detail=0)
    on = compose(clean, ref, .1, 1, detail=0)
    t.check('detail zero cancels patch and controls exactly', np.array_equal(off, on))
    ref[..., 3] = -1
    t.check('explicit current-frame routing excludes patch and controls',
            np.array_equal(off, compose(clean, ref, .1, 1)))
    ref = t.seed(fine)[3]
    split = z.copy(); split[:, w//2:] = 30
    # Retain independent left-half data; vary only a disconnected right surface.
    changed = ref.copy(); changed[:, w//2:, :3] = 4
    o1 = compose(stale, changed, 0, 0, depth=split)
    o2 = compose(stale, ref, 0, 0, depth=split)
    t.check('patch comparisons do not borrow across depth discontinuity',
            np.max(np.abs(o1[:, :w//2, :3]-o2[:, :w//2, :3])) < .001)
    (t.OUT/'results.json').write_text(json.dumps({'checks': t.checks, 'dispatches': t.timings,
                                                'records': t.records}, indent=2))
    print(json.dumps(t.records, indent=2))
    assert all(c['passed'] for c in t.checks), 'patch handover regression'


if __name__ == '__main__':
    run()
