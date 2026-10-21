"""Independent exhaustive FP16 storage-domain check, not a native GPU test.

The frozen shared scaling shader multiplies RGB and clamps at 65504.  A
power-of-two multiplier has an exact inverse only before that saturation.
This test deliberately includes every nonnegative finite half word, plus -0,
and rejects the known-bad claim that all finite inputs round trip exactly.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import sys

import numpy as np


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
SHADER = REPO / "OptiScaler/shaders/fsrd_preprocess/precompile/FSRDRadianceScale.hlsl"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def shader_rgb_storage_model(words: np.ndarray, factor: float) -> np.ndarray:
    values = words.view(np.float16).astype(np.float32)
    multiplied = values * np.float32(factor)
    # Match the frozen shader's one-sided finite RGB clamp.  This CPU exercise
    # intentionally makes no promise about a typed UAV's alpha NaN payloads.
    clamped = np.where(multiplied > np.float32(65504), np.float32(65504), multiplied)
    return clamped.astype(np.float16).view(np.uint16)


def check() -> dict:
    words = np.concatenate((np.arange(0x7c00, dtype=np.uint16),
                            np.array([0x8000], dtype=np.uint16)))
    values = words.view(np.float16).astype(np.float32)
    cases = []
    for lobe, factor in (("diffuse", 16), ("specular", 256)):
        forward = shader_rgb_storage_model(words, factor)
        returned = shader_rgb_storage_model(forward, 1.0 / factor)
        safe = values * np.float32(factor) <= np.float32(65504)
        equal = returned == words
        assert np.array_equal(returned[safe], words[safe])
        assert np.all(~equal[~safe]), "Saturation must invalidate the blanket inverse claim"
        assert returned[-1] == np.uint16(0x8000), "Negative zero survives RGB model"
        cases.append({
            "lobe": lobe,
            "factor": factor,
            "input_word_count": int(words.size),
            "unsaturated_count": int(np.sum(safe)),
            "exact_roundtrip_count": int(np.sum(equal)),
            "saturated_nonroundtrip_count": int(np.sum(~safe)),
            "largest_exact_positive_input": float(np.max(values[safe])),
            "first_nonroundtrip_input": float(np.min(values[~safe])),
            "zero_and_negative_zero_words_preserved": bool(equal[0] and equal[-1]),
            "all_finite_exact_mutant_rejected": bool(not np.all(equal)),
        })

    # Independent ABI falsifier: conversion factors are per-lobe.  A common
    # scale or swapped inverse cannot be silently accepted as physical units.
    source = np.array([0.03125, 0.125, 0.5], dtype=np.float16).view(np.uint16)
    d = shader_rgb_storage_model(source, 16)
    s = shader_rgb_storage_model(source, 256)
    wrong_d = shader_rgb_storage_model(d, 1.0 / 256)
    wrong_s = shader_rgb_storage_model(s, 1.0 / 16)
    assert np.all(wrong_d != source) and np.all(wrong_s != source)
    assert np.array_equal(shader_rgb_storage_model(d, 1.0 / 16), source)
    assert np.array_equal(shader_rgb_storage_model(s, 1.0 / 256), source)
    return {
        "schema": "native-colour-independent-scale-domain-v1",
        "scope": "Exhaustive half RGB arithmetic/storage model of the frozen clamp; not D3D12 execution",
        "gpu_executed": False,
        "native_alpha_payload_contract_proven": False,
        "source_snapshot_required_before_provider": True,
        "runtime": {"python": sys.version, "platform": platform.platform(), "numpy": np.__version__},
        "review_source_sha256": sha(Path(__file__)),
        "frozen_scale_shader_sha256": sha(SHADER),
        "cases": cases,
        "wrong_lobe_scale_mutant_rejected": True,
        "passed": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = check()
    serialized = json.dumps(report, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
