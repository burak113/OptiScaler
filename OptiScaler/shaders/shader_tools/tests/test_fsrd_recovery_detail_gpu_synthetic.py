"""Short real seven-shader numeric test; requires the parent's GPU token."""
from pathlib import Path
import argparse
import numpy as np
from fsrd_recovery_detail_gpu import Dispatcher, DetailState, stored
from test_fsrd_recovery_detail_safety import CPUState, rgba
from test_fsrd_recovery_detail_replay import original_gate, checked_output, save, sha256


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output = checked_output(args.output)
    gate = original_gate(Path("F:/FSRD/recovery_v2/scripts/eval"))
    paths = [Path(__file__), Path(__file__).with_name("fsrd_recovery_detail_gpu.py"),
        Path(__file__).with_name("fsrd_recovery_detail_reference.py"),
        Path(__file__).with_name("test_fsrd_recovery_detail_safety.py")]
    before = {str(p): sha256(p) for p in paths}
    dispatcher = Dispatcher(args.output/"jobs")
    checks, frames = [], []
    def check(name, passed, **evidence):
        checks.append(dict(name=name, passed=bool(passed), **evidence))
        print(("PASS " if passed else "FAIL ")+name+" "+str(evidence), flush=True)
        save(args.output/"progress.json", dict(checks=checks, frames=frames))
    try:
        h, w = 23, 137  # crosses a 128-thread prefix block and has partial groups
        y, x = np.indices((h, w))
        base = rgba(np.full((h, w, 3), .375, np.float32), .625)
        rr = [rgba(np.full((h, w, 3), .125, np.float32)) for _ in range(2)]
        guides = [rgba(np.full((h, w, 3), .75, np.float32), 1.),
                  rgba(np.full((h, w, 3), .625, np.float32), 1.)]
        depth = np.full((h, w), 10., np.float32)
        normal = rgba(np.broadcast_to([.5, .5, 1.], (h, w, 3)).astype(np.float32), 1.)
        motion = np.zeros((h, w, 4), np.float32); motion[..., 3] = 1.
        gpu, cpu = DetailState(dispatcher, w, h), CPUState(gate, w, h)
        for frame in range(24):
            signals = [v.copy() for v in rr]
            signals[0][..., :3] += (.05*np.sin(x/4)+.015*np.cos(y/3)+
                                    .0005*((frame % 2)*2-1)*np.cos((x+y)/2))[..., None]
            signals[1][..., :3] += (.02*np.cos((x+y)/9))[..., None]
            reset = frame == 12
            expected = cpu.step(signals, rr, guides, base, depth, normal, motion, reset=reset)
            actual = gpu.step(signals, rr, guides, base, depth, normal, motion, reset=reset)
            target = expected.astype(np.float16)
            up = abs(np.nextafter(target, np.float16(np.inf)).astype(np.float32)-expected)
            down = abs(np.nextafter(target, np.float16(-np.inf)).astype(np.float32)-expected)
            difference = abs(actual-expected)
            outside = int(np.count_nonzero(difference > 2*np.maximum(up, down)+2e-6))
            moments = {}
            for index, lobe in enumerate(("specular", "diffuse")):
                state = cpu.states[index]
                mean, variance, meta = gpu.history[lobe]
                errors = dict(mean=float(abs(mean[..., :3]-state.mean[0]).max()),
                    variance=float(abs(variance[..., :3]-state.variance[0]).max()),
                    mass=float(abs(mean[..., 3]-state.mass).max()),
                    q=float(abs(variance[..., 3]-state.q).max()),
                    age=float(abs(meta[..., 3]-state.age).max()))
                errors["passed"] = errors["mean"] <= 2e-5 and errors["variance"] <= 2e-5 and \
                    errors["mass"] <= 1e-5 and errors["q"] <= 1e-5 and errors["age"] <= 3e-4
                moments[lobe] = errors
            row = dict(frame=frame, reset=reset, maximum_stored_difference=float(difference.max()),
                outside_declared_two_ulp_plus_2e_minus6=outside, moments=moments,
                alpha_exact=bool(np.array_equal(actual[..., 3], base[..., 3])))
            row["passed"] = outside == 0 and row["alpha_exact"] and all(r["passed"] for r in moments.values())
            frames.append(row)
        check("24-frame stored color and all temporal moment stages match frozen CPU bounds",
              all(row["passed"] for row in frames), maximum=float(max(r["maximum_stored_difference"] for r in frames)),
              failed_frames=[r["frame"] for r in frames if not r["passed"]], logical=[w, h])
        # Reconstruct the CPU's unstored signed correction for the debug encoding.
        expected_correction = np.zeros((h, w, 3), np.float32)
        for state in cpu.states:
            noise = np.sqrt(np.maximum(state.variance*state.q[None, ..., None]/
                np.maximum(1-state.q[None, ..., None], 1e-6), 0))
            raw = state.correction(noise, np.ones((h, w), bool), 2., "soft", 8.)[0]
            value, _ = gate.neutral_correction(raw, np.isfinite(raw) & (abs(raw) > 0), base[..., :3])
            expected_correction += value
        negative = expected_correction < 0
        scale = min(1., float(np.min(base[..., :3][negative]/-expected_correction[negative]))) if negative.any() else 1.
        expected_correction *= max(scale, 0.)
        # Apply only: do not advance temporal state when comparing this encoding.
        debug = dispatcher.dispatch("Apply", dict(DstTexSize=gpu.constants, Debug=1, LobeMask=3),
            [base, gpu.last["spec"], gpu.last["diffuse"], gpu.last["dc"],
             gpu.last["lobe_scales"], gpu.last["sum_scale"]], gpu.groups, [gpu.size])[0]
        expected_debug = (.5+.5*expected_correction/np.maximum(abs(base[..., :3]), .01)).astype(np.float16).astype(np.float32)
        check("debug signed-correction encoding is independently readable",
              np.max(abs(debug[..., :3]-expected_debug)) <= .001 and np.array_equal(debug[..., 3], base[..., 3]),
              maximum=float(abs(debug[..., :3]-expected_debug).max()), tolerance=.001,
              alpha_exact=bool(np.array_equal(debug[..., 3], base[..., 3])))
        # Intentional nonfinite base representation must not enter DC/scale.
        # The general adapter rejects nonfinite outputs; preserve/read the failed
        # owned staging bytes explicitly for this negative expected-output test.
        nonfinite = base.copy(); nonfinite[:4, :, 0] = np.nan; nonfinite[4:8, :, 1] = np.inf
        try:
            actual = gpu.step(signals, rr, guides, nonfinite, depth, normal, motion)
        except AssertionError as error:
            if "Apply produced nonfinite output" not in str(error):
                raise
            job = dispatcher.output/f"{dispatcher.counter-1:05}_FSRDRecoveryDetailApply"
            actual = np.fromfile(job/"out0.bin", dtype="<f2").reshape(h, w, 4).astype(np.float32)
            save(args.output/"expected_nonfinite_adapter_rejection.json", dict(error=str(error),
                expected_nan_inf_representation=True, staging_preserved=str(job)))
        check("nonfinite HDR base channels are preserved and cannot contaminate finite channels",
              np.all(np.isnan(actual[:4, :, 0])) and np.all(np.isposinf(actual[4:8, :, 1])) and
              np.all(np.isfinite(actual[np.isfinite(nonfinite)])),
              finite_channels=int(np.isfinite(nonfinite).sum()))
        check("D3D12 debug layer stayed clean on every dispatch",
              all(float(row["validation_errors"]) == 0 and float(row["validation_warnings"]) == 0
                  for row in dispatcher.timings), dispatches=len(dispatcher.timings))
    finally:
        dispatcher.close()
    after = {str(p): sha256(p) for p in paths}
    check("CPU/GPU source identities remained fixed", before == after)
    result = dict(passed=all(c["passed"] for c in checks), checks=checks, frames=frames,
        source_start=before, source_finish=after, gpu_executed=True,
        production_enabled=False, scope="original unsafe global-DC seven-shader numeric prototype",
        limitations="strict 12-record GPU M3 not run; known boundary/dropout failures are reported separately")
    save(args.output/"results.json", result)
    return int(not result["passed"])


if __name__ == "__main__":
    raise SystemExit(main())
