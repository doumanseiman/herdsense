"""Append detector feature windows and decisions to a label-ready CSV."""
from __future__ import annotations

import csv
from pathlib import Path

from features import FEATURE_NAMES

CSV_COLUMNS = (
    "session_id",
    "timestamp_ms",
    "member",
    *FEATURE_NAMES,
    "rule_status",
    "status",
    "ai_status",
    "ai_confidence",
    "label",
)


class DetectorCsvLogger:
    def __init__(self, path: Path, session_id: str) -> None:
        self.path = path
        self.session_id = session_id
        self.path.parent.mkdir(parents=True, exist_ok=True)
        needs_header = not self.path.exists() or self.path.stat().st_size == 0
        self._file = self.path.open("a", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._file, fieldnames=CSV_COLUMNS)
        if needs_header:
            self._writer.writeheader()
            self._file.flush()
        else:
            with self.path.open("r", newline="", encoding="utf-8") as existing:
                header = next(csv.reader(existing), [])
            if tuple(header) != CSV_COLUMNS:
                self._file.close()
                raise ValueError(f"{self.path} has an unexpected CSV header; use a new log file")

    def log(
        self,
        timestamp_ms: int,
        member: str,
        features: dict[str, float],
        rule_status: str,
        status: str,
        ai_status: str = "",
        ai_confidence: float | None = None,
    ) -> None:
        row = {
            "session_id": self.session_id,
            "timestamp_ms": timestamp_ms,
            "member": member,
            **features,
            "rule_status": rule_status,
            "status": status,
            "ai_status": ai_status,
            "ai_confidence": "" if ai_confidence is None else ai_confidence,
            "label": "",
        }
        self._writer.writerow(row)
        self._file.flush()

    def close(self) -> None:
        self._file.close()
