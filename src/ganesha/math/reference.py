"""Independent reference evaluator for cross-checking explicitly supplied Math inputs.

This module deliberately imports no project Math configuration or production engine.
Callers must provide every rule-bearing input. It does not claim that any supplied
model is canonical or Provider-approved.
"""
from copy import deepcopy


class ReferenceMathError(ValueError):
    pass


class UnspecifiedReferenceRule(ReferenceMathError):
    pass


def evaluate_line(symbols, paytable_milli, wild_symbol, scale_numerator=1,
                  scale_denominator=1):
    if not isinstance(symbols, (list, tuple)) or len(symbols) != 5:
        raise ReferenceMathError("line must contain exactly five symbols")
    if any(not isinstance(symbol, str) or not symbol for symbol in symbols):
        raise ReferenceMathError("line symbols must be non-empty strings")
    if not isinstance(paytable_milli, dict) or not paytable_milli:
        raise ReferenceMathError("paytable must be a non-empty mapping")
    if not isinstance(wild_symbol, str) or not wild_symbol:
        raise ReferenceMathError("wild symbol must be explicit")
    if type(scale_numerator) is not int or scale_numerator <= 0:
        raise ReferenceMathError("scale numerator must be a positive integer")
    if type(scale_denominator) is not int or scale_denominator <= 0:
        raise ReferenceMathError("scale denominator must be a positive integer")

    candidates = []
    for target, payouts in paytable_milli.items():
        if not isinstance(target, str) or not target or not isinstance(payouts, dict):
            raise ReferenceMathError("paytable entries must map symbol names to payout maps")
        if (any(type(count) is not int for count in payouts)
                or set(payouts) != {3, 4, 5}):
            raise ReferenceMathError("each paytable entry must define exactly counts 3, 4, and 5")
        if any(type(amount) is not int or amount < 0 for amount in payouts.values()):
            raise ReferenceMathError("paytable payouts must be non-negative integers")
        count = 0
        for symbol in symbols:
            if symbol == target or (symbol == wild_symbol and target != wild_symbol):
                count += 1
            else:
                break
        if count >= 3 and count in payouts:
            amount = payouts[count]
            if type(amount) is not int or amount < 0:
                raise ReferenceMathError("paytable payouts must be non-negative integers")
            scaled = (amount * scale_numerator + scale_denominator // 2) // scale_denominator
            candidates.append((scaled, target, count))
    if not candidates:
        return {"payout_milli": 0, "symbol": "", "count": 0}
    amount, target, count = max(candidates, key=lambda item: (item[0], item[2]))
    return {"payout_milli": amount, "symbol": target, "count": count}


def base_scatter_award(scatter_count, mode):
    if type(scatter_count) is not int or not 0 <= scatter_count <= 15:
        raise ReferenceMathError("Scatter count must be an integer in [0, 15]")
    if mode == "BASE":
        if scatter_count == 5:
            raise UnspecifiedReferenceRule(
                "5 BASE Scatter selects embedded EPICBUY_V37; provider-authoritative feature payload is required"
            )
        if scatter_count >= 6:
            raise UnspecifiedReferenceRule("6+ BASE Scatter behavior is unspecified")
        return 10 if scatter_count == 3 else 12 if scatter_count == 4 else 0
    if mode == "FREE_SPINS":
        if scatter_count >= 3:
            raise UnspecifiedReferenceRule("Free Spins retrigger rules are unspecified")
        return 0
    raise ReferenceMathError("unsupported game mode")


def evaluate_board(board, *, paylines, paytable_milli, wild_symbol,
                   scatter_symbol, mode, wild_expansion_reels=(),
                   wild_multiplier=1, scale_numerator=1,
                   scale_denominator=1, payout_cap_milli=None):
    if not isinstance(board, (list, tuple)) or len(board) != 5:
        raise ReferenceMathError("board must contain exactly five reels")
    raw = [list(reel) for reel in board]
    if any(len(reel) != 3 or any(not isinstance(s, str) or not s for s in reel) for reel in raw):
        raise ReferenceMathError("each board reel must contain three non-empty symbol strings")
    if not isinstance(paylines, (list, tuple)) or not paylines:
        raise ReferenceMathError("paylines must be explicitly supplied")
    for line in paylines:
        if (not isinstance(line, (list, tuple)) or len(line) != 5
                or any(type(row) is not int or row not in (0, 1, 2) for row in line)):
            raise ReferenceMathError("each payline must contain five valid row indices")
    if type(wild_multiplier) is not int or wild_multiplier < 1:
        raise ReferenceMathError("wild multiplier must be a positive integer")
    if payout_cap_milli is not None and (type(payout_cap_milli) is not int or payout_cap_milli < 0):
        raise ReferenceMathError("payout cap must be a non-negative integer")

    expanded = list(wild_expansion_reels)
    if (any(type(index) is not int or not 0 <= index < 5 for index in expanded)
            or len(set(expanded)) != len(expanded)):
        raise ReferenceMathError("expanded Wild reel indices must be unique integers from 0 to 4")
    display = deepcopy(raw)
    for index in expanded:
        if wild_symbol not in raw[index]:
            raise ReferenceMathError("an expanded raw reel must contain the Wild symbol")
        display[index] = [wild_symbol, wild_symbol, wild_symbol]

    if mode == "BASE" and (expanded or display != raw or wild_multiplier != 1):
        raise ReferenceMathError("BASE mode cannot apply feature-only Wild transformations")
    if mode == "FREE_SPINS" and any(
            display[index] != [wild_symbol, wild_symbol, wild_symbol]
            for index in expanded):
        raise ReferenceMathError("expanded display reel is not a full Wild reel")

    wins = []
    raw_payout = 0
    for line_number, rows in enumerate(paylines, start=1):
        symbols = [display[reel_index][rows[reel_index]] for reel_index in range(5)]
        result = evaluate_line(symbols, paytable_milli, wild_symbol,
                               scale_numerator, scale_denominator)
        if result["payout_milli"]:
            wins.append({"line": line_number, **result})
            raw_payout += result["payout_milli"]

    multiplied = raw_payout * wild_multiplier
    payout = multiplied if payout_cap_milli is None else min(multiplied, payout_cap_milli)
    scatters = sum(symbol == scatter_symbol for reel in raw for symbol in reel)
    award = base_scatter_award(scatters, mode)
    return {
        "mode": mode,
        "board": raw,
        "display_board": display,
        "line_wins": wins,
        "raw_payout_milli": raw_payout,
        "expanded_wild_reels": expanded,
        "wild_multiplier": wild_multiplier,
        "scatter_count": scatters,
        "free_spins_awarded": award,
        "payout_milli": payout,
        "max_win_capped": payout_cap_milli is not None and multiplied > payout_cap_milli,
        "jackpot_triggered": False,
    }
