"""Local RGS HTTP adapter with opaque session IDs, HMAC requests and server-side outcomes.

This is a development adapter. Production authentication must follow the Provider contract.
"""
import json
import hashlib
import ipaddress
import logging
import mimetypes
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from ganesha.rgs.service import RoundService
from ganesha.demo.session import DemoSessionError, DemoSessionStore
from ganesha.demo.game_fixture import GameFixtureSessionError, GameFixtureSessionStore
from ganesha.game.runtime import GameRuntime, GameRuntimeError
from ganesha.security.verification import verify_request
from ganesha.wallet.ledger import InsufficientFunds, DuplicateOperation, InvalidRoundState

MAX_BODY_BYTES = 65536
AUDIT_LOG = logging.getLogger("ganesha.rgs.audit")


def make_handler(ledger=None, stop_generator=None, sessions=None, nonce_registry=None, frontend_root=None,
                 enable_round_api=False, game_engine=None, allow_unapproved_math_for_tests=False,
                 enable_demo_api=False, enable_game_fixture_api=False, runtime=None,
                 runtime_stop_provider=None):
    if enable_round_api:
        if ledger is None or stop_generator is None or nonce_registry is None or not isinstance(sessions, dict):
            raise ValueError("Enabled local round API requires ledger, stop generator, sessions and nonce registry")
        for session_id, session in sessions.items():
            if (not isinstance(session_id, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{16,128}", session_id)
                    or not isinstance(session, dict)
                    or not isinstance(session.get("account_id"), str)
                    or not isinstance(session.get("secret"), bytes) or len(session["secret"]) < 32):
                raise ValueError("Local sessions require an opaque session id, account_id and 32-byte HMAC secret")
        service = RoundService(ledger, game_engine=game_engine, stop_generator=stop_generator,
                               allow_unapproved_math_for_tests=allow_unapproved_math_for_tests)
    else:
        service = None
    demo_store = DemoSessionStore() if enable_demo_api else None
    game_fixture_store = GameFixtureSessionStore() if enable_game_fixture_api else None
    if (runtime is None) != (runtime_stop_provider is None):
        raise ValueError("Runtime API requires both an explicit GameRuntime and trusted stop-vector provider")
    if runtime is not None and not isinstance(runtime, GameRuntime):
        raise TypeError("runtime must be an explicit GameRuntime instance")
    sessions = sessions if sessions is not None else {}
    static_root = Path(frontend_root).resolve() if frontend_root else None
    class Handler(BaseHTTPRequestHandler):
        server_version = "GaneshaLocalRGS/0.2"

        def _security_headers(self):
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
            self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")

        def _json(self, status, value):
            raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self._security_headers()
            self.end_headers()
            try:
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                # A caller may disconnect after the business transaction has
                # committed but before receiving its response. Do not attempt
                # a second HTTP error response on the already-closed socket;
                # the caller must reconcile by request_id/readback.
                AUDIT_LOG.warning("http_response_client_disconnected method=%s path=%s status=%d",
                                  self.command, self.path.split("?", 1)[0], status)
            error_code = value.get("error") if isinstance(value, dict) else None
            AUDIT_LOG.info("http_response method=%s path=%s status=%d error=%s",
                           self.command, self.path.split("?", 1)[0], status, error_code or "-")

        def _authenticate(self, method, payload):
            session_id = self.headers.get("X-Session-ID", "")
            session = sessions.get(session_id)
            if not isinstance(session, dict):
                return None
            try:
                timestamp = int(self.headers.get("X-Timestamp", ""))
            except ValueError:
                return None
            nonce = self.headers.get("X-Nonce", "")
            signature = self.headers.get("X-Signature", "")
            signed_payload = {"method": method, "path": self.path, "body": payload}
            try:
                valid = verify_request(session["secret"], signed_payload, signature,
                                       timestamp, nonce, nonce_registry, now=int(time.time()))
            except (KeyError, TypeError, ValueError):
                valid = False
            return session["account_id"] if valid else None

        def _static(self, requested):
            if static_root is None:
                return self._json(404, {"error": "STATIC_FRONTEND_DISABLED"})
            allowed = {
                "/": "index.html", "/index.html": "index.html",
                "/style.css": "style.css", "/layout-v2.css": "layout-v2.css",
                "/app.js": "app.js", "/config.js": "config.js",
                "/presentation-contract.js": "presentation-contract.js",
                "/assets/a_icon_v15.svg": "assets/a_icon_v15.svg",
                "/assets/chakra_icon_v15.svg": "assets/chakra_icon_v15.svg",
                "/assets/elephant_icon_v15.svg": "assets/elephant_icon_v15.svg",
                "/assets/ganesha_wild_v15.svg": "assets/ganesha_wild_v15.svg",
                "/assets/k_icon_v15.svg": "assets/k_icon_v15.svg",
                "/assets/lotus_scatter_v15.svg": "assets/lotus_scatter_v15.svg",
                "/assets/modak_icon_v15.svg": "assets/modak_icon_v15.svg",
                "/assets/mouse_icon_v15.svg": "assets/mouse_icon_v15.svg",
                "/assets/ganesha_temple_scene_v15.svg": "assets/ganesha_temple_scene_v15.svg",
                # Retain the exact legacy preview routes for historical QA
                # reproducibility; the active frontend manifest uses v15 only.
                "/assets/a_icon_v14.svg": "assets/a_icon_v14.svg",
                "/assets/chakra_icon_v14.svg": "assets/chakra_icon_v14.svg",
                "/assets/elephant_icon_v14.svg": "assets/elephant_icon_v14.svg",
                "/assets/ganesha_wild_v14.svg": "assets/ganesha_wild_v14.svg",
                "/assets/k_icon_v14.svg": "assets/k_icon_v14.svg",
                "/assets/lotus_scatter_v14.svg": "assets/lotus_scatter_v14.svg",
                "/assets/modak_icon_v14.svg": "assets/modak_icon_v14.svg",
                "/assets/mouse_icon_v14.svg": "assets/mouse_icon_v14.svg",
                "/assets/ganesha_temple_scene_v14.png": "assets/ganesha_temple_scene_v14.png",
                "/assets/sfx/reel-stop.wav": "assets/sfx/reel-stop.wav",
                "/assets/sfx/wild-expansion.wav": "assets/sfx/wild-expansion.wav",
                "/assets/sfx/free-spins.wav": "assets/sfx/free-spins.wav",
                "/assets/sfx/win.wav": "assets/sfx/win.wav",
            }
            filename = allowed.get(requested)
            if not filename:
                return self._json(404, {"error": "NOT_FOUND"})
            path = (static_root / filename).resolve()
            if static_root not in path.parents or not path.is_file():
                return self._json(404, {"error": "NOT_FOUND"})
            content = path.read_bytes()
            content_type, _ = mimetypes.guess_type(filename)
            content_type = content_type or "application/octet-stream"
            if content_type.startswith("text/") or content_type in ("application/javascript", "image/svg+xml"):
                content_type += "; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self._security_headers()
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, fmt, *args):
            return

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/favicon.ico":
                self.send_response(204)
                self.send_header("Cache-Control", "no-store")
                self._security_headers()
                self.end_headers()
                return
            if path == "/health":
                return self._json(200, {"status": "ok", "environment": "local-development",
                                        "provider_connected": False,
                                        "round_api_enabled": bool(enable_round_api),
                                        "demo_api_enabled": bool(enable_demo_api),
                                        "game_fixture_api_enabled": bool(enable_game_fixture_api),
                                        "runtime_api_enabled": runtime is not None})
            if path == "/api/demo/sessions":
                if demo_store is None:
                    return self._json(404, {"error": "DEMO_API_DISABLED"})
                return self._json(405, {"error": "METHOD_NOT_ALLOWED"})
            if path.startswith("/api/demo/sessions/"):
                if demo_store is None:
                    return self._json(404, {"error": "DEMO_API_DISABLED"})
                parts = path.split("/")
                if len(parts) == 5 and parts[3] == "sessions" and re.fullmatch(r"[a-f0-9]{32}", parts[4]):
                    try:
                        return self._json(200, demo_store.snapshot(parts[4]))
                    except DemoSessionError:
                        return self._json(404, {"error": "DEMO_SESSION_NOT_FOUND"})
                return self._json(404, {"error": "NOT_FOUND"})
            fixture_match = re.fullmatch(r"/api/demo/game-sessions/([a-f0-9]{32})", path)
            if fixture_match:
                if game_fixture_store is None:
                    return self._json(404, {"error": "GAME_FIXTURE_API_DISABLED"})
                try:
                    return self._json(200, game_fixture_store.snapshot(fixture_match.group(1)))
                except GameFixtureSessionError:
                    return self._json(404, {"error": "GAME_FIXTURE_SESSION_NOT_FOUND"})
            runtime_match = re.fullmatch(r"/api/runtime/sessions/([a-f0-9]{32})", path)
            if runtime_match:
                if runtime is None:
                    return self._json(404, {"error": "RUNTIME_API_DISABLED"})
                try:
                    return self._json(200, runtime.snapshot(runtime_match.group(1)))
                except GameRuntimeError:
                    return self._json(404, {"error": "RUNTIME_SESSION_NOT_FOUND"})
            if path.startswith("/api/v1/rounds/"):
                if not enable_round_api:
                    return self._json(404, {"error": "ROUND_API_DISABLED_IN_PREVIEW"})
                round_id = path[len("/api/v1/rounds/"):]
                if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", round_id):
                    return self._json(404, {"error": "NOT_FOUND"})
                account_id = self._authenticate("GET", None)
                if not account_id:
                    return self._json(401, {"error": "REQUEST_AUTHENTICATION_FAILED"})
                try:
                    snapshot = ledger.round_snapshot(round_id)
                    if snapshot["round"]["account_id"] != account_id:
                        return self._json(404, {"error": "NOT_FOUND"})
                    state = ledger.round_state(round_id)
                except Exception:
                    return self._json(404, {"error": "NOT_FOUND_OR_INVALID_ROUND"})
                public_payload_fields = {
                    "ROUND_OPENED": ("mode",),
                    "BET_RESERVED": ("currency", "debit_minor"),
                    "RNG_COMMITTED": ("generator_version",),
                    "FEATURE_STARTED": ("feature", "initial_spins"),
                    "FEATURE_SPIN_RESOLVED": ("spin_number", "stops", "payout_milli", "retrigger_awarded", "remaining_spins", "board", "display_board"),
                    "FEATURE_ENDED": ("spins_played", "payout_milli", "termination_reason"),
                    "OUTCOME_COMMITTED": ("payout_minor", "engine_version", "base_board", "base_display_board"),
                    "WIN_PRESENTED": ("payout_minor",),
                    "SETTLED": ("credit_minor", "currency"),
                    "REFUNDED": ("refund_minor", "currency"),
                    "END_ROUND": ("terminal_status",),
                }
                events = []
                public_previous_hash = "0" * 64
                for event in snapshot["events"]:
                    allowed_fields = public_payload_fields.get(event["event_type"], ())
                    public_event = {"schema_version": event["schema_version"], "round_id": event["round_id"],
                                    "sequence": event["sequence"], "event_id": event["event_id"],
                                    "event_type": event["event_type"],
                                    "payload": {key: event["payload"][key] for key in allowed_fields if key in event["payload"]},
                                    "previous_hash": public_previous_hash}
                    public_event["event_hash"] = hashlib.sha256(
                        json.dumps(public_event, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
                    ).hexdigest()
                    public_previous_hash = public_event["event_hash"]
                    events.append(public_event)
                public_state_fields = ("status", "mode", "payout_minor", "feature", "feature_spins_played",
                                       "feature_spins_remaining", "event_count", "last_event_hash", "win_presented", "ended")
                public_state = {key: state[key] for key in public_state_fields if key in state}
                public_state["last_event_hash"] = public_previous_hash
                return self._json(200, {"contract": "ganesha.game.events", "schema_version": 1,
                                        "round_id": round_id, "status": snapshot["round"]["status"],
                                        "mode": snapshot["round"]["mode"], "currency": snapshot["round"]["currency"],
                                        "state": public_state,
                                        "events": events})
            return self._static(path)

        def do_POST(self):
            if self.path == "/api/demo/sessions":
                if demo_store is None:
                    return self._json(404, {"error": "DEMO_API_DISABLED"})
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    return self._json(400, {"error": "INVALID_CONTENT_LENGTH"})
                if length < 0 or length > 1024:
                    return self._json(413, {"error": "BODY_SIZE_INVALID"})
                try:
                    body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
                except Exception:
                    return self._json(400, {"error": "INVALID_JSON"})
                if body != {}:
                    return self._json(400, {"error": "REQUEST_SCHEMA_INVALID"})
                return self._json(201, demo_store.create())
            demo_match = re.fullmatch(r"/api/demo/sessions/([a-f0-9]{32})/spins", self.path)
            if demo_match:
                if demo_store is None:
                    return self._json(404, {"error": "DEMO_API_DISABLED"})
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    return self._json(400, {"error": "INVALID_CONTENT_LENGTH"})
                if length <= 0 or length > 2048:
                    return self._json(413, {"error": "BODY_SIZE_INVALID"})
                try:
                    body = json.loads(self.rfile.read(length).decode("utf-8"))
                except Exception:
                    return self._json(400, {"error": "INVALID_JSON"})
                if not isinstance(body, dict) or set(body) != {"request_id"}:
                    return self._json(400, {"error": "REQUEST_SCHEMA_INVALID"})
                try:
                    result = demo_store.spin(demo_match.group(1), body["request_id"])
                    return self._json(200, result)
                except DemoSessionError as exc:
                    return self._json(404 if "unknown" in str(exc) else 400,
                                       {"error": "DEMO_REQUEST_INVALID", "detail": str(exc)})
            if self.path == "/api/demo/game-sessions":
                if game_fixture_store is None:
                    return self._json(404, {"error": "GAME_FIXTURE_API_DISABLED"})
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    return self._json(400, {"error": "INVALID_CONTENT_LENGTH"})
                if length > 1024:
                    return self._json(413, {"error": "BODY_SIZE_INVALID"})
                try:
                    body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
                except Exception:
                    return self._json(400, {"error": "INVALID_JSON"})
                if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
                    return self._json(415, {"error": "JSON_REQUIRED"})
                if body != {}:
                    return self._json(400, {"error": "REQUEST_SCHEMA_INVALID"})
                return self._json(201, game_fixture_store.create())
            if self.path == "/api/runtime/sessions":
                if runtime is None:
                    return self._json(404, {"error": "RUNTIME_API_DISABLED"})
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    return self._json(400, {"error": "INVALID_CONTENT_LENGTH"})
                if length > 1024:
                    return self._json(413, {"error": "BODY_SIZE_INVALID"})
                if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
                    return self._json(415, {"error": "JSON_REQUIRED"})
                try:
                    body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
                except Exception:
                    return self._json(400, {"error": "INVALID_JSON"})
                if body != {}:
                    return self._json(400, {"error": "REQUEST_SCHEMA_INVALID"})
                return self._json(201, runtime.create_session())
            runtime_play_match = re.fullmatch(r"/api/runtime/sessions/([a-f0-9]{32})/rounds", self.path)
            if runtime_play_match:
                if runtime is None:
                    return self._json(404, {"error": "RUNTIME_API_DISABLED"})
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    return self._json(400, {"error": "INVALID_CONTENT_LENGTH"})
                if length <= 0 or length > 2048:
                    return self._json(413, {"error": "BODY_SIZE_INVALID"})
                if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
                    return self._json(415, {"error": "JSON_REQUIRED"})
                try:
                    def _reject_duplicate_runtime_keys(pairs):
                        result = {}
                        for key, value in pairs:
                            if key in result:
                                raise ValueError("duplicate JSON key")
                            result[key] = value
                        return result
                    body = json.loads(self.rfile.read(length).decode("utf-8"),
                                      object_pairs_hook=_reject_duplicate_runtime_keys)
                except Exception:
                    return self._json(400, {"error": "INVALID_JSON"})
                if not isinstance(body, dict) or set(body) != {"request_id"}:
                    return self._json(400, {"error": "REQUEST_SCHEMA_INVALID"})
                try:
                    base_stops, feature_stops = runtime_stop_provider(runtime_play_match.group(1))
                    result = runtime.play_base(runtime_play_match.group(1), body["request_id"],
                                               base_stops, feature_stops)
                    return self._json(200, result)
                except GameRuntimeError as exc:
                    return self._json(409, {"error": "RUNTIME_REQUEST_REJECTED", "detail": str(exc)})
                except Exception:
                    return self._json(500, {"error": "RUNTIME_PROCESSING_FAILED"})
            fixture_play_match = re.fullmatch(r"/api/demo/game-sessions/([a-f0-9]{32})/rounds", self.path)
            if fixture_play_match:
                if game_fixture_store is None:
                    return self._json(404, {"error": "GAME_FIXTURE_API_DISABLED"})
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    return self._json(400, {"error": "INVALID_CONTENT_LENGTH"})
                if length <= 0 or length > 2048:
                    return self._json(413, {"error": "BODY_SIZE_INVALID"})
                if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
                    return self._json(415, {"error": "JSON_REQUIRED"})
                try:
                    def _reject_duplicate_fixture_keys(pairs):
                        result = {}
                        for key, value in pairs:
                            if key in result:
                                raise ValueError("duplicate JSON key")
                            result[key] = value
                        return result
                    body = json.loads(self.rfile.read(length).decode("utf-8"),
                                      object_pairs_hook=_reject_duplicate_fixture_keys)
                except Exception:
                    return self._json(400, {"error": "INVALID_JSON"})
                if not isinstance(body, dict) or set(body) != {"request_id"}:
                    return self._json(400, {"error": "REQUEST_SCHEMA_INVALID"})
                try:
                    return self._json(200, game_fixture_store.play(fixture_play_match.group(1), body["request_id"]))
                except GameFixtureSessionError as exc:
                    return self._json(404 if "unknown" in str(exc) else 409,
                                       {"error": "GAME_FIXTURE_REQUEST_INVALID", "detail": str(exc)})
            if not enable_round_api:
                return self._json(404, {"error": "ROUND_API_DISABLED_IN_PREVIEW"})
            recover_match = re.fullmatch(r"/api/v1/rounds/([A-Za-z0-9][A-Za-z0-9._:-]{0,127})/recover", self.path)
            if recover_match:
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    return self._json(400, {"error": "INVALID_CONTENT_LENGTH"})
                if length <= 0 or length > 1024:
                    return self._json(413, {"error": "BODY_SIZE_INVALID"})
                if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
                    return self._json(415, {"error": "JSON_REQUIRED"})
                try:
                    def _reject_recovery_duplicate_keys(pairs):
                        result = {}
                        for key, value in pairs:
                            if key in result:
                                raise ValueError("duplicate JSON key")
                            result[key] = value
                        return result
                    body = json.loads(self.rfile.read(length).decode("utf-8"),
                                      object_pairs_hook=_reject_recovery_duplicate_keys)
                except Exception:
                    return self._json(400, {"error": "INVALID_JSON"})
                if body != {}:
                    return self._json(400, {"error": "REQUEST_SCHEMA_INVALID"})
                account_id = self._authenticate("POST", body)
                if not account_id:
                    return self._json(401, {"error": "REQUEST_AUTHENTICATION_FAILED"})
                try:
                    recovered = service.recover_round(recover_match.group(1), account_id)
                    return self._json(200, {"contract": "ganesha.game.recovery", "schema_version": 1,
                                            "round_id": recover_match.group(1), "status": recovered["status"],
                                            "recovered": True, "reason": recovered.get("reason")})
                except InvalidRoundState:
                    return self._json(404, {"error": "NOT_FOUND_OR_INVALID_ROUND"})
                except Exception:
                    return self._json(409, {"error": "ROUND_RECOVERY_NOT_COMPLETED"})
            if self.path != "/api/v1/rounds":
                return self._json(404, {"error": "NOT_FOUND"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                return self._json(400, {"error": "INVALID_CONTENT_LENGTH"})
            if length <= 0 or length > MAX_BODY_BYTES:
                return self._json(413, {"error": "BODY_SIZE_INVALID"})
            if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
                return self._json(415, {"error": "JSON_REQUIRED"})
            try:
                def _reject_duplicate_keys(pairs):
                    result = {}
                    for key, value in pairs:
                        if key in result:
                            raise ValueError("duplicate JSON key")
                        result[key] = value
                    return result
                body = json.loads(self.rfile.read(length).decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
            except Exception:
                return self._json(400, {"error": "INVALID_JSON"})
            allowed = {"round_id", "operation_id", "bet_minor", "mode"}
            if not isinstance(body, dict) or set(body) != allowed:
                return self._json(400, {"error": "REQUEST_SCHEMA_INVALID", "required_fields": sorted(allowed)})
            account_id = self._authenticate("POST", body)
            if not account_id:
                return self._json(401, {"error": "REQUEST_AUTHENTICATION_FAILED"})
            if type(body["bet_minor"]) is not int or body["bet_minor"] <= 0:
                return self._json(400, {"error": "BET_AMOUNT_INVALID"})
            try:
                result = service.play_round(account_id, body["round_id"], body["operation_id"],
                                            body["bet_minor"], body["mode"])
                return self._json(200, result)
            except InsufficientFunds:
                return self._json(409, {"error": "INSUFFICIENT_FUNDS"})
            except (DuplicateOperation, InvalidRoundState):
                return self._json(409, {"error": "ROUND_CONFLICT"})
            except ValueError:
                return self._json(400, {"error": "ROUND_REQUEST_INVALID"})
            except Exception:
                return self._json(500, {"error": "ROUND_PROCESSING_FAILED"})

    return Handler


def create_server(host, port, ledger=None, stop_generator=None, sessions=None, nonce_registry=None,
                  frontend_root=None, enable_round_api=False, game_engine=None,
                  allow_unapproved_math_for_tests=False, enable_demo_api=False,
                  enable_game_fixture_api=False, runtime=None, runtime_stop_provider=None):
    if enable_demo_api or enable_game_fixture_api or runtime is not None:
        try:
            loopback = host == "localhost" or ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = False
        if not loopback:
            raise ValueError("Unauthenticated demo and game-fixture APIs may bind only to a loopback address")
    handler = make_handler(ledger, stop_generator, sessions, nonce_registry, frontend_root,
                           enable_round_api, game_engine, allow_unapproved_math_for_tests,
                           enable_demo_api, enable_game_fixture_api, runtime, runtime_stop_provider)
    return ThreadingHTTPServer((host, port), handler)
