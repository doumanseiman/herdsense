import unittest

from features import FEATURE_NAMES, build_features
from rules import Member


class FeaturesTest(unittest.TestCase):
    def test_builds_fifteen_window_features(self):
        member = Member("a", 0.0, 0.0, 5.0, 1.0, 12.0)
        history = [
            {"ts": 0.0, "lat": 0.0, "lon": 0.0, "accuracy_m": 5.0,
             "motion_rms": 0.5, "distance_m": 10.0},
            {"ts": 10.0, "lat": 0.0, "lon": 0.001, "accuracy_m": 7.0,
             "motion_rms": 1.0, "distance_m": 30.0},
            {"ts": 40.0, "lat": 0.0, "lon": 0.002, "accuracy_m": 9.0,
             "motion_rms": None, "distance_m": 50.0},
        ]
        result = build_features(history, member, 50.0, 0.0, 40.0, window_s=30.0)
        self.assertEqual(tuple(result), FEATURE_NAMES)
        self.assertEqual(result["samples_in_window"], 2.0)
        self.assertAlmostEqual(result["distance_trend_mps"], 2.0 / 3.0)
        self.assertEqual(result["motion_rms"], 1.0)
        self.assertAlmostEqual(result["window_accuracy_mean_m"], 8.0)


if __name__ == "__main__":
    unittest.main()
