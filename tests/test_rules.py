import unittest

from rules import LOST, SEPARATED, TOGETHER, WAITING, Config, Member, evaluate, haversine_m

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
        self.assertEqual(r["b"]["status"], TOGETHER)


if __name__ == "__main__":
    unittest.main()
