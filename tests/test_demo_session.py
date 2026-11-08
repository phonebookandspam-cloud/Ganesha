import unittest
from concurrent.futures import ThreadPoolExecutor

from ganesha.demo.session import DemoSessionError, DemoSessionStore


class DemoSessionTests(unittest.TestCase):
    def setUp(self):
        self.store = DemoSessionStore()
        self.session = self.store.create()
        self.session_id = self.session["session_id"]

    def test_demo_spin_emits_ordered_scripted_reel_events_and_5x3_board(self):
        result = self.store.spin(self.session_id, "request-1")
        self.assertEqual(result["classification"], "SCRIPTED_VISUAL_FIXTURE")
        self.assertEqual([event["event_type"] for event in result["events"]],
                         ["DEMO_SPIN_STARTED"] + ["DEMO_REEL_STOPPED"] * 5
                         + ["DEMO_BOARD_REVEALED", "DEMO_PRESENTATION_COMPLETED"])
        board = result["events"][-2]["payload"]["board"]
        self.assertEqual(len(board), 5)
        self.assertTrue(all(len(reel) == 3 for reel in board))
        self.assertTrue(all(event["contract"] == "ganesha.demo.events" for event in result["events"]))

    def test_same_request_id_is_idempotent_and_does_not_append_events(self):
        first = self.store.spin(self.session_id, "same-request")
        second = self.store.spin(self.session_id, "same-request")
        self.assertEqual(first, second)
        self.assertEqual(self.store.snapshot(self.session_id)["spin_count"], 1)
        self.assertEqual(len(self.store.snapshot(self.session_id)["events"]), 8)

    def test_concurrent_duplicate_requests_produce_one_scripted_spin(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.store.spin(self.session_id, "concurrent-request"), range(8)))
        self.assertTrue(all(result == results[0] for result in results))
        self.assertEqual(self.store.snapshot(self.session_id)["spin_count"], 1)

    def test_request_validation_unknown_session_and_session_limit(self):
        with self.assertRaises(DemoSessionError):
            self.store.spin(self.session_id, "")
        with self.assertRaises(DemoSessionError):
            self.store.spin("f" * 32, "request")
        for index in range(100):
            self.store.spin(self.session_id, "request-%d" % index)
        with self.assertRaises(DemoSessionError):
            self.store.spin(self.session_id, "request-over-limit")


if __name__ == "__main__":
    unittest.main()
