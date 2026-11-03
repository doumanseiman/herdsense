"""Incremental Gaussian Naive Bayes model for live HerdSense telemetry."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path

from features import FEATURE_NAMES
from rules import INITIALIZING, LOST, SEPARATED, TOGETHER, WAITING

LABELS = (TOGETHER, WAITING, SEPARATED, LOST)
FORMAT_VERSION = 1


class OnlineGaussianNB:
    """Online classifier trained with debounced rule outputs as pseudo-labels."""

    def __init__(self, min_samples_per_class: int = 5) -> None:
        if min_samples_per_class < 2:
            raise ValueError("min_samples_per_class must be at least 2")
        self.min_samples_per_class = min_samples_per_class
        self._stats: dict[str, dict] = {}

    @classmethod
    def load_or_create(cls, path: Path, min_samples_per_class: int = 5) -> OnlineGaussianNB:
        model = cls(min_samples_per_class)
        if not path.exists():
            return model
        with path.open(encoding="utf-8") as model_file:
            saved = json.load(model_file)
        if saved.get("format_version") != FORMAT_VERSION:
            raise ValueError(f"Unsupported online AI model format in {path}")
        if tuple(saved.get("feature_names", ())) != FEATURE_NAMES:
            raise ValueError(f"Online AI model feature schema mismatch in {path}")
        if tuple(saved.get("labels", ())) != LABELS:
            raise ValueError(f"Online AI model label schema mismatch in {path}")
        if saved.get("min_samples_per_class") != min_samples_per_class:
            raise ValueError(
                f"AI warm-up setting differs from the saved model in {path}; "
                "use the saved setting or a new AI_STATE_PATH"
            )
        stats = saved.get("stats")
        if not isinstance(stats, dict):
            raise ValueError(f"Online AI model statistics are invalid in {path}")
        for label, item in stats.items():
            if label not in LABELS or not isinstance(item, dict):
                raise ValueError(f"Online AI model contains an unknown class in {path}")
            count, means, m2 = item.get("count"), item.get("means"), item.get("m2")
            if (not isinstance(count, int) or count < 0
                    or not isinstance(means, list) or not isinstance(m2, list)
                    or len(means) != len(FEATURE_NAMES) or len(m2) != len(FEATURE_NAMES)
                    or any(not math.isfinite(float(value)) for value in means + m2)
                    or any(float(value) < 0 for value in m2)):
                raise ValueError(f"Online AI model class statistics are invalid in {path}")
            model._stats[label] = {
                "count": count,
                "means": [float(value) for value in means],
                "m2": [float(value) for value in m2],
            }
        return model

    @property
    def sample_counts(self) -> dict[str, int]:
        return {label: self._stats.get(label, {}).get("count", 0) for label in LABELS}

    @property
    def is_ready(self) -> bool:
        return sum(
            count >= self.min_samples_per_class for count in self.sample_counts.values()
        ) >= 2

    @staticmethod
    def _vector(values: dict[str, float]) -> list[float]:
        try:
            vector = [float(values[name]) for name in FEATURE_NAMES]
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Missing or invalid AI model input feature") from exc
        if any(not math.isfinite(value) for value in vector):
            raise ValueError("AI model input features must be finite")
        return vector

    def update(self, label: str, values: dict[str, float]) -> None:
        if label not in LABELS:
            raise ValueError(f"Unknown AI training label: {label}")
        vector = self._vector(values)
        item = self._stats.setdefault(label, {
            "count": 0,
            "means": [0.0] * len(FEATURE_NAMES),
            "m2": [0.0] * len(FEATURE_NAMES),
        })
        item["count"] += 1
        count = item["count"]
        for index, value in enumerate(vector):
            delta = value - item["means"][index]
            item["means"][index] += delta / count
            item["m2"][index] += delta * (value - item["means"][index])

    def predict(self, values: dict[str, float]) -> tuple[str, float] | None:
        vector = self._vector(values)
        eligible = {
            label: self._stats[label]
            for label in LABELS
            if self._stats.get(label, {}).get("count", 0) >= self.min_samples_per_class
        }
        if len(eligible) < 2:
            return None

        total_count = sum(item["count"] for item in eligible.values())
        log_probabilities: dict[str, float] = {}
        for label, item in eligible.items():
            count = item["count"]
            log_probability = math.log(count / total_count)
            for index, value in enumerate(vector):
                mean = item["means"][index]
                variance = item["m2"][index] / max(1, count - 1)
                variance = max(variance, 1e-6 * max(1.0, mean * mean))
                difference = value - mean
                log_probability -= 0.5 * (
                    math.log(2 * math.pi * variance) + difference * difference / variance
                )
            log_probabilities[label] = log_probability

        maximum = max(log_probabilities.values())
        probabilities = {
            label: math.exp(value - maximum) for label, value in log_probabilities.items()
        }
        total_probability = sum(probabilities.values())
        normalized = {
            label: value / total_probability for label, value in probabilities.items()
        }
        prediction = max(normalized, key=normalized.__getitem__)
        return prediction, normalized[prediction]

    def decide(
        self, rule_status: str, values: dict[str, float], min_confidence: float
    ) -> tuple[str, str, str | None, float | None]:
        if rule_status == INITIALIZING:
            return INITIALIZING, "RULE_WARMUP", None, None
        prediction = self.predict(values)
        if prediction is None:
            return rule_status, "RULE_WARMUP", None, None
        ai_status, confidence = prediction
        if confidence < min_confidence:
            return rule_status, "RULE_LOW_CONFIDENCE", ai_status, confidence
        return ai_status, "AI", ai_status, confidence

    def save(self, path: Path) -> None:
        payload = {
            "format_version": FORMAT_VERSION,
            "feature_names": list(FEATURE_NAMES),
            "labels": list(LABELS),
            "min_samples_per_class": self.min_samples_per_class,
            "stats": self._stats,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        try:
            with temporary.open("w", encoding="utf-8") as model_file:
                json.dump(payload, model_file, separators=(",", ":"), allow_nan=False)
                model_file.flush()
                os.fsync(model_file.fileno())
            temporary.replace(path)
        finally:
            if temporary.exists():
                temporary.unlink()


def group_model_path(base_path: Path, group_id: str) -> Path:
    """Use a group-specific file name without storing the private group ID."""
    digest = hashlib.sha256(group_id.encode("utf-8")).hexdigest()[:12]
    return base_path.with_name(f"{base_path.stem}_{digest}{base_path.suffix}")
