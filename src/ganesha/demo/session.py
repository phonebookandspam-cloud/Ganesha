"""Deterministic scripted presentation sessions, isolated from Math and Wallet.

The fixture boards are visual test data only. They do not represent RNG output,
probability, payline evaluation, wins, Free Spins awards or purchase behavior.
"""
import hashlib
import json
import threading
import uuid

SCHEMA_VERSION = 1
CONTRACT = "ganesha.demo.events"
ZERO_HASH = "0" * 64
MAX_SPINS_PER_SESSION = 100

_BOARDS = (
    (("A", "K", "MODAK"), ("CHAKRA", "ELEPHANT", "A"), ("MOUSE", "MODAK", "K"),
     ("K", "A", "CHAKRA"), ("ELEPHANT", "MOUSE", "MODAK")),
    (("MODAK", "A", "K"), ("MOUSE", "CHAKRA", "ELEPHANT"), ("A", "K", "MODAK"),
     ("CHAKRA", "MODAK", "MOUSE"), ("K", "ELEPHANT", "A")),
)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


class DemoSessionError(ValueError):
    pass


class DemoSessionStore:
    """Thread-safe in-memory demo sessions with request-idempotent scripted spins."""

    def __init__(self):
        self._lock = threading.RLock()
        self._sessions = {}

    def create(self):
        with self._lock:
            session_id = uuid.uuid4().hex
            session = {"session_id": session_id, "contract": CONTRACT,
                       "schema_version": SCHEMA_VERSION, "spin_count": 0,
                       "events": [], "last_event_hash": ZERO_HASH,
                       "requests": {}}
            self._sessions[session_id] = session
            return self.snapshot(session_id)

    def _append(self, session, event_type, payload):
        event = {"contract": CONTRACT, "schema_version": SCHEMA_VERSION,
                 "session_id": session["session_id"], "sequence": len(session["events"]) + 1,
                 "event_id": uuid.uuid4().hex, "event_type": event_type,
                 "payload": payload, "previous_hash": session["last_event_hash"]}
        event["event_hash"] = hashlib.sha256(_canonical(event).encode("ascii")).hexdigest()
        session["events"].append(event)
        session["last_event_hash"] = event["event_hash"]
        return event

    def spin(self, session_id, request_id):
        if not isinstance(request_id, str) or not request_id or len(request_id) > 128:
            raise DemoSessionError("request_id must be a non-empty string of at most 128 characters")
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise DemoSessionError("unknown demo session")
            cached = session["requests"].get(request_id)
            if cached is not None:
                return json.loads(json.dumps(cached))
            if session["spin_count"] >= MAX_SPINS_PER_SESSION:
                raise DemoSessionError("demo session spin limit reached")
            spin_number = session["spin_count"] + 1
            board = _BOARDS[(spin_number - 1) % len(_BOARDS)]
            first_sequence = len(session["events"]) + 1
            self._append(session, "DEMO_SPIN_STARTED", {"request_id": request_id,
                                                          "spin_number": spin_number,
                                                          "classification": "SCRIPTED_VISUAL_FIXTURE"})
            for reel_index, reel in enumerate(board):
                self._append(session, "DEMO_REEL_STOPPED", {"request_id": request_id,
                                                              "spin_number": spin_number,
                                                              "reel_index": reel_index,
                                                              "symbols": list(reel)})
            self._append(session, "DEMO_BOARD_REVEALED", {"request_id": request_id,
                                                           "spin_number": spin_number,
                                                           "board": [list(reel) for reel in board],
                                                           "classification": "SCRIPTED_VISUAL_FIXTURE"})
            self._append(session, "DEMO_PRESENTATION_COMPLETED", {"request_id": request_id,
                                                                   "spin_number": spin_number})
            session["spin_count"] = spin_number
            response = {"contract": CONTRACT, "schema_version": SCHEMA_VERSION,
                        "session_id": session_id, "spin_number": spin_number,
                        "classification": "SCRIPTED_VISUAL_FIXTURE",
                        "events": session["events"][first_sequence - 1:]}
            session["requests"][request_id] = response
            return json.loads(json.dumps(response))

    def snapshot(self, session_id):
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise DemoSessionError("unknown demo session")
            return {"contract": CONTRACT, "schema_version": SCHEMA_VERSION,
                    "session_id": session_id, "spin_count": session["spin_count"],
                    "events": json.loads(json.dumps(session["events"]))}
