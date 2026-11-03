import unittest

from rules import (
    INITIALIZING,
    LOST,
    SEPARATED,
    TOGETHER,
    WAITING,
    Config,
    Member,
    debounce_status,
    evaluate,
    haversine_m,
)

BASE = (-6.1754, 106.8272)
M_PER_DEG_LON = 111320 * 0.99443  # cos(6.1754 deg)


def mem(name, east_m=0.0, now=100.0, rms=1.5, acc=8.0, age=0.0):
    return Member(name, BASE[0], BASE[1] + east_m / M_PER_DEG_LON, acc, rms, now - age)


class RulesTest(unittest.TestCase):
    cfg = Config(separation_m=100, grace_s=60)

    def run_eval(self, members, now=100.0, memory=None):
        memory = {} if memory is None else memory
        return evaluate({m.name: m for m in members}, now, self.cfg, memory), memory

    def test_haversine(self):
        self.assertAlmostEqual(haversine_m(0, 0, 0, 1), 111195, delta=100)
        self.assertEqual(haversine_m(1, 1, 1, 1), 0)

    def test_together(self):
        r, _ = self.run_eval([mem("a"), mem("b", 30), mem("c", 50)])
        self.assertTrue(all(v["status"] == TOGETHER for v in r.values()))

    def test_far_and_moving_is_separated(self):
        r, _ = self.run_eval([mem("a"), mem("b"), mem("c", 300)])
        self.assertEqual(r["c"]["status"], SEPARATED)
        self.assertEqual(r["a"]["status"], TOGETHER)

    def test_two_people_far_apart_both_flagged(self):
        r, _ = self.run_eval([mem("a"), mem("b", 300)])
        self.assertEqual(r["a"]["status"], SEPARATED)
        self.assertEqual(r["b"]["nearest"], "a")

    def test_far_and_still_waits_then_escalates(self):
        mm = {}
        r, mm = self.run_eval([mem("a"), mem("b"), mem("c", 300, rms=0.1)], now=100, memory=mm)
        self.assertEqual(r["c"]["status"], WAITING)
        r, mm = self.run_eval([mem("a", now=170), mem("b", now=170), mem("c", 300, now=170, rms=0.1)],
                              now=170, memory=mm)
        self.assertEqual(r["c"]["status"], SEPARATED)

    def test_stale_or_bad_gps_is_lost(self):
        r, _ = self.run_eval([mem("a"), mem("b"), mem("c", age=40)])
        self.assertEqual(r["c"]["status"], LOST)
        r, _ = self.run_eval([mem("a"), mem("b"), mem("c", acc=200)])
        self.assertEqual(r["c"]["status"], LOST)

    def test_hysteresis(self):
        mm = {}
        _, mm = self.run_eval([mem("a"), mem("b", 130)], memory=mm)   # separated
        r, mm = self.run_eval([mem("a"), mem("b", 90)], memory=mm)    # inside 100 but not inside 80
        self.assertEqual(r["b"]["status"], SEPARATED)
        r, mm = self.run_eval([mem("a"), mem("b", 70)], memory=mm)
        self.assertEqual(r["b"]["status"], SEPARATED)
        r, mm = self.run_eval([mem("a"), mem("b", 70)], memory=mm)
        self.assertEqual(r["b"]["status"], TOGETHER)

    def test_distance_threshold_uses_combined_gps_accuracy_and_minimum(self):
        cfg = Config(separation_m=30, min_separation_m=50)
        members = [mem("a"), mem("b", 45)]
        result = evaluate({m.name: m for m in members}, 100, cfg, {})
        self.assertEqual(result["b"]["threshold_m"], 50)
        self.assertEqual(result["b"]["status"], TOGETHER)

        members = [mem("a", acc=40), mem("b", 55, acc=40)]
        result = evaluate({m.name: m for m in members}, 100, cfg, {})
        self.assertEqual(result["b"]["threshold_m"], 56.6)
        self.assertEqual(result["b"]["status"], TOGETHER)

    def test_median_smoothing_rejects_one_gps_spike(self):
        cfg = Config(separation_m=100, smoothing_samples=3)
        memory = {}
        for distance in (40, 300, 40):
            result = evaluate({m.name: m for m in [mem("a"), mem("b", distance)]},
                              100, cfg, memory)
        self.assertAlmostEqual(result["b"]["raw_distance_m"], 40, delta=0.2)
        self.assertAlmostEqual(result["b"]["distance_m"], 40, delta=0.2)
        self.assertEqual(result["b"]["status"], TOGETHER)

    def test_debounce_requires_consecutive_candidates(self):
        state = {}
        self.assertEqual(debounce_status(TOGETHER, state, 3), INITIALIZING)
        self.assertEqual(debounce_status(SEPARATED, state, 3), INITIALIZING)
        self.assertEqual(debounce_status(TOGETHER, state, 3), INITIALIZING)
        self.assertEqual(debounce_status(TOGETHER, state, 3), INITIALIZING)
        self.assertEqual(debounce_status(TOGETHER, state, 3), TOGETHER)
        self.assertEqual(debounce_status(SEPARATED, state, 3), TOGETHER)
        self.assertEqual(debounce_status(SEPARATED, state, 3), TOGETHER)
        self.assertEqual(debounce_status(SEPARATED, state, 3), SEPARATED)


if __name__ == "__main__":
    unittest.main()
