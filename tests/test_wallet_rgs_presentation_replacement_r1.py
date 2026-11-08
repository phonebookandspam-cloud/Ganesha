"""Current-contract replacement for stale Wallet/RGS presentation projections."""
import tempfile
import unittest
from pathlib import Path

from ganesha.game.engine import GameEngine
from ganesha.game.math_port import DraftMathPort
from ganesha.game.presentation import (
    PRESENTATION_CLASSIFICATION,
    build_presentation_events,
    replay_events,
)
from ganesha.rgs.service import RoundService
from ganesha.wallet.ledger import WalletLedger
from ganesha.wallet.settlement_boundary_v2_r2 import GuardedWalletLedger


class CurrentWalletPresentationReplacementTests(unittest.TestCase):
    def test_draft_maximum_local_path_uses_current_presentation_and_wallet_v2_contracts(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "wallet.sqlite3"
            raw_wallet = WalletLedger(database)
            raw_wallet.create_account("acct-draft", "USD", 20_000_000)
            guarded_wallet = GuardedWalletLedger(raw_wallet)
            service = RoundService(
                guarded_wallet,
                game_engine=GameEngine(math_port=DraftMathPort()),
                allow_unapproved_math_for_tests=True,
                allow_test_vectors_for_tests=True,
            )
            result = service.play_round(
                "acct-draft", "round-draft-max", "op-draft-max", 1_000,
                "BASE", internal_stop_vectors=[(12, 4, 4, 5, 6)] + [(0, 0, 4, 0, 5)] * 10,
            )
            outcome = result["outcome"]
            self.assertEqual(outcome["base_result"]["payout_milli"], 88_738)
            self.assertEqual(outcome["free_spins_played"], 10)
            self.assertEqual(outcome["total_payout_milli"], 10_088_738)

            presentation = build_presentation_events("round-draft-max", outcome)
            state = replay_events("round-draft-max", presentation)
            self.assertEqual(state["classification"], PRESENTATION_CLASSIFICATION)
            self.assertEqual(state["status"], "COMPLETED")
            self.assertEqual(state["total_payout_milli"], outcome["total_payout_milli"])

            v1_events = raw_wallet.round_events("round-draft-max")
            v2_events = guarded_wallet.financial_evidence_v2("round-draft-max")
            public_v2 = guarded_wallet.public_financial_evidence_v2("round-draft-max")
            self.assertTrue(all(event["schema_version"] == 1 for event in v1_events))
            self.assertEqual(len(v2_events), 11)
            self.assertEqual(len(public_v2), 11)
            self.assertTrue(all(event["payload"]["raw_payout_milli"] >= 0 for event in v2_events))
            self.assertEqual(result["settlement"]["payout_minor"], 10_088_738)
            self.assertEqual(raw_wallet.balance("acct-draft")["balance_minor"],
                             20_000_000 - 1_000 + 10_088_738)
            self.assertTrue(raw_wallet.reconcile_round("round-draft-max")["ok"])


if __name__ == "__main__":
    unittest.main()
