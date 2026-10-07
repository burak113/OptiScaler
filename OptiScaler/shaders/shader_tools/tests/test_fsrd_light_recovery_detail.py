"""Light Anchor Mix retains detail without recycling coarse Floor noise.

Independent noisy frames and moving radiance on stationary geometry. The existing
specular-noise suite separately bounds grain, shared noise and lying seed alpha.
The controlled Floor probes keep the native denoiser output independent from the
current noisy pedestal in both Light and Full recovery.
"""
import json
import numpy as np
import run_fsrd_gpu_tests as t
from test_fsrd_panel_recovery import blur


def floor_support_contract(directory=None, baseline=None):
    directory = t.PRE if directory is None else directory
    w, h = 65, 49
    y, x = np.indices((h, w))
    roi = (slice(8, -8), slice(8, -8), slice(0, 3))
    zero = t.rgba(w, h, (0, 0, 0))
    spec = t.rgba(w, h, (.8, .8, .8))
    diff = t.rgba(w, h, (.2, .2, .2))
    normal = t.rgba(w, h, (.5, .5, .4), 0)
    depth = np.full((h, w), 10, np.float32)
    native_flat = t.rgba(w, h, (.15, .15, .15))
    records = []

    def compose(reference, skip, native=native_flat, *, detail=1, anchor=4, mix=1,
                method=6, path=directory, alternate=None, trust=0, guide=normal):
        flags = 0 if alternate is None else 1 << 8
        cb = dict(DstTexSize=[w, h, 1/w, 1/h], Flags=flags,
                  DetailPreservation=detail, RecoveryMask=6, SpatialTemporalMask=method,
                  SpecularAlbedoDemodulation=1, DiffuseAlbedoModulation=1,
                  FloorHandoverAnchorClamp=anchor, FloorHandoverCorrelationMix=mix,
                  LumaRecovery=1, ChromaRecovery=1,
                  UnsupportedAlbedoRecovery=trust, DemodDivisorFloor=.008)
        inputs = [zero, spec, native / .2, diff, skip, guide, reference, depth]
        if alternate is not None:
            inputs += [zero, t.rgba(w, h, (-1, -1, -1), -1),
                       np.zeros((h, w, 4), np.uint32), alternate * .8,
                       t.rgba(w, h, (0, 0, 0), 1),
                       np.full((h, w, 2), 4, np.float32), alternate * .2,
                       zero, native / .2]
        return t.dispatch('FSRDOutputComp', cb, inputs, [10], (w, h), directory=path)[0]

    def measure(label, output, base, **metadata):
        delta = output[roi] - base[roi]
        row = dict(case=label, returned_rms=float(np.sqrt(np.mean(delta**2))),
                   returned_p99=float(np.percentile(abs(delta), 99)), **metadata)
        records.append(row)
        print(json.dumps(row), flush=True)
        return row

    first_reference = first_skip = None
    for chromatic in (False, True):
        rng = np.random.default_rng(84191 + int(chromatic))
        field = zero.copy()
        field[..., :3] = rng.normal(0, 1, (h, w, 3 if chromatic else 1))
        field = blur(field, 12)[..., :3]
        field -= np.mean(field[8:-8, 8:-8], axis=(0, 1))
        field *= .055 / np.sqrt(np.mean(field[8:-8, 8:-8]**2, axis=(0, 1)))
        skip = t.rgba(w, h, (.20, .20, .20))
        skip[..., :3] += .55 * field
        for alpha in (.003, .012):
            reference = t.rgba(w, h, (.35, .35, .35), alpha)
            reference[..., :3] += field
            base = compose(reference, skip, detail=0)
            recovered = compose(reference, skip)
            row = measure('coarse shared Floor noise', recovered, base,
                          chromatic=chromatic, reference_sigma=alpha)
            t.check(f'coarse Floor cannot authorize Light noise chromatic={chromatic} sigma={alpha}',
                    row['returned_rms'] <= .0003 and row['returned_p99'] <= .0005, **row)
            full = compose(reference, skip, method=0)
            row = measure('Full/Anchor shared Floor noise', full, base,
                          chromatic=chromatic, reference_sigma=alpha)
            t.check(f'coarse Floor cannot authorize Full noise chromatic={chromatic} sigma={alpha}',
                    row['returned_rms'] <= .0003 and row['returned_p99'] <= .0005, **row)
            if first_reference is None:
                first_reference, first_skip = reference, skip

    # Both opt-outs keep their previous recovery behavior. When a checkpoint is
    # provided this is also a byte comparison against its actual DXIL.
    base = compose(first_reference, first_skip, detail=0)
    for method in (6, 0):
        for anchor, mix in ((0, 1), (4, 0)):
            result = compose(first_reference, first_skip, anchor=anchor, mix=mix, method=method)
            row = measure('recovery opt-out', result, base, anchor=anchor, mix=mix, method=method)
            t.check(f'opt-out remains active method={method} anchor={anchor} mix={mix}',
                    row['returned_rms'] > .001, **row)
            if baseline is not None:
                previous = compose(first_reference, first_skip, anchor=anchor, mix=mix, method=method, path=baseline)
                t.check(f'opt-out retains checkpoint bytes method={method} anchor={anchor} mix={mix}',
                        np.array_equal(result, previous))

    for method in (6, 0):
        for amount in (0., .20):
            skip = t.rgba(w, h, (amount, amount, amount))
            result = compose(first_reference, skip, method=method)
            base = compose(first_reference, skip, detail=0, method=method)
            row = measure('constant pedestal with flat native RR', result, base, skip_level=amount, method=method)
            t.check(f'constant Skip leaves flat RR steady method={method} level={amount}', row['returned_rms'] <= .0003, **row)
            if baseline is not None:
                previous = compose(first_reference, skip, method=method, path=baseline)
                t.check(f'constant Skip retains checkpoint bytes method={method} level={amount}', np.array_equal(result, previous))

    # Moment/support storage must stay finite and exposure-independent in dim
    # and HDR lighting. Normalise the observed error, not a shader statistic.
    for exposure in (.03125, 8000.):
        reference = first_reference * exposure
        native = native_flat * exposure
        skip = first_skip * exposure
        for method in (6, 0):
            base = compose(reference, skip, native, detail=0, method=method)
            result = compose(reference, skip, native, method=method)
            delta = (result[roi] - base[roi]) / exposure
            row = dict(case='exposure-scaled shared Floor noise', exposure=exposure, method=method,
                       normalized_returned_rms=float(np.sqrt(np.mean(delta**2))),
                       normalized_returned_p99=float(np.percentile(abs(delta), 99)))
            records.append(row)
            t.check(f'dim/HDR Floor support stays finite and rejects shared grain method={method} exposure={exposure}',
                    np.isfinite(result).all() and row['normalized_returned_rms'] <= .0003 and
                    row['normalized_returned_p99'] <= .0005, **row)
            for amount in (0., .20):
                constant = t.rgba(w, h, (amount, amount, amount)) * exposure
                result = compose(reference, constant, native, method=method)
                t.check(f'dim/HDR constant Skip remains finite method={method} level={amount} exposure={exposure}',
                        np.isfinite(result).all())
                if baseline is not None:
                    previous = compose(reference, constant, native, method=method, path=baseline)
                    t.check(f'dim/HDR constant Skip retains checkpoint bytes method={method} level={amount} exposure={exposure}',
                            np.array_equal(result, previous))

    # Genuine texture has independent native support even with a nonzero Floor.
    pattern = (.12*np.sin(.63*x + .37*y))[..., None]
    truth = t.rgba(w, h, (.35, .35, .35))
    truth[..., :3] += pattern
    reference = truth.copy()
    reference[..., :3] += np.random.default_rng(19837).normal(0, .006, (h, w, 3))
    reference[..., 3] = .006
    native = native_flat.copy(); native[..., :3] += .55 * pattern
    skip = t.rgba(w, h, (.20, .20, .20))
    for method in (6, 0):
        for alternate in (None, truth * .55 + t.rgba(w, h, (.1575, .1575, .1575))):
            strength = 0 if alternate is None else 1
            base = compose(reference, skip, native, detail=0, alternate=alternate, trust=strength, method=method)
            recovered = compose(reference, skip, native, alternate=alternate, trust=strength, method=method)
            before = float(np.mean((base[roi] - truth[roi])**2))
            after = float(np.mean((recovered[roi] - truth[roi])**2))
            t.check(f'independent textured RR support preserves recovery method={method} alternate={alternate is not None}',
                    after < .5 * before, base_mse=before, recovered_mse=after)

    # Clean current structure keeps its explicit authority with a real pedestal.
    edge = t.rgba(w, h, (.1, .3, .8), 0); edge[:, w//2:, :3] = (.8, .3, .1)
    constant_skip = t.rgba(w, h, (.04, .04, .04))
    for method in (6, 0):
        native = blur(edge, 2) - constant_skip
        base = compose(edge, constant_skip, native, detail=0, method=method)
        restored = compose(edge, constant_skip, native, method=method)
        before = float(np.mean((base[..., :3] - edge[..., :3])**2))
        after = float(np.mean((restored[..., :3] - edge[..., :3])**2))
        error = float(np.max(np.abs(restored[..., :3] - edge[..., :3])))
        # Full recovery has always blended this edge; its checkpoint error is
        # nonzero. Require useful restoration in both modes and the existing
        # quiet-reference fixed point in Light, which restores it exactly.
        t.check(f'clean sharp edge retains recovery with nonzero Skip method={method}',
                after < .75 * before and (method == 0 or error < .001),
                base_mse=before, recovered_mse=after, maximum_error=error)
        if baseline is not None:
            previous = compose(edge, constant_skip, native, method=method, path=baseline)
            t.check(f'clean sharp edge retains checkpoint bytes method={method}',
                    np.array_equal(restored, previous))

    # Full and partial alternate replacement removes only the surviving Floor
    # from the witness. The removed part must not create independent texture.
    for method in (6, 0):
        for strength in (.5, 1.):
            alternate = t.rgba(w, h, (.35, .35, .35))
            base = compose(first_reference, first_skip, detail=0, alternate=alternate, trust=strength, method=method)
            result = compose(first_reference, first_skip, alternate=alternate, trust=strength, method=method)
            row = measure('alternate shared Floor noise', result, base, strength=strength, method=method)
            t.check(f'alternate surviving Floor cannot authorize noise method={method} strength={strength}',
                    row['returned_rms'] <= .0003 and row['returned_p99'] <= .0005, **row)

    # A valid certificate grants quiet current raw authority. Its neighbour's
    # denoised residual is flat, so the certificate must not authorize grain
    # there. In screenRROnly routing, native RR keeps the full source on the
    # certified side while the ordinary side submits its residual.
    certificate = first_skip.copy()
    certificate[:, :w//2, :3] = .35; certificate[:, :w//2, 3] = -1
    reference = first_reference.copy()
    reference[:, :w//2, :3] = .35; reference[:, :w//2, 3] = 0
    for native_step, screen_domain in ((False, False), (True, False), (True, True)):
        native = native_flat.copy()
        guide = normal.copy()
        if native_step:
            native[:, :w//2, :3] = .35
        if screen_domain:
            guide[:, :w//2, 3] = 1/3
        for method in (6, 0):
            suffix = f'method={method} full_native={native_step} screen_domain={screen_domain}'
            base = compose(reference, certificate, native, detail=0, method=method, guide=guide)
            result = compose(reference, certificate, native, method=method, guide=guide)
            t.check('quiet current-source certificate retains authority beside noisy Floor ' + suffix,
                    np.array_equal(result[:, :w//2, :3], certificate[:, :w//2, :3].astype(np.float16).astype(np.float32)))
            boundary = result[8:-8, w//2:w//2+3, :3] - base[8:-8, w//2:w//2+3, :3]
            row = dict(case='ordinary neighbour of clean certificate', method=method,
                       native_rr_step=native_step, certificate_screen_domain=screen_domain,
                       returned_rms=float(np.sqrt(np.mean(boundary**2))),
                       returned_p99=float(np.percentile(abs(boundary), 99)))
            records.append(row)
            t.check('clean certificate cannot turn current colour into neighbouring RR support ' + suffix,
                    row['returned_rms'] <= .0003 and row['returned_p99'] <= .0005, **row)
    return records


def mixed_surface_hdr_contract(directory=None, baseline=None):
    """Rejected bright geometry cannot erase independently denoised dim detail.

    The dim patch has the same known textured signal as the active recovery
    control above. Only radiance on a different depth surface changes. Both
    constant and varying accepted Floor exercise its independence from that
    rejected surface, with all uploaded RR values representable in FP16.
    """
    directory = t.PRE if directory is None else directory
    w, h = 65, 49
    y, x = np.indices((h, w))
    roi = (slice(10, 14), slice(10, 15), slice(0, 3))
    zero = t.rgba(w, h, (0, 0, 0))
    diffuse = t.rgba(w, h, (.2, .2, .2))
    specular = t.rgba(w, h, (.8, .8, .8))
    guide = t.rgba(w, h, (.5, .5, .4), 0)
    depth = np.full((h, w), 10, np.float32)
    depth[:, :8] = 50
    pattern = (.12 * np.sin(.63*x + .37*y))[..., None]
    truth = t.rgba(w, h, (.35, .35, .35))
    truth[..., :3] += pattern
    field = zero.copy()
    field[..., :3] = np.random.default_rng(837193).normal(0, 1, (h, w, 1))
    field = blur(field, 4)[..., :3]
    field -= field[8:-8, 8:-8].mean((0, 1))
    field *= .004 / np.sqrt(np.mean(field[8:-8, 8:-8]**2, (0, 1)))
    cb = dict(DstTexSize=[w, h, 1/w, 1/h], Flags=0, RecoveryMask=6,
              SpatialTemporalMask=6, SpecularAlbedoDemodulation=1,
              DiffuseAlbedoModulation=1, FloorHandoverAnchorClamp=4,
              FloorHandoverCorrelationMix=1, LumaRecovery=1, ChromaRecovery=1,
              UnsupportedAlbedoRecovery=0, DemodDivisorFloor=.008)
    records = []
    for shared_floor in (False, True):
        quiet = None
        for origin in (.15, 8000., 32000.):
            native = t.rgba(w, h, (.15, .15, .15))
            native[..., :3] += .55 * pattern
            native[:, :8, :3] = origin
            skip = t.rgba(w, h, (.2, .2, .2))
            if shared_floor:
                skip[..., :3] += .55 * field
            skip[:, :8, :3] = .7
            reference = truth.copy()
            reference[..., :3] += np.random.default_rng(19837).normal(0, .006, (h, w, 3))
            reference[..., 3] = .006
            reference[:, :8, :3] = origin + .7
            reference[:, :8, 3] = .003
            # Send the bright surface through specular RR: 32000/.8 is finite
            # FP16. Diffuse demodulation by .2 would overflow its transport.
            rr_specular = zero.copy()
            rr_specular[:, :8, :3] = native[:, :8, :3] / .8
            rr_diffuse = native / .2
            rr_diffuse[:, :8, :3] = 0
            inputs = [rr_specular, specular, rr_diffuse, diffuse, skip, guide, reference, depth]
            t.check(f'mixed HDR inputs remain representable shared_floor={shared_floor} origin={origin}',
                    all(np.isfinite(signal.astype(np.float16)).all() for signal in inputs))
            base = t.dispatch('FSRDOutputComp', dict(cb, DetailPreservation=0),
                              inputs, [10], (w, h), directory=directory)[0]
            result = t.dispatch('FSRDOutputComp', dict(cb, DetailPreservation=1),
                                inputs, [10], (w, h), directory=directory)[0]
            before = float(np.mean((base[roi] - truth[roi])**2))
            after = float(np.mean((result[roi] - truth[roi])**2))
            row = dict(case='texture on dim geometry beside rejected HDR surface',
                       shared_floor=shared_floor, rejected_native_radiance=origin,
                       base_mse=before, recovered_mse=after)
            records.append(row)
            t.check(f'mixed HDR preserves active independent texture shared_floor={shared_floor} origin={origin}',
                    np.isfinite(result).all() and after < .5 * before, **row)
            if quiet is None:
                quiet = result
            else:
                t.check(f'rejected HDR geometry leaves dim texture unchanged shared_floor={shared_floor} origin={origin}',
                        np.array_equal(result[roi], quiet[roi]))
            if baseline is not None:
                previous = t.dispatch('FSRDOutputComp', dict(cb, DetailPreservation=1),
                                      inputs, [10], (w, h), directory=baseline)[0]
                t.check(f'mixed HDR dim texture retains checkpoint bytes shared_floor={shared_floor} origin={origin}',
                        np.array_equal(result[roi], previous[roi]))
    return records


def run():
    t.build_runner()
    w,h=65,49
    y,x=np.indices((h,w))
    roi=(slice(8,-8),slice(8,-8),slice(0,3))
    zero=t.rgba(w,h,(0,0,0))
    spec=t.rgba(w,h,(.8,.8,.8)); diff=t.rgba(w,h,(.2,.2,.2))
    normal=t.rgba(w,h,(.5,.5,.4),0)
    depth=np.full((h,w),10,np.float32)
    cb=dict(DstTexSize=[w,h,1/w,1/h],DetailPreservation=1,RecoveryMask=2,
            SpatialTemporalMask=2,SpecularAlbedoDemodulation=1,DiffuseAlbedoModulation=1,
            FloorHandoverCorrelationMix=1,LumaRecovery=1,ChromaRecovery=1)
    records=[]
    for frame,phase in enumerate((0.0,.85,2.4)):
        truth=t.rgba(w,h,(.35,.4,.45))
        truth[...,:3]+=(.12*np.sin(x*.91+y*.83+phase))[...,None]
        rr=blur(truth,6)
        rr_spec=rr.copy(); rr_spec[...,:3]/=.8
        ref=truth.copy()
        ref[...,:3]+=np.random.default_rng(137551+frame).normal(0,.01,(h,w,3))
        ref[...,3]=.01
        signal=truth[roi]-np.mean(truth[roi],axis=(0,1),keepdims=True)
        gains={}
        for anchor in (0,4):
            out=t.dispatch('FSRDOutputComp',dict(cb,FloorHandoverAnchorClamp=anchor),
                [rr_spec,spec,zero,diff,zero,normal,ref,depth],[10],(w,h))[0]
            error=float(np.mean((out[roi]-truth[roi])**2))
            gains[anchor]=float(np.sum((out[roi]-np.mean(out[roi],axis=(0,1),keepdims=True))*signal)/
                                np.sum(signal**2))
            records.append(dict(frame=frame,anchor=anchor,mse=error,contrast=gains[anchor]))
            t.check(f'phase {phase} anchor {anchor} improves blurred RR',
                    error < float(np.mean((rr[roi]-truth[roi])**2))*.3,mse=error,contrast=gains[anchor])
        t.check(f'phase {phase} positive anchor retains diagonal detail',gains[4]>.60,contrast=gains[4])
    records.extend(floor_support_contract())
    records.extend(mixed_surface_hdr_contract())
    (t.OUT/'results.json').write_text(json.dumps(dict(checks=t.checks,dispatches=t.timings,records=records),indent=2))
    assert all(c['passed'] for c in t.checks), 'light recovery detail regression'


if __name__=='__main__': run()
