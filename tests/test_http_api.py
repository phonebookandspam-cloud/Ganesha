import http.client
import json
import os
import tempfile
import threading
import time
import unittest
from ganesha.math.rng import HmacStopGenerator
from ganesha.rgs.http_api import create_server
from ganesha.security.nonce import NonceRegistry
from ganesha.security.verification import sign_request
from ganesha.wallet.ledger import WalletLedger
from ganesha.game.runtime import GameRuntime
from tests.test_game_runtime import RuntimeMathPort

class HttpApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = WalletLedger(os.path.join(self.tmp.name, "wallet.sqlite"))
        self.ledger.create_account("player-1", "USD", 1000000)
        self.ledger.create_account("player-2", "USD", 1000000)
        self.session_id = "local-session-id-player-one"
        self.other_session_id = "local-session-id-player-two"
        self.secret = b"s" * 32
        self.other_secret = b"o" * 32
        self.frontend = os.path.join(self.tmp.name, "frontend")
        os.makedirs(self.frontend)
        with open(os.path.join(self.frontend, "index.html"), "w") as f: f.write("<!doctype html><title>local</title>")
        with open(os.path.join(self.frontend, "config.js"), "w") as f: f.write("window.GANESHA_CONFIG = {};")
        with open(os.path.join(self.frontend, "layout-v2.css"), "w") as f: f.write(":root { --stage-layout: 2; }")
        with open(os.path.join(self.frontend, "presentation-contract.js"), "w") as f:
            f.write("export const deriveExpandedWildDisplayBoard = () => 'WILD_GANESHA';")
        os.makedirs(os.path.join(self.frontend, "assets"))
        with open(os.path.join(self.frontend, "assets", "ganesha_wild_v14.svg"), "w") as f: f.write('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"></svg>')
        source_assets = os.path.join(os.path.dirname(__file__), "..", "frontend", "assets")
        for filename in ("a_icon_v15.svg", "chakra_icon_v15.svg", "elephant_icon_v15.svg",
                         "ganesha_wild_v15.svg", "k_icon_v15.svg", "lotus_scatter_v15.svg",
                         "modak_icon_v15.svg", "mouse_icon_v15.svg", "ganesha_temple_scene_v15.svg"):
            with open(os.path.join(source_assets, filename), "rb") as source:
                with open(os.path.join(self.frontend, "assets", filename), "wb") as target:
                    target.write(source.read())
        os.makedirs(os.path.join(self.frontend, "assets", "sfx"))
        for filename in ("reel-stop.wav", "wild-expansion.wav", "free-spins.wav", "win.wav"):
            with open(os.path.join(self.frontend, "assets", "sfx", filename), "wb") as f: f.write(b"RIFF0000WAVE")
        self.runtime = GameRuntime(RuntimeMathPort())
        self.server = create_server("127.0.0.1", 0, self.ledger,
                                    HmacStopGenerator(b"r" * 32),
                                    {self.session_id: {"account_id": "player-1", "secret": self.secret},
                                     self.other_session_id: {"account_id": "player-2", "secret": self.other_secret}},
                                    NonceRegistry(os.path.join(self.tmp.name, "nonces.sqlite")), self.frontend,
                                    enable_round_api=True, allow_unapproved_math_for_tests=True,
                                    enable_demo_api=True, enable_game_fixture_api=True,
                                    runtime=self.runtime,
                                    runtime_stop_provider=lambda _session: ([0] * 5, [[1] * 5] * 10))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.tmp.cleanup()

    def _signed_headers(self, method, path, body, nonce, other=False):
        timestamp = int(time.time())
        secret = self.other_secret if other else self.secret
        session_id = self.other_session_id if other else self.session_id
        payload = {"method": method, "path": path, "body": body}
        signature = sign_request(secret, payload, timestamp, nonce)
        return {"Content-Type": "application/json", "X-Session-ID": session_id,
                "X-Timestamp": str(timestamp), "X-Nonce": nonce, "X-Signature": signature}

    def _post(self, body, nonce):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        connection.request("POST", "/api/v1/rounds", body=json.dumps(body),
                           headers=self._signed_headers("POST", "/api/v1/rounds", body, nonce))
        response = connection.getresponse()
        data = json.loads(response.read().decode("utf-8"))
        connection.close()
        return response.status, data

    def test_authenticated_recovery_endpoint_settles_pending_outcome_and_exposes_verifiable_projection(self):
        round_id = "http-recover-pending"
        self.ledger.reserve_bet("http-recover-debit", round_id, "player-1", 100,
                                max_payout_minor=1000, round_mode="BASE", base_bet_minor=100,
                                engine_version="game-engine-sha256:" + "a" * 64)
        token = self.ledger.claim_recovery_lease(round_id, "http-test-owner")
        self.ledger.commit_outcome(round_id, {"mode": "BASE", "total_payout_milli": 500,
                                              "engine_version": "game-engine-sha256:" + "a" * 64},
                                   50, fencing_token=token)
        self.ledger.release_recovery_lease(round_id, "http-test-owner", token)
        path = "/api/v1/rounds/" + round_id + "/recover"
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        body = {}
        connection.request("POST", path, body=json.dumps(body),
                           headers=self._signed_headers("POST", path, body, "nonce-recover"))
        response = connection.getresponse()
        recovered = json.loads(response.read().decode("utf-8"))
        self.assertEqual(response.status, 200)
        self.assertEqual(recovered["contract"], "ganesha.game.recovery")
        self.assertEqual(recovered["status"], "SETTLED")
        self.assertTrue(recovered["recovered"])
        self.assertEqual(self.ledger.round_snapshot(round_id)["round"]["status"], "SETTLED")
        read_path = "/api/v1/rounds/" + round_id
        connection.request("GET", read_path,
                           headers=self._signed_headers("GET", read_path, None, "nonce-recover-read"))
        read_response = connection.getresponse()
        snapshot = json.loads(read_response.read().decode("utf-8"))
        self.assertEqual(read_response.status, 200)
        previous = "0" * 64
        import hashlib
        for event in snapshot["events"]:
            self.assertEqual(event["previous_hash"], previous)
            envelope = {key: event[key] for key in ("schema_version", "round_id", "sequence", "event_id", "event_type", "payload", "previous_hash")}
            expected = hashlib.sha256(json.dumps(envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")).hexdigest()
            self.assertEqual(event["event_hash"], expected)
            previous = expected
        self.assertEqual(snapshot["state"]["last_event_hash"], previous)
        self.assertTrue(self.ledger.reconcile_round(round_id)["ok"])
        connection.close()

    def test_recovery_endpoint_requires_account_scoped_hmac_and_empty_body(self):
        round_id = "http-recover-auth"
        self.ledger.reserve_bet("http-recover-auth-debit", round_id, "player-1", 100)
        path = "/api/v1/rounds/" + round_id + "/recover"
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.request("POST", path, body="{}", headers={"Content-Type": "application/json"})
        unauth = connection.getresponse()
        self.assertEqual(unauth.status, 401)
        unauth.read()
        body = {"account_id": "player-2"}
        connection.request("POST", path, body=json.dumps(body),
                           headers=self._signed_headers("POST", path, body, "nonce-recover-schema"))
        invalid = connection.getresponse()
        self.assertEqual(invalid.status, 400)
        invalid.read()
        body = {}
        connection.request("POST", path, body=json.dumps(body),
                           headers=self._signed_headers("POST", path, body, "nonce-recover-other", other=True))
        denied = connection.getresponse()
        self.assertEqual(denied.status, 404)
        denied.read()
        self.assertEqual(self.ledger.round_snapshot(round_id)["round"]["status"], "BET_RESERVED")
        connection.close()

    def test_frontend_static_routes_are_allowlisted(self):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.request("GET", "/")
        response = connection.getresponse()
        body = response.read().decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn("local", body)
        connection.request("GET", "/config.js")
        config_response = connection.getresponse()
        self.assertEqual(config_response.status, 200)
        config_body = config_response.read().decode("utf-8")
        self.assertNotIn(self.secret.hex(), config_body)
        connection.request("GET", "/favicon.ico")
        favicon_response = connection.getresponse()
        self.assertEqual(favicon_response.status, 204)
        favicon_response.read()
        connection.request("GET", "/assets/ganesha_wild_v14.svg")
        asset_response = connection.getresponse()
        self.assertEqual(asset_response.status, 200)
        self.assertIn("image/svg+xml", asset_response.getheader("Content-Type"))
        self.assertEqual(asset_response.getheader("X-Frame-Options"), "DENY")
        self.assertIn("form-action 'none'", asset_response.getheader("Content-Security-Policy"))
        self.assertIn("Content-Security-Policy", asset_response.headers)
        self.assertIsNone(asset_response.getheader("Access-Control-Allow-Origin"))
        asset_response.read()
        for filename in ("a_icon_v15.svg", "chakra_icon_v15.svg", "elephant_icon_v15.svg",
                         "ganesha_wild_v15.svg", "k_icon_v15.svg", "lotus_scatter_v15.svg",
                         "modak_icon_v15.svg", "mouse_icon_v15.svg", "ganesha_temple_scene_v15.svg"):
            connection.request("GET", "/assets/" + filename)
            current_art = connection.getresponse()
            current_body = current_art.read().decode("utf-8")
            self.assertEqual(current_art.status, 200, filename)
            self.assertIn("image/svg+xml", current_art.getheader("Content-Type"), filename)
            self.assertIn("<svg", current_body, filename)
        connection.request("GET", "/presentation-contract.js")
        presentation_response = connection.getresponse()
        presentation_body = presentation_response.read().decode("utf-8")
        self.assertEqual(presentation_response.status, 200)
        self.assertIn("deriveExpandedWildDisplayBoard", presentation_body)
        self.assertIn("WILD_GANESHA", presentation_body)
        connection.request("GET", "/layout-v2.css")
        layout_response = connection.getresponse()
        layout_body = layout_response.read().decode("utf-8")
        self.assertEqual(layout_response.status, 200)
        self.assertIn("text/css", layout_response.getheader("Content-Type"))
        self.assertIn("--stage-layout: 2", layout_body)
        for filename in ("reel-stop.wav", "wild-expansion.wav", "free-spins.wav", "win.wav"):
            connection.request("GET", "/assets/sfx/" + filename)
            sound_response = connection.getresponse()
            self.assertEqual(sound_response.status, 200, filename)
            self.assertIn(sound_response.getheader("Content-Type"), ("audio/wav", "audio/x-wav"))
            sound_response.read()
        connection.request("GET", "/assets/sfx/unlisted.wav")
        unlisted = connection.getresponse()
        self.assertEqual(unlisted.status, 404)
        unlisted.read()
        connection.request("GET", "/../wallet.sqlite")
        blocked = connection.getresponse()
        self.assertEqual(blocked.status, 404)
        blocked.read()
        connection.close()

    def test_health(self):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.request("GET", "/health")
        response = connection.getresponse()
        data = json.loads(response.read().decode("utf-8"))
        connection.close()
        self.assertEqual(response.status, 200)
        self.assertFalse(data["provider_connected"])
        self.assertTrue(data["round_api_enabled"])
        self.assertTrue(data["demo_api_enabled"])
        self.assertTrue(data["game_fixture_api_enabled"])

    def test_scripted_demo_api_is_idempotent_and_has_no_wallet_effect(self):
        before = self.ledger.balance("player-1")["balance_minor"]
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.request("POST", "/api/demo/sessions", body="{}",
                           headers={"Content-Type": "application/json"})
        created = connection.getresponse()
        session = json.loads(created.read().decode("utf-8"))
        self.assertEqual(created.status, 201)
        self.assertEqual(session["contract"], "ganesha.demo.events")
        session_id = session["session_id"]
        path = "/api/demo/sessions/" + session_id + "/spins"
        request_body = json.dumps({"request_id": "http-demo-request"})
        connection.request("POST", path, body=request_body,
                           headers={"Content-Type": "application/json"})
        first_response = connection.getresponse()
        first = json.loads(first_response.read().decode("utf-8"))
        self.assertEqual(first_response.status, 200)
        connection.request("POST", path, body=request_body,
                           headers={"Content-Type": "application/json"})
        retry_response = connection.getresponse()
        retry = json.loads(retry_response.read().decode("utf-8"))
        self.assertEqual(retry_response.status, 200)
        self.assertEqual(first, retry)
        connection.request("GET", "/api/demo/sessions/" + session_id)
        snapshot_response = connection.getresponse()
        snapshot = json.loads(snapshot_response.read().decode("utf-8"))
        connection.close()
        self.assertEqual(snapshot_response.status, 200)
        self.assertEqual(snapshot["spin_count"], 1)
        self.assertEqual(self.ledger.balance("player-1")["balance_minor"], before)
        self.assertEqual(self.ledger.pending_round_ids(), [])
        self.assertEqual(self.ledger.reconcile_account("player-1")["journal_delta_minor"], 0)

    def test_game_fixture_api_uses_engine_and_has_no_wallet_effect(self):
        before_balance = self.ledger.balance("player-1")["balance_minor"]
        before_journal = self.ledger.reconcile_account("player-1")["journal_delta_minor"]
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        connection.request("POST", "/api/demo/game-sessions", body="{}",
                           headers={"Content-Type": "application/json"})
        created = connection.getresponse()
        session = json.loads(created.read().decode("utf-8"))
        self.assertEqual(created.status, 201)
        self.assertEqual(session["classification"], "TEST_FIXTURE_ONLY")
        self.assertFalse(session["financial_effects"])
        session_id = session["session_id"]
        round_path = "/api/demo/game-sessions/" + session_id + "/rounds"
        request_body = json.dumps({"request_id": "engine-fixture-request"})
        connection.request("POST", round_path, body=request_body,
                           headers={"Content-Type": "application/json"})
        first_response = connection.getresponse()
        first = json.loads(first_response.read().decode("utf-8"))
        self.assertEqual(first_response.status, 200)
        self.assertEqual(first["contract"], "ganesha.game.presentation")
        self.assertEqual(first["state"]["status"], "COMPLETED")
        self.assertEqual(first["state"]["feature_spins_played"], 12)
        self.assertEqual(len(first["events"]), 106)
        connection.request("POST", round_path, body=request_body,
                           headers={"Content-Type": "application/json"})
        retry_response = connection.getresponse()
        retry = json.loads(retry_response.read().decode("utf-8"))
        self.assertEqual(retry_response.status, 200)
        self.assertEqual(first, retry)
        connection.request("GET", "/api/demo/game-sessions/" + session_id)
        snapshot_response = connection.getresponse()
        snapshot = json.loads(snapshot_response.read().decode("utf-8"))
        connection.close()
        self.assertEqual(snapshot_response.status, 200)
        self.assertEqual(snapshot["events"], first["events"])
        self.assertEqual(self.ledger.balance("player-1")["balance_minor"], before_balance)
        self.assertEqual(self.ledger.pending_round_ids(), [])
        self.assertEqual(self.ledger.reconcile_account("player-1")["journal_delta_minor"], before_journal)
        with self.assertRaises(Exception):
            self.ledger.round_snapshot(first["round_id"])

    def test_independent_runtime_api_executes_replayable_nonfinancial_round(self):
        before_balance = self.ledger.balance("player-1")["balance_minor"]
        before_journal = self.ledger.reconcile_account("player-1")["journal_delta_minor"]
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        connection.request("POST", "/api/runtime/sessions", body="{}",
                           headers={"Content-Type": "application/json"})
        created = connection.getresponse()
        session = json.loads(created.read().decode("utf-8"))
        self.assertEqual(created.status, 201)
        self.assertEqual(session["contract"], "ganesha.game.runtime")
        self.assertEqual(session["classification"], "NON_FINANCIAL_SIMULATION")
        self.assertFalse(session["financial_effects"])
        path = "/api/runtime/sessions/" + session["session_id"] + "/rounds"
        body = json.dumps({"request_id": "runtime-http-request"})
        connection.request("POST", path, body=body, headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        result = json.loads(response.read().decode("utf-8"))
        self.assertEqual(response.status, 200)
        self.assertEqual(result["state"]["status"], "COMPLETED")
        self.assertEqual(result["state"]["feature_spins_played"], 10)
        self.assertEqual(result["lifecycle_state"]["status"], "COMPLETED")
        self.assertEqual(len(result["lifecycle_events"]), 3)
        self.assertEqual(result["state"]["base_board"], result["outcome"]["base_result"]["board"])
        connection.request("GET", "/api/runtime/sessions/" + session["session_id"])
        snapshot_response = connection.getresponse()
        snapshot = json.loads(snapshot_response.read().decode("utf-8"))
        connection.close()
        self.assertEqual(snapshot_response.status, 200)
        self.assertEqual(snapshot["events"], result["events"])
        self.assertEqual(self.ledger.balance("player-1")["balance_minor"], before_balance)
        self.assertEqual(self.ledger.pending_round_ids(), [])
        self.assertEqual(self.ledger.reconcile_account("player-1")["journal_delta_minor"], before_journal)
        with self.assertRaises(Exception):
            self.ledger.round_snapshot(result["round_id"])

    def test_independent_runtime_http_lost_response_recovers_cached_result_without_second_round(self):
        before_balance = self.ledger.balance("player-1")["balance_minor"]
        before_journal = self.ledger.reconcile_account("player-1")["journal_delta_minor"]
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        connection.request("POST", "/api/runtime/sessions", body="{}",
                           headers={"Content-Type": "application/json"})
        created = connection.getresponse()
        session = json.loads(created.read().decode("utf-8"))
        self.assertEqual(created.status, 201)
        session_id = session["session_id"]
        path = "/api/runtime/sessions/" + session_id + "/rounds"
        body = json.dumps({"request_id": "runtime-lost-http-response"})

        # Dispatch the first request and close without reading its response. The
        # server may have committed the Runtime outcome before the socket closes.
        connection.request("POST", path, body=body,
                           headers={"Content-Type": "application/json"})
        connection.close()
        deadline = time.monotonic() + 5
        snapshot = self.runtime.snapshot(session_id)
        while snapshot["status"] != "COMPLETED" and time.monotonic() < deadline:
            time.sleep(0.01)
            snapshot = self.runtime.snapshot(session_id)
        self.assertEqual(snapshot["status"], "COMPLETED")

        retry = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        retry.request("POST", path, body=body, headers={"Content-Type": "application/json"})
        retry_response = retry.getresponse()
        cached = json.loads(retry_response.read().decode("utf-8"))
        retry.request("GET", "/api/runtime/sessions/" + session_id)
        snapshot_response = retry.getresponse()
        restored = json.loads(snapshot_response.read().decode("utf-8"))
        retry.close()

        self.assertEqual(retry_response.status, 200)
        self.assertEqual(snapshot_response.status, 200)
        self.assertEqual(cached["state"]["status"], "COMPLETED")
        self.assertEqual(cached["state"]["event_count"], 90)
        self.assertEqual(restored["events"], cached["events"])
        self.assertEqual(restored["outcome"], cached["outcome"])
        self.assertEqual(restored["lifecycle_events"], cached["lifecycle_events"])
        self.assertEqual(self.ledger.balance("player-1")["balance_minor"], before_balance)
        self.assertEqual(self.ledger.pending_round_ids(), [])
        self.assertEqual(self.ledger.reconcile_account("player-1")["journal_delta_minor"], before_journal)

    def test_static_preview_server_has_no_wager_endpoint_by_default(self):
        preview = create_server("127.0.0.1", 0, frontend_root=self.frontend, enable_round_api=False)
        thread = threading.Thread(target=preview.serve_forever, daemon=True)
        thread.start()
        try:
            port = preview.server_address[1]
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            connection.request("POST", "/api/v1/rounds", body='{}', headers={"Content-Type": "application/json"})
            response = connection.getresponse()
            data = json.loads(response.read().decode("utf-8"))
            connection.close()
            self.assertEqual(response.status, 404)
            self.assertEqual(data["error"], "ROUND_API_DISABLED_IN_PREVIEW")
            connection.request("POST", "/api/demo/sessions", body="{}", headers={"Content-Type": "application/json"})
            demo_response = connection.getresponse()
            demo_data = json.loads(demo_response.read().decode("utf-8"))
            self.assertEqual(demo_response.status, 404)
            self.assertEqual(demo_data["error"], "DEMO_API_DISABLED")
            connection.request("POST", "/api/demo/game-sessions", body="{}", headers={"Content-Type": "application/json"})
            fixture_response = connection.getresponse()
            fixture_data = json.loads(fixture_response.read().decode("utf-8"))
            self.assertEqual(fixture_response.status, 404)
            self.assertEqual(fixture_data["error"], "GAME_FIXTURE_API_DISABLED")
            connection.request("POST", "/api/runtime/sessions", body="{}", headers={"Content-Type": "application/json"})
            runtime_response = connection.getresponse()
            runtime_data = json.loads(runtime_response.read().decode("utf-8"))
            self.assertEqual(runtime_response.status, 404)
            self.assertEqual(runtime_data["error"], "RUNTIME_API_DISABLED")
        finally:
            preview.shutdown()
            preview.server_close()
            thread.join(timeout=2)

    def test_unauthenticated_game_fixture_api_refuses_non_loopback_bind(self):
        with self.assertRaisesRegex(ValueError, "loopback address"):
            create_server("0.0.0.0", 0, frontend_root=self.frontend, enable_game_fixture_api=True)

    def test_unauthenticated_demo_api_refuses_non_loopback_bind(self):
        with self.assertRaisesRegex(ValueError, "loopback address"):
            create_server("0.0.0.0", 0, frontend_root=self.frontend, enable_demo_api=True)

    def test_authenticated_round_and_retry(self):
        body = {"round_id": "http-round-1", "operation_id": "http-op-1", "bet_minor": 100, "mode": "BASE"}
        status, first = self._post(body, "nonce-a")
        self.assertEqual(status, 200)
        self.assertEqual(first["settlement"]["status"], "SETTLED")
        balance = self.ledger.balance("player-1")["balance_minor"]
        status, second = self._post(body, "nonce-b")
        self.assertEqual(status, 200)
        self.assertEqual(first, second)
        self.assertEqual(self.ledger.balance("player-1")["balance_minor"], balance)
        self.assertEqual(first["state"]["status"], "ENDED")
        self.assertTrue(first["events"])

    def test_round_state_readback_is_authenticated_and_account_scoped(self):
        body = {"round_id": "http-state-1", "operation_id": "http-state-op", "bet_minor": 100, "mode": "BASE"}
        status, _ = self._post(body, "nonce-state")
        self.assertEqual(status, 200)
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        path = "/api/v1/rounds/http-state-1"
        connection.request("GET", path, headers=self._signed_headers("GET", path, None, "nonce-state-read"))
        response = connection.getresponse()
        data = json.loads(response.read().decode("utf-8"))
        self.assertEqual(response.status, 200)
        self.assertEqual(data["contract"], "ganesha.game.events")
        self.assertEqual(data["schema_version"], 1)
        self.assertEqual(data["currency"], "USD")
        self.assertEqual(data["state"]["status"], "ENDED")
        self.assertTrue(data["events"])
        self.assertTrue(all(event["schema_version"] == 1 and event["round_id"] == "http-state-1"
                            for event in data["events"]))
        outcome_events = [event for event in data["events"] if event["event_type"] == "OUTCOME_COMMITTED"]
        self.assertTrue(outcome_events)
        self.assertEqual(len(outcome_events[-1]["payload"]["base_display_board"]), 5)
        self.assertNotIn("account_id", data["state"])
        self.assertNotIn("rng_commitment", data["state"])
        connection.request("GET", path, headers=self._signed_headers("GET", path, None, "nonce-state-other", other=True))
        denied = connection.getresponse()
        denied_data = json.loads(denied.read().decode("utf-8"))
        self.assertEqual(denied.status, 404)
        self.assertEqual(denied_data["error"], "NOT_FOUND")
        connection.request("GET", path)
        unauth = connection.getresponse()
        self.assertEqual(unauth.status, 401)
        unauth.read()
        connection.close()

    def test_client_cannot_supply_reel_stops(self):
        body = {"round_id": "http-round-2", "operation_id": "http-op-2", "bet_minor": 100,
                "mode": "BASE", "stops": [0, 0, 0, 0, 0]}
        status, data = self._post(body, "nonce-c")
        self.assertEqual(status, 400)
        self.assertEqual(data["error"], "REQUEST_SCHEMA_INVALID")

    def test_duplicate_json_keys_are_rejected(self):
        raw = '{"round_id":"http-dup","round_id":"http-other","operation_id":"http-op-dup","bet_minor":100,"mode":"BASE"}'
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        connection.request("POST", "/api/v1/rounds", body=raw, headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        data = json.loads(response.read().decode("utf-8"))
        connection.close()
        self.assertEqual(response.status, 400)
        self.assertEqual(data["error"], "INVALID_JSON")

    def test_boolean_bet_amount_is_rejected(self):
        body = {"round_id": "http-round-bool", "operation_id": "http-op-bool", "bet_minor": True, "mode": "BASE"}
        status, data = self._post(body, "nonce-bool")
        self.assertEqual(status, 400)
        self.assertEqual(data["error"], "BET_AMOUNT_INVALID")

    def test_nonce_replay_is_rejected(self):
        body = {"round_id": "http-round-3", "operation_id": "http-op-3", "bet_minor": 100, "mode": "BASE"}
        status, _ = self._post(body, "nonce-replay")
        self.assertEqual(status, 200)
        status, data = self._post({"round_id": "http-round-4", "operation_id": "http-op-4", "bet_minor": 100, "mode": "BASE"}, "nonce-replay")
        self.assertEqual(status, 401)
        self.assertEqual(data["error"], "REQUEST_AUTHENTICATION_FAILED")

    def test_request_hmac_binds_method_path_and_body(self):
        signed_body = {"round_id": "http-signed-1", "operation_id": "http-signed-op-1", "bet_minor": 100, "mode": "BASE"}
        changed_body = dict(signed_body, bet_minor=200)
        headers = self._signed_headers("POST", "/api/v1/rounds", signed_body, "nonce-tamper")
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        connection.request("POST", "/api/v1/rounds", body=json.dumps(changed_body), headers=headers)
        response = connection.getresponse()
        data = json.loads(response.read().decode("utf-8"))
        connection.close()
        self.assertEqual(response.status, 401)
        self.assertEqual(data["error"], "REQUEST_AUTHENTICATION_FAILED")
        self.assertEqual(self.ledger.balance("player-1")["balance_minor"], 1000000)

if __name__ == "__main__":
    unittest.main()
