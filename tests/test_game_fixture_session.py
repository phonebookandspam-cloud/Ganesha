import unittest
from concurrent.futures import ThreadPoolExecutor

from ganesha.demo.game_fixture import GameFixtureSessionError, GameFixtureSessionStore


class GameFixtureSessionTests(unittest.TestCase):
    def setUp(self):
        self.store = GameFixtureSessionStore()
        self.session = self.store.create()
        self.session_id = self.session["session_id"]

    def test_fixture_runs_game_engine_base_four_scatter_twelve_free_spins_and_presentation_events(self):
        result = self.store.play(self.session_id, "fixture-request-1")
        self.assertEqual(result["classification"], "TEST_FIXTURE_ONLY")
        self.assertFalse(result["financial_effects"])
        self.assertEqual(result["state"]["status"], "COMPLETED")
        self.assertEqual(result["state"]["feature_initial_spins"], 12)
        self.assertEqual(result["state"]["feature_spins_played"], 12)
        self.assertEqual(result["state"]["feature_spins_remaining"], 0)
        types = [event["event_type"] for event in result["events"]]
        self.assertEqual(types[0], "ROUND_PRESENTATION_STARTED")
        self.assertEqual(types.count("BASE_REEL_STOPPED"), 5)
        self.assertEqual(types.count("FEATURE_REEL_STOPPED"), 60)
        self.assertEqual(types.count("WILD_EXPANSION_APPLIED"), 12)
        self.assertEqual(types.count("MULTIPLIER_APPLIED"), 12)
        self.assertEqual(types.count("FEATURE_SPIN_RESOLVED"), 12)
        self.assertEqual(types[-1], "ROUND_PRESENTATION_COMPLETED")
        self.assertEqual(result["state"]["event_count"], len(result["events"]))

    def test_same_request_id_is_idempotent_and_different_request_is_rejected(self):
        first = self.store.play(self.session_id, "same-request")
        second = self.store.play(self.session_id, "same-request")
        self.assertEqual(first, second)
        with self.assertRaisesRegex(GameFixtureSessionError, "already completed"):
            self.store.play(self.session_id, "different-request")

    def test_concurrent_duplicate_requests_create_one_identical_round(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.store.play(self.session_id, "parallel-request"), range(8)))
        self.assertTrue(all(item == results[0] for item in results))
        self.assertEqual(len(self.store.snapshot(self.session_id)["events"]), 106)

    def test_snapshot_before_and_after_play_is_deterministic(self):
        before = self.store.snapshot(self.session_id)
        self.assertEqual(before["events"], [])
        self.assertEqual(before["state"]["status"], "CREATED")
        self.store.play(self.session_id, "snapshot-request")
        after = self.store.snapshot(self.session_id)
        self.assertEqual(after["state"]["status"], "COMPLETED")
        self.assertEqual(after["events"], self.store.play(self.session_id, "snapshot-request")["events"])

    def test_invalid_request_and_unknown_session_fail_closed(self):
        with self.assertRaises(GameFixtureSessionError):
            self.store.play(self.session_id, "")
        with self.assertRaises(GameFixtureSessionError):
            self.store.play("f" * 32, "request")


if __name__ == "__main__":
    unittest.main()
