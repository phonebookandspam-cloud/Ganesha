"""Actual process-death recovery through the standard guarded startup factory.

This is a local SQLite test fixture only. It verifies that the standard factory
reconstructs the GuardedGameEngine + GuardedWalletLedger boundary for recovery;
it does not claim canonical Math or distributed recovery.
"""
import os
import sqlite3
from sqlite_test_support import connect as sqlite_connect
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ganesha.demo.game_fixture import PresentationFixtureMathPort
from ganesha.game.engine import GameEngine
from ganesha.math.rng import HmacStopGenerator
from ganesha.rgs.standard_startup_v1 import (
    GuardedGameEngine,
    create_guarded_round_service,
)
from ganesha.wallet.ledger import WalletLedger
from ganesha.wallet.settlement_boundary_v2_r2 import GuardedWalletLedger


class StandardGuardedRecoveryV2R1Tests(unittest.TestCase):
    def test_process_death_after_v1_outcome_commit_recovers_via_standard_factory_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "wallet.sqlite3"
            raw = WalletLedger(db_path)
            raw.create_account("standard-recovery-acct", "USD", 100_000)
            round_id = "standard-recovery-after-outcome"
            operation_id = "standard-recovery-operation"
            source_root = str(Path(__file__).resolve().parents[1] / "src")
            child = r"""
import os, sys
from ganesha.demo.game_fixture import PresentationFixtureMathPort
from ganesha.game.engine import GameEngine
from ganesha.math.rng import HmacStopGenerator
from ganesha.rgs.standard_startup_v1 import create_guarded_round_service
from ganesha.wallet.ledger import WalletLedger

ledger = WalletLedger(sys.argv[1])
service = create_guarded_round_service(
    ledger,
    stop_generator=HmacStopGenerator(b"standard-guarded-recovery-key-000000"),
    game_engine=GameEngine(PresentationFixtureMathPort()),
    test_mode=True,
    allow_test_vectors=True,
)
service.ledger._ensure_v2_evidence = lambda _round_id: os._exit(77)
vectors = [(0,) * 5] + [(index % 13,) * 5 for index in range(10)]
service.play_round(
    "standard-recovery-acct",
    "standard-recovery-after-outcome",
    "standard-recovery-operation",
    1000,
    "BASE",
    internal_stop_vectors=vectors,
)
"""
            env = os.environ.copy()
            env["PYTHONPATH"] = source_root + os.pathsep + env.get("PYTHONPATH", "")
            crashed = subprocess.run(
                [sys.executable, "-c", child, str(db_path)],
                env=env,
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            self.assertEqual(crashed.returncode, 77, crashed.stderr)

            snapshot = raw.round_snapshot(round_id)
            self.assertEqual(snapshot["round"]["status"], "OUTCOME_COMMITTED")
            self.assertEqual(raw.balance("standard-recovery-acct")["balance_minor"], 99_000)
            original_v1 = raw.round_events(round_id)
            with sqlite_connect(db_path) as db:
                self.assertEqual(
                    db.execute(
                        "SELECT COUNT(*) FROM round_financial_evidence_v2 WHERE round_id=?",
                        (round_id,),
                    ).fetchone()[0],
                    0,
                )
                db.execute(
                    "UPDATE recovery_leases SET expires_at=0 WHERE round_id=?",
                    (round_id,),
                )

            recovery = create_guarded_round_service(
                WalletLedger(db_path),
                stop_generator=HmacStopGenerator(b"standard-guarded-recovery-key-000000"),
                game_engine=GameEngine(PresentationFixtureMathPort()),
                test_mode=True,
                allow_test_vectors=True,
            )
            self.assertIsInstance(recovery.game_engine, GuardedGameEngine)
            self.assertIsInstance(recovery.ledger, GuardedWalletLedger)

            recovered = recovery.recover_round(round_id, "standard-recovery-acct")
            self.assertEqual(recovered["status"], "SETTLED")
            self.assertEqual(recovered["settlement"]["payout_minor"], 1_500)
            self.assertEqual(raw.balance("standard-recovery-acct")["balance_minor"], 100_500)
            recovered_v1 = raw.round_events(round_id)
            self.assertEqual(recovered_v1[:len(original_v1)], original_v1)
            self.assertEqual(
                [event["event_type"] for event in recovered_v1[len(original_v1):]],
                ["WIN_PRESENTED", "SETTLED", "END_ROUND"],
            )
            self.assertEqual(len(recovery.ledger.financial_evidence_v2(round_id)), 11)
            self.assertEqual(len(recovery.ledger.public_financial_evidence_v2(round_id)), 11)
            self.assertEqual(len(raw.journal_for_round(round_id)), 2)
            self.assertTrue(raw.reconcile_round(round_id)["ok"])

            replayed = recovery.recover_round(round_id, "standard-recovery-acct")
            self.assertEqual(replayed["status"], "SETTLED")
            self.assertEqual(raw.balance("standard-recovery-acct")["balance_minor"], 100_500)
            self.assertEqual(len(raw.journal_for_round(round_id)), 2)
            self.assertTrue(raw.reconcile_round(round_id)["ok"])


if __name__ == "__main__":
    unittest.main()
