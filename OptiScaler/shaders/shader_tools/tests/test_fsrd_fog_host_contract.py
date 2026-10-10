"""Verify Fog's production upload and reject silent CB/resource/history drift."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import verify_fsrd_mirrors as mirrors


class FogHostContract(unittest.TestCase):
    def setUp(self):
        mirrors.errors.clear()

    def tearDown(self):
        mirrors.errors.clear()

    def test_current_descriptor_is_uploaded(self):
        mirrors.check_fog_history_host()
        self.assertEqual(mirrors.errors, [])

    def test_stale_and_reversed_jitter_are_rejected(self):
        source = mirrors.read(mirrors.PREPROCESSOR_CPP)
        for replacement in ("m_historyJitterDelta.x",
                            "desc.JitterOffsets.x - desc.JitterOffsets.z",
                            "(desc.JitterOffsets.z - desc.JitterOffsets.x) * desc.RenderSize.z"):
            with self.subTest(replacement=replacement):
                mirrors.errors.clear()
                altered = source.replace("desc.JitterOffsets.z - desc.JitterOffsets.x",
                                         replacement, 1)
                self.assertNotEqual(altered, source)
                mirrors.check_fog_history_host(altered)
                self.assertTrue(mirrors.errors)

    def test_discarded_jitter_upload_is_rejected(self):
        source = mirrors.read(mirrors.PREPROCESSOR_CPP)
        altered = source.replace("reset ? 1u : 0u, historyJitterDelta", "reset ? 1u : 0u, {}", 1)
        self.assertNotEqual(altered, source)
        mirrors.check_fog_history_host(altered)
        self.assertTrue(mirrors.errors)

    def test_verified_layout_and_bindings(self):
        mirrors.check_constants()
        mirrors.check_resources()
        self.assertEqual(mirrors.errors, [])

    def test_rank_cannot_be_bypassed(self):
        source = mirrors.read(mirrors.PREPROCESSOR_CPP)
        altered = source.replace("const FogSmooth::Input inputs {{m_fogKappaRank.Get()",
                                 "const FogSmooth::Input inputs {{m_fogKappaRaw.Get()", 1)
        self.assertNotEqual(altered, source)
        mirrors.check_fog_history_host(altered)
        self.assertTrue(any("median must be wired" in error for error in mirrors.errors))

    def test_rank_parameter_swap_is_rejected(self):
        original_read = mirrors.read
        shader = original_read(mirrors.FOG_RANK_HLSL)
        altered = shader.replace("float ZTolerance;", "float Percentile;", 1)
        altered = altered.replace("float Percentile; // 0..100", "float ZTolerance; // 0..100", 1)
        self.assertNotEqual(altered, shader)
        with patch.object(mirrors, "read", side_effect=lambda path:
                          altered if path == mirrors.FOG_RANK_HLSL else original_read(path)):
            mirrors.check_constants()
        self.assertTrue(any("FogRank::Constants member order differs" in error
                            for error in mirrors.errors))

    def test_tail_member_width_drift_is_rejected(self):
        original_read = mirrors.read
        data = original_read(mirrors.DATA_H)
        altered = data.replace("XMFLOAT2 HistoryJitterDelta;", "float HistoryJitterDelta;", 1)
        self.assertNotEqual(altered, data)
        with patch.object(mirrors, "read", side_effect=lambda path:
                          altered if path == mirrors.DATA_H else original_read(path)):
            mirrors.check_constants()
        self.assertTrue(any("HistoryJitterDelta occupies 4 bytes" in error
                            for error in mirrors.errors))

    def test_motion_binding_swap_is_rejected(self):
        original_read = mirrors.read
        shader = original_read(mirrors.FOG_STATS_HLSL)
        altered = shader.replace("InLinearDepth : register(t6)", "InLinearDepth : register(t7)")
        altered = altered.replace("InMotion : register(t7)", "InMotion : register(t6)")
        self.assertNotEqual(altered, shader)
        with patch.object(mirrors, "read", side_effect=lambda path:
                          altered if path == mirrors.FOG_STATS_HLSL else original_read(path)):
            mirrors.check_resources()
        self.assertTrue(any("FogStats SRV order differs" in error for error in mirrors.errors))


if __name__ == "__main__":
    unittest.main(verbosity=2)
