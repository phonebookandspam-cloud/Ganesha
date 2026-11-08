"""Focused concurrent local-SQLite smoke through the standard Guarded Factory."""
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ganesha.demo.game_fixture import PresentationFixtureMathPort
from ganesha.game.engine import GameEngine
from ganesha.math.rng import HmacStopGenerator
from ganesha.rgs.standard_startup_v1 import create_guarded_round_service
from ganesha.wallet.ledger import WalletLedger


class StandardGuardedConcurrentRoundsV2R1Tests(unittest.TestCase):
    def test_24_concurrent_rounds_settle_once_with_complete_public_evidence(self):
        workers = 24
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "wallet.sqlite3"
            ledger = WalletLedger(db_path)
            for index in range(workers):
                ledger.create_account("concurrent-account-%02d" % index, "USD", 100_000)
            service = create_guarded_round_service(
                ledger,
                stop_generator=HmacStopGenerator(b"standard-concurrent-round-key-000000"),
                game_engine=GameEngine(PresentationFixtureMathPort()),
                test_mode=True,
                allow_test_vectors=True,
            )

            def run(index):
                account = "concurrent-account-%02d" % index
                round_id = "concurrent-standard-round-%02d" % index
                operation = "concurrent-standard-op-%02d" % index
                vectors = [(0,) * 5] + [((spin + index) % 13,) * 5 for spin in range(10)]
                result = service.play_round(
                    account, round_id, operation, 1_000, "BASE",
                    internal_stop_vectors=vectors,
                )
                return account, round_id, result

            with ThreadPoolExecutor(max_workers=workers) as pool:
                results = list(pool.map(run, range(workers)))

            self.assertEqual(len(results), workers)
            for account, round_id, result in results:
                self.assertEqual(result["settlement"]["status"], "SETTLED")
                self.assertEqual(ledger.balance(account)["balance_minor"], 100_500)
                snapshot = ledger.round_snapshot(round_id)
                self.assertEqual(snapshot["round"]["status"], "SETTLED")
                self.assertEqual(len(ledger.journal_for_round(round_id)), 2)
                self.assertEqual(len(service.ledger.financial_evidence_v2(round_id)), 11)
                self.assertEqual(len(service.ledger.public_financial_evidence_v2(round_id)), 11)
                self.assertTrue(ledger.reconcile_round(round_id)["ok"])

            all_rounds = [ledger.round_snapshot("concurrent-standard-round-%02d" % i)["round"]
                          for i in range(workers)]
            self.assertEqual(sum(row["payout_minor"] for row in all_rounds), workers * 1_500)
            self.assertTrue(all(row["status"] == "SETTLED" for row in all_rounds))


if __name__ == "__main__":
    unittest.main()
