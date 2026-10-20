"""Local D3D12 mechanical canaries; does not establish game image quality.

Run while holding the shared GPU lock. Requires NumPy, MSVC, Windows SDK DXC.
--output must be scratch storage; no game deployment is performed.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import struct
import subprocess
import sys
from types import SimpleNamespace

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
TOOLS = REPO / "OptiScaler/shaders/shader_tools"
CANDIDATE = HERE.parent / "candidates/03-native-colour"
sys.path[:0] = [str(TOOLS), str(TOOLS / "tests"), str(CANDIDATE)]
from fsrd_toolchain import compile_cpp, dxc
from fsrd_gpu_chain import ChainJob
from native_colour import NativeColourModel, Config


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    runner = out / "runner/fsrd_gpu_runner.exe"
    runner.parent.mkdir(exist_ok=True)
    compile_cpp(TOOLS / "tests/fsrd_gpu_runner.cpp", runner, ("d3d12.lib", "dxgi.lib"))
    compiler = dxc()
    shader = CANDIDATE / "shaders/NativeColourPacked.hlsl"
    cso = out / "NativeColourPacked.cso"
    command = [str(compiler), "-T", "cs_6_2", "-E", "CSMain", "-HV", "2021",
               "-Ges", "-Gis", "-O3", str(shader), "-Fo", str(cso)]
    compiled = subprocess.run(command, capture_output=True, text=True)
    (out / "compile.txt").write_text(compiled.stdout + compiled.stderr, encoding="utf-8")
    if compiled.returncode:
        raise RuntimeError(compiled.stderr)
    rm = SimpleNamespace(run_runner=lambda p: subprocess.run(
        [str(runner), str(p)], capture_output=True, text=True, timeout=60))
    # Odd render extent inside a larger allocation; unequal padded copy pitches.
    W, H, AW, AH = 13, 9, 17, 12
    rng = np.random.default_rng(20261020)
    raw = np.ones((AH, AW, 4), np.float16)
    raw[..., :3] = rng.uniform(.1, .7, (AH, AW, 1)) * np.array([1.05, 1., .96])
    source = raw.copy()
    source[..., :3] *= np.array([.9, 1., 1.12], np.float16)
    # Preserve arbitrary half NaN payloads and signed zero in alpha.
    raw.view(np.uint16)[..., 3] = rng.choice(np.array([0x7e11, 0xfc01, 0x8000, 0, 0x3c00], np.uint16), (AH, AW))
    selected = raw.copy()
    selected[1, 2, 0] *= np.float16(.8)
    selected.view(np.uint16)[2, 3, 3] ^= np.uint16(1)
    depth = np.full((AH, AW), 10, np.float32)
    authority = np.ones((AH, AW), np.uint32)
    authority[3, 4] = 0
    # Same exact R10 UNORM decoding is supplied to the CPU oracle.
    oct_value = np.float32(512 / 1023)
    uv = np.float32(2) * (np.array([oct_value, oct_value]) - np.float32(.5))
    normal = np.array([uv[0], uv[1], 1 - np.abs(uv).sum()], np.float32)
    normal /= np.linalg.norm(normal)
    normals = np.broadcast_to(normal, (AH, AW, 3)).copy()
    roughness = np.full((AH, AW), np.float32(600 / 1023))
    packed_normal = np.full((AH, AW), np.uint32(512 | (512 << 10) | (600 << 20)))
    active = np.zeros((AH, AW), bool)
    active[:H, :W] = True

    def buffer(rgba, pitch, offset):
        value = np.full(offset + AH * pitch + 512, 0xCD, np.uint8)
        for y in range(AH):
            value[offset + y * pitch:offset + y * pitch + AW * 8] = rgba[y].view(np.uint8).reshape(-1)
        return value.view(np.uint32)

    cases = []
    for name, enabled, rep, strength, invalid in (
            ("off", False, "log", 1., False), ("zero_strength", True, "log", 0., False),
            ("log", True, "log", 1., False), ("linear", True, "linear", 1., False),
            ("invalid_geometry", True, "log", 1., True)):
        cfg = Config(enabled=enabled, representation=rep, strength=strength)
        z = depth.copy()
        if invalid:
            z[:H, :W] = np.resize(np.array([0, np.nan, np.inf], np.float32), (H, W))
        expected, diag = NativeColourModel(cfg).frame(source, raw, selected, z, normals,
                roughness=roughness, authority=authority.astype(bool), active_extent=(W, H))
        j = ChainJob(out / name, rm)
        pitches, offsets = (256, 512, 768, 1024), (512, 1024, 1536, 2048)
        for i, (label, value) in enumerate((("source", source), ("raw", raw), ("selected", selected))):
            j.raw(label, buffer(value, pitches[i], offsets[i]))
        initial = buffer(selected, pitches[3], offsets[3])
        j.raw("output", initial, writable=True, readback=True)
        j.texture("depth", z, format=41)
        j.texture("normal", packed_normal, format=24)
        j.texture("authority", authority, format=42)
        j.texture("diagnostic", np.zeros((AH, AW, 4), np.float32), format=2, writable=True, readback=True)
        constants = struct.pack("16I8f", W, H, AW, AH, *pitches, *offsets,
            int(enabled), int(rep == "linear"), cfg.radius, 0,
            cfg.spatial_sigma, cfg.depth_tolerance, cfg.normal_cosine, cfg.roughness_tolerance,
            cfg.guide_chroma_radius, cfg.max_log_delta, cfg.support_prior, cfg.strength)
        j.compute(name, cso, constants, ["source", "raw", "selected", "depth", "normal", "authority"],
                  ["output", "diagnostic"], ((W + 7) // 8, (H + 7) // 8, 1))
        outputs, meta = j.run(keep_staging=True)
        returned = outputs["output"].view(np.uint8)
        actual_words = np.stack([returned[offsets[3] + y * pitches[3]:offsets[3] + y * pitches[3] + AW * 8]
                                 for y in range(AH)]).copy().view(np.uint16).reshape(AH, AW, 4)
        initial_bytes = initial.view(np.uint8)
        canary = np.ones(returned.size, bool)
        for y in range(H):
            canary[offsets[3] + y * pitches[3]:offsets[3] + y * pitches[3] + W * 8] = False
        protected = ~diag["eligible"]
        difference = np.abs(actual_words[..., :3].astype(np.int32) - expected.view(np.uint16)[..., :3].astype(np.int32))
        changed = np.any(actual_words != selected.view(np.uint16), axis=-1)
        checks = dict(alpha_exact=bool(np.array_equal(actual_words[..., 3], selected.view(np.uint16)[..., 3])),
            protected_exact=bool(np.array_equal(actual_words[protected], selected.view(np.uint16)[protected])),
            padding_exact=bool(np.array_equal(returned[canary], initial_bytes[canary])),
            cpu_rgb_within_one_half_ulp=bool(difference.max() <= 1),
            eligibility_exact=bool(np.array_equal(outputs["diagnostic"][..., 0].astype(bool), diag["eligible"])),
            finite_rgb=bool(np.isfinite(actual_words.view(np.float16)[..., :3]).all()),
            debug_clean=meta["counters"].get("debug_layer") == 1 and
                not any(meta["counters"].get(k, -1) != 0 for k in ("validation_errors", "validation_warnings")))
        if name in ("off", "zero_strength", "invalid_geometry"):
            checks["full_word_identity"] = not bool(changed.any())
        else:
            checks["non_vacuous_change"] = bool(changed[active & ~protected].any())
        row = dict(name=name, checks=checks, max_half_ulp=int(difference.max()),
                   changed_pixels=int(changed.sum()), adapter=meta["adapter"], counters=meta["counters"])
        cases.append(row)
        print(json.dumps(row), flush=True)
    report = dict(schema="astra-local-colour-gpu-v1", shader_sha256=sha(shader),
                  dxil_sha256=sha(cso), compiler_sha256=sha(compiler), runner_sha256=sha(runner),
                  test_sha256=sha(__file__), cases=cases,
                  passed=all(all(c["checks"].values()) for c in cases),
                  quality_accepted=False, scope="Synthetic D3D12 transport/packing checks; no native graph, real RR replay or game visual acceptance")
    (out / "gpu_result.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
