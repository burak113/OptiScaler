"""CPU arithmetic-only Ek B boundary proof; no compiler, native or GPU work.

PASS here expresses one thing: the recomputed S1 formulas and the shared
2 GiB Selase decision boundaries reproduce exactly, and the leading named
nominal plan/slot counts do not exceed the documented limit margins. NOTHING
about real D3D allocation, retained graph age or resident VRAM is claimed.
"""
import json
from pathlib import Path
import os

from fsrd_recovery_memory_model import (GIB, MIB, GRAPH_BYTE_LIMIT, STAGING_SLOT_LIMIT,
    PlanBytes, S1_FULL_GIB, S1_MIXED_GIB, S1_STAGING_MIB, StagingByteLedgerModel,
    chain_plan, crosses_plan_limit, graph_texture_plan_count, payload_bytes,
    staging_bytes, summary_table)


def close(value, expected, places=4):
    return round(value, places) == round(expected, places)


def run(checks):
    records = []

    def check(name, passed, **numbers):
        records.append(dict(name=name, passed=bool(passed), **numbers))
        print(("PASS " if passed else "FAIL ") + name, numbers, flush=True)

    plan = payload_bytes(1505, 847)
    check("recovery graph plan is the55-texture host plan",
          graph_texture_plan_count() == 55, textures=graph_texture_plan_count())
    check("formulas reproduce S1 nominal payloads",
          all(close(payload_bytes(*size).full / GIB, S1_FULL_GIB[size], 6)
              for size in S1_FULL_GIB) and
          all(close(payload_bytes(*size).mixed / GIB, S1_MIXED_GIB[size], 6)
              for size in S1_MIXED_GIB),
          **{f"{w}x{h}": [round(payload_bytes(w, h).full / GIB, 6),
                          round(payload_bytes(w, h).mixed / GIB, 6)]
             for w, h in S1_FULL_GIB})
    slot = plan.staging_slot / MIB
    check("staging slot cells equal16 B/px logical payload",
          all(close(payload_bytes(*size).staging_slot / MIB, value, 3)
              for size, value in S1_STAGING_MIB.items()) and
              close(slot, S1_STAGING_MIB[1505, 847], 3),
          slot_mib_1505=round(slot, 6))
    check("32-slot staging cell reproduces the formula for every internal size",
          close(payload_bytes(1505, 847).staging_slot * STAGING_SLOT_LIMIT / MIB,
                622.429199, 6) and
          close(payload_bytes(1505, 847).staging_slot * 4 / MIB, 77.803650, 6),
          slot32_mib=round(payload_bytes(1505, 847).staging_slot * STAGING_SLOT_LIMIT / MIB, 6))

    ab_full_1440 = chain_plan("full", 2, 2560, 1440)
    single_full_4k = chain_plan("full", 1, 3840, 2160)
    ab_mixed_4k = chain_plan("mixed", 2, 3840, 2160)
    check("1440p A+B Full already exceeds the shared2GiB nominal limit",
          crosses_plan_limit("full", 2, 2560, 1440) and
          close(ab_full_1440 / GIB, 2.013992, 6), gib=round(ab_full_1440 / GIB, 6))
    check("single 4K Full already exceeds the shared2GiB nominal limit",
          crosses_plan_limit("full", 1, 3840, 2160) and
          close(single_full_4k / GIB, 2.265746, 6), gib=round(single_full_4k / GIB, 6))
    check("4K A+B Mixed already exceeds the shared2GiB nominal limit",
          crosses_plan_limit("mixed", 2, 3840, 2160) and
          close(ab_mixed_4k / GIB, 2.966046, 6), gib=round(ab_mixed_4k / GIB, 6))
    check("1505x847 A+B Full stays nominally inside the shared cap",
          not crosses_plan_limit("full", 2, 1505, 847) and
          close(2 * payload_bytes(1505, 847).full / GIB, 0.696650, 6),
          gib=round(2 * payload_bytes(1505, 847).full / GIB, 6))
    check("1505x847 warm4+conversion is the S1-scaled snapshot class",
          close(payload_bytes(1505, 847).staging_slot * 4 / MIB, 77.804, 3) and
          close(staging_bytes(1505, 847, 4, debug_targets_per_slot=0) / MIB, 77.804, 3),
          warm4_mib=round(payload_bytes(1505, 847).staging_slot * 4 / MIB, 6))

    warm = StagingByteLedgerModel(GRAPH_BYTE_LIMIT, 2560, 1440)
    nominal_warm = warm.slot * 32
    check("ledger at its nominal cap admits all32 slots of one 1440p context",
          warm.admit(32) and warm.retained == nominal_warm and
          warm.retained_peak == nominal_warm, payload=nominal_warm)
    warm.retire(32)
    check("ledger retirement returns the exact admitted bytes",
          warm.retained == 0 and warm.retired_total == nominal_warm and
          not warm.retire(1) and not warm.retire(0), retired_total=warm.retired_total)

    budget = StagingByteLedgerModel(4 * payload_bytes(1505, 847).staging_slot,
                                    1505, 847)
    admitted = [budget.admit(1) for _ in range(4)]
    check("byte admission stops exactly at the configured retained budget",
          all(admitted) and not budget.admit(1) and budget.rejected == 1 and
          budget.retained == budget.limit, retained=budget.retained, limit=budget.limit)
    check("retirement restores admission availability exactly",
          budget.retire(4) and budget.admit(4) and budget.retained == budget.limit,
          peak=budget.retained_peak)
    sandbox = StagingByteLedgerModel(0, 1505, 847)
    check("limit0 means byte admission is disabled rather than infinite",
          not sandbox.byte_admission_active and sandbox.admit(32) and
          sandbox.retained == sandbox.slot * 32, retained=sandbox.retained)

    path = Path(os.environ.get('FSRD_GPU_TEST_OUTPUT', 'F:/FSRD/sol_batch/15c-recovery/memory-model'))
    path.mkdir(parents=True, exist_ok=True)
    (path / 'results.json').write_text(
        json.dumps(dict(checks=len(records), results=records, passed=all(c['passed'] for c in records),
                        snapshot=summary_table(), scope=__doc__), indent=2) + '\n', encoding='utf-8')
    if not all(c['passed'] for c in records):
        raise SystemExit(1)


if __name__ == '__main__':
    run([])
