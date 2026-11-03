import unittest

from ai_model import GradientBoostingModel
from features import FEATURE_NAMES
from rules import SEPARATED, TOGETHER


class ModelTest(unittest.TestCase):
    def test_portable_binary_model_predicts_confidence(self):
        leaf = {"feature": -1, "threshold": 0.0, "left": -1, "right": -1, "value": 0.0}
        model = GradientBoostingModel({
            "format_version": 1,
            "feature_names": list(FEATURE_NAMES),
            "classes": [TOGETHER, SEPARATED],
            "class_prior": [0.5, 0.5],
            "learning_rate": 1.0,
            "trees": [[
                {"nodes": [leaf]},
                {"nodes": [
                    {"feature": 0, "threshold": 10.0, "left": 1, "right": 2, "value": 0.0},
                    {"feature": -1, "threshold": 0.0, "left": -1, "right": -1, "value": -2.0},
                    {"feature": -1, "threshold": 0.0, "left": -1, "right": -1, "value": 2.0},
                ]},
            ]],
        })
        prediction, confidence = model.predict({name: 0.0 for name in FEATURE_NAMES}
                                               | {"nearest_distance_m": 20.0})
        self.assertEqual(prediction, SEPARATED)
        self.assertGreater(confidence, 0.85)

    def test_rejects_mismatched_feature_schema(self):
        with self.assertRaisesRegex(ValueError, "feature schema"):
            GradientBoostingModel({
                "format_version": 1,
                "feature_names": ["lat", "lon"],
                "classes": [TOGETHER, SEPARATED],
                "class_prior": [0.5, 0.5],
                "learning_rate": 0.1,
                "trees": [],
            })


if __name__ == "__main__":
    unittest.main()
