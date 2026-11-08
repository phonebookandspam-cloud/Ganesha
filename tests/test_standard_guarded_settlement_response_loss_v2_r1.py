"""Standard guarded-startup retry after a committed Wallet response is lost.

Local SQLite only. This test verifies idempotent readback after the Wallet credit
has durably committed but the caller receives no response.
"""
import tempfile
import unittest
from pathlib import Path

from ganesha.demo.game_fixture import PresentationFixtureMathPort
from ganesha.game.engine import GameEngine
from ganesha.math.rng import HmacStopGenerator
from ganesha.rgs.standard_startup_v1 import create_guarded_round_service
from ganesha.wallet.ledger import WalletLedger


class StandardGuardedSettlementResponseLossV2R1Tests(unittest.TestCase):
    def test_committed_settlement_with_lost_response_reopens_and_recovers_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "wallet.sqlite3"
            ledger = WalletLedger(db_path)
            ledger.create_account("response-loss-account", "USD", 100_000)
            service = create_guarded_round_service(
                ledger,
                stop_generator=HmacStopGenerator(b"standard-response-loss-key-material-000"),
                game_engine=GameEngine(PresentationFixtureMathPort()),
                test_mode=True,
                allow_test_vectors=True,
            )
            round_id = "standard-response-loss-round"
            vectors = [(0,) * 5] + [(index % 13,) * 5 for index in range(10)]
            original_settle = service.ledger.settle_round
            calls = {"count": 0}

            def commit_then_drop_response(operation_id, target_round_id, fencing_token):
                result = original_settle(operation_id, target_round_id, fencing_token)
                calls["count"] += 1
                if calls["count"] == 1:
                    raise ConnectionError("simulated response loss after durable Wallet commit")
                return result

            service.ledger.settle_round = commit_then_drop_response
            with self.assertRaisesRegex(ConnectionError, "response loss"):
                service.play_round(
                    "response-loss-account", round_id, "response-loss-operation", 1_000,
                    "BASE", internal_stop_vectors=vectors,
                )

            committed = ledger.round_snapshot(round_id)
            self.assertEqual(committed["round"]["status"], "SETTLED")
            self.assertEqual(ledger.balance("response-loss-account")["balance_minor"], 100_500)
            original_v1 = ledger.round_events(round_id)
            original_journal = ledger.journal_for_round(round_id)
            self.assertEqual(len(original_journal), 2)
            self.assertTrue(ledger.reconcile_round(round_id)["ok"])

            reopened = WalletLedger(db_path)
            recovery = create_guarded_round_service(
                reopened,
                stop_generator=HmacStopGenerator(b"standard-response-loss-key-material-000"),
                game_engine=GameEngine(PresentationFixtureMathPort()),
                test_mode=True,
                allow_test_vectors=True,
            )
            first = recovery.recover_round(round_id, "response-loss-account")
            second = recovery.recover_round(round_id, "response-loss-account")
            self.assertEqual(first["status"], "SETTLED")
            self.assertEqual(second["status"], "SETTLED")
            self.assertEqual(reopened.balance("response-loss-account")["balance_minor"], 100_500)
            self.assertEqual(reopened.round_events(round_id), original_v1)
            self.assertEqual(reopened.journal_for_round(round_id), original_journal)
            private_evidence = recovery.ledger.financial_evidence_v2(round_id)
            public_evidence = recovery.ledger.public_financial_evidence_v2(round_id)
            self.assertEqual(len(private_evidence), 11)
            self.assertEqual(len(public_evidence), 11)
            required_fields = {
                "raw_payout_milli", "wild_multiplier", "expanded_wild_reels",
                "max_win_capped", "payout_milli",
            }
            self.assertEqual(private_evidence[0]["event_type"], "OUTCOME_COMMITTED")
            self.assertEqual(sum(item["event_type"] == "FEATURE_SPIN_RESOLVED" for item in private_evidence), 10)
            for private_event, public_event in zip(private_evidence, public_evidence):
                self.assertTrue(required_fields.issubset(private_event["payload"]))
                self.assertTrue(required_fields.issubset(public_event["payload"]))
                self.assertEqual(public_event["source_event_hash"], private_event["payload"]["source_ledger_event_hash"])
                self.assertNotIn("account_id", public_event["payload"])
                self.assertNotIn("rng_commitment", public_event["payload"])
            round_row = reopened.round_snapshot(round_id)["round"]
            outcome = reopened.round_snapshot(round_id)["outcome"]
            expected_minor = (round_row["base_bet_minor"] * outcome["total_payout_milli"] + 500) // 1000
            self.assertEqual(round_row["payout_minor"], expected_minor)
            self.assertEqual(round_row["payout_minor"], 1_500)
            self.assertTrue(reopened.reconcile_round(round_id)["ok"])


if __name__ == "__main__":
    unittest.main()
