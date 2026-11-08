"""Same-round recovery lease competition through two independent guarded services.

This is a local SQLite regression. It proves one lease owner can settle a
committed round while a concurrent recovery claimant is rejected; it is not a
multi-host distributed-database guarantee.
"""
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ganesha.demo.game_fixture import PresentationFixtureMathPort
from ganesha.game.engine import GameEngine
from ganesha.math.rng import HmacStopGenerator
from ganesha.rgs.standard_startup_v1 import create_guarded_round_service
from ganesha.wallet.ledger import RoundLeaseBusy, WalletLedger


KEY = b"same-round-recovery-lease-key-000000"


class SameRoundRecoveryLeaseCompetitionTests(unittest.TestCase):
    def test_two_recovery_workers_cannot_settle_same_round_concurrently(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "wallet.sqlite3"
            initial_ledger = WalletLedger(db_path)
            initial_ledger.create_account("lease-race-account", "USD", 100_000)
            initial = create_guarded_round_service(
                initial_ledger,
                stop_generator=HmacStopGenerator(KEY),
                game_engine=GameEngine(PresentationFixtureMathPort()),
                test_mode=True,
                allow_test_vectors=True,
            )

            # Leave a fully evidenced OUTCOME_COMMITTED round for recovery.
            initial.ledger.settle_round = lambda *_args, **_kwargs: (_ for _ in ()).throw(
                RuntimeError("injected failure before settlement")
            )
            vectors = [(0,) * 5] + [(index % 13,) * 5 for index in range(10)]
            with self.assertRaisesRegex(RuntimeError, "before settlement"):
                initial.play_round(
                    "lease-race-account", "same-round-lease-race",
                    "same-round-lease-operation", 1_000, "BASE",
                    internal_stop_vectors=vectors,
                )
            pending = initial_ledger.round_snapshot("same-round-lease-race")
            self.assertEqual(pending["round"]["status"], "OUTCOME_COMMITTED")
            self.assertEqual(len(initial.ledger.financial_evidence_v2("same-round-lease-race")), 11)
            self.assertEqual(len(initial_ledger.journal_for_round("same-round-lease-race")), 1)

            services = [
                create_guarded_round_service(
                    WalletLedger(db_path),
                    stop_generator=HmacStopGenerator(KEY),
                    game_engine=GameEngine(PresentationFixtureMathPort()),
                    test_mode=True,
                    allow_test_vectors=True,
                )
                for _ in range(2)
            ]
            claim_barrier = threading.Barrier(2)
            winner_claimed = threading.Event()
            loser_rejected = threading.Event()
            allow_winner_to_finish = threading.Event()

            for service in services:
                original_claim = service.ledger.claim_recovery_lease
                def synchronized_claim(round_id, owner_id, _claim=original_claim):
                    claim_barrier.wait(timeout=5)
                    try:
                        token = _claim(round_id, owner_id)
                    except RoundLeaseBusy:
                        loser_rejected.set()
                        raise
                    winner_claimed.set()
                    return token
                service.ledger.claim_recovery_lease = synchronized_claim

                original_present = service.ledger.record_win_presented
                def hold_winner(round_id, fencing_token, _present=original_present):
                    result = _present(round_id, fencing_token)
                    if winner_claimed.is_set():
                        if not allow_winner_to_finish.wait(timeout=5):
                            raise TimeoutError("test did not release winning recovery worker")
                    return result
                service.ledger.record_win_presented = hold_winner

            def recover(service):
                try:
                    return ("SETTLED", service.recover_round(
                        "same-round-lease-race", "lease-race-account"
                    ))
                except RoundLeaseBusy as exc:
                    return ("REJECTED", str(exc))

            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(recover, service) for service in services]
                self.assertTrue(winner_claimed.wait(timeout=5), "no recovery worker acquired the lease")
                self.assertTrue(loser_rejected.wait(timeout=5), "competing recovery was not rejected")
                allow_winner_to_finish.set()
                results = [future.result(timeout=10) for future in futures]

            self.assertEqual(sorted(status for status, _ in results), ["REJECTED", "SETTLED"])
            final = initial_ledger.round_snapshot("same-round-lease-race")
            self.assertEqual(final["round"]["status"], "SETTLED")
            self.assertEqual(initial_ledger.balance("lease-race-account")["balance_minor"], 100_500)
            self.assertEqual(len(initial_ledger.journal_for_round("same-round-lease-race")), 2)
            self.assertEqual(len(services[0].ledger.financial_evidence_v2("same-round-lease-race")), 11)
            self.assertTrue(initial_ledger.reconcile_round("same-round-lease-race")["ok"])


if __name__ == "__main__":
    unittest.main()
