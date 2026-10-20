"""Chronological submission/publication tests; no actual GPU is invoked."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from history import HistoryModel


class PublicationTests(unittest.TestCase):
    def test_schedule_submit_complete_publish_are_four_distinct_states(self):
        model = HistoryModel()
        model.begin_frame(40, (137, 131))
        metadata = {"camera": [1, 2, 3], "frame": 40}
        token = model.schedule_capture(metadata)
        metadata["camera"][0] = 99
        self.assertEqual(model.captures[token].state, "scheduled")
        self.assertEqual(model.valid_keys(), [])
        with self.assertRaises(RuntimeError):
            model.publish(token)
        model.submit(token, 10)
        self.assertEqual(model.captures[token].state, "submitted")
        with self.assertRaises(RuntimeError):
            model.publish(token)
        model.complete(10)
        self.assertEqual(model.captures[token].state, "completed")
        self.assertEqual(model.valid_keys(), [])
        model.publish(token)
        self.assertEqual(model.captures[token].state, "valid")
        self.assertEqual(model.valid_keys()[0].metadata["camera"][0], 1)

    def test_six_physical_slots_keep_camera_frame_pair_after_wrap(self):
        model = HistoryModel()
        for frame in range(80, 95):
            model.begin_frame(frame, (137, 131))
            token = model.schedule_capture({"camera_frame": frame})
            model.submit(token, frame)
            model.complete(frame)
            model.publish(token)
        keys = model.valid_keys()
        self.assertEqual([x.frame for x in keys], list(range(94, 88, -1)))
        self.assertEqual(len(set(x.slot for x in keys)), 6)
        for key in keys:
            self.assertEqual(key.metadata["camera_frame"], key.frame)
            self.assertEqual(key.slot, (key.frame-80) % 6)

    def test_unlooped_trajectory_reset_gap_drs_toggle_and_invalid_camera(self):
        model = HistoryModel()
        schedule = [(0, (137, 131), True, True, False),
                    (1, (137, 131), True, True, False),
                    (2, (137, 131), True, True, True),
                    (5, (137, 131), True, True, False),
                    (6, (101, 87), True, True, False),
                    (7, (101, 87), False, True, False),
                    (8, (101, 87), True, True, False),
                    (9, (101, 87), True, False, False)]
        seen_reasons = []
        for frame, extent, enabled, valid_camera, reset in schedule:
            reasons = model.begin_frame(frame, extent, enabled=enabled,
                                        previous_camera_valid=valid_camera, explicit_reset=reset)
            seen_reasons.extend(reasons)
            if reasons:
                self.assertEqual(model.valid_keys(), [])
            if enabled:
                token = model.schedule_capture({"frame": frame})
                model.submit(token, frame+1)
                model.complete(frame+1)
                model.publish(token)
        for reason in ("explicit_reset", "frame_gap", "DRS_extent_change", "option_toggle", "invalid_previous_camera"):
            self.assertIn(reason, seen_reasons)
        with self.assertRaises(ValueError):
            model.begin_frame(0, (101, 87))

    def test_discarded_or_unsubmitted_graph_cannot_publish(self):
        model = HistoryModel()
        model.begin_frame(0, (31, 27))
        token = model.schedule_capture({})
        model.discard(token)
        with self.assertRaises(RuntimeError):
            model.submit(token, 1)
        model.begin_frame(1, (31, 27))
        token = model.schedule_capture({})
        reasons = model.begin_frame(2, (31, 27))
        self.assertIn("unsubmitted_previous_graph", reasons)
        with self.assertRaises(RuntimeError):
            model.submit(token, 2)
        self.assertEqual(model.valid_keys(), [])

    def test_old_fence_completion_after_cut_cannot_resurrect_old_history(self):
        model = HistoryModel()
        model.begin_frame(0, (31, 27))
        token = model.schedule_capture({"frame": 0})
        model.submit(token, 10)
        reasons = model.begin_frame(1, (31, 27), camera_cut=True)
        self.assertIn("camera_cut", reasons)
        model.complete(10)
        with self.assertRaises(RuntimeError):
            model.publish(token)
        self.assertEqual(model.valid_keys(), [])

    def test_inflight_slot_cannot_be_overwritten_or_published_by_record_only(self):
        model = HistoryModel(ring_size=2)
        for frame in range(2):
            model.begin_frame(frame, (31, 27))
            token = model.schedule_capture({})
            model.submit(token, frame+1)
        model.begin_frame(2, (31, 27))
        with self.assertRaises(RuntimeError):
            model.schedule_capture({})
        self.assertEqual(model.valid_keys(), [])

    def test_completed_old_owner_cannot_publish_over_new_slot_owner(self):
        model = HistoryModel(ring_size=1)
        model.begin_frame(0, (31, 27))
        old = model.schedule_capture({"frame": 0})
        model.submit(old, 1)
        model.complete(1)
        model.begin_frame(1, (31, 27))
        new = model.schedule_capture({"frame": 1})
        with self.assertRaises(RuntimeError):
            model.publish(old)
        model.submit(new, 2)
        model.complete(2)
        model.publish(new)
        self.assertEqual(model.valid_keys()[0].frame, 1)


if __name__ == "__main__":
    unittest.main()
