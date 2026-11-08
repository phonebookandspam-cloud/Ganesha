"""Exact weighted enumeration of the finite BASE and one-spin FREE_SPINS spaces."""
from collections import Counter
from fractions import Fraction
from itertools import product
from typing import Dict
from .config import CONFIG, REEL_STRIPS, STOP_WEIGHTS, validate_config
from .engine import board_from_stops, evaluate_board, free_spins_awarded


def exact_mode_audit(mode="BASE") -> Dict[str, object]:
    validate_config()
    if mode not in ("BASE", "FREE_SPINS"):
        raise ValueError("Only BASE and FREE_SPINS single-spin distributions are enumerated here")
    total_weight = 1
    for weights in STOP_WEIGHTS:
        total_weight *= sum(weights)
    total_payout_weighted = 0
    hit_weighted = 0
    trigger_weights = Counter()
    payout_weighted_sum_by_award = Counter()
    payout_square_weighted_sum_by_award = Counter()
    zero_weight_by_award = Counter()
    payout_buckets = Counter()
    max_seen = 0
    max_vectors = []
    for stops in product(*(range(len(reel)) for reel in REEL_STRIPS)):
        outcome_weight = 1
        for reel_index, stop in enumerate(stops):
            outcome_weight *= STOP_WEIGHTS[reel_index][stop]
        result = evaluate_board(board_from_stops(stops), mode)
        payout = int(result["payout_milli"])
        total_payout_weighted += payout * outcome_weight
        if payout > 0:
            hit_weighted += outcome_weight
        scatters = int(result["scatter_count"])
        award = free_spins_awarded(scatters, retrigger=(mode == "FREE_SPINS"))
        trigger_weights[award] += outcome_weight
        payout_weighted_sum_by_award[award] += payout * outcome_weight
        payout_square_weighted_sum_by_award[award] += payout * payout * outcome_weight
        if payout == 0:
            zero_weight_by_award[award] += outcome_weight
        payout_buckets["zero" if payout == 0 else "low_0_5x" if payout <= 5000 else "mid_5_50x" if payout <= 50000 else "high_50x_plus"] += outcome_weight
        if payout > max_seen:
            max_seen = payout
            max_vectors = [tuple(stops)]
        elif payout == max_seen and len(max_vectors) < 20:
            max_vectors.append(tuple(stops))
    mean_payout_x = Fraction(total_payout_weighted, total_weight * 1000)
    rtp_percent = mean_payout_x * 100
    return {
        "config_version": CONFIG.version,
        "mode": mode,
        "outcome_count": 13 ** 5,
        "total_weight": total_weight,
        "direct_single_spin_rtp_percent": str(float(rtp_percent)),
        "direct_single_spin_rtp_fraction_percent": str(rtp_percent),
        "hit_frequency": str(Fraction(hit_weighted, total_weight)),
        "hit_frequency_percent": float(Fraction(hit_weighted * 100, total_weight)),
        "weighted_hit_count": hit_weighted,
        "scatter_award_weight_by_free_spins": {str(k): v for k, v in sorted(trigger_weights.items())},
        "payout_weighted_sum_by_free_spins": {str(k): v for k, v in sorted(payout_weighted_sum_by_award.items())},
        "payout_square_weighted_sum_by_free_spins": {str(k): v for k, v in sorted(payout_square_weighted_sum_by_award.items())},
        "zero_payout_weight_by_free_spins": {str(k): v for k, v in sorted(zero_weight_by_award.items())},
        "payout_bucket_weights": dict(payout_buckets),
        "max_observed_single_spin_payout_x": str(Fraction(max_seen, 1000)),
        "max_stop_vectors_sample": max_vectors,
        "single_spin_cap_x": str(Fraction(CONFIG.max_win_milli, 1000)),
        "feature_value_included": False,
        "rtp_status": "SINGLE-SPIN COMPONENT ONLY — multi-spin Free Spins EV and round-level cap are separate calculations",
    }


def exact_base_audit() -> Dict[str, object]:
    return exact_mode_audit("BASE")


def exact_free_spin_audit() -> Dict[str, object]:
    return exact_mode_audit("FREE_SPINS")
