"""Versioned, deterministic round-event contract and replay reducer.

This contract is Provider-neutral. It records lifecycle facts; it does not define
canonical slot mathematics or claim distributed exactly-once delivery.
"""
import copy
import hashlib
import json
import re

from ganesha.math.config import CONFIG

SCHEMA_VERSION = 1
ZERO_HASH = "0" * 64
MODES = frozenset(("BASE", "MAGIC_BUY", "EPIC_BUY"))
TERMINAL = frozenset(("SETTLED", "REFUNDED"))
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class EventContractError(ValueError):
    pass


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def initial_state(round_id):
    if not isinstance(round_id, str) or not round_id:
        raise EventContractError("round_id is required")
    return {
        "schema_version": SCHEMA_VERSION,
        "round_id": round_id,
        "status": "CREATED",
        "mode": None,
        "account_id": None,
        "currency": None,
        "debit_minor": None,
        "rng_commitment": None,
        "generator_version": None,
        "outcome_sha256": None,
        "payout_minor": None,
        "settlement_operation_id": None,
        "refund_operation_id": None,
        "feature": None,
        "feature_spins_played": 0,
        "feature_spins_remaining": 0,
        "feature_payout_milli": 0,
        "feature_base_payout_milli": None,
        "round_cap_milli": None,
        "round_cap_reached": False,
        "event_count": 0,
        "last_event_hash": ZERO_HASH,
    }


def _integer(payload, key, minimum=0):
    value = payload.get(key)
    if type(value) is not int or value < minimum:
        raise EventContractError("%s must be an integer >= %d" % (key, minimum))
    return value


def _required_text(payload, key):
    value = payload.get(key)
    if not isinstance(value, str) or not value or len(value) > 256:
        raise EventContractError("%s must be a non-empty string" % key)
    return value


def _valid_board(value):
    return (isinstance(value, list) and len(value) == 5
            and all(isinstance(reel, list) and len(reel) == 3
                    and all(isinstance(symbol, str) and 0 < len(symbol) <= 32 for symbol in reel)
                    for reel in value))


def make_event(state, event_id, event_type, payload):
    if not isinstance(event_id, str) or not event_id or len(event_id) > 256:
        raise EventContractError("event_id must be a non-empty string")
    if not isinstance(event_type, str) or not event_type or len(event_type) > 64:
        raise EventContractError("event_type must be a non-empty string")
    if not isinstance(payload, dict):
        raise EventContractError("event payload must be an object")
    event = {
        "schema_version": SCHEMA_VERSION,
        "round_id": state["round_id"],
        "sequence": state["event_count"] + 1,
        "event_id": event_id,
        "event_type": event_type,
        "payload": payload,
        "previous_hash": state["last_event_hash"],
    }
    event["event_hash"] = hashlib.sha256(canonical_json(event).encode("ascii")).hexdigest()
    return event


def apply_event(state, event):
    if not isinstance(event, dict) or event.get("schema_version") != SCHEMA_VERSION:
        raise EventContractError("unsupported or missing event schema version")
    if set(event) != {"schema_version", "round_id", "sequence", "event_id", "event_type",
                      "payload", "previous_hash", "event_hash"}:
        raise EventContractError("event envelope contains missing or unknown fields")
    if event.get("round_id") != state["round_id"]:
        raise EventContractError("event round_id mismatch")
    if type(event.get("sequence")) is not int or event["sequence"] != state["event_count"] + 1:
        raise EventContractError("event sequence gap or duplicate")
    if event.get("previous_hash") != state["last_event_hash"]:
        raise EventContractError("event hash-chain predecessor mismatch")
    if (not isinstance(event.get("event_id"), str) or not event["event_id"]
            or len(event["event_id"]) > 256):
        raise EventContractError("event_id is required")
    if not isinstance(event.get("payload"), dict):
        raise EventContractError("event payload must be an object")
    unhashed = {key: value for key, value in event.items() if key != "event_hash"}
    expected_hash = hashlib.sha256(canonical_json(unhashed).encode("ascii")).hexdigest()
    if event.get("event_hash") != expected_hash:
        raise EventContractError("event hash mismatch")

    event_type = event.get("event_type")
    payload = event["payload"]
    next_state = dict(state)

    if event_type == "ROUND_OPENED":
        if (state["status"] != "CREATED" or set(payload) != {"mode"}
                or not isinstance(payload.get("mode"), str) or payload["mode"] not in MODES):
            raise EventContractError("invalid ROUND_OPENED transition or payload")
        next_state["mode"] = payload["mode"]
        next_state["status"] = "OPEN"
    elif event_type == "BET_RESERVED":
        if state["status"] != "OPEN" or set(payload) != {"account_id", "currency", "debit_minor", "operation_id"}:
            raise EventContractError("invalid BET_RESERVED transition or payload")
        next_state["account_id"] = _required_text(payload, "account_id")
        next_state["currency"] = _required_text(payload, "currency")
        next_state["debit_minor"] = _integer(payload, "debit_minor", 1)
        next_state["debit_operation_id"] = _required_text(payload, "operation_id")
        next_state["status"] = "BET_RESERVED"
    elif event_type == "RNG_COMMITTED":
        if state["status"] != "BET_RESERVED" or state["rng_commitment"] is not None or set(payload) != {"commitment", "generator_version"}:
            raise EventContractError("invalid RNG_COMMITTED transition or payload")
        commitment = _required_text(payload, "commitment")
        if not (_HEX64.fullmatch(commitment) or commitment.startswith("TEST:")):
            raise EventContractError("RNG commitment format is invalid")
        next_state["rng_commitment"] = commitment
        next_state["generator_version"] = _required_text(payload, "generator_version")
    elif event_type == "FEATURE_STARTED":
        if state["status"] != "BET_RESERVED" or state["rng_commitment"] is None or state["feature"] is not None:
            raise EventContractError("FEATURE_STARTED requires a committed RNG and no active feature")
        cap_fields = {"base_payout_milli", "round_cap_milli"}
        if (set(payload) not in ({"feature", "initial_spins"}, {"feature", "initial_spins"} | cap_fields)
                or payload.get("feature") != "FREE_SPINS"):
            raise EventContractError("unsupported feature payload")
        spins = _integer(payload, "initial_spins", 1)
        next_state["feature"] = "FREE_SPINS"
        next_state["feature_spins_remaining"] = spins
        if cap_fields.issubset(payload):
            base_payout = _integer(payload, "base_payout_milli")
            round_cap = _integer(payload, "round_cap_milli", 1)
            if base_payout > round_cap:
                raise EventContractError("base payout already exceeds the declared round cap")
            next_state["feature_base_payout_milli"] = base_payout
            next_state["round_cap_milli"] = round_cap
            next_state["round_cap_reached"] = base_payout == round_cap
    elif event_type == "FEATURE_SPIN_RESOLVED":
        if state["status"] != "BET_RESERVED" or state["feature"] != "FREE_SPINS" or state["feature_spins_remaining"] <= 0:
            raise EventContractError("FEATURE_SPIN_RESOLVED without an active Free Spins feature")
        if state["round_cap_reached"]:
            raise EventContractError("FEATURE_SPIN_RESOLVED cannot continue after the round cap is reached")
        required = {"spin_number", "stops", "payout_milli", "retrigger_awarded", "remaining_spins"}
        optional = {"board", "display_board", "round_payout_after_milli", "round_cap_applied"}
        if not required.issubset(payload) or set(payload) - required - optional:
            raise EventContractError("FEATURE_SPIN_RESOLVED payload schema mismatch")
        if _integer(payload, "spin_number", 1) != state["feature_spins_played"] + 1:
            raise EventContractError("Free Spins sequence is not contiguous")
        stops = payload["stops"]
        if not isinstance(stops, list) or len(stops) != 5 or any(type(x) is not int or x < 0 for x in stops):
            raise EventContractError("stops must contain five non-negative integer positions")
        payout = _integer(payload, "payout_milli")
        retrigger = _integer(payload, "retrigger_awarded")
        remaining = _integer(payload, "remaining_spins")
        if retrigger != 0:
            raise EventContractError("Free Spins retrigger is unspecified and therefore disabled")
        expected_remaining = state["feature_spins_remaining"] - 1 + retrigger
        if remaining != expected_remaining:
            raise EventContractError("remaining Free Spins does not match consumption and retrigger")
        for field in ("board", "display_board"):
            if field in payload and not _valid_board(payload[field]):
                raise EventContractError("Feature event board is malformed")
        cap_fields = {"round_payout_after_milli", "round_cap_applied"}
        if state["round_cap_milli"] is not None:
            if not cap_fields.issubset(payload):
                raise EventContractError("feature spin is missing round-cap reconciliation evidence")
            round_after = _integer(payload, "round_payout_after_milli")
            cap_applied = payload["round_cap_applied"]
            if type(cap_applied) is not bool:
                raise EventContractError("round_cap_applied must be boolean")
            expected_after = min(
                state["feature_base_payout_milli"] + state["feature_payout_milli"] + payout,
                state["round_cap_milli"],
            )
            if round_after != expected_after:
                raise EventContractError("feature spin round payout does not reconcile to base, feature and cap")
            if cap_applied and round_after != state["round_cap_milli"]:
                raise EventContractError("round-cap application flag lacks exact cap payout evidence")
            next_state["round_cap_reached"] = round_after == state["round_cap_milli"]
        elif cap_fields.intersection(payload):
            raise EventContractError("round-cap spin evidence requires a declared base payout and cap")
        next_state["feature_spins_played"] += 1
        next_state["feature_spins_remaining"] = remaining
        next_state["feature_payout_milli"] += payout
    elif event_type == "FEATURE_ENDED":
        if state["status"] != "BET_RESERVED" or state["feature"] != "FREE_SPINS":
            raise EventContractError("FEATURE_ENDED without active Free Spins")
        if set(payload) != {"spins_played", "payout_milli", "termination_reason"}:
            raise EventContractError("FEATURE_ENDED payload schema mismatch")
        if _integer(payload, "spins_played") != state["feature_spins_played"] or _integer(payload, "payout_milli") != state["feature_payout_milli"]:
            raise EventContractError("FEATURE_ENDED totals disagree with resolved spins")
        reason = payload["termination_reason"]
        if reason == "ROUND_CAP":
            if state["round_cap_milli"] is None or not state["round_cap_reached"]:
                raise EventContractError("ROUND_CAP termination requires verifiable exact round-cap evidence")
        elif reason == "EXHAUSTED":
            if state["feature_spins_remaining"] != 0 or state["round_cap_reached"]:
                raise EventContractError("EXHAUSTED termination requires zero remaining spins below the round cap")
        else:
            raise EventContractError("invalid Free Spins termination reason")
        next_state["feature"] = None
    elif event_type == "OUTCOME_COMMITTED":
        if state["status"] != "BET_RESERVED" or state["rng_commitment"] is None or state["feature"] is not None:
            raise EventContractError("OUTCOME_COMMITTED requires RNG commitment and completed features")
        required = {"outcome_sha256", "payout_minor", "engine_version"}
        optional = {"base_board", "base_display_board", "base_payout_milli",
                    "feature_payout_milli", "total_payout_milli"}
        if not required.issubset(payload) or set(payload) - required - optional:
            raise EventContractError("OUTCOME_COMMITTED payload schema mismatch")
        digest = _required_text(payload, "outcome_sha256")
        if not _HEX64.fullmatch(digest):
            raise EventContractError("outcome_sha256 must be lowercase SHA-256")
        next_state["outcome_sha256"] = digest
        next_state["payout_minor"] = _integer(payload, "payout_minor")
        next_state["engine_version"] = _required_text(payload, "engine_version")
        payout_fields = {"base_payout_milli", "feature_payout_milli", "total_payout_milli"}
        present_payout_fields = payout_fields.intersection(payload)
        if present_payout_fields and present_payout_fields != payout_fields:
            raise EventContractError("outcome milli-payout fields must be supplied together")
        if present_payout_fields:
            base_milli = _integer(payload, "base_payout_milli")
            feature_milli = _integer(payload, "feature_payout_milli")
            total_milli = _integer(payload, "total_payout_milli")
            if feature_milli != state["feature_payout_milli"]:
                raise EventContractError("committed feature payout differs from resolved feature events")
            if total_milli != base_milli + feature_milli:
                raise EventContractError("committed total payout differs from base plus feature payout")
            if state["round_cap_milli"] is not None:
                if (base_milli != state["feature_base_payout_milli"]
                        or total_milli > state["round_cap_milli"]
                        or state["round_cap_reached"] != (total_milli == state["round_cap_milli"])):
                    raise EventContractError("committed round payout does not reconcile to declared base and round cap")
            next_state["base_payout_milli"] = base_milli
            next_state["total_payout_milli"] = total_milli
        elif state["round_cap_milli"] is not None:
            raise EventContractError("capped feature outcome requires complete committed milli-payout fields")
        for field in ("base_board", "base_display_board"):
            if field in payload and not _valid_board(payload[field]):
                raise EventContractError("Outcome board is malformed")
        next_state["status"] = "OUTCOME_COMMITTED"
    elif event_type == "WIN_PRESENTED":
        if state["status"] != "OUTCOME_COMMITTED" or set(payload) != {"payout_minor"} or _integer(payload, "payout_minor") != state["payout_minor"]:
            raise EventContractError("WIN_PRESENTED must match the immutable committed payout")
        if state.get("win_presented"):
            raise EventContractError("WIN_PRESENTED cannot be repeated")
        next_state["win_presented"] = True
    elif event_type == "SETTLED":
        if state["status"] != "OUTCOME_COMMITTED" or set(payload) != {"operation_id", "credit_minor", "currency"}:
            raise EventContractError("invalid SETTLED transition or payload")
        if _integer(payload, "credit_minor") != state["payout_minor"] or payload.get("currency") != state["currency"]:
            raise EventContractError("settlement amount or currency differs from committed round")
        next_state["settlement_operation_id"] = _required_text(payload, "operation_id")
        next_state["status"] = "SETTLED"
    elif event_type == "REFUNDED":
        if state["status"] != "BET_RESERVED" or set(payload) != {"operation_id", "refund_minor", "currency"}:
            raise EventContractError("invalid REFUNDED transition or payload")
        if _integer(payload, "refund_minor") != state["debit_minor"] or payload.get("currency") != state["currency"]:
            raise EventContractError("refund amount or currency differs from reserved debit")
        next_state["refund_operation_id"] = _required_text(payload, "operation_id")
        next_state["status"] = "REFUNDED"
    elif event_type == "END_ROUND":
        if state["status"] not in TERMINAL or set(payload) != {"terminal_status"} or payload.get("terminal_status") != state["status"]:
            raise EventContractError("END_ROUND must match a settled or refunded state")
        if state.get("ended"):
            raise EventContractError("END_ROUND cannot be repeated")
        next_state["ended"] = True
        next_state["status"] = "ENDED"
    else:
        raise EventContractError("unknown event type: %s" % event_type)

    next_state["event_count"] = event["sequence"]
    next_state["last_event_hash"] = event["event_hash"]
    return next_state


def replay_events(round_id, events):
    state = initial_state(round_id)
    seen_ids = set()
    for event in events:
        if not isinstance(event, dict):
            raise EventContractError("event stream entries must be objects")
        event_id = event.get("event_id")
        if not isinstance(event_id, str) or not event_id or len(event_id) > 256:
            raise EventContractError("event stream entry has an invalid event_id")
        if event_id in seen_ids:
            raise EventContractError("duplicate event_id in event stream")
        seen_ids.add(event_id)
        state = apply_event(state, event)
    return state


# A separate non-financial lifecycle uses the same envelope/hash primitives as
# the Wallet Round contract without fabricating BET_RESERVED or zero-value debit
# records. It is deliberately not accepted by apply_event/replay_events.
SIMULATION_CLASSIFICATION = "NON_FINANCIAL_SIMULATION"


def initial_simulation_state(round_id):
    if not isinstance(round_id, str) or not round_id or len(round_id) > 128:
        raise EventContractError("simulation round_id is required")
    return {
        "schema_version": SCHEMA_VERSION,
        "round_id": round_id,
        "classification": SIMULATION_CLASSIFICATION,
        "financial_effects": False,
        "status": "CREATED",
        "mode": None,
        "math_version": None,
        "base_board": None,
        "base_display_board": None,
        "scatter_count": None,
        "initial_free_spins": 0,
        "free_spins_played": 0,
        "base_payout_milli": 0,
        "feature_payout_milli": 0,
        "total_payout_milli": 0,
        "round_cap_reached": False,
        "event_count": 0,
        "last_event_hash": ZERO_HASH,
    }


def make_simulation_event(state, event_id, event_type, payload):
    if not isinstance(event_id, str) or not event_id or len(event_id) > 256:
        raise EventContractError("simulation event_id must be a non-empty string")
    if not isinstance(event_type, str) or not event_type or len(event_type) > 64:
        raise EventContractError("simulation event_type must be a non-empty string")
    if not isinstance(payload, dict):
        raise EventContractError("simulation event payload must be an object")
    event = {
        "schema_version": SCHEMA_VERSION,
        "round_id": state["round_id"],
        "sequence": state["event_count"] + 1,
        "event_id": event_id,
        "event_type": event_type,
        "payload": payload,
        "previous_hash": state["last_event_hash"],
    }
    event["event_hash"] = hashlib.sha256(canonical_json(event).encode("ascii")).hexdigest()
    return event


def apply_simulation_event(state, event):
    if not isinstance(event, dict) or event.get("schema_version") != SCHEMA_VERSION:
        raise EventContractError("unsupported simulation event schema version")
    if set(event) != {"schema_version", "round_id", "sequence", "event_id", "event_type",
                      "payload", "previous_hash", "event_hash"}:
        raise EventContractError("simulation event envelope contains missing or unknown fields")
    if event.get("round_id") != state["round_id"]:
        raise EventContractError("simulation event round_id mismatch")
    if type(event.get("sequence")) is not int or event["sequence"] != state["event_count"] + 1:
        raise EventContractError("simulation event sequence gap or duplicate")
    if event.get("previous_hash") != state["last_event_hash"]:
        raise EventContractError("simulation event predecessor hash mismatch")
    if not isinstance(event.get("event_id"), str) or not event["event_id"] or len(event["event_id"]) > 256:
        raise EventContractError("simulation event_id is invalid")
    if not isinstance(event.get("payload"), dict):
        raise EventContractError("simulation event payload must be an object")
    unhashed = {key: value for key, value in event.items() if key != "event_hash"}
    digest = hashlib.sha256(canonical_json(unhashed).encode("ascii")).hexdigest()
    if event.get("event_hash") != digest:
        raise EventContractError("simulation event hash mismatch")
    payload = event["payload"]
    next_state = dict(state)
    if event["event_type"] == "SIMULATION_STARTED":
        if state["status"] != "CREATED" or set(payload) != {"mode", "math_version"} or payload.get("mode") != "BASE":
            raise EventContractError("invalid SIMULATION_STARTED transition or payload")
        next_state["mode"] = "BASE"
        next_state["math_version"] = _required_text(payload, "math_version")
        next_state["status"] = "RUNNING"
    elif event["event_type"] == "SIMULATION_OUTCOME_COMMITTED":
        required = {"base_board", "base_display_board", "scatter_count", "initial_free_spins",
                    "free_spins_played", "base_payout_milli", "feature_payout_milli",
                    "total_payout_milli", "round_cap_reached", "math_version"}
        if state["status"] != "RUNNING" or set(payload) != required:
            raise EventContractError("invalid SIMULATION_OUTCOME_COMMITTED transition or payload")
        if not _valid_board(payload["base_board"]) or not _valid_board(payload["base_display_board"]):
            raise EventContractError("simulation committed board must be exactly 5x3")
        if payload["base_display_board"] != payload["base_board"]:
            raise EventContractError("BASE simulation display board must equal the raw stopped board")
        scatter_count = _integer(payload, "scatter_count")
        initial_spins = _integer(payload, "initial_free_spins")
        played = _integer(payload, "free_spins_played")
        base = _integer(payload, "base_payout_milli")
        feature = _integer(payload, "feature_payout_milli")
        total = _integer(payload, "total_payout_milli")
        actual_scatter_count = sum(
            symbol == "SCATTER_LOTUS"
            for reel in payload["base_board"] for symbol in reel
        )
        if scatter_count != actual_scatter_count:
            raise EventContractError("simulation Scatter count differs from the committed BASE board")
        if scatter_count == 5:
            raise EventContractError("5 Scatter requires an embedded EPICBUY_V37 provider payload")
        if scatter_count >= 6:
            raise EventContractError("6+ Scatter behavior is not authorized")
        expected_initial = 10 if scatter_count == 3 else 12 if scatter_count == 4 else 0
        if initial_spins != expected_initial:
            raise EventContractError("simulation Scatter award violates the 3=>10 / 4=>12 Free Spins contract")
        if played > initial_spins or total != base + feature:
            raise EventContractError("simulation feature progress or payout arithmetic is inconsistent")
        if type(payload["round_cap_reached"]) is not bool:
            raise EventContractError("round_cap_reached must be boolean")
        if total > CONFIG.max_round_win_milli:
            raise EventContractError("simulation payout exceeds the configured round cap")
        cap_reached = total == CONFIG.max_round_win_milli
        if payload["round_cap_reached"] != cap_reached:
            raise EventContractError("simulation round-cap flag must match the committed total payout")
        if played < initial_spins and not cap_reached:
            raise EventContractError("simulation cannot end Free Spins before exhaustion without reaching the round cap")
        if initial_spins == 0 and played != 0:
            raise EventContractError("simulation cannot play Free Spins without an authorized BASE award")
        if payload["math_version"] != state["math_version"]:
            raise EventContractError("simulation Math version changed within the round")
        next_state.update({
            "base_board": copy.deepcopy(payload["base_board"]),
            "base_display_board": copy.deepcopy(payload["base_display_board"]),
            "scatter_count": scatter_count,
            "initial_free_spins": initial_spins,
            "free_spins_played": played,
            "base_payout_milli": base,
            "feature_payout_milli": feature,
            "total_payout_milli": total,
            "round_cap_reached": payload["round_cap_reached"],
            "status": "OUTCOME_COMMITTED",
        })
    elif event["event_type"] == "SIMULATION_COMPLETED":
        if state["status"] != "OUTCOME_COMMITTED" or set(payload) != {"terminal_status"} or payload.get("terminal_status") != "COMPLETED":
            raise EventContractError("invalid SIMULATION_COMPLETED transition or payload")
        next_state["status"] = "COMPLETED"
    else:
        raise EventContractError("unknown simulation event type: %s" % event["event_type"])
    next_state["event_count"] = event["sequence"]
    next_state["last_event_hash"] = event["event_hash"]
    return next_state


def replay_simulation_events(round_id, events):
    state = initial_simulation_state(round_id)
    seen = set()
    for event in events:
        if not isinstance(event, dict):
            raise EventContractError("simulation event stream entries must be objects")
        event_id = event.get("event_id")
        if not isinstance(event_id, str) or not event_id or event_id in seen:
            raise EventContractError("duplicate or invalid simulation event_id")
        seen.add(event_id)
        state = apply_simulation_event(state, event)
    return state
