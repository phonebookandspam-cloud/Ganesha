"""Regression: v2 recovery appends after, but never rewrites, a valid prefix row."""
import json
import sqlite3
from sqlite_test_support import connect as sqlite_connect
import tempfile
import unittest
from pathlib import Path

from ganesha.demo.game_fixture import PresentationFixtureMathPort
from ganesha.game.engine import GameEngine
from ganesha.math.rng import HmacStopGenerator
from ganesha.rgs.standard_startup_v1 import create_guarded_round_service
from ganesha.wallet.ledger import WalletLedger


class FinancialEvidencePartialPrefixImmutabilityV2R1Tests(unittest.TestCase):
    def test_recovery_preserves_existing_partial_prefix_row_verbatim(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "wallet.sqlite3"
            ledger = WalletLedger(db_path)
            ledger.create_account("prefix-immutability-account", "USD", 100_000)
            key = b"partial-prefix-immutability-v2-key"
            service = create_guarded_round_service(
                ledger,
                stop_generator=HmacStopGenerator(key),
                game_engine=GameEngine(PresentationFixtureMathPort()),
                test_mode=True,
                allow_test_vectors=True,
            )
            guarded = service.ledger
            round_id = "partial-prefix-immutability-round"

            def persist_one_valid_event_then_fail(target_round_id):
                snapshot = ledger.round_snapshot(target_round_id)
                first = guarded._build_v2_events(
                    target_round_id, snapshot["outcome"], snapshot["events"],
                    snapshot["round"], guarded.round_cap_milli,
                )[0]
                encoded = json.dumps(first, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
                with ledger._connect() as db:
                    db.execute(
                        "INSERT INTO round_financial_evidence_v2 "
                        "(round_id,sequence,event_id,event_type,schema_version,event_json,event_hash,source_ledger_event_hash) "
                        "VALUES(?,?,?,?,?,?,?,?)",
                        (target_round_id, first["sequence"], first["event_id"], first["event_type"],
                         first["schema_version"], encoded, first["event_hash"],
                         first["payload"]["source_ledger_event_hash"]),
                    )
                    db.commit()
                raise RuntimeError("injected interruption after durable valid prefix")

            guarded._ensure_v2_evidence = persist_one_valid_event_then_fail
            vectors = [(0,) * 5] + [(index % 13,) * 5 for index in range(10)]
            with self.assertRaisesRegex(RuntimeError, "durable valid prefix"):
                service.play_round(
                    "prefix-immutability-account", round_id,
                    "partial-prefix-immutability-operation", 1_000, "BASE",
                    internal_stop_vectors=vectors,
                )

            with sqlite_connect(db_path) as db:
                before = db.execute(
                    "SELECT round_id,sequence,event_id,event_type,schema_version,event_json,event_hash,source_ledger_event_hash "
                    "FROM round_financial_evidence_v2 WHERE round_id=? ORDER BY sequence",
                    (round_id,),
                ).fetchall()
            self.assertEqual(len(before), 1)
            self.assertEqual(ledger.round_snapshot(round_id)["round"]["status"], "OUTCOME_COMMITTED")

            reopened = WalletLedger(db_path)
            recovery = create_guarded_round_service(
                reopened,
                stop_generator=HmacStopGenerator(key),
                game_engine=GameEngine(PresentationFixtureMathPort()),
                test_mode=True,
                allow_test_vectors=True,
            )
            result = recovery.recover_round(round_id, "prefix-immutability-account")
            self.assertEqual(result["status"], "SETTLED")

            with sqlite_connect(db_path) as db:
                after = db.execute(
                    "SELECT round_id,sequence,event_id,event_type,schema_version,event_json,event_hash,source_ledger_event_hash "
                    "FROM round_financial_evidence_v2 WHERE round_id=? ORDER BY sequence",
                    (round_id,),
                ).fetchall()
            self.assertEqual(after[:len(before)], before)
            self.assertEqual(len(after), 11)
            self.assertEqual(reopened.balance("prefix-immutability-account")["balance_minor"], 100_500)
            self.assertEqual(len(reopened.journal_for_round(round_id)), 2)
            self.assertTrue(reopened.reconcile_round(round_id)["ok"])


if __name__ == "__main__":
    unittest.main()
