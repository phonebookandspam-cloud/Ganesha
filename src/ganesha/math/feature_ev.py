"""Quarantined Free Spins EV boundary plus retained pure DP utilities.

The pure helper functions are retained for regression tests and unrelated
finite-state calculations. They are not called by the active game audit.
Full feature EV is blocked until canonical scatter/retrigger/termination rules
and probability inputs are supplied.
"""
from fractions import Fraction
import math
from .config import CONFIG
from .engine import UnspecifiedMathRule


def _moments_for_cap(max_spins, grouped, total_weight):
    """Pure backward-DP helper over supplied grouped outcomes; not game policy."""
    expected = {}
    second = {}
    zero_probability = {}
    jackpot_x = Fraction(CONFIG.max_round_win_milli, 1000)
    jackpot_milli = CONFIG.max_round_win_milli
    for played in range(max_spins, -1, -1):
        for awarded_total in range(max_spins, played - 1, -1):
            remaining = awarded_total - played
            if remaining == 0:
                expected[(played, awarded_total)] = Fraction(0, 1)
                second[(played, awarded_total)] = Fraction(0, 1)
                zero_probability[(played, awarded_total)] = Fraction(1, 1)
                continue
            mean_value = Fraction(0, 1)
            second_value = Fraction(0, 1)
            zero_value = Fraction(0, 1)
            next_played = played + 1
            for award, (weight, payout_weight, payout_square_weight, zero_weight, jackpot_weight) in grouped.items():
                non_jackpot_weight = weight - jackpot_weight
                if jackpot_weight:
                    jackpot_p = Fraction(jackpot_weight, total_weight)
                    mean_value += jackpot_p * jackpot_x
                    second_value += jackpot_p * jackpot_x * jackpot_x
                if non_jackpot_weight:
                    extra = min(award, max_spins - awarded_total)
                    next_awarded = awarded_total + extra
                    next_remaining = next_awarded - next_played
                    if next_remaining > 0:
                        future_mean = expected[(next_played, next_awarded)]
                        future_second = second[(next_played, next_awarded)]
                        future_zero = zero_probability[(next_played, next_awarded)]
                    else:
                        future_mean = Fraction(0, 1)
                        future_second = Fraction(0, 1)
                        future_zero = Fraction(1, 1)
                    non_p = Fraction(non_jackpot_weight, total_weight)
                    non_payout_sum = payout_weight - jackpot_weight * jackpot_milli
                    non_payout_square_sum = payout_square_weight - jackpot_weight * jackpot_milli * jackpot_milli
                    payout_mean = Fraction(non_payout_sum, non_jackpot_weight * 1000)
                    payout_second = Fraction(non_payout_square_sum, non_jackpot_weight * 1_000_000)
                    mean_value += non_p * (payout_mean + future_mean)
                    second_value += non_p * (payout_second + 2 * payout_mean * future_mean + future_second)
                    zero_value += Fraction(zero_weight, total_weight) * future_zero
            expected[(played, awarded_total)] = mean_value
            second[(played, awarded_total)] = second_value
            zero_probability[(played, awarded_total)] = zero_value
    variance = {state: second[state] - expected[state] * expected[state] for state in expected}
    return expected, second, variance, zero_probability


def _jackpot_probability(initial_spins, max_spins, grouped, total_weight):
    """Pure probability DP over supplied states; not an enabled game jackpot."""
    from functools import lru_cache

    @lru_cache(maxsize=None)
    def visit(played, awarded_total):
        remaining = awarded_total - played
        if remaining <= 0:
            return Fraction(0, 1)
        probability = Fraction(0, 1)
        next_played = played + 1
        for award, values in grouped.items():
            weight, _, _, _, jackpot_weight = values
            probability += Fraction(jackpot_weight, total_weight)
            non_jackpot_weight = weight - jackpot_weight
            if non_jackpot_weight:
                extra = min(award, max_spins - awarded_total)
                next_awarded = awarded_total + extra
                next_remaining = next_awarded - next_played
                if next_remaining > 0:
                    probability += Fraction(non_jackpot_weight, total_weight) * visit(next_played, next_awarded)
        return probability

    return visit(0, initial_spins)


def free_spin_transition_distribution():
    raise UnspecifiedMathRule(
        "Free Spins transition distribution is blocked: retrigger, 4+ Scatter, "
        "termination and complete canonical probability inputs are unspecified"
    )


def exact_free_spins_expected_value(max_spins=None):
    if max_spins is not None and (type(max_spins) is not int or max_spins <= 0):
        raise ValueError("max_spins must be a positive integer when supplied")
    raise UnspecifiedMathRule(
        "Free Spins EV/variance cannot be computed without approved retrigger, "
        "termination and probability rules; no 49/50-spin or jackpot assumption is permitted"
    )
