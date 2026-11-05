import unittest

from features import FEATURE_NAMES, build_features
from rules import Member


class FeaturesTest(unittest.TestCase):
    def test_builds_fifteen_window_features(self):
        member = Member("a", 0.0, 0.0, 5.0, 1.0, 12.0)
        history = [
            {"ts": 0.0, "lat": 0.0, "lon": 0.0, "accuracy_m": 5.0,
             "motion_rms": 0.5, "distance_m": 10.0, "threshold_m": 100.0},
            {"ts": 10.0, "lat": 0.0, "lon": 0.001, "accuracy_m": 7.0,
             "motion_rms": 1.0, "distance_m": 30.0, "threshold_m": 100.0},
            {"ts": 40.0, "lat": 0.0, "lon": 0.002, "accuracy_m": 9.0,
             "motion_rms": None, "distance_m": 50.0, "threshold_m": 100.0},
        ]
        result = build_features(history, member, 50.0, 0.0, 40.0, window_s=30.0)
        self.assertEqual(tuple(result), FEATURE_NAMES)
        self.assertEqual(result["samples_in_window"], 2.0)
        self.assertAlmostEqual(result["distance_trend_ratio_s"], 1.0 / 150.0)
        self.assertAlmostEqual(result["nearest_distance_ratio"], 0.5)
        self.assertEqual(result["motion_rms"], 1.0)
        self.assertAlmostEqual(result["window_accuracy_mean_m"], 8.0)

    def test_distance_features_are_normalized_by_effective_limit(self):
        member = Member("a", 0.0, 0.0, 5.0, 1.0, 12.0)
        history_50 = [{
            "ts": 12.0,
            "lat": 0.0,
            "lon": 0.0,
            "accuracy_m": 5.0,
            "motion_rms": 1.0,
            "distance_m": 30.0,
            "threshold_m": 50.0,
        }]
        history_100 = [{
            **history_50[0],
            "distance_m": 60.0,
            "threshold_m": 100.0,
        }]
        result_50 = build_features(
            history_50, member, 30.0, 0.0, 12.0, separation_limit_m=50.0
        )
        result_100 = build_features(
            history_100, member, 60.0, 0.0, 12.0, separation_limit_m=100.0
        )
        self.assertAlmostEqual(result_50["nearest_distance_ratio"], 0.6)
        self.assertAlmostEqual(result_50["window_distance_mean_ratio"], 0.6)
        self.assertEqual(result_50, result_100)


if __name__ == "__main__":
    unittest.main()
