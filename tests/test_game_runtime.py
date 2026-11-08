import copy
import json
import os
import sqlite3
import tempfile
import unittest

from ganesha.game.runtime import GameRuntime, GameRuntimeError, CLASSIFICATION
from ganesha.game.presentation import PRESENTATION_CLASSIFICATION
from ganesha.math.engine import EmbeddedEpicFeatureUnavailable, UnspecifiedMathRule
from ganesha.math.config import WILD


BASE_BOARD = [
    ["A", "SCATTER_LOTUS", "K"],
    ["MOUSE", "A", "SCATTER_LOTUS"],
    ["K", "ELEPHANT", "A"],
    ["SCATTER_LOTUS", "CHAKRA", "MOUSE"],
    ["A", "K", "MODAK"],
]
FEATURE_BOARD = [
    ["A", "K", "CHAKRA"], ["MOUSE", "A", "K"], [WILD, "A", "MODAK"],
    ["K", "CHAKRA", "A"], ["A", "MOUSE", "K"],
]
FEATURE_DISPLAY = copy.deepcopy(FEATURE_BOARD)
FEATURE_DISPLAY[2] = [WILD, WILD, WILD]
FOUR_SCATTER_BOARD = [["A", "A", "A"] for _ in range(5)]
for _reel, _row in ((0, 0), (1, 1), (2, 2), (4, 1)):
    FOUR_SCATTER_BOARD[_reel][_row] = "SCATTER_LOTUS"


class RuntimeMathPort:
    authority_status = "TEST_FIXTURE_ONLY"
    version = "runtime-math-fixture-v1"

    def __init__(self, scatter_board=None):
        self.base_board = copy.deepcopy(scatter_board or BASE_BOARD)
        self.feature_calls = 0

    def evaluate_stops(self, stops, mode):
        if mode == "BASE":
            count = sum(symbol == "SCATTER_LOTUS" for reel in self.base_board for symbol in reel)
            if count == 5:
                raise EmbeddedEpicFeatureUnavailable("5 Scatter requires the provider EPICBUY_V37 feature payload")
            if count >= 6:
                raise UnspecifiedMathRule("6+ Scatter reward is intentionally unspecified")
            return {"mode": "BASE", "board": copy.deepcopy(self.base_board),
                    "display_board": copy.deepcopy(self.base_board),
                    "raw_payout_milli": 1000, "payout_milli": 1000,
                    "wild_multiplier": 1, "expanded_wild_reels": [],
                    "max_win_capped": False, "scatter_count": count,
                    "free_spins_awarded": 10 if count == 3 else 12 if count == 4 else 0}
        self.feature_calls += 1
        return {"mode": "FREE_SPINS", "board": copy.deepcopy(FEATURE_BOARD),
                "display_board": copy.deepcopy(FEATURE_DISPLAY),
                "raw_payout_milli": 25, "payout_milli": 50,
                "wild_multiplier": 2, "max_win_capped": False,
                "scatter_count": 0, "expanded_wild_reels": [2],
                "jackpot_triggered": False}

    def award_free_spins(self, scatter_count, retrigger=False):
        if retrigger:
            return 0
        if scatter_count == 3:
            return 10
        if scatter_count == 4:
            return 12
        if scatter_count < 3:
            return 0
        if scatter_count == 5:
            raise EmbeddedEpicFeatureUnavailable("5 Scatter requires the provider EPICBUY_V37 feature payload")
        raise UnspecifiedMathRule("6+ Scatter reward is intentionally unspecified")


class RuntimeBuyMathPort(RuntimeMathPort):
    def resolve_bonus_buy_terms(self, mode):
        return {"mode": mode, "initial_free_spins": 2,
                "purchase_cost_multiplier_milli": 1500 if mode == "MAGIC_BUY" else 4000,
                "max_stop_vectors": 2}


class DevelopmentRuntimeMathPort(RuntimeMathPort):
    authority_status = "DEVELOPMENT_ONLY_NOT_CANONICAL"


class GameRuntimeTests(unittest.TestCase):
    def test_runtime_requires_explicit_math_port(self):
        with self.assertRaisesRegex(TypeError, "explicit MathPort"):
            GameRuntime(None)

    def test_independent_runtime_resolves_base_and_all_ten_free_spins(self):
        runtime = GameRuntime(RuntimeMathPort())
        created = runtime.create_session()
        result = runtime.play_base(created["session_id"], "request-1", [0] * 5, [[1] * 5] * 10)
        self.assertEqual(result["classification"], CLASSIFICATION)
        self.assertFalse(result["financial_effects"])
        self.assertEqual(result["events"][0]["payload"]["classification"], PRESENTATION_CLASSIFICATION)
        self.assertEqual(result["outcome"]["base_result"]["raw_payout_milli"], 1000)
        self.assertEqual(result["outcome"]["base_result"]["wild_multiplier"], 1)
        self.assertEqual(result["outcome"]["base_result"]["expanded_wild_reels"], [])
        self.assertIs(result["outcome"]["base_result"]["max_win_capped"], False)
        feature_result = result["outcome"]["feature_events"][0]["result"]
        self.assertEqual(feature_result["raw_payout_milli"], 25)
        self.assertEqual(feature_result["wild_multiplier"], 2)
        self.assertEqual(feature_result["expanded_wild_reels"], [2])
        self.assertIs(feature_result["max_win_capped"], False)
        feature_projection = next(
            event["payload"] for event in result["events"]
            if event["event_type"] == "FEATURE_SPIN_RESOLVED"
        )
        self.assertEqual(feature_projection["raw_payout_milli"], 25)
        self.assertEqual(feature_projection["multiplier"], 2)
        self.assertEqual(feature_projection["wild_reels"], [2])
        self.assertIs(feature_projection["max_win_capped"], False)
        self.assertEqual(result["state"]["classification"], CLASSIFICATION)
        self.assertEqual(runtime._sessions[created["session_id"]]["state"]["classification"], PRESENTATION_CLASSIFICATION)
        self.assertEqual(result["state"]["status"], "COMPLETED")
        self.assertEqual(result["state"]["feature_initial_spins"], 10)
        self.assertEqual(result["state"]["feature_spins_played"], 10)
        self.assertEqual(result["state"]["feature_spins_remaining"], 0)
        self.assertEqual(result["state"]["base_board"], result["outcome"]["base_result"]["board"])
        self.assertEqual(result["state"]["total_payout_milli"], result["outcome"]["total_payout_milli"])
        self.assertEqual(result["lifecycle_state"]["status"], "COMPLETED")
        self.assertFalse(result["lifecycle_state"]["financial_effects"])
        self.assertEqual(result["lifecycle_state"]["total_payout_milli"], result["state"]["total_payout_milli"])
        self.assertEqual(len(result["lifecycle_events"]), 3)
        replayed = runtime.replay(created["session_id"])
        self.assertEqual(replayed, result["state"])
        self.assertEqual(replayed["classification"], CLASSIFICATION)
        self.assertEqual(runtime.snapshot(created["session_id"])["state"]["classification"], CLASSIFICATION)

    def test_independent_runtime_resolves_four_scatter_and_all_twelve_free_spins(self):
        runtime = GameRuntime(RuntimeMathPort(FOUR_SCATTER_BOARD))
        created = runtime.create_session()
        result = runtime.play_base(
            created["session_id"], "request-four-scatter", [0] * 5, [[1] * 5] * 12,
        )
        self.assertEqual(result["outcome"]["initial_free_spins"], 12)
        self.assertEqual(result["outcome"]["free_spins_played"], 12)
        self.assertEqual(result["state"]["feature_initial_spins"], 12)
        self.assertEqual(result["state"]["feature_spins_played"], 12)
        self.assertEqual(result["state"]["status"], "COMPLETED")
        self.assertEqual(runtime.replay(created["session_id"]), result["state"])

    def test_runtime_never_exposes_mutable_math_authority_as_provenance(self):
        runtime = GameRuntime(DevelopmentRuntimeMathPort())
        session_id = runtime.create_session()["session_id"]
        response = runtime.play_base(session_id, "development-authority", [0] * 5, [[1] * 5] * 10)
        self.assertEqual(response["classification"], CLASSIFICATION)
        self.assertNotIn("math_authority", response)
        self.assertNotIn("math_authority", response["outcome"])
        snapshot = runtime.snapshot(session_id)
        self.assertEqual(snapshot["classification"], CLASSIFICATION)
        self.assertNotIn("math_authority", snapshot["outcome"])
        retry = runtime.play_base(session_id, "development-authority", [0] * 5, [[1] * 5] * 10)
        self.assertNotIn("math_authority", retry)
        self.assertNotIn("math_authority", retry["outcome"])

    def test_same_request_is_idempotent_and_response_mutation_isolated(self):
        runtime = GameRuntime(RuntimeMathPort())
        session = runtime.create_session()["session_id"]
        first = runtime.play_base(session, "same-request", [0] * 5, [[1] * 5] * 10)
        first["state"]["total_payout_milli"] = 999999
        second = runtime.play_base(session, "same-request", [0] * 5, [[1] * 5] * 10)
        self.assertEqual(second["state"]["total_payout_milli"], 1500)
        self.assertEqual(runtime.replay(session)["total_payout_milli"], 1500)

    def test_same_request_id_rejects_different_input_vectors(self):
        runtime = GameRuntime(RuntimeMathPort())
        session = runtime.create_session()["session_id"]
        runtime.play_base(session, "same-request", [0] * 5, [[1] * 5] * 10)
        with self.assertRaisesRegex(GameRuntimeError, "different inputs"):
            runtime.play_base(session, "same-request", [9] * 5, [[1] * 5] * 10)
        with self.assertRaisesRegex(GameRuntimeError, "different inputs"):
            runtime.play_base(session, "same-request", [0] * 5, [[2] * 5] * 10)

    def test_new_request_cannot_start_second_round_in_same_session(self):
        runtime = GameRuntime(RuntimeMathPort())
        session = runtime.create_session()["session_id"]
        runtime.play_base(session, "request-1", [0] * 5, [[1] * 5] * 10)
        with self.assertRaisesRegex(GameRuntimeError, "already has a committed outcome"):
            runtime.play_base(session, "request-2", [0] * 5, [])

    def test_five_and_six_plus_scatter_fail_closed_without_embedded_epic_payload(self):
        for count in (5, 6):
            board = [["A", "A", "A"] for _ in range(5)]
            for reel, row in [(0, 0), (1, 1), (2, 2), (3, 0), (4, 1), (0, 2)][:count]:
                board[reel][row] = "SCATTER_LOTUS"
            runtime = GameRuntime(RuntimeMathPort(board))
            session = runtime.create_session()["session_id"]
            with self.subTest(scatter_count=count), self.assertRaises(GameRuntimeError):
                runtime.play_base(session, "request", [0] * 5, [])

    def test_magic_and_epic_buy_validation_is_separate_and_never_debits(self):
        runtime = GameRuntime(RuntimeBuyMathPort())
        session = runtime.create_session()["session_id"]
        magic = runtime.validate_buy(session, "magic-1", "MAGIC_BUY")
        epic = runtime.validate_buy(session, "epic-1", "EPIC_BUY")
        self.assertEqual(magic["terms"]["mode"], "MAGIC_BUY")
        self.assertEqual(epic["terms"]["mode"], "EPIC_BUY")
        for result in (magic, epic):
            self.assertFalse(result["purchase_executed"])
            self.assertFalse(result["debit_created"])
            self.assertFalse(result["financial_effects"])

    def test_buy_validation_fails_closed_without_explicit_terms(self):
        runtime = GameRuntime(RuntimeMathPort())
        session = runtime.create_session()["session_id"]
        with self.assertRaisesRegex(GameRuntimeError, "validation unavailable"):
            runtime.validate_buy(session, "buy-1", "MAGIC_BUY")
        with self.assertRaisesRegex(GameRuntimeError, "validation unavailable"):
            runtime.validate_buy(session, "buy-2", "EPIC_BUY")

    def test_sqlite_runtime_restores_buy_validation_only_when_full_record_matches_math_port(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "runtime.sqlite")
            runtime = GameRuntime(RuntimeBuyMathPort(), storage_path=path)
            session_id = runtime.create_session()["session_id"]
            expected = runtime.validate_buy(session_id, "buy-restore", "MAGIC_BUY")
            runtime.close()

            restored = GameRuntime(RuntimeBuyMathPort(), storage_path=path)
            self.assertEqual(restored.validate_buy(session_id, "buy-restore", "MAGIC_BUY"), expected)
            restored.close()

    def test_sqlite_runtime_rejects_tampered_persisted_buy_validation(self):
        mutations = (
            lambda result: result["terms"].update(purchase_cost_multiplier_milli=999999),
            lambda result: result.update(session_id="another-session"),
            lambda result: result.update(classification="TEST_FIXTURE_ONLY"),
            lambda result: result.update(financial_effects=True),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, "runtime.sqlite")
                runtime = GameRuntime(RuntimeBuyMathPort(), storage_path=path)
                session_id = runtime.create_session()["session_id"]
                runtime.validate_buy(session_id, "buy-tamper", "MAGIC_BUY")
                runtime.close()

                db = sqlite3.connect(path)
                row = db.execute(
                    "SELECT payload_json FROM game_runtime_sessions WHERE session_id=?", (session_id,)
                ).fetchone()
                payload = json.loads(row[0])
                mutation(payload["buy_validations"][0][2])
                db.execute(
                    "UPDATE game_runtime_sessions SET payload_json=? WHERE session_id=?",
                    (json.dumps(payload), session_id),
                )
                db.commit()
                db.close()

                with self.assertRaisesRegex(GameRuntimeError, "failed closed validation"):
                    GameRuntime(RuntimeBuyMathPort(), storage_path=path)

    def test_sqlite_runtime_restores_event_state_and_idempotency_after_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "runtime.sqlite")
            first_runtime = GameRuntime(RuntimeMathPort(), storage_path=path)
            session_id = first_runtime.create_session()["session_id"]
            first = first_runtime.play_base(session_id, "durable-request", [0] * 5, [[1] * 5] * 10)
            first_runtime.close()

            restored = GameRuntime(RuntimeMathPort(), storage_path=path)
            self.assertEqual(restored.snapshot(session_id)["state"], first["state"])
            self.assertEqual(restored.replay(session_id), first["state"])
            retry = restored.play_base(session_id, "durable-request", [0] * 5, [[1] * 5] * 10)
            self.assertEqual(retry, first)
            with self.assertRaisesRegex(GameRuntimeError, "different inputs"):
                restored.play_base(session_id, "durable-request", [9] * 5, [[1] * 5] * 10)
            restored.close()

    def test_sqlite_runtime_rejects_tampered_persisted_event_stream(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "runtime.sqlite")
            runtime = GameRuntime(RuntimeMathPort(), storage_path=path)
            session_id = runtime.create_session()["session_id"]
            runtime.play_base(session_id, "tamper-request", [0] * 5, [[1] * 5] * 10)
            runtime.close()
            db = sqlite3.connect(path)
            row = db.execute("SELECT payload_json FROM game_runtime_sessions WHERE session_id=?", (session_id,)).fetchone()
            payload = json.loads(row[0])
            payload["events"][1]["payload"]["symbols"][0] = "FORGED"
            db.execute("UPDATE game_runtime_sessions SET payload_json=? WHERE session_id=?",
                       (json.dumps(payload), session_id))
            db.commit()
            db.close()
            with self.assertRaisesRegex(GameRuntimeError, "failed closed validation"):
                GameRuntime(RuntimeMathPort(), storage_path=path)

    def test_sqlite_restore_rejects_tampered_outcome_feature_trace_and_cached_response(self):
        for mutation in (
            lambda payload: payload["outcome"]["base_result"].update(payout_milli=777777),
            lambda payload: payload["outcome"]["feature_events"][0]["result"].update(payout_milli=777777),
            lambda payload: payload["requests"]["tamper-request"]["outcome"]["base_result"].update(payout_milli=777777),
            lambda payload: payload["requests"]["tamper-request"].update(math_authority="FORGED"),
        ):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, "runtime.sqlite")
                runtime = GameRuntime(RuntimeMathPort(), storage_path=path)
                session_id = runtime.create_session()["session_id"]
                runtime.play_base(session_id, "tamper-request", [0] * 5, [[1] * 5] * 10)
                runtime.close()
                db = sqlite3.connect(path)
                row = db.execute("SELECT payload_json FROM game_runtime_sessions WHERE session_id=?", (session_id,)).fetchone()
                payload = json.loads(row[0])
                mutation(payload)
                db.execute("UPDATE game_runtime_sessions SET payload_json=? WHERE session_id=?",
                           (json.dumps(payload), session_id))
                db.commit()
                db.close()
                with self.assertRaisesRegex(GameRuntimeError, "failed closed validation"):
                    GameRuntime(RuntimeMathPort(), storage_path=path)

    def test_sqlite_commit_failure_does_not_publish_completed_memory_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "runtime.sqlite")
            runtime = GameRuntime(RuntimeMathPort(), storage_path=path)
            session_id = runtime.create_session()["session_id"]
            runtime._db.execute(
                "CREATE TRIGGER fail_runtime_update BEFORE UPDATE ON game_runtime_sessions "
                "BEGIN SELECT RAISE(ABORT, 'forced commit failure'); END"
            )
            with self.assertRaisesRegex(sqlite3.IntegrityError, "forced commit failure"):
                runtime.play_base(session_id, "commit-failure", [0] * 5, [[1] * 5] * 10)
            self.assertEqual(runtime.snapshot(session_id)["status"], "CREATED")
            runtime._db.execute("DROP TRIGGER fail_runtime_update")
            runtime.close()
            restored = GameRuntime(RuntimeMathPort(), storage_path=path)
            self.assertEqual(restored.snapshot(session_id)["status"], "CREATED")
            restored.close()

    def test_sqlite_runtime_rejects_math_port_version_change_on_restore(self):
        class NewMathVersion(RuntimeMathPort):
            version = "runtime-math-fixture-v2"
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "runtime.sqlite")
            runtime = GameRuntime(RuntimeMathPort(), storage_path=path)
            runtime.create_session()
            runtime.close()
            with self.assertRaisesRegex(GameRuntimeError, "failed closed validation"):
                GameRuntime(NewMathVersion(), storage_path=path)


if __name__ == "__main__":
    unittest.main()
