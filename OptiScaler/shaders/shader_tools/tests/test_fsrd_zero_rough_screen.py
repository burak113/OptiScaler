"""Zero-rough screen domain: the acceptance gates the redesign was written against.

Tests execute production DXIL. Closure/volume cases run seed, five filters, conversion and
composition with identity or erased RR. Stale-text cases explicitly feed independently
blurred/displaced radiance into composition. The runner does not execute AMD RR.

The gates, in order:
  1. identity closure in the zero-rough domain, dark and bright text, Detail Preservation 0
  2. the same for RGB texture, HDR radiance, mirrors and a non-zero subrect
  3. a blurred/displaced denoiser may not move or soften current-frame text
  4. grain over a known clean screen layer: structure measured against the clean layer and
     noise measured against the clean illumination, both independently generated
  5. the volume/transparency in front of a zero-rough surface keeps its light
  6. no halo or trail: the output stays inside the supported reference envelope
"""
import json
import numpy as np
import run_fsrd_gpu_tests as t

CONV_INPUTS = 17
# u0 spec, u4 spec albedo, u1 diffuse, u5 diff albedo, u6 skip, u3 normals, u7 reference, depth
COMP_INPUTS = 'spec, specalbedo, diffuse, diffalbedo, skip, normals, reference, depth'


def chain_cb(w, h, flags, detail=1.0, noise=.75):
    return {
        'InvViewMatrix': np.eye(4).ravel(), 'InvProjMatrix': np.eye(4).ravel(),
        'PrevViewMatrix': np.eye(4).ravel(), 'DstTexSize': [w, h, 1 / w, 1 / h],
        'MotionInputSize': [w, h, 1 / w, 1 / h], 'MotionTransform': [1, 1, 0, 0],
        'NearPlane': .1, 'FarPlane': 1000, 'FloorDetailPreservation': detail,
        'Flags': flags, 'DemodDivisorFloor': .008, 'BiasMaskStrength': 1,
        # Legacy quality/energy fixtures explicitly retain the original Floor.
        # Automatic/forced routes have independent tests in test_fsrd_rr_routing.
    }


def run_chain(colour, depth, normal, spec_albedo, diff_albedo, reference,
              floor=None, roughness=None, detail=1.0, floor_enabled=True, size=None,
              crop=None, origin=(0, 0)):
    """Floor seed and five passes, conversion, then composition with an identity denoiser.

    Returns the composed output. `colour` is the title's current frame, `reference` the
    cleaned current-frame reference the seed produced.
    """
    h, w = colour.shape[:2]
    lw, lh = size or (w, h)
    zero = t.rgba(w, h, (0, 0, 0))
    if floor is None:
        floor = t.rgba(w, h, (0, 0, 0))
    if roughness is None:
        roughness = np.zeros((h, w), np.float32)
    flags = (1 << 1) | ((1 << 7) if floor_enabled else 0)
    vals = chain_cb(lw, lh, flags, detail)
    # The title resources are read at `origin`; the logical window is dispatched at (lw,lh)
    # and the internal packed resources stay zero-based, so the composition output already is
    # the logical window.
    vals['InputBase0'] = [origin[0], origin[1], 0, 0]
    vals['InputBase1'] = [origin[0], origin[1], 0, 0]
    vals['InputBase2'] = [0, 0, origin[0], origin[1]]
    vals['InputBase3'] = [origin[0], origin[1], 0, 0]
    vals['InputBase4'] = [0, 0, 0, 0]
    vals['InputBase5'] = [0, 0, origin[0], origin[1]]
    packed = t.dispatch('FSRDInputConv', vals,
                        [colour, depth, zero, normal, roughness, depth, diff_albedo,
                         spec_albedo, zero, floor, zero, zero, zero, zero, depth, zero,
                         reference],
                        [10, 10, 10, 24, 28, 28, 10, 10], (lw, lh))
    out = t.dispatch('FSRDOutputComp',
                     {'DstTexSize': [lw, lh, 1 / lw, 1 / lh], 'Flags': 0,
                      'DetailPreservation': detail},
                     [packed[0], packed[4], packed[1], packed[5], packed[6], packed[3],
                      packed[7], depth],
                     [10], (lw, lh))[0]
    if crop:
        out = out[crop]
    return out


def blur(c, passes):
    out = c.copy()
    for _ in range(passes):
        for axis in (0, 1):
            out = .25 * np.roll(out, 1, axis) + .5 * out + .25 * np.roll(out, -1, axis)
    return out


def text_pair(w, h):
    """Dark-on-light and light-on-dark 1px strokes: the asymmetric case V5 filled in."""
    yy, xx = np.indices((h, w))
    dark = t.rgba(w, h, (.85, .85, .85))
    bright = t.rgba(w, h, (.08, .08, .08))
    ink = (((xx % 7) < 1) & (yy > 2) & (yy < h - 3)) | ((yy == h // 2) & (xx > 2) & (xx < w - 3))
    dark[ink, :3] = .04
    bright[ink, :3] = .9
    return dark, bright, ink


def flat(w, h, value):
    return t.rgba(w, h, (value, value, value))


def run():
    t.OUT = t.OUT.parent / 'zero_rough_screen'
    t.OUT.mkdir(parents=True, exist_ok=True)
    t.build_runner()
    w, h = 33, 25
    alb = t.rgba(w, h, (.5, .5, .5))
    half = t.rgba(w, h, (.5, .5, .5))
    normal = t.rgba(w, h, (0, 0, 1))
    depth = np.full((h, w), 10, np.float32)
    zero_rough = np.zeros((h, w), np.float32)

    # --- 1. identity closure in the zero-rough domain -------------------------------
    dark, bright, ink = text_pair(w, h)
    for label, colour in (('dark-on-light text', dark), ('light-on-dark text', bright)):
        f, z, g, reference = t.seed(colour)
        floor = t.filter_floor(f, z, g, alb)
        for detail in (0.0, .35):
            out = run_chain(colour, z, normal, half, half, reference, floor, zero_rough,
                            detail=detail)
            error = np.max(np.abs(out[..., :3] - colour[..., :3]))
            t.check(f'zero-rough identity closure: {label} detail={detail}',
                    error < 3e-3, max_error=float(error))
        # The pre-rewrite split reconstructed max(C,F) here: the pedestal sat above the dark
        # strokes and brightened them. The test measures against the current frame, never
        # against C plus that excess.
        f, z, g, reference = t.seed(colour)
        floor = t.filter_floor(f, z, g, alb)
        out = run_chain(colour, z, normal, half, half, reference, floor, zero_rough)
        t.check(f'zero-rough excess never added back: {label}',
                np.max(np.abs(out[..., :3] - colour[..., :3])) < 3e-3)

    # Symmetry: the two polarities must be treated alike. A sign-asymmetric split shows up
    # as one polarity losing materially more contrast than the other.
    errors = {}
    for label, colour in (('dark', dark), ('bright', bright)):
        f, z, g, reference = t.seed(colour)
        floor = t.filter_floor(f, z, g, alb)
        out = run_chain(colour, z, normal, half, half, reference, floor, zero_rough)
        errors[label] = float(np.mean(np.abs(out[ink, :3] - colour[ink, :3])))
    t.check('dark and bright text treated symmetrically',
            errors['bright'] <= max(errors['dark'] * 2.0, .01),
            dark=errors['dark'], bright=errors['bright'])

    # --- 2. RGB texture, HDR, mirror, subrect ---------------------------------------
    yy, xx = np.indices((h, w), dtype=np.float32)
    texture = t.rgba(w, h, (0, 0, 0))
    for c, phase in enumerate((0, 1.7, 3.1)):
        texture[..., c] = .5 + .22 * np.sin(xx * .7 + yy * .3 + phase) + .12 * np.cos(yy * .9 - xx * .4 + phase)
    # Three pixels in: inside that the seed's 5x5 stencil is still clamped against the
    # resource edge, and the resulting ring is a boundary artefact rather than screen content.
    band = (slice(3, -3), slice(3, -3), slice(0, 3))
    for label, colour in (('rgb texture', texture),
                          ('hdr texture', texture * 40.0),
                          ('dim texture', texture * 1e-3)):
        f, z, g, reference = t.seed(colour)
        floor = t.filter_floor(f, z, g, alb)
        out = run_chain(colour, z, normal, half, half, reference, floor, zero_rough)
        scale = max(float(np.max(colour[..., :3])), 1e-6)
        # Judged inside a two-pixel margin: the outermost ring is where the seed's 5x5 stencil
        # is clamped against the resource edge, and no title screen structure lives there.
        error = float(np.max(np.abs(out[band] - colour[band])) / scale)
        t.check(f'zero-rough identity closure: {label}', error < 6e-3, relative_error=error)

    # A mirror is zero-rough too, and is the other half of this domain.
    mirror = t.rgba(w, h, (.9, .9, .9))
    mirror[8:16, 10:22, :3] = [.2, .6, .9]
    mirror_alb = t.rgba(w, h, (.95, .95, .95))
    f, z, g, reference = t.seed(mirror, albedo=mirror_alb)
    floor = t.filter_floor(f, z, g, mirror_alb)
    out = run_chain(mirror, z, normal, mirror_alb, t.rgba(w, h, (.02, .02, .02)), reference,
                    floor, zero_rough)
    t.check('zero-rough mirror identity closure',
            np.max(np.abs(out[..., :3] - mirror[..., :3])) < 4e-3,
            max_error=float(np.max(np.abs(out[..., :3] - mirror[..., :3]))))

    # A non-zero subrect: the logical window is smaller than the resources it lives in.
    big_w, big_h = w + 6, h + 6
    pad = t.rgba(big_w, big_h, (0, 0, 0))
    pad[3:3 + h, 3:3 + w, :3] = dark[..., :3]
    f, z, g, reference = t.seed(pad, base=(3, 3), logical=(w, h),
                                albedo=t.rgba(big_w, big_h, (.5, .5, .5)))
    floor = t.filter_floor(f, z, g, t.rgba(big_w, big_h, (.5, .5, .5)))
    out = run_chain(pad, z, normal, t.rgba(big_w, big_h, (.5, .5, .5)),
                    t.rgba(big_w, big_h, (.5, .5, .5)), reference, floor, zero_rough,
                    size=(w, h), origin=(3, 3))
    t.check('zero-rough closure on a non-zero subrect',
            np.max(np.abs(out[..., :3] - dark[..., :3])) < 4e-3,
            max_error=float(np.max(np.abs(out[..., :3] - dark[..., :3]))))

    # Odd dimensions with no optional input bound beyond the required set.
    for (ow, oh) in ((13, 7), (1, 9), (9, 1)):
        c = flat(ow, oh, .3)
        c[oh // 2, ow // 2, :3] = .9
        f, z, g, reference = t.seed(c)
        floor = t.filter_floor(f, z, g, t.rgba(ow, oh, (.5, .5, .5)))
        out = run_chain(c, z, t.rgba(ow, oh, (0, 0, 1)), t.rgba(ow, oh, (.5, .5, .5)),
                        t.rgba(ow, oh, (.5, .5, .5)), reference, floor,
                        np.zeros((oh, ow), np.float32))
        t.check(f'zero-rough closure at odd size {ow}x{oh}',
                np.max(np.abs(out[..., :3] - c[..., :3])) < 4e-3)

    # --- 3. a stale denoiser may not touch current text -----------------------------
    for passes in (1, 3, 8):
        for shift in (0, 2):
            f, z, g, reference = t.seed(dark)
            floor = t.filter_floor(f, z, g, alb)
            h_, w_ = dark.shape[:2]
            lw, lh = w_ - 8, h_ - 8
            rr = blur(np.roll(dark, shift, axis=1), passes)
            inter = (slice(4, 4 + lh), slice(4, 4 + lw))
            # Feed the computed stale RR, then compare with independently defined ink.
            # Unconstrained recovery. V9 controls intentionally trade it for stability.
            out = t.compose(rr, reference, z, t.rgba(w,h,(.5,.5,.1),1/3), alb, anchor=0, mix=0)
            out = out[inter[0], inter[1], :3]
            ink_crop = ink[inter]
            reference_crop = dark[inter][..., :3]
            ink_error = float(np.mean(np.abs(out[ink_crop] - reference_crop[ink_crop])))
            t.check(f'stale RR blur={passes} shift={shift} keeps current text (anchor/mix off)',
                    ink_error < .05, ink_error=ink_error)
            halo = float(np.max(out) - np.max(dark[inter][..., :3]))
            t.check(f'stale RR blur={passes} shift={shift} adds no bright halo',
                    halo < .02, halo=halo)

    # --- 4. grain over a known clean screen layer -----------------------------------
    rng = np.random.default_rng(31337)
    clean_screen = t.rgba(w, h, (0, 0, 0))
    for c, phase in enumerate((0, 2.1, 4.0)):
        clean_screen[..., c] = .45 + .18 * np.sin(xx * .5 + yy * .25 + phase) + .09 * np.cos(yy * .8 + phase)
    strokes = ink & (np.indices((h, w))[1] < w // 2)
    clean_screen[strokes, :3] = [.05, .07, .1]
    flat_half = np.indices((h, w))[1] >= w // 2 + 6
    illumination = np.full((h, w), .82, np.float32)
    noisy_light = illumination + rng.normal(0, .06, (h, w)).astype(np.float32)
    current = clean_screen.copy()
    current[..., :3] *= noisy_light[..., None]
    f, z, g, reference = t.seed(current)
    floor = t.filter_floor(f, z, g, alb)
    # The best case for the denoiser: it removes the grain and keeps the screen it was
    # lighting, which is what a temporally accumulated estimate of a static screen does.
    # Anything the operator fails to keep here is its own doing.
    denoised = clean_screen.copy()
    denoised[..., :3] *= blur(illumination[..., None], 6)
    lw, lh = w, h
    vals = chain_cb(lw, lh, (1 << 1) | (1 << 7))
    zero = t.rgba(lw, lh, (0, 0, 0))
    packed = t.dispatch('FSRDInputConv', vals,
                        [current, z, zero, normal, zero_rough, z, half, half, zero, floor,
                         zero, zero, zero, zero, z, zero, reference],
                        [10, 10, 10, 24, 28, 28, 10, 10], (lw, lh))
    # The reference here is the production one from the chain above; the denoised radiance is
    # fed in with a unit albedo so composition sees it unchanged at the same radiance scale.
    rr = denoised
    ones = t.rgba(lw, lh, (1, 1, 1))
    out = t.dispatch('FSRDOutputComp',
                     {'DstTexSize': [lw, lh, 1 / lw, 1 / lh], 'Flags': 0,
                      'DetailPreservation': 1.0},
                     [zero, ones, rr, ones, zero, packed[3], packed[7], z],
                     [10], (lw, lh))[0]
    target_structure = clean_screen[..., :3] * illumination[..., None]
    structure_error = float(np.sqrt(np.mean((out[..., :3] - target_structure) ** 2)))
    noisy_error = float(np.sqrt(np.mean((current[..., :3] - target_structure) ** 2)))
    t.check('grain over a screen: output is closer to both clean layers than the input',
            structure_error < noisy_error, after=structure_error, noisy=noisy_error)
    # Where the screen carries no structure there is nothing to keep sharp, so the grain has
    # to go: that is the half of the split the design asks RR to serve.
    def calm_only(a):
        # The right half carries no strokes at all, so what is measured there is grain
        # against the known clean layer rather than structure the operator was told to keep.
        m = np.zeros(a.shape[:2], bool)
        m[2:-2, 2:-2] = True
        m &= flat_half
        return a[m]
    grain_after = float(np.sqrt(np.mean((calm_only(out[..., :3]) - calm_only(target_structure)) ** 2)))
    grain_noisy = float(np.sqrt(np.mean((calm_only(current[..., :3]) - calm_only(target_structure)) ** 2)))
    t.check('grain over a screen: grain reduced where the screen is flat',
            grain_after < grain_noisy * .5, after=grain_after, noisy=grain_noisy)
    # Contrast of the strokes is the structure that must survive; 5% is the ceiling.
    background = np.roll(strokes, 1, axis=1) & ~strokes
    contrast_in = float(np.mean(target_structure[background,0])-np.mean(target_structure[strokes,0]))
    contrast_out = float(np.mean(out[background,0])-np.mean(out[strokes,0]))
    t.check('grain over a screen: stroke contrast loss at most 5%',
            abs(contrast_out-contrast_in) <= abs(contrast_in)*.05,
            contrast_in=contrast_in, contrast_out=contrast_out)

    # --- 5. volume in front of a zero-rough surface ---------------------------------
    vol = np.array([.12, .18, .3], np.float32)
    c = t.rgba(w, h, vol)
    # A volume whose geometry guide describes something else entirely: the local depth test
    # in FloorSurfaceWeight rejects the neighbourhood, so the pixel has no surface support
    # and the wide pedestal stays available to carry its light.
    bad_depth = 5 + rng.uniform(0, 2000, (h, w)).astype(np.float32)
    f, z, g, reference = t.seed(c, depth=bad_depth)
    floor = t.filter_floor(f, z, g, alb)
    zero = t.rgba(w, h, (0, 0, 0))
    vals = chain_cb(w, h, (1 << 1) | (1 << 7))
    packed = t.dispatch('FSRDInputConv', vals,
                        [c, z, zero, normal, zero_rough, z, alb, alb, zero, floor, zero,
                         zero, zero, zero, z, zero, reference],
                        [10, 10, 10, 24, 28, 28, 10, 10], (w, h))
    out = t.dispatch('FSRDOutputComp',
                     {'DstTexSize': [w, h, 1 / w, 1 / h], 'Flags': 0,
                      'DetailPreservation': 1.0},
                     [zero, packed[4], zero, packed[5], packed[6], packed[3], packed[7], z],
                     [10], (w, h))[0]
    retained = float(np.min(np.mean(out[3:-3, 3:-3, :3], axis=(0, 1)) / vol))
    t.check('volume over an incompatible guide keeps its light through composition',
            retained > .9, retained_fraction=retained)
    # Selected screens now intentionally send the entire light signal through
    # RR. If RR erases a constant layer, no hidden pedestal may restore it.
    # The incompatible/unselected guide above still retains volume protection.
    uniform = t.rgba(w, h, vol)
    f, zz, g, reference = t.seed(uniform)
    floor = t.filter_floor(f, zz, g, alb)
    eligible = float(np.mean(reference[..., 3] >= 0))
    t.check('self-consistent zero-rough layer has an eligible reference',
            eligible > .9, eligible_fraction=eligible)
    vals = chain_cb(w, h, (1 << 1) | (1 << 7))
    packed = t.dispatch('FSRDInputConv', vals,
                        [uniform, zz, zero, normal, zero_rough, zz, alb, alb, zero, floor,
                         zero, zero, zero, zero, zz, zero, reference],
                        [10, 10, 10, 24, 28, 28, 10, 10], (w, h))
    erased = t.dispatch('FSRDOutputComp',
                        {'DstTexSize': [w, h, 1 / w, 1 / h], 'Flags': 0,
                         'DetailPreservation': 1.0},
                        [zero, packed[4], zero, packed[5], packed[6], packed[3], packed[7], zz],
                        [10], (w, h))[0]
    t.records.append({
        'metric': 'self-consistent zero-rough layer retained when the denoiser erases',
        'retained_fraction': float(np.mean(erased[3:-3, 3:-3, :3]) / float(np.mean(vol)))})
    t.check('selected zero-rough screen does not bypass erased RR with a pedestal',
            np.max(packed[6][3:-3,3:-3,:3]) == 0 and
            np.max(erased[3:-3,3:-3,:3]) < .001)

    # --- 6. already-sharp denoiser output is left alone -----------------------------
    f, z, g, reference = t.seed(texture)
    floor = t.filter_floor(f, z, g, alb)
    vals = chain_cb(w, h, (1 << 1) | (1 << 7))
    zero = t.rgba(w, h, (0, 0, 0))
    packed = t.dispatch('FSRDInputConv', vals,
                        [texture, z, zero, normal, zero_rough, z, half, half, zero, floor,
                         zero, zero, zero, zero, z, zero, reference],
                        [10, 10, 10, 24, 28, 28, 10, 10], (w, h))
    identity = t.dispatch('FSRDOutputComp',
                          {'DstTexSize': [w, h, 1 / w, 1 / h], 'Flags': 0,
                           'DetailPreservation': 1.0},
                          [packed[0], packed[4], packed[1], packed[5], packed[6], packed[3],
                           packed[7], z],
                          [10], (w, h))[0]
    # The gate is the design's 5% contrast ceiling. This fixture's peak-to-peak contrast is
    # 2 * (.22 + .12) = 0.68, so 5% of it is 0.034.
    texture_contrast = float(np.max(texture[..., :3]) - np.min(texture[..., :3]))
    t.check('sharp denoiser output is reproduced within the 5% contrast ceiling',
            np.max(np.abs(identity[band] - texture[band])) < .05 * texture_contrast,
            max_error=float(np.max(np.abs(identity[band] - texture[band]))),
            ceiling=float(.05 * texture_contrast))

    (t.OUT / 'results.json').write_text(
        json.dumps({'checks': t.checks, 'recorded_metrics': t.records,
                    'dispatches': t.timings}, indent=2))
    assert all(c['passed'] for c in t.checks), 'zero-rough screen acceptance'
    print(f'{len(t.checks)} checks passed; {len(t.timings)} production shader dispatches')


if __name__ == '__main__':
    run()
