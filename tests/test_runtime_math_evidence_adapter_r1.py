import unittest

from ganesha.demo.runtime_math import LocalRuntimeMathPort
from ganesha.game.engine import GameEngine
from ganesha.game.presentation import build_presentation_events


class RuntimeMathEvidenceAdapterR1Tests(unittest.TestCase):
    def test_base_and_feature_emit_explicit_payout_wild_and_cap_evidence(self):
        port = LocalRuntimeMathPort()
        base = port.evaluate_stops([0] * 5, "BASE")
        feature = port.evaluate_stops([1] * 5, "FREE_SPINS")

        self.assertEqual(base["raw_payout_milli"], 1000)
        self.assertEqual(base["wild_multiplier"], 1)
        self.assertEqual(base["expanded_wild_reels"], [])
        self.assertIs(base["max_win_capped"], False)

        self.assertEqual(feature["raw_payout_milli"], 25)
        self.assertEqual(feature["wild_multiplier"], 2)
        self.assertEqual(feature["expanded_wild_reels"], [2])
        self.assertIs(feature["max_win_capped"], False)

    def test_runtime_math_port_satisfies_presentation_evidence_contract(self):
        outcome = GameEngine(LocalRuntimeMathPort()).resolve_base_round(
            [0] * 5, [[index] * 5 for index in range(10)]
        )
        events = build_presentation_events("runtime-math-evidence-r1", outcome)
        base_reveal = next(event["payload"] for event in events
                           if event["event_type"] == "BASE_OUTCOME_REVEALED")
        feature_reveals = [event["payload"] for event in events
                           if event["event_type"] == "FEATURE_SPIN_RESOLVED"]
        self.assertEqual(base_reveal["raw_payout_milli"], 1000)
        self.assertEqual(base_reveal["multiplier"], 1)
        self.assertIs(base_reveal["max_win_capped"], False)
        self.assertEqual(len(feature_reveals), 10)
        self.assertTrue(all(item["raw_payout_milli"] == 25 for item in feature_reveals))
        self.assertTrue(all(item["multiplier"] == 2 for item in feature_reveals))
        self.assertTrue(all(item["wild_reels"] == [2] for item in feature_reveals))
        self.assertTrue(all(item["max_win_capped"] is False for item in feature_reveals))


if __name__ == "__main__":
    unittest.main()
