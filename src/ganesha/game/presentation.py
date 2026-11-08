"""Non-financial, hash-chained presentation events for resolved game outcomes.

This contract projects an already-resolved GameEngine outcome into deterministic
reel/feature presentation events. It does not generate RNG, authorize Math,
reserve bets, settle funds, or claim Provider compatibility. Every projection is
unconditionally classified NON_FINANCIAL_PRESENTATION_ONLY.
"""
import hashlib
import json

from ganesha.math.engine import SCATTER
from ganesha.math.config import CONFIG, WILD

CONTRACT = "ganesha.game.presentation"
SCHEMA_VERSION = 1
ZERO_HASH = "0" * 64
PRESENTATION_CLASSIFICATION = "NON_FINANCIAL_PRESENTATION_ONLY"


class PresentationContractError(ValueError):
    pass


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _board(value, field):
    if not isinstance(value, (list, tuple)) or len(value) != 5:
        raise PresentationContractError("%s must contain exactly five reels" % field)
    result = []
    for reel in value:
        if not isinstance(reel, (list, tuple)) or len(reel) != 3:
            raise PresentationContractError("%s reels must contain exactly three symbols" % field)
        if any(not isinstance(symbol, str) or not symbol or len(symbol) > 32 for symbol in reel):
            raise PresentationContractError("%s contains an invalid symbol" % field)
        result.append(list(reel))
    return result


def _expected_display_board(board, expanded_reels):
    expected = [list(reel) for reel in board]
    for index in expanded_reels:
        if type(index) is not int or index < 0 or index > 4 or WILD not in board[index]:
            raise PresentationContractError("expanded Wild reel must contain an original Wild symbol")
        expected[index] = [WILD, WILD, WILD]
    return expected


def _expected_wild_multiplier(expanded_reels):
    count = len(expanded_reels)
    if count == 0:
        return 1
    return min(
        CONFIG.feature_rules.free_spin_wild_reel_multiplier ** count
        * (2 if count == 5 else 1),
        CONFIG.feature_rules.max_wild_reel_multiplier,
    )


def initial_state(round_id, classification=PRESENTATION_CLASSIFICATION):
    if not isinstance(round_id, str) or not round_id or len(round_id) > 128:
        raise PresentationContractError("round_id must be a non-empty string of at most 128 characters")
    if type(classification) is not str or classification != PRESENTATION_CLASSIFICATION:
        raise PresentationContractError("presentation classification is unconditional and non-financial")
    return {
        "contract": CONTRACT, "schema_version": SCHEMA_VERSION,
        "round_id": round_id, "classification": classification,
        "status": "CREATED", "mode": None, "base_board": None,
        "base_display_board": None, "base_reels_stopped": 0, "base_stopped_reels": [],
        "feature_active": False, "feature_initial_spins": 0,
        "feature_spins_awarded_total": 0,
        "feature_spins_played": 0, "feature_spins_remaining": 0,
        "feature_reels_stopped": 0, "feature_stopped_reels": [], "feature_payout_milli": 0,
        "total_payout_milli": 0, "round_cap_reached": False, "event_count": 0,
        "last_event_hash": ZERO_HASH,
    }


def make_event(state, event_type, payload):
    if not isinstance(event_type, str) or not event_type or len(event_type) > 64:
        raise PresentationContractError("event_type is invalid")
    if not isinstance(payload, dict):
        raise PresentationContractError("event payload must be an object")
    sequence = state["event_count"] + 1
    event_id = hashlib.sha256((state["round_id"] + ":presentation:" + str(sequence)
                               + ":" + event_type + ":" + _canonical(payload)).encode("utf-8")).hexdigest()
    event = {
        "contract": CONTRACT, "schema_version": SCHEMA_VERSION,
        "round_id": state["round_id"], "sequence": sequence,
        "event_id": event_id, "event_type": event_type,
        "payload": payload, "previous_hash": state["last_event_hash"],
    }
    event["event_hash"] = hashlib.sha256(_canonical(event).encode("ascii")).hexdigest()
    return event


def apply_event(state, event):
    if not isinstance(event, dict) or event.get("contract") != CONTRACT or type(event.get("schema_version")) is not int or event.get("schema_version") != SCHEMA_VERSION:
        raise PresentationContractError("unsupported presentation contract or schema version")
    if event.get("round_id") != state["round_id"]:
        raise PresentationContractError("round_id mismatch")
    if type(event.get("sequence")) is not int or event["sequence"] != state["event_count"] + 1:
        raise PresentationContractError("event sequence gap or duplicate")
    if event.get("previous_hash") != state["last_event_hash"]:
        raise PresentationContractError("event hash-chain predecessor mismatch")
    payload = event.get("payload")
    if not isinstance(payload, dict):
        raise PresentationContractError("event payload must be an object")
    unhashed = {key: value for key, value in event.items() if key != "event_hash"}
    expected_hash = hashlib.sha256(_canonical(unhashed).encode("ascii")).hexdigest()
    if event.get("event_hash") != expected_hash:
        raise PresentationContractError("event hash mismatch")
    if event.get("event_id") != hashlib.sha256((state["round_id"] + ":presentation:" + str(event["sequence"])
            + ":" + str(event.get("event_type")) + ":" + _canonical(payload)).encode("utf-8")).hexdigest():
        raise PresentationContractError("event_id does not match deterministic event identity")

    next_state = dict(state)
    kind = event["event_type"]
    if kind == "ROUND_PRESENTATION_STARTED":
        if state["status"] != "CREATED" or set(payload) != {"mode", "classification"}:
            raise PresentationContractError("invalid round presentation start")
        if (payload["mode"] != "BASE" or type(payload["classification"]) is not str
                or payload["classification"] != PRESENTATION_CLASSIFICATION
                or payload["classification"] != state["classification"]):
            raise PresentationContractError("unsupported mode or non-fixture classification")
        next_state.update(status="BASE_REELS", mode=payload["mode"])
    elif kind == "BASE_REEL_STOPPED":
        if state["status"] != "BASE_REELS" or set(payload) != {"reel_index", "symbols"}:
            raise PresentationContractError("invalid base reel stop")
        if type(payload["reel_index"]) is not int or payload["reel_index"] != state["base_reels_stopped"]:
            raise PresentationContractError("base reels must stop in order")
        if not isinstance(payload["symbols"], list) or len(payload["symbols"]) != 3 or any(not isinstance(x, str) or not x for x in payload["symbols"]):
            raise PresentationContractError("base reel symbols are malformed")
        next_state["base_stopped_reels"] = list(state["base_stopped_reels"]) + [list(payload["symbols"])]
        next_state["base_reels_stopped"] += 1
    elif kind == "BASE_OUTCOME_REVEALED":
        required = {"board", "display_board", "raw_payout_milli", "payout_milli", "wild_reels",
                    "multiplier", "max_win_capped", "free_spins_awarded", "round_cap_reached"}
        if state["status"] != "BASE_REELS" or state["base_reels_stopped"] != 5 or set(payload) != required:
            raise PresentationContractError("base outcome requires five ordered reel stops")
        board = _board(payload["board"], "board")
        display = _board(payload["display_board"], "display_board")
        if state["base_stopped_reels"] != board:
            raise PresentationContractError("base outcome board differs from stopped reel events")
        if (type(payload["raw_payout_milli"]) is not int or payload["raw_payout_milli"] < 0
                or type(payload["payout_milli"]) is not int or payload["payout_milli"] < 0
                or payload["payout_milli"] > CONFIG.max_win_milli):
            raise PresentationContractError("BASE raw and capped payouts must be non-negative exact integers within the per-spin cap")
        wild_reels = payload["wild_reels"]
        if (type(wild_reels) is not list or wild_reels
                or type(payload["multiplier"]) is not int or payload["multiplier"] != 1
                or type(payload["max_win_capped"]) is not bool):
            raise PresentationContractError("BASE mode cannot apply Wild expansion and requires exact multiplier/cap evidence")
        multiplied_payout = payload["raw_payout_milli"] * payload["multiplier"]
        if (payload["payout_milli"] != min(multiplied_payout, CONFIG.max_win_milli)
                or payload["max_win_capped"] != (multiplied_payout > CONFIG.max_win_milli)):
            raise PresentationContractError("BASE per-spin payout/cap evidence is inconsistent")
        if type(payload["free_spins_awarded"]) is not int or payload["free_spins_awarded"] not in (0, 10, 12):
            raise PresentationContractError("BASE Free Spins award must be 0, 10 or 12")
        scatter_count = sum(symbol == SCATTER for reel in board for symbol in reel)
        if scatter_count == 5:
            raise PresentationContractError("5 Scatter requires the embedded EPICBUY_V37 provider payload, unavailable in this local runtime")
        if scatter_count >= 6:
            raise PresentationContractError("6+ BASE Scatter behavior is not authorized")
        expected_award = 10 if scatter_count == 3 else 12 if scatter_count == 4 else 0
        if payload["free_spins_awarded"] != expected_award:
            raise PresentationContractError("BASE Scatter count and 3=>10 / 4=>12 Free Spins award disagree")
        if display != board:
            raise PresentationContractError("BASE display board must match the raw outcome board")
        if payload["payout_milli"] > CONFIG.max_round_win_milli:
            raise PresentationContractError("BASE payout exceeds the configured round cap")
        if type(payload["round_cap_reached"]) is not bool or payload["round_cap_reached"] != (payload["payout_milli"] == CONFIG.max_round_win_milli):
            raise PresentationContractError("BASE round-cap flag must match the capped BASE payout")
        next_state.update(base_board=board, base_display_board=display,
                          total_payout_milli=payload["payout_milli"],
                          feature_initial_spins=payload["free_spins_awarded"],
                          feature_spins_remaining=payload["free_spins_awarded"],
                          round_cap_reached=payload["round_cap_reached"],
                          status="FEATURE_PENDING" if payload["free_spins_awarded"] else "COMPLETABLE")
    elif kind == "FEATURE_STARTED":
        if (state["status"] != "FEATURE_PENDING" or state["feature_active"]
                or set(payload) != {"feature", "initial_spins"} or payload["feature"] != "FREE_SPINS"
                or type(payload["initial_spins"]) is not int or payload["initial_spins"] not in (10, 12)
                or payload["initial_spins"] != state["feature_spins_remaining"]):
            raise PresentationContractError("invalid Free Spins start")
        next_state.update(status="FEATURE_REELS", feature_active=True,
                          feature_initial_spins=payload["initial_spins"],
                          feature_spins_awarded_total=payload["initial_spins"],
                          feature_reels_stopped=0, feature_stopped_reels=[])
    elif kind == "FEATURE_REEL_STOPPED":
        if state["status"] != "FEATURE_REELS" or state["round_cap_reached"] or set(payload) != {"spin_number", "reel_index", "symbols"}:
            raise PresentationContractError("invalid feature reel stop")
        if (type(payload["spin_number"]) is not int or payload["spin_number"] != state["feature_spins_played"] + 1
                or type(payload["reel_index"]) is not int or payload["reel_index"] != state["feature_reels_stopped"]):
            raise PresentationContractError("feature reels must stop in order for the active spin")
        if not isinstance(payload["symbols"], list) or len(payload["symbols"]) != 3 or any(not isinstance(x, str) or not x for x in payload["symbols"]):
            raise PresentationContractError("feature reel symbols are malformed")
        next_state["feature_stopped_reels"] = list(state["feature_stopped_reels"]) + [list(payload["symbols"])]
        next_state["feature_reels_stopped"] += 1
    elif kind == "WILD_EXPANSION_APPLIED":
        if (state["status"] != "FEATURE_REELS" or state["feature_reels_stopped"] != 5
                or "wild_expansion_reels" in state or "active_multiplier" in state):
            raise PresentationContractError("Wild expansion must follow five stopped feature reels and precede the multiplier")
        if (set(payload) != {"spin_number", "reels", "display_board"}
                or type(payload["spin_number"]) is not int or payload["spin_number"] != state["feature_spins_played"] + 1):
            raise PresentationContractError("invalid Wild expansion event")
        reels = payload["reels"]
        if not isinstance(reels, list) or not reels or any(type(x) is not int or x < 0 or x > 4 for x in reels) or len(set(reels)) != len(reels):
            raise PresentationContractError("expanded Wild reel indices are invalid")
        display = _board(payload["display_board"], "display_board")
        raw_board = state["feature_stopped_reels"]
        if display != _expected_display_board(raw_board, reels):
            raise PresentationContractError("Wild expansion display board must be derived exactly from the raw board and expanded reels")
        next_state["wild_expansion_reels"] = reels
        next_state["wild_expansion_display_board"] = display
    elif kind == "MULTIPLIER_APPLIED":
        if (state["status"] != "FEATURE_REELS" or state["feature_reels_stopped"] != 5
                or "active_multiplier" in state or not state.get("wild_expansion_reels")):
            raise PresentationContractError("multiplier requires a preceding Wild expansion and may occur once per spin")
        if (set(payload) != {"spin_number", "multiplier"}
                or type(payload["spin_number"]) is not int or payload["spin_number"] != state["feature_spins_played"] + 1):
            raise PresentationContractError("invalid multiplier event")
        expected_multiplier = _expected_wild_multiplier(state["wild_expansion_reels"])
        if type(payload["multiplier"]) is not int or payload["multiplier"] != expected_multiplier:
            raise PresentationContractError("multiplier event must match the preceding Wild expansion")
        next_state["active_multiplier"] = payload["multiplier"]
    elif kind == "FEATURE_SPIN_RESOLVED":
        required = {"spin_number", "board", "display_board", "raw_payout_milli", "payout_milli",
                    "max_win_capped", "payout_awarded_milli", "retrigger_awarded", "remaining_spins",
                    "round_payout_after_milli", "round_cap_applied", "wild_reels", "multiplier"}
        if state["status"] != "FEATURE_REELS" or state["feature_reels_stopped"] != 5 or set(payload) != required:
            raise PresentationContractError("feature resolution requires five stopped reels")
        if type(payload["spin_number"]) is not int or payload["spin_number"] != state["feature_spins_played"] + 1:
            raise PresentationContractError("feature spin sequence is not contiguous")
        board = _board(payload["board"], "board")
        display = _board(payload["display_board"], "display_board")
        feature_scatter_count = sum(symbol == SCATTER for reel in board for symbol in reel)
        if feature_scatter_count >= 3:
            raise PresentationContractError("Free Spins 3+ Scatter/retrigger behavior is unspecified and disabled")
        if state["feature_stopped_reels"] != board:
            raise PresentationContractError("feature outcome board differs from stopped reel events")
        for field in ("raw_payout_milli", "payout_milli", "payout_awarded_milli", "retrigger_awarded", "remaining_spins", "round_payout_after_milli"):
            if type(payload[field]) is not int or payload[field] < 0:
                raise PresentationContractError("%s must be a non-negative integer" % field)
        if type(payload["round_cap_applied"]) is not bool:
            raise PresentationContractError("round_cap_applied must be a boolean")
        if type(payload["max_win_capped"]) is not bool:
            raise PresentationContractError("max_win_capped must be an exact boolean")
        if payload["retrigger_awarded"] > CONFIG.feature_rules.max_total_free_spins - state["feature_spins_awarded_total"]:
            raise PresentationContractError("cumulative Free Spins awards exceed the configured feature cap")
        if payload["retrigger_awarded"] != 0:
            raise PresentationContractError("Free Spins retrigger is unspecified and therefore disabled")
        expected_remaining = state["feature_spins_remaining"] - 1 + payload["retrigger_awarded"]
        if payload["remaining_spins"] != expected_remaining:
            raise PresentationContractError("remaining Free Spins does not match consumption and retrigger")
        wild_reels = payload["wild_reels"]
        if not isinstance(wild_reels, list) or any(type(x) is not int or x < 0 or x > 4 for x in wild_reels) or len(set(wild_reels)) != len(wild_reels):
            raise PresentationContractError("resolved Wild reel indices are invalid")
        if wild_reels != state.get("wild_expansion_reels", []):
            raise PresentationContractError("resolved Wild reels disagree with the expansion event")
        if display != _expected_display_board(board, wild_reels):
            raise PresentationContractError("feature display board must exactly match raw board plus expanded Wild reels")
        if wild_reels and state.get("wild_expansion_display_board") != display:
            raise PresentationContractError("Wild expansion display board differs from resolved display board")
        multiplier = payload["multiplier"]
        if (type(multiplier) is not int or multiplier != _expected_wild_multiplier(wild_reels)
                or (multiplier > 1 and state.get("active_multiplier") != multiplier)
                or (multiplier == 1 and "active_multiplier" in state)):
            raise PresentationContractError("resolved multiplier disagrees with multiplier event")
        multiplied_payout = payload["raw_payout_milli"] * multiplier
        if (payload["payout_milli"] != min(multiplied_payout, CONFIG.max_win_milli)
                or payload["max_win_capped"] != (multiplied_payout > CONFIG.max_win_milli)):
            raise PresentationContractError("feature per-spin payout or max-win cap evidence is inconsistent")
        next_state["feature_spins_played"] += 1
        next_state["feature_spins_remaining"] = payload["remaining_spins"]
        expected_round_payout = min(
            CONFIG.max_round_win_milli,
            state["total_payout_milli"] + payload["payout_milli"],
        )
        expected_spin_award = expected_round_payout - state["total_payout_milli"]
        expected_cap_applied = state["total_payout_milli"] + payload["payout_milli"] > CONFIG.max_round_win_milli
        if payload["payout_awarded_milli"] != expected_spin_award:
            raise PresentationContractError("per-spin awarded payout does not reconcile with the capped round total")
        if payload["round_cap_applied"] != expected_cap_applied:
            raise PresentationContractError("round-cap evidence does not match raw spin payout arithmetic")
        next_state["feature_payout_milli"] += payload["payout_awarded_milli"]
        next_state["feature_spins_awarded_total"] += payload["retrigger_awarded"]
        if payload["round_payout_after_milli"] != expected_round_payout:
            raise PresentationContractError("round payout projection must equal prior total plus this spin, capped at the configured round limit")
        next_state["total_payout_milli"] = expected_round_payout
        next_state["round_cap_reached"] = expected_round_payout == CONFIG.max_round_win_milli
        next_state["feature_reels_stopped"] = 0
        next_state["feature_stopped_reels"] = []
        next_state.pop("wild_expansion_reels", None)
        next_state.pop("wild_expansion_display_board", None)
        next_state.pop("active_multiplier", None)
        next_state["status"] = "FEATURE_REELS" if payload["remaining_spins"] else "FEATURE_END_PENDING"
    elif kind == "FEATURE_ENDED":
        if (state["status"] not in ("FEATURE_END_PENDING", "FEATURE_REELS") or not state["feature_active"]
                or state["feature_reels_stopped"] != 0 or state.get("wild_expansion_reels")
                or "active_multiplier" in state):
            raise PresentationContractError("Free Spins feature is not active")
        if set(payload) != {"spins_played", "remaining_spins", "payout_milli", "termination_reason", "round_cap_reached"}:
            raise PresentationContractError("invalid Free Spins end payload")
        if (any(type(payload[key]) is not int for key in ("spins_played", "remaining_spins", "payout_milli"))
                or payload["spins_played"] != state["feature_spins_played"]
                or payload["remaining_spins"] != state["feature_spins_remaining"]
                or payload["payout_milli"] != state["feature_payout_milli"]):
            raise PresentationContractError("Free Spins end totals disagree with resolved events")
        reason = payload["termination_reason"]
        if type(payload["round_cap_reached"]) is not bool:
            raise PresentationContractError("round_cap_reached must be a boolean")
        if (reason not in ("EXHAUSTED", "ROUND_CAP")
                or (reason == "EXHAUSTED" and (state["status"] != "FEATURE_END_PENDING" or state["feature_spins_remaining"] != 0 or payload["round_cap_reached"]))
                or (reason == "ROUND_CAP" and (not payload["round_cap_reached"] or not state["round_cap_reached"]))
                or payload["round_cap_reached"] != state["round_cap_reached"]):
            raise PresentationContractError("invalid Free Spins termination reason")
        next_state.update(status="COMPLETABLE", feature_active=False)
    elif kind == "ROUND_PRESENTATION_COMPLETED":
        if state["status"] != "COMPLETABLE" or set(payload) != {"total_payout_milli", "feature_spins_played", "round_cap_reached"}:
            raise PresentationContractError("round presentation cannot complete in this state")
        if (type(payload["total_payout_milli"]) is not int or payload["total_payout_milli"] < 0
                or type(payload["feature_spins_played"]) is not int
                or type(payload["round_cap_reached"]) is not bool
                or payload["round_cap_reached"] != state["round_cap_reached"]
                or payload["feature_spins_played"] != state["feature_spins_played"]
                or payload["total_payout_milli"] != state["total_payout_milli"]):
            raise PresentationContractError("completed presentation totals mismatch")
        next_state["total_payout_milli"] = payload["total_payout_milli"]
        next_state["status"] = "COMPLETED"
    else:
        raise PresentationContractError("unknown presentation event: %s" % kind)

    next_state["event_count"] = event["sequence"]
    next_state["last_event_hash"] = event["event_hash"]
    return next_state


def replay_events(round_id, events, classification=PRESENTATION_CLASSIFICATION):
    state = initial_state(round_id, classification)
    seen = set()
    for event in events:
        if not isinstance(event, dict) or event.get("event_id") in seen:
            raise PresentationContractError("event stream contains a non-object or duplicate event_id")
        seen.add(event.get("event_id"))
        state = apply_event(state, event)
    return state


def build_presentation_events(round_id, outcome, classification=PRESENTATION_CLASSIFICATION):
    """Project a resolved BASE outcome into a deterministic, non-authoritative UI trace."""
    if (not isinstance(outcome, dict) or type(outcome.get("mode")) is not str or outcome.get("mode") != "BASE"
            or type(classification) is not str or classification != PRESENTATION_CLASSIFICATION):
        raise PresentationContractError("only a BASE outcome can be projected as non-financial presentation data")
    base = outcome.get("base_result")
    if not isinstance(base, dict) or type(base.get("mode")) is not str or base.get("mode") != "BASE":
        raise PresentationContractError("outcome has no base_result")
    board = _board(base.get("board"), "base board")
    display = _board(base.get("display_board"), "base display_board")
    initial_spins = outcome.get("initial_free_spins")
    if (type(initial_spins) is not int or initial_spins not in (0, 10, 12)
            or type(base.get("free_spins_awarded")) is not int or base["free_spins_awarded"] != initial_spins):
        raise PresentationContractError("outcome does not satisfy the BASE 3=>10 / 4=>12 Free Spins award contract")
    scatter_count = sum(symbol == SCATTER for reel in board for symbol in reel)
    if type(base.get("scatter_count")) is not int or base["scatter_count"] != scatter_count:
        raise PresentationContractError("BASE Scatter count differs from the authoritative board")
    if scatter_count == 5:
        raise PresentationContractError("5 Scatter requires the embedded EPICBUY_V37 provider payload, unavailable in this local runtime")
    if scatter_count >= 6:
        raise PresentationContractError("6+ BASE Scatter behavior is not authorized")
    expected_initial = 10 if scatter_count == 3 else 12 if scatter_count == 4 else 0
    if initial_spins != expected_initial:
        raise PresentationContractError("BASE Scatter count and 3=>10 / 4=>12 Free Spins award disagree")
    base_raw_payout = base.get("raw_payout_milli")
    base_multiplier = base.get("wild_multiplier")
    base_expanded = base.get("expanded_wild_reels")
    base_max_win_capped = base.get("max_win_capped")
    base_payout = base.get("payout_milli")
    if (type(base_raw_payout) is not int or base_raw_payout < 0
            or type(base_multiplier) is not int or base_multiplier != 1
            or type(base_expanded) is not list or base_expanded
            or type(base_max_win_capped) is not bool
            or type(base_payout) is not int or base_payout < 0 or base_payout > CONFIG.max_win_milli
            or base_payout != min(base_raw_payout * base_multiplier, CONFIG.max_win_milli)
            or base_max_win_capped != (base_raw_payout * base_multiplier > CONFIG.max_win_milli)):
        raise PresentationContractError("BASE payout, Wild multiplier and per-spin cap evidence are inconsistent")
    if display != board:
        raise PresentationContractError("BASE display board must exactly match its raw board")
    if type(outcome.get("total_payout_milli")) is not int or outcome["total_payout_milli"] < 0:
        raise PresentationContractError("final round payout must be a non-negative integer")
    round_cap_reached = outcome.get("round_cap_reached")
    if type(round_cap_reached) is not bool:
        raise PresentationContractError("round_cap_reached must be a boolean")
    base_payout_capped = min(base_payout, CONFIG.max_round_win_milli)
    base_round_cap_reached = base_payout_capped == CONFIG.max_round_win_milli
    feature_events = outcome.get("feature_events")
    feature_spins_played = outcome.get("free_spins_played")
    if (not isinstance(feature_events, list) or type(feature_spins_played) is not int
            or feature_spins_played != len(feature_events)):
        raise PresentationContractError("feature event count does not match resolved outcome")
    if initial_spins == 0 and feature_events:
        raise PresentationContractError("Free Spins events cannot exist without an authorized BASE award")
    if initial_spins and not round_cap_reached and len(feature_events) != initial_spins:
        raise PresentationContractError("all awarded Free Spins must resolve unless the round cap is reached")
    if len(feature_events) > initial_spins:
        raise PresentationContractError("feature event count exceeds the authorized initial Free Spins")
    awarded_total = outcome.get("free_spins_awarded_total")
    if (type(awarded_total) is not int or awarded_total != initial_spins
            or awarded_total > CONFIG.feature_rules.max_total_free_spins):
        raise PresentationContractError("cumulative Free Spins awards exceed or disagree with the configured feature cap")

    classification = PRESENTATION_CLASSIFICATION
    state = initial_state(round_id, classification)
    events = []

    def emit(kind, payload):
        nonlocal state
        event = make_event(state, kind, payload)
        state = apply_event(state, event)
        events.append(event)

    emit("ROUND_PRESENTATION_STARTED", {"mode": "BASE", "classification": classification})
    for reel_index, reel in enumerate(board):
        emit("BASE_REEL_STOPPED", {"reel_index": reel_index, "symbols": reel})
    emit("BASE_OUTCOME_REVEALED", {
        "board": board, "display_board": display,
        "raw_payout_milli": base_raw_payout, "payout_milli": base_payout,
        "wild_reels": [], "multiplier": base_multiplier,
        "max_win_capped": base_max_win_capped,
        "free_spins_awarded": initial_spins,
        "round_cap_reached": base_round_cap_reached,
    })

    remaining = initial_spins
    projected_round_payout = base_payout_capped
    if initial_spins:
        emit("FEATURE_STARTED", {"feature": "FREE_SPINS", "initial_spins": initial_spins})
        for index, item in enumerate(feature_events, start=1):
            if not isinstance(item, dict) or type(item.get("spin_number")) is not int or item["spin_number"] != index:
                raise PresentationContractError("feature spin numbers must be contiguous")
            result = item.get("result")
            if not isinstance(result, dict):
                raise PresentationContractError("feature result is missing")
            if result.get("jackpot_triggered"):
                raise PresentationContractError("jackpot presentation is disabled until canonical Math authorizes its trigger and payout")
            if type(result.get("jackpot_triggered")) is not bool or type(item.get("jackpot_triggered")) is not bool:
                raise PresentationContractError("jackpot evidence must be explicit booleans")
            if item["jackpot_triggered"] != result["jackpot_triggered"] or item["jackpot_triggered"]:
                raise PresentationContractError("jackpot termination requires matching authorized evidence")
            feature_board = _board(result.get("board"), "feature board")
            actual_feature_scatters = sum(symbol == SCATTER for reel in feature_board for symbol in reel)
            if (type(result.get("scatter_count")) is not int
                    or result["scatter_count"] != actual_feature_scatters
                    or actual_feature_scatters >= 3
                    or type(item.get("retrigger_requested")) is not int
                    or item["retrigger_requested"] != 0
                    or type(item.get("retrigger_awarded")) is not int
                    or item["retrigger_awarded"] != 0):
                raise PresentationContractError("Free Spins 3+ Scatter/retrigger behavior is unspecified and disabled")
            feature_display = _board(result.get("display_board"), "feature display_board")
            raw_payout = result.get("raw_payout_milli")
            payout = result.get("payout_milli")
            max_win_capped = result.get("max_win_capped")
            if (type(raw_payout) is not int or raw_payout < 0
                    or type(payout) is not int or payout < 0 or payout > CONFIG.max_win_milli
                    or type(max_win_capped) is not bool):
                raise PresentationContractError("feature raw/capped payout and max_win_capped must have exact types and bounds")
            after = item.get("round_payout_after_milli")
            expected_after = min(CONFIG.max_round_win_milli, projected_round_payout + result["payout_milli"])
            if type(after) is not int or after != expected_after:
                raise PresentationContractError("round payout projection must equal prior total plus this spin, capped at the configured round limit")
            payout_awarded = item.get("payout_awarded_milli")
            if type(payout_awarded) is not int or payout_awarded != expected_after - projected_round_payout:
                raise PresentationContractError("per-spin awarded payout does not reconcile with cumulative round payout")
            cap_applied = item.get("round_cap_applied")
            expected_cap_applied = projected_round_payout + result["payout_milli"] > CONFIG.max_round_win_milli
            if type(cap_applied) is not bool or cap_applied != expected_cap_applied:
                raise PresentationContractError("round-cap evidence does not match raw spin payout arithmetic")
            expanded = result.get("expanded_wild_reels")
            if (not isinstance(expanded, list) or any(type(x) is not int or x < 0 or x > 4 for x in expanded)
                    or len(set(expanded)) != len(expanded)):
                raise PresentationContractError("expanded Wild reel indices are invalid")
            multiplier = result.get("wild_multiplier")
            if type(multiplier) is not int or multiplier != _expected_wild_multiplier(expanded):
                raise PresentationContractError("Wild multiplier must match the exact expanded reel count and configured rule")
            multiplied_payout = raw_payout * multiplier
            if (payout != min(multiplied_payout, CONFIG.max_win_milli)
                    or max_win_capped != (multiplied_payout > CONFIG.max_win_milli)):
                raise PresentationContractError("feature payout_milli must equal capped raw payout times Wild multiplier")
            if feature_display != _expected_display_board(feature_board, expanded):
                raise PresentationContractError("feature display board must be derived exactly from the raw board and expanded Wild reels")
            spin_number = index
            for reel_index, reel in enumerate(feature_board):
                emit("FEATURE_REEL_STOPPED", {"spin_number": spin_number,
                                               "reel_index": reel_index, "symbols": reel})
            if expanded:
                emit("WILD_EXPANSION_APPLIED", {"spin_number": spin_number,
                                                  "reels": list(expanded), "display_board": feature_display})
            if multiplier > 1:
                emit("MULTIPLIER_APPLIED", {"spin_number": spin_number, "multiplier": multiplier})
            remaining -= 1
            emit("FEATURE_SPIN_RESOLVED", {
                "spin_number": spin_number, "board": feature_board,
                "display_board": feature_display,
                "raw_payout_milli": raw_payout, "payout_milli": payout,
                "max_win_capped": max_win_capped,
                "payout_awarded_milli": payout_awarded,
                "retrigger_awarded": 0,
                "remaining_spins": remaining,
                "round_payout_after_milli": after,
                "round_cap_applied": cap_applied,
                "wild_reels": list(expanded), "multiplier": multiplier,
            })
            projected_round_payout = after
        if not round_cap_reached and remaining != 0:
            raise PresentationContractError("Free Spins ended before exhaustion without a round cap")
        emit("FEATURE_ENDED", {
            "spins_played": len(feature_events), "remaining_spins": remaining,
            "payout_milli": sum(item["payout_awarded_milli"] for item in feature_events),
            "termination_reason": "ROUND_CAP" if round_cap_reached else "EXHAUSTED",
            "round_cap_reached": round_cap_reached,
        })

    if outcome["total_payout_milli"] != projected_round_payout:
        raise PresentationContractError("final payout does not match the final Engine round-payout projection")
    if round_cap_reached != (projected_round_payout == CONFIG.max_round_win_milli):
        raise PresentationContractError("final round-cap flag does not match the capped final payout")
    emit("ROUND_PRESENTATION_COMPLETED", {
        "total_payout_milli": outcome["total_payout_milli"],
        "feature_spins_played": len(feature_events),
        "round_cap_reached": round_cap_reached,
    })
    return events
