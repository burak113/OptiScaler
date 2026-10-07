"""Albedo-trust evidence uses independent surface samples and full RR radiance.

The full alternate witness must not inherit current Floor/Skip or main residual
noise. Flat reflection over a hidden textured albedo and real textured light
provide opposing controls, so invariance cannot pass through an inactive vote.
"""
import json
import numpy as np
import run_fsrd_gpu_tests as t


def evidence(w, h, depth):
    y, x = np.indices((h, w))
    spec = t.rgba(w, h, (0, 0, 0))
    spec[..., :3] = np.where((x + y) % 2 == 0, .1, .8)[..., None]
    zero = t.rgba(w, h, (0, 0, 0))
    # Flat light over a varying albedo is potential evidence only with enough support.
    return t.dispatch('FSRDAlbedoTrustEvidence',
                      {'DstTexSize': [w, h, 1 / w, 1 / h], 'DemodDivisorFloor': .008},
                      [t.rgba(w, h, (.2, .2, .2)), zero, spec, zero, zero,
                       depth, t.rgba(w, h, (.5, .5, .2)), t.rgba(w, h, (0, 0, 0), 1)],
                      [16], (w, h))[0]


def full_alternate_witness_contract(directory=None):
    directory = t.PRE if directory is None else directory
    w, h = 35, 27
    y, x = np.indices((h, w))
    checker = (x + y) % 2 == 0
    zero = t.rgba(w, h, (0, 0, 0))
    specular_albedo = t.rgba(w, h, (.004, .006, .002))
    diffuse_albedo = zero.copy()
    diffuse_albedo[..., :3] = np.where(checker, .002, .72)[..., None]
    depth = np.full((h, w), 10, np.float32)
    normals = t.rgba(w, h, (.5, .5, .2))
    eligible = t.rgba(w, h, (0, 0, 0), 1)
    full_specular = t.rgba(w, h, (.13, .17, .19))
    full_diffuse = t.rgba(w, h, (.23, .29, .31))
    roi = (slice(4, -4), slice(4, -4))

    def vote(flags, *, direct_diffuse=zero, skip=zero,
             specular_signal=zero, diffuse_signal=zero,
             alternate_specular=full_specular, alternate_diffuse=full_diffuse):
        return t.dispatch('FSRDAlbedoTrustEvidence',
                          {'DstTexSize': [w, h, 1 / w, 1 / h], 'Flags': flags,
                           'DemodDivisorFloor': .008},
                          [alternate_specular, direct_diffuse, specular_albedo,
                           diffuse_albedo, skip, depth, normals, eligible,
                           alternate_diffuse, specular_signal, diffuse_signal],
                          [16], (w, h), directory=directory)[0]

    control = vote(2)
    t.check('full alternate flat reflection identifies hidden textured albedo',
            np.all(control[roi][..., 0] > .99) and np.all(control[roi][..., 1] > .99),
            minimum_unsupported=float(control[roi][..., 0].min()),
            minimum_structure=float(control[roi][..., 1].min()))

    # These are independently constructed current-frame inputs. In particular,
    # low albedo enables divisor-floor losses in the main signal controls.
    residual = t.rgba(w, h, (4, 4, 4))
    pedestal = zero.copy()
    pedestal[..., :3] = (.05 + 10 * np.sin(.27*x + .19*y)**2)[..., None] * [1., .5, 2.]
    main_specular = zero.copy()
    main_specular[..., :3] = np.where(checker, 0, 10000)[..., None]
    main_diffuse = zero.copy()
    main_diffuse[..., :3] = np.where(checker, 10000, 0)[..., None]
    cases = (
        ('main diffuse residual', dict(direct_diffuse=residual)),
        ('current Floor Skip', dict(skip=pedestal)),
        ('main specular divisor loss', dict(specular_signal=main_specular)),
        ('main diffuse divisor loss', dict(diffuse_signal=main_diffuse)),
        ('combined current colour change', dict(direct_diffuse=residual, skip=pedestal,
                                              specular_signal=main_specular,
                                              diffuse_signal=main_diffuse)),
    )
    for flags in (2, 3):
        for name, arguments in cases:
            result = vote(flags, **arguments)
            t.check(f'full alternate witness ignores {name} flags={flags}',
                    np.array_equal(result, control),
                    maximum_vote_change=float(np.max(np.abs(result - control))))

    # Independently known radiance carries the material's actual texture. A
    # constant classifier would satisfy the invariance above and fail here.
    clean_radiance = specular_albedo + diffuse_albedo
    textured = vote(2, alternate_specular=clean_radiance * .25,
                    alternate_diffuse=clean_radiance * .75)
    t.check('full alternate true textured light remains supported',
            np.all(textured[roi][..., 0] < .01) and np.all(textured[roi][..., 1] > .99),
            maximum_unsupported=float(textured[roi][..., 0].max()),
            minimum_structure=float(textured[roi][..., 1].min()))

    # The specular-only path still has to reconstruct diffuse radiance from its
    # main demodulated output and current diffuse Skip. Its meaningful controls
    # therefore respond to those inputs, and a shared diffuse lobe is counted.
    spec_only_flat = vote(0)
    spec_only_texture = vote(0, direct_diffuse=t.rgba(w, h, (4, 4, 4)))
    shared_diffuse_texture = vote(1, alternate_diffuse=t.rgba(w, h, (4, 4, 4)))
    current_skip_texture = vote(0, skip=diffuse_albedo * 4)
    t.check('specular-only flat light still identifies hidden texture',
            np.all(spec_only_flat[roi][..., 0] > .99))
    t.check('specular-only main diffuse texture remains supported',
            np.all(spec_only_texture[roi][..., 0] < .01))
    t.check('specular-only shared diffuse texture remains supported',
            np.all(shared_diffuse_texture[roi][..., 0] < .01))
    t.check('specular-only diffuse Skip remains part of its witness',
            np.all(current_skip_texture[roi][..., 0] < .01))


def run():
    t.OUT = t.OUT.parent / 'albedo_support'
    t.OUT.mkdir(parents=True, exist_ok=True)
    t.build_runner()
    for w, h in ((1, 1), (2, 2), (3, 3), (1, 17), (17, 1)):
        votes = evidence(w, h, np.full((h, w), 10, np.float32))
        t.check(f'{w}x{h}: fewer than ten unique samples cannot authorize recovery',
                np.all(np.isfinite(votes)) and np.all(votes == 0),
                maximum_vote=float(np.max(votes)))

    w = h = 17
    # The same one-pixel surface at an edge and in the interior has at most nine
    # independent samples. Replicating edge texels must not turn it into 45 votes.
    for column in (0, 8, 16):
        depth = np.full((h, w), 20, np.float32)
        depth[:, column] = 10
        votes = evidence(w, h, depth)
        t.check(f'thin surface at x={column} abstains', np.all(votes[:, column] == 0),
                maximum_vote=float(np.max(votes[:, column])))

    votes = evidence(w, h, np.full((h, w), 10, np.float32))
    t.check('supported interior still supplies unsupported-albedo evidence',
            np.all(votes[4:-4, 4:-4] > .99))
    full_alternate_witness_contract()
    (t.OUT / 'results.json').write_text(json.dumps({'checks': t.checks, 'dispatches': t.timings}, indent=2))
    assert all(c['passed'] for c in t.checks), 'albedo support regression'
    print(f'{len(t.checks)} checks passed; {len(t.timings)} production shader dispatches')


if __name__ == '__main__':
    run()
