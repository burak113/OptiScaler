"""CPU eligibility matrix support for D06/WP09: alpha times roughness, one model.

The diffuse-alpha0 policy stays exactly the shipped recovery behavior: both
lobes require noisy alpha strictly greater than zero, no sparse membership is
invented, no negative-alpha sentinel is activated and strength0 remains a
pure RR passthrough. Classification mirrors the shipped Reference/Band
conditions explicitly; it is a mirror of shipped arithmetic, not new GPU
behavior. No compiler, native or GPU work runs here.
"""
import os

import numpy as np

from fsrd_nrd_lobe_reference_prototype import LobeReferenceRecovery, ReferenceSettings
from fsrd_nrd_recovery_prototype import decode_normals, neighbourhood

WIDTH, HEIGHT, FRAMES = 33, 29, 24
MIN_AGE = ReferenceSettings().minimum_age
# Mirror priority when several conditions explain one ineligible pixel; a
# pixel is counted once under its highest-priority matching reason.
REASONS = ("uncertain_hit_distance", "roughness0", "inactive_alpha",
           "geometry_mismatch", "insufficient_history_age", "eligible")
ALPHA_CLASSES = ('active_plus_one', 'plus_small_half', 'zero', 'negative', 'nonfinite')
ALPHA_VALUES = {'active_plus_one': 1.0, 'plus_small_half': .03125, 'zero': 0.0,
                'negative': -5.0, 'nonfinite': float('nan')}
ROUGHNESS_CLASSES = ('roughness123', 'roughness0')
ROUGHNESS_BITS = {'roughness123': 123, 'roughness0': 0}


def matrix_inputs():
    """One RGB/geometry context; the alpha axis is rows, roughness axis columns.

    Committed opaque alpha stays 7 everywhere: eligibility reads the NOISY
    hit-distance alpha, never the committed RR alpha.
    """
    yy, xx = np.mgrid[:HEIGHT, :WIDTH]
    rr = np.full((HEIGHT, WIDTH, 4), .5, '<f2')
    rr[..., :3] += np.where((xx + yy) % 2, .03125, -.03125)[..., None].astype('<f2')
    rr[..., 3] = 7
    raw = rr.copy()
    raw[..., :3] += np.where((xx + yy) % 2, .0625, -.0625)[..., None].astype('<f2')
    alpha_row = np.asarray([ALPHA_VALUES[name] for name in ALPHA_CLASSES], '<f2')
    raw[..., 3] = alpha_row[yy % len(ALPHA_CLASSES)]
    depth = np.full((HEIGHT, WIDTH), -8, '<f4')
    normal = np.zeros((HEIGHT, WIDTH), '<u4')
    normal |= 512 | (512 << 10)
    for column, name in enumerate(ROUGHNESS_CLASSES):
        normal[:, (column * WIDTH) // len(ROUGHNESS_CLASSES):
               ((column + 1) * WIDTH) // len(ROUGHNESS_CLASSES)] |= \
            ROUGHNESS_BITS[name] << 20
    motion = np.zeros((HEIGHT, WIDTH, 4), '<f4')
    motion[..., 3] = 1
    return dict(spec=raw, diff=raw, rr=rr, depth=depth, normal=normal, motion=motion)


def mirror_state(arrays):
    """Input-only mirror of the shipped eligibility conditions.

    geometry mirrors the Reference 3x3 contract; alpha uses the noisy
    hit-distance alpha of each lobe input ('spec'/'diff' share one context).
    """
    normal, roughness, material = decode_normals(arrays['normal'])
    depth, motion = arrays['depth'], arrays['motion']
    height, width = depth.shape
    geometry = np.isfinite(depth) & (np.abs(depth) > 1e-5) & (roughness > 0) & \
        np.isfinite(motion).all(-1) & (motion[..., 3] >= .5)
    geometry &= neighbourhood(depth, maximum=True) - neighbourhood(depth, minimum=True) <= \
        ReferenceSettings().depth_relative_tolerance * np.maximum(np.abs(depth), 1e-3)
    geometry &= neighbourhood(material, minimum=True) == neighbourhood(material, maximum=True)
    padded = np.pad(normal, ((1, 1), (1, 1), (0, 0)), mode='edge')
    for dy in range(3):
        for dx in range(3):
            geometry &= np.sum(normal * padded[dy:dy + height, dx:dx + width], -1) > \
                ReferenceSettings().normal_dot_minimum
    alpha = arrays['spec'][..., 3].astype(np.float32)
    return dict(alpha=alpha, roughness=roughness, geometry=geometry,
                age=np.zeros((height, width), np.float32), material=material)


def classify(state):
    """Priority-ranked exclusion reason per pixel (mirror, not new behavior).

    Priority: uncertain_hit_distance(nonninfin alpha) > roughness0 >
    inactive_alpha > geometry_mismatch > insufficient_history_age > eligible.
    Later reasons never overwrite an already-assigned earlier one.
    """
    alpha, roughness, geometry = state['alpha'], state['roughness'], state['geometry']
    reasons = np.empty(alpha.shape, object)
    reasons[:] = 'eligible'
    reasons[~np.isfinite(alpha)] = 'uncertain_hit_distance'
    reasons[(reasons == 'eligible') & (roughness <= 0)] = 'roughness0'
    reasons[(reasons == 'eligible') & (alpha <= 0) & (roughness > 0)] = 'inactive_alpha'
    reasons[(reasons == 'eligible') & ~geometry] = 'geometry_mismatch'
    young = (reasons == 'eligible') & (state['age'] < MIN_AGE)
    reasons[young] = 'insufficient_history_age'
    return reasons


def counts(reasons):
    unique, values = np.unique(reasons, return_counts=True)
    return {name: int(count) for name, count in zip(unique, values)}


def run_case(arrays, settings):
    """Steps the one shipped control model FRAMES times; reports per frame."""
    operator = LobeReferenceRecovery(settings)
    rows = []
    for frame in range(FRAMES):
        result = operator.step(arrays['spec'], arrays['rr'], arrays['depth'],
                               arrays['normal'], arrays['motion'], frame,
                               reset=frame == 0)
        state = mirror_state(arrays)
        # Shipped history ages one step per eligible active pixel inside the
        # Reference pass; strength0 skips the graph entirely, leaving that
        # mirror's computed-history axes zeroed (documented consumption rule).
        if operator.reference is not None:
            state['age'] = operator.reference['age'].copy()
        rr, output = arrays['rr'], result
        differences = output[...,:3].astype(np.float64) - rr[...,:3].astype(np.float64)
        rows.append(dict(frame=frame,
                         reasons=counts(classify(state)),
                         committed_age_max=float(state['age'].max()),
                         correction_energy_l2=float(np.sqrt(np.sum(differences * differences))),
                         output_bitwise_rr=bool(np.array_equal(output.view('<u2'), rr.view('<u2'))),
                         alpha_bitwise_preserved=bool(np.array_equal(output[...,3].view('<u2'),
                                                                     rr[...,3].view('<u2')))))
    return rows


def zone_report(rows, frame=-1):
    """Snapshot of one frame: per-reason pixel shares, energies and identity."""
    row = rows[frame]
    return dict(frame=row['frame'], reasons=row['reasons'],
                correction_energy_l2=row['correction_energy_l2'],
                committed_age_max=row['committed_age_max'],
                output_bitwise_rr=row['output_bitwise_rr'],
                alpha_bitwise_preserved=row['alpha_bitwise_preserved'])
