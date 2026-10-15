"""CPU contracts only; this entry point never builds or executes GPU work."""
import unittest


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromNames([
        'test_fsrd_nrd_recovery_prototype',
        'test_fsrd_nrd_lobe_reference_prototype',
        'test_fsrd_nrd_rr_band_gain_prototype',
        'test_fsrd_nrd_recovery_uncertainty',
    ])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
