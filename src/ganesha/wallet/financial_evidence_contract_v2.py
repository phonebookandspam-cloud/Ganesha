"""Versioned v2 financial-evidence contract used by GuardedWalletLedger/RGS.

The additive v2 sidecar is linked to immutable v1 Wallet events. Existing v1
event creation, replay, ledger rows and public API remain untouched. A caller
must pin the round's schema version before using v2.
"""
import hashlib
import json
import re

from ganesha.math.config import CONFIG, WILD

SCHEMA_VERSION = 2
ZERO_HASH = "0" * 64
HEX64 = re.compile(r"^[0-9a-f]{64}$")
EVIDENCE_FIELDS = (
    "raw_payout_milli", "wild_multiplier", "expanded_wild_reels", "max_win_capped"
)
BASE_EVENT = "OUTCOME_COMMITTED"
FEATURE_EVENT = "FEATURE_SPIN_RESOLVED"


class FinancialEvidenceContractError(ValueError):
    pass


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def expected_wild_multiplier(expanded_reels):
    if type(expanded_reels) is not list:
        raise FinancialEvidenceContractError("expanded_wild_reels must be a list")
    count = len(expanded_reels)
    return min(
        CONFIG.feature_rules.free_spin_wild_reel_multiplier ** count
        * (2 if count == 5 else 1),
        CONFIG.feature_rules.max_wild_reel_multiplier,
    )


def validate_spin_evidence(mode, payload, spin_cap_milli=None):
    """Validate the four Math-origin fields and capped per-spin payout arithmetic."""
    cap = CONFIG.max_win_milli if spin_cap_milli is None else spin_cap_milli
    if type(cap) is not int or cap <= 0:
        raise FinancialEvidenceContractError("spin_cap_milli must be a positive exact integer")
    if mode not in ("BASE", "FEATURE") or not isinstance(payload, dict):
        raise FinancialEvidenceContractError("unsupported spin evidence mode or payload")
    required = set(EVIDENCE_FIELDS) | {"payout_milli"}
    if not required.issubset(payload):
        raise FinancialEvidenceContractError("spin evidence is incomplete")
    raw = payload["raw_payout_milli"]
    payout = payload["payout_milli"]
    multiplier = payload["wild_multiplier"]
    expanded = payload["expanded_wild_reels"]
    capped = payload["max_win_capped"]
    if any(type(value) is not int or value < 0 for value in (raw, payout)):
        raise FinancialEvidenceContractError("raw and capped payout must be non-negative exact integers")
    if type(multiplier) is not int or multiplier < 1:
        raise FinancialEvidenceContractError("wild_multiplier must be a positive exact integer")
    if type(expanded) is not list or any(type(index) is not int or not 0 <= index <= 4 for index in expanded):
        raise FinancialEvidenceContractError("expanded_wild_reels must contain valid reel indices")
    if len(set(expanded)) != len(expanded):
        raise FinancialEvidenceContractError("expanded_wild_reels cannot contain duplicates")
    if expanded:
        board = payload.get("board")
        if (type(board) is not list or len(board) != 5
                or any(type(reel) is not list or len(reel) != 3
                       or any(type(symbol) is not str or not symbol for symbol in reel)
                       for reel in board)):
            raise FinancialEvidenceContractError("expanded Wild evidence requires a valid raw 5x3 board")
        if any(WILD not in board[index] for index in expanded):
            raise FinancialEvidenceContractError("expanded Wild reel has no matching raw Ganesha Wild")
        if "display_board" in payload:
            expected_display = [[WILD, WILD, WILD] if index in expanded else list(reel)
                                for index, reel in enumerate(board)]
            if payload["display_board"] != expected_display:
                raise FinancialEvidenceContractError("Wild display board does not match raw board and expansion indices")
    if type(capped) is not bool:
        raise FinancialEvidenceContractError("max_win_capped must be an exact boolean")
    if mode == "BASE":
        if expanded or multiplier != 1:
            raise FinancialEvidenceContractError("BASE spin cannot contain Wild expansion or multiplier")
    elif multiplier != expected_wild_multiplier(expanded):
        raise FinancialEvidenceContractError("FEATURE Wild multiplier disagrees with expanded reels")
    multiplied = raw * multiplier
    if payout != min(multiplied, cap) or capped is not (multiplied > cap):
        raise FinancialEvidenceContractError("spin payout/cap evidence does not reconcile")
    return {key: payload[key] for key in EVIDENCE_FIELDS} | {"payout_milli": payout}


def _required_source_hash(payload):
    value = payload.get("source_ledger_event_hash")
    if not isinstance(value, str) or not HEX64.fullmatch(value):
        raise FinancialEvidenceContractError("source_ledger_event_hash must be lowercase SHA-256")
    return value


def _validate_event_payload(event_type, payload):
    if not isinstance(payload, dict):
        raise FinancialEvidenceContractError("event payload must be an object")
    if event_type == BASE_EVENT:
        validate_spin_evidence("BASE", payload)
        _required_source_hash(payload)
        for field in ("outcome_sha256", "engine_version"):
            value = payload.get(field)
            if not isinstance(value, str) or not value or len(value) > 256:
                raise FinancialEvidenceContractError("OUTCOME_COMMITTED %s is invalid" % field)
        if not HEX64.fullmatch(payload["outcome_sha256"]):
            raise FinancialEvidenceContractError("outcome_sha256 must be lowercase SHA-256")
        integer_fields = ("base_payout_milli", "feature_payout_milli", "total_payout_milli",
                          "payout_minor", "round_cap_milli")
        if any(type(payload.get(field)) is not int or payload[field] < 0 for field in integer_fields):
            raise FinancialEvidenceContractError("OUTCOME_COMMITTED payout fields must be non-negative exact integers")
        if payload["round_cap_milli"] <= 0 or payload["total_payout_milli"] > payload["round_cap_milli"]:
            raise FinancialEvidenceContractError("OUTCOME_COMMITTED exceeds its declared round cap")
        if (payload["base_payout_milli"] != payload["payout_milli"]
                or payload["total_payout_milli"] != payload["base_payout_milli"] + payload["feature_payout_milli"]):
            raise FinancialEvidenceContractError("OUTCOME_COMMITTED base/feature/total payout does not reconcile")
        if type(payload.get("round_cap_reached")) is not bool or payload["round_cap_reached"] is not (payload["total_payout_milli"] == payload["round_cap_milli"]):
            raise FinancialEvidenceContractError("OUTCOME_COMMITTED round-cap flag does not reconcile")
    elif event_type == FEATURE_EVENT:
        validate_spin_evidence("FEATURE", payload)
        _required_source_hash(payload)
        required = ("payout_awarded_milli", "spin_number", "remaining_spins",
                    "round_payout_after_milli", "round_cap_applied")
        if any(field not in payload for field in required):
            raise FinancialEvidenceContractError("FEATURE event is missing lifecycle/cap evidence")
        for field in ("payout_awarded_milli", "spin_number", "remaining_spins", "round_payout_after_milli"):
            if type(payload[field]) is not int or payload[field] < 0:
                raise FinancialEvidenceContractError("FEATURE %s must be a non-negative exact integer" % field)
        if payload["spin_number"] < 1 or payload["payout_awarded_milli"] > payload["payout_milli"]:
            raise FinancialEvidenceContractError("FEATURE payout or spin number is invalid")
        if type(payload["round_cap_applied"]) is not bool:
            raise FinancialEvidenceContractError("FEATURE round_cap_applied must be boolean")
    else:
        raise FinancialEvidenceContractError("unsupported v2 evidence event type")


def make_v2_event(round_id, sequence, event_id, event_type, payload, previous_hash=ZERO_HASH):
    if not isinstance(round_id, str) or not round_id or len(round_id) > 128:
        raise FinancialEvidenceContractError("round_id is invalid")
    if type(sequence) is not int or sequence < 1:
        raise FinancialEvidenceContractError("sequence must be a positive exact integer")
    if not isinstance(event_id, str) or not event_id or len(event_id) > 256:
        raise FinancialEvidenceContractError("event_id is invalid")
    if not isinstance(previous_hash, str) or not HEX64.fullmatch(previous_hash):
        raise FinancialEvidenceContractError("previous_hash must be lowercase SHA-256")
    if not isinstance(payload, dict):
        raise FinancialEvidenceContractError("payload must be an object")
    _validate_event_payload(event_type, payload)
    event = {
        "schema_version": SCHEMA_VERSION,
        "round_id": round_id,
        "sequence": sequence,
        "event_id": event_id,
        "event_type": event_type,
        "payload": payload,
        "previous_hash": previous_hash,
    }
    event["event_hash"] = hashlib.sha256(_canonical(event).encode("ascii")).hexdigest()
    return event


def verify_v2_event(event, expected_previous_hash=ZERO_HASH, expected_sequence=1):
    if not isinstance(event, dict) or set(event) != {
        "schema_version", "round_id", "sequence", "event_id", "event_type",
        "payload", "previous_hash", "event_hash",
    }:
        raise FinancialEvidenceContractError("event envelope is invalid")
    if event["schema_version"] != SCHEMA_VERSION:
        raise FinancialEvidenceContractError("v1 history is not replayed by the v2 verifier")
    if (not isinstance(event["round_id"], str) or not event["round_id"] or len(event["round_id"]) > 128
            or not isinstance(event["event_id"], str) or not event["event_id"] or len(event["event_id"]) > 256
            or type(event["sequence"]) is not int or type(expected_sequence) is not int
            or not isinstance(event["event_type"], str)):
        raise FinancialEvidenceContractError("event identity fields are invalid")
    if (not isinstance(event["previous_hash"], str) or not HEX64.fullmatch(event["previous_hash"])
            or not isinstance(expected_previous_hash, str) or not HEX64.fullmatch(expected_previous_hash)
            or event["previous_hash"] != expected_previous_hash or event["sequence"] != expected_sequence):
        raise FinancialEvidenceContractError("event sequence or predecessor does not match")
    unhashed = {key: value for key, value in event.items() if key != "event_hash"}
    expected_hash = hashlib.sha256(_canonical(unhashed).encode("ascii")).hexdigest()
    if event["event_hash"] != expected_hash:
        raise FinancialEvidenceContractError("event hash mismatch")
    _validate_event_payload(event["event_type"], event["payload"])
    return True


_PUBLIC_FIELDS = {
    BASE_EVENT: frozenset({"spin_number", "board", "display_board", *EVIDENCE_FIELDS, "payout_milli",
                           "base_payout_milli", "feature_payout_milli", "total_payout_milli",
                           "round_cap_milli", "round_cap_reached", "payout_minor"}),
    FEATURE_EVENT: frozenset({"spin_number", "stops", "board", "display_board", *EVIDENCE_FIELDS,
                              "payout_milli", "payout_awarded_milli", "remaining_spins",
                              "round_payout_after_milli", "round_cap_applied"}),
}


def project_public_v2(event, previous_public_hash=ZERO_HASH,
                      expected_source_previous_hash=ZERO_HASH, expected_sequence=1):
    """Create a filtered public event cryptographically linked to its source event."""
    verify_v2_event(event, expected_source_previous_hash, expected_sequence)
    if not isinstance(previous_public_hash, str) or not HEX64.fullmatch(previous_public_hash):
        raise FinancialEvidenceContractError("previous_public_hash must be lowercase SHA-256")
    allowed = _PUBLIC_FIELDS[event["event_type"]]
    source_event_hash = _required_source_hash(event["payload"])
    projected = {
        "schema_version": SCHEMA_VERSION,
        "round_id": event["round_id"],
        "sequence": event["sequence"],
        "event_id": event["event_id"],
        "event_type": event["event_type"],
        "payload": {key: event["payload"][key] for key in allowed if key in event["payload"]},
        "source_event_hash": source_event_hash,
        "previous_hash": previous_public_hash,
    }
    projected["event_hash"] = hashlib.sha256(_canonical(projected).encode("ascii")).hexdigest()
    return projected


def verify_public_v2_event(event, expected_previous_hash=ZERO_HASH, expected_sequence=1):
    """Verify a filtered public projection and its link to the source event hash."""
    required = {"schema_version", "round_id", "sequence", "event_id", "event_type",
                "payload", "source_event_hash", "previous_hash", "event_hash"}
    if not isinstance(event, dict) or set(event) != required:
        raise FinancialEvidenceContractError("public v2 event envelope is invalid")
    if (event["schema_version"] != SCHEMA_VERSION or type(event["sequence"]) is not int
            or event["sequence"] != expected_sequence
            or not isinstance(event["round_id"], str) or not event["round_id"]
            or not isinstance(event["event_id"], str) or not event["event_id"]
            or event["event_type"] not in _PUBLIC_FIELDS
            or not isinstance(event["payload"], dict)
            or set(event["payload"]) - _PUBLIC_FIELDS[event["event_type"]]
            or not isinstance(event["previous_hash"], str) or not HEX64.fullmatch(event["previous_hash"])
            or event["previous_hash"] != expected_previous_hash
            or not isinstance(event["source_event_hash"], str) or not HEX64.fullmatch(event["source_event_hash"])):
        raise FinancialEvidenceContractError("public event version, schema, sequence or source linkage is invalid")
    payload = event["payload"]
    required_evidence = set(EVIDENCE_FIELDS) | {"payout_milli"}
    if not required_evidence.issubset(payload):
        raise FinancialEvidenceContractError("public event is missing payout evidence")
    mode = "BASE" if event["event_type"] == BASE_EVENT else "FEATURE"
    validate_spin_evidence(mode, payload)
    if mode == "BASE":
        required = {"spin_number", "base_payout_milli", "feature_payout_milli",
                    "total_payout_milli", "payout_minor", "round_cap_milli", "round_cap_reached"}
        if not required.issubset(payload):
            raise FinancialEvidenceContractError("public BASE event is missing round settlement fields")
        integer_fields = ("spin_number", "base_payout_milli", "feature_payout_milli",
                          "total_payout_milli", "payout_minor", "round_cap_milli")
        if any(type(payload[field]) is not int or payload[field] < 0 for field in integer_fields):
            raise FinancialEvidenceContractError("public BASE settlement fields must be non-negative exact integers")
        if (payload["spin_number"] != 0 or payload["round_cap_milli"] <= 0
                or payload["base_payout_milli"] != payload["payout_milli"]
                or payload["total_payout_milli"] != payload["base_payout_milli"] + payload["feature_payout_milli"]
                or payload["total_payout_milli"] > payload["round_cap_milli"]
                or type(payload["round_cap_reached"]) is not bool
                or payload["round_cap_reached"] is not (payload["total_payout_milli"] == payload["round_cap_milli"])):
            raise FinancialEvidenceContractError("public BASE settlement totals or cap evidence do not reconcile")
    else:
        required = {"spin_number", "payout_awarded_milli", "remaining_spins",
                    "round_payout_after_milli", "round_cap_applied"}
        if not required.issubset(payload):
            raise FinancialEvidenceContractError("public FEATURE event is missing lifecycle/cap fields")
        for field in ("spin_number", "payout_awarded_milli", "remaining_spins", "round_payout_after_milli"):
            if type(payload[field]) is not int or payload[field] < 0:
                raise FinancialEvidenceContractError("public FEATURE %s must be a non-negative exact integer" % field)
        if (payload["spin_number"] < 1 or payload["payout_awarded_milli"] > payload["payout_milli"]
                or type(payload["round_cap_applied"]) is not bool):
            raise FinancialEvidenceContractError("public FEATURE payout/lifecycle evidence is invalid")
    unhashed = {key: value for key, value in event.items() if key != "event_hash"}
    expected_hash = hashlib.sha256(_canonical(unhashed).encode("ascii")).hexdigest()
    if event["event_hash"] != expected_hash:
        raise FinancialEvidenceContractError("public event hash mismatch")
    return True


def verify_public_v2_chain(events):
    """Verify public hash order and BASE/FEATURE cumulative payout reconciliation."""
    if type(events) is not list or not events:
        raise FinancialEvidenceContractError("public evidence chain must be a non-empty event list")
    round_id = events[0].get("round_id") if isinstance(events[0], dict) else None
    if not isinstance(round_id, str) or not round_id:
        raise FinancialEvidenceContractError("public evidence chain round identity is invalid")
    if events[0].get("event_type") != BASE_EVENT:
        raise FinancialEvidenceContractError("public evidence chain must begin with BASE outcome")
    previous_hash = ZERO_HASH
    previous_total = 0
    previous_remaining = None
    round_cap = None
    feature_awarded = 0
    for index, event in enumerate(events, start=1):
        if not isinstance(event, dict) or event.get("round_id") != round_id:
            raise FinancialEvidenceContractError("public evidence chain contains a cross-round event")
        verify_public_v2_event(event, expected_previous_hash=previous_hash, expected_sequence=index)
        payload = event["payload"]
        if index == 1:
            previous_total = payload["payout_milli"]
            round_cap = payload["round_cap_milli"]
        else:
            if event["event_type"] != FEATURE_EVENT or payload["spin_number"] != index - 1:
                raise FinancialEvidenceContractError("public FEATURE sequence is not contiguous")
            if previous_remaining is not None and payload["remaining_spins"] != previous_remaining - 1:
                raise FinancialEvidenceContractError("public FEATURE remaining-spin sequence is inconsistent")
            requested_total = previous_total + payload["payout_milli"]
            expected_total = min(round_cap, requested_total)
            expected_award = expected_total - previous_total
            if (payload["round_payout_after_milli"] != expected_total
                    or payload["payout_awarded_milli"] != expected_award
                    or payload["round_cap_applied"] is not (requested_total > round_cap)):
                raise FinancialEvidenceContractError("public FEATURE cumulative payout or round-cap evidence does not reconcile")
            previous_total = expected_total
            feature_awarded += expected_award
        previous_remaining = payload.get("remaining_spins", previous_remaining)
        previous_hash = event["event_hash"]
    base = events[0]["payload"]
    if (base["feature_payout_milli"] != feature_awarded
            or base["total_payout_milli"] != previous_total
            or base["round_cap_reached"] is not (previous_total == round_cap)):
        raise FinancialEvidenceContractError("public BASE totals do not reconcile to the FEATURE chain")
    return True
