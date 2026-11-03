"""Safe JSON inference for exported Gradient Boosting models (no pickle/joblib)."""
from __future__ import annotations

import json
import math
from pathlib import Path

from features import FEATURE_NAMES


class GradientBoostingModel:
    def __init__(self, model: dict) -> None:
        if model.get("format_version") != 1:
            raise ValueError("Unsupported AI model format version")
        if tuple(model.get("feature_names", ())) != FEATURE_NAMES:
            raise ValueError("AI model feature schema does not match this HerdSense version")
        self.classes = model["classes"]
        self.priors = model["class_prior"]
        self.learning_rate = float(model["learning_rate"])
        self.trees = model["trees"]
        if len(self.classes) < 2 or len(self.priors) != len(self.classes):
            raise ValueError("AI model has invalid class metadata")
        if any(len(stage) != len(self.classes) for stage in self.trees):
            raise ValueError("AI model has an invalid tree stage")

    @classmethod
    def load(cls, path: Path) -> GradientBoostingModel:
        with path.open(encoding="utf-8") as model_file:
            return cls(json.load(model_file))

    @staticmethod
    def _tree_value(tree: dict, features: list[float]) -> float:
        nodes = tree["nodes"]
        index = 0
        for _ in range(len(nodes)):
            node = nodes[index]
            feature = node["feature"]
            if feature < 0:
                return float(node["value"])
            index = node["left"] if features[feature] <= node["threshold"] else node["right"]
            if not 0 <= index < len(nodes):
                raise ValueError("AI model contains an invalid tree node")
        raise ValueError("AI model tree contains a cycle")

    def predict(self, values: dict[str, float]) -> tuple[str, float]:
        try:
            vector = [float(values[name]) for name in FEATURE_NAMES]
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Missing or invalid AI model input feature") from exc
        if any(not math.isfinite(value) for value in vector):
            raise ValueError("AI model input features must be finite")

        logits = [math.log(max(float(prior), 1e-15)) for prior in self.priors]
        for stage in self.trees:
            for class_index, tree in enumerate(stage):
                logits[class_index] += self.learning_rate * self._tree_value(tree, vector)
        maximum = max(logits)
        exponentials = [math.exp(value - maximum) for value in logits]
        total = sum(exponentials)
        probabilities = [value / total for value in exponentials]
        best = max(range(len(probabilities)), key=probabilities.__getitem__)
        return str(self.classes[best]), probabilities[best]
