"""Additive fail-closed settlement guard for GameEngine payout evidence.

The standard guarded startup invokes this validator through GuardedGameEngine,
and GuardedWalletLedger repeats it at the Wallet outcome-commit boundary. The
module remains independent of GameEngine and Wallet so both boundaries can
cross-check the same BASE/FEATURE payout semantics.
"""
from ganesha.math.config import CONFIG, WILD


class EnginePayoutGuardError(ValueError):
    pass


def _expected_multiplier(expanded_reels):
    if type(expanded_reels) is not list:
        raise EnginePayoutGuardError("expanded_wild_reels must be a list")
    if any(type(index) is not int or not 0 <= index <= 4 for index in expanded_reels):
        raise EnginePayoutGuardError("expanded_wild_reels contains an invalid reel index")
    if len(set(expanded_reels)) != len(expanded_reels):
        raise EnginePayoutGuardError("expanded_wild_reels contains duplicate reel indices")
    count = len(expanded_reels)
    return min(
        CONFIG.feature_rules.free_spin_wild_reel_multiplier ** count
        * (2 if count == 5 else 1),
        CONFIG.feature_rules.max_wild_reel_multiplier,
    )


def _validate_expansion_board(result, expanded_reels):
    """Bind every financially credited Wild expansion to an actual raw-board Wild."""
    if not expanded_reels:
        return
    board = result.get("board")
    if (type(board) is not list or len(board) != 5
            or any(type(reel) is not list or len(reel) != 3
                   or any(type(symbol) is not str or not symbol for symbol in reel)
                   for reel in board)):
        raise EnginePayoutGuardError("expanded Wild payout requires a valid raw 5x3 board")
    for index in expanded_reels:
        if WILD not in board[index]:
            raise EnginePayoutGuardError("expanded Wild reel does not contain a raw Ganesha Wild")
    if "display_board" in result:
        display = result["display_board"]
        expected = [[WILD, WILD, WILD] if index in expanded_reels else list(reel)
                    for index, reel in enumerate(board)]
        if display != expected:
            raise EnginePayoutGuardError("expanded Wild display board does not match raw board and reel indices")


def _spin_payout(result, mode, spin_cap_milli):
    if not isinstance(result, dict) or result.get("mode") != mode:
        raise EnginePayoutGuardError("spin result mode is invalid")
    required = ("raw_payout_milli", "payout_milli", "wild_multiplier",
                "expanded_wild_reels", "max_win_capped")
    if any(key not in result for key in required):
        raise EnginePayoutGuardError("spin payout evidence is incomplete")
    raw = result["raw_payout_milli"]
    payout = result["payout_milli"]
    multiplier = result["wild_multiplier"]
    capped = result["max_win_capped"]
    expanded = result["expanded_wild_reels"]
    if type(raw) is not int or raw < 0 or type(payout) is not int or payout < 0:
        raise EnginePayoutGuardError("raw/capped payout must be non-negative exact integers")
    if type(multiplier) is not int or multiplier < 1 or type(capped) is not bool:
        raise EnginePayoutGuardError("Wild multiplier or cap flag has an invalid type")
    expected_multiplier = 1 if mode == "BASE" and type(expanded) is list and not expanded else _expected_multiplier(expanded)
    if mode == "BASE" and (expanded or multiplier != 1):
        raise EnginePayoutGuardError("BASE spin cannot expand Wild or apply a multiplier")
    if mode == "FEATURE" and multiplier != expected_multiplier:
        raise EnginePayoutGuardError("FEATURE multiplier disagrees with expanded Wild reels")
    _validate_expansion_board(result, expanded)
    multiplied = raw * multiplier
    expected_payout = min(multiplied, spin_cap_milli)
    expected_capped = multiplied > spin_cap_milli
    if payout != expected_payout or capped is not expected_capped:
        raise EnginePayoutGuardError("spin payout exceeds or contradicts the per-spin cap")
    return payout


def validate_outcome_for_settlement(outcome, *, spin_cap_milli=None, round_cap_milli=None):
    """Reject outcomes unless every BASE/FEATURE payout and round total reconciles."""
    spin_cap = CONFIG.max_win_milli if spin_cap_milli is None else spin_cap_milli
    round_cap = CONFIG.max_round_win_milli if round_cap_milli is None else round_cap_milli
    if type(spin_cap) is not int or spin_cap <= 0 or type(round_cap) is not int or round_cap <= 0:
        raise EnginePayoutGuardError("spin and round caps must be positive exact integers")
    if not isinstance(outcome, dict) or outcome.get("mode") != "BASE":
        raise EnginePayoutGuardError("only BASE GameEngine outcomes are supported")
    base = outcome.get("base_result")
    base_payout = _spin_payout(base, "BASE", spin_cap)
    initial = outcome.get("initial_free_spins")
    scatter_count = base.get("scatter_count")
    if type(scatter_count) is not int or not 0 <= scatter_count <= 15:
        raise EnginePayoutGuardError("BASE Scatter count must be an exact integer in [0, 15]")
    if scatter_count == 5:
        raise EnginePayoutGuardError("five Scatter requires an embedded EPICBUY_V37 provider payload")
    if scatter_count >= 6:
        raise EnginePayoutGuardError("6+ BASE Scatter behavior is not authorized")
    expected_initial = 10 if scatter_count == 3 else 12 if scatter_count == 4 else 0
    if type(initial) is not int or initial != expected_initial:
        raise EnginePayoutGuardError("BASE feature award must match the 3=>10 / 4=>12 Scatter contract")
    if type(base.get("free_spins_awarded")) is not int or base["free_spins_awarded"] != initial:
        raise EnginePayoutGuardError("BASE result and round feature award disagree")
    if base_payout > round_cap:
        raise EnginePayoutGuardError("BASE payout already exceeds the round cap")
    if (type(outcome.get("free_spins_awarded_total")) is not int
            or outcome["free_spins_awarded_total"] != initial):
        raise EnginePayoutGuardError("cumulative Free Spins award is inconsistent")
    events = outcome.get("feature_events")
    played = outcome.get("free_spins_played")
    if not isinstance(events, list) or type(played) is not int or played != len(events):
        raise EnginePayoutGuardError("FEATURE event count is inconsistent")
    if initial == 0 and events:
        raise EnginePayoutGuardError("FEATURE events exist without an authorized award")
    if len(events) > initial:
        raise EnginePayoutGuardError("FEATURE events exceed the initial award")

    total = base_payout
    feature_awarded = 0
    for index, item in enumerate(events, start=1):
        if not isinstance(item, dict) or type(item.get("spin_number")) is not int or item["spin_number"] != index:
            raise EnginePayoutGuardError("FEATURE spin sequence is not contiguous")
        if (type(item.get("retrigger_requested")) is not int or item["retrigger_requested"] != 0
                or type(item.get("retrigger_awarded")) is not int or item["retrigger_awarded"] != 0):
            raise EnginePayoutGuardError("FEATURE retrigger is unsupported")
        result = item.get("result")
        payout = _spin_payout(result, "FREE_SPINS", spin_cap)
        if item.get("jackpot_triggered") is not False or result.get("jackpot_triggered") is not False:
            raise EnginePayoutGuardError("Jackpot outcome is unsupported")
        expected_total = min(round_cap, total + payout)
        expected_award = expected_total - total
        expected_round_cap_applied = total + payout > round_cap
        if (type(item.get("payout_awarded_milli")) is not int
                or item["payout_awarded_milli"] != expected_award
                or type(item.get("round_payout_after_milli")) is not int
                or item["round_payout_after_milli"] != expected_total
                or type(item.get("round_cap_applied")) is not bool
                or item["round_cap_applied"] is not expected_round_cap_applied):
            raise EnginePayoutGuardError("FEATURE payout award or round-cap evidence does not reconcile")
        total = expected_total
        feature_awarded += expected_award
        if total == round_cap and index != len(events):
            raise EnginePayoutGuardError("FEATURE continues after the round cap is reached")

    if initial and total < round_cap and len(events) != initial:
        raise EnginePayoutGuardError("FEATURE ended before all awarded spins resolved")
    if (type(outcome.get("total_payout_milli")) is not int
            or outcome["total_payout_milli"] != total
            or type(outcome.get("round_cap_reached")) is not bool
            or outcome["round_cap_reached"] is not (total == round_cap)):
        raise EnginePayoutGuardError("final round payout or cap flag does not reconcile")
    return {
        "base_payout_milli": base_payout,
        "feature_payout_milli": feature_awarded,
        "total_payout_milli": total,
        "round_cap_reached": total == round_cap,
        "spins_checked": 1 + len(events),
    }
