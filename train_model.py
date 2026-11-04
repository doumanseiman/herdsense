"""Train and evaluate the offline Gradient Boosting model on labeled sessions."""
from __future__ import annotations

import argparse
import csv
import math
from datetime import datetime, timezone
from pathlib import Path

import joblib
import sklearn
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import accuracy_score, classification_report, f1_score
from sklearn.model_selection import GroupShuffleSplit

from features import FEATURE_NAMES
from ml_labels import MODEL_LABELS, RULE_TO_LABEL

MODEL_FORMAT_VERSION = 1


def load_rows(path: Path) -> tuple[list[list[float]], list[str], list[str], list[str]]:
    features: list[list[float]] = []
    labels: list[str] = []
    groups: list[str] = []
    rule_labels: list[str] = []
    with path.open("r", newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        required = {"session_id", "label", "rule_status", *FEATURE_NAMES}
        missing = required.difference(reader.fieldnames or ())
        if missing:
            raise ValueError(f"Dataset is missing required columns: {', '.join(sorted(missing))}")
        for row_number, row in enumerate(reader, start=2):
            label = (row["label"] or "").strip()
            if not label:
                continue
            if label not in MODEL_LABELS:
                raise ValueError(f"Unknown ground-truth label {label!r} at CSV row {row_number}")
            session_id = (row["session_id"] or "").strip()
            if not session_id:
                raise ValueError(f"Empty session_id at CSV row {row_number}")
            try:
                vector = [float(row[name]) for name in FEATURE_NAMES]
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Invalid feature value at CSV row {row_number}") from exc
            if any(not math.isfinite(value) for value in vector):
                raise ValueError(f"Nonfinite feature value at CSV row {row_number}")
            features.append(vector)
            labels.append(label)
            groups.append(session_id)
            rule_labels.append(RULE_TO_LABEL.get((row["rule_status"] or "").strip(), ""))

    if not features:
        raise ValueError("Dataset contains no manually labeled or simulator-labeled rows")
    return features, labels, groups, rule_labels


def split_sessions(groups: list[str], seed: int) -> tuple[list[int], list[int], list[int]]:
    import numpy as np

    indices = np.arange(len(groups))
    first_split = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=seed)
    train_validation, test = next(first_split.split(indices, groups=groups))
    second_split = GroupShuffleSplit(n_splits=1, test_size=0.25, random_state=seed + 1)
    train_relative, validation_relative = next(
        second_split.split(train_validation, groups=[groups[i] for i in train_validation])
    )
    train = train_validation[train_relative].tolist()
    validation = train_validation[validation_relative].tolist()
    test = test.tolist()
    sets = [set(groups[i] for i in selection) for selection in (train, validation, test)]
    if sets[0] & sets[1] or sets[0] & sets[2] or sets[1] & sets[2]:
        raise RuntimeError("Session leakage detected in train/validation/test split")
    return train, validation, test


def print_metrics(title: str, expected: list[str], predicted: list[str]) -> None:
    print(f"\n{title}")
    print(f"  accuracy: {accuracy_score(expected, predicted):.3f}")
    print(f"  macro F1: {f1_score(expected, predicted, labels=MODEL_LABELS, average='macro', zero_division=0):.3f}")
    print(classification_report(
        expected, predicted, labels=MODEL_LABELS, target_names=MODEL_LABELS, zero_division=0
    ))


def train(input_path: Path, output_path: Path, seed: int) -> None:
    import numpy as np

    x, y, groups, rule_labels = load_rows(input_path)
    if len(set(groups)) < 6:
        raise ValueError("At least 6 distinct sessions are required for held-out evaluation")
    train_ids, validation_ids, test_ids = split_sessions(groups, seed)
    training_labels = {y[index] for index in train_ids}
    if training_labels != set(MODEL_LABELS):
        missing = sorted(set(MODEL_LABELS) - training_labels)
        raise ValueError(f"Training sessions do not contain all model classes: {', '.join(missing)}")

    estimator = GradientBoostingClassifier(
        n_estimators=120,
        learning_rate=0.05,
        max_depth=3,
        random_state=seed,
    )
    estimator.fit(np.asarray(x)[train_ids], np.asarray(y)[train_ids])

    validation_prediction = estimator.predict(np.asarray(x)[validation_ids]).tolist()
    print_metrics("Validation sessions (not used for fitting)", [y[i] for i in validation_ids], validation_prediction)

    test_expected = [y[i] for i in test_ids]
    test_prediction = estimator.predict(np.asarray(x)[test_ids]).tolist()
    print_metrics("Held-out test sessions", test_expected, test_prediction)

    baseline_indices = [i for i in test_ids if rule_labels[i]]
    if not baseline_indices:
        raise ValueError("Held-out test set has no rows with a comparable rules baseline")
    print_metrics(
        f"Rules baseline on same held-out rows ({len(baseline_indices)}/{len(test_ids)} covered)",
        [y[i] for i in baseline_indices],
        [rule_labels[i] for i in baseline_indices],
    )

    artifact = {
        "format_version": MODEL_FORMAT_VERSION,
        "sklearn_version": sklearn.__version__,
        "feature_names": FEATURE_NAMES,
        "labels": MODEL_LABELS,
        "trained_at_utc": datetime.now(timezone.utc).isoformat(),
        "training_session_count": len({groups[i] for i in train_ids}),
        "validation_session_count": len({groups[i] for i in validation_ids}),
        "test_session_count": len({groups[i] for i in test_ids}),
        "estimator": estimator,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, output_path)
    print(f"Saved trained model: {output_path}")
    print("Synthetic-only metrics do not establish real-world accuracy; validate with manually labeled trips.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/synthetic_dataset.csv"))
    parser.add_argument("--output", type=Path, default=Path("models/herdsense_gbc.joblib"))
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    train(args.input, args.output, args.seed)


if __name__ == "__main__":
    main()
