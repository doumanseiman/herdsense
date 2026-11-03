import json
import unittest

from detector import parse


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


if __name__ == "__main__":
    unittest.main()
