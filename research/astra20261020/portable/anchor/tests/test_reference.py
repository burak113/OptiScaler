"""Portable fresh CPU tests. No GPU, DLL, game, local drive or RR Lab needed."""
import hashlib
import json
from pathlib import Path
import sys
import unittest
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import anchor_reference as A


class ReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((ROOT / "fixtures/manifest.json").read_text())
        cls.data = {}
        for group in cls.manifest["groups"]:
            for capture in group["captures"]:
                path = ROOT / capture["file"]
                cls.data[(group["id"], capture["capture"])] = np.load(path, allow_pickle=False)

    def test_payload_hashes(self):
        for relative, expected in self.manifest["payload_sha256"].items():
            with self.subTest(file=relative):
                self.assertEqual(hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(), expected)
        for relative, source in self.manifest["source_files"].items():
            if relative.startswith("source/"):
                with self.subTest(source=relative):
                    self.assertEqual(hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(), source["sha256"])

    def test_actual_combined_shader_parity_all_133_frames(self):
        n, max_error = 0, 0.
        for (group, cid), data in self.data.items():
            if group != "combined": continue
            for j, frame in enumerate(data["frames"]):
                with self.subTest(capture=cid, frame=int(frame)):
                    s, r = data["stats"][j], data["recalled"][j]
                    mask = A.fixed_measurement_mask(s, r)
                    np.testing.assert_array_equal(mask, data["fixed_mask"][j])
                    atom = data["counters"][j]
                    self.assertEqual(int(mask.sum()), int(atom[2]))
                    self.assertEqual(float(data["frame_ratio"][j]), int(atom[1]) / int(atom[0]))
                    predicted = A.predict(s, r, int(data["k"][j]), float(data["frame_ratio"][j]))
                    error = float(np.max(np.abs(predicted - data["gain"][j].astype(np.float32))))
                    max_error = max(max_error, error)
                    self.assertLessEqual(error, .0005)
                    n += 1
        self.assertEqual(n, 133)
        print("combined actual-CSO parity:", n, "frames; max_abs", max_error)

    def test_actual_native_policy_shader_parity_7_frames(self):
        n, max_error = 0, 0.
        for (group, cid), data in self.data.items():
            if group != "native_policy": continue
            for j, frame in enumerate(data["frames"]):
                with self.subTest(capture=cid, frame=int(frame)):
                    s, r = data["stats"][j], data["recalled"][j]
                    np.testing.assert_array_equal(A.fixed_measurement_mask(s, r), data["fixed_mask"][j])
                    ratio, lo, hi, count = A.frame_ratio_from_stored_fields(s, r)
                    np.testing.assert_allclose([ratio, lo, hi], data["frame_ratio_bounds"][j], rtol=0, atol=0)
                    threshold = float(A.reject_threshold(int(data["k"][j])))
                    self.assertEqual(1-lo > threshold, 1-hi > threshold,
                                     "pre-store uncertainty may not change this fixture's guard decision")
                    self.assertEqual(count, int(data["valid_count"][j]))
                    predicted = A.predict(s, r, int(data["k"][j]), ratio, policy="native")
                    error = float(np.max(np.abs(predicted-data["gain"][j].astype(np.float32))))
                    max_error = max(max_error, error)
                    self.assertLessEqual(error, .0005)
                    n += 1
        self.assertEqual(n, 7)
        print("native-policy actual-CSO parity:", n, "frames; max_abs", max_error)

    def test_identity_and_no_input_mutation(self):
        for (group, cid), data in self.data.items():
            if group != "native_policy": continue
            s = data["stats"][0].astype(np.float32)
            r = data["recalled"][0].astype(np.float32)
            before_s, before_r = s.copy(), r.copy()
            A.predict(s, r, 0, 1, policy="native")
            np.testing.assert_array_equal(s, before_s)
            np.testing.assert_array_equal(r, before_r)
            r[..., 0] = s[..., 0]
            for policy in ("combined", "native"):
                np.testing.assert_array_equal(A.predict(s, r, 0, 1, policy=policy), 1)

    def test_antithetic_null_against_frozen_prior_cpu_result(self):
        rng = np.random.default_rng(20261020)
        for case in self.manifest["null_cases"]:
            data = self.data[("native_policy", case["capture"])]
            j = list(map(int, data["frames"])).index(case["frame"])
            for expected in case["null"]:
                values, errors = A.antithetic_null(data["stats"][j], data["recalled"][j],
                    int(data["k"][j]), expected["residual_amplitude"], rng)
                with self.subTest(capture=case["capture"],frame=case["frame"],amplitude=expected["residual_amplitude"]):
                    self.assertEqual(len(values), 32)
                    self.assertLess(float(errors.max()), 1e-6)
                    self.assertAlmostEqual(float(values.mean()), expected["input_gain_mean"], delta=1e-9)
                    self.assertLess(float(values.mean()), 1)

    def test_moderate_real_light_change_is_a_known_baseline_falsifier(self):
        probes = {p["step"]:p for p in A.uniform_light_probe()}
        self.assertAlmostEqual(probes[1.25]["output"], 1, delta=.001)
        self.assertLess(abs(probes[1.1]["response"]), .01)
        self.assertLess(probes[1.4]["response"], .31)
        self.assertEqual(probes[2.]["gain"], 1)
        self.assertEqual(probes[.5]["gain"], 1)

    def test_native_local_identity_vs_combined_global_fallback(self):
        s = np.zeros((16,16,4),np.float32)
        r = s.copy()
        s[...,0],s[...,1],s[...,2] = 1,1,1
        r[...,0],r[...,1],r[...,3] = .8,1,1
        s[8,8,2] = 0
        self.assertLess(float(A.predict(s,r,0,.8)[8,8]), .81)
        self.assertEqual(float(A.predict(s,r,0,.8,policy="native")[8,8]), 1)
        s[8,8,2] = 1
        for dy in (-3,0,3):
            for dx in (-3,0,3): r[8+dy,8+dx,1] = 0
        self.assertLess(float(A.predict(s,r,0,.8)[8,8]), .81)
        self.assertEqual(float(A.predict(s,r,0,.8,policy="native")[8,8]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
