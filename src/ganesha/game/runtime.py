"""Independent, non-financial game runtime over an explicitly injected MathPort.

This runtime owns session lifecycle, idempotency, deterministic outcome projection
and replay. It deliberately has no Wallet, RGS debit, settlement or RNG secret.
The caller must supply trusted server-side stop vectors and an explicit MathPort.
"""
import copy
import hashlib
import json
import sqlite3
import threading
import uuid

from ganesha.game.engine import GameEngine
from ganesha.game.events import (
    EventContractError,
    initial_simulation_state,
    make_simulation_event,
    replay_simulation_events,
)
from ganesha.game.presentation import (
    PresentationContractError,
    build_presentation_events,
    replay_events,
)


CLASSIFICATION = "NON_FINANCIAL_SIMULATION"
CONTRACT = "ganesha.game.runtime"
SCHEMA_VERSION = 1
STORAGE_SCHEMA_VERSION = 3


class GameRuntimeError(ValueError):
    pass


class GameRuntime:
    """Session-oriented runtime. No implicit DraftMathPort fallback is permitted."""

    def __init__(self, math_port, storage_path=None):
        if math_port is None:
            raise TypeError("an explicit MathPort is required; implicit DraftMathPort is forbidden")
        self.engine = GameEngine(math_port=math_port)
        self.math_port = math_port
        self._lock = threading.RLock()
        self._sessions = {}
        self._db = None
        if storage_path is not None:
            self._db = sqlite3.connect(storage_path, timeout=10, check_same_thread=False)
            self._db.execute("PRAGMA foreign_keys=ON")
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS game_runtime_sessions ("
                "session_id TEXT PRIMARY KEY, round_id TEXT NOT NULL UNIQUE, payload_json TEXT NOT NULL)"
            )
            self._restore_sessions()

    def create_session(self):
        with self._lock:
            session_id = uuid.uuid4().hex
            round_id = "runtime-" + uuid.uuid4().hex
            session = {
                "session_id": session_id,
                "round_id": round_id,
                "classification": CLASSIFICATION,
                "financial_effects": False,
                "math_version": str(getattr(self.math_port, "version", "UNDECLARED")),
                "status": "CREATED",
                "events": [],
                "state": None,
                "lifecycle_events": [],
                "lifecycle_state": None,
                "outcome": None,
                "requests": {},
                "request_inputs": {},
                "buy_validations": {},
            }
            self._persist_session(session)
            self._sessions[session_id] = session
            return self._snapshot(session)

    def play_base(self, session_id, request_id, base_stops, free_spin_stop_vectors):
        """Resolve one BASE round from trusted server-side vectors; never touches Wallet."""
        if not isinstance(request_id, str) or not request_id or len(request_id) > 128:
            raise GameRuntimeError("request_id must be a non-empty string of at most 128 characters")
        if not isinstance(base_stops, (list, tuple)) or len(base_stops) != 5:
            raise GameRuntimeError("base_stops must contain five server-side reel positions")
        if not isinstance(free_spin_stop_vectors, (list, tuple)):
            raise GameRuntimeError("free_spin_stop_vectors must be a server-side sequence")
        request_input = {
            "base_stops": copy.deepcopy(list(base_stops)),
            "free_spin_stop_vectors": copy.deepcopy(list(free_spin_stop_vectors)),
        }
        fingerprint = hashlib.sha256(
            json.dumps(request_input, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
        ).hexdigest()
        with self._lock:
            session = self._require_session(session_id)
            cached = session["requests"].get(request_id)
            if cached is not None:
                if session["request_inputs"].get(request_id, {}).get("fingerprint") != fingerprint:
                    raise GameRuntimeError("request_id was already used with different inputs")
                return self._public_response(cached)
            if session["status"] != "CREATED":
                raise GameRuntimeError("runtime session already has a committed outcome")
            try:
                outcome = self.engine.resolve_base_round(base_stops, free_spin_stop_vectors)
                events = build_presentation_events(session["round_id"], outcome)
                state = replay_events(session["round_id"], events)
                lifecycle_events, lifecycle_state = self._build_lifecycle(
                    session["round_id"], outcome
                )
            except (EventContractError, PresentationContractError, TypeError, ValueError, RuntimeError) as exc:
                raise GameRuntimeError("runtime resolution rejected: %s" % exc) from exc
            if state["status"] != "COMPLETED":
                raise GameRuntimeError("runtime reducer did not reach COMPLETED")
            if state["base_board"] != outcome["base_result"]["board"]:
                raise GameRuntimeError("committed Math board differs from replayed presentation board")
            if state["total_payout_milli"] != outcome["total_payout_milli"]:
                raise GameRuntimeError("replayed payout differs from committed Math outcome")
            response = self._make_response(
                session_id, session["round_id"], outcome, events, state,
                lifecycle_events, lifecycle_state,
            )
            candidate = copy.deepcopy(session)
            candidate.update(status="COMPLETED", events=events, state=state,
                             lifecycle_events=lifecycle_events, lifecycle_state=lifecycle_state,
                             outcome=outcome)
            candidate["requests"][request_id] = copy.deepcopy(response)
            candidate["request_inputs"][request_id] = {
                "fingerprint": fingerprint, "input": request_input,
            }
            self._persist_session(candidate)
            self._sessions[session_id] = candidate
            return self._public_response(response)

    def validate_buy(self, session_id, request_id, mode):
        """Validate explicit MathPort terms without charging, buying or resolving spins."""
        if mode not in ("MAGIC_BUY", "EPIC_BUY"):
            raise GameRuntimeError("mode must be MAGIC_BUY or EPIC_BUY")
        if not isinstance(request_id, str) or not request_id or len(request_id) > 128:
            raise GameRuntimeError("request_id must be a non-empty string of at most 128 characters")
        with self._lock:
            session = self._require_session(session_id)
            cache_key = (request_id, mode)
            if cache_key in session["buy_validations"]:
                return copy.deepcopy(session["buy_validations"][cache_key])
            try:
                terms = self.engine.get_bonus_buy_terms(mode)
            except Exception as exc:
                raise GameRuntimeError("%s validation unavailable: %s" % (mode, exc)) from exc
            result = {
                "contract": CONTRACT,
                "schema_version": SCHEMA_VERSION,
                "session_id": session_id,
                "classification": CLASSIFICATION,
                "financial_effects": False,
                "purchase_executed": False,
                "debit_created": False,
                "mode": mode,
                "terms": copy.deepcopy(terms),
            }
            candidate = copy.deepcopy(session)
            candidate["buy_validations"][cache_key] = copy.deepcopy(result)
            self._persist_session(candidate)
            self._sessions[session_id] = candidate
            return result

    def replay(self, session_id):
        with self._lock:
            session = self._require_session(session_id)
            if session["status"] != "COMPLETED":
                raise GameRuntimeError("runtime session has no completed event stream")
            rebuilt = replay_events(session["round_id"], session["events"])
            lifecycle_rebuilt = replay_simulation_events(session["round_id"], session["lifecycle_events"])
            if rebuilt != session["state"] or lifecycle_rebuilt != session["lifecycle_state"]:
                raise GameRuntimeError("runtime replay does not match stored state")
            return self._public_state(rebuilt)

    def snapshot(self, session_id):
        with self._lock:
            return self._snapshot(self._require_session(session_id))

    def _require_session(self, session_id):
        session = self._sessions.get(session_id)
        if session is None:
            raise GameRuntimeError("unknown runtime session")
        return session

    def _persist_session(self, session):
        if self._db is None:
            return
        payload = {
            "storage_schema_version": STORAGE_SCHEMA_VERSION,
            "classification": session["classification"],
            "financial_effects": session["financial_effects"],
            "math_version": session["math_version"],
            "status": session["status"],
            "events": session["events"],
            "state": session["state"],
            "lifecycle_events": session["lifecycle_events"],
            "lifecycle_state": session["lifecycle_state"],
            "outcome": session["outcome"],
            "requests": session["requests"],
            "request_inputs": session["request_inputs"],
            "buy_validations": [
                [key[0], key[1], value]
                for key, value in session["buy_validations"].items()
            ],
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        with self._db:
            self._db.execute(
                "INSERT INTO game_runtime_sessions(session_id, round_id, payload_json) VALUES (?, ?, ?) "
                "ON CONFLICT(session_id) DO UPDATE SET round_id=excluded.round_id, payload_json=excluded.payload_json",
                (session["session_id"], session["round_id"], encoded),
            )

    def _restore_sessions(self):
        rows = self._db.execute(
            "SELECT session_id, round_id, payload_json FROM game_runtime_sessions ORDER BY session_id"
        ).fetchall()
        for session_id, round_id, encoded in rows:
            try:
                payload = json.loads(encoded)
                if (not isinstance(payload, dict)
                        or payload.get("storage_schema_version") != STORAGE_SCHEMA_VERSION
                        or payload.get("classification") != CLASSIFICATION
                        or payload.get("financial_effects") is not False
                        or payload.get("status") not in ("CREATED", "COMPLETED")
                        or payload.get("math_version") != str(getattr(self.math_port, "version", "UNDECLARED"))
                        or not isinstance(payload.get("events"), list)
                        or not isinstance(payload.get("lifecycle_events"), list)
                        or not isinstance(payload.get("requests"), dict)
                        or not isinstance(payload.get("request_inputs"), dict)
                        or not isinstance(payload.get("buy_validations"), list)):
                    raise ValueError("persisted runtime session envelope is invalid")
                state = payload.get("state")
                outcome = payload.get("outcome")
                if payload["status"] == "CREATED":
                    if (payload["events"] or payload["lifecycle_events"] or state is not None
                            or payload.get("lifecycle_state") is not None or outcome is not None
                            or payload["requests"] or payload["request_inputs"]):
                        raise ValueError("created runtime session contains a partial outcome")
                else:
                    rebuilt = replay_events(round_id, payload["events"])
                    lifecycle_rebuilt = replay_simulation_events(round_id, payload["lifecycle_events"])
                    if (rebuilt != state or rebuilt.get("status") != "COMPLETED"
                            or lifecycle_rebuilt != payload.get("lifecycle_state")
                            or lifecycle_rebuilt.get("status") != "COMPLETED"
                            or not isinstance(outcome, dict)
                            or len(payload["requests"]) != 1
                            or set(payload["requests"]) != set(payload["request_inputs"])):
                        raise ValueError("persisted runtime events, state and outcome do not reconcile")
                    request_id = next(iter(payload["requests"]))
                    request_record = payload["request_inputs"][request_id]
                    request_data = request_record.get("input") if isinstance(request_record, dict) else None
                    if (not isinstance(request_data, dict)
                            or set(request_data) != {"base_stops", "free_spin_stop_vectors"}):
                        raise ValueError("persisted request input is invalid")
                    fingerprint = hashlib.sha256(
                        json.dumps(request_data, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
                    ).hexdigest()
                    if request_record.get("fingerprint") != fingerprint:
                        raise ValueError("persisted request fingerprint mismatch")
                    recomputed = self.engine.resolve_base_round(
                        request_data["base_stops"], request_data["free_spin_stop_vectors"]
                    )
                    expected_events = build_presentation_events(round_id, recomputed)
                    expected_state = replay_events(round_id, expected_events)
                    expected_lifecycle_events, expected_lifecycle_state = self._build_lifecycle(round_id, recomputed)
                    expected_response = self._make_response(
                        session_id, round_id, recomputed, expected_events, expected_state,
                        expected_lifecycle_events, expected_lifecycle_state,
                    )
                    if (outcome != recomputed or payload["events"] != expected_events or state != expected_state
                            or payload["lifecycle_events"] != expected_lifecycle_events
                            or payload.get("lifecycle_state") != expected_lifecycle_state
                            or payload["requests"].get(request_id) != expected_response):
                        raise ValueError("persisted outcome or cached response differs from recomputed Math and event replay")
                validations = {}
                for item in payload["buy_validations"]:
                    if (not isinstance(item, list) or len(item) != 3
                            or type(item[0]) is not str or not item[0] or len(item[0]) > 128
                            or type(item[1]) is not str or item[1] not in ("MAGIC_BUY", "EPIC_BUY")
                            or not isinstance(item[2], dict)):
                        raise ValueError("persisted Buy validation record is invalid")
                    expected_validation = {
                        "contract": CONTRACT,
                        "schema_version": SCHEMA_VERSION,
                        "session_id": session_id,
                        "classification": CLASSIFICATION,
                        "financial_effects": False,
                        "purchase_executed": False,
                        "debit_created": False,
                        "mode": item[1],
                        "terms": copy.deepcopy(self.engine.get_bonus_buy_terms(item[1])),
                    }
                    if item[2] != expected_validation:
                        raise ValueError("persisted Buy validation differs from its session, non-financial contract or current MathPort terms")
                    key = (item[0], item[1])
                    if key in validations:
                        raise ValueError("persisted Buy validation contains a duplicate request key")
                    validations[key] = item[2]
                session = {
                    "session_id": session_id, "round_id": round_id,
                    "classification": CLASSIFICATION, "financial_effects": False,
                    "math_version": str(payload.get("math_version", "UNDECLARED")),
                    "status": payload["status"], "events": payload["events"],
                    "state": state, "lifecycle_events": payload["lifecycle_events"],
                    "lifecycle_state": payload.get("lifecycle_state"), "outcome": outcome,
                    "requests": payload["requests"], "buy_validations": validations,
                    "request_inputs": payload["request_inputs"],
                }
                self._sessions[session_id] = session
            except Exception as exc:
                raise GameRuntimeError("persisted runtime session failed closed validation: %s" % exc) from exc

    def close(self):
        with self._lock:
            if self._db is not None:
                self._db.close()
                self._db = None

    @staticmethod
    def _public_state(state):
        """Return a runtime-classified copy without relabelling stored presentation state."""
        public_state = copy.deepcopy(state)
        if public_state is not None:
            public_state["classification"] = CLASSIFICATION
        return public_state

    @staticmethod
    def _public_outcome(outcome):
        """Remove caller-controlled MathPort authority claims from the public runtime API."""
        public_outcome = copy.deepcopy(outcome)
        if isinstance(public_outcome, dict):
            public_outcome.pop("math_authority", None)
        return public_outcome

    @staticmethod
    def _public_response(response):
        """Expose runtime classification, never mutable MathPort authority metadata."""
        public_response = copy.deepcopy(response)
        public_response.pop("math_authority", None)
        public_response["outcome"] = GameRuntime._public_outcome(public_response.get("outcome"))
        return public_response

    @staticmethod
    def _snapshot(session):
        return {
            "contract": CONTRACT,
            "schema_version": SCHEMA_VERSION,
            "session_id": session["session_id"],
            "round_id": session["round_id"],
            "classification": CLASSIFICATION,
            "financial_effects": False,
            "math_version": session["math_version"],
            "status": session["status"],
            "events": copy.deepcopy(session["events"]),
            "state": GameRuntime._public_state(session["state"]),
            "lifecycle_events": copy.deepcopy(session["lifecycle_events"]),
            "lifecycle_state": copy.deepcopy(session["lifecycle_state"]),
            "outcome": GameRuntime._public_outcome(session["outcome"]),
        }

    @staticmethod
    def _make_response(session_id, round_id, outcome, events, state,
                       lifecycle_events, lifecycle_state):
        return {
            "contract": CONTRACT,
            "schema_version": SCHEMA_VERSION,
            "session_id": session_id,
            "round_id": round_id,
            "classification": CLASSIFICATION,
            "financial_effects": False,
            "math_authority": outcome["math_authority"],
            "math_version": outcome["math_version"],
            "events": copy.deepcopy(events),
            "state": GameRuntime._public_state(state),
            "lifecycle_events": copy.deepcopy(lifecycle_events),
            "lifecycle_state": copy.deepcopy(lifecycle_state),
            "outcome": copy.deepcopy(outcome),
        }

    @staticmethod
    def _build_lifecycle(round_id, outcome):
        state = initial_simulation_state(round_id)
        events = []

        def emit(event_type, payload):
            nonlocal state
            event = make_simulation_event(
                state, round_id + ":simulation:" + str(state["event_count"] + 1),
                event_type, payload,
            )
            events.append(event)
            state = replay_simulation_events(round_id, events)

        math_version = str(outcome["math_version"])
        base = outcome["base_result"]
        total = outcome["total_payout_milli"]
        base_payout = base["payout_milli"]
        feature_payout = total - base_payout
        emit("SIMULATION_STARTED", {"mode": "BASE", "math_version": math_version})
        emit("SIMULATION_OUTCOME_COMMITTED", {
            "base_board": base["board"],
            "base_display_board": base.get("display_board", base["board"]),
            "scatter_count": base["scatter_count"],
            "initial_free_spins": outcome["initial_free_spins"],
            "free_spins_played": outcome["free_spins_played"],
            "base_payout_milli": base_payout,
            "feature_payout_milli": feature_payout,
            "total_payout_milli": total,
            "round_cap_reached": outcome["round_cap_reached"],
            "math_version": math_version,
        })
        emit("SIMULATION_COMPLETED", {"terminal_status": "COMPLETED"})
        return events, state
