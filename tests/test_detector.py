import json
import unittest

from detector import (
    append_history_sample,
    debounced_status,
    decide_alert,
    format_distance,
    choose_status,
    parse,
    prediction_guard_reason,
)
from rules import LOST, SEPARATED, TOGETHER, Member
from ml_labels import APART, MOVING_AWAY, SAFE, STRAGGLER


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

    def test_prediction_guard_rejects_apart_prediction_close_to_group(self):
        reason = prediction_guard_reason(APART, TOGETHER, 15.0, 100.0, 0.0)
        self.assertIn("TOGETHER", reason)

    def test_prediction_guard_rejects_drift_without_increasing_distance(self):
        reason = prediction_guard_reason(MOVING_AWAY, TOGETHER, 60.0, 100.0, 0.0)
        self.assertIn("not clearly increasing", reason)

    def test_prediction_guard_rejects_small_gps_noise_trend(self):
        reason = prediction_guard_reason(MOVING_AWAY, TOGETHER, 90.0, 100.0, 0.003)
        self.assertIn("not clearly increasing", reason)

    def test_prediction_guard_allows_drift_with_increasing_distance(self):
        self.assertIsNone(
            prediction_guard_reason(MOVING_AWAY, TOGETHER, 90.0, 100.0, 0.02)
        )


class AiDecidesTest(unittest.TestCase):
    def test_model_decides_when_not_vetoed(self):
        self.assertEqual(choose_status(TOGETHER, MOVING_AWAY, None), (MOVING_AWAY, "AI_MODEL"))

    def test_rules_take_over_when_vetoed_or_signal_lost(self):
        self.assertEqual(choose_status(TOGETHER, APART, "why"), (SAFE, "RULES_GUARD"))
        self.assertEqual(choose_status(LOST, None, None), (LOST, "RULE_SAFETY"))

    def test_resting_group_is_not_reported_as_stopped_behind(self):
        reason = prediction_guard_reason(STRAGGLER, TOGETHER, 15.0, 100.0, 0.0)
        self.assertIsNotNone(reason)
        self.assertEqual(choose_status(TOGETHER, STRAGGLER, reason), (SAFE, "RULES_GUARD"))


class DecideAlertTest(unittest.TestCase):
    def test_apart_and_separated_trigger_warning_with_cooldown(self):
        self.assertEqual(
            decide_alert(APART, SAFE, 2500.0, 100.0, 0.0, 30.0),
            ("warn", "is 2500 m from the group"),
        )
        self.assertIsNone(decide_alert(APART, APART, 2500.0, 110.0, 100.0, 30.0))
        self.assertEqual(
            decide_alert(APART, APART, 2500.0, 140.0, 100.0, 30.0),
            ("warn", "is 2500 m from the group"),
        )
        self.assertEqual(
            decide_alert(SEPARATED, TOGETHER, 120.0, 100.0, 0.0, 30.0),
            ("warn", "is 120 m from the group"),
        )

    def test_moving_away_triggers_early_drift_info(self):
        self.assertEqual(
            decide_alert(MOVING_AWAY, SAFE, 60.0, 100.0, 0.0, 30.0),
            ("info", "is starting to drift away (60 m)"),
        )

    def test_straggler_and_recovery_alerts(self):
        self.assertEqual(
            decide_alert(STRAGGLER, SAFE, 120.0, 100.0, 0.0, 30.0),
            ("info", "stopped 120 m from the group"),
        )
        self.assertEqual(
            decide_alert(SAFE, APART, 10.0, 100.0, 0.0, 30.0),
            ("info", "is back with the group"),
        )
        self.assertEqual(
            decide_alert(LOST, SAFE, None, 100.0, 0.0, 30.0),
            ("info", "no signal"),
        )


if __name__ == "__main__":
    unittest.main()
