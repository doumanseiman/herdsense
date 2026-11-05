"""Load and run the offline-trained HerdSense Gradient Boosting model."""
from __future__ import annotations

import math
from pathlib import Path

import joblib
import sklearn

from features import FEATURE_NAMES
from ml_labels import MODEL_LABELS

MODEL_FORMAT_VERSION = 2


class HerdSenseModel:
    def __init__(self, estimator) -> None:
        self.estimator = estimator
        classes = tuple(str(label) for label in getattr(estimator, "classes_", ()))
        if set(classes) != set(MODEL_LABELS):
            raise ValueError(f"Model must contain exactly these classes: {', '.join(MODEL_LABELS)}")
        if not callable(getattr(estimator, "predict_proba", None)):
            raise ValueError("HerdSense model must support predict_proba")
        self.classes = classes

    @classmethod
    def load(cls, path: Path) -> HerdSenseModel:
        if not path.is_file():
            raise FileNotFoundError(
                f"Required AI model not found: {path}. Run generate_dataset.py and "
                "train_model.py first, or set AI_MODEL_PATH to a trained model."
            )
        artifact = joblib.load(path)
        if not isinstance(artifact, dict):
            raise ValueError(f"Invalid HerdSense model artifact: {path}")
        if artifact.get("format_version") != MODEL_FORMAT_VERSION:
            raise ValueError(f"Unsupported HerdSense model format: {path}")
        if artifact.get("sklearn_version") != sklearn.__version__:
            raise ValueError(
                f"Model was trained with scikit-learn {artifact.get('sklearn_version')}; "
                f"this environment has {sklearn.__version__}. Install the matching "
                "requirements-ai.txt before loading it."
            )
        if tuple(artifact.get("feature_names", ())) != FEATURE_NAMES:
            raise ValueError(f"Model feature schema does not match this HerdSense version: {path}")
        if tuple(artifact.get("labels", ())) != MODEL_LABELS:
            raise ValueError(f"Model label schema does not match this HerdSense version: {path}")
        return cls(artifact.get("estimator"))

    def predict(self, values: dict[str, float]) -> tuple[str, float]:
        try:
            vector = [float(values[name]) for name in FEATURE_NAMES]
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Missing or invalid AI model input feature") from exc
        if any(not math.isfinite(value) for value in vector):
            raise ValueError("AI model input features must be finite")
        probabilities = self.estimator.predict_proba([vector])[0]
        if len(probabilities) != len(self.classes):
            raise ValueError("AI model returned an invalid probability vector")
        scores = [float(score) for score in probabilities]
        if any(not math.isfinite(score) or score < 0 for score in scores):
            raise ValueError("AI model returned invalid probabilities")
        total = sum(scores)
        if total <= 0:
            raise ValueError("AI model returned a zero probability sum")
        index = max(range(len(scores)), key=scores.__getitem__)
        return self.classes[index], scores[index] / total
