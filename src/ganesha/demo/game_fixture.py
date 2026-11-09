"""Loopback-only GameEngine presentation fixture; never a production Math adapter.

The fixed outcomes exercise the real GameEngine and presentation reducer without
RNG, canonical Math, Wallet, debit, credit, settlement or Provider dependencies.
"""
import json
import threading
import uuid

from ganesha.game.engine import GameEngine
from ganesha.game.presentation import build_presentation_events, initial_state, replay_events
from ganesha.math.engine import EmbeddedEpicFeatureUnavailable, UnspecifiedMathRule
from ganesha.math.config import WILD

CONTRACT = "ganesha.game.fixture.sessions"
SCHEMA_VERSION = 1

_BASE_BOARD = (
    ("A", "SCATTER_LOTUS", "K"),
    ("MOUSE", "A", "SCATTER_LOTUS"),
    ("K", "ELEPHANT", "A"),
    ("SCATTER_LOTUS", "CHAKRA", "MOUSE"),
    ("A", "K", "MODAK"),
)
_BASE_BOARD_FOUR_SCATTER = (
    ("A", "SCATTER_LOTUS", "K"),
    ("MOUSE", "A", "SCATTER_LOTUS"),
    ("K", "ELEPHANT", "A"),
    ("SCATTER_LOTUS", "CHAKRA", "MOUSE"),
    ("A", "SCATTER_LOTUS", "MODAK"),
)
_FEATURE_BOARD = (
    ("A", "K", "CHAKRA"),
    ("MOUSE", "A", "K"),
    (WILD, "A", "MODAK"),
    ("K", "CHAKRA", "A"),
    ("A", "MOUSE", "K"),
)
_FEATURE_DISPLAY = (
    ("A", "K", "CHAKRA"),
    ("MOUSE", "A", "K"),
    (WILD, WILD, WILD),
    ("K", "CHAKRA", "A"),
    ("A", "MOUSE", "K"),
)


def _clone(value):
    return json.loads(json.dumps(value))


class GameFixtureSessionError(ValueError):
    pass


class PresentationFixtureMathPort:
    """Fixed, non-probabilistic scenario for integration and animation acceptance."""
    authority_status = "TEST_FIXTURE_ONLY"
    version = "ganesha-presentation-fixture-v1"

    def evaluate_stops(self, stops, mode):
        if mode == "BASE":
            return {
                "mode": "BASE", "board": [list(reel) for reel in _BASE_BOARD],
                "display_board": [list(reel) for reel in _BASE_BOARD],
                "payout_milli": 1000, "raw_payout_milli": 1000,
                "wild_multiplier": 1, "expanded_wild_reels": [],
                "max_win_capped": False, "free_spins_awarded": 10,
                "scatter_count": 3, "line_wins": [],
            }
        if mode == "FREE_SPINS":
            return {
                "mode": "FREE_SPINS", "board": [list(reel) for reel in _FEATURE_BOARD],
                "display_board": [list(reel) for reel in _FEATURE_DISPLAY],
                "payout_milli": 50, "raw_payout_milli": 25,
                "scatter_count": 0, "expanded_wild_reels": [2],
                "wild_multiplier": 2, "line_wins": [],
                "max_win_capped": False, "jackpot_triggered": False,
            }
        raise ValueError("unsupported fixture mode")

    def award_free_spins(self, scatter_count, retrigger=False):
        if type(scatter_count) is not int or scatter_count < 0:
            raise ValueError("scatter_count must be a non-negative integer")
        if retrigger:
            if scatter_count == 0:
                return 0
            raise UnspecifiedMathRule("Free Spins retrigger behavior is unspecified")
        if scatter_count == 3:
            return 10
        if scatter_count == 4:
            return 12
        if scatter_count == 5:
            raise EmbeddedEpicFeatureUnavailable("embedded EPICBUY_V37 provider payload is unavailable")
        if scatter_count >= 6:
            raise UnspecifiedMathRule("6+ Scatter is rejected by the current BASE contract (fail closed)")
        if scatter_count < 3:
            return 0


class FourScatterPresentationFixtureMathPort(PresentationFixtureMathPort):
    """Four-Scatter / twelve-spin fixture for the current UI contract."""

    version = "ganesha-four-scatter-presentation-fixture-v1"

    def evaluate_stops(self, stops, mode):
        if mode == "BASE":
            return {
                "mode": "BASE", "board": [list(reel) for reel in _BASE_BOARD_FOUR_SCATTER],
                "display_board": [list(reel) for reel in _BASE_BOARD_FOUR_SCATTER],
                "payout_milli": 1000, "raw_payout_milli": 1000,
                "wild_multiplier": 1, "expanded_wild_reels": [],
                "max_win_capped": False, "free_spins_awarded": 12,
                "scatter_count": 4, "line_wins": [],
            }
        return super().evaluate_stops(stops, mode)


class GameFixtureSessionStore:
    """Thread-safe, request-idempotent fixture sessions with no Wallet reference."""

    def __init__(self):
        self._lock = threading.RLock()
        self._sessions = {}

    def create(self):
        with self._lock:
            session_id = uuid.uuid4().hex
            round_id = "fixture-" + uuid.uuid4().hex
            self._sessions[session_id] = {
                "session_id": session_id, "round_id": round_id,
                "events": [], "state": initial_state(round_id),
                "requests": {}, "completed": False,
            }
            return {
                "contract": CONTRACT, "schema_version": SCHEMA_VERSION,
                "session_id": session_id, "round_id": round_id,
                "classification": "TEST_FIXTURE_ONLY", "financial_effects": False,
            }

    def play(self, session_id, request_id):
        if not isinstance(request_id, str) or not request_id or len(request_id) > 128:
            raise GameFixtureSessionError("request_id must be a non-empty string of at most 128 characters")
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise GameFixtureSessionError("unknown game fixture session")
            cached = session["requests"].get(request_id)
            if cached is not None:
                return _clone(cached)
            if session["completed"]:
                raise GameFixtureSessionError("fixture session already completed; create a new session")

            engine = GameEngine(math_port=FourScatterPresentationFixtureMathPort())
            stops = [(0, 0, 0, 0, 0)] * 12
            outcome = engine.resolve_base_round((0, 0, 0, 0, 0), stops)
            events = build_presentation_events(session["round_id"], outcome)
            state = replay_events(session["round_id"], events)
            if state["status"] != "COMPLETED" or state["feature_spins_played"] != 12:
                raise GameFixtureSessionError("fixture GameEngine did not complete the expected 4-Scatter/12-Free-Spins sequence")

            response = {
                "contract": "ganesha.game.presentation", "schema_version": 1,
                "session_contract": CONTRACT, "session_schema_version": SCHEMA_VERSION,
                "session_id": session_id, "round_id": session["round_id"],
                "classification": "TEST_FIXTURE_ONLY", "financial_effects": False,
                "events": events, "state": state,
            }
            session["events"] = events
            session["state"] = state
            session["completed"] = True
            session["requests"][request_id] = response
            return _clone(response)

    def snapshot(self, session_id):
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise GameFixtureSessionError("unknown game fixture session")
            return {
                "contract": "ganesha.game.presentation", "schema_version": 1,
                "session_contract": CONTRACT, "session_schema_version": SCHEMA_VERSION,
                "session_id": session_id, "round_id": session["round_id"],
                "classification": "TEST_FIXTURE_ONLY", "financial_effects": False,
                "events": _clone(session["events"]), "state": _clone(session["state"]),
            }
