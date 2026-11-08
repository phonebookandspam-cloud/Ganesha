import os
import sqlite3
from sqlite_test_support import connect as sqlite_connect
import subprocess
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from ganesha.wallet.ledger import WalletLedger, InsufficientFunds, DuplicateOperation, InvalidRoundState, LedgerError, StaleFencingToken, RoundLeaseBusy
from ganesha.rgs.service import RoundService
from ganesha.game.engine import GameEngine, BonusBuyTermsUnavailable
from ganesha.game.presentation import build_presentation_events, replay_events
from ganesha.security.signing import sign_payload, verify_payload, timestamp_is_fresh
from ganesha.security.nonce import NonceRegistry
from ganesha.security.verification import verify_request, sign_request
from ganesha.math.rng import HmacStopGenerator
from ganesha.game.math_port import DraftMathPort
from ganesha.math.engine import UnspecifiedMathRule

class WalletRgsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = WalletLedger(os.path.join(self.tmp.name, "wallet.sqlite"))
        self.ledger.create_account("player-1", "USD", 100000)
        self._test_fencing_tokens = {}

    def _fencing_token(self, round_id):
        """Claim one explicit local lease for direct ledger-mutation tests."""
        if round_id not in self._test_fencing_tokens:
            self._test_fencing_tokens[round_id] = self.ledger.claim_recovery_lease(
                round_id, "test-worker-" + round_id
            )
        return self._test_fencing_tokens[round_id]

    def _run_crash_process(self, script):
        env = os.environ.copy()
        source_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
        env["PYTHONPATH"] = source_root + os.pathsep + env.get("PYTHONPATH", "")
        return subprocess.run(
            [sys.executable, "-c", script, self.ledger.database_path],
            env=env, check=True, timeout=15, capture_output=True, text=True,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_debit_credit_are_idempotent(self):
        first = self.ledger.reserve_bet("debit-1", "round-1", "player-1", 1000)
        second = self.ledger.reserve_bet("debit-1", "round-1", "player-1", 1000)
        self.assertEqual(first, second)
        self.ledger.commit_outcome("round-1", {"payout": 250}, 250, fencing_token=self._fencing_token("round-1"))
        settled = self.ledger.settle_round("credit-1", "round-1", fencing_token=self._fencing_token("round-1"))
        replay = self.ledger.settle_round("credit-1", "round-1", fencing_token=self._fencing_token("round-1"))
        self.assertEqual(settled, replay)
        self.assertEqual(self.ledger.balance("player-1")["balance_minor"], 99250)
        self.assertEqual(len(self.ledger.journal_for_round("round-1")), 2)

    def test_round_journal_reconciliation_across_lifecycle(self):
        self.ledger.reserve_bet("recon-debit", "round-recon", "player-1", 1000)
        self.assertTrue(self.ledger.reconcile_round("round-recon")["ok"])
        self.ledger.commit_outcome("round-recon", {"payout": 250}, 250, fencing_token=self._fencing_token("round-recon"))
        self.assertTrue(self.ledger.reconcile_round("round-recon")["ok"])
        self.ledger.settle_round("recon-credit", "round-recon", fencing_token=self._fencing_token("round-recon"))
        report = self.ledger.reconcile_round("round-recon")
        self.assertTrue(report["ok"], report["issues"])
        self.assertEqual(report["journal_delta_minor"], -750)

    def test_service_outcome_payout_is_recomputed_at_ledger_boundary(self):
        round_id = "strict-payout-round"
        self.ledger.reserve_bet("strict-payout-debit", round_id, "player-1", 500,
                                max_payout_minor=5000, round_mode="BASE", base_bet_minor=100,
                                engine_version="game-engine-sha256:" + "a" * 64)
        token = self._fencing_token(round_id)
        outcome = {"mode": "BASE", "total_payout_milli": 1250,
                   "engine_version": "game-engine-sha256:" + "a" * 64}
        with self.assertRaises(LedgerError):
            self.ledger.commit_outcome(round_id, outcome, 124, fencing_token=token)
        with self.assertRaises(LedgerError):
            self.ledger.commit_outcome(round_id, dict(outcome, mode="EPIC_BUY"), 125, fencing_token=token)
        with self.assertRaises(LedgerError):
            self.ledger.commit_outcome(round_id, {"mode": "BASE", "engine_version": "game-engine-sha256:" + "a" * 64},
                                       125, fencing_token=token)
        self.assertEqual(self.ledger.round_snapshot(round_id)["round"]["status"], "BET_RESERVED")
        committed = self.ledger.commit_outcome(round_id, outcome, 125, fencing_token=token)
        self.assertEqual(committed["status"], "OUTCOME_COMMITTED")
        self.assertEqual(self.ledger.round_snapshot(round_id)["round"]["payout_minor"], 125)

    def test_round_service_persists_ordinary_round_cap_increment_and_replays_total_payout(self):
        class JackpotPort:
            def evaluate_stops(self, stops, mode):
                if mode == "BASE":
                    return {"mode": mode, "payout_milli": 100, "free_spins_awarded": 10, "scatter_count": 3}
                return {"mode": mode, "payout_milli": 900, "scatter_count": 0, "jackpot_triggered": False}
            def award_free_spins(self, scatter_count, retrigger=False):
                return 0

        engine = GameEngine(math_port=JackpotPort())
        engine.round_cap_milli = 1000
        service = RoundService(self.ledger, game_engine=engine,
                               allow_unapproved_math_for_tests=True,
                               allow_test_vectors_for_tests=True)
        result = service.play_round("player-1", "round-cap-replay-round", "round-cap-replay-op", 100, "BASE",
                                    internal_stop_vectors=[(0, 0, 0, 0, 0), (1, 1, 1, 1, 1)])
        events = result["events"]
        feature_spin = next(event for event in events if event["event_type"] == "FEATURE_SPIN_RESOLVED")
        committed = next(event for event in events if event["event_type"] == "OUTCOME_COMMITTED")
        self.assertEqual(feature_spin["payload"]["payout_milli"], 900)
        self.assertEqual(committed["payload"]["base_payout_milli"], 100)
        self.assertEqual(committed["payload"]["feature_payout_milli"], 900)
        self.assertEqual(committed["payload"]["total_payout_milli"], 1000)
        self.assertEqual(result["state"]["total_payout_milli"], 1000)
        self.assertTrue(self.ledger.reconcile_round("round-cap-replay-round")["ok"])

    def test_round_service_presentation_projection_matches_wallet_feature_trace_and_settlement(self):
        base_board = [
            ["A", "SCATTER_LOTUS", "K"],
            ["MOUSE", "A", "SCATTER_LOTUS"],
            ["K", "ELEPHANT", "A"],
            ["SCATTER_LOTUS", "CHAKRA", "MOUSE"],
            ["A", "K", "MODAK"],
        ]
        feature_board = [
            ["A", "K", "CHAKRA"], ["MOUSE", "A", "K"], ["WILD_GANESHA", "A", "MODAK"],
            ["K", "CHAKRA", "A"], ["A", "MOUSE", "K"],
        ]
        feature_display = [list(reel) for reel in feature_board]
        feature_display[2] = ["WILD_GANESHA", "WILD_GANESHA", "WILD_GANESHA"]

        class PresentationWalletMathPort:
            authority_status = "TEST_FIXTURE_ONLY"
            version = "presentation-wallet-integration-fixture-v1"

            def evaluate_stops(self, stops, mode):
                if mode == "BASE":
                    return {"mode": "BASE", "board": [list(reel) for reel in base_board],
                            "display_board": [list(reel) for reel in base_board],
                            "raw_payout_milli": 100, "payout_milli": 100,
                            "wild_multiplier": 1, "expanded_wild_reels": [],
                            "max_win_capped": False, "scatter_count": 3,
                            "free_spins_awarded": 10}
                return {"mode": "FREE_SPINS", "board": [list(reel) for reel in feature_board],
                        "display_board": [list(reel) for reel in feature_display],
                        "raw_payout_milli": 25, "payout_milli": 50,
                        "max_win_capped": False, "scatter_count": 0,
                        "expanded_wild_reels": [2], "wild_multiplier": 2,
                        "jackpot_triggered": False}

            def award_free_spins(self, scatter_count, retrigger=False):
                return 10 if scatter_count == 3 and not retrigger else 0

        service = RoundService(
            self.ledger, game_engine=GameEngine(math_port=PresentationWalletMathPort()),
            allow_unapproved_math_for_tests=True, allow_test_vectors_for_tests=True,
        )
        vectors = [(0, 0, 0, 0, 0)] + [(1, 1, 1, 1, 1)] * 10
        result = service.play_round(
            "player-1", "presentation-wallet-round", "presentation-wallet-op", 1000,
            "BASE", internal_stop_vectors=vectors,
        )

        presentation_events = build_presentation_events(
            "presentation-wallet-round", result["outcome"],
        )
        presentation_state = replay_events(
            "presentation-wallet-round", presentation_events,
        )
        self.assertEqual(presentation_state["classification"], "NON_FINANCIAL_PRESENTATION_ONLY")
        wallet_snapshot = self.ledger.round_snapshot("presentation-wallet-round")
        wallet_state = self.ledger.round_state("presentation-wallet-round")
        wallet_outcome_event = next(
            event for event in wallet_snapshot["events"] if event["event_type"] == "OUTCOME_COMMITTED"
        )
        wallet_feature_events = [event for event in wallet_snapshot["events"]
                                 if event["event_type"] == "FEATURE_SPIN_RESOLVED"]
        presentation_feature_events = [event for event in presentation_events
                                       if event["event_type"] == "FEATURE_SPIN_RESOLVED"]
        presentation_base_event = next(event for event in presentation_events
                                        if event["event_type"] == "BASE_OUTCOME_REVEALED")

        self.assertEqual(presentation_state["status"], "COMPLETED")
        self.assertEqual(presentation_state["base_board"], wallet_snapshot["outcome"]["base_result"]["board"])
        self.assertEqual(presentation_state["base_display_board"], wallet_outcome_event["payload"]["base_display_board"])
        self.assertEqual(presentation_state["feature_spins_played"], wallet_state["feature_spins_played"])
        self.assertEqual(presentation_state["feature_spins_remaining"], wallet_state["feature_spins_remaining"])
        self.assertEqual(presentation_state["feature_payout_milli"], wallet_state["feature_payout_milli"])
        self.assertEqual(presentation_state["total_payout_milli"], wallet_state["total_payout_milli"])
        self.assertEqual(presentation_state["total_payout_milli"], result["outcome"]["total_payout_milli"])
        self.assertEqual(wallet_outcome_event["payload"]["base_payout_milli"],
                         presentation_base_event["payload"]["payout_milli"])
        self.assertEqual(len(wallet_feature_events), 10)
        self.assertEqual(len(presentation_feature_events), 10)
        for wallet_event, presentation_event, outcome_event in zip(
                wallet_feature_events, presentation_feature_events, result["outcome"]["feature_events"]):
            wallet_payload = wallet_event["payload"]
            presentation_payload = presentation_event["payload"]
            outcome_result = outcome_event["result"]
            self.assertEqual(wallet_payload["spin_number"], presentation_payload["spin_number"])
            self.assertEqual(wallet_payload["stops"], outcome_event["stops"])
            self.assertEqual(wallet_payload["board"], outcome_result["board"])
            self.assertEqual(wallet_payload["display_board"], outcome_result["display_board"])
            self.assertEqual(presentation_payload["board"], outcome_result["board"])
            self.assertEqual(presentation_payload["display_board"], outcome_result["display_board"])
            self.assertEqual(presentation_payload["wild_reels"], outcome_result["expanded_wild_reels"])
            self.assertEqual(presentation_payload["multiplier"], outcome_result["wild_multiplier"])
            self.assertEqual(wallet_payload["payout_milli"], outcome_event["payout_awarded_milli"])
            self.assertEqual(presentation_payload["payout_awarded_milli"], outcome_event["payout_awarded_milli"])
        self.assertEqual(result["settlement"]["payout_minor"],
                         (1000 * presentation_state["total_payout_milli"] + 500) // 1000)
        self.assertEqual(wallet_snapshot["round"]["status"], "SETTLED")
        self.assertTrue(self.ledger.reconcile_round("presentation-wallet-round")["ok"])

    def test_actual_draft_math_exact_three_scatter_runtime_presentation_and_wallet_settlement(self):
        """Exercise real Draft evaluator -> 10 FS -> presentation -> local ledger (test-only)."""
        service = RoundService(
            self.ledger, game_engine=GameEngine(math_port=DraftMathPort()),
            allow_unapproved_math_for_tests=True, allow_test_vectors_for_tests=True,
        )
        base_stops = (0, 0, 2, 3, 4)  # exactly three Scatter, 386 milli payout
        free_spin_stops = (0, 0, 0, 0, 0)  # one expanded Wild reel, x2, 78,140 milli payout
        vectors = [base_stops] + [free_spin_stops] * 10
        initial_balance = self.ledger.balance("player-1")["balance_minor"]
        result = service.play_round(
            "player-1", "actual-draft-feature-round", "actual-draft-feature-op", 1000,
            "BASE", internal_stop_vectors=vectors,
        )
        outcome = result["outcome"]
        self.assertEqual(outcome["base_result"]["scatter_count"], 3)
        self.assertEqual(outcome["initial_free_spins"], 10)
        self.assertEqual(outcome["free_spins_played"], 10)
        self.assertEqual(outcome["base_result"]["payout_milli"], 386)
        self.assertEqual(outcome["feature_events"][0]["result"]["payout_milli"], 78140)
        self.assertEqual(outcome["feature_events"][0]["result"]["expanded_wild_reels"], [0])
        self.assertEqual(outcome["feature_events"][0]["result"]["display_board"][0],
                         ["WILD_GANESHA"] * 3)
        self.assertEqual(outcome["total_payout_milli"], 386 + 10 * 78140)

        presentation_events = build_presentation_events(
            "actual-draft-feature-round", outcome,
        )
        presentation_state = replay_events(
            "actual-draft-feature-round", presentation_events,
        )
        self.assertEqual(presentation_state["classification"], "NON_FINANCIAL_PRESENTATION_ONLY")
        snapshot = self.ledger.round_snapshot("actual-draft-feature-round")
        wallet_state = self.ledger.round_state("actual-draft-feature-round")
        wallet_feature = [event for event in snapshot["events"]
                          if event["event_type"] == "FEATURE_SPIN_RESOLVED"]
        presentation_feature = [event for event in presentation_events
                                if event["event_type"] == "FEATURE_SPIN_RESOLVED"]
        self.assertEqual(presentation_state["status"], "COMPLETED")
        self.assertEqual(presentation_state["base_board"], outcome["base_result"]["board"])
        self.assertEqual(presentation_state["base_display_board"], outcome["base_result"]["display_board"])
        self.assertEqual(presentation_state["total_payout_milli"], outcome["total_payout_milli"])
        self.assertEqual(wallet_state["total_payout_milli"], outcome["total_payout_milli"])
        self.assertEqual(len(wallet_feature), 10)
        self.assertEqual(len(presentation_feature), 10)
        for index, (wallet_event, ui_event, outcome_event) in enumerate(
                zip(wallet_feature, presentation_feature, outcome["feature_events"]), start=1):
            self.assertEqual(wallet_event["payload"]["spin_number"], index)
            self.assertEqual(wallet_event["payload"]["board"], outcome_event["result"]["board"])
            self.assertEqual(wallet_event["payload"]["display_board"], outcome_event["result"]["display_board"])
            self.assertEqual(ui_event["payload"]["board"], outcome_event["result"]["board"])
            self.assertEqual(ui_event["payload"]["display_board"], outcome_event["result"]["display_board"])
            self.assertEqual(ui_event["payload"]["multiplier"], outcome_event["result"]["wild_multiplier"])
            self.assertEqual(wallet_event["payload"]["payout_milli"], outcome_event["payout_awarded_milli"])
        expected_credit = (1000 * outcome["total_payout_milli"] + 500) // 1000
        self.assertEqual(result["settlement"]["payout_minor"], expected_credit)
        self.assertEqual(self.ledger.balance("player-1")["balance_minor"],
                         initial_balance - 1000 + expected_credit)
        self.assertEqual(snapshot["round"]["status"], "SETTLED")
        self.assertTrue(self.ledger.reconcile_round("actual-draft-feature-round")["ok"])

    def test_four_scatter_twelve_free_spins_settle_as_one_base_round(self):
        base_board = [["A", "A", "A"] for _ in range(5)]
        for reel, row in ((0, 0), (1, 1), (2, 2), (4, 1)):
            base_board[reel][row] = "SCATTER_LOTUS"
        feature_board = [["A", "K", "MOUSE"] for _ in range(5)]

        class FourScatterWalletMathPort:
            authority_status = "TEST_FIXTURE_ONLY"
            version = "four-scatter-twelve-spin-wallet-fixture-v1"

            def evaluate_stops(self, stops, mode):
                if mode == "BASE":
                    return {"mode": "BASE", "board": [list(reel) for reel in base_board],
                            "display_board": [list(reel) for reel in base_board],
                            "raw_payout_milli": 100, "payout_milli": 100,
                            "wild_multiplier": 1, "expanded_wild_reels": [],
                            "max_win_capped": False, "scatter_count": 4,
                            "free_spins_awarded": 12}
                return {"mode": "FREE_SPINS", "board": [list(reel) for reel in feature_board],
                        "display_board": [list(reel) for reel in feature_board],
                        "raw_payout_milli": 25, "payout_milli": 25,
                        "max_win_capped": False, "scatter_count": 0,
                        "expanded_wild_reels": [], "wild_multiplier": 1,
                        "jackpot_triggered": False}

            def award_free_spins(self, scatter_count, retrigger=False):
                if retrigger:
                    return 0
                return 12 if scatter_count == 4 else 10 if scatter_count == 3 else 0

        service = RoundService(
            self.ledger, game_engine=GameEngine(math_port=FourScatterWalletMathPort()),
            allow_unapproved_math_for_tests=True, allow_test_vectors_for_tests=True,
        )
        initial_balance = self.ledger.balance("player-1")["balance_minor"]
        result = service.play_round(
            "player-1", "four-scatter-twelve-spin-round", "four-scatter-twelve-spin-op", 1000,
            "BASE", internal_stop_vectors=[(0,) * 5] + [(1,) * 5] * 12,
        )
        outcome = result["outcome"]
        self.assertEqual(outcome["base_result"]["scatter_count"], 4)
        self.assertEqual(outcome["initial_free_spins"], 12)
        self.assertEqual(outcome["free_spins_played"], 12)
        self.assertEqual(len(outcome["feature_events"]), 12)

        presentation_events = build_presentation_events("four-scatter-twelve-spin-round", outcome)
        presentation_state = replay_events("four-scatter-twelve-spin-round", presentation_events)
        self.assertEqual(presentation_state["feature_initial_spins"], 12)
        self.assertEqual(presentation_state["feature_spins_played"], 12)
        self.assertEqual(presentation_state["status"], "COMPLETED")

        snapshot = self.ledger.round_snapshot("four-scatter-twelve-spin-round")
        self.assertEqual(snapshot["round"]["mode"], "BASE")
        self.assertEqual(snapshot["round"]["bet_minor"], 1000)
        self.assertEqual(snapshot["round"]["status"], "SETTLED")
        wallet_feature = [event for event in snapshot["events"]
                          if event["event_type"] == "FEATURE_SPIN_RESOLVED"]
        self.assertEqual(len(wallet_feature), 12)
        journal = self.ledger.journal_for_round("four-scatter-twelve-spin-round")
        debit_entries = [entry for entry in journal if entry["entry_type"] == "BET_DEBIT"]
        credit_entries = [entry for entry in journal if entry["entry_type"] == "PAYOUT_CREDIT"]
        self.assertEqual(len(debit_entries), 1)
        self.assertEqual(len(credit_entries), 1)
        self.assertEqual(self.ledger.balance("player-1")["balance_minor"],
                         initial_balance - 1000 + result["settlement"]["payout_minor"])
        self.assertTrue(self.ledger.reconcile_round("four-scatter-twelve-spin-round")["ok"])

    def test_five_scatter_refunds_base_debit_until_embedded_epic_payload_exists(self):
        from ganesha.math.engine import EmbeddedEpicFeatureUnavailable

        class FiveScatterWithoutProviderPayload:
            authority_status = "TEST_FIXTURE_ONLY"
            version = "five-scatter-payload-unavailable-v1"

            def evaluate_stops(self, stops, mode):
                if mode == "BASE":
                    return {"mode": "BASE", "payout_milli": 0, "raw_payout_milli": 0,
                            "scatter_count": 5, "free_spins_awarded": 0,
                            "max_win_capped": False}
                raise AssertionError("5 Scatter must fail before any feature Math evaluation")

            def award_free_spins(self, scatter_count, retrigger=False):
                raise AssertionError("5 Scatter must not be translated into Free Spins")

        service = RoundService(
            self.ledger, game_engine=GameEngine(math_port=FiveScatterWithoutProviderPayload()),
            allow_unapproved_math_for_tests=True, allow_test_vectors_for_tests=True,
        )
        round_id = "five-scatter-embedded-epic-unavailable"
        before = self.ledger.balance("player-1")["balance_minor"]
        with self.assertRaises(EmbeddedEpicFeatureUnavailable):
            service.play_round("player-1", round_id, "five-scatter-op", 100, "BASE",
                               internal_stop_vectors=[(0, 0, 0, 0, 0)])

        snapshot = self.ledger.round_snapshot(round_id)
        self.assertEqual(snapshot["round"]["mode"], "BASE")
        self.assertEqual(snapshot["round"]["status"], "REFUNDED")
        self.assertEqual(self.ledger.balance("player-1")["balance_minor"], before)
        journal = self.ledger.journal_for_round(round_id)
        self.assertEqual(sum(entry["entry_type"] == "BET_DEBIT" for entry in journal), 1)
        self.assertEqual(sum(entry["entry_type"] == "BET_REFUND" for entry in journal), 1)
        self.assertEqual(sum(entry["entry_type"] == "PAYOUT_CREDIT" for entry in journal), 0)
        self.assertFalse(any(event["event_type"] == "FEATURE_STARTED" for event in snapshot["events"]))
        self.assertTrue(self.ledger.reconcile_round(round_id)["ok"])

    def test_actual_draft_math_retrigger_unknown_fails_closed_and_refunds(self):
        service = RoundService(
            self.ledger, game_engine=GameEngine(math_port=DraftMathPort()),
            allow_unapproved_math_for_tests=True, allow_test_vectors_for_tests=True,
        )
        initial_balance = self.ledger.balance("player-1")["balance_minor"]
        # Exact-3 BASE trigger is valid; this Free Spin has 3+ Scatter, whose
        # retrigger contract is unspecified and must not be silently ignored.
        with self.assertRaisesRegex(UnspecifiedMathRule, "retrigger rules are not user-authorized"):
            service.play_round(
                "player-1", "actual-draft-retrigger-block", "actual-draft-retrigger-op", 1000,
                "BASE", internal_stop_vectors=[(0, 0, 2, 3, 4)] + [(4, 3, 4, 5, 6)] * 10,
            )
        snapshot = self.ledger.round_snapshot("actual-draft-retrigger-block")
        self.assertEqual(snapshot["round"]["status"], "REFUNDED")
        self.assertIsNone(snapshot["outcome"])
        self.assertEqual(self.ledger.balance("player-1")["balance_minor"], initial_balance)
        self.assertFalse(any(event["event_type"] == "OUTCOME_COMMITTED" for event in snapshot["events"]))
        self.assertTrue(self.ledger.reconcile_round("actual-draft-retrigger-block")["ok"])

    def test_actual_draft_math_exact_conditional_maximum_path_reaches_wallet_once(self):
        """Prove the enumerated 10,088.738x Draft path is engine-generatable and locally payable."""
        service = RoundService(
            self.ledger, game_engine=GameEngine(math_port=DraftMathPort()),
            allow_unapproved_math_for_tests=True, allow_test_vectors_for_tests=True,
        )
        # Exhaustive Draft stop enumeration: BASE exact-3 maximum 88.738x;
        # Free Spin maximum 1,000x with only two Scatter (no retrigger ambiguity).
        base_max_stops = (12, 4, 4, 5, 6)
        free_spin_max_stops = (0, 0, 4, 0, 5)
        initial_balance = self.ledger.balance("player-1")["balance_minor"]
        result = service.play_round(
            "player-1", "actual-draft-max-path", "actual-draft-max-path-op", 1000,
            "BASE", internal_stop_vectors=[base_max_stops] + [free_spin_max_stops] * 10,
        )
        outcome = result["outcome"]
        self.assertEqual(outcome["base_result"]["scatter_count"], 3)
        self.assertEqual(outcome["base_result"]["payout_milli"], 88738)
        self.assertEqual(outcome["initial_free_spins"], 10)
        self.assertEqual(outcome["free_spins_played"], 10)
        self.assertTrue(all(event["result"]["scatter_count"] == 2 for event in outcome["feature_events"]))
        self.assertTrue(all(event["result"]["payout_milli"] == 1_000_000 for event in outcome["feature_events"]))
        self.assertTrue(all(event["result"]["max_win_capped"] for event in outcome["feature_events"]))
        self.assertEqual(outcome["total_payout_milli"], 10_088_738)
        self.assertFalse(outcome["round_cap_reached"])

        events = build_presentation_events(
            "actual-draft-max-path", outcome,
        )
        presentation = replay_events(
            "actual-draft-max-path", events,
        )
        self.assertEqual(presentation["classification"], "NON_FINANCIAL_PRESENTATION_ONLY")
        self.assertEqual(presentation["total_payout_milli"], 10_088_738)
        self.assertEqual(presentation["feature_spins_played"], 10)
        expected_credit = 10_088_738  # 1,000 minor-unit wager × 10,088.738x, half-up
        self.assertEqual(result["settlement"]["payout_minor"], expected_credit)
        self.assertEqual(self.ledger.balance("player-1")["balance_minor"],
                         initial_balance - 1000 + expected_credit)
        self.assertEqual(self.ledger.round_snapshot("actual-draft-max-path")["round"]["status"], "SETTLED")
        self.assertTrue(self.ledger.reconcile_round("actual-draft-max-path")["ok"])

    def test_server_rng_round_refuses_unapproved_draft_math_before_debit(self):
        service = RoundService(self.ledger, stop_generator=HmacStopGenerator(b"draft-math-block-key-000000000000"))
        before = self.ledger.balance("player-1")["balance_minor"]
        with self.assertRaisesRegex(RuntimeError, "canonical Math approval trust record"):
            service.play_round("player-1", "draft-math-blocked", "draft-math-blocked-op", 100, "BASE")
        self.assertEqual(self.ledger.balance("player-1")["balance_minor"], before)
        with self.assertRaises(InvalidRoundState):
            self.ledger.round_snapshot("draft-math-blocked")

    def test_unverified_authority_status_string_cannot_enable_financial_rounds(self):
        class SpoofedApprovedPort:
            authority_status = "CANONICAL_APPROVED"

            def evaluate_stops(self, stops):
                return {"payout_milli": 0, "scatter_count": 0, "free_spins_awarded": 0}

            def award_free_spins(self, scatter_count):
                return 0

        service = RoundService(self.ledger, game_engine=GameEngine(math_port=SpoofedApprovedPort()),
                               stop_generator=HmacStopGenerator(b"spoofed-approval-key-000000000000"))
        before = self.ledger.balance("player-1")["balance_minor"]
        with self.assertRaisesRegex(RuntimeError, "canonical Math approval trust record"):
            service.play_round("player-1", "spoofed-math-blocked", "spoofed-math-blocked-op", 100, "BASE")
        self.assertEqual(self.ledger.balance("player-1")["balance_minor"], before)
        with self.assertRaises(InvalidRoundState):
            self.ledger.round_snapshot("spoofed-math-blocked")

    def test_client_supplied_stop_vectors_are_rejected_without_test_only_service_flag(self):
        service = RoundService(self.ledger, stop_generator=HmacStopGenerator(b"test-vector-block-key-000000000000"))
        before = self.ledger.balance("player-1")["balance_minor"]
        with self.assertRaisesRegex(RuntimeError, "explicit test-only service instances"):
            service.play_round("player-1", "client-vector-blocked", "client-vector-blocked-op", 100,
                               "BASE", internal_stop_vectors=[[0, 0, 0, 0, 0]])
        self.assertEqual(self.ledger.balance("player-1")["balance_minor"], before)
        with self.assertRaises(InvalidRoundState):
            self.ledger.round_snapshot("client-vector-blocked")

    def test_round_journal_reconciliation_detects_tampering(self):
        self.ledger.reserve_bet("recon-tamper-debit", "round-recon-tamper", "player-1", 1000)
        with sqlite_connect(self.ledger.database_path) as db:
            db.execute("UPDATE journal SET delta_minor=-999 WHERE round_id=?", ("round-recon-tamper",))
        report = self.ledger.reconcile_round("round-recon-tamper")
        self.assertFalse(report["ok"])
        self.assertIn("journal delta disagrees with round state", report["issues"])

    def test_round_journal_reconciliation_validates_refund(self):
        self.ledger.reserve_bet("recon-refund-debit", "round-recon-refund", "player-1", 1000)
        self.ledger.refund_reserved_round("recon-refund", "round-recon-refund", fencing_token=self._fencing_token("round-recon-refund"))
        report = self.ledger.reconcile_round("round-recon-refund")
        self.assertTrue(report["ok"], report["issues"])
        self.assertEqual(report["journal_delta_minor"], 0)

    def test_account_reconciliation_matches_opening_balance_and_all_round_journals(self):
        self.ledger.reserve_bet("account-recon-debit", "account-recon-round", "player-1", 1000)
        self.ledger.commit_outcome("account-recon-round", {"payout": 250}, 250, fencing_token=self._fencing_token("account-recon-round"))
        self.ledger.settle_round("account-recon-credit", "account-recon-round", fencing_token=self._fencing_token("account-recon-round"))
        report = self.ledger.reconcile_account("player-1")
        self.assertTrue(report["ok"], report["issues"])
        self.assertEqual(report["opening_balance_minor"], 100000)
        self.assertEqual(report["journal_delta_minor"], -750)
        self.assertEqual(report["expected_balance_minor"], 99250)
        self.assertEqual(report["rounds_checked"], 1)

    def test_account_reconciliation_detects_balance_tampering(self):
        self.ledger.reserve_bet("account-tamper-debit", "account-tamper-round", "player-1", 1000)
        with sqlite_connect(self.ledger.database_path) as db:
            db.execute("UPDATE accounts SET balance_minor=balance_minor+1 WHERE account_id=?", ("player-1",))
        report = self.ledger.reconcile_account("player-1")
        self.assertFalse(report["ok"])
        self.assertIn("account balance disagrees with opening balance plus journal net delta", report["issues"])

    def test_legacy_account_without_verified_opening_baseline_fails_closed(self):
        path = os.path.join(self.tmp.name, "legacy-account.sqlite")
        with sqlite_connect(path) as db:
            db.execute("CREATE TABLE accounts(account_id TEXT PRIMARY KEY,currency TEXT NOT NULL,balance_minor INTEGER NOT NULL)")
            db.execute("INSERT INTO accounts VALUES(?,?,?)", ("legacy-player", "USD", 5000))
        migrated = WalletLedger(path)
        report = migrated.reconcile_account("legacy-player")
        self.assertFalse(report["ok"])
        self.assertIsNone(report["opening_balance_minor"])
        self.assertIn("account opening balance is unavailable; historical baseline cannot be proven", report["issues"])

    def test_event_contract_is_persisted_and_replay_matches_ledger(self):
        self.ledger.reserve_bet("event-debit", "round-events", "player-1", 1000)
        self.ledger.commit_outcome("round-events", {"payout": 500, "engine_version": "test"}, 500, fencing_token=self._fencing_token("round-events"))
        self.ledger.settle_round("event-credit", "round-events", fencing_token=self._fencing_token("round-events"))
        events = self.ledger.round_events("round-events")
        state = self.ledger.round_state("round-events")
        self.assertEqual([item["event_type"] for item in events], [
            "ROUND_OPENED", "BET_RESERVED", "RNG_COMMITTED", "OUTCOME_COMMITTED", "SETTLED", "END_ROUND"
        ])
        self.assertEqual(state["status"], "ENDED")
        self.assertEqual(state["payout_minor"], 500)

    def test_feature_trace_and_win_ack_are_ordered_in_event_stream(self):
        self.ledger.reserve_bet("feature-debit", "round-feature", "player-1", 1000, engine_version="test")
        feature_events = [
            {"spin_number": 1, "stops": [0, 1, 2, 3, 4], "result": {"payout_milli": 1000}, "retrigger_awarded": 0},
            {"spin_number": 2, "stops": [1, 2, 3, 4, 5], "result": {"payout_milli": 2000}, "retrigger_awarded": 0},
        ]
        self.ledger.record_feature_progress("round-feature", 2, feature_events, fencing_token=self._fencing_token("round-feature"))
        self.ledger.commit_outcome("round-feature", {"payout": 3000, "engine_version": "test"}, 300, fencing_token=self._fencing_token("round-feature"))
        state = self.ledger.record_win_presented("round-feature", fencing_token=self._fencing_token("round-feature"))
        self.assertTrue(state["win_presented"])
        self.ledger.settle_round("feature-credit", "round-feature", fencing_token=self._fencing_token("round-feature"))
        types = [item["event_type"] for item in self.ledger.round_events("round-feature")]
        self.assertEqual(types[3:7], ["FEATURE_STARTED", "FEATURE_SPIN_RESOLVED", "FEATURE_SPIN_RESOLVED", "FEATURE_ENDED"])
        self.assertIn("WIN_PRESENTED", types)
        self.assertTrue(self.ledger.reconcile_round("round-feature")["ok"])

    def test_fencing_token_rejects_stale_worker_after_lease_reclaim(self):
        self.ledger.reserve_bet("fence-debit", "round-fence", "player-1", 1000)
        first = self.ledger.claim_recovery_lease("round-fence", "worker-old", lease_seconds=30)
        with sqlite_connect(self.ledger.database_path) as db:
            db.execute("UPDATE recovery_leases SET expires_at=0 WHERE round_id=?", ("round-fence",))
        second = self.ledger.claim_recovery_lease("round-fence", "worker-new", lease_seconds=30)
        self.assertGreater(second, first)
        with self.assertRaises(StaleFencingToken):
            self.ledger.commit_outcome("round-fence", {"payout": 0}, 0, fencing_token=first)
        self.ledger.commit_outcome("round-fence", {"payout": 0}, 0, fencing_token=second)
        self.ledger.settle_round("fence-credit", "round-fence", fencing_token=second)

    def test_all_round_mutations_require_a_fencing_token(self):
        mutations = ("commit", "feature", "settle", "refund", "win")
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                round_id = "missing-token-" + mutation
                self.ledger.reserve_bet("debit-" + mutation, round_id, "player-1", 100)
                if mutation in ("settle", "win"):
                    token = self.ledger.claim_recovery_lease(round_id, "setup-" + mutation)
                    self.ledger.commit_outcome(round_id, {"payout": 10}, 10, fencing_token=token)
                with self.assertRaises(TypeError):
                    if mutation == "commit":
                        self.ledger.commit_outcome(round_id, {"payout": 10}, 10)
                    elif mutation == "feature":
                        self.ledger.record_feature_progress(round_id, 1, [])
                    elif mutation == "settle":
                        self.ledger.settle_round("credit-" + mutation, round_id)
                    elif mutation == "refund":
                        self.ledger.refund_reserved_round("refund-" + mutation, round_id)
                    else:
                        self.ledger.record_win_presented(round_id)
                with self.assertRaises(StaleFencingToken):
                    if mutation == "commit":
                        self.ledger.commit_outcome(round_id, {"payout": 10}, 10, fencing_token=None)
                    elif mutation == "feature":
                        self.ledger.record_feature_progress(round_id, 1, [], fencing_token=None)
                    elif mutation == "settle":
                        self.ledger.settle_round("credit-none-" + mutation, round_id, fencing_token=None)
                    elif mutation == "refund":
                        self.ledger.refund_reserved_round("refund-none-" + mutation, round_id, fencing_token=None)
                    else:
                        self.ledger.record_win_presented(round_id, fencing_token=None)

    def test_all_round_mutations_reject_expired_and_superseded_tokens(self):
        mutations = ("commit", "feature", "settle", "refund", "win")
        feature_events = [
            {"spin_number": 1, "stops": [0, 1, 2, 3, 4], "result": {"payout_milli": 1000}, "retrigger_awarded": 0},
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                round_id = "expired-token-" + mutation
                self.ledger.reserve_bet("debit-" + mutation, round_id, "player-1", 100)
                old_token = self.ledger.claim_recovery_lease(round_id, "old-" + mutation)
                if mutation in ("settle", "win"):
                    self.ledger.commit_outcome(round_id, {"payout": 10}, 10, fencing_token=old_token)
                with sqlite_connect(self.ledger.database_path) as db:
                    db.execute("UPDATE recovery_leases SET expires_at=0 WHERE round_id=?", (round_id,))

                def mutate(token):
                    if mutation == "commit":
                        return self.ledger.commit_outcome(round_id, {"payout": 10}, 10, fencing_token=token)
                    if mutation == "feature":
                        return self.ledger.record_feature_progress(round_id, 1, feature_events, fencing_token=token)
                    if mutation == "settle":
                        return self.ledger.settle_round("credit-" + mutation, round_id, fencing_token=token)
                    if mutation == "refund":
                        return self.ledger.refund_reserved_round("refund-" + mutation, round_id, fencing_token=token)
                    return self.ledger.record_win_presented(round_id, fencing_token=token)

                with self.assertRaises(StaleFencingToken):
                    mutate(old_token)  # expired
                new_token = self.ledger.claim_recovery_lease(round_id, "new-" + mutation)
                with self.assertRaises(StaleFencingToken):
                    mutate(old_token)  # superseded by a newer generation
                # The current generation remains usable at the mutation boundary.
                mutate(new_token)

    def test_active_recovery_lease_is_exclusive_and_renewable(self):
        self.ledger.reserve_bet("lease-debit", "round-lease", "player-1", 1000)
        token = self.ledger.claim_recovery_lease("round-lease", "worker-one", lease_seconds=30)
        with self.assertRaises(RoundLeaseBusy):
            self.ledger.claim_recovery_lease("round-lease", "worker-two", lease_seconds=30)
        self.ledger.renew_recovery_lease("round-lease", "worker-one", token, lease_seconds=30)
        self.ledger.release_recovery_lease("round-lease", "worker-one", token)
        next_token = self.ledger.claim_recovery_lease("round-lease", "worker-two", lease_seconds=30)
        self.assertGreater(next_token, token)
        self.ledger.release_recovery_lease("round-lease", "worker-two", next_token)

    def test_concurrent_round_service_retries_have_single_financial_effect(self):
        class NoWinEngine:
            def resolve_base_round(self, base_stops, free_spin_stop_vectors):
                return {"mode": "BASE", "initial_free_spins": 0, "feature_events": [],
                        "total_payout_milli": 0, "round_cap_reached": False}
        service = RoundService(self.ledger, game_engine=NoWinEngine(), stop_generator=HmacStopGenerator(b"concurrent-round-key-000000000000"), allow_unapproved_math_for_tests=True)
        def play():
            try:
                return service.play_round("player-1", "round-service-concurrent", "op-service-concurrent", 100, "BASE")
            except RoundLeaseBusy:
                return "BUSY"
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: play(), range(2)))
        self.assertTrue(any(result != "BUSY" for result in results))
        self.assertEqual(self.ledger.balance("player-1")["balance_minor"], 99900)
        self.assertEqual(self.ledger.round_snapshot("round-service-concurrent")["round"]["status"], "SETTLED")
        self.assertTrue(self.ledger.reconcile_round("round-service-concurrent")["ok"])

    def test_round_service_emits_win_presentation_before_settlement(self):
        class SmallWinEngine:
            def resolve_base_round(self, base_stops, free_spin_stop_vectors):
                return {"mode": "BASE", "initial_free_spins": 0, "feature_events": [],
                        "total_payout_milli": 1000, "round_cap_reached": False}
        service = RoundService(self.ledger, game_engine=SmallWinEngine(),
                               stop_generator=HmacStopGenerator(b"win-presentation-key-000000000000"),
                               allow_unapproved_math_for_tests=True)
        service.play_round("player-1", "round-win-event", "op-win-event", 100, "BASE")
        types = [event["event_type"] for event in self.ledger.round_events("round-win-event")]
        self.assertLess(types.index("OUTCOME_COMMITTED"), types.index("WIN_PRESENTED"))
        self.assertLess(types.index("WIN_PRESENTED"), types.index("SETTLED"))
        self.assertEqual(types[-1], "END_ROUND")
        self.assertTrue(self.ledger.reconcile_round("round-win-event")["ok"])

    def test_refund_and_outcome_commit_race_has_one_terminal_winner(self):
        self.ledger.reserve_bet("race-debit", "round-race", "player-1", 1000, engine_version="race-test")
        token = self._fencing_token("round-race")
        def commit():
            try:
                return self.ledger.commit_outcome("round-race", {"payout": 100, "engine_version": "race-test"}, 100, fencing_token=token)
            except InvalidRoundState:
                return "LOST"
        def refund():
            try:
                return self.ledger.refund_reserved_round("race-refund", "round-race", fencing_token=token)
            except InvalidRoundState:
                return "LOST"
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = [pool.submit(commit), pool.submit(refund)]
            results = [item.result() for item in outcomes]
        status = self.ledger.round_snapshot("round-race")["round"]["status"]
        if status == "OUTCOME_COMMITTED":
            self.ledger.settle_round("race-credit", "round-race", fencing_token=token)
            self.assertEqual(self.ledger.balance("player-1")["balance_minor"], 99100)
        else:
            self.assertEqual(status, "REFUNDED")
            self.assertEqual(self.ledger.balance("player-1")["balance_minor"], 100000)
        self.assertEqual(sum(result != "LOST" for result in results), 1)
        self.assertTrue(self.ledger.reconcile_round("round-race")["ok"])

    def test_event_chain_tampering_is_reported_by_round_reconciliation(self):
        self.ledger.reserve_bet("tamper-event-debit", "round-event-tamper", "player-1", 1000)
        with sqlite_connect(self.ledger.database_path) as db:
            row = db.execute("SELECT event_json FROM round_events WHERE round_id=? ORDER BY sequence LIMIT 1",
                             ("round-event-tamper",)).fetchone()
            altered = row[0].replace('"BASE"', '"EPIC_BUY"')
            db.execute("UPDATE round_events SET event_json=? WHERE round_id=? AND sequence=1",
                       (altered, "round-event-tamper"))
        report = self.ledger.reconcile_round("round-event-tamper")
        self.assertFalse(report["ok"])
        self.assertIn("round event stream is invalid or cannot be replayed", report["issues"])

    def test_legacy_sqlite_schema_migrates_without_fabricating_historical_events(self):
        path = os.path.join(self.tmp.name, "legacy.sqlite")
        with sqlite_connect(path) as db:
            db.executescript("""
                CREATE TABLE accounts(account_id TEXT PRIMARY KEY,currency TEXT NOT NULL,balance_minor INTEGER NOT NULL);
                CREATE TABLE rounds(round_id TEXT PRIMARY KEY,account_id TEXT NOT NULL,currency TEXT NOT NULL,
                    bet_minor INTEGER NOT NULL,status TEXT NOT NULL,outcome_json TEXT,payout_minor INTEGER NOT NULL DEFAULT 0,
                    settlement_operation_id TEXT UNIQUE,rng_commitment TEXT NOT NULL);
                CREATE TABLE operations(operation_id TEXT PRIMARY KEY,round_id TEXT NOT NULL,action TEXT NOT NULL,
                    amount_minor INTEGER NOT NULL,response_json TEXT NOT NULL);
                CREATE TABLE journal(entry_id INTEGER PRIMARY KEY AUTOINCREMENT,operation_id TEXT NOT NULL UNIQUE,
                    round_id TEXT NOT NULL,account_id TEXT NOT NULL,currency TEXT NOT NULL,delta_minor INTEGER NOT NULL,entry_type TEXT NOT NULL);
            """)
        migrated = WalletLedger(path)
        with sqlite_connect(path) as db:
            columns = {row[1] for row in db.execute("PRAGMA table_info(rounds)").fetchall()}
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        self.assertTrue({"max_payout_minor", "mode", "base_bet_minor", "generator_version", "engine_version", "fencing_token"}.issubset(columns))
        self.assertIn("round_events", tables)
        self.assertEqual(migrated.round_events("no-such-round"), [])

    def test_recovery_after_debit_replays_same_server_rng_and_settles_once(self):
        generator = HmacStopGenerator(b"recovery-key" * 4)
        service = RoundService(self.ledger, stop_generator=generator, allow_unapproved_math_for_tests=True)
        commitment = generator.commitment("round-crash-debit")
        self.ledger.reserve_bet("op-crash-debit", "round-crash-debit", "player-1", 100,
                                commitment, max_payout_minor=5_000_000, round_mode="BASE",
                                base_bet_minor=100, generator_version=generator.version,
                                engine_version=service.engine_version)
        result = service.recover_round("round-crash-debit", "player-1")
        self.assertEqual(result["settlement"]["status"], "SETTLED")
        balance = self.ledger.balance("player-1")["balance_minor"]
        replay = service.recover_round("round-crash-debit", "player-1")
        self.assertEqual(replay["settlement"], result["settlement"])
        self.assertEqual(self.ledger.balance("player-1")["balance_minor"], balance)

    def test_recovery_after_outcome_commit_settles_without_regenerating_outcome(self):
        self.ledger.reserve_bet("op-crash-outcome", "round-crash-outcome", "player-1", 100,
                                "a" * 64, max_payout_minor=5000, round_mode="BASE", base_bet_minor=100)
        token = self._fencing_token("round-crash-outcome")
        self.ledger.commit_outcome("round-crash-outcome", {"total_payout_milli": 1250, "engine_version": "test"}, 125, fencing_token=token)
        self.ledger.release_recovery_lease("round-crash-outcome", "test-worker-round-crash-outcome", token)
        service = RoundService(self.ledger)
        result = service.recover_round("round-crash-outcome", "player-1")
        self.assertEqual(result["settlement"]["payout_minor"], 125)
        self.assertEqual(self.ledger.round_state("round-crash-outcome")["status"], "ENDED")

    def test_process_exit_immediately_after_debit_recovers_by_refunding_test_round(self):
        script = r"""
import os, sys
from ganesha.wallet.ledger import WalletLedger
ledger = WalletLedger(sys.argv[1])
ledger.reserve_bet("process-debit-op", "process-debit-round", "player-1", 100, "TEST:" + "c" * 64)
os._exit(0)
"""
        self._run_crash_process(script)
        self.assertEqual(self.ledger.balance("player-1")["balance_minor"], 99900)
        recovered = RoundService(self.ledger).recover_round("process-debit-round", "player-1")
        self.assertEqual(recovered["status"], "REFUNDED")
        self.assertEqual(self.ledger.balance("player-1")["balance_minor"], 100000)
        self.assertTrue(self.ledger.reconcile_round("process-debit-round")["ok"])

    def test_process_exit_after_outcome_commit_recovers_same_outcome_and_settles(self):
        script = r"""
import os, sys
from ganesha.wallet.ledger import WalletLedger
from ganesha.rgs.service import _engine_build_version
ledger = WalletLedger(sys.argv[1])
version = _engine_build_version()
ledger.reserve_bet("process-outcome-op", "process-outcome-round", "player-1", 100,
                   "a" * 64, max_payout_minor=5000, round_mode="BASE", base_bet_minor=100,
                   engine_version=version)
token = ledger.claim_recovery_lease("process-outcome-round", "process-outcome-worker")
outcome = {"mode":"BASE", "total_payout_milli":1250, "engine_version":version}
ledger.commit_outcome("process-outcome-round", outcome, 125, fencing_token=token)
ledger.record_win_presented("process-outcome-round", fencing_token=token)
os._exit(0)
"""
        self._run_crash_process(script)
        with sqlite_connect(self.ledger.database_path) as db:
            db.execute("UPDATE recovery_leases SET expires_at=0 WHERE round_id=?", ("process-outcome-round",))
        recovered = RoundService(self.ledger).recover_round("process-outcome-round", "player-1")
        self.assertEqual(recovered["status"], "SETTLED")
        self.assertEqual(recovered["settlement"]["payout_minor"], 125)
        self.assertEqual(self.ledger.balance("player-1")["balance_minor"], 100025)
        self.assertEqual(len(self.ledger.journal_for_round("process-outcome-round")), 2)
        self.assertTrue(self.ledger.reconcile_round("process-outcome-round")["ok"])

    def test_process_exit_after_credit_commit_does_not_credit_twice(self):
        script = r"""
import os, sys
from ganesha.wallet.ledger import WalletLedger
from ganesha.rgs.service import _engine_build_version
ledger = WalletLedger(sys.argv[1])
version = _engine_build_version()
ledger.reserve_bet("process-credit-op", "process-credit-round", "player-1", 100,
                   "a" * 64, max_payout_minor=5000, round_mode="BASE", base_bet_minor=100,
                   engine_version=version)
token = ledger.claim_recovery_lease("process-credit-round", "process-credit-worker")
outcome = {"mode":"BASE", "total_payout_milli":1250, "engine_version":version}
ledger.commit_outcome("process-credit-round", outcome, 125, fencing_token=token)
ledger.record_win_presented("process-credit-round", fencing_token=token)
ledger.settle_round("process-credit-op:settle", "process-credit-round", fencing_token=token)
os._exit(0)
"""
        self._run_crash_process(script)
        balance_after_credit = self.ledger.balance("player-1")["balance_minor"]
        self.assertEqual(balance_after_credit, 100025)
        recovered = RoundService(self.ledger).recover_round("process-credit-round", "player-1")
        self.assertEqual(recovered["status"], "SETTLED")
        self.assertEqual(self.ledger.balance("player-1")["balance_minor"], balance_after_credit)
        self.assertEqual(len(self.ledger.journal_for_round("process-credit-round")), 2)
        self.assertTrue(self.ledger.reconcile_round("process-credit-round")["ok"])

    def test_process_exit_before_refund_commit_recovers_reserved_round_once(self):
        script = r"""
import os, sys
from ganesha.wallet.ledger import WalletLedger
from ganesha.rgs.service import RoundService

class CrashBeforeRefundLedger(WalletLedger):
    def refund_reserved_round(self, *args, **kwargs):
        os._exit(73)

class FailingEngine:
    def resolve_base_round(self, base_stops, free_spin_stop_vectors):
        raise ValueError("simulated engine failure before refund")

ledger = CrashBeforeRefundLedger(sys.argv[1])
service = RoundService(ledger, game_engine=FailingEngine(),
                       allow_unapproved_math_for_tests=True,
                       allow_test_vectors_for_tests=True)
service.play_round("player-1", "pre-refund-crash-round", "pre-refund-crash-op", 100,
                   "BASE", internal_stop_vectors=[[0, 0, 0, 0, 0]])
"""
        env = os.environ.copy()
        source_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
        env["PYTHONPATH"] = source_root + os.pathsep + env.get("PYTHONPATH", "")
        crashed = subprocess.run(
            [sys.executable, "-c", script, self.ledger.database_path],
            env=env, check=False, timeout=15, capture_output=True, text=True,
        )
        self.assertEqual(crashed.returncode, 73, crashed.stderr)
        self.assertEqual(self.ledger.balance("player-1")["balance_minor"], 99900)
        with sqlite_connect(self.ledger.database_path) as db:
            db.execute("UPDATE recovery_leases SET expires_at=0 WHERE round_id=?",
                       ("pre-refund-crash-round",))

        service = RoundService(self.ledger)
        recovered = service.recover_round("pre-refund-crash-round", "player-1")
        self.assertEqual(recovered["status"], "REFUNDED")
        self.assertEqual(self.ledger.balance("player-1")["balance_minor"], 100000)
        self.assertEqual(len(self.ledger.journal_for_round("pre-refund-crash-round")), 2)
        event_types = [event["event_type"] for event in self.ledger.round_events("pre-refund-crash-round")]
        self.assertEqual(event_types.count("REFUNDED"), 1)
        self.assertEqual(event_types.count("END_ROUND"), 1)
        self.assertTrue(self.ledger.reconcile_round("pre-refund-crash-round")["ok"])

        replay = service.recover_round("pre-refund-crash-round", "player-1")
        self.assertEqual(replay["status"], "REFUNDED")
        self.assertEqual(self.ledger.balance("player-1")["balance_minor"], 100000)
        self.assertEqual(len(self.ledger.journal_for_round("pre-refund-crash-round")), 2)

    def test_service_refund_commit_with_lost_response_retries_after_sqlite_reopen(self):
        class LostRefundResponse(RuntimeError):
            pass

        class RefundResponseLostLedger(WalletLedger):
            def refund_reserved_round(self, operation_id, round_id, fencing_token):
                committed = super().refund_reserved_round(operation_id, round_id, fencing_token)
                self.committed_refund_response = committed
                raise LostRefundResponse("simulated response loss after SQLite commit")

        class FailingEngine:
            def resolve_base_round(self, base_stops, free_spin_stop_vectors):
                raise ValueError("simulated engine failure requiring refund")

        path = self.ledger.database_path
        interrupted_ledger = RefundResponseLostLedger(path)
        interrupted_service = RoundService(
            interrupted_ledger,
            game_engine=FailingEngine(),
            allow_unapproved_math_for_tests=True,
            allow_test_vectors_for_tests=True,
        )
        with self.assertRaises(LostRefundResponse):
            interrupted_service.play_round(
                "player-1", "refund-lost-response-round", "refund-lost-response-op", 100,
                "BASE", internal_stop_vectors=[[0, 0, 0, 0, 0]],
            )

        committed_response = interrupted_ledger.committed_refund_response
        self.assertEqual(committed_response["status"], "REFUNDED")
        self.assertEqual(self.ledger.balance("player-1")["balance_minor"], 100000)

        # Reopen through fresh ledger/service objects, as after process restart.
        reopened_ledger = WalletLedger(path)
        reopened_service = RoundService(reopened_ledger)
        recovered = reopened_service.recover_round("refund-lost-response-round", "player-1")
        self.assertEqual(recovered["status"], "REFUNDED")
        self.assertEqual(reopened_ledger.round_snapshot("refund-lost-response-round")["operations"]["REFUND"],
                         committed_response)

        # Retry recovery through a fresh service. Terminal replay must remain
        # stable and must not apply a second refund.
        replayed = reopened_service.recover_round("refund-lost-response-round", "player-1")
        self.assertEqual(replayed["status"], "REFUNDED")
        self.assertEqual(reopened_ledger.round_snapshot("refund-lost-response-round")["operations"]["REFUND"],
                         committed_response)
        self.assertEqual(reopened_ledger.balance("player-1")["balance_minor"], 100000)
        self.assertEqual(len(reopened_ledger.journal_for_round("refund-lost-response-round")), 2)
        event_types = [event["event_type"] for event in reopened_ledger.round_events("refund-lost-response-round")]
        self.assertEqual(event_types.count("REFUNDED"), 1)
        self.assertEqual(event_types.count("END_ROUND"), 1)
        self.assertTrue(reopened_ledger.reconcile_round("refund-lost-response-round")["ok"])

    def test_process_exit_after_refund_commit_does_not_refund_twice(self):
        script = r"""
import os, sys
from ganesha.wallet.ledger import WalletLedger
ledger = WalletLedger(sys.argv[1])
ledger.reserve_bet("process-refund-op", "process-refund-round", "player-1", 100, "TEST:" + "d" * 64)
token = ledger.claim_recovery_lease("process-refund-round", "process-refund-worker")
ledger.refund_reserved_round("process-refund-op:refund", "process-refund-round", fencing_token=token)
os._exit(0)
"""
        self._run_crash_process(script)
        balance_after_refund = self.ledger.balance("player-1")["balance_minor"]
        self.assertEqual(balance_after_refund, 100000)
        recovered = RoundService(self.ledger).recover_round("process-refund-round", "player-1")
        self.assertEqual(recovered["status"], "REFUNDED")
        self.assertEqual(self.ledger.balance("player-1")["balance_minor"], balance_after_refund)
        self.assertEqual(len(self.ledger.journal_for_round("process-refund-round")), 2)
        self.assertTrue(self.ledger.reconcile_round("process-refund-round")["ok"])

    def test_recovery_after_credit_commit_with_lost_response_does_not_credit_twice(self):
        round_id = "round-credit-response-lost"

        class PositivePayoutEngine:
            def resolve_base_round(self, base_stops, free_spin_stop_vectors):
                return {"mode": "BASE", "initial_free_spins": 0, "feature_events": [],
                        "total_payout_milli": 1250, "round_cap_reached": False}

        service = RoundService(self.ledger, game_engine=PositivePayoutEngine(),
                               allow_unapproved_math_for_tests=True,
                               allow_test_vectors_for_tests=True)
        settle_round = self.ledger.settle_round

        class LostSettlementResponse(RuntimeError):
            pass

        def commit_then_lose_response(*args, **kwargs):
            # Cross the real SQLite transaction boundary, then simulate the
            # caller losing the successful response before RoundService sees it.
            settle_round(*args, **kwargs)
            raise LostSettlementResponse("simulated response loss after SQLite COMMIT")

        self.ledger.settle_round = commit_then_lose_response
        with self.assertRaisesRegex(LostSettlementResponse, "after SQLite COMMIT"):
            service.play_round("player-1", round_id, "op-credit-response-lost", 100, "BASE",
                               internal_stop_vectors=[(0, 0, 0, 0, 0)])

        balance_after_credit = self.ledger.balance("player-1")["balance_minor"]
        self.assertEqual(balance_after_credit, 100025)
        # Reopen the same local SQLite database to exercise recovery against
        # persisted state, not an in-memory response or staged ledger object.
        reopened_ledger = WalletLedger(self.ledger.database_path)
        recovered = RoundService(reopened_ledger).recover_round(round_id, "player-1")
        self.assertEqual(recovered["status"], "SETTLED")
        self.assertEqual(recovered["settlement"]["payout_minor"], 125)
        self.assertEqual(reopened_ledger.balance("player-1")["balance_minor"], balance_after_credit)
        self.assertEqual(len(reopened_ledger.journal_for_round(round_id)), 2)
        event_types = [event["event_type"] for event in reopened_ledger.round_events(round_id)]
        self.assertEqual(event_types.count("SETTLED"), 1)
        self.assertEqual(event_types.count("END_ROUND"), 1)
        self.assertTrue(reopened_ledger.reconcile_round(round_id)["ok"])

    def test_recovery_after_refund_commit_with_lost_response_does_not_refund_twice(self):
        round_id = "round-refund-response-lost"
        self.ledger.reserve_bet("op-refund-response-lost", round_id, "player-1", 100,
                                "TEST:" + "b" * 64)
        token = self._fencing_token(round_id)
        refund = self.ledger.refund_reserved_round("op-refund-response-lost:refund", round_id,
                                                   fencing_token=token)
        self.ledger.release_recovery_lease(round_id, "test-worker-" + round_id, token)
        balance_after_refund = self.ledger.balance("player-1")["balance_minor"]

        recovered = RoundService(self.ledger).recover_round(round_id, "player-1")
        self.assertEqual(recovered["status"], "REFUNDED")
        self.assertEqual(self.ledger.balance("player-1")["balance_minor"], balance_after_refund)
        self.assertEqual(balance_after_refund, 100000)
        self.assertEqual(len(self.ledger.journal_for_round(round_id)), 2)
        self.assertEqual(self.ledger.journal_for_round(round_id)[1]["operation_id"], "op-refund-response-lost:refund")
        event_types = [event["event_type"] for event in self.ledger.round_events(round_id)]
        self.assertEqual(event_types.count("REFUNDED"), 1)
        self.assertEqual(event_types.count("END_ROUND"), 1)
        self.assertTrue(self.ledger.reconcile_round(round_id)["ok"])

    def test_idempotent_outcome_replay_requires_current_fencing_token(self):
        round_id = "round-outcome-replay-fence"
        self.ledger.reserve_bet("outcome-replay-debit", round_id, "player-1", 100)
        old_token = self._fencing_token(round_id)
        outcome = {"payout": 25}
        self.ledger.commit_outcome(round_id, outcome, 25, fencing_token=old_token)
        with sqlite_connect(self.ledger.database_path) as db:
            db.execute("UPDATE recovery_leases SET expires_at=0 WHERE round_id=?", (round_id,))
        new_token = self.ledger.claim_recovery_lease(round_id, "new-outcome-replay-worker")
        with self.assertRaises(StaleFencingToken):
            self.ledger.commit_outcome(round_id, outcome, 25, fencing_token=old_token)
        replay = self.ledger.commit_outcome(round_id, outcome, 25, fencing_token=new_token)
        self.assertEqual(replay["status"], "OUTCOME_COMMITTED")
        self.assertTrue(self.ledger.reconcile_round(round_id)["ok"])

    def test_idempotent_credit_and_refund_replays_reject_expired_tokens(self):
        credit_round = "round-credit-replay-fence"
        self.ledger.reserve_bet("credit-replay-debit", credit_round, "player-1", 100)
        credit_token = self._fencing_token(credit_round)
        self.ledger.commit_outcome(credit_round, {"payout": 10}, 10, fencing_token=credit_token)
        credit = self.ledger.settle_round("credit-replay-op", credit_round, fencing_token=credit_token)
        with sqlite_connect(self.ledger.database_path) as db:
            db.execute("UPDATE recovery_leases SET expires_at=0 WHERE round_id=?", (credit_round,))
        with self.assertRaises(StaleFencingToken):
            self.ledger.settle_round("credit-replay-op", credit_round, fencing_token=credit_token)
        self.assertEqual(self.ledger.balance("player-1")["balance_minor"], credit["balance_minor"])

        refund_round = "round-refund-replay-fence"
        self.ledger.reserve_bet("refund-replay-debit", refund_round, "player-1", 100)
        refund_token = self._fencing_token(refund_round)
        refund = self.ledger.refund_reserved_round("refund-replay-op", refund_round, fencing_token=refund_token)
        with sqlite_connect(self.ledger.database_path) as db:
            db.execute("UPDATE recovery_leases SET expires_at=0 WHERE round_id=?", (refund_round,))
        with self.assertRaises(StaleFencingToken):
            self.ledger.refund_reserved_round("refund-replay-op", refund_round, fencing_token=refund_token)
        self.assertEqual(self.ledger.balance("player-1")["balance_minor"], refund["balance_minor"])
        self.assertTrue(self.ledger.reconcile_round(credit_round)["ok"])
        self.assertTrue(self.ledger.reconcile_round(refund_round)["ok"])

    def test_recovery_rejects_test_vector_round_without_original_vectors(self):
        self.ledger.reserve_bet("op-test-only", "round-test-only", "player-1", 100,
                                "TEST:" + "a" * 64, max_payout_minor=5000)
        result = RoundService(self.ledger, stop_generator=HmacStopGenerator(b"r" * 32), allow_unapproved_math_for_tests=True).recover_round("round-test-only")
        self.assertEqual(result["status"], "REFUNDED")
        self.assertEqual(self.ledger.balance("player-1")["balance_minor"], 100000)

    def test_recovery_refunds_reserved_round_when_engine_build_changed(self):
        generator = HmacStopGenerator(b"engine-version-key-0000000000000000")
        service = RoundService(self.ledger, stop_generator=generator, allow_unapproved_math_for_tests=True)
        self.ledger.reserve_bet("op-engine-version", "round-engine-version", "player-1", 100,
                                generator.commitment("round-engine-version"), max_payout_minor=5000,
                                generator_version=generator.version, engine_version=service.engine_version)
        changed_service = RoundService(self.ledger, stop_generator=generator, allow_unapproved_math_for_tests=True)
        changed_service.engine_version = "game-engine-sha256:" + "0" * 64
        result = changed_service.recover_round("round-engine-version")
        self.assertEqual(result["reason"], "ENGINE_BUILD_VERSION_MISMATCH")
        self.assertEqual(self.ledger.balance("player-1")["balance_minor"], 100000)


    def test_round_reconciliation_detects_deleted_event_sequence(self):
        round_id = "round-event-gap"
        self.ledger.reserve_bet("event-gap-debit", round_id, "player-1", 100)
        with sqlite_connect(self.ledger.database_path) as db:
            db.execute("DELETE FROM round_events WHERE round_id=? AND sequence=2", (round_id,))
            remaining_sequences = [row[0] for row in db.execute(
                "SELECT sequence FROM round_events WHERE round_id=? ORDER BY sequence", (round_id,)
            )]
        self.assertEqual(remaining_sequences, [1, 3])

        # Verify the gap survives closing/reopening the SQLite database.
        reopened_ledger = WalletLedger(self.ledger.database_path)
        report = reopened_ledger.reconcile_round(round_id)
        self.assertFalse(report["ok"])
        self.assertIn("round event stream is invalid or cannot be replayed", report["issues"])
        self.assertEqual(reopened_ledger.round_snapshot(round_id)["round"]["status"], "BET_RESERVED")
        self.assertEqual(len(reopened_ledger.journal_for_round(round_id)), 1)

    def test_feature_progress_is_atomic_when_later_event_is_invalid(self):
        round_id = "round-feature-atomic"
        self.ledger.reserve_bet("feature-atomic-debit", round_id, "player-1", 100,
                                "a" * 64, max_payout_minor=5000, round_mode="BASE",
                                base_bet_minor=100)
        before = self.ledger.round_events(round_id)
        valid = {"spin_number": 1, "stops": [0, 0, 0, 0, 0],
                 "result": {"payout_milli": 10}, "retrigger_awarded": 0}
        with self.assertRaises((KeyError, ValueError)):
            self.ledger.record_feature_progress(round_id, 10, [valid, {}],
                                                fencing_token=self._fencing_token(round_id))
        self.assertEqual(self.ledger.round_events(round_id), before)
        self.assertEqual(self.ledger.round_state(round_id)["status"], "BET_RESERVED")
        self.assertTrue(self.ledger.reconcile_round(round_id)["ok"])

    def test_service_process_exit_immediately_after_debit_commit_recovers(self):
        script = r"""
import os, sys
from ganesha.wallet.ledger import WalletLedger
from ganesha.rgs.service import RoundService
from ganesha.game.engine import GameEngine
class ZeroMath:
    authority_status = "TEST_FIXTURE_ONLY"
    version = "zero-fixture"
    def evaluate_stops(self, stops, mode):
        board = [["A", "A", "A"] for _ in range(5)]
        return {"mode": mode, "board": board, "display_board": board,
                "payout_milli": 1000, "free_spins_awarded": 0, "scatter_count": 0}
    def award_free_spins(self, scatter_count, retrigger=False): return 0
ledger = WalletLedger(sys.argv[1])
service = RoundService(ledger, game_engine=GameEngine(ZeroMath()), allow_test_vectors_for_tests=True)
reserve = ledger.reserve_bet
def crash_after_reserve(*args, **kwargs):
    result = reserve(*args, **kwargs)
    os._exit(0)
ledger.reserve_bet = crash_after_reserve
service.play_round("player-1", "service-crash-debit", "service-crash-debit-op",
                   100, "BASE", [(0, 0, 0, 0, 0)])
"""
        self._run_crash_process(script)
        self.assertEqual(self.ledger.balance("player-1")["balance_minor"], 99900)
        recovered = RoundService(self.ledger).recover_round("service-crash-debit", "player-1")
        self.assertEqual(recovered["status"], "REFUNDED")
        self.assertEqual(self.ledger.balance("player-1")["balance_minor"], 100000)
        self.assertTrue(self.ledger.reconcile_round("service-crash-debit")["ok"])

    def test_service_process_exit_immediately_after_outcome_commit_recovers(self):
        script = r"""
import os, sys
from ganesha.wallet.ledger import WalletLedger
from ganesha.rgs.service import RoundService
from ganesha.game.engine import GameEngine
class ZeroMath:
    authority_status = "TEST_FIXTURE_ONLY"
    version = "zero-fixture"
    def evaluate_stops(self, stops, mode):
        board = [["A", "A", "A"] for _ in range(5)]
        return {"mode": mode, "board": board, "display_board": board,
                "payout_milli": 1000, "free_spins_awarded": 0, "scatter_count": 0}
    def award_free_spins(self, scatter_count, retrigger=False): return 0
ledger = WalletLedger(sys.argv[1])
service = RoundService(ledger, game_engine=GameEngine(ZeroMath()), allow_test_vectors_for_tests=True)
commit = ledger.commit_outcome
def crash_after_outcome(*args, **kwargs):
    result = commit(*args, **kwargs)
    os._exit(0)
ledger.commit_outcome = crash_after_outcome
service.play_round("player-1", "service-crash-outcome", "service-crash-outcome-op",
                   100, "BASE", [(0, 0, 0, 0, 0)])
"""
        self._run_crash_process(script)
        with sqlite_connect(self.ledger.database_path) as db:
            db.execute("UPDATE recovery_leases SET expires_at=0 WHERE round_id=?", ("service-crash-outcome",))
        self.assertEqual(self.ledger.balance("player-1")["balance_minor"], 99900)
        recovered = RoundService(self.ledger).recover_round("service-crash-outcome", "player-1")
        self.assertEqual(recovered["status"], "SETTLED")
        self.assertEqual(self.ledger.balance("player-1")["balance_minor"], 100000)
        self.assertTrue(self.ledger.reconcile_round("service-crash-outcome")["ok"])

    def test_service_process_exit_after_win_presented_before_settlement_recovers(self):
        script = r"""
import os, sys
from ganesha.wallet.ledger import WalletLedger
from ganesha.rgs.service import RoundService
from ganesha.game.engine import GameEngine
class ZeroMath:
    authority_status = "TEST_FIXTURE_ONLY"
    version = "zero-fixture"
    def evaluate_stops(self, stops, mode):
        board = [["A", "A", "A"] for _ in range(5)]
        return {"mode": mode, "board": board, "display_board": board,
                "payout_milli": 1000, "free_spins_awarded": 0, "scatter_count": 0}
    def award_free_spins(self, scatter_count, retrigger=False): return 0
ledger = WalletLedger(sys.argv[1])
service = RoundService(ledger, game_engine=GameEngine(ZeroMath()), allow_test_vectors_for_tests=True)
def crash_before_settle(*args, **kwargs):
    os._exit(0)
ledger.settle_round = crash_before_settle
service.play_round("player-1", "service-crash-win-presented", "service-crash-win-presented-op",
                   100, "BASE", [(0, 0, 0, 0, 0)])
"""
        self._run_crash_process(script)
        with sqlite_connect(self.ledger.database_path) as db:
            db.execute("UPDATE recovery_leases SET expires_at=0 WHERE round_id=?", ("service-crash-win-presented",))
        events = self.ledger.round_events("service-crash-win-presented")
        self.assertIn("WIN_PRESENTED", [event["event_type"] for event in events])
        self.assertEqual(self.ledger.balance("player-1")["balance_minor"], 99900)
        recovered = RoundService(self.ledger).recover_round("service-crash-win-presented", "player-1")
        self.assertEqual(recovered["status"], "SETTLED")
        self.assertEqual(self.ledger.balance("player-1")["balance_minor"], 100000)
        self.assertTrue(self.ledger.reconcile_round("service-crash-win-presented")["ok"])

    def test_concurrent_duplicate_debit_and_settlement_are_single_effect(self):
        def reserve():
            return self.ledger.reserve_bet("debit-concurrent", "round-concurrent", "player-1", 1000)
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: reserve(), range(8)))
        self.assertTrue(all(item == results[0] for item in results))
        self.assertEqual(self.ledger.balance("player-1")["balance_minor"], 99000)
        self.ledger.commit_outcome("round-concurrent", {"payout": 500}, 500, fencing_token=self._fencing_token("round-concurrent"))
        def settle():
            return self.ledger.settle_round("credit-concurrent", "round-concurrent", fencing_token=self._fencing_token("round-concurrent"))
        with ThreadPoolExecutor(max_workers=8) as pool:
            settlements = list(pool.map(lambda _: settle(), range(8)))
        self.assertTrue(all(item == settlements[0] for item in settlements))
        self.assertEqual(self.ledger.balance("player-1")["balance_minor"], 99500)
        self.assertEqual(len(self.ledger.journal_for_round("round-concurrent")), 2)

    def test_duplicate_round_cannot_be_debited_twice(self):
        self.ledger.reserve_bet("debit-1", "round-1", "player-1", 1000)
        with self.assertRaises(DuplicateOperation):
            self.ledger.reserve_bet("debit-2", "round-1", "player-1", 1000)

    def test_sqlite_begin_immediate_retries_after_external_writer_releases_lock(self):
        blocker = sqlite3.connect(self.ledger.database_path, timeout=1, isolation_level=None)
        blocker.execute("BEGIN IMMEDIATE")
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(
                    self.ledger.reserve_bet,
                    "debit:lock-retry", "round:lock-retry", "player-1", 100,
                    rng_commitment="TEST:LOCK-RETRY", max_payout_minor=1000,
                    round_mode="BASE", base_bet_minor=100,
                    generator_version="lock-retry-test", engine_version="lock-retry-test",
                )
                deadline = time.monotonic() + 5
                while self.ledger.write_lock_retry_count == 0 and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertGreater(self.ledger.write_lock_retry_count, 0)
                blocker.commit()
                result = future.result(timeout=10)
            self.assertEqual(result["status"], "BET_RESERVED")
        finally:
            blocker.close()

    def test_insufficient_funds_and_refund(self):
        with self.assertRaises(InsufficientFunds):
            self.ledger.reserve_bet("debit-1", "round-1", "player-1", 100001)
        self.ledger.reserve_bet("debit-1", "round-2", "player-1", 1000)
        self.ledger.refund_reserved_round("refund-1", "round-2", fencing_token=self._fencing_token("round-2"))
        self.assertEqual(self.ledger.balance("player-1")["balance_minor"], 100000)
        with self.assertRaises(InvalidRoundState):
            self.ledger.settle_round("credit-1", "round-2", fencing_token=self._fencing_token("round-2"))

    def test_outcome_is_immutable(self):
        self.ledger.reserve_bet("debit-1", "round-1", "player-1", 1000)
        self.ledger.commit_outcome("round-1", {"payout": 250}, 250, fencing_token=self._fencing_token("round-1"))
        with self.assertRaises(DuplicateOperation):
            self.ledger.commit_outcome("round-1", {"payout": 500}, 500, fencing_token=self._fencing_token("round-1"))

    def test_hmac_and_timestamp(self):
        secret = b"x" * 32
        payload = {"round_id": "r-1", "amount_minor": 100}
        signature = sign_payload(secret, payload)
        self.assertTrue(verify_payload(secret, payload, signature))
        self.assertFalse(verify_payload(secret, {"round_id": "r-1", "amount_minor": 101}, signature))
        self.assertTrue(timestamp_is_fresh(1000, now=1005, tolerance_seconds=10))
        self.assertFalse(timestamp_is_fresh(1000, now=1100, tolerance_seconds=10))

    def test_round_service_local_deterministic_four_scatter_uses_twelve_spins(self):
        service = RoundService(self.ledger, allow_test_vectors_for_tests=True)
        result = service.play_round(
            "player-1", "round-1", "op-1", 100, "BASE",
            [(0, 1, 2, 3, 4)] + [(1, 1, 1, 1, 1)] * 12,
        )
        self.assertEqual(result["outcome"]["base_result"]["scatter_count"], 4)
        self.assertEqual(result["outcome"]["initial_free_spins"], 12)
        self.assertEqual(result["outcome"]["free_spins_played"], 12)
        snapshot = self.ledger.round_snapshot("round-1")
        self.assertEqual(snapshot["round"]["mode"], "BASE")
        self.assertEqual(snapshot["round"]["status"], "SETTLED")
        self.assertEqual(sum(event["event_type"] == "FEATURE_SPIN_RESOLVED"
                             for event in snapshot["events"]), 12)
        journal = self.ledger.journal_for_round("round-1")
        self.assertEqual(sum(entry["entry_type"] == "BET_DEBIT" for entry in journal), 1)
        self.assertEqual(sum(entry["entry_type"] == "PAYOUT_CREDIT" for entry in journal), 1)
        self.assertTrue(self.ledger.reconcile_round("round-1")["ok"])

    def test_settlement_overflow_fails_closed_without_credit(self):
        self.ledger.create_account("player-max", "USD", (1 << 63) - 1)
        self.ledger.reserve_bet("debit-max", "round-max", "player-max", 1)
        self.ledger.commit_outcome("round-max", {"payout": 2}, 2, fencing_token=self._fencing_token("round-max"))
        with self.assertRaises(LedgerError):
            self.ledger.settle_round("credit-max", "round-max", fencing_token=self._fencing_token("round-max"))
        self.assertEqual(self.ledger.balance("player-max")["balance_minor"], (1 << 63) - 2)
        self.assertEqual(self.ledger.round_snapshot("round-max")["round"]["status"], "OUTCOME_COMMITTED")
        self.assertEqual(len(self.ledger.journal_for_round("round-max")), 1)

    def test_payout_cap_is_enforced_at_outcome_commit_and_settlement(self):
        self.ledger.reserve_bet("cap-debit", "round-cap", "player-1", 1000, max_payout_minor=2000)
        with self.assertRaises(LedgerError):
            self.ledger.commit_outcome("round-cap", {"payout": 2001}, 2001, fencing_token=self._fencing_token("round-cap"))
        self.assertEqual(self.ledger.round_snapshot("round-cap")["round"]["status"], "BET_RESERVED")
        self.ledger.commit_outcome("round-cap", {"payout": 2000}, 2000, fencing_token=self._fencing_token("round-cap"))
        with sqlite_connect(self.ledger.database_path) as db:
            db.execute("UPDATE rounds SET payout_minor=2001 WHERE round_id=?", ("round-cap",))
        with self.assertRaises(LedgerError):
            self.ledger.settle_round("cap-credit", "round-cap", fencing_token=self._fencing_token("round-cap"))
        self.assertEqual(self.ledger.balance("player-1")["balance_minor"], 99000)
        self.assertEqual(self.ledger.round_snapshot("round-cap")["round"]["status"], "OUTCOME_COMMITTED")

    def test_round_retry_is_bound_to_original_account(self):
        self.ledger.create_account("player-2", "USD", 50000)
        generator = HmacStopGenerator(b"a" * 32)
        service = RoundService(self.ledger, stop_generator=generator, allow_unapproved_math_for_tests=True)
        service.play_round("player-1", "round-owned", "op-owned", 100, "BASE")
        before = self.ledger.balance("player-2")["balance_minor"]
        with self.assertRaises(InvalidRoundState):
            service.play_round("player-2", "round-owned", "op-owned", 100, "BASE")
        self.assertEqual(self.ledger.balance("player-2")["balance_minor"], before)

    def test_round_service_rejects_boolean_and_out_of_range_bets(self):
        service = RoundService(self.ledger, stop_generator=HmacStopGenerator(b"b" * 32), allow_unapproved_math_for_tests=True)
        with self.assertRaises(ValueError):
            service.play_round("player-1", "round-bool", "op-bool", True, "BASE")
        with self.assertRaises(ValueError):
            service.play_round("player-1", "round-large", "op-large", 10**30, "BASE")
        with self.assertRaises(ValueError):
            service.play_round("player-1", "bad id", "op-invalid", 100, "BASE")

    def test_buy_modes_without_explicit_math_terms_fail_before_debit(self):
        service = RoundService(self.ledger, allow_unapproved_math_for_tests=True)
        before = self.ledger.balance("player-1")["balance_minor"]
        for mode in ("MAGIC_BUY", "EPIC_BUY"):
            with self.subTest(mode=mode):
                with self.assertRaises(BonusBuyTermsUnavailable):
                    service.play_round("player-1", "round-no-terms-" + mode.lower(),
                                        "op-no-terms-" + mode.lower(), 100, mode)
                self.assertEqual(self.ledger.balance("player-1")["balance_minor"], before)
                with self.assertRaises(InvalidRoundState):
                    self.ledger.round_snapshot("round-no-terms-" + mode.lower())

    def test_spoofed_canonical_status_string_cannot_enable_bonus_buy(self):
        class SpoofedApprovedMathPort:
            authority_status = "CANONICAL_APPROVED"
            version = "untrusted-string-only"
            def evaluate_stops(self, stops, mode): return {"mode": mode, "payout_milli": 0, "scatter_count": 0, "jackpot_triggered": False}
            def award_free_spins(self, scatter_count, retrigger=False): return 0
            def resolve_bonus_buy_terms(self, mode):
                return {"mode": mode, "initial_free_spins": 2,
                        "purchase_cost_multiplier_milli": 1500, "max_stop_vectors": 2}
        service = RoundService(self.ledger, game_engine=GameEngine(math_port=SpoofedApprovedMathPort()),
                               stop_generator=HmacStopGenerator(b"x" * 32))
        before = self.ledger.balance("player-1")["balance_minor"]
        with self.assertRaises(RuntimeError):
            service.play_round("player-1", "round-spoofed-buy", "op-spoofed-buy", 100, "MAGIC_BUY")
        self.assertEqual(self.ledger.balance("player-1")["balance_minor"], before)
        with self.assertRaises(InvalidRoundState):
            self.ledger.round_snapshot("round-spoofed-buy")

    def test_magic_buy_uses_only_explicit_test_fixture_terms(self):
        class TestBuyMathPort:
            authority_status = "TEST_FIXTURE_ONLY"
            version = "buy-test-fixture-v1"
            def resolve_bonus_buy_terms(self, mode):
                return {"mode": mode, "initial_free_spins": 2,
                        "purchase_cost_multiplier_milli": 1500, "max_stop_vectors": 2}
            def evaluate_stops(self, stops, mode): return {"mode": mode, "payout_milli": 0, "scatter_count": 0, "jackpot_triggered": False}
            def award_free_spins(self, scatter_count, retrigger=False): return 0
        service = RoundService(self.ledger, game_engine=GameEngine(math_port=TestBuyMathPort()),
                               allow_unapproved_math_for_tests=True, allow_test_vectors_for_tests=True)
        service.play_round("player-1", "round-magic-fixture", "op-magic-fixture", 100, "MAGIC_BUY",
                           internal_stop_vectors=[(0, 0, 0, 0, 0)] * 2)
        snapshot = self.ledger.round_snapshot("round-magic-fixture")
        self.assertEqual(snapshot["round"]["bet_minor"], 150)
        self.assertEqual(snapshot["round"]["status"], "SETTLED")
        self.assertTrue(self.ledger.reconcile_round("round-magic-fixture")["ok"])

    def test_epic_buy_uses_only_explicit_test_fixture_terms(self):
        class TestBuyMathPort:
            authority_status = "TEST_FIXTURE_ONLY"
            version = "buy-test-fixture-v1"
            def resolve_bonus_buy_terms(self, mode):
                return {"mode": mode, "initial_free_spins": 3,
                        "purchase_cost_multiplier_milli": 4000, "max_stop_vectors": 3}
            def evaluate_stops(self, stops, mode): return {"mode": mode, "payout_milli": 0, "scatter_count": 0, "jackpot_triggered": False}
            def award_free_spins(self, scatter_count, retrigger=False): return 0
        service = RoundService(self.ledger, game_engine=GameEngine(math_port=TestBuyMathPort()),
                               allow_unapproved_math_for_tests=True, allow_test_vectors_for_tests=True)
        service.play_round("player-1", "round-epic-fixture", "op-epic-fixture", 100, "EPIC_BUY",
                           internal_stop_vectors=[(0, 0, 0, 0, 0)] * 3)
        snapshot = self.ledger.round_snapshot("round-epic-fixture")
        self.assertEqual(snapshot["round"]["bet_minor"], 400)
        self.assertEqual(snapshot["round"]["status"], "SETTLED")
        self.assertTrue(self.ledger.reconcile_round("round-epic-fixture")["ok"])

    def test_hmac_stop_generator_is_deterministic(self):
        generator = HmacStopGenerator(b"r" * 32)
        self.assertEqual(generator.stop_vector("round-1", 0), generator.stop_vector("round-1", 0))
        self.assertNotEqual(generator.stop_vector("round-1", 0), generator.stop_vector("round-1", 1))
        self.assertEqual(len(generator.stop_vectors("round-1", 50)), 50)
        self.assertEqual(len(generator.commitment("round-1")), 64)

    def test_hmac_stop_generator_rejects_boolean_indices_and_invalid_round_ids(self):
        generator = HmacStopGenerator(b"strict-rng-input-validation-key-0001")
        for call in (
            lambda: generator.stop_vector("round", True),
            lambda: generator.stop_vector("", 0),
            lambda: generator.stop_vectors("round", True),
            lambda: generator.stop_vectors("", 0),
            lambda: generator.commitment(123),
        ):
            with self.assertRaises(ValueError):
                call()

    def test_draft_rng_golden_vector_is_version_bound(self):
        generator = HmacStopGenerator(b"ganesha-rng-golden-vector-secret-0001")
        self.assertEqual(generator.commitment("golden-round-001"),
                         "c32ec4586f055def5b19da22425a31de6622d5b9a97099dc2e69fa4b43c22dd9")
        self.assertEqual(generator.stop_vector("golden-round-001", 0), (10, 11, 11, 8, 2))
        self.assertEqual(generator.stop_vector("golden-round-001", 1), (8, 12, 11, 9, 0))

    def test_server_rng_round_retry_is_idempotent(self):
        generator = HmacStopGenerator(b"r" * 32)
        service = RoundService(self.ledger, stop_generator=generator, allow_unapproved_math_for_tests=True)
        first = service.play_round("player-1", "round-rng", "op-rng", 100, "BASE")
        self.assertEqual(self.ledger.round_snapshot("round-rng")["round"]["bet_minor"], 100)
        balance_after = self.ledger.balance("player-1")["balance_minor"]
        second = service.play_round("player-1", "round-rng", "op-rng", 100, "BASE")
        self.assertEqual(first, second)
        self.assertEqual(self.ledger.balance("player-1")["balance_minor"], balance_after)

    def test_nonce_is_one_time_and_signed_request_verifies(self):
        registry = NonceRegistry(os.path.join(self.tmp.name, "security.sqlite"))
        secret = b"s" * 32
        payload = {"round_id": "r-1", "amount_minor": 100}
        signature = sign_request(secret, payload, 1000, "nonce-1")
        self.assertTrue(verify_request(secret, payload, signature, 1000, "nonce-1", registry, now=1001))
        self.assertFalse(verify_request(secret, payload, signature, 1000, "nonce-1", registry, now=1001))
        self.assertFalse(verify_request(secret, payload, signature, 1002, "nonce-2", registry, now=1001))

if __name__ == "__main__":
    unittest.main()
