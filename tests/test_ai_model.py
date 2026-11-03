import tempfile
import unittest
from pathlib import Path

from ai_model import OnlineGaussianNB, group_model_path
from features import FEATURE_NAMES
from rules import INITIALIZING, SEPARATED, TOGETHER, WAITING


def features(distance: float) -> dict[str, float]:
    return {name: (distance if name == "nearest_distance_m" else 0.0)
            for name in FEATURE_NAMES}


class OnlineModelTest(unittest.TestCase):
    def test_learns_incrementally_then_predicts(self):
        model = OnlineGaussianNB(min_samples_per_class=3)
        self.assertIsNone(model.predict(features(5)))
        for distance in (5, 6, 4):
            model.update(TOGETHER, features(distance))
        for distance in (100, 101, 99):
            model.update(SEPARATED, features(distance))

        self.assertTrue(model.is_ready)
        prediction, confidence = model.predict(features(100))
        self.assertEqual(prediction, SEPARATED)
        self.assertGreater(confidence, 0.99)
        self.assertEqual(model.sample_counts[TOGETHER], 3)
        self.assertEqual(model.sample_counts[SEPARATED], 3)

    def test_rule_status_is_used_during_warmup_and_ai_after_training(self):
        model = OnlineGaussianNB(min_samples_per_class=2)
        candidate, source, prediction, confidence = model.decide(
            TOGETHER, features(5), min_confidence=0.6
        )
        self.assertEqual((candidate, source, prediction, confidence),
                         (TOGETHER, "RULE_WARMUP", None, None))
        self.assertEqual(
            model.decide(INITIALIZING, features(5), 0.6),
            (INITIALIZING, "RULE_WARMUP", None, None),
        )

        for distance in (5, 6):
            model.update(TOGETHER, features(distance))
        for distance in (100, 101):
            model.update(SEPARATED, features(distance))
        candidate, source, prediction, confidence = model.decide(
            SEPARATED, features(100), min_confidence=0.6
        )
        self.assertEqual(candidate, SEPARATED)
        self.assertEqual(source, "AI")
        self.assertEqual(prediction, SEPARATED)
        self.assertIsNotNone(confidence)

    def test_low_confidence_uses_rule_baseline(self):
        model = OnlineGaussianNB(min_samples_per_class=2)
        for _ in range(2):
            model.update(TOGETHER, features(5))
            model.update(WAITING, features(5))
        candidate, source, prediction, confidence = model.decide(
            SEPARATED, features(5), min_confidence=0.6
        )
        self.assertEqual(candidate, SEPARATED)
        self.assertEqual(source, "RULE_LOW_CONFIDENCE")
        self.assertIn(prediction, (TOGETHER, WAITING))
        self.assertLess(confidence, 0.6)

    def test_persists_and_loads_state_per_group(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory) / "model.json"
            path = group_model_path(base, "private-group")
            model = OnlineGaussianNB(min_samples_per_class=2)
            for _ in range(2):
                model.update(TOGETHER, features(5))
                model.update(SEPARATED, features(100))
            model.save(path)

            restored = OnlineGaussianNB.load_or_create(path, min_samples_per_class=2)
            self.assertEqual(restored.sample_counts, model.sample_counts)
            self.assertIsNotNone(restored.predict(features(5)))
            self.assertNotEqual(
                group_model_path(base, "private-group"),
                group_model_path(base, "different-group"),
            )

    def test_rejects_unknown_training_label_and_invalid_features(self):
        model = OnlineGaussianNB()
        with self.assertRaisesRegex(ValueError, "Unknown AI training label"):
            model.update("not-a-status", features(5))
        with self.assertRaisesRegex(ValueError, "Missing or invalid"):
            model.predict({})


if __name__ == "__main__":
    unittest.main()
