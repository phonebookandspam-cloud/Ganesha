"""Integration tests for GuardedWalletLedger at the RoundService commit boundary."""
import tempfile
import json
import hashlib
import sqlite3
from sqlite_test_support import connect as sqlite_connect
import unittest
from pathlib import Path

from ganesha.demo.game_fixture import PresentationFixtureMathPort
from ganesha.game.engine import GameEngine
from ganesha.math.rng import HmacStopGenerator
from ganesha.rgs.service import RoundService
from ganesha.rgs.standard_startup_v1 import _approved_engine
from ganesha.wallet.ledger import WalletLedger
from ganesha.wallet.settlement_boundary_v2_r2 import (
    GuardedWalletLedger,
    SettlementBoundaryV2Error,
    create_guarded_server,
)


class _MathPort:
    authority_status = "TEST_FIXTURE_ONLY"
    version = "settlement-boundary-test-v1"

    def __init__(self, payout):
        self.payout = payout

    def evaluate_stops(self, stops, mode):
        return {
            "mode": mode,
            "payout_milli": self.payout,
            "raw_payout_milli": self.payout,
            "wild_multiplier": 1,
            "expanded_wild_reels": [],
            "max_win_capped": False,
            "scatter_count": 0,
            "free_spins_awarded": 0,
        }

    def award_free_spins(self, scatter_count, retrigger=False):
        return 0


class SettlementBoundaryV2IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "wallet.sqlite3"
        self.raw_ledger = WalletLedger(self.db)
        self.raw_ledger.create_account("acct-boundary", "USD", 100_000)
        self.ledger = GuardedWalletLedger(self.raw_ledger)
        self.engine = GameEngine(PresentationFixtureMathPort())
        self.service = RoundService(
            self.ledger,
            game_engine=self.engine,
            allow_unapproved_math_for_tests=True,
            allow_test_vectors_for_tests=True,
        )

    def tearDown(self):
        self.temp.cleanup()

    def _vectors(self):
        return [(0,) * 5] + [(index % 13,) * 5 for index in range(10)]

    def test_round_service_uses_guarded_wallet_and_settles_exact_minor_amount(self):
        result = self.service.play_round(
            "acct-boundary", "round-boundary", "operation-boundary", 1_000,
            "BASE", internal_stop_vectors=self._vectors(),
        )
        self.assertEqual(result["state"]["status"], "ENDED")
        self.assertEqual(result["outcome"]["total_payout_milli"], 1_500)
        self.assertEqual(result["settlement"]["payout_minor"], 1_500)
        self.assertEqual(self.raw_ledger.balance("acct-boundary")["balance_minor"], 100_500)
        self.assertTrue(self.raw_ledger.reconcile_round("round-boundary")["ok"])
        # Evidence remains in the committed canonical outcome JSON.
        persisted = self.raw_ledger.round_snapshot("round-boundary")["outcome"]
        self.assertEqual(persisted["base_result"]["raw_payout_milli"], 1_000)
        self.assertEqual(persisted["feature_events"][0]["result"]["mode"], "FREE_SPINS")
        v1_events = self.raw_ledger.round_events("round-boundary")
        v2_events = self.ledger.financial_evidence_v2("round-boundary")
        public_v2 = self.ledger.public_financial_evidence_v2("round-boundary")
        self.assertTrue(all(event["schema_version"] == 1 for event in v1_events))
        self.assertEqual(len(v2_events), 11)
        self.assertEqual(len(public_v2), 11)
        self.assertEqual(v2_events[0]["payload"]["source_ledger_event_hash"],
                         next(event["event_hash"] for event in v1_events
                              if event["event_id"] == "round-boundary:outcome"))
        self.assertEqual(v2_events[1]["payload"]["source_ledger_event_hash"],
                         next(event["event_hash"] for event in v1_events
                              if event["event_id"] == "round-boundary:feature-spin-1"))
        self.assertEqual(public_v2[0]["source_event_hash"], v2_events[0]["payload"]["source_ledger_event_hash"])
        self.assertEqual(public_v2[1]["source_event_hash"], v2_events[1]["payload"]["source_ledger_event_hash"])
        self.assertTrue({"raw_payout_milli", "wild_multiplier", "expanded_wild_reels",
                         "max_win_capped"}.issubset(public_v2[1]["payload"]))
        self.assertNotIn("source_ledger_event_hash", public_v2[1]["payload"])
        self.assertNotIn("account_id", public_v2[1]["payload"])

    def test_rehashed_v2_sidecar_tampering_still_fails_outcome_reconciliation(self):
        self.service.play_round(
            "acct-boundary", "round-v2-rehash-tamper", "operation-v2-rehash-tamper", 1_000,
            "BASE", internal_stop_vectors=self._vectors(),
        )
        with sqlite_connect(self.db) as db:
            # Model offline database-owner tampering by explicitly removing
            # the local append-only trigger before mutating stored evidence.
            db.execute("DROP TRIGGER IF EXISTS round_financial_evidence_v2_no_update")
            rows = db.execute(
                "SELECT sequence,event_json FROM round_financial_evidence_v2 "
                "WHERE round_id=? ORDER BY sequence", ("round-v2-rehash-tamper",),
            ).fetchall()
            previous = "0" * 64
            for sequence, encoded in rows:
                event = json.loads(encoded)
                if sequence == 1:
                    payload = event["payload"]
                    payload["raw_payout_milli"] += 1
                    payload["payout_milli"] += 1
                    payload["base_payout_milli"] += 1
                    payload["total_payout_milli"] += 1
                    payload["payout_minor"] += 1
                event["previous_hash"] = previous
                unhashed = {key: value for key, value in event.items() if key != "event_hash"}
                event["event_hash"] = hashlib.sha256(
                    json.dumps(unhashed, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
                ).hexdigest()
                db.execute(
                    "UPDATE round_financial_evidence_v2 SET event_json=?,event_hash=? "
                    "WHERE round_id=? AND sequence=?",
                    (json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=True),
                     event["event_hash"], "round-v2-rehash-tamper", sequence),
                )
                previous = event["event_hash"]
        reopened = GuardedWalletLedger(WalletLedger(self.db))
        with self.assertRaisesRegex(SettlementBoundaryV2Error, "exactly reconcile"):
            reopened.financial_evidence_v2("round-v2-rehash-tamper")

    def test_v2_outcome_committed_carries_base_evidence_and_source_ledger_hash(self):
        self.service.play_round(
            "acct-boundary", "round-v2-outcome-contract", "operation-v2-outcome-contract", 1_000,
            "BASE", internal_stop_vectors=self._vectors(),
        )
        source = next(event for event in self.raw_ledger.round_events("round-v2-outcome-contract")
                      if event["event_type"] == "OUTCOME_COMMITTED")
        evidence = self.ledger.financial_evidence_v2("round-v2-outcome-contract")
        public = self.ledger.public_financial_evidence_v2("round-v2-outcome-contract")
        outcome_event = evidence[0]
        payload = outcome_event["payload"]
        self.assertEqual(outcome_event["event_type"], "OUTCOME_COMMITTED")
        self.assertEqual(payload["source_ledger_event_hash"], source["event_hash"])
        self.assertEqual(public[0]["source_event_hash"], source["event_hash"])
        self.assertEqual(payload["base_payout_milli"], 1_000)
        self.assertEqual(payload["feature_payout_milli"], 500)
        self.assertEqual(payload["total_payout_milli"], 1_500)
        self.assertEqual(payload["payout_minor"], 1_500)
        self.assertTrue({"raw_payout_milli", "wild_multiplier", "expanded_wild_reels",
                         "max_win_capped"}.issubset(public[0]["payload"]))
        self.assertNotIn("outcome_sha256", public[0]["payload"])
        self.assertNotIn("engine_version", public[0]["payload"])

    def test_v2_evidence_survives_sqlite_reopen_and_identical_retry(self):
        args = ("acct-boundary", "round-retry", "operation-retry", 1_000, "BASE")
        first = self.service.play_round(*args, internal_stop_vectors=self._vectors())
        balance_after_first = self.raw_ledger.balance("acct-boundary")["balance_minor"]
        second = self.service.play_round(*args, internal_stop_vectors=self._vectors())
        self.assertEqual(second["settlement"], first["settlement"])
        self.assertEqual(self.raw_ledger.balance("acct-boundary")["balance_minor"], balance_after_first)

        reopened = GuardedWalletLedger(WalletLedger(self.db))
        self.assertEqual(len(reopened.financial_evidence_v2("round-retry")), 11)
        self.assertEqual(len(reopened.public_financial_evidence_v2("round-retry")), 11)

    def test_v2_evidence_hash_tampering_is_detected_after_reopen(self):
        self.service.play_round(
            "acct-boundary", "round-tamper", "operation-tamper", 1_000,
            "BASE", internal_stop_vectors=self._vectors(),
        )
        with sqlite_connect(self.db) as db:
            # Model offline database-owner tampering outside the trigger guard.
            db.execute("DROP TRIGGER IF EXISTS round_financial_evidence_v2_no_update")
            row = db.execute(
                "SELECT event_json FROM round_financial_evidence_v2 "
                "WHERE round_id=? AND sequence=1", ("round-tamper",),
            ).fetchone()
            event = json.loads(row[0])
            event["payload"]["raw_payout_milli"] += 1
            db.execute(
                "UPDATE round_financial_evidence_v2 SET event_json=? WHERE round_id=? AND sequence=1",
                (json.dumps(event, sort_keys=True, separators=(",", ":")), "round-tamper"),
            )
        reopened = GuardedWalletLedger(WalletLedger(self.db))
        with self.assertRaises(ValueError):
            reopened.financial_evidence_v2("round-tamper")

    def test_recovery_rebuilds_v2_evidence_after_commit_response_loss(self):
        original = self.ledger._ensure_v2_evidence
        calls = {"count": 0}

        def fail_once(round_id):
            calls["count"] += 1
            if calls["count"] == 1:
                raise RuntimeError("simulated process loss after Wallet outcome commit")
            return original(round_id)

        self.ledger._ensure_v2_evidence = fail_once
        with self.assertRaises(RuntimeError):
            self.service.play_round(
                "acct-boundary", "round-crash", "operation-crash", 1_000,
                "BASE", internal_stop_vectors=self._vectors(),
            )
        self.assertEqual(self.raw_ledger.round_snapshot("round-crash")["round"]["status"],
                         "OUTCOME_COMMITTED")
        self.assertEqual(self.raw_ledger.balance("acct-boundary")["balance_minor"], 99_000)

        reopened_ledger = GuardedWalletLedger(WalletLedger(self.db))
        recovered_service = RoundService(
            reopened_ledger,
            game_engine=GameEngine(PresentationFixtureMathPort()),
            allow_unapproved_math_for_tests=True,
            allow_test_vectors_for_tests=True,
        )
        recovered = recovered_service.recover_round("round-crash", "acct-boundary")
        self.assertEqual(recovered["status"], "SETTLED")
        self.assertEqual(self.raw_ledger.balance("acct-boundary")["balance_minor"], 100_500)
        self.assertEqual(len(reopened_ledger.financial_evidence_v2("round-crash")), 11)
        self.assertTrue(self.raw_ledger.reconcile_round("round-crash")["ok"])

    def test_settlement_response_loss_does_not_credit_twice_on_retry(self):
        original = self.raw_ledger.settle_round

        def commit_then_lose_response(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("simulated response loss after Wallet credit commit")

        self.raw_ledger.settle_round = commit_then_lose_response
        args = ("acct-boundary", "round-credit-loss", "operation-credit-loss", 1_000, "BASE")
        with self.assertRaises(RuntimeError):
            self.service.play_round(*args, internal_stop_vectors=self._vectors())
        self.assertEqual(self.raw_ledger.round_snapshot("round-credit-loss")["round"]["status"], "SETTLED")
        balance_after_commit = self.raw_ledger.balance("acct-boundary")["balance_minor"]
        self.assertEqual(balance_after_commit, 100_500)
        self.raw_ledger.settle_round = original

        retry = self.service.play_round(*args, internal_stop_vectors=self._vectors())
        self.assertEqual(retry["settlement"]["payout_minor"], 1_500)
        self.assertEqual(self.raw_ledger.balance("acct-boundary")["balance_minor"], balance_after_commit)
        self.assertEqual(len(self.ledger.financial_evidence_v2("round-credit-loss")), 11)
        self.assertTrue(self.raw_ledger.reconcile_round("round-credit-loss")["ok"])

    def test_guarded_rgs_exposes_authenticated_public_v2_projection(self):
        self.service.play_round(
            "acct-boundary", "round-http-v2", "operation-http-v2", 1_000,
            "BASE", internal_stop_vectors=self._vectors(),
        )
        session_id = "s" * 16
        server = create_guarded_server(
            "127.0.0.1", 0, self.raw_ledger,
            HmacStopGenerator(b"guarded-rgs-test-key-000000000000"),
            {session_id: {"account_id": "acct-boundary", "secret": b"x" * 32}},
            nonce_registry=object(),
            game_engine=_approved_engine(
                GameEngine(PresentationFixtureMathPort()), test_mode=True, canonical_math_approval=None,
            ),
            allow_unapproved_math_for_tests=True,
        )
        try:
            handler = object.__new__(server.RequestHandlerClass)
            captured = {}
            handler.path = "/api/v2/rounds/round-http-v2/financial-evidence"
            handler._authenticate = lambda method, body: "acct-boundary"
            handler._json = lambda status, value: captured.update(status=status, value=value)
            handler.do_GET()
            self.assertEqual(captured["status"], 200)
            self.assertEqual(captured["value"]["schema_version"], 2)
            self.assertEqual(len(captured["value"]["events"]), 11)
            feature_payload = captured["value"]["events"][1]["payload"]
            v1_feature_hash = next(
                event["event_hash"] for event in self.raw_ledger.round_events("round-http-v2")
                if event["event_id"] == "round-http-v2:feature-spin-1"
            )
            self.assertEqual(captured["value"]["events"][1]["source_event_hash"], v1_feature_hash)
            self.assertTrue({"raw_payout_milli", "wild_multiplier", "expanded_wild_reels",
                             "max_win_capped"}.issubset(feature_payload))
            self.assertNotIn("account_id", feature_payload)
            self.assertNotIn("rng_commitment", feature_payload)

            captured.clear()
            handler._authenticate = lambda method, body: "another-account"
            handler.do_GET()
            self.assertEqual(captured["status"], 404)

            captured.clear()
            handler._authenticate = lambda method, body: "acct-boundary"
            handler.path = "/api/v2/rounds/unknown-round/financial-evidence?view=public"
            handler.do_GET()
            self.assertEqual(captured["status"], 404)
        finally:
            server.server_close()

    def test_guarded_reference_server_refuses_non_loopback_binding(self):
        with self.assertRaisesRegex(ValueError, "loopback"):
            create_guarded_server(
                "0.0.0.0", 0, self.raw_ledger, HmacStopGenerator(b"guarded-rgs-test-key-000000000000"),
                {}, nonce_registry=object(),
            )

    def test_wallet_commit_rejects_spin_cap_plus_one_before_outcome_commit(self):
        engine = GameEngine(_MathPort(100))
        outcome = engine.resolve_base_round((0,) * 5, [])
        # Forge a Math result after the GameEngine boundary to prove the Wallet
        # independently rejects a cap violation before durable outcome commit.
        outcome["base_result"]["raw_payout_milli"] = 1_000_001
        outcome["base_result"]["payout_milli"] = 1_000_001
        outcome["base_result"]["max_win_capped"] = False
        outcome["total_payout_milli"] = 1_000_001
        outcome["round_cap_reached"] = False
        outcome["engine_version"] = self.service.engine_version
        self.raw_ledger.reserve_bet(
            "debit-overcap", "round-overcap", "acct-boundary", 1_000,
            "TEST:overcap", max_payout_minor=50_000_000,
            round_mode="BASE", base_bet_minor=1_000,
            engine_version=self.service.engine_version,
        )
        token = self.raw_ledger.claim_recovery_lease("round-overcap", "owner-overcap")
        with self.assertRaises(SettlementBoundaryV2Error):
            self.ledger.commit_outcome("round-overcap", outcome, 1_000_001, token)
        snapshot = self.raw_ledger.round_snapshot("round-overcap")
        self.assertEqual(snapshot["round"]["status"], "REFUNDED")
        self.assertIsNone(snapshot["outcome"])
        self.assertEqual(self.raw_ledger.balance("acct-boundary")["balance_minor"], 100_000)
        self.raw_ledger.release_recovery_lease("round-overcap", "owner-overcap", token)

    def test_wallet_commit_rejects_minor_unit_mismatch(self):
        outcome = GameEngine(_MathPort(100)).resolve_base_round((0,) * 5, [])
        outcome["engine_version"] = self.service.engine_version
        self.raw_ledger.reserve_bet(
            "debit-mismatch", "round-mismatch", "acct-boundary", 1_000,
            "TEST:mismatch", max_payout_minor=50_000_000,
            round_mode="BASE", base_bet_minor=1_000,
            engine_version=self.service.engine_version,
        )
        token = self.raw_ledger.claim_recovery_lease("round-mismatch", "owner-mismatch")
        with self.assertRaises(SettlementBoundaryV2Error):
            self.ledger.commit_outcome("round-mismatch", outcome, 99, token)
        self.assertEqual(self.raw_ledger.round_snapshot("round-mismatch")["round"]["status"], "REFUNDED")
        self.assertEqual(self.raw_ledger.balance("acct-boundary")["balance_minor"], 100_000)
        self.raw_ledger.release_recovery_lease("round-mismatch", "owner-mismatch", token)

    def test_bonus_buy_is_fail_closed(self):
        self.raw_ledger.reserve_bet(
            "debit-buy", "round-buy", "acct-boundary", 5_000,
            "TEST:buy", max_payout_minor=50_000_000,
            round_mode="MAGIC_BUY", base_bet_minor=1_000,
            engine_version=self.service.engine_version,
        )
        outcome = {"mode": "MAGIC_BUY", "engine_version": self.service.engine_version}
        token = self.raw_ledger.claim_recovery_lease("round-buy", "owner-buy")
        with self.assertRaises(SettlementBoundaryV2Error):
            self.ledger.commit_outcome("round-buy", outcome, 0, token)
        self.assertEqual(self.raw_ledger.round_snapshot("round-buy")["round"]["status"], "REFUNDED")
        self.raw_ledger.release_recovery_lease("round-buy", "owner-buy", token)

    def test_feature_wild_multiplier_mismatch_is_refunded_before_commit(self):
        outcome = self.engine.resolve_base_round((0,) * 5, self._vectors()[1:])
        outcome["engine_version"] = self.service.engine_version
        outcome["feature_events"][0]["result"]["wild_multiplier"] = 4
        self.raw_ledger.reserve_bet(
            "debit-wild", "round-wild", "acct-boundary", 1_000,
            "TEST:wild", max_payout_minor=50_000_000,
            round_mode="BASE", base_bet_minor=1_000,
            engine_version=self.service.engine_version,
        )
        token = self.raw_ledger.claim_recovery_lease("round-wild", "owner-wild")
        with self.assertRaises(SettlementBoundaryV2Error):
            self.ledger.commit_outcome("round-wild", outcome, 1_500, token)
        self.assertEqual(self.raw_ledger.round_snapshot("round-wild")["round"]["status"], "REFUNDED")
        self.assertEqual(self.raw_ledger.balance("acct-boundary")["balance_minor"], 100_000)
        self.raw_ledger.release_recovery_lease("round-wild", "owner-wild", token)

    def test_feature_expansion_without_raw_wild_is_refunded_before_commit(self):
        outcome = self.engine.resolve_base_round((0,) * 5, self._vectors()[1:])
        outcome["engine_version"] = self.service.engine_version
        outcome["feature_events"][0]["result"]["board"][2] = ["A", "K", "CHAKRA"]
        self.raw_ledger.reserve_bet(
            "debit-wild-board", "round-wild-board", "acct-boundary", 1_000,
            "TEST:wild-board", max_payout_minor=50_000_000,
            round_mode="BASE", base_bet_minor=1_000,
            engine_version=self.service.engine_version,
        )
        token = self.raw_ledger.claim_recovery_lease("round-wild-board", "owner-wild-board")
        with self.assertRaisesRegex(SettlementBoundaryV2Error, "raw Ganesha Wild"):
            self.ledger.commit_outcome("round-wild-board", outcome, 1_500, token)
        snapshot = self.raw_ledger.round_snapshot("round-wild-board")
        self.assertEqual(snapshot["round"]["status"], "REFUNDED")
        self.assertIsNone(snapshot["outcome"])
        self.assertEqual(self.raw_ledger.balance("acct-boundary")["balance_minor"], 100_000)
        self.raw_ledger.release_recovery_lease("round-wild-board", "owner-wild-board", token)

    def test_raw_times_multiplier_integer_overflow_is_refunded(self):
        outcome = GameEngine(_MathPort(0)).resolve_base_round((0,) * 5, [])
        outcome["base_result"].update({
            "raw_payout_milli": 1 << 63,
            "payout_milli": 1_000_000,
            "max_win_capped": True,
        })
        outcome["engine_version"] = self.service.engine_version
        self.raw_ledger.reserve_bet(
            "debit-overflow", "round-overflow", "acct-boundary", 1_000,
            "TEST:overflow", max_payout_minor=50_000_000,
            round_mode="BASE", base_bet_minor=1_000,
            engine_version=self.service.engine_version,
        )
        token = self.raw_ledger.claim_recovery_lease("round-overflow", "owner-overflow")
        with self.assertRaises(SettlementBoundaryV2Error):
            self.ledger.commit_outcome("round-overflow", outcome, 1_000_000, token)
        self.assertEqual(self.raw_ledger.round_snapshot("round-overflow")["round"]["status"], "REFUNDED")
        self.assertEqual(self.raw_ledger.balance("acct-boundary")["balance_minor"], 100_000)
        self.raw_ledger.release_recovery_lease("round-overflow", "owner-overflow", token)


if __name__ == "__main__":
    unittest.main()
