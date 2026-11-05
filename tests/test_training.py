import csv
import random
import tempfile
import unittest
from pathlib import Path

from ai_model import HerdSenseModel
from features import FEATURE_NAMES
from generate_dataset import make_dataset, sample_separation_limit
from ml_labels import MODEL_LABELS
from rules import Config
from train_model import load_rows, split_sessions, train


class OfflineTrainingTest(unittest.TestCase):
    def test_simulator_samples_limits_across_requested_range(self):
        rng = random.Random(42)
        limits = [sample_separation_limit(rng, 50.0, 300.0) for _ in range(20)]
        self.assertGreater(min(limits), 50.0)
        self.assertLess(max(limits), 300.0)
        self.assertGreater(len(set(limits)), 1)

    def test_simulator_labels_all_four_classes_and_splits_by_session(self):
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "trips.csv"
            count = make_dataset(dataset, sessions=8, seed=7, cfg=Config())
            features, labels, groups, _ = load_rows(dataset)
            self.assertEqual(count, len(features))
            self.assertEqual(set(labels), set(MODEL_LABELS))
            self.assertEqual(len(set(groups)), 8)
            motion_index = FEATURE_NAMES.index("motion_rms")
            safe_motion = [
                row[motion_index] for row, label in zip(features, labels)
                if label == "AMAN"
            ]
            drift_motion = [
                row[motion_index] for row, label in zip(features, labels)
                if label == "MULAI MENJAUH"
            ]
            apart_motion = [
                row[motion_index] for row, label in zip(features, labels)
                if label == "TERPISAH"
            ]
            motion_max_index = FEATURE_NAMES.index("window_motion_max_rms")
            distance_index = FEATURE_NAMES.index("nearest_distance_ratio")
            resting_safe = [
                row for row, label in zip(features, labels)
                if label == "AMAN"
                and row[motion_index] <= 0.25
                and row[motion_max_index] <= 0.25
                and row[distance_index] < 1.0
            ]
            self.assertGreaterEqual(len(resting_safe), 8)
            self.assertLess(
                max(min(safe_motion), min(drift_motion)),
                min(max(safe_motion), max(drift_motion)),
            )
            self.assertLess(
                max(min(safe_motion), min(apart_motion)),
                min(max(safe_motion), max(apart_motion)),
            )

            train_ids, validation_ids, test_ids = split_sessions(groups, seed=3)
            split_groups = [
                {groups[index] for index in selected}
                for selected in (train_ids, validation_ids, test_ids)
            ]
            self.assertFalse(split_groups[0] & split_groups[1])
            self.assertFalse(split_groups[0] & split_groups[2])
            self.assertFalse(split_groups[1] & split_groups[2])

    def test_training_exports_loadable_predictor(self):
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "trips.csv"
            model_path = Path(directory) / "model.joblib"
            make_dataset(dataset, sessions=120, seed=11, cfg=Config())
            train(dataset, model_path, seed=13)

            model = HerdSenseModel.load(model_path)
            values = {name: 0.0 for name in FEATURE_NAMES}
            label, confidence = model.predict(values)
            self.assertIn(label, MODEL_LABELS)
            self.assertGreaterEqual(confidence, 0.0)
            self.assertLessEqual(confidence, 1.0)

            _, labels, _, _ = load_rows(dataset)
            self.assertIn("AMAN", labels)
            with dataset.open("r", newline="", encoding="utf-8") as source:
                resting_rows = [
                    row for row in csv.DictReader(source)
                    if row["label"] == "AMAN"
                    and float(row["motion_rms"]) <= 0.25
                    and float(row["window_motion_max_rms"]) <= 0.25
                    and float(row["nearest_distance_ratio"]) < 1.0
                ]
            self.assertTrue(resting_rows)
            resting_features = {
                name: float(resting_rows[-1][name]) for name in FEATURE_NAMES
            }
            resting_prediction, _ = model.predict(resting_features)
            self.assertEqual(resting_prediction, "AMAN")

            for distance_ratio in (0.3, 0.6, 0.8):
                brisk_walking_together = dict(values)
                brisk_walking_together.update({
                    "nearest_distance_ratio": distance_ratio,
                    "distance_trend_ratio_s": 0.0,
                    "speed_mps": 1.8,
                    "window_distance_mean_ratio": distance_ratio,
                    "motion_rms": 2.2,
                    "window_motion_mean_rms": 2.2,
                    "window_motion_max_rms": 2.2,
                    "window_speed_mean_mps": 1.8,
                    "window_speed_max_mps": 2.1,
                    "samples_in_window": 8.0,
                    "window_duration_s": 21.0,
                })
                prediction, _ = model.predict(brisk_walking_together)
                self.assertEqual(prediction, "AMAN")


if __name__ == "__main__":
    unittest.main()
