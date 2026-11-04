import tempfile
import unittest
from pathlib import Path

from ai_model import HerdSenseModel
from features import FEATURE_NAMES
from generate_dataset import make_dataset
from ml_labels import MODEL_LABELS
from rules import Config
from train_model import load_rows, split_sessions, train


class OfflineTrainingTest(unittest.TestCase):
    def test_simulator_labels_all_four_classes_and_splits_by_session(self):
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "trips.csv"
            count = make_dataset(dataset, sessions=8, seed=7, cfg=Config())
            features, labels, groups, _ = load_rows(dataset)
            self.assertEqual(count, len(features))
            self.assertEqual(set(labels), set(MODEL_LABELS))
            self.assertEqual(len(set(groups)), 8)

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
            make_dataset(dataset, sessions=8, seed=11, cfg=Config())
            train(dataset, model_path, seed=13)

            model = HerdSenseModel.load(model_path)
            values = {name: 0.0 for name in FEATURE_NAMES}
            label, confidence = model.predict(values)
            self.assertIn(label, MODEL_LABELS)
            self.assertGreaterEqual(confidence, 0.0)
            self.assertLessEqual(confidence, 1.0)


if __name__ == "__main__":
    unittest.main()
