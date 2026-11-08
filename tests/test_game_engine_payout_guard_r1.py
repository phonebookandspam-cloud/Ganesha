"""Standalone pre-Wallet payout guard tests; not wired into RoundService."""
import unittest

from ganesha.demo.game_fixture import PresentationFixtureMathPort
from ganesha.game.engine import GameEngine
from ganesha.game.engine_payout_guard_r1 import EnginePayoutGuardError, validate_outcome_for_settlement


class _Port:
    def __init__(self, base, feature=0, trigger=False):
        self.base, self.feature, self.trigger = base, feature, trigger
    def evaluate_stops(self, stops, mode):
        if mode == "BASE":
            return {"mode": mode, "payout_milli": self.base, "raw_payout_milli": self.base,
                    "wild_multiplier": 1, "expanded_wild_reels": [], "max_win_capped": False,
                    "scatter_count": 3 if self.trigger else 0,
                    "free_spins_awarded": 10 if self.trigger else 0}
        return {"mode": mode, "payout_milli": self.feature, "raw_payout_milli": self.feature,
                "wild_multiplier": 1, "expanded_wild_reels": [], "max_win_capped": False,
                "scatter_count": 0, "jackpot_triggered": False}
    def award_free_spins(self, scatter_count, retrigger=False):
        return 0 if retrigger else (10 if scatter_count == 3 else 0)


def _forged_outcome(base_payout=0, *, initial_spins=0, feature_payout=None,
                    scatter_count=None, total_payout=None, round_cap_reached=False):
    if scatter_count is None:
        scatter_count = 3 if initial_spins == 10 else 4 if initial_spins == 12 else 0
    base = {
        "mode": "BASE", "raw_payout_milli": base_payout,
        "payout_milli": base_payout, "wild_multiplier": 1,
        "expanded_wild_reels": [], "max_win_capped": False,
        "free_spins_awarded": initial_spins, "scatter_count": scatter_count,
    }
    events = []
    if feature_payout is not None:
        feature = {
            "mode": "FREE_SPINS", "raw_payout_milli": feature_payout,
            "payout_milli": feature_payout, "wild_multiplier": 1,
            "expanded_wild_reels": [], "max_win_capped": False,
            "jackpot_triggered": False,
        }
        events.append({
            "spin_number": 1, "retrigger_requested": 0,
            "retrigger_awarded": 0, "result": feature,
            "payout_awarded_milli": feature_payout,
            "round_payout_after_milli": base_payout + feature_payout,
            "round_cap_applied": False, "jackpot_triggered": False,
        })
    return {
        "mode": "BASE", "base_result": base,
        "initial_free_spins": initial_spins,
        "free_spins_awarded_total": initial_spins,
        "free_spins_played": len(events), "feature_events": events,
        "total_payout_milli": (base_payout + (feature_payout or 0)
                               if total_payout is None else total_payout),
        "round_cap_reached": round_cap_reached,
    }


class EnginePayoutGuardTests(unittest.TestCase):
    def test_valid_fixture_outcome_passes_guard(self):
        outcome = GameEngine(PresentationFixtureMathPort()).resolve_base_round(
            (0,) * 5, [(1,) * 5 for _ in range(10)]
        )
        result = validate_outcome_for_settlement(outcome)
        self.assertEqual(result["spins_checked"], 11)
        self.assertEqual(result["total_payout_milli"], outcome["total_payout_milli"])

    def test_four_scatter_twelve_spin_outcome_passes_guard(self):
        class FourScatterPort:
            def evaluate_stops(self, stops, mode):
                if mode == "BASE":
                    return {"mode": mode, "payout_milli": 0, "raw_payout_milli": 0,
                            "wild_multiplier": 1, "expanded_wild_reels": [],
                            "max_win_capped": False, "scatter_count": 4,
                            "free_spins_awarded": 12}
                return {"mode": mode, "payout_milli": 0, "raw_payout_milli": 0,
                        "wild_multiplier": 1, "expanded_wild_reels": [],
                        "max_win_capped": False, "scatter_count": 0,
                        "jackpot_triggered": False}
            def award_free_spins(self, scatter_count, retrigger=False): return 0

        outcome = GameEngine(FourScatterPort()).resolve_base_round(
            (0,) * 5, [(index,) * 5 for index in range(12)]
        )
        result = validate_outcome_for_settlement(outcome)
        self.assertEqual(result["spins_checked"], 13)
        self.assertEqual(outcome["initial_free_spins"], 12)

    def test_base_spin_over_cap_is_rejected(self):
        outcome = _forged_outcome(base_payout=1_000_001)
        with self.assertRaises(EnginePayoutGuardError):
            validate_outcome_for_settlement(outcome)

    def test_feature_spin_over_cap_is_rejected(self):
        outcome = _forged_outcome(initial_spins=10, feature_payout=1_000_001)
        with self.assertRaises(EnginePayoutGuardError):
            validate_outcome_for_settlement(outcome)

    def test_base_payout_over_round_cap_is_rejected_before_feature_resolution(self):
        outcome = _forged_outcome(base_payout=1_000_001, total_payout=1_000_001)
        with self.assertRaises(EnginePayoutGuardError):
            validate_outcome_for_settlement(outcome, spin_cap_milli=2_000_000, round_cap_milli=1_000_000)

    def test_round_cap_increment_is_independent_from_spin_cap(self):
        engine = GameEngine(_Port(100, 900, True))
        engine.round_cap_milli = 1_000
        outcome = engine.resolve_base_round((0,) * 5, [(index,) * 5 for index in range(12)])
        result = validate_outcome_for_settlement(outcome, round_cap_milli=1_000)
        self.assertEqual(result["total_payout_milli"], 1_000)
        self.assertTrue(result["round_cap_reached"])
        self.assertEqual(result["spins_checked"], 2)

    def test_tampered_round_total_is_rejected(self):
        outcome = GameEngine(PresentationFixtureMathPort()).resolve_base_round(
            (0,) * 5, [(1,) * 5 for _ in range(10)]
        )
        outcome["total_payout_milli"] += 1
        with self.assertRaises(EnginePayoutGuardError):
            validate_outcome_for_settlement(outcome)

    def test_feature_expansion_requires_a_raw_wild_on_each_expanded_reel(self):
        outcome = GameEngine(math_port=PresentationFixtureMathPort()).resolve_base_round(
            (0,) * 5, [(1,) * 5 for _ in range(10)]
        )
        outcome["feature_events"][0]["result"]["board"][2] = ["A", "K", "CHAKRA"]
        with self.assertRaisesRegex(EnginePayoutGuardError, "raw Ganesha Wild"):
            validate_outcome_for_settlement(outcome)

    def test_feature_expansion_display_must_match_raw_board_and_indices(self):
        outcome = GameEngine(math_port=PresentationFixtureMathPort()).resolve_base_round(
            (0,) * 5, [(1,) * 5 for _ in range(10)]
        )
        outcome["feature_events"][0]["result"]["display_board"][2] = ["A", "A", "A"]
        with self.assertRaisesRegex(EnginePayoutGuardError, "display board"):
            validate_outcome_for_settlement(outcome)


if __name__ == "__main__":
    unittest.main()
