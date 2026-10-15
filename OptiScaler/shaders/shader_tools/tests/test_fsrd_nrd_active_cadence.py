"""CPU parser controls; no native compilation, device or protected-log mutation."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fsrd_nrd_active_cadence import audit


class Cadence(unittest.TestCase):
    def read(self, lines):
        with tempfile.TemporaryDirectory(prefix="nrd_cadence_", dir="F:/FSRD/tmp") as folder:
            path = Path(folder) / "synthetic.log"
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return audit(path)

    def test_checkpoint_cadence_and_single_context(self):
        result = self.read([
            "[10:00:00.000000] [I] [NRD_BRIDGE] runtime=false",
            "[10:00:01.000000] [I] [NRD_BRIDGE] runtime=true",
            "[10:00:01.010000] [I] [NRD_BRIDGE] RR context initialized: actual",
            "[10:00:01.100000] [I] [NRD_BRIDGE] active frames=1 resets=1 SL_frame=100 bridge_frame=0",
            "[10:00:11.100000] [I] [NRD_BRIDGE] active frames=601 resets=1 SL_frame=700 bridge_frame=600",
        ])
        interval = result["active_checkpoint_intervals"][0]
        self.assertEqual(result["RR_context_creation_count"], 1)
        self.assertEqual(interval["active_frame_delta"], 600)
        self.assertAlmostEqual(interval["elapsed_ms_per_active_frame"], 10000 / 600)
        self.assertEqual(interval["runtime_off_seconds_inside"], 0)
        self.assertIn("not display/GPU FPS", interval["scope"])

    def test_off_and_survey_confounds_remain_explicit(self):
        result = self.read([
            "[10:00:00.000000] [I] [NRD_BRIDGE] runtime=true",
            "[10:00:01.000000] [I] [NRD_BRIDGE] active frames=1 resets=1 SL_frame=100 bridge_frame=0",
            "[10:00:02.000000] [I] [FRAME_SURVEY] started at Present",
            "[10:00:05.000000] [I] [NRD_BRIDGE] runtime=false",
            "[10:00:08.000000] [I] [NRD_BRIDGE] runtime=true",
            "[10:00:21.000000] [I] [NRD_BRIDGE] active frames=601 resets=2 SL_frame=800 bridge_frame=600",
        ])
        interval = result["active_checkpoint_intervals"][0]
        self.assertEqual(interval["seconds"], 20)
        self.assertEqual(interval["runtime_off_seconds_inside"], 3)
        self.assertEqual(interval["resets_delta"], 1)
        self.assertEqual(len(interval["survey_events_inside"]), 1)

    def test_midnight_wrap_and_counter_restart(self):
        result = self.read([
            "[23:59:58.000000] [I] [NRD_BRIDGE] runtime=true",
            "[23:59:59.000000] [I] [NRD_BRIDGE] active frames=1 resets=1 SL_frame=100 bridge_frame=0",
            "[00:00:01.000000] [I] [NRD_BRIDGE] active frames=601 resets=1 SL_frame=700 bridge_frame=600",
            "[00:00:02.000000] [I] [NRD_BRIDGE] active frames=1 resets=1 SL_frame=800 bridge_frame=0",
        ])
        self.assertEqual(len(result["active_checkpoint_intervals"]), 1)
        self.assertEqual(result["active_checkpoint_intervals"][0]["seconds"], 2)

    def test_sl_spacing_and_hook_totals_are_separate(self):
        result = self.read([
            "[10:00:00.000000] [I] [NRD_BRIDGE] runtime=false",
            "[10:00:00.100000] [I] [NRD_BRIDGE] window=100_gameplay_Consumer_intervals cpu_hooks_sum_ms_per_frame=1000",
            "[10:00:00.200000] [I] StreamlineHooks::hkslEvaluateFeature slEvaluateFeature: feature 0",
            "[10:00:00.280000] [I] StreamlineHooks::hkslEvaluateFeature slEvaluateFeature: feature 0",
            "[10:00:00.300000] [I] [NRD_BRIDGE] runtime=true",
        ])
        self.assertEqual(result["active_checkpoint_intervals"], [])
        self.assertEqual(len(result["first100_reports"]), 1)
        self.assertAlmostEqual(result["runtime_segments"][0]["SL_feature0_spacing"]["mean_ms"], 80)
        self.assertIn("not FPS", result["runtime_segments"][0]["scope"])


if __name__ == "__main__":
    unittest.main()
