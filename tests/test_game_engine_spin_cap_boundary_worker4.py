"""Focused regression contract for GameEngine per-spin and round payout caps.

These tests intentionally assert the required safety boundary. They are kept
outside the existing dirty GameEngine test/source files so failures in the
current implementation remain visible without weakening existing coverage.
"""

import unittest

from ganesha.game.engine import GameEngine, InvalidMathOutcome


STOPS = (0, 0, 0, 0, 0)
SPIN_CAP_MILLI = 1_000_000


class ScriptedMathPort:
    def __init__(self, base_payout=0, feature_payout=0, trigger_feature=True):
        self.base_payout = base_payout
        self.feature_payout = feature_payout
        self.trigger_feature = trigger_feature

    def evaluate_stops(self, stops, mode):
        if mode == "BASE":
            return {
                "mode": mode,
                "payout_milli": self.base_payout,
                "free_spins_awarded": 10 if self.trigger_feature else 0,
                "scatter_count": 3 if self.trigger_feature else 0,
            }
        return {
            "mode": mode,
            "payout_milli": self.feature_payout,
            "scatter_count": 0,
            "jackpot_triggered": False,
        }

    def award_free_spins(self, scatter_count, retrigger=False):
        return 0


class GameEngineSpinCapBoundaryTests(unittest.TestCase):
    def _base_engine(self, payout):
        port = ScriptedMathPort(base_payout=payout, trigger_feature=False)
        engine = GameEngine(port)
        engine.spin_cap_milli = SPIN_CAP_MILLI
        return engine

    def _feature_engine(self, payout):
        port = ScriptedMathPort(base_payout=0, feature_payout=payout, trigger_feature=True)
        engine = GameEngine(port)
        engine.spin_cap_milli = SPIN_CAP_MILLI
        return engine

    def test_base_spin_cap_minus_one_and_exact_cap_are_accepted(self):
        for payout in (SPIN_CAP_MILLI - 1, SPIN_CAP_MILLI):
            with self.subTest(payout_milli=payout):
                outcome = self._base_engine(payout).resolve_base_round(STOPS, [])
                self.assertEqual(outcome["base_result"]["payout_milli"], payout)
                self.assertEqual(outcome["total_payout_milli"], payout)

    def test_base_spin_cap_plus_one_is_rejected(self):
        with self.assertRaises(InvalidMathOutcome):
            self._base_engine(SPIN_CAP_MILLI + 1).resolve_base_round(STOPS, [])

    def test_feature_spin_cap_minus_one_and_exact_cap_are_accepted(self):
        for payout in (SPIN_CAP_MILLI - 1, SPIN_CAP_MILLI):
            with self.subTest(payout_milli=payout):
                outcome = self._feature_engine(payout).resolve_base_round(
                    STOPS, [STOPS] * 10
                )
                self.assertEqual(outcome["feature_events"][0]["result"]["payout_milli"], payout)
                self.assertEqual(outcome["feature_events"][0]["payout_awarded_milli"], payout)

    def test_feature_spin_cap_plus_one_is_rejected(self):
        with self.assertRaises(InvalidMathOutcome):
            self._feature_engine(SPIN_CAP_MILLI + 1).resolve_base_round(
                STOPS, [STOPS] * 10
            )

    def test_malformed_base_payout_values_are_rejected(self):
        for payout in (True, 1.0, "1", -1):
            with self.subTest(payout=payout), self.assertRaises(InvalidMathOutcome):
                self._base_engine(payout).resolve_base_round(STOPS, [])

    def test_malformed_feature_payout_values_are_rejected(self):
        for payout in (True, 1.0, "1", -1):
            with self.subTest(payout=payout), self.assertRaises(InvalidMathOutcome):
                self._feature_engine(payout).resolve_base_round(STOPS, [STOPS] * 10)

    def test_cumulative_feature_payout_is_independently_limited_by_round_cap(self):
        port = ScriptedMathPort(base_payout=100, feature_payout=900, trigger_feature=True)
        engine = GameEngine(port)
        engine.spin_cap_milli = SPIN_CAP_MILLI
        engine.round_cap_milli = 1_500

        outcome = engine.resolve_base_round(STOPS, [STOPS] * 10)

        self.assertEqual(outcome["total_payout_milli"], 1_500)
        self.assertTrue(outcome["round_cap_reached"])
        self.assertEqual(outcome["feature_events"][0]["payout_awarded_milli"], 900)
        self.assertEqual(outcome["feature_events"][1]["payout_awarded_milli"], 500)
        self.assertLessEqual(outcome["total_payout_milli"], engine.round_cap_milli)

    def test_base_initial_payout_above_round_cap_is_rejected_before_feature_loop(self):
        class TrackingPort(ScriptedMathPort):
            def __init__(self):
                super().__init__(base_payout=1_001, feature_payout=0, trigger_feature=True)
                self.feature_calls = 0

            def evaluate_stops(self, stops, mode):
                if mode == "FREE_SPINS":
                    self.feature_calls += 1
                return super().evaluate_stops(stops, mode)

        port = TrackingPort()
        engine = GameEngine(port)
        engine.spin_cap_milli = 2_000
        engine.round_cap_milli = 1_000

        with self.assertRaises(InvalidMathOutcome):
            engine.resolve_base_round(STOPS, [STOPS] * 10)
        self.assertEqual(port.feature_calls, 0)


if __name__ == "__main__":
    unittest.main()
