"""Focused regression for a lost commit_outcome response after v2 is durable.

The existing fault matrix covers hard process exit at this boundary. This test
covers the distinct caller-visible case where the full guarded commit returns,
then its response is lost before RoundService receives it.
"""
import tempfile
import unittest
from pathlib import Path

from ganesha.demo.game_fixture import PresentationFixtureMathPort
from ganesha.game.engine import GameEngine
from ganesha.math.rng import HmacStopGenerator
from ganesha.rgs.standard_startup_v1 import create_guarded_round_service
from ganesha.wallet.ledger import WalletLedger


class CommitOutcomeResponseLossV2R1Tests(unittest.TestCase):
    def test_lost_commit_outcome_response_after_v2_durable_recovers_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "wallet.sqlite3"
            ledger = WalletLedger(db_path)
            ledger.create_account("commit-response-loss-account", "USD", 100_000)
            generator = HmacStopGenerator(b"commit-outcome-response-loss-v2-key")
            service = create_guarded_round_service(
                ledger,
                stop_generator=generator,
                game_engine=GameEngine(PresentationFixtureMathPort()),
                test_mode=True,
                allow_test_vectors=True,
            )
            round_id = "commit-outcome-response-loss-round"
            vectors = [(0,) * 5] + [(index % 13,) * 5 for index in range(10)]
            guarded = service.ledger
            original_commit = guarded.commit_outcome
            observed = {}

            def commit_then_lose_response(target_round_id, outcome, payout_minor, fencing_token):
                result = original_commit(target_round_id, outcome, payout_minor, fencing_token)
                # Returning from the real adapter proves its v1 outcome and v2
                # sidecar commits completed before the simulated response loss.
                observed["v2"] = guarded.financial_evidence_v2(target_round_id)
                observed["v1"] = ledger.round_events(target_round_id)
                raise ConnectionError("simulated commit_outcome response loss after v2 durable")

            guarded.commit_outcome = commit_then_lose_response
            with self.assertRaisesRegex(ConnectionError, "after v2 durable"):
                service.play_round(
                    "commit-response-loss-account", round_id,
                    "commit-response-loss-operation", 1_000, "BASE",
                    internal_stop_vectors=vectors,
                )

            self.assertEqual(len(observed["v2"]), 11)
            self.assertEqual(len(observed["v1"]), 16)
            self.assertEqual(ledger.round_snapshot(round_id)["round"]["status"], "OUTCOME_COMMITTED")
            self.assertEqual(ledger.balance("commit-response-loss-account")["balance_minor"], 99_000)

            reopened = WalletLedger(db_path)
            recovery = create_guarded_round_service(
                reopened,
                stop_generator=HmacStopGenerator(b"commit-outcome-response-loss-v2-key"),
                game_engine=GameEngine(PresentationFixtureMathPort()),
                test_mode=True,
                allow_test_vectors=True,
            )
            first = recovery.recover_round(round_id, "commit-response-loss-account")
            second = recovery.recover_round(round_id, "commit-response-loss-account")

            self.assertEqual(first["status"], "SETTLED")
            self.assertEqual(second["status"], "SETTLED")
            self.assertEqual(reopened.balance("commit-response-loss-account")["balance_minor"], 100_500)
            self.assertEqual(reopened.round_events(round_id)[:len(observed["v1"])], observed["v1"])
            self.assertEqual(reopened.journal_for_round(round_id), ledger.journal_for_round(round_id))
            self.assertEqual(len(reopened.journal_for_round(round_id)), 2)
            self.assertEqual(len(recovery.ledger.financial_evidence_v2(round_id)), 11)
            self.assertTrue(reopened.reconcile_round(round_id)["ok"])


if __name__ == "__main__":
    unittest.main()
