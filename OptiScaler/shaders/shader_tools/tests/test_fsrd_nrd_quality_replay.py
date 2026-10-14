"""CPU checks for paired replay data integrity and linear-RGB metrics; no compiler/GPU."""
from pathlib import Path
import tempfile
import unittest
import numpy as np
from fsrd_nrd_quality_replay import _put, load_payload, frame_metrics


class QualityReplayChecks(unittest.TestCase):
    def test_native_half_payload_roundtrip(self):
        with tempfile.TemporaryDirectory(prefix='fsrd13e-') as temporary:
            path = Path(temporary)
            values = np.arange(128, dtype='<f2').reshape(4, 8, 4)
            payload = _put(path, 'finite-native.bin', values)
            self.assertEqual(load_payload(path, payload).tobytes(), values.tobytes())
            self.assertEqual(payload['bytes'], values.nbytes)

    def test_sealed_payload_rejects_mutation(self):
        with tempfile.TemporaryDirectory(prefix='fsrd13e-') as temporary:
            path = Path(temporary)
            payload = _put(path, 'native.bin', np.ones((2, 2, 4), '<f2'))
            data = bytearray((path/'native.bin').read_bytes()); data[0] ^= 1
            (path/'native.bin').write_bytes(data)
            with self.assertRaisesRegex(ValueError, 'integrity'):
                load_payload(path, payload)

    def test_sealed_payload_rejects_wrong_size(self):
        with tempfile.TemporaryDirectory(prefix='fsrd13e-') as temporary:
            path = Path(temporary)
            payload = _put(path, 'native.bin', np.ones((2, 2, 4), '<f2'))
            (path/'native.bin').write_bytes(b'zero')
            with self.assertRaisesRegex(ValueError, 'integrity'):
                load_payload(path, payload)

    def test_payload_paths_are_local(self):
        for name in ('../foreign.bin', 'nested/foreign.bin', 'nested\\foreign.bin'):
            with self.assertRaisesRegex(ValueError, 'basename'):
                load_payload(Path('unused'), dict(file=name))

    def test_exact_reference_has_zero_linear_metrics(self):
        reference = np.arange(48).reshape(4, 4, 3)/256.
        output = np.concatenate((reference, np.ones((4, 4, 1))), axis=-1)
        measured = frame_metrics(output, reference, [0, 0, 4, 4])
        self.assertEqual(measured, dict(rmse=0., bias=0., detail_gradient_rmse=0.))

    def test_guard_alpha_are_excluded_and_reveal_is_current_surface(self):
        reference = np.zeros((8, 8, 3))
        output = np.zeros((8, 8, 4)); output[..., 3] = 12345
        output[:2, :, :3] = 100; output[:, :2, :3] = 100
        output[2:6, 2:6, :3] = .125
        mask = np.zeros((8, 8), bool); mask[3:5, 3:5] = True
        measured = frame_metrics(output, reference, [2, 2, 4, 4], mask)
        self.assertEqual(measured['rmse'], .125)
        self.assertEqual(measured['bias'], .125)
        self.assertEqual(measured['detail_gradient_rmse'], 0)
        self.assertEqual(measured['reveal_rmse'], .125)
        self.assertEqual(measured['reveal_pixels'], 4)

    def test_nonfinite_output_never_becomes_quality_score(self):
        reference = np.zeros((4, 4, 3)); output = np.zeros((4, 4, 4)); output[2, 2, 0] = np.nan
        with self.assertRaisesRegex(ValueError, 'nonfinite'):
            frame_metrics(output, reference, [0, 0, 4, 4])

    def test_detail_metric_detects_shifted_equal_mean_edge(self):
        reference = np.zeros((8, 8, 3)); reference[:, 4:] = .125
        output = np.zeros((8, 8, 4)); output[:, 3:7, :3] = .125
        measured = frame_metrics(output, reference, [0, 0, 8, 8])
        self.assertEqual(measured['bias'], 0)
        self.assertGreater(measured['detail_gradient_rmse'], 0)
        self.assertGreater(measured['rmse'], 0)


if __name__ == '__main__':
    unittest.main()
