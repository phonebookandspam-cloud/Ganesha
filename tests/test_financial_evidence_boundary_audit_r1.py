"""Regression checks for GameEngine payout caps and Wallet/RGS evidence boundaries.

Engine-level over-cap outcomes must fail before a feature or settlement can proceed.
The unguarded-Wallet probe remains as a negative control: standard startup must use
the guarded settlement adapter rather than treating WalletLedger alone as safe.
"""
import ast
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ganesha.game.engine import GameEngine, InvalidMathOutcome
from ganesha.rgs.service import RoundService
from ganesha.wallet.ledger import WalletLedger

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_FIELDS = {
    "raw_payout_milli", "wild_multiplier", "expanded_wild_reels", "max_win_capped"
}


class _OverCapPort:
    authority_status = "TEST_FIXTURE_ONLY"
    version = "over-cap-audit-v1"

    def __init__(self, base_payout, feature_payout=0):
        self.base_payout = base_payout
        self.feature_payout = feature_payout

    def evaluate_stops(self, stops, mode):
        payout = self.base_payout if mode == "BASE" else self.feature_payout
        result = {
            "mode": mode, "payout_milli": payout, "raw_payout_milli": payout,
            "wild_multiplier": 1, "expanded_wild_reels": [],
            "max_win_capped": False, "scatter_count": 3 if mode == "BASE" and self.feature_payout else 0,
        }
        if mode == "BASE":
            result["free_spins_awarded"] = 10 if self.feature_payout else 0
        else:
            result["jackpot_triggered"] = False
        return result

    def award_free_spins(self, scatter_count, retrigger=False):
        return 0 if retrigger else (10 if scatter_count == 3 else 0)


class _EvidencePort:
    authority_status = "TEST_FIXTURE_ONLY"
    version = "evidence-boundary-audit-v1"

    def evaluate_stops(self, stops, mode):
        if mode == "BASE":
            return {"mode": mode, "payout_milli": 100, "raw_payout_milli": 100,
                    "wild_multiplier": 1, "expanded_wild_reels": [],
                    "max_win_capped": False, "scatter_count": 3,
                    "free_spins_awarded": 10}
        return {"mode": mode, "payout_milli": 50, "raw_payout_milli": 25,
                "wild_multiplier": 2, "expanded_wild_reels": [2],
                "max_win_capped": False, "scatter_count": 0,
                "jackpot_triggered": False}

    def award_free_spins(self, scatter_count, retrigger=False):
        return 0 if retrigger else (10 if scatter_count == 3 else 0)


def _public_event_allowlist():
    tree = ast.parse((ROOT / "src/ganesha/rgs/http_api.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "public_payload_fields"
            for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError("public_payload_fields allowlist not found")


class GameEngineCapAudit(unittest.TestCase):
    def test_base_initial_payout_above_spin_cap_is_rejected(self):
        engine = GameEngine(_OverCapPort(1_000_001))
        with self.assertRaises(InvalidMathOutcome):
            engine.resolve_base_round((0, 0, 0, 0, 0), [])

    def test_each_feature_spin_above_spin_cap_is_rejected(self):
        engine = GameEngine(_OverCapPort(0, 1_000_001))
        with self.assertRaises(InvalidMathOutcome):
            engine.resolve_base_round(
                (0, 0, 0, 0, 0), [(index,) * 5 for index in range(10)]
            )

    def test_base_initial_payout_above_round_cap_is_rejected_before_feature_loop(self):
        engine = GameEngine(_OverCapPort(1_000_001, 0))
        engine.spin_cap_milli = 2_000_000
        engine.round_cap_milli = 1_000_000
        # Force the BASE result to award a feature while retaining the over-cap payout.
        class TriggeringPort(_OverCapPort):
            feature_calls = 0
            def evaluate_stops(self, stops, mode):
                if mode == "FREE_SPINS":
                    self.feature_calls += 1
                result = super().evaluate_stops(stops, mode)
                if mode == "BASE":
                    result["scatter_count"] = 3
                    result["free_spins_awarded"] = 10
                return result
        port = TriggeringPort(1_000_001, 0)
        engine = GameEngine(port)
        engine.spin_cap_milli = 2_000_000
        engine.round_cap_milli = 1_000_000
        with self.assertRaises(InvalidMathOutcome):
            engine.resolve_base_round((0,) * 5, [(index,) * 5 for index in range(10)])
        self.assertEqual(port.feature_calls, 0)

    def test_spin_cap_boundary_and_invalid_types_are_distinguished(self):
        for value in (-1, True, 1.0, "1"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                GameEngine._validated_spin_result(
                    {"mode": "BASE", "payout_milli": value, "scatter_count": 0,
                     "free_spins_awarded": 0}, "BASE"
                )
        exact = GameEngine._validated_spin_result(
            {"mode": "BASE", "payout_milli": 1_000_000, "scatter_count": 0,
             "free_spins_awarded": 0}, "BASE"
        )
        self.assertEqual(exact["payout_milli"], 1_000_000)
        with self.assertRaises(InvalidMathOutcome):
            GameEngine._validated_spin_result(
                {"mode": "BASE", "payout_milli": 1_000_001, "scatter_count": 0,
                 "free_spins_awarded": 0}, "BASE"
            )

    def test_wallet_rounds_with_engine_over_cap_are_refunded_before_settlement(self):
        for round_id, port, vectors in (
            ("base-overcap-wallet", _OverCapPort(1_000_001), []),
            ("feature-overcap-wallet", _OverCapPort(0, 1_000_001),
             [(index,) * 5 for index in range(10)]),
        ):
            with self.subTest(round_id=round_id), tempfile.TemporaryDirectory() as directory:
                ledger = WalletLedger(os.path.join(directory, "wallet.sqlite"))
                ledger.create_account("cap-player", "USD", 100_000)
                service = RoundService(
                    ledger, game_engine=GameEngine(port),
                    allow_unapproved_math_for_tests=True, allow_test_vectors_for_tests=True,
                )
                with self.assertRaises(InvalidMathOutcome):
                    service.play_round(
                        "cap-player", round_id, round_id + "-op", 1_000, "BASE",
                        internal_stop_vectors=[(0,) * 5] + vectors if vectors else [(0,) * 5],
                    )
                snapshot = ledger.round_snapshot(round_id)
                self.assertEqual(snapshot["round"]["status"], "REFUNDED")
                self.assertEqual(ledger.balance("cap-player")["balance_minor"], 100_000)
                self.assertTrue(ledger.reconcile_round(round_id)["ok"])


class WalletRgsEvidenceAudit(unittest.TestCase):
    def test_wallet_ledger_connection_context_closes_the_sqlite_handle(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = WalletLedger(os.path.join(directory, "connection-close.sqlite"))
            connection = None
            with ledger._connect() as db:
                connection = db
                db.execute("SELECT 1").fetchone()
            with self.assertRaisesRegex(sqlite3.ProgrammingError, "closed database"):
                connection.execute("SELECT 1")

    def test_outcome_json_keeps_evidence_but_financial_event_ledger_drops_it(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = WalletLedger(os.path.join(directory, "audit.sqlite"))
            ledger.create_account("audit-player", "USD", 100_000)
            service = RoundService(
                ledger, game_engine=GameEngine(_EvidencePort()),
                allow_unapproved_math_for_tests=True, allow_test_vectors_for_tests=True,
            )
            result = service.play_round(
                "audit-player", "audit-evidence-round", "audit-evidence-op", 1_000,
                "BASE", internal_stop_vectors=[(0, 0, 0, 0, 0)] + [(1,) * 5] * 10,
            )
            snapshot = ledger.round_snapshot("audit-evidence-round")
            outcome = snapshot["outcome"]
            self.assertTrue(EVIDENCE_FIELDS.issubset(outcome["base_result"]))
            self.assertTrue(EVIDENCE_FIELDS.issubset(outcome["feature_events"][0]["result"]))
            feature_events = [e for e in snapshot["events"] if e["event_type"] == "FEATURE_SPIN_RESOLVED"]
            self.assertEqual(len(feature_events), 10)
            self.assertTrue(all(not (EVIDENCE_FIELDS & set(e["payload"])) for e in feature_events))
            outcome_event = next(e for e in snapshot["events"] if e["event_type"] == "OUTCOME_COMMITTED")
            self.assertTrue(EVIDENCE_FIELDS.isdisjoint(outcome_event["payload"]))
            self.assertEqual(result["settlement"]["payout_minor"], 600)
            self.assertTrue(ledger.reconcile_round("audit-evidence-round")["ok"])

    def test_nonfinancial_presentation_projection_reconciles_base_and_feature_evidence(self):
        from ganesha.demo.game_fixture import PresentationFixtureMathPort
        from ganesha.game.presentation import build_presentation_events, replay_events
        with tempfile.TemporaryDirectory() as directory:
            ledger = WalletLedger(os.path.join(directory, "presentation.sqlite"))
            ledger.create_account("presentation-player", "USD", 100_000)
            service = RoundService(
                ledger, game_engine=GameEngine(PresentationFixtureMathPort()),
                allow_unapproved_math_for_tests=True, allow_test_vectors_for_tests=True,
            )
            result = service.play_round(
                "presentation-player", "presentation-evidence-round", "presentation-evidence-op",
                1_000, "BASE", internal_stop_vectors=[(0,) * 5] + [(1,) * 5] * 10,
            )
            events = build_presentation_events(
                "presentation-evidence-round", result["outcome"],
                classification="NON_FINANCIAL_PRESENTATION_ONLY",
            )
            state = replay_events(
                "presentation-evidence-round", events,
                classification="NON_FINANCIAL_PRESENTATION_ONLY",
            )
            base = next(e["payload"] for e in events if e["event_type"] == "BASE_OUTCOME_REVEALED")
            features = [e["payload"] for e in events if e["event_type"] == "FEATURE_SPIN_RESOLVED"]
            self.assertEqual(state["status"], "COMPLETED")
            self.assertEqual(base["raw_payout_milli"], result["outcome"]["base_result"]["raw_payout_milli"])
            self.assertEqual(base["multiplier"], result["outcome"]["base_result"]["wild_multiplier"])
            self.assertEqual(base["max_win_capped"], result["outcome"]["base_result"]["max_win_capped"])
            self.assertEqual(len(features), 10)
            for projected, item in zip(features, result["outcome"]["feature_events"]):
                source = item["result"]
                self.assertEqual(projected["raw_payout_milli"], source["raw_payout_milli"])
                self.assertEqual(projected["wild_reels"], source["expanded_wild_reels"])
                self.assertEqual(projected["multiplier"], source["wild_multiplier"])
                self.assertEqual(projected["max_win_capped"], source["max_win_capped"])
            self.assertEqual(state["total_payout_milli"], result["outcome"]["total_payout_milli"])

    def test_version_one_event_contract_rejects_evidence_field_extension(self):
        from ganesha.game.events import initial_state, make_event, apply_event
        state = initial_state("event-schema-audit")
        # Reach FEATURE_SPINS state through the actual event contract.
        sequence = [
            ("ROUND_OPENED", {"mode": "BASE"}),
            ("BET_RESERVED", {"account_id": "p", "currency": "USD", "debit_minor": 1, "operation_id": "d"}),
            ("RNG_COMMITTED", {"commitment": "TEST:" + "a" * 64, "generator_version": "test"}),
            ("FEATURE_STARTED", {"feature": "FREE_SPINS", "initial_spins": 1}),
        ]
        for index, (kind, payload) in enumerate(sequence, 1):
            event = make_event(state, "event-%d" % index, kind, payload)
            state = apply_event(state, event)
        payload = {"spin_number": 1, "stops": [0] * 5, "payout_milli": 1,
                   "retrigger_awarded": 0, "remaining_spins": 0,
                   "raw_payout_milli": 1, "wild_multiplier": 1,
                   "expanded_wild_reels": [], "max_win_capped": False}
        event = make_event(state, "event-5", "FEATURE_SPIN_RESOLVED", payload)
        with self.assertRaisesRegex(ValueError, "payload schema mismatch"):
            apply_event(state, event)

    def test_public_rgs_projection_omits_all_four_evidence_fields(self):
        allowlist = _public_event_allowlist()
        self.assertTrue(EVIDENCE_FIELDS.isdisjoint(set(allowlist["FEATURE_SPIN_RESOLVED"])))
        self.assertTrue(EVIDENCE_FIELDS.isdisjoint(set(allowlist["OUTCOME_COMMITTED"])))


if __name__ == "__main__":
    unittest.main()
