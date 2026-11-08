"""Additive fault-injection tests for v2 evidence metadata, round binding and atomic recovery.

These tests deliberately preserve the immutable v1 journal. They exercise only the
local SQLite guarded startup path; they are not distributed-database guarantees.
"""
import os
import json
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
from ganesha.rgs.service import RoundService
from ganesha.rgs.standard_startup_v1 import create_guarded_round_service
from ganesha.wallet.ledger import WalletLedger
from ganesha.wallet.settlement_boundary_v2_r2 import (
    GuardedWalletLedger,
    SettlementBoundaryV2Error,
)


class FinancialEvidenceV2FaultMatrixR1Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "wallet.sqlite3"
        self.raw = WalletLedger(self.db_path)
        self.raw.create_account("fault-matrix-acct", "USD", 100_000)
        self.generator = HmacStopGenerator(b"v2-fault-matrix-key-material-000000")
        self.engine = GameEngine(PresentationFixtureMathPort())
        self.guarded = create_guarded_round_service(
            self.raw, stop_generator=self.generator, game_engine=self.engine,
            test_mode=True, allow_test_vectors=True,
        )

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def _vectors():
        return [(0,) * 5] + [(index % 13,) * 5 for index in range(10)]

    def _play(self, suffix):
        round_id = "fault-round-" + suffix
        operation_id = "fault-op-" + suffix
        result = self.guarded.play_round(
            "fault-matrix-acct", round_id, operation_id, 1_000, "BASE",
            internal_stop_vectors=self._vectors(),
        )
        self.assertEqual(result["state"]["status"], "ENDED")
        self.assertEqual(result["settlement"]["payout_minor"], 1_500)
        return round_id

    def _run_crash_process(self, script, expected_exit):
        env = os.environ.copy()
        source_root = str(Path(__file__).resolve().parents[1] / "src")
        test_support_root = str(Path(__file__).resolve().parent)
        env["PYTHONPATH"] = source_root + os.pathsep + test_support_root + os.pathsep + env.get("PYTHONPATH", "")
        completed = subprocess.run(
            [sys.executable, "-c", script, str(self.db_path)],
            env=env, check=False, timeout=20, capture_output=True, text=True,
        )
        self.assertEqual(completed.returncode, expected_exit, completed.stderr)

    def _expire_crashed_lease(self, round_id):
        # A real process death cannot release its lease; wait is avoided by
        # explicitly expiring the abandoned worker lease as an operator would.
        with sqlite_connect(self.db_path) as db:
            db.execute("UPDATE recovery_leases SET expires_at=0 WHERE round_id=?", (round_id,))

    @staticmethod
    def _drop_sidecar_immutability_triggers(db):
        # Simulate offline DB-owner tampering, which is outside the protection
        # offered by in-database append-only triggers.
        for name in (
            "round_financial_evidence_v2_no_update",
            "round_financial_evidence_v2_no_delete",
            "round_financial_evidence_v2_no_replace",
        ):
            db.execute("DROP TRIGGER IF EXISTS " + name)

    def test_sidecar_rows_reject_update_delete_and_conflict_replace(self):
        round_id = self._play("append-only")
        reopened = GuardedWalletLedger(WalletLedger(self.db_path))
        with sqlite_connect(self.db_path) as db:
            original = db.execute(
                "SELECT round_id,sequence,event_id,event_type,schema_version,event_json,event_hash,source_ledger_event_hash "
                "FROM round_financial_evidence_v2 WHERE round_id=? AND sequence=1", (round_id,),
            ).fetchone()
            with self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
                db.execute(
                    "UPDATE round_financial_evidence_v2 SET event_id=? WHERE round_id=? AND sequence=1",
                    ("mutated", round_id),
                )
            with self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
                db.execute(
                    "DELETE FROM round_financial_evidence_v2 WHERE round_id=? AND sequence=1",
                    (round_id,),
                )
            with self.assertRaisesRegex(sqlite3.IntegrityError, "duplicate identity is immutable"):
                db.execute(
                    "INSERT OR REPLACE INTO round_financial_evidence_v2 "
                    "(round_id,sequence,event_id,event_type,schema_version,event_json,event_hash,source_ledger_event_hash) "
                    "VALUES(?,?,?,?,?,?,?,?)", original,
                )
            current = db.execute(
                "SELECT round_id,sequence,event_id,event_type,schema_version,event_json,event_hash,source_ledger_event_hash "
                "FROM round_financial_evidence_v2 WHERE round_id=? AND sequence=1", (round_id,),
            ).fetchone()
            self.assertEqual(current, original)
        self.assertEqual(len(reopened.financial_evidence_v2(round_id)), 11)

    def test_sidecar_source_hash_column_tampering_is_detected_after_reopen(self):
        round_id = self._play("source-column")
        with sqlite_connect(self.db_path) as db:
            self._drop_sidecar_immutability_triggers(db)
            db.execute(
                "UPDATE round_financial_evidence_v2 SET source_ledger_event_hash=? "
                "WHERE round_id=? AND sequence=2", ("f" * 64, round_id),
            )
        reopened = GuardedWalletLedger(WalletLedger(self.db_path))
        with self.assertRaisesRegex(SettlementBoundaryV2Error, "source event"):
            reopened.financial_evidence_v2(round_id)

    def test_sidecar_denormalized_metadata_columns_are_bound_to_canonical_event_json(self):
        round_id = self._play("metadata-columns")
        columns = {
            "event_id": "tampered-event-id",
            "event_type": "TAMPERED_EVENT_TYPE",
            "schema_version": 99,
            "event_hash": "e" * 64,
        }
        with sqlite_connect(self.db_path) as db:
            self._drop_sidecar_immutability_triggers(db)
            original = db.execute(
                "SELECT event_id,event_type,schema_version,event_hash "
                "FROM round_financial_evidence_v2 WHERE round_id=? AND sequence=1", (round_id,),
            ).fetchone()
            for column, bad_value in columns.items():
                db.execute(
                    "UPDATE round_financial_evidence_v2 SET %s=? WHERE round_id=? AND sequence=1" % column,
                    (bad_value, round_id),
                )
                db.commit()
                reopened = GuardedWalletLedger(WalletLedger(self.db_path))
                with self.subTest(column=column), self.assertRaises((SettlementBoundaryV2Error, ValueError)):
                    reopened.financial_evidence_v2(round_id)
                self._drop_sidecar_immutability_triggers(db)
                db.execute(
                    "UPDATE round_financial_evidence_v2 SET %s=? WHERE round_id=? AND sequence=1" % column,
                    (original[list(columns).index(column)], round_id),
                )
                db.commit()

    def test_missing_and_extra_duplicate_sidecar_rows_fail_closed(self):
        missing_round = self._play("missing-row")
        with sqlite_connect(self.db_path) as db:
            self._drop_sidecar_immutability_triggers(db)
            db.execute(
                "DELETE FROM round_financial_evidence_v2 WHERE round_id=? AND sequence=11",
                (missing_round,),
            )
        with self.assertRaisesRegex(SettlementBoundaryV2Error, "incomplete"):
            GuardedWalletLedger(WalletLedger(self.db_path)).financial_evidence_v2(missing_round)

        extra_round = self._play("extra-row")
        with sqlite_connect(self.db_path) as db:
            row = db.execute(
                "SELECT event_type,schema_version,event_json,event_hash,source_ledger_event_hash "
                "FROM round_financial_evidence_v2 WHERE round_id=? AND sequence=11", (extra_round,),
            ).fetchone()
            db.execute(
                "INSERT INTO round_financial_evidence_v2 "
                "(round_id,sequence,event_id,event_type,schema_version,event_json,event_hash,source_ledger_event_hash) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (extra_round, 12, extra_round + ":duplicate-copy", row[0], row[1], row[2], row[3], row[4]),
            )
        with self.assertRaisesRegex(SettlementBoundaryV2Error, "incomplete"):
            GuardedWalletLedger(WalletLedger(self.db_path)).financial_evidence_v2(extra_round)

    def test_outcome_json_digest_mismatch_against_immutable_v1_source_is_rejected(self):
        round_id = self._play("outcome-digest")
        with sqlite_connect(self.db_path) as db:
            encoded = db.execute("SELECT outcome_json FROM rounds WHERE round_id=?", (round_id,)).fetchone()[0]
            outcome = json.loads(encoded)
            outcome["total_payout_milli"] += 1
            db.execute(
                "UPDATE rounds SET outcome_json=? WHERE round_id=?",
                (json.dumps(outcome, sort_keys=True, separators=(",", ":")), round_id),
            )
        with self.assertRaisesRegex(SettlementBoundaryV2Error, "digest"):
            GuardedWalletLedger(WalletLedger(self.db_path)).financial_evidence_v2(round_id)

    def test_sidecar_sequence_reordering_is_detected_after_reopen(self):
        round_id = self._play("sequence-order")
        with sqlite_connect(self.db_path) as db:
            self._drop_sidecar_immutability_triggers(db)
            db.execute(
                "UPDATE round_financial_evidence_v2 SET sequence=12 "
                "WHERE round_id=? AND sequence=2", (round_id,),
            )
        reopened = GuardedWalletLedger(WalletLedger(self.db_path))
        with self.assertRaises((SettlementBoundaryV2Error, ValueError)):
            reopened.financial_evidence_v2(round_id)

    def test_sidecar_evidence_transplanted_to_another_round_is_rejected(self):
        source_round = self._play("transplant-source")
        target_round = self._play("transplant-target")
        with sqlite_connect(self.db_path) as db:
            self._drop_sidecar_immutability_triggers(db)
            # Vacate the target's first sequence while retaining its other rows.
            db.execute(
                "UPDATE round_financial_evidence_v2 SET sequence=99 "
                "WHERE round_id=? AND sequence=1", (target_round,),
            )
            db.execute(
                "UPDATE round_financial_evidence_v2 SET round_id=? "
                "WHERE round_id=? AND sequence=1", (target_round, source_round),
            )
        reopened = GuardedWalletLedger(WalletLedger(self.db_path))
        with self.assertRaises(SettlementBoundaryV2Error):
            reopened.financial_evidence_v2(target_round)
        with self.assertRaises(SettlementBoundaryV2Error):
            reopened.financial_evidence_v2(source_round)

    def test_partial_sidecar_insert_rolls_back_then_recovery_rebuilds_once(self):
        round_id = "fault-round-partial-insert"
        operation_id = "fault-op-partial-insert"
        with sqlite_connect(self.db_path) as db:
            db.execute("""CREATE TRIGGER fail_v2_second_insert
                BEFORE INSERT ON round_financial_evidence_v2
                WHEN NEW.round_id='fault-round-partial-insert' AND NEW.sequence=2
                BEGIN SELECT RAISE(ABORT, 'injected sidecar insert failure'); END""")

        with self.assertRaisesRegex(sqlite3.IntegrityError, "injected sidecar insert failure"):
            self.guarded.play_round(
                "fault-matrix-acct", round_id, operation_id, 1_000, "BASE",
                internal_stop_vectors=self._vectors(),
            )

        snapshot = self.raw.round_snapshot(round_id)
        self.assertEqual(snapshot["round"]["status"], "OUTCOME_COMMITTED")
        self.assertEqual(self.raw.balance("fault-matrix-acct")["balance_minor"], 99_000)
        original_v1 = self.raw.round_events(round_id)
        self.assertEqual(len(original_v1), 16)
        with sqlite_connect(self.db_path) as db:
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM round_financial_evidence_v2 WHERE round_id=?", (round_id,),
            ).fetchone()[0], 0, "sidecar insert transaction must roll back as a unit")
            db.execute("DROP TRIGGER fail_v2_second_insert")

        reopened = GuardedWalletLedger(WalletLedger(self.db_path))
        recovery_service = RoundService(
            reopened, game_engine=GameEngine(PresentationFixtureMathPort()),
            stop_generator=self.generator,
        )
        recovered = recovery_service.recover_round(round_id, "fault-matrix-acct")
        self.assertEqual(recovered["status"], "SETTLED")
        self.assertEqual(recovered["settlement"]["payout_minor"], 1_500)
        self.assertEqual(self.raw.balance("fault-matrix-acct")["balance_minor"], 100_500)
        recovered_v1 = self.raw.round_events(round_id)
        self.assertEqual(recovered_v1[:len(original_v1)], original_v1)
        self.assertEqual(
            [event["event_type"] for event in recovered_v1[len(original_v1):]],
            ["WIN_PRESENTED", "SETTLED", "END_ROUND"],
        )
        self.assertEqual(len(reopened.financial_evidence_v2(round_id)), 11)
        self.assertEqual(len(reopened.public_financial_evidence_v2(round_id)), 11)
        self.assertTrue(self.raw.reconcile_round(round_id)["ok"])
        replayed = recovery_service.recover_round(round_id, "fault-matrix-acct")
        self.assertEqual(replayed["status"], "SETTLED")
        self.assertEqual(self.raw.balance("fault-matrix-acct")["balance_minor"], 100_500)
        self.assertEqual(len(self.raw.journal_for_round(round_id)), 2)

    def test_process_exit_inside_v2_append_transaction_rolls_back_and_recovers(self):
        script = r"""
import os, sqlite3, sys
from sqlite_test_support import connect as sqlite_connect
from ganesha.demo.game_fixture import PresentationFixtureMathPort
from ganesha.game.engine import GameEngine
from ganesha.math.rng import HmacStopGenerator
from ganesha.rgs.standard_startup_v1 import create_guarded_round_service
from ganesha.wallet.ledger import WalletLedger

class CrashableLedger(WalletLedger):
    def _connect(self):
        db = super()._connect()
        db.create_function("crash_now", 0, lambda: os._exit(71))
        return db

ledger = CrashableLedger(sys.argv[1])
with sqlite_connect(sys.argv[1]) as db:
    db.execute('''CREATE TRIGGER crash_v2_second_insert
        BEFORE INSERT ON round_financial_evidence_v2
        WHEN NEW.round_id='fault-round-process-inside-v2' AND NEW.sequence=2
        BEGIN SELECT crash_now(); END''')
service = create_guarded_round_service(
    ledger, stop_generator=HmacStopGenerator(b"v2-fault-matrix-key-material-000000"),
    game_engine=GameEngine(PresentationFixtureMathPort()), test_mode=True, allow_test_vectors=True,
)
vectors = [(0,) * 5] + [(index % 13,) * 5 for index in range(10)]
service.play_round("fault-matrix-acct", "fault-round-process-inside-v2", "fault-op-process-inside-v2",
                   1000, "BASE", internal_stop_vectors=vectors)
"""
        self._run_crash_process(script, 71)
        round_id = "fault-round-process-inside-v2"
        self.assertEqual(self.raw.round_snapshot(round_id)["round"]["status"], "OUTCOME_COMMITTED")
        self.assertEqual(self.raw.balance("fault-matrix-acct")["balance_minor"], 99_000)
        self._expire_crashed_lease(round_id)
        with sqlite_connect(self.db_path) as db:
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM round_financial_evidence_v2 WHERE round_id=?", (round_id,),
            ).fetchone()[0], 0)
            db.execute("DROP TRIGGER crash_v2_second_insert")
        reopened = GuardedWalletLedger(WalletLedger(self.db_path))
        recovery = RoundService(reopened, game_engine=GameEngine(PresentationFixtureMathPort()),
                                stop_generator=self.generator)
        result = recovery.recover_round(round_id, "fault-matrix-acct")
        self.assertEqual(result["status"], "SETTLED")
        self.assertEqual(self.raw.balance("fault-matrix-acct")["balance_minor"], 100_500)
        self.assertEqual(len(reopened.financial_evidence_v2(round_id)), 11)
        self.assertTrue(self.raw.reconcile_round(round_id)["ok"])

    def test_process_exit_after_v1_outcome_commit_before_v2_append_recovers(self):
        script = r"""
import os, sys
from ganesha.demo.game_fixture import PresentationFixtureMathPort
from ganesha.game.engine import GameEngine
from ganesha.math.rng import HmacStopGenerator
from ganesha.rgs.standard_startup_v1 import create_guarded_round_service
from ganesha.wallet.ledger import WalletLedger
ledger = WalletLedger(sys.argv[1])
service = create_guarded_round_service(
    ledger, stop_generator=HmacStopGenerator(b"v2-fault-matrix-key-material-000000"),
    game_engine=GameEngine(PresentationFixtureMathPort()), test_mode=True, allow_test_vectors=True,
)
service.ledger._ensure_v2_evidence = lambda _round_id: os._exit(74)
vectors = [(0,) * 5] + [(index % 13,) * 5 for index in range(10)]
service.play_round("fault-matrix-acct", "fault-round-v1-before-v2", "fault-op-v1-before-v2",
                   1000, "BASE", internal_stop_vectors=vectors)
"""
        self._run_crash_process(script, 74)
        round_id = "fault-round-v1-before-v2"
        self.assertEqual(self.raw.round_snapshot(round_id)["round"]["status"], "OUTCOME_COMMITTED")
        self.assertEqual(self.raw.balance("fault-matrix-acct")["balance_minor"], 99_000)
        self._expire_crashed_lease(round_id)
        with sqlite_connect(self.db_path) as db:
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM round_financial_evidence_v2 WHERE round_id=?", (round_id,),
            ).fetchone()[0], 0)
        reopened = GuardedWalletLedger(WalletLedger(self.db_path))
        recovery = RoundService(reopened, game_engine=GameEngine(PresentationFixtureMathPort()),
                                stop_generator=self.generator)
        result = recovery.recover_round(round_id, "fault-matrix-acct")
        self.assertEqual(result["status"], "SETTLED")
        self.assertEqual(len(reopened.financial_evidence_v2(round_id)), 11)
        self.assertEqual(self.raw.balance("fault-matrix-acct")["balance_minor"], 100_500)
        self.assertEqual(len(self.raw.journal_for_round(round_id)), 2)
        self.assertTrue(self.raw.reconcile_round(round_id)["ok"])

    def test_process_exit_after_v2_commit_before_commit_outcome_returns_recovers_once(self):
        script = r"""
import os, sys
from ganesha.demo.game_fixture import PresentationFixtureMathPort
from ganesha.game.engine import GameEngine
from ganesha.math.rng import HmacStopGenerator
from ganesha.rgs.standard_startup_v1 import create_guarded_round_service
from ganesha.wallet.ledger import WalletLedger
ledger = WalletLedger(sys.argv[1])
service = create_guarded_round_service(
    ledger, stop_generator=HmacStopGenerator(b"v2-fault-matrix-key-material-000000"),
    game_engine=GameEngine(PresentationFixtureMathPort()), test_mode=True, allow_test_vectors=True,
)
guarded = service.ledger
original = guarded._ensure_v2_evidence
def commit_then_exit(round_id):
    original(round_id)
    os._exit(72)
guarded._ensure_v2_evidence = commit_then_exit
vectors = [(0,) * 5] + [(index % 13,) * 5 for index in range(10)]
service.play_round("fault-matrix-acct", "fault-round-after-v2-commit", "fault-op-after-v2-commit",
                   1000, "BASE", internal_stop_vectors=vectors)
"""
        self._run_crash_process(script, 72)
        round_id = "fault-round-after-v2-commit"
        self.assertEqual(self.raw.round_snapshot(round_id)["round"]["status"], "OUTCOME_COMMITTED")
        self.assertEqual(self.raw.balance("fault-matrix-acct")["balance_minor"], 99_000)
        self._expire_crashed_lease(round_id)
        reopened = GuardedWalletLedger(WalletLedger(self.db_path))
        self.assertEqual(len(reopened.financial_evidence_v2(round_id)), 11)
        recovery = RoundService(reopened, game_engine=GameEngine(PresentationFixtureMathPort()),
                                stop_generator=self.generator)
        result = recovery.recover_round(round_id, "fault-matrix-acct")
        self.assertEqual(result["status"], "SETTLED")
        self.assertEqual(self.raw.balance("fault-matrix-acct")["balance_minor"], 100_500)
        replay = recovery.recover_round(round_id, "fault-matrix-acct")
        self.assertEqual(replay["status"], "SETTLED")
        self.assertEqual(self.raw.balance("fault-matrix-acct")["balance_minor"], 100_500)
        self.assertEqual(len(self.raw.journal_for_round(round_id)), 2)
        self.assertTrue(self.raw.reconcile_round(round_id)["ok"])

    def test_recovery_appends_only_missing_suffix_to_valid_partial_sidecar_prefix(self):
        script = r"""
import os, sys
from ganesha.demo.game_fixture import PresentationFixtureMathPort
from ganesha.game.engine import GameEngine
from ganesha.math.rng import HmacStopGenerator
from ganesha.rgs.standard_startup_v1 import create_guarded_round_service
from ganesha.wallet.ledger import WalletLedger
ledger = WalletLedger(sys.argv[1])
service = create_guarded_round_service(
    ledger, stop_generator=HmacStopGenerator(b"v2-fault-matrix-key-material-000000"),
    game_engine=GameEngine(PresentationFixtureMathPort()), test_mode=True, allow_test_vectors=True,
)
guarded = service.ledger
def persist_prefix_then_exit(round_id):
    snapshot = ledger.round_snapshot(round_id)
    desired = guarded._build_v2_events(round_id, snapshot["outcome"], snapshot["events"],
                                       snapshot["round"], guarded.round_cap_milli)
    event = desired[0]
    import json
    encoded = json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    with ledger._connect() as db:
        db.execute("INSERT INTO round_financial_evidence_v2 "
                   "(round_id,sequence,event_id,event_type,schema_version,event_json,event_hash,source_ledger_event_hash) "
                   "VALUES(?,?,?,?,?,?,?,?)",
                   (round_id, event["sequence"], event["event_id"], event["event_type"],
                    event["schema_version"], encoded, event["event_hash"],
                    event["payload"]["source_ledger_event_hash"]))
        db.commit()
    os._exit(73)
guarded._ensure_v2_evidence = persist_prefix_then_exit
vectors = [(0,) * 5] + [(index % 13,) * 5 for index in range(10)]
service.play_round("fault-matrix-acct", "fault-round-partial-prefix", "fault-op-partial-prefix",
                   1000, "BASE", internal_stop_vectors=vectors)
"""
        self._run_crash_process(script, 73)
        round_id = "fault-round-partial-prefix"
        self.assertEqual(self.raw.round_snapshot(round_id)["round"]["status"], "OUTCOME_COMMITTED")
        self._expire_crashed_lease(round_id)
        with sqlite_connect(self.db_path) as db:
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM round_financial_evidence_v2 WHERE round_id=?", (round_id,),
            ).fetchone()[0], 1)
        reopened = GuardedWalletLedger(WalletLedger(self.db_path))
        recovery = RoundService(reopened, game_engine=GameEngine(PresentationFixtureMathPort()),
                                stop_generator=self.generator)
        result = recovery.recover_round(round_id, "fault-matrix-acct")
        self.assertEqual(result["status"], "SETTLED")
        self.assertEqual(len(reopened.financial_evidence_v2(round_id)), 11)
        self.assertEqual(self.raw.balance("fault-matrix-acct")["balance_minor"], 100_500)
        self.assertEqual(len(self.raw.journal_for_round(round_id)), 2)
        self.assertTrue(self.raw.reconcile_round(round_id)["ok"])


if __name__ == "__main__":
    unittest.main()
