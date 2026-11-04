import json
import unittest

from detector import append_history_sample, debounced_status, format_distance, parse
from rules import LOST, SEPARATED, Member


class DetectorParseTest(unittest.TestCase):
    def test_accepts_valid_telemetry(self):
        payload = json.dumps({
            "lat": -6.2,
            "lon": 106.8,
            "sequence": 3,
            "accuracy_m": 8.5,
            "motion_rms": 0.4,
        }).encode()
        self.assertEqual(
            parse("trip/group/edge/ayu/telemetry", payload),
            ("ayu", 3, -6.2, 106.8, 8.5, 0.4),
        )

    def test_rejects_nonfinite_accuracy_and_invalid_values(self):
        for value in (float("nan"), -1):
            payload = json.dumps({
                "lat": 0,
                "lon": 0,
                "sequence": 0,
                "accuracy_m": value,
            }).encode()
            self.assertIsNone(parse("trip/group/edge/ayu/telemetry", payload))

        payload = b'{"lat": 91, "lon": 0, "sequence": 0, "accuracy_m": 1}'
        self.assertIsNone(parse("trip/group/edge/ayu/telemetry", payload))
        self.assertIsNone(parse("trip/group/edge/ayu/telemetry", b"not-json"))

    def test_history_only_appends_once_for_each_telemetry_timestamp(self):
        member = Member("ayu", -6.2, 106.8, 8.5, 0.4, 123.0)
        history = []
        self.assertTrue(append_history_sample(history, member, 20.0, 130.0, None))
        self.assertFalse(append_history_sample(history, member, 20.0, 134.0, 123.0))
        self.assertEqual(len(history), 1)

    def test_status_alert_distance_is_safe_when_missing(self):
        self.assertEqual(format_distance(None), "unknown distance")
        self.assertEqual(format_distance(12.6), "13 m")

    def test_lost_signal_safety_override_is_not_delayed_by_debounce(self):
        state = {"stable": SEPARATED, "pending": SEPARATED, "count": 2}
        self.assertEqual(debounced_status(LOST, state, 3), LOST)
        self.assertEqual(state, {"stable": LOST})


if __name__ == "__main__":
    unittest.main()
