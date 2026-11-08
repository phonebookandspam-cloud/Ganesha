"""Recovery must reject a corrupt partial v2 prefix before appending its suffix."""
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
from ganesha.wallet.settlement_boundary_v2_r2 import SettlementBoundaryV2Error


class FinancialEvidenceCorruptPrefixNoAppendV2R1Tests(unittest.TestCase):
    def test_recovery_rejects_tampered_partial_prefix_before_appending_suffix(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "wallet.sqlite3"
            ledger = WalletLedger(db_path)
            ledger.create_account("corrupt-prefix-account", "USD", 100_000)
            key = b"corrupt-partial-prefix-no-append-v2-key"
            service = create_guarded_round_service(
                ledger,
                stop_generator=HmacStopGenerator(key),
                game_engine=GameEngine(PresentationFixtureMathPort()),
                test_mode=True,
                allow_test_vectors=True,
            )
            guarded = service.ledger
            round_id = "corrupt-partial-prefix-round"

            def persist_prefix_then_interrupt(target_round_id):
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
                raise RuntimeError("injected interruption after valid partial prefix")

            guarded._ensure_v2_evidence = persist_prefix_then_interrupt
            vectors = [(0,) * 5] + [(index % 13,) * 5 for index in range(10)]
            with self.assertRaisesRegex(RuntimeError, "valid partial prefix"):
                service.play_round(
                    "corrupt-prefix-account", round_id,
                    "corrupt-partial-prefix-operation", 1_000, "BASE",
                    internal_stop_vectors=vectors,
                )

            with sqlite_connect(db_path) as db:
                # Deliberately bypass DB triggers to model offline DB-owner tampering.
                db.execute("DROP TRIGGER IF EXISTS round_financial_evidence_v2_no_update")
                db.execute(
                    "UPDATE round_financial_evidence_v2 SET event_id=? WHERE round_id=? AND sequence=1",
                    ("tampered-prefix-event-id", round_id),
                )
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
            with self.assertRaisesRegex(SettlementBoundaryV2Error, "conflicts with committed outcome"):
                recovery.recover_round(round_id, "corrupt-prefix-account")

            with sqlite_connect(db_path) as db:
                after = db.execute(
                    "SELECT round_id,sequence,event_id,event_type,schema_version,event_json,event_hash,source_ledger_event_hash "
                    "FROM round_financial_evidence_v2 WHERE round_id=? ORDER BY sequence",
                    (round_id,),
                ).fetchall()
            self.assertEqual(after, before)
            self.assertEqual(len(after), 1)
            self.assertEqual(reopened.round_snapshot(round_id)["round"]["status"], "OUTCOME_COMMITTED")
            self.assertEqual(reopened.balance("corrupt-prefix-account")["balance_minor"], 99_000)
            journal = reopened.journal_for_round(round_id)
            self.assertEqual(len(journal), 1)
            self.assertEqual(journal[0]["entry_type"], "BET_DEBIT")


if __name__ == "__main__":
    unittest.main()
