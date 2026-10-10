"""Check the q*age lower bound without changing the frozen estimator.

Mathematical proof for normalized nonnegative correlated gather weights:
1. Restart gives q=A=1.
2. q_i>=1/A_i implies gathered q>=sum(w_i/A_i)>=1/sum(w_i*A_i)
   by Jensen, with A_g=sum(w_i*A_i).
3. q'=(1-a)^2*q_g+a^2 >= (1-a)^2/A_g+a^2 >=1/(A_g+1)
   by Cauchy (minimum at a=1/(A_g+1)). A'=A_g+1.
Thus n_eff=1/q<=age. With minimum_count>=8 the age>=8 test is
mathematically redundant. FP32 shader equivalence is still a separate gate;
unnormalized/negative weights, nonfinite histories or count<8 void this proof.
"""
from pathlib import Path
import argparse
import numpy as np
from fsrd_recovery_detail_reference import PairedBandMoments
from test_fsrd_recovery_detail_replay import checked_output, save, sha256


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = checked_output(args.output)
    sources = [Path(__file__), Path(__file__).with_name("fsrd_recovery_detail_reference.py")]
    before = {str(p): sha256(p) for p in sources}
    rng = np.random.default_rng(193871)
    checks = []
    def check(name, passed, **evidence):
        checks.append(dict(name=name, passed=bool(passed), **evidence))
        print(("PASS " if passed else "FAIL ")+name+" "+str(evidence), flush=True)
    weights = rng.uniform(size=(200000, 4)); weights /= weights.sum(1, keepdims=True)
    age = rng.uniform(1, 256, size=weights.shape)
    q = 1/age+rng.uniform(size=age.shape)*.1
    gather_age = (weights*age).sum(1); gather_q = (weights*q).sum(1)
    a = rng.uniform(size=gather_q.shape)
    next_q = (1-a)**2*gather_q+a*a
    bound = next_q*(gather_age+1)
    check("normalized mixed-population Jensen and update Cauchy bound",
          np.all(bound >= 1-2e-14), cases=bound.size, minimum_q_times_age=float(bound.min()))
    optimum = 1/(gather_age+1)
    equality = ((1-optimum)**2/gather_age+optimum**2)*(gather_age+1)
    check("sharp Cauchy boundary has the claimed equality", np.max(abs(equality-1)) <= 2e-14,
          maximum=float(np.max(abs(equality-1))))
    h, w = 16, 24
    total_cases, mismatch, minimum = 0, 0, 10.
    per_response = []
    for response in (.03, .1, .125, .5, 1.):
        state = PairedBandMoments((h, w), 1, response)
        local_mismatch = 0; local_minimum = 10.
        for frame in range(512):
            weight = rng.uniform(size=(4, h, w)).astype(np.float32)
            weight /= weight.sum(0)
            taps = [(rng.integers(h, size=(h, w)), rng.integers(w, size=(h, w)), weight[i])
                    for i in range(4)]
            reuse = rng.uniform(size=(h, w)) >= .025
            if frame == 0 or frame % 101 == 0:
                reuse[:] = False
            observations = rng.normal(size=(1, h, w, 3)).astype(np.float32)*.01
            state.update(observations, taps, reuse)
            supported = state.effective_count >= 8
            failures = supported & (state.age < 8)
            local_mismatch += int(failures.sum())
            local_minimum = min(local_minimum, float((state.q*state.age).min()))
            total_cases += h*w
        mismatch += local_mismatch; minimum = min(minimum, local_minimum)
        per_response.append(dict(response=response, gate_mismatches=local_mismatch,
                                 minimum_q_times_age=local_minimum))
    check("real FP32 moment trajectories have no count>=8 with age<8",
          mismatch == 0, cases=total_cases, mismatches=mismatch, minimum_q_times_age=minimum,
          per_response=per_response)
    # Positive mass/finite-history guards are part of the premise; a shader must
    # establish these before dividing or authorizing any supported correction.
    after = {str(p): sha256(p) for p in sources}
    check("original estimator remained unchanged", before == after)
    result = dict(passed=all(c["passed"] for c in checks), checks=checks,
        source_start=before, source_finish=after, gpu_executed=False,
        mathematical_scope="normalized nonnegative gather, correlated q update, finite age>=1, minimum_count>=8",
        production_age_removal_enabled=False,
        pending="exact real GPU/replay equivalence and bounded FP32 threshold rounding; proof alone does not enable removal")
    save(output/"results.json", result)
    return int(not result["passed"])


if __name__ == "__main__":
    raise SystemExit(main())
