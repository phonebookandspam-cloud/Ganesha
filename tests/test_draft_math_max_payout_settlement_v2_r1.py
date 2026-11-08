"""Exhaustively-derived Draft-005 BASE maximum carried through guarded Wallet.

This is explicitly Draft-only evidence, not a canonical or Provider payout claim.
"""
import tempfile
import unittest
from pathlib import Path

from ganesha.game.engine import GameEngine
from ganesha.game.math_port import DraftMathPort
from ganesha.math.rng import HmacStopGenerator
from ganesha.rgs.standard_startup_v1 import create_guarded_round_service
from ganesha.wallet.ledger import WalletLedger


class DraftMathMaxPayoutSettlementV2R1Tests(unittest.TestCase):
    def test_draft_base_maximum_10088_738x_reaches_guarded_wallet_once(self):
        # Found by exhaustive enumeration of all 13**5 Draft stop vectors:
        # BASE exact-3 Scatter maximum = 88.738x; FEATURE maximum = 1,000x.
        base_stops = (12, 4, 4, 5, 6)
        feature_max_stops = (0, 0, 4, 0, 5)
        feature_stops = [feature_max_stops] * 10
        expected_total_milli = 10_088_738

        with tempfile.TemporaryDirectory() as tmp:
            ledger = WalletLedger(Path(tmp) / "wallet.sqlite3")
            ledger.create_account("draft-max-account", "USD", 100_000)
            service = create_guarded_round_service(
                ledger,
                stop_generator=HmacStopGenerator(b"draft-max-settlement-key-material-0000"),
                game_engine=GameEngine(DraftMathPort()),
                test_mode=True,
                allow_test_vectors=True,
            )
            result = service.play_round(
                "draft-max-account", "draft-max-round", "draft-max-operation", 1_000,
                "BASE", internal_stop_vectors=[base_stops] + feature_stops,
            )

            self.assertEqual(result["outcome"]["total_payout_milli"], expected_total_milli)
            self.assertEqual(result["outcome"]["base_result"]["payout_milli"], 88_738)
            self.assertEqual(len(result["outcome"]["feature_events"]), 10)
            self.assertTrue(all(item["result"]["payout_milli"] == 1_000_000
                                for item in result["outcome"]["feature_events"]))
            snapshot = ledger.round_snapshot("draft-max-round")
            self.assertEqual(snapshot["round"]["status"], "SETTLED")
            self.assertEqual(snapshot["round"]["payout_minor"], expected_total_milli)
            self.assertEqual(ledger.balance("draft-max-account")["balance_minor"],
                             100_000 - 1_000 + expected_total_milli)
            self.assertEqual(len(service.ledger.financial_evidence_v2("draft-max-round")), 11)
            self.assertEqual(len(service.ledger.public_financial_evidence_v2("draft-max-round")), 11)
            self.assertTrue(ledger.reconcile_round("draft-max-round")["ok"])


if __name__ == "__main__":
    unittest.main()
