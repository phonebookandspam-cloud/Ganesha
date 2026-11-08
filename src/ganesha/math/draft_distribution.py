"""Exact single-spin payout distributions for explicitly unapproved Draft Math.

This module intentionally excludes feature-transition value. It enumerates the
configured weighted stop model and evaluates only the BASE or FREE_SPINS spin
payout. Scatter awards/retriggers, Buy modes and full-round RTP remain outside
this projection and must not be inferred from its results.
"""
from __future__ import annotations

from fractions import Fraction
from itertools import product
from math import sqrt

from .config import (CONFIG, PAYLINES, PAYOUT_SCALE_DENOMINATOR,
                     PAYOUT_SCALE_NUMERATOR, PAYTABLE_MILLI, REEL_STRIPS,
                     SCATTER, STOP_WEIGHTS, WILD)
from .engine import board_from_stops
from .reference import evaluate_board as reference_evaluate_board


def evaluate_spin_payout(board, mode: str) -> int:
    """Return the capped payout for one Draft spin, independent of Scatter awards."""
    if mode not in ("BASE", "FREE_SPINS"):
        raise ValueError("single-spin projection supports BASE and FREE_SPINS only")
    expanded = [i for i, reel in enumerate(board) if WILD in reel] if mode == "FREE_SPINS" else []
    multiplier = 1
    if expanded:
        multiplier = min(
            CONFIG.feature_rules.free_spin_wild_reel_multiplier ** len(expanded)
            * (2 if len(expanded) == 5 else 1),
            CONFIG.feature_rules.max_wild_reel_multiplier,
        )
    # A sentinel absent from every board suppresses the reference evaluator's
    # feature-award branch while preserving line-payout evaluation exactly.
    result = reference_evaluate_board(
        board, paylines=PAYLINES, paytable_milli=PAYTABLE_MILLI,
        wild_symbol=WILD, scatter_symbol="__NO_SCATTER_AWARD_IN_SPIN_PROJECTION__",
        mode=mode, wild_expansion_reels=expanded, wild_multiplier=multiplier,
        scale_numerator=PAYOUT_SCALE_NUMERATOR,
        scale_denominator=PAYOUT_SCALE_DENOMINATOR,
        payout_cap_milli=CONFIG.max_win_milli,
    )
    return result["payout_milli"]


def _quantile(distribution: dict[int, int], total_mass: int, q: Fraction) -> int:
    threshold = q * total_mass
    cumulative = 0
    for payout, mass in sorted(distribution.items()):
        cumulative += mass
        if cumulative >= threshold:
            return payout
    return max(distribution)


def _upper_tail_mean(distribution: dict[int, int], total_mass: int,
                     tail_fraction: Fraction) -> Fraction:
    remaining = tail_fraction * total_mass
    weighted = Fraction(0, 1)
    for payout, mass in sorted(distribution.items(), reverse=True):
        take = min(Fraction(mass, 1), remaining)
        weighted += payout * take
        remaining -= take
        if remaining == 0:
            break
    if remaining:
        raise ValueError("tail fraction exceeds probability mass")
    return weighted / (tail_fraction * total_mass)


def summarize_weighted_distribution(distribution: dict[int, int], total_mass: int) -> dict:
    """Summarize integer payout/weight masses without floating-point probability loss."""
    if (not distribution or type(total_mass) is not int or total_mass <= 0
            or any(type(p) is not int or p < 0 or type(w) is not int or w < 0
                   for p, w in distribution.items())
            or sum(distribution.values()) != total_mass):
        raise ValueError("distribution must contain non-negative integer payouts and exact positive mass")
    # Zero-mass keys are not part of the probability support. Exclude them
    # before counting outcomes or deriving the maximum reachable payout.
    distribution = {payout: mass for payout, mass in distribution.items() if mass > 0}
    mean = Fraction(sum(p * w for p, w in distribution.items()), total_mass)
    second = Fraction(sum(p * p * w for p, w in distribution.items()), total_mass)
    variance = second - mean * mean
    hit_mass = sum(w for payout, w in distribution.items() if payout > 0)
    loss_mass = total_mass - hit_mass
    maximum = max(distribution)
    maximum_mass = distribution[maximum]
    cap_mass = distribution.get(CONFIG.max_win_milli, 0)
    streaks = {
        "model": "IID weighted-spin Bernoulli projection; not full-round or observed streaks",
        "loss_probability": {"numerator": loss_mass, "denominator": total_mass},
        "win_probability": {"numerator": hit_mass, "denominator": total_mass},
        "loss_run_at_least_n": [
            {"n": n, "numerator": loss_mass ** n, "denominator": total_mass ** n}
            for n in range(1, 11)
        ],
        "win_run_at_least_n": [
            {"n": n, "numerator": hit_mass ** n, "denominator": total_mass ** n}
            for n in range(1, 11)
        ],
    }
    cvar = _upper_tail_mean(distribution, total_mass, Fraction(1, 1000))
    return {
        "total_probability_mass": total_mass,
        "unique_payout_values": len(distribution),
        "single_spin_return_percent_excluding_feature_value": float(mean / 10),
        "mean_payout_milli": {"numerator": mean.numerator, "denominator": mean.denominator},
        "variance_milli_squared": {"numerator": variance.numerator, "denominator": variance.denominator},
        "standard_deviation_milli": sqrt(float(variance)),
        "volatility_coefficient_of_variation": (sqrt(float(variance)) / float(mean)) if mean else None,
        "hit_frequency": {"numerator": hit_mass, "denominator": total_mass},
        "loss_frequency": {"numerator": loss_mass, "denominator": total_mass},
        "quantiles_payout_milli": {
            "p50": _quantile(distribution, total_mass, Fraction(50, 100)),
            "p90": _quantile(distribution, total_mass, Fraction(90, 100)),
            "p95": _quantile(distribution, total_mass, Fraction(95, 100)),
            "p99": _quantile(distribution, total_mass, Fraction(99, 100)),
            "p99_9": _quantile(distribution, total_mass, Fraction(999, 1000)),
            "p99_99": _quantile(distribution, total_mass, Fraction(9999, 10000)),
        },
        "upper_0_1_percent_cvar_payout_milli": {
            "numerator": cvar.numerator,
            "denominator": cvar.denominator,
        },
        "maximum_single_spin_payout_milli": maximum,
        "maximum_single_spin_frequency": {"numerator": maximum_mass, "denominator": total_mass},
        "configured_single_spin_cap_milli": CONFIG.max_win_milli,
        "configured_cap_frequency": {"numerator": cap_mass, "denominator": total_mass},
        "streak_distribution": streaks,
        "payout_distribution": [
            {"payout_milli": payout, "weight_mass": mass}
            for payout, mass in sorted(distribution.items())
        ],
    }


def exact_weighted_spin_distribution(mode: str) -> dict:
    """Enumerate every configured Draft stop vector using exact integer weights."""
    if mode not in ("BASE", "FREE_SPINS"):
        raise ValueError("mode must be BASE or FREE_SPINS")
    distribution: dict[int, int] = {}
    total_vectors = 0
    total_mass = 1
    for weights in STOP_WEIGHTS:
        total_mass *= sum(weights)
    maximum_vectors = 0
    import hashlib
    digest = hashlib.sha256()
    maximum = -1
    scatter_mass: dict[int, int] = {}
    scatter_payout_mass: dict[int, dict[int, int]] = {}
    for stops in product(*(range(len(strip)) for strip in REEL_STRIPS)):
        total_vectors += 1
        weight = 1
        for reel, stop in enumerate(stops):
            weight *= STOP_WEIGHTS[reel][stop]
        board = board_from_stops(stops)
        scatter_count = sum(symbol == SCATTER for reel in board for symbol in reel)
        scatter_mass[scatter_count] = scatter_mass.get(scatter_count, 0) + weight
        payout = evaluate_spin_payout(board, mode)
        distribution[payout] = distribution.get(payout, 0) + weight
        by_payout = scatter_payout_mass.setdefault(scatter_count, {})
        by_payout[payout] = by_payout.get(payout, 0) + weight
        if payout > maximum:
            maximum = payout
            maximum_vectors = 1
            digest = hashlib.sha256()
            digest.update((",".join(map(str, stops)) + "\n").encode("ascii"))
        elif payout == maximum:
            maximum_vectors += 1
            digest.update((",".join(map(str, stops)) + "\n").encode("ascii"))
    summary = summarize_weighted_distribution(distribution, total_mass)
    summary.update({
        "mode": mode,
        "draft_config_version": CONFIG.version,
        "total_stop_vectors_enumerated": total_vectors,
        "stop_weight_sums": [sum(weights) for weights in STOP_WEIGHTS],
        "unweighted_vectors_at_maximum": maximum_vectors,
        "maximum_vector_list_sha256": digest.hexdigest(),
        "scatter_count_weight_mass": [
            {"scatter_count": count, "weight_mass": mass}
            for count, mass in sorted(scatter_mass.items())
        ],
        "scatter_count_payout_weight_mass": [
            {
                "scatter_count": count,
                "payout_distribution": [
                    {"payout_milli": payout, "weight_mass": mass}
                    for payout, mass in sorted(payouts.items())
                ],
            }
            for count, payouts in sorted(scatter_payout_mass.items())
        ],
        "exact_three_scatter_probability": {
            "numerator": scatter_mass.get(3, 0), "denominator": total_mass,
        },
        "scope": "single-spin payout only; excludes Free Spins feature value, retrigger and all Buy modes",
    })
    return summary
