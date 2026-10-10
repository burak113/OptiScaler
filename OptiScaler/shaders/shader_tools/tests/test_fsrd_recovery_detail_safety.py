"""Independent boundary/black/noise/dropout checks for the paired detail profile.

CPU mode is a read-only reference test. GPU mode runs the isolated real shader
pipeline and requires the serialized GPU slot. A known boundary/dropout failure
is a real quality failure, even if M3 or aggregate metrics pass.
"""
from pathlib import Path
import argparse
import json
import os
import numpy as np
from fsrd_recovery_detail_reference import PairedBandMoments, identity_taps
from fsrd_recovery_detail_gpu import Dispatcher, DetailState, stored
from test_fsrd_recovery_detail_replay import original_gate, checked_output, save, sha256


def rgba(rgb, alpha=.625):
    rgb = np.asarray(rgb, np.float32)
    return np.concatenate((rgb, np.full((*rgb.shape[:-1], 1), alpha, np.float32)), -1)


class CPUState:
    def __init__(self, gate, width, height):
        self.gate, self.width, self.height = gate, width, height
        self.shape = height, width
        self.taps = identity_taps(height, width)
        self.states = [PairedBandMoments(self.shape, 1, .1) for _ in range(2)]
        self.valid = False
        self.old_depth = np.zeros(self.shape, np.float32)
        self.old_normal = np.zeros((*self.shape, 3), np.float32)

    def step(self, signals, denoised, albedo, base, depth, normal, motion,
             strengths=(1., 1.), reset=False, **unused):
        h, w = self.shape
        base = np.asarray(base[:h, :w], np.float16).astype(np.float32)
        depth = np.asarray(depth[:h, :w], np.float32)
        normal = self.gate.decode_normals(stored(normal[:h, :w], 24)).astype(np.float32)
        reuse = (self.valid and not reset) & np.isfinite(depth) & (abs(depth) > 1e-5) & \
            (abs(depth-self.old_depth) <= .03*np.maximum(abs(depth), .001)) & \
            ((normal*self.old_normal).sum(-1) > .95)
        correction = np.zeros((*self.shape, 3), np.float32)
        for index in range(2):
            signal = np.asarray(signals[index][:h, :w, :3], np.float16).astype(np.float32)
            rr = np.asarray(denoised[index][:h, :w, :3], np.float16).astype(np.float32)
            guide = np.asarray(albedo[index][:h, :w, :3], np.float32)
            if albedo[index].dtype == np.uint8:
                guide /= 255.
            else:
                guide = np.rint(np.clip(guide, 0, 1)*255).astype(np.float32)/255.
            observed = self.gate.band((signal-rr)*guide, 3, 40)[None]
            state = self.states[index]
            _, noise = state.update(observed, self.taps, reuse)
            raw = strengths[index]*state.correction(noise, reuse, 2., "soft", 8.)[0]
            value, _ = self.gate.neutral_correction(raw, np.isfinite(raw) & (abs(raw) > 0), base[..., :3])
            correction += value
        negative = correction < 0
        scale = min(1., float(np.min(base[..., :3][negative]/-correction[negative]))) if negative.any() else 1.
        correction *= max(0., scale)
        output = base.copy()
        output[..., :3] += correction
        self.valid = True
        self.old_depth, self.old_normal = depth.copy(), normal.copy()
        return output.astype(np.float16).astype(np.float32)


def run(args):
    args.output = checked_output(args.output)
    gate = original_gate(args.evidence_scripts)
    dispatcher = None
    sources = {str(path): sha256(path) for path in
        (Path(__file__), Path(__file__).with_name("fsrd_recovery_detail_reference.py"),
         Path(__file__).with_name("fsrd_recovery_detail_gpu.py"))}
    if args.mode == "gpu":
        os.environ.setdefault("FSRD_GPU_TEST_OUTPUT", str(args.output/"shared_runner_initial"))
        dispatcher = Dispatcher(args.output/"jobs")
    checks = []
    def check(name, passed, **evidence):
        checks.append(dict(name=name, passed=bool(passed), **evidence))
        print(("PASS " if passed else "FAIL ")+name+" "+str(evidence), flush=True)
        save(args.output/"progress.json", checks)

    h, w = 48, 96
    def state(width=w, height=h):
        return DetailState(dispatcher, width, height) if dispatcher else CPUState(gate, width, height)
    def fixture():
        base = rgba(np.full((h, w, 3), .25, np.float32))
        lobes = [rgba(np.full((h, w, 3), .125, np.float32)) for _ in range(2)]
        guide = rgba(np.ones((h, w, 3), np.float32), 1.)
        depth = np.full((h, w), 10., np.float32)
        normal = rgba(np.broadcast_to(np.array([.5, .5, 1.], np.float32), (h, w, 3)), 1.)
        motion = np.zeros((h, w, 4), np.float32); motion[..., 3] = 1.
        return base, lobes, [guide.copy(), guide.copy()], depth, normal, motion
    def difference(output, base):
        return output[..., :3]-base[..., :3].astype(np.float16).astype(np.float32)
    try:
        base, lobes, guides, depth, normal, motion = fixture()
        engine = state()
        for _ in range(16):
            out = engine.step(lobes, lobes, guides, base, depth, normal, motion)
        check("RR identity remains bit exact after maturity", np.array_equal(out, base))

        y, x = np.indices((h, w))
        pattern = (np.sin(2*np.pi*x/18)*.0625).astype(np.float32)
        signals = [lobes[0].copy(), lobes[1].copy()]
        signals[0][..., :3] += pattern[..., None]
        engine = state()
        for frame in range(20):
            out = engine.step(signals, lobes, guides, base, depth, normal, motion, strengths=(1., 0.))
            if frame == 0:
                check("restart has no single-frame raw fallback", np.array_equal(out, base))
        signed = difference(out, base)
        check("supported signed detail includes dark and bright structure",
              signed.min() < -.001 and signed.max() > .001,
              minimum=float(signed.min()), maximum=float(signed.max()))
        check("stored output alpha is unchanged", np.array_equal(out[..., 3], base[..., 3]))
        saved = out.copy()
        out = engine.step(signals, lobes, guides, base, depth, normal, motion, reset=True)
        check("explicit reset immediately abstains", np.array_equal(out, base))

        negative = base.copy(); negative[..., 0] = -.125; negative[..., 1] = 2.
        out = engine.step(signals, lobes, guides, negative, depth, normal, motion, strengths=(0., 0.))
        check("two strength-zero controls preserve negative HDR and alpha exactly", np.array_equal(out, negative))
        engine = state()
        for frame in range(32):
            noise = lobes[0].copy()
            noise[..., :3] += ((1 if frame % 2 else -1) * .0625 * ((x+y)%2*2-1))[..., None]
            out = engine.step([noise, lobes[1]], lobes, guides, base, depth, normal, motion)
        check("zero-mean alternating noise remains RR-only", np.array_equal(out, base),
              maximum=float(abs(difference(out, base)).max()))

        black = base.copy(); black[:, w//2:, :3] = 0.
        engine = state()
        for _ in range(20):
            out = engine.step(signals, lobes, guides, black, depth, normal, motion)
        check("black silhouette cannot receive geometry-neighbor radiance", np.all(out[:, w//2:, :3] == 0))
        check("uniformly attenuated stored output is nonnegative", np.all(out[..., :3] >= 0),
              minimum=float(out[..., :3].min()))

        # Same-surface temporal taps do not fix a spatial box spanning a boundary.
        boundary_signal = [lobes[0].copy(), lobes[1].copy()]
        boundary_signal[0][:, :w//2, :3] += .25
        edge_depth = depth.copy(); edge_depth[:, w//2:] = 100.
        edge_normal = normal.copy(); edge_normal[:, w//2:, 0] = 1.
        engine = state()
        for _ in range(20):
            out = engine.step(boundary_signal, lobes, guides, base, edge_depth, edge_normal, motion)
        region_error = abs(difference(out, base)[:, w//2:])
        check("disconnected RR-clean surface has no new detail", np.all(region_error == 0),
              maximum=float(region_error.max()), mean=float(region_error.mean()),
              reason="Quality gate independent of M3; global box/DC boundary mixing is not accepted")

        engine = state()
        for _ in range(20):
            out = engine.step(signals, lobes, guides, base, depth, normal, motion)
        dropped = [np.zeros_like(guides[0]), np.zeros_like(guides[1])]
        out = engine.step(signals, lobes, dropped, base, depth, normal, motion)
        dropout_error = abs(difference(out, base))
        check("current zero-material guide immediately abstains", np.all(dropout_error == 0),
              maximum=float(dropout_error.max()),
              reason="Quality gate independent of M3; historical signed mean cannot bypass a current material veto")

        invalid_depth = np.full_like(depth, np.nan)
        out = engine.step(signals, lobes, guides, base, invalid_depth, normal, motion)
        check("nonfinite current depth immediately abstains", np.array_equal(out, base))
        if dispatcher:
            for lobe in engine.history:
                for image in engine.history[lobe]:
                    image[...] = np.nan
            out = engine.step(signals, lobes, guides, base, depth, normal, motion)
            check("rejected nonfinite history cannot survive zero tap weight", np.array_equal(out, base) and
                  all(np.all(np.isfinite(image)) for history in engine.history.values() for image in history))

        # Logical 17x13 subrect in larger allocations; poison unaddressable texels.
        lw, lh = 17, 13
        base_small, signals_small, rr_small, guide_small = [], [], [], []
        for images, target in (([base], base_small), (signals, signals_small), (lobes, rr_small), (guides, guide_small)):
            target.extend(image[:lh, :lw].copy() for image in images)
        small = state(lw, lh); padded = state(lw, lh)
        def poison(image, value):
            array = np.full((lh+6, lw+7, *image.shape[2:]), value, image.dtype)
            array[:lh, :lw] = image
            return array
        for _ in range(12):
            cropped = small.step(signals_small, rr_small, guide_small, base_small[0], depth[:lh, :lw],
                                 normal[:lh, :lw], motion[:lh, :lw])
            out = padded.step([poison(v, 100.) for v in signals_small], [poison(v, 10.) for v in rr_small],
                [poison(v, 0.) for v in guide_small], poison(base_small[0], 50.),
                poison(depth[:lh, :lw], 100.), poison(normal[:lh, :lw], 0.), poison(motion[:lh, :lw], 1.))
        check("partial groups use logical extent and ignore allocation padding", np.array_equal(out, cropped),
              maximum=float(abs(out-cropped).max()), logical=[lw, lh], allocated=[lw+7, lh+6])
    finally:
        if dispatcher:
            dispatcher.close()
    finish = {path: sha256(path) for path in sources}
    check("source identities remained fixed throughout run", sources == finish)
    result = dict(mode=args.mode, passed=all(row["passed"] for row in checks), checks=checks,
        failures=sum(not row["passed"] for row in checks), source_start=sources, source_finish=finish,
        gpu_executed=bool(dispatcher), reference_scope="paired broad .1/k2/1,1 prototype; global DC",
        production_enabled=False,
        pending="availability/Skip-alpha/current-source routing and runtime OFF allocation remain host gates")
    save(args.output/"results.json", result)
    return int(not result["passed"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("cpu", "gpu"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--evidence-scripts", type=Path, default=Path("F:/FSRD/recovery_v2/scripts/eval"))
    raise SystemExit(run(parser.parse_args()))
