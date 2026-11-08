"""Focused tests for the isolated standard-startup bootstrap constructors."""
import http.client
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from ganesha.demo.game_fixture import PresentationFixtureMathPort
from ganesha.game.engine import GameEngine
from ganesha.game.engine_payout_guard_r1 import EnginePayoutGuardError
from ganesha.math.config import CONFIG
from ganesha.math.rng import HmacStopGenerator
from ganesha.rgs.standard_startup_v1 import (
    GuardedGameEngine, _approved_engine, create_guarded_round_service, create_guarded_rgs_server,
)
from ganesha.security.nonce import NonceRegistry
from ganesha.security.verification import sign_request
from ganesha.wallet.ledger import WalletLedger
from ganesha.wallet.settlement_boundary_v2_r2 import GuardedWalletLedger, create_guarded_server


class _AdversarialMathPort:
    authority_status = "TEST_FIXTURE_ONLY"
    version = "adversarial-cap-test-v1"

    def __init__(self, base_payout=0, feature_payout=0, free_spins=0):
        self.base_payout = base_payout
        self.feature_payout = feature_payout
        self.free_spins = free_spins

    def evaluate_stops(self, stops, mode):
        payout = self.base_payout if mode == "BASE" else self.feature_payout
        return {
            "mode": mode, "payout_milli": payout, "raw_payout_milli": payout,
            "wild_multiplier": 1, "expanded_wild_reels": [],
            "max_win_capped": False, "scatter_count": 3 if mode == "BASE" and self.free_spins else 0,
            "free_spins_awarded": self.free_spins if mode == "BASE" else 0,
            "jackpot_triggered": False,
        }

    def award_free_spins(self, scatter_count, retrigger=False):
        return 0 if retrigger else self.free_spins


class StandardStartupBootstrapWorker25Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.ledger = WalletLedger(Path(self.temp.name) / "wallet.sqlite3")
        self.ledger.create_account("bootstrap-acct", "USD", 100_000)
        self.rng = HmacStopGenerator(b"bootstrap-test-key-material-000000")

    def tearDown(self):
        self.temp.cleanup()

    def test_service_constructor_wraps_wallet_and_engine_and_is_test_explicit(self):
        service = create_guarded_round_service(
            self.ledger, stop_generator=self.rng, game_engine=GameEngine(PresentationFixtureMathPort()),
            test_mode=True, allow_test_vectors=True,
        )
        self.assertIsInstance(service.ledger, GuardedWalletLedger)
        self.assertIsInstance(service.game_engine, GuardedGameEngine)
        self.assertTrue(service.allow_unapproved_math_for_tests)
        self.assertTrue(service.allow_test_vectors_for_tests)
        vectors = [((index % 13),) * 5 for index in range(11)]
        result = service.play_round(
            "bootstrap-acct", "bootstrap-round", "bootstrap-operation", 1_000,
            "BASE", internal_stop_vectors=vectors,
        )
        self.assertEqual(result["state"]["status"], "ENDED")
        self.assertEqual(result["settlement"]["payout_minor"], 1_500)

    def test_production_constructor_requires_explicit_approval_verifier(self):
        with self.assertRaisesRegex(RuntimeError, "approval verifier"):
            create_guarded_round_service(self.ledger, stop_generator=self.rng)
        with self.assertRaisesRegex(RuntimeError, "absent or invalid"):
            create_guarded_round_service(
                self.ledger, stop_generator=self.rng, game_engine=GameEngine(PresentationFixtureMathPort()),
                canonical_math_approval=lambda math_port: False,
            )

    def test_verified_production_constructor_disables_test_switches(self):
        service = create_guarded_round_service(
            self.ledger, stop_generator=self.rng, game_engine=GameEngine(PresentationFixtureMathPort()),
            canonical_math_approval=lambda math_port: True,
        )
        self.assertFalse(service.allow_unapproved_math_for_tests)
        self.assertFalse(service.allow_test_vectors_for_tests)

    def test_production_approval_rejects_math_port_replacement_during_verification(self):
        approved_port = PresentationFixtureMathPort()
        replacement_port = PresentationFixtureMathPort()
        engine = GameEngine(approved_port)

        def approval_with_side_effect(math_port):
            self.assertIs(math_port, approved_port)
            engine.math_port = replacement_port
            return True

        with self.assertRaisesRegex(RuntimeError, "changed during canonical Math approval"):
            create_guarded_round_service(
                self.ledger, stop_generator=self.rng, game_engine=engine,
                canonical_math_approval=approval_with_side_effect,
            )

    def test_production_approval_callback_does_not_enable_server_generated_rounds(self):
        service = create_guarded_round_service(
            self.ledger, stop_generator=self.rng, game_engine=GameEngine(PresentationFixtureMathPort()),
            canonical_math_approval=lambda math_port: True,
        )
        with self.assertRaisesRegex(RuntimeError, "Server-generated financial rounds are disabled"):
            service.play_round(
                "bootstrap-acct", "approval-capability-not-wired", "approval-capability-op",
                1_000, "BASE",
            )
        self.assertEqual(self.ledger.balance("bootstrap-acct")["balance_minor"], 100_000)
        self.assertEqual(self.ledger.pending_round_ids(), [])

    def test_engine_decorator_rejects_buy_modes_and_validates_base_outcome(self):
        guarded = _approved_engine(
            GameEngine(PresentationFixtureMathPort()), test_mode=True, canonical_math_approval=None,
        )
        feature_vectors = [((index % 13),) * 5 for index in range(10)]
        self.assertEqual(guarded.resolve_base_round((0,) * 5, feature_vectors)["mode"], "BASE")
        with self.assertRaisesRegex(RuntimeError, "disabled"):
            guarded.get_bonus_buy_terms("MAGIC_BUY")
        with self.assertRaisesRegex(RuntimeError, "disabled"):
            guarded.resolve_bonus_buy_round("EPIC_BUY", [])

    def test_guarded_engine_rejects_base_spin_cap_plus_one(self):
        guarded = _approved_engine(
            GameEngine(_AdversarialMathPort(base_payout=1_000_001)), test_mode=True, canonical_math_approval=None,
        )
        with self.assertRaises(EnginePayoutGuardError):
            guarded.resolve_base_round((0,) * 5, [])

    def test_guarded_engine_rejects_feature_spin_cap_plus_one(self):
        guarded = _approved_engine(
            GameEngine(_AdversarialMathPort(feature_payout=1_000_001, free_spins=10)),
            test_mode=True, canonical_math_approval=None,
        )
        vectors = [((index % 13),) * 5 for index in range(10)]
        with self.assertRaises(EnginePayoutGuardError):
            guarded.resolve_base_round((0,) * 5, vectors)

    def test_guarded_engine_rejects_noncanonical_round_cap_before_outcome_validation(self):
        engine = GameEngine(_AdversarialMathPort(base_payout=1_000_001, free_spins=10))
        engine.round_cap_milli = CONFIG.max_round_win_milli + 1
        with self.assertRaisesRegex(ValueError, "canonical configured limits"):
            _approved_engine(engine, test_mode=True, canonical_math_approval=None)

    def test_guarded_engine_cannot_be_constructed_without_startup_capability(self):
        with self.assertRaisesRegex(RuntimeError, "standard startup approval boundary"):
            GuardedGameEngine(GameEngine(PresentationFixtureMathPort()))

    def test_guarded_rgs_factory_enforces_loopback_and_approval(self):
        engine = GameEngine(PresentationFixtureMathPort())
        with self.assertRaisesRegex(RuntimeError, "approval verifier"):
            create_guarded_rgs_server("127.0.0.1", 0, self.ledger, stop_generator=self.rng,
                                      sessions={}, nonce_registry=object(), game_engine=engine)
        with self.assertRaisesRegex(ValueError, "loopback"):
            create_guarded_rgs_server("0.0.0.0", 0, self.ledger, stop_generator=self.rng,
                                      sessions={}, nonce_registry=object(), test_mode=True)
        server = create_guarded_rgs_server("127.0.0.1", 0, self.ledger, stop_generator=self.rng,
                                           sessions={}, nonce_registry=object(), test_mode=True)
        try:
            self.assertIsInstance(server.guarded_ledger, GuardedWalletLedger)
        finally:
            server.server_close()

    def test_low_level_guarded_server_rejects_raw_or_missing_game_engine(self):
        class SubclassedGuard(GuardedGameEngine):
            pass

        for engine in (None, GameEngine(PresentationFixtureMathPort()),
                       object.__new__(SubclassedGuard)):
            with self.subTest(engine=type(engine).__name__ if engine is not None else "None"):
                with self.assertRaisesRegex(TypeError, "GuardedGameEngine"):
                    create_guarded_server(
                        "127.0.0.1", 0, self.ledger, self.rng, {}, object(), game_engine=engine,
                    )
        forged_exact_type = object.__new__(GuardedGameEngine)
        with self.assertRaisesRegex(RuntimeError, "startup capability does not match"):
            create_guarded_server(
                "127.0.0.1", 0, self.ledger, self.rng, {}, object(), game_engine=forged_exact_type,
            )

    def test_low_level_guarded_server_requires_matching_startup_capability(self):
        test_engine = _approved_engine(
            GameEngine(PresentationFixtureMathPort()), test_mode=True, canonical_math_approval=None,
        )
        production_service = create_guarded_round_service(
            self.ledger, stop_generator=self.rng,
            game_engine=GameEngine(PresentationFixtureMathPort()),
            canonical_math_approval=lambda math_port: True,
        )
        cases = (
            (test_engine, False),
            (production_service.game_engine, True),
        )
        for engine, test_override in cases:
            with self.subTest(test_override=test_override), self.assertRaisesRegex(
                RuntimeError, "startup capability does not match"
            ):
                create_guarded_server(
                    "127.0.0.1", 0, self.ledger, self.rng, {}, object(),
                    game_engine=engine,
                    allow_unapproved_math_for_tests=test_override,
                )

    def test_standard_rgs_startup_runs_guarded_round_and_serves_linked_v2_evidence(self):
        secret = b"guarded-rgs-startup-test-secret-0000"
        session_id = "guarded-rgs-startup-session"
        server = create_guarded_rgs_server(
            "127.0.0.1", 0, self.ledger, stop_generator=self.rng,
            sessions={session_id: {"account_id": "bootstrap-acct", "secret": secret}},
            nonce_registry=NonceRegistry(Path(self.temp.name) / "rgs-nonces.sqlite"),
            game_engine=GameEngine(PresentationFixtureMathPort()), test_mode=True,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)

        def headers(method, path, body, nonce):
            timestamp = int(time.time())
            signature = sign_request(secret, {"method": method, "path": path, "body": body}, timestamp, nonce)
            return {
                "Content-Type": "application/json", "X-Session-ID": session_id,
                "X-Timestamp": str(timestamp), "X-Nonce": nonce, "X-Signature": signature,
            }

        try:
            self.assertIsInstance(server.guarded_ledger, GuardedWalletLedger)
            body = {"round_id": "guarded-rgs-startup-round", "operation_id": "guarded-rgs-startup-op",
                    "bet_minor": 1_000, "mode": "BASE"}
            connection.request("POST", "/api/v1/rounds", body=json.dumps(body),
                               headers=headers("POST", "/api/v1/rounds", body, "guarded-rgs-post-nonce"))
            response = connection.getresponse()
            result = json.loads(response.read().decode("utf-8"))
            self.assertEqual(response.status, 200, result)
            self.assertEqual(result["state"]["status"], "ENDED")
            self.assertEqual(result["settlement"]["payout_minor"], 1_500)

            path = "/api/v2/rounds/guarded-rgs-startup-round/financial-evidence?view=public"
            connection.request("GET", path, headers=headers("GET", path, None, "guarded-rgs-get-nonce"))
            evidence_response = connection.getresponse()
            evidence = json.loads(evidence_response.read().decode("utf-8"))
            self.assertEqual(evidence_response.status, 200, evidence)
            self.assertEqual(evidence["schema_version"], 2)
            self.assertEqual(len(evidence["events"]), 11)
            self.assertEqual(evidence["events"][0]["event_type"], "OUTCOME_COMMITTED")
            self.assertEqual(sum(event["event_type"] == "FEATURE_SPIN_RESOLVED" for event in evidence["events"]), 10)
            self.assertTrue({"raw_payout_milli", "wild_multiplier", "expanded_wild_reels",
                             "max_win_capped"}.issubset(evidence["events"][1]["payload"]))
            self.assertEqual(self.ledger.balance("bootstrap-acct")["balance_minor"], 100_500)
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
