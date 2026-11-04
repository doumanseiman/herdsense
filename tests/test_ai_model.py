import tempfile
import unittest
from pathlib import Path

import joblib

from ai_model import HerdSenseModel, MODEL_FORMAT_VERSION
from features import FEATURE_NAMES
from ml_labels import MODEL_LABELS
import sklearn


class ExampleEstimator:
    classes_ = MODEL_LABELS

    def predict_proba(self, rows):
        return [[0.1, 0.7, 0.1, 0.1] for _ in rows]


class AiModelTest(unittest.TestCase):
    def test_predict_returns_label_and_probability(self):
        model = HerdSenseModel(ExampleEstimator())
        values = {name: 0.0 for name in FEATURE_NAMES}
        self.assertEqual(model.predict(values), (MODEL_LABELS[1], 0.7))

    def test_rejects_missing_or_nonfinite_features(self):
        model = HerdSenseModel(ExampleEstimator())
        with self.assertRaisesRegex(ValueError, "Missing or invalid"):
            model.predict({})
        invalid = {name: 0.0 for name in FEATURE_NAMES}
        invalid[FEATURE_NAMES[0]] = float("nan")
        with self.assertRaisesRegex(ValueError, "must be finite"):
            model.predict(invalid)

    def test_load_validates_artifact_schema_and_sklearn_version(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.joblib"
            artifact = {
                "format_version": MODEL_FORMAT_VERSION,
                "sklearn_version": sklearn.__version__,
                "feature_names": FEATURE_NAMES,
                "labels": MODEL_LABELS,
                "estimator": ExampleEstimator(),
            }
            joblib.dump(artifact, path)
            self.assertIsInstance(HerdSenseModel.load(path), HerdSenseModel)

            artifact["sklearn_version"] = "0.0"
            joblib.dump(artifact, path)
            with self.assertRaisesRegex(ValueError, "trained with scikit-learn"):
                HerdSenseModel.load(path)

    def test_missing_model_has_setup_instructions(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(FileNotFoundError, "generate_dataset.py"):
                HerdSenseModel.load(Path(directory) / "missing.joblib")


if __name__ == "__main__":
    unittest.main()
