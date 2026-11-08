import unittest

from ganesha.game.engine import GameEngine
from ganesha.game.presentation import build_presentation_events, replay_events


class ZeroFeatureFixtureMathPort:
    authority_status = "TEST_FIXTURE_ONLY"
    version = "zero-feature-presentation-fixture-r2"

    def evaluate_stops(self, stops, mode):
        if mode != "BASE":
            raise AssertionError("zero-feature fixture must not request Free Spins")
        board = [
            ["A", "SCATTER_LOTUS", "K"],
            ["MOUSE", "A", "K"],
            ["K", "ELEPHANT", "A"],
            ["A", "CHAKRA", "MOUSE"],
            ["A", "K", "MODAK"],
        ]
        return {
            "mode": "BASE",
            "board": board,
            "display_board": board,
            "raw_payout_milli": 1000,
            "payout_milli": 1000,
            "wild_multiplier": 1,
            "expanded_wild_reels": [],
            "max_win_capped": False,
            "free_spins_awarded": 0,
            "scatter_count": 1,
            "jackpot_triggered": False,
        }

    def award_free_spins(self, scatter_count, retrigger=False):
        if retrigger or scatter_count not in (0, 1, 2):
            raise AssertionError("zero-feature fixture does not support retriggers or trigger Scatter counts")
        return 0


class ZeroFeaturePresentationTests(unittest.TestCase):
    def test_zero_free_spins_completes_without_feature_events(self):
        engine = GameEngine(math_port=ZeroFeatureFixtureMathPort())
        outcome = engine.resolve_base_round((0, 0, 0, 0, 0), [])

        events = build_presentation_events("zero-feature-round", outcome)
        state = replay_events("zero-feature-round", events)

        event_types = [event["event_type"] for event in events]
        self.assertEqual(state["status"], "COMPLETED")
        self.assertEqual(state["classification"], "NON_FINANCIAL_PRESENTATION_ONLY")
        self.assertEqual(state["feature_initial_spins"], 0)
        self.assertEqual(state["feature_spins_played"], 0)
        self.assertEqual(state["feature_spins_remaining"], 0)
        self.assertEqual(state["total_payout_milli"], 1000)
        self.assertEqual(event_types.count("FEATURE_STARTED"), 0)
        self.assertEqual(event_types.count("FEATURE_REEL_STOPPED"), 0)
        self.assertEqual(event_types.count("FEATURE_SPIN_RESOLVED"), 0)
        self.assertEqual(event_types[-1], "ROUND_PRESENTATION_COMPLETED")


if __name__ == "__main__":
    unittest.main()
