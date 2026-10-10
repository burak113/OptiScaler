"""Independent statistical checks for the Floor-free paired detail estimator."""
from pathlib import Path
import argparse
import json
import numpy as np
from fsrd_recovery_detail_reference import PairedBandMoments, identity_taps


def run(output):
    checks = []
    def check(name, passed, **evidence):
        checks.append(dict(name=name, passed=bool(passed), **evidence))
        print(("PASS " if passed else "FAIL ")+name, flush=True)

    shape = (32, 32)
    taps = identity_taps(*shape)
    reuse = np.ones(shape, bool)
    rng = np.random.default_rng(20261010)
    for response in (.03, .1):
        state = PairedBandMoments(shape, 1, response)
        samples = []
        weights = []
        for frame in range(32):
            value = rng.normal(.2, .05, (1, *shape, 3)).astype(np.float32)
            samples.append(value)
            mean, noise = state.update(value, taps, reuse if frame else np.zeros(shape, bool))
            weights = [(1-response)*weight for weight in weights]+[response]
            expected = np.sum(np.asarray(samples)*np.asarray(weights)[:, None, None, None, None], axis=0)/sum(weights)
            if frame in (0, 7, 31):
                error = float(np.max(abs(mean-expected)))
                expected_q = sum(weight**2 for weight in weights)/sum(weights)**2
                check(f"normalized causal mean response={response} frame={frame}", error < 3e-7, max_error=error)
                check(f"effective count response={response} frame={frame}",
                      np.max(abs(state.q-expected_q)) < 3e-7,
                      measured=float(state.effective_count.mean()), expected=1/expected_q)
        empirical = float(np.mean((mean-.2)**2))
        predicted = float(np.mean(noise**2))
        check(f"independent noise calibration response={response}", .85 < predicted/empirical < 1.15,
              empirical_mse=empirical, predicted_mse=predicted, ratio=predicted/empirical)

    state = PairedBandMoments((1, 1), 1)
    one = identity_taps(1, 1)
    yes = np.ones((1, 1), bool)
    no = np.zeros((1, 1), bool)
    for frame in range(16):
        observed = np.full((1, 1, 1, 3), -.15, np.float32)
        mean, noise = state.update(observed, one, yes if frame else no)
        correction = state.correction(noise, yes)
        if frame < 7:
            check(f"no raw fallback at startup {frame}", np.array_equal(correction, np.zeros_like(correction)))
    check("signed dark structure survives", np.all(correction < -.149))
    bright = np.full((1, 1, 1, 3), 100., np.float32)
    mean, noise = state.update(bright, one, no)
    check("rare bright observation remains in unbiased mean", np.array_equal(mean, bright))
    check("reset bright sample cannot display", np.array_equal(state.correction(noise, no), np.zeros_like(mean)))
    check("reset population really restarts", float(state.effective_count[0, 0]) == 1 and float(state.age[0, 0]) == 1)

    # A deterministic reprojected ramp has no between-tap sample variance.
    ramp = np.repeat(np.arange(8, dtype=np.float32)[None, :, None], 3, axis=2)[None]
    state = PairedBandMoments((1, 8), 1)
    state.update(ramp, identity_taps(1, 8), np.zeros((1, 8), bool))
    y, x = np.indices((1, 8))
    half_taps = [(y, x, np.full((1, 8), .5, np.float32)),
                 (y, np.minimum(x+1, 7), np.full((1, 8), .5, np.float32))]
    expected = (ramp+np.roll(ramp, -1, axis=2))*.5
    expected[..., -1, :] = ramp[..., -1, :]
    state.update(expected, half_taps, np.ones((1, 8), bool))
    check("bilinear deterministic ramp stays noiseless", np.max(state.variance) < 1e-12)
    expected_count = (2-state.response)**2 / (1+(1-state.response)**2)
    check("bilinear gather cannot invent independent observations",
          np.allclose(state.effective_count, expected_count, atol=3e-6) and
          np.all(state.effective_count <= 2),
          measured=float(state.effective_count.mean()), expected=expected_count)
    failures = sum(not item["passed"] for item in checks)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(dict(checks=checks, failures=failures), indent=2), encoding="utf-8")
    return bool(failures)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    raise SystemExit(run(parser.parse_args().output))
