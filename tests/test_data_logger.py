import csv
import tempfile
import unittest
from pathlib import Path

from data_logger import CSV_COLUMNS, DetectorCsvLogger
from features import FEATURE_NAMES


class DetectorCsvLoggerTest(unittest.TestCase):
    def test_appends_label_ready_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "detector.csv"
            logger = DetectorCsvLogger(path, "session-a")
            logger.log(1234, "ayu", {name: 1.0 for name in FEATURE_NAMES},
                       "TOGETHER", "TOGETHER", "TOGETHER", 0.8)
            logger.close()
            with path.open(newline="", encoding="utf-8") as source:
                reader = csv.DictReader(source)
                self.assertEqual(tuple(reader.fieldnames), CSV_COLUMNS)
                row = next(reader)
            self.assertEqual(row["session_id"], "session-a")
            self.assertEqual(row["label"], "")
            self.assertEqual(row["ai_confidence"], "0.8")

    def test_refuses_a_mismatched_existing_header(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "detector.csv"
            path.write_text("wrong,header\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unexpected CSV header"):
                DetectorCsvLogger(path, "session-a")

if __name__ == "__main__":
    unittest.main()
