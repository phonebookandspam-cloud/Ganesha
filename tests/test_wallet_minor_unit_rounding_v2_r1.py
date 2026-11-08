"""Half-up milli-bet to Wallet minor-unit conversion through standard startup."""
import tempfile
import unittest
from pathlib import Path

from ganesha.game.engine import GameEngine
from ganesha.math.rng import HmacStopGenerator
from ganesha.rgs.standard_startup_v1 import create_guarded_round_service
from ganesha.wallet.ledger import WalletLedger


class RoundingMathPort:
    version = "minor-unit-rounding-test-v1"
    authority_status = "TEST_FIXTURE_ONLY"

    def __init__(self, payout_milli):
        self.payout_milli = payout_milli

    def evaluate_stops(self, stops, mode):
        board = [["A", "A", "A"] for _ in range(5)]
        result = {
            "mode": mode,
            "payout_milli": self.payout_milli,
            "raw_payout_milli": self.payout_milli,
            "wild_multiplier": 1,
            "expanded_wild_reels": [],
            "max_win_capped": False,
            "scatter_count": 0,
            "board": board,
            "display_board": board,
        }
        if mode == "BASE":
            result["free_spins_awarded"] = 0
        else:
            result["jackpot_triggered"] = False
        return result

    def award_free_spins(self, scatter_count, retrigger=False):
        return 0


class WalletMinorUnitRoundingV2R1Tests(unittest.TestCase):
    def test_half_up_minor_unit_rounding_499_500_999(self):
        cases = ((499, 0), (500, 1), (999, 1))
        with tempfile.TemporaryDirectory() as tmp:
            ledger = WalletLedger(Path(tmp) / "wallet.sqlite3")
            for index, (payout_milli, expected_minor) in enumerate(cases):
                account = "rounding-account-%d" % index
                ledger.create_account(account, "USD", 1_000)
                service = create_guarded_round_service(
                    ledger,
                    stop_generator=HmacStopGenerator(b"minor-rounding-test-key-material-00000"),
                    game_engine=GameEngine(RoundingMathPort(payout_milli)),
                    test_mode=True,
                    allow_test_vectors=True,
                )
                result = service.play_round(
                    account, "rounding-round-%d" % index, "rounding-operation-%d" % index,
                    1, "BASE", internal_stop_vectors=[(0, 0, 0, 0, 0)],
                )
                self.assertEqual(result["outcome"]["total_payout_milli"], payout_milli)
                snapshot = ledger.round_snapshot("rounding-round-%d" % index)
                self.assertEqual(snapshot["round"]["payout_minor"], expected_minor)
                self.assertEqual(ledger.balance(account)["balance_minor"], 1_000 - 1 + expected_minor)
                self.assertTrue(ledger.reconcile_round("rounding-round-%d" % index)["ok"])


if __name__ == "__main__":
    unittest.main()
