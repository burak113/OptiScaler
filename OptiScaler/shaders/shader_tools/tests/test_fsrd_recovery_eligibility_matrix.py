"""CPU D06/WP09 alpha/roughness eligibility matrix assertions.

PASS expresses shipped-conditional arithmetic on the one control model:
ineligible zones never move, the zero-roughness and inactive/nonfinite alpha
zones stay excluded forever, small positive alpha matures and gains
correction energy at the shipped minimum age, committed opaque alpha follows
only RR alpha, and strength0 is a bit-exact RR passthrough on every zone.
This is a mirror of shipped arithmetic; no new eligibility, no compiler,
no native and no GPU work runs here.
"""
import json
import os
from dataclasses import replace
from pathlib import Path

import numpy as np

from fsrd_nrd_lobe_reference_prototype import LobeReferenceRecovery, ReferenceSettings
from fsrd_recovery_eligibility_matrix import (ALPHA_CLASSES, ALPHA_VALUES,
    FRAMES, MIN_AGE, REASONS, ROUGHNESS_CLASSES, classify, counts, matrix_inputs,
    mirror_state, run_case, zone_report)


def alpha_class_of_row(row):
    return ALPHA_CLASSES[row % len(ALPHA_CLASSES)]


def zone_energies(rr, result, rows=5):
    """RGB L2 energy per alpha-row class at one snapshot frame."""
    delta = result[...,:3].astype(np.float64) - rr[...,:3].astype(np.float64)
    energies = {}
    for row in range(rows):
        name = alpha_class_of_row(row)
        energies[name] = float(np.sqrt(np.sum(delta[row::rows] * delta[row::rows])))
    return energies


def run():
    checks = []
    arrays = matrix_inputs()
    state = mirror_state(arrays)
    alpha_field, roughness = state['alpha'], state['roughness']
    yy, _ = np.mgrid[:alpha_field.shape[0], :alpha_field.shape[1]]

    def check(name, passed, **numbers):
        checks.append(dict(name=name, passed=bool(passed), **numbers))
        print(('PASS ' if passed else 'FAIL ') + name, numbers, flush=True)

    check('alpha rows carry the documented classification values',
          np.array_equal(alpha_field[0], np.full(alpha_field.shape[1],
              ALPHA_VALUES['active_plus_one'], '<f2')) and
          np.array_equal(alpha_field[1], np.full(alpha_field.shape[1],
              ALPHA_VALUES['plus_small_half'], '<f2')) and
          np.all(alpha_field[2] == 0.0) and
          np.all(alpha_field[3] == ALPHA_VALUES['negative']) and
          not np.isfinite(alpha_field).all(),
          rows=len(ALPHA_CLASSES))
    check('roughness axis is a column partition containing both classes',
          np.any(roughness > 0) and np.any(roughness == 0) and
          np.all(roughness[:, :16] > 0) and np.all(roughness[:, 16:] == 0),
          rough123=int(np.sum(roughness > 0)), rough0=int(np.sum(roughness == 0)))

    live = run_case(arrays, ReferenceSettings(bound_projection='local_anchor'))
    cold = zone_report(live, 0)
    check('cold first frame is a complete passthrough and ages eligible pixels once',
          cold['output_bitwise_rr'] and cold['correction_energy_l2'] == 0.0 and
          cold['committed_age_max'] == 1.0, frame=cold['frame'])
    late = zone_report(live)
    counts_late = late['reasons']
    check('excluded zones keep their per-lobe exclusion reasons at maturity',
          counts_late.get('roughness0', 0) >= 400 and
          counts_late.get('inactive_alpha', 0) >= 150 and
          counts_late.get('uncertain_hit_distance', 0) >= 80 and
          sum(counts_late.values()) == alpha_field.size,
          reasons=counts_late)
    check('no pixel is classified ineligible-by-history forever',
          counts_late.get('insufficient_history_age', 0) == 0 and
          late['committed_age_max'] >= MIN_AGE,
          committed_max_age=late['committed_age_max'])
    check('committed opaque alpha equals RR alpha at every frame',
          all(r['alpha_bitwise_preserved'] for r in live), frames=FRAMES)
    energies = {}
    operator = LobeReferenceRecovery(ReferenceSettings(bound_projection='local_anchor'))
    replay = None
    for frame in range(FRAMES):
        replay = operator.step(arrays['spec'], arrays['rr'], arrays['depth'],
                               arrays['normal'], arrays['motion'], frame,
                               reset=frame == 0)
    energies = zone_energies(arrays['rr'], replay)
    check('correction energy stays zero in every excluded alpha zone',
          energies['zero'] == 0.0 and energies['negative'] == 0.0 and
          energies['nonfinite'] == 0.0,
          per_zone={k: round(v, 6) for k, v in energies.items()})
    check('active positive alpha zones carry correction energy at maturity',
          energies['active_plus_one'] > 0 and energies['plus_small_half'] > 0,
          active=round(energies['active_plus_one'], 6),
          small=round(energies['plus_small_half'], 6))
    rough_energy = float(np.sqrt(np.sum((replay[..., :3][:, 16:].astype(np.float64) -
        arrays['rr'][..., :3][:, 16:].astype(np.float64)) ** 2)))
    check('zero-roughness columns stay bit-alive with RR for every alpha class',
          rough_energy == 0.0, columns16_ener=rough_energy)

    identity = run_case(arrays, replace(ReferenceSettings(
        bound_projection='local_anchor'), strength=0.0))
    check('strength0 identity keeps the whole matrix bit-exact RR each frame',
          all(r['output_bitwise_rr'] for r in identity) and
          all(r['correction_energy_l2'] == 0.0 for r in identity), frames=FRAMES)

    path = Path(os.environ.get('FSRD_GPU_TEST_OUTPUT', 'F:/FSRD/sol_batch/15c-recovery/eligibility-matrix'))
    path.mkdir(parents=True, exist_ok=True)
    (path / 'results.json').write_text(
        json.dumps(dict(checks=len(checks), results=checks, passed=all(c['passed'] for c in checks),
                        cold=cold, late=late, mirror_priority=list(REASONS),
                        alpha_classes=list(ALPHA_CLASSES), roughness_classes=list(ROUGHNESS_CLASSES),
                        frames=FRAMES, minimum_age=MIN_AGE,
                        scope=__doc__, game_quality_claimed=False), indent=2) + '\n',
        encoding='utf-8')
    if not all(c['passed'] for c in checks):
        raise SystemExit(1)


if __name__ == '__main__':
    run()
