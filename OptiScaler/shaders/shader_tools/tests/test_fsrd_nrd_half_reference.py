"""Independent NumPy half reference for the final YCoCg integer rounding rule.

Run via lead_ops/run_task_test.py --cpu. The native RR fixture separately runs
the actual production shader and compares its stored words with DirectX's CPU
half conversion, including zero, subnormal ties and exponent carries.
"""
from pathlib import Path
import json
import os
import numpy as np


def integer_half_words(values):
    bits = values.view(np.uint32)
    sign = (bits >> 16) & 0x8000
    magnitude = bits & 0x7fffffff
    result = sign.copy()
    normal = magnitude >= 0x38800000
    selected = magnitude[normal].astype(np.uint64)
    result[normal] |= np.minimum(((selected + 0xfff + ((selected >> 13) & 1)) >> 13) - 0x1c000, 0x7c00).astype(np.uint32)
    exponent = magnitude >> 23
    subnormal = ~normal & (exponent >= 102)
    shift = 126 - exponent[subnormal]
    mantissa = (magnitude[subnormal] & 0x7fffff) | 0x800000
    retained = mantissa >> shift
    remainder = mantissa & ((np.uint32(1) << shift) - 1)
    halfway = np.uint32(1) << (shift - 1)
    result[subnormal] |= retained + ((remainder > halfway) | ((remainder == halfway) & ((retained & 1) != 0)))
    return result.astype(np.uint16)


def main():
    rng = np.random.default_rng(0x30312)
    uniform = rng.uniform(-65504, 65504, 1_000_000).astype(np.float32)
    bits = rng.integers(0, 0x477fe001, 1_000_000, dtype=np.uint32)
    bits |= rng.integers(0, 2, len(bits), dtype=np.uint32) << 31
    anchors = np.array([0., -0., 2.**-25, 2.**-24, 3*2.**-25,
                        2.**-14-2.**-25, 2.**-14, 1.99951171875, 65504.], np.float32)
    boundaries = np.concatenate((anchors, np.nextafter(anchors, np.float32(-np.inf)),
                                 np.nextafter(anchors, np.float32(np.inf)), -anchors))
    boundaries = boundaries[np.abs(boundaries) <= 65504]
    values = np.concatenate((uniform, bits.view(np.float32), boundaries))
    assert np.isfinite(values).all() and np.max(np.abs(values)) <= 65504
    expected = values.astype(np.float16).view(np.uint16)
    actual = integer_half_words(values)
    mismatches = int(np.count_nonzero(actual != expected))
    result = dict(cpu_samples=len(values), exact_nearest_half_matches=int(np.count_nonzero(actual == expected)),
                  mismatches=mismatches, boundary_samples=len(boundaries),
                  scope='finite/clamped native half range; signed zero, 2^-25 ties, subnormal/normal boundary, normal carry, 65504',
                  independent_reference='NumPy float32->float16 conversion; actual GPU shader verified separately')
    report = Path(os.environ.get('FSRD_NRD_RR_REPORT', 'E:/FSRD/sol_batch/12c-rr'))
    report.mkdir(parents=True, exist_ok=True)
    (report / 'integer-rne-cpu-reference.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result, indent=2))
    assert mismatches == 0, 'Integer RNE differs from independent IEEE nearest-half reference'


if __name__ == '__main__':
    main()
