import unittest

from ganesha.demo.game_fixture import (
    GameFixtureSessionStore,
    PresentationFixtureMathPort,
)


class GameFixtureEvidenceAdapterTests(unittest.TestCase):
    def test_base_and_feature_math_results_expose_explicit_payout_and_wild_evidence(self):
        port = PresentationFixtureMathPort()

        base = port.evaluate_stops((0, 0, 0, 0, 0), "BASE")
        self.assertEqual(base["raw_payout_milli"], 1000)
        self.assertEqual(base["wild_multiplier"], 1)
        self.assertEqual(base["expanded_wild_reels"], [])
        self.assertIs(base["max_win_capped"], False)

        feature = port.evaluate_stops((0, 0, 0, 0, 0), "FREE_SPINS")
        self.assertEqual(feature["raw_payout_milli"], 25)
        self.assertEqual(feature["wild_multiplier"], 2)
        self.assertEqual(feature["expanded_wild_reels"], [2])
        self.assertIs(feature["max_win_capped"], False)

    def test_session_presentation_events_preserve_base_and_feature_evidence(self):
        store = GameFixtureSessionStore()
        session = store.create()["session_id"]
        response = store.play(session, "fixture-evidence")

        base_event = next(
            event for event in response["events"]
            if event["event_type"] == "BASE_OUTCOME_REVEALED"
        )
        self.assertEqual(base_event["payload"]["raw_payout_milli"], 1000)
        self.assertEqual(base_event["payload"]["multiplier"], 1)
        self.assertEqual(base_event["payload"]["wild_reels"], [])
        self.assertIs(base_event["payload"]["max_win_capped"], False)

        feature_events = [
            event for event in response["events"]
            if event["event_type"] == "FEATURE_SPIN_RESOLVED"
        ]
        self.assertEqual(len(feature_events), 12)
        for event in feature_events:
            payload = event["payload"]
            self.assertEqual(payload["raw_payout_milli"], 25)
            self.assertEqual(payload["multiplier"], 2)
            self.assertEqual(payload["wild_reels"], [2])
            self.assertIs(payload["max_win_capped"], False)


if __name__ == "__main__":
    unittest.main()
