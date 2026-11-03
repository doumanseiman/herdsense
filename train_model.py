"""Train, evaluate, and export a portable Gradient Boosting model."""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

from features import FEATURE_NAMES
from rules import LOST, SEPARATED, TOGETHER, WAITING

LABELS = {LOST, SEPARATED, TOGETHER, WAITING}


def _read_dataset(
    path: Path,
) -> tuple[list[list[float]], list[str], list[str], list[str], list[tuple[str, str, int]]]:
    features: list[list[float]] = []
    labels: list[str] = []
    sessions: list[str] = []
    rules: list[str] = []
    series: list[tuple[str, str, int]] = []
    with path.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        required = {"session_id", "timestamp_ms", "member", "label", "rule_status", *FEATURE_NAMES}
        missing = required - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"Dataset is missing columns: {', '.join(sorted(missing))}")
        for line_number, row in enumerate(reader, start=2):
            label = row["label"].strip()
            rule_status = row["rule_status"].strip()
            if label not in LABELS or rule_status not in LABELS:
                raise ValueError(f"{path}:{line_number}: invalid label or rule_status")
            try:
                vector = [float(row[name]) for name in FEATURE_NAMES]
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{path}:{line_number}: invalid numeric feature") from exc
            if any(not math.isfinite(value) for value in vector):
                raise ValueError(f"{path}:{line_number}: features must be finite")
            features.append(vector)
            labels.append(label)
            sessions.append(row["session_id"])
            rules.append(rule_status)
            try:
                timestamp_ms = int(row["timestamp_ms"])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{path}:{line_number}: invalid timestamp_ms") from exc
            series.append((row["session_id"], row["member"], timestamp_ms))
    if not features:
        raise ValueError(f"{path} has no labeled examples")
    return features, labels, sessions, rules, series


def _serialize_tree(estimator) -> dict:
    tree = estimator.tree_
    return {
        "nodes": [
            {
                "feature": int(tree.feature[index]),
                "threshold": float(tree.threshold[index]),
                "left": int(tree.children_left[index]),
                "right": int(tree.children_right[index]),
                "value": float(tree.value[index][0][0]),
            }
            for index in range(tree.node_count)
        ]
    }


def _export_model(classifier, path: Path) -> None:
    classes = [str(value) for value in classifier.classes_]
    trees = []
    for estimators in classifier.estimators_:
        stage = [{"nodes": [{"feature": -1, "threshold": 0.0, "left": -1, "right": -1, "value": 0.0}]} for _ in classes]
        if len(classes) == 2 and len(estimators) == 1:
            stage[1] = _serialize_tree(estimators[0])
        else:
            for class_index, estimator in enumerate(estimators):
                stage[class_index] = _serialize_tree(estimator)
        trees.append(stage)

    payload = {
        "format_version": 1,
        "feature_names": list(FEATURE_NAMES),
        "classes": classes,
        "class_prior": [float(value) for value in classifier.init_.class_prior_],
        "learning_rate": float(classifier.learning_rate),
        "trees": trees,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as destination:
        json.dump(payload, destination, separators=(",", ":"), allow_nan=False)


def train(dataset: Path, model_path: Path) -> bool:
    try:
        from sklearn.ensemble import GradientBoostingClassifier
        from sklearn.metrics import f1_score, precision_score, recall_score
        from sklearn.model_selection import GroupShuffleSplit
    except ImportError as exc:
        raise RuntimeError(
            "Training requires scikit-learn. Install requirements-ml.txt (for example in Colab)."
        ) from exc

    x, y, groups, rule_predictions, series = _read_dataset(dataset)
    unique_groups = sorted(set(groups))
    if len(unique_groups) < 3:
        raise ValueError("Need at least 3 distinct session_id values for train/validation/test splits")
    classes = sorted(LABELS)
    first_split = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=42)
    train_validation, test = next(first_split.split(x, y, groups))
    train_validation_groups = [groups[index] for index in train_validation]
    second_split = GroupShuffleSplit(n_splits=1, test_size=0.25, random_state=43)
    train_relative, validation_relative = next(
        second_split.split(
            [x[index] for index in train_validation],
            [y[index] for index in train_validation],
            train_validation_groups,
        )
    )
    train_indices = [train_validation[index] for index in train_relative]
    validation_indices = [train_validation[index] for index in validation_relative]
    required_training_labels = set(y[index] for index in train_indices)
    if len(required_training_labels) < 2:
        raise ValueError("Training split must contain at least two classes; collect more sessions")

    classifier = GradientBoostingClassifier(
        n_estimators=100, learning_rate=0.05, max_depth=2, random_state=42
    )
    classifier.fit([x[index] for index in train_indices], [y[index] for index in train_indices])

    def flip_count(indices: list[int], predictions: list[str]) -> int:
        ordered = sorted(
            zip(indices, predictions),
            key=lambda item: (series[item[0]][0], series[item[0]][1], series[item[0]][2]),
        )
        previous: dict[tuple[str, str], str] = {}
        flips = 0
        for index, prediction in ordered:
            session_member = (series[index][0], series[index][1])
            if session_member in previous and previous[session_member] != prediction:
                flips += 1
            previous[session_member] = prediction
        return flips

    def report(name: str, indices: list[int]) -> tuple[float, float, int]:
        actual = [y[index] for index in indices]
        predicted = classifier.predict([x[index] for index in indices]).tolist()
        baseline = [rule_predictions[index] for index in indices]
        macro_f1 = f1_score(actual, predicted, labels=classes, average="macro", zero_division=0)
        macro_precision = precision_score(
            actual, predicted, labels=classes, average="macro", zero_division=0
        )
        macro_recall = recall_score(
            actual, predicted, labels=classes, average="macro", zero_division=0
        )
        separated_recall = recall_score(
            actual, predicted, labels=[SEPARATED], average="macro", zero_division=0
        )
        baseline_f1 = f1_score(
            actual, baseline,
            labels=classes, average="macro", zero_division=0,
        )
        baseline_recall = recall_score(
            actual, baseline,
            labels=[SEPARATED], average="macro", zero_division=0,
        )
        ai_flips = flip_count(indices, predicted)
        rule_flips = flip_count(indices, baseline)
        ai_precision = precision_score(
            actual, predicted, labels=[SEPARATED], average="macro", zero_division=0
        )
        print(
            f"{name}: AI macro precision={macro_precision:.3f}, macro recall={macro_recall:.3f}, "
            f"macro-F1={macro_f1:.3f}, separated precision={ai_precision:.3f}, "
            f"separated recall={separated_recall:.3f}; "
            f"rules macro-F1={baseline_f1:.3f}, separated recall={baseline_recall:.3f}; "
            f"status flips AI={ai_flips}, rules={rule_flips}"
        )
        return macro_f1 - baseline_f1, separated_recall - baseline_recall, rule_flips - ai_flips

    print(
        f"Rows: train={len(train_indices)}, validation={len(validation_indices)}, test={len(test)}; "
        f"sessions={len(unique_groups)} (split by session_id)"
    )
    report("Validation", validation_indices)
    f1_gain, recall_gain, flip_gain = report("Test", test)
    if f1_gain < 0 or recall_gain < 0 or flip_gain < 0:
        print(
            "Model not exported: it must match the rule baseline on test macro-F1 and "
            "SEPARATED recall, and must not increase status flips."
        )
        return False
    _export_model(classifier, model_path)
    print(f"Model exported to {model_path}")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path, help="labeled training CSV from prepare_dataset.py")
    parser.add_argument("--model", type=Path, default=Path("models/herdsense_gbc.json"))
    args = parser.parse_args()
    if not train(args.dataset, args.model):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
