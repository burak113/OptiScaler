"""Independent frozen-seed identifiability and lighting interventions.

These tests demonstrate what a guide-only observer cannot identify. They are
not candidate tuning, captured causal evidence, or AMD RR output.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
from foliage_guides import GuideFrame, observe_guides, pack_normal_roughness
from synthetic_scene import SceneConfig, generate_scene
from proxy_metrics import metrics, run_proxy


def digest(arrays):
    h = hashlib.sha256()
    for array in arrays:
        a = np.ascontiguousarray(array)
        h.update(a.dtype.str.encode())
        h.update(str(a.shape).encode())
        h.update(a.tobytes())
    return h.hexdigest()


def observation_digest(frames):
    arrays = []
    for i, frame in enumerate(frames):
        output = observe_guides(frame, frames[i-1] if i else None, enabled=True)
        arrays.extend((output.angular_dispersion, output.relative_depth_span,
                       output.temporal_innovation, output.temporal_supported,
                       output.flags, output.experimental_history_multiplier))
    return digest(arrays)


def hidden_mixture_probe():
    shape = (8, 12)
    normals = np.broadcast_to(np.array([0, 0, 1], np.float32), shape + (3,))
    words = pack_normal_roughness(normals, .4, 0)
    depth = np.full(shape, 12, np.float32)
    motion = np.zeros(shape + (4,), np.float16)
    frames = [GuideFrame(words.copy(), depth.copy(), motion.copy(), i,
                         (0, 0), (12, 8), True) for i in (50, 51)]
    # Two analytic worlds share every observable and all metadata. World A is a
    # single stationary surface; B retains the same dominant foreground guide
    # while hidden coverage changes. A single guide has no minority-layer MV.
    front = np.array([.4, .4, .4], np.float32)
    back = np.array([.03, .22, .8], np.float32)
    a = np.broadcast_to(front, (2,) + shape + (3,)).copy()
    fractions = np.array([.6, .8], np.float32)
    b = np.broadcast_to(fractions[:, None, None, None] * front +
                        (1 - fractions[:, None, None, None]) * back,
                        a.shape).copy()
    result = observe_guides(frames[1], frames[0], enabled=True)
    sig_a = observation_digest(frames)
    sig_b = observation_digest([replace(f, packed_normal_roughness=f.packed_normal_roughness.copy()) for f in frames])
    assert sig_a == sig_b
    assert np.all(result.experimental_history_multiplier[result.temporal_supported] > .99999)
    assert np.max(np.abs(np.diff(a, axis=0))) == 0
    assert np.max(np.abs(np.diff(b, axis=0))) > .07
    return {
        "scope": "analytic identical-observation collision, not a captured scene",
        "observation_digest_both_worlds": sig_a,
        "all_observations_equal": True,
        "comparable_pixels": int(result.temporal_supported.sum()),
        "min_multiplier_on_comparable": float(result.experimental_history_multiplier[result.temporal_supported].min()),
        "world_A_max_rgb_change": float(np.max(np.abs(np.diff(a, axis=0)))),
        "world_B_max_rgb_change": float(np.max(np.abs(np.diff(b, axis=0)))),
        "front_coverage_world_B": fractions.tolist(),
        "conclusion": "Comparable dominant guides cannot certify composite temporal history or infer minority coverage/motion",
    }


def lighting_probe():
    config = SceneConfig(name="reviewer_fixed_coverage", split="independent_review", seed=924619,
                         width=20, height=16, frames=10, camera_vx=0, camera_vy=0,
                         object_vx=0, object_vy=0, jitter_amplitude=0, light_step=1)
    independent = generate_scene(config)
    correlated = generate_scene(replace(config, name="reviewer_correlated", noise_rho=.95))
    moderate = generate_scene(replace(config, name="reviewer_light_step", light_step=1.1))
    signature = observation_digest(independent.frames)
    assert signature == observation_digest(correlated.frames) == observation_digest(moderate.frames)
    guide_bytes = lambda scene: digest([a for f in scene.frames for a in (f.packed_normal_roughness, f.depth, f.motion)])
    assert guide_bytes(independent) == guide_bytes(correlated) == guide_bytes(moderate)
    assert not np.array_equal(independent.observed, correlated.observed)
    assert not np.array_equal(independent.truth, moderate.truth)
    values = {name: metrics(scene, run_proxy(scene, "raw_half_inputs")) for name, scene in
              (("independent", independent), ("correlated_rho_095", correlated), ("moderate_light_step_11", moderate))}
    return {
        "scope": "independent reviewer synthetic intervention, no output filter or native execution",
        "seed": 924619,
        "coverage_fixed_exact": bool(np.array_equal(independent.coverage[1:], independent.coverage[:-1])),
        "guide_bytes_sha256": guide_bytes(independent),
        "observation_digest_all_three": signature,
        "guide_observations_identical": True,
        "raw_metrics": values,
        "conclusion": "Noise temporal correlation and true-light response change without any observable guide change",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=HERE / "independent_probes.json")
    args = parser.parse_args()
    start = time.perf_counter()
    result = {"executor": "/root/skeptic", "gpu_executed": False,
              "hidden_mixture": hidden_mixture_probe(), "lighting": lighting_probe()}
    result["elapsed_seconds"] = time.perf_counter() - start
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"hidden_mixture_observations_equal": result["hidden_mixture"]["all_observations_equal"],
                      "lighting_observations_equal": result["lighting"]["guide_observations_identical"],
                      "elapsed_seconds": result["elapsed_seconds"]}, indent=2))


if __name__ == "__main__":
    main()
