"""Deterministic slot outcome evaluator; no RNG or external state is used here."""
from typing import Dict, List, Sequence, Tuple
from .config import CONFIG, PAYLINES, PAYTABLE_MILLI, PAYOUT_SCALE_DENOMINATOR, PAYOUT_SCALE_NUMERATOR, REEL_STRIPS, SCATTER, STOP_WEIGHTS, SYMBOLS, WILD

StopVector = Tuple[int, int, int, int, int]
Board = Tuple[Tuple[str, str, str], ...]  # reel-major, top/middle/bottom


class UnspecifiedMathRule(RuntimeError):
    """Raised when an outcome depends on a rule without user/Provider authority."""


class EmbeddedEpicFeatureUnavailable(UnspecifiedMathRule):
    """Five-Scatter EPIC trigger is authorized, but its canonical payload is absent."""


def board_from_stops(stops: Sequence[int]) -> Board:
    if len(stops) != 5:
        raise ValueError("Exactly five stop indices are required")
    reels = []
    for reel_index, stop in enumerate(stops):
        strip = REEL_STRIPS[reel_index]
        if type(stop) is not int or stop < 0 or stop >= len(strip):
            raise ValueError("Stop index outside reel strip")
        reels.append(tuple(strip[(stop + row) % len(strip)] for row in range(3)))
    return tuple(reels)


def _line_symbols(board: Board, rows: Sequence[int]) -> Tuple[str, ...]:
    return tuple(board[reel][rows[reel]] for reel in range(5))


def evaluate_line(symbols: Sequence[str]) -> Dict[str, int]:
    """Return the highest-paying left-to-right line result in milli-bet units."""
    if len(symbols) != 5:
        raise ValueError("A payline must contain five symbols")
    candidates = []
    for target, pays in PAYTABLE_MILLI.items():
        count = 0
        for symbol in symbols:
            if symbol == target or (symbol == WILD and target != WILD):
                count += 1
            else:
                break
        if count >= 3:
            scaled_payout = (pays[count] * PAYOUT_SCALE_NUMERATOR + PAYOUT_SCALE_DENOMINATOR // 2) // PAYOUT_SCALE_DENOMINATOR
            candidates.append((scaled_payout, target, count))
    if not candidates:
        return {"payout_milli": 0, "symbol": "", "count": 0}
    payout, target, count = max(candidates, key=lambda item: (item[0], item[2]))
    return {"payout_milli": payout, "symbol": target, "count": count}


def scatter_count(board: Board) -> int:
    return sum(1 for reel in board for symbol in reel if symbol == SCATTER)


def free_spins_awarded(count: int, retrigger: bool = False) -> int:
    if type(retrigger) is not bool:
        raise ValueError("Retrigger flag must be a boolean")
    if type(count) is not int or not 0 <= count <= 15:
        raise ValueError("Scatter count must be an integer in [0, 15]")
    if count < 3:
        return 0
    if retrigger:
        raise UnspecifiedMathRule("Free Spins retrigger rules are not user-authorized")
    if count == 3:
        return 10
    if count == 4:
        return 12
    if count == 5:
        raise EmbeddedEpicFeatureUnavailable(
            "5 Scatter selects the embedded EPICBUY_V37 feature; a provider-authoritative "
            "10-spin payload and BASE-bet payout-unit mapping are required"
        )
    raise UnspecifiedMathRule("6+ Scatter is rejected by the current BASE contract (fail closed)")


def evaluate_board(board: Board, mode: str = "BASE") -> Dict[str, object]:
    if len(board) != 5 or any(len(reel) != 3 for reel in board):
        raise ValueError("Board must be 5 reels × 3 rows")
    if any(type(symbol) is not str or symbol not in SYMBOLS
           for reel in board for symbol in reel):
        raise ValueError("Board contains a symbol outside the configured inventory")
    if mode not in ("BASE", "FREE_SPINS"):
        raise ValueError("Unknown evaluation mode")

    evaluated = [list(reel) for reel in board]
    expanded_reels = []
    if mode == "FREE_SPINS":
        for reel_index, reel in enumerate(evaluated):
            if WILD in reel:
                expanded_reels.append(reel_index)
                evaluated[reel_index] = [WILD, WILD, WILD]

    line_results = []
    raw_payout_milli = 0
    for line_index, rows in enumerate(PAYLINES):
        result = evaluate_line(_line_symbols(evaluated, rows))
        if result["payout_milli"]:
            line_results.append({"line": line_index + 1, **result})
            raw_payout_milli += result["payout_milli"]

    wild_multiplier = min(
        CONFIG.feature_rules.free_spin_wild_reel_multiplier ** len(expanded_reels)
        * (2 if len(expanded_reels) == 5 else 1),
        CONFIG.feature_rules.max_wild_reel_multiplier,
    ) if expanded_reels else 1
    multiplied = raw_payout_milli * wild_multiplier
    # Stake Engine's published approval rules require stateless games and prohibit jackpots.
    # The historical Divine Jackpot draft is deliberately not executed by this evaluator.
    jackpot_triggered = False
    final_payout_milli = min(multiplied, CONFIG.max_win_milli)
    scatters = scatter_count(board)
    return {
        "mode": mode,
        "board": [list(reel) for reel in board],
        "display_board": [list(reel) for reel in evaluated],
        "line_wins": line_results,
        "raw_payout_milli": raw_payout_milli,
        "expanded_wild_reels": expanded_reels,
        "wild_multiplier": wild_multiplier,
        "scatter_count": scatters,
        "free_spins_awarded": free_spins_awarded(scatters, retrigger=(mode == "FREE_SPINS")),
        "payout_milli": final_payout_milli,
        "max_win_capped": multiplied > CONFIG.max_win_milli or jackpot_triggered,
        "jackpot_triggered": jackpot_triggered,
    }
