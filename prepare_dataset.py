"""Build a compact labeled training CSV from annotated detector log files."""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

from data_logger import CSV_COLUMNS
from features import FEATURE_NAMES
from rules import LOST, SEPARATED, TOGETHER, WAITING

LABELS = {LOST, SEPARATED, TOGETHER, WAITING}
OUTPUT_COLUMNS = ("session_id", "timestamp_ms", "member", *FEATURE_NAMES, "rule_status", "label")


def prepare(inputs: list[Path], output: Path) -> int:
    output.parent.mkdir(parents=True, exist_ok=True)
    examples: list[dict[str, str]] = []
    for path in inputs:
        with path.open(newline="", encoding="utf-8") as source:
            reader = csv.DictReader(source)
            if tuple(reader.fieldnames or ()) != CSV_COLUMNS:
                raise ValueError(f"{path} does not have a HerdSense detector log header")
            for line_number, row in enumerate(reader, start=2):
                label = row["label"].strip()
                if not label:
                    continue
                if label not in LABELS:
                    raise ValueError(f"{path}:{line_number}: label must be one of {sorted(LABELS)}")
                examples.append({column: row[column] for column in OUTPUT_COLUMNS})

    if not examples:
        raise ValueError("No labeled rows found. Add labels to the detector CSV 'label' column.")
    with output.open("w", newline="", encoding="utf-8") as destination:
        writer = csv.DictWriter(destination, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(examples)
    return len(examples)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("logs", nargs="+", type=Path, help="annotated detector CSV logs")
    parser.add_argument("--output", type=Path, default=Path("data/training.csv"))
    args = parser.parse_args()
    count = prepare(args.logs, args.output)
    print(f"Wrote {count} labeled examples to {args.output}")


if __name__ == "__main__":
    main()
