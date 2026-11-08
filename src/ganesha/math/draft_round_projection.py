"""Exact conditional BASE + exact-3/10-Free-Spins Draft projection.

This is deliberately not a Canonical Math or unconditional game-RTP model.
BASE 4+ Scatter outcomes and Free Spins 3+ Scatter outcomes are excluded because
their award/retrigger rules are not authorized. All probabilities are exact
integer stop-weight masses; no Monte Carlo sampling is used.
"""
from __future__ import annotations

from fractions import Fraction
from math import sqrt
from bisect import bisect_right
from collections import Counter
import random

from .config import CONFIG, STOP_WEIGHTS
from .draft_distribution import exact_weighted_spin_distribution


def _fraction(value: Fraction) -> dict[str, int]:
    return {"numerator": value.numerator, "denominator": value.denominator}


def _convolve(left: dict[int, int], right: dict[int, int]) -> dict[int, int]:
    result: dict[int, int] = {}
    for left_value, left_mass in left.items():
        for right_value, right_mass in right.items():
            value = left_value + right_value
            result[value] = result.get(value, 0) + left_mass * right_mass
    return result


def _quantile(distribution: dict[int, int], total_mass: int, q: Fraction) -> int:
    threshold = q * total_mass
    cumulative = 0
    for payout, mass in sorted(distribution.items()):
        cumulative += mass
        if cumulative >= threshold:
            return payout
    return max(distribution)


def _cvar(distribution: dict[int, int], total_mass: int,
          tail_fraction: Fraction = Fraction(1, 1000)) -> Fraction:
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


def _distribution_summary(distribution: dict[int, int], total_mass: int,
                          *, wager_spins: int, scope: str) -> dict:
    if not distribution or sum(distribution.values()) != total_mass:
        raise ValueError("payout distribution does not conserve exact probability mass")
    if any(type(x) is not int or x < 0 or type(m) is not int or m < 0
           for x, m in distribution.items()):
        raise ValueError("payout distribution must use non-negative integer values and masses")
    mean = Fraction(sum(x * m for x, m in distribution.items()), total_mass)
    second = Fraction(sum(x * x * m for x, m in distribution.items()), total_mass)
    variance = second - mean * mean
    sd = sqrt(float(variance))
    hit_mass = sum(m for x, m in distribution.items() if x > 0)
    max_payout = max(distribution)
    buckets = {
        "zero": sum(m for x, m in distribution.items() if x == 0),
        "0_to_1x_inclusive": sum(m for x, m in distribution.items() if 0 < x <= 1000),
        "1_to_5x": sum(m for x, m in distribution.items() if 1000 < x <= 5000),
        "5_to_20x": sum(m for x, m in distribution.items() if 5000 < x <= 20000),
        "20_to_100x": sum(m for x, m in distribution.items() if 20000 < x <= 100000),
        "100x_plus": sum(m for x, m in distribution.items() if x > 100000),
    }
    tail = _cvar(distribution, total_mass)
    return {
        "scope": scope,
        "wager_spins": wager_spins,
        "total_probability_mass": total_mass,
        "unique_payout_values": len(distribution),
        "mean_payout_milli": _fraction(mean),
        "mean_payout_x_of_base_wager": float(mean / 1000),
        "return_percent_of_one_base_wager": float(mean / 10),
        "variance_milli_squared": _fraction(variance),
        "standard_deviation_milli": sd,
        "standard_deviation_x_of_base_wager": sd / 1000,
        "coefficient_of_variation": sd / float(mean) if mean else None,
        "hit_frequency": _fraction(Fraction(hit_mass, total_mass)),
        "loss_frequency": _fraction(Fraction(total_mass - hit_mass, total_mass)),
        "quantiles_payout_milli": {
            "p50": _quantile(distribution, total_mass, Fraction(50, 100)),
            "p90": _quantile(distribution, total_mass, Fraction(90, 100)),
            "p95": _quantile(distribution, total_mass, Fraction(95, 100)),
            "p99": _quantile(distribution, total_mass, Fraction(99, 100)),
            "p99_9": _quantile(distribution, total_mass, Fraction(999, 1000)),
            "p99_99": _quantile(distribution, total_mass, Fraction(9999, 10000)),
        },
        "upper_0_1_percent_cvar_payout_milli": _fraction(tail),
        "maximum_payout_milli": max_payout,
        "maximum_payout_x_of_base_wager": max_payout / 1000,
        "maximum_payout_frequency": _fraction(Fraction(distribution[max_payout], total_mass)),
        "payout_buckets_weight_mass": buckets,
        "payout_buckets_probability": {
            key: _fraction(Fraction(value, total_mass)) for key, value in buckets.items()
        },
        "payout_distribution": [
            {"payout_milli": x, "weight_mass": mass}
            for x, mass in sorted(distribution.items())
        ],
    }


def _joint_by_scatter(summary: dict) -> dict[int, dict[int, int]]:
    return {
        item["scatter_count"]: {
            row["payout_milli"]: row["weight_mass"]
            for row in item["payout_distribution"]
        }
        for item in summary["scatter_count_payout_weight_mass"]
    }


def _aggregate_scatter_domain(joint: dict[int, dict[int, int]], counts) -> dict[int, int]:
    """Aggregate payout masses across Scatter classes without overwriting shared payouts."""
    result: dict[int, int] = {}
    for scatter_count in counts:
        for payout, mass in joint.get(scatter_count, {}).items():
            result[payout] = result.get(payout, 0) + mass
    return result


def _moments(distribution: dict[int, int], total_mass: int) -> tuple[Fraction, Fraction, Fraction]:
    mean = Fraction(sum(x * m for x, m in distribution.items()), total_mass)
    second = Fraction(sum(x * x * m for x, m in distribution.items()), total_mass)
    return mean, second, second - mean * mean


def _sampler(distribution: dict[int, int]):
    values = []
    cumulative = []
    total = 0
    for value, mass in sorted(distribution.items()):
        if mass <= 0:
            continue
        values.append(value)
        total += mass
        cumulative.append(total)
    if total <= 0:
        raise ValueError("cannot sample an empty weighted distribution")
    def sample(rng: random.Random) -> int:
        return values[bisect_right(cumulative, rng.randrange(total))]
    return sample, total


def _sample_summary(samples: list[int], exact_mean: Fraction, exact_variance: Fraction,
                    exact_hit: Fraction, scope: str, wager_spins: int) -> dict:
    if not samples:
        raise ValueError("simulation sample is empty")
    ordered = sorted(samples)
    n = len(ordered)
    sample_mean = sum(ordered) / n
    sample_variance = sum((x - sample_mean) ** 2 for x in ordered) / n
    tail_count = max(1, (n + 999) // 1000)
    tail_mean = sum(ordered[-tail_count:]) / tail_count
    def q(index_num: int, index_den: int) -> int:
        return ordered[min(n - 1, (n * index_num + index_den - 1) // index_den - 1)]
    bucket_counts = {
        "zero": sum(x == 0 for x in ordered),
        "0_to_1x_inclusive": sum(0 < x <= 1000 for x in ordered),
        "1_to_5x": sum(1000 < x <= 5000 for x in ordered),
        "5_to_20x": sum(5000 < x <= 20000 for x in ordered),
        "20_to_100x": sum(20000 < x <= 100000 for x in ordered),
        "100x_plus": sum(x > 100000 for x in ordered),
    }
    stderr = sqrt(float(exact_variance) / n)
    z_score = (sample_mean - float(exact_mean)) / stderr if stderr else 0.0
    return {
        "scope": scope,
        "wager_spins": wager_spins,
        "distribution_method": "deterministic-seed Monte Carlo sampled from exact integer-weighted single-spin distributions; quantiles/CVaR/buckets are estimates",
        "sample_count": n,
        "sample_mean_payout_milli": sample_mean,
        "sample_mean_z_score_vs_exact_moment": z_score,
        "exact_mean_payout_milli": _fraction(exact_mean),
        "exact_variance_milli_squared": _fraction(exact_variance),
        "exact_standard_deviation_milli": sqrt(float(exact_variance)),
        "exact_standard_deviation_x_of_base_wager": sqrt(float(exact_variance)) / 1000,
        "exact_coefficient_of_variation": (sqrt(float(exact_variance)) / float(exact_mean)) if exact_mean else None,
        "exact_mean_payout_x_of_base_wager": float(exact_mean / 1000),
        "exact_return_percent_of_one_base_wager": float(exact_mean / 10),
        "exact_hit_frequency": _fraction(exact_hit),
        "exact_loss_frequency": _fraction(1 - exact_hit),
        "sample_standard_deviation_milli": sqrt(sample_variance),
        "estimated_quantiles_payout_milli": {
            "p50": q(50, 100), "p90": q(90, 100), "p95": q(95, 100),
            "p99": q(99, 100), "p99_9": q(999, 1000), "p99_99": q(9999, 10000),
        },
        "estimated_upper_0_1_percent_cvar_payout_milli": tail_mean,
        "estimated_maximum_payout_milli": ordered[-1],
        "estimated_payout_bucket_counts": bucket_counts,
        "estimated_payout_bucket_probabilities": {
            key: value / n for key, value in bucket_counts.items()
        },
        "empirical_payout_histogram": [
            {"payout_milli": payout, "sample_count": count}
            for payout, count in sorted(Counter(ordered).items())
        ],
    }


def _max_streak_masses(hit_mass: int, loss_mass: int, total_mass: int,
                       spins: int = 10) -> dict:
    """Exact IID binary-sequence longest-run distributions for a fixed spin count."""
    win_runs = {n: 0 for n in range(spins + 1)}
    loss_runs = {n: 0 for n in range(spins + 1)}
    sequence_count = 1 << spins
    for mask in range(sequence_count):
        wins = bin(mask).count("1")
        losses = spins - wins
        mass = hit_mass ** wins * loss_mass ** losses
        current_win = current_loss = max_win = max_loss = 0
        for index in range(spins):
            if mask & (1 << index):
                current_win += 1
                current_loss = 0
            else:
                current_loss += 1
                current_win = 0
            max_win = max(max_win, current_win)
            max_loss = max(max_loss, current_loss)
        win_runs[max_win] += mass
        loss_runs[max_loss] += mass
    denominator = total_mass ** spins
    if sum(win_runs.values()) != denominator or sum(loss_runs.values()) != denominator:
        raise ValueError("streak probability mass was not conserved")
    return {
        "model": "exact IID binary payout/no-payout sequences over 10 fixed spins; conditional no-retrigger spin distribution",
        "maximum_consecutive_winning_spin_distribution": [
            {"length": n, "probability": _fraction(Fraction(m, denominator))}
            for n, m in sorted(win_runs.items())
        ],
        "maximum_consecutive_losing_spin_distribution": [
            {"length": n, "probability": _fraction(Fraction(m, denominator))}
            for n, m in sorted(loss_runs.items())
        ],
        "probability_at_least_n_consecutive_wins": [
            {"n": n, "probability": _fraction(Fraction(sum(m for k, m in win_runs.items() if k >= n), denominator))}
            for n in range(1, spins + 1)
        ],
        "probability_at_least_n_consecutive_losses": [
            {"n": n, "probability": _fraction(Fraction(sum(m for k, m in loss_runs.items() if k >= n), denominator))}
            for n in range(1, spins + 1)
        ],
    }


def build_conditional_draft_round_projection() -> dict:
    """Enumerate and combine exact stop-weight distributions for a conditional round."""
    base = exact_weighted_spin_distribution("BASE")
    free = exact_weighted_spin_distribution("FREE_SPINS")
    total_spin_mass = 1
    for weights in STOP_WEIGHTS:
        total_spin_mass *= sum(weights)
    base_joint = _joint_by_scatter(base)
    free_joint = _joint_by_scatter(free)

    base_valid = _aggregate_scatter_domain(base_joint, range(4))
    base_valid_mass = sum(base_valid.values())
    base_exact_three_mass = sum(base_joint.get(3, {}).values())
    free_valid = _aggregate_scatter_domain(free_joint, range(3))
    free_valid_mass = sum(free_valid.values())
    free_blocked_mass = total_spin_mass - free_valid_mass

    if not base_valid_mass or not free_valid_mass or not base_exact_three_mass:
        raise ValueError("conditional Draft model has an empty required outcome domain")

    base_summary = _distribution_summary(base_valid, base_valid_mass,
        wager_spins=1, scope="BASE payout conditional on 0-3 Scatter; excludes feature value")
    free_single_summary = _distribution_summary(free_valid, free_valid_mass,
        wager_spins=1, scope="FREE_SPINS payout conditional on 0-2 Scatter; excludes retrigger outcomes")
    free_mean, free_second, free_variance = _moments(free_valid, free_valid_mass)
    base_mean, base_second, base_variance = _moments(base_valid, base_valid_mass)
    trigger_probability = Fraction(base_exact_three_mass, base_valid_mass)
    feature_ev = 10 * free_mean
    feature_variance = 10 * free_variance
    feature_second = feature_variance + feature_ev * feature_ev
    base_three_mean, base_three_second, _ = _moments(
        base_joint[3], base_exact_three_mass,
    )
    round_mean = base_mean + trigger_probability * feature_ev
    round_second = (base_second + 2 * trigger_probability * base_three_mean * feature_ev
                    + trigger_probability * feature_second)
    round_variance = round_second - round_mean * round_mean
    free_hit_mass = sum(m for payout, m in free_valid.items() if payout > 0)
    free_zero_mass = free_valid_mass - free_hit_mass
    free_ten_hit = 1 - Fraction(free_zero_mass, free_valid_mass) ** 10
    base_zero_no_feature = sum(base_joint.get(count, {}).get(0, 0) for count in range(3))
    base_zero_exact_three = base_joint.get(3, {}).get(0, 0)
    round_zero_probability = (
        Fraction(base_zero_no_feature, base_valid_mass)
        + Fraction(base_zero_exact_three, base_valid_mass)
          * Fraction(free_zero_mass, free_valid_mass) ** 10
    )
    round_hit = 1 - round_zero_probability

    # Quantile/tail estimates are sampled from the exact weighted spin laws.
    # Exact EV and variance above do not depend on Monte Carlo.
    sample_count = 1_000_000
    simulation_seed = 20261104
    rng = random.Random(simulation_seed)
    sample_free_spin, sampled_free_mass = _sampler(free_valid)
    if sampled_free_mass != free_valid_mass:
        raise ValueError("Free Spins sampler mass mismatch")
    free_ten_samples = [sum(sample_free_spin(rng) for _ in range(10))
                        for _ in range(sample_count)]

    base_items = []
    for scatter_count in range(4):
        for payout, mass in base_joint.get(scatter_count, {}).items():
            base_items.append(((scatter_count, payout), mass))
    base_values, base_cumulative, base_sample_mass = [], [], 0
    for (scatter_count, payout), mass in base_items:
        base_values.append((scatter_count, payout))
        base_sample_mass += mass
        base_cumulative.append(base_sample_mass)
    if base_sample_mass != base_valid_mass:
        raise ValueError("BASE sampler mass mismatch")
    round_samples = []
    for _ in range(sample_count):
        scatter_count, base_payout = base_values[bisect_right(base_cumulative, rng.randrange(base_sample_mass))]
        payout = base_payout
        if scatter_count == 3:
            payout += sum(sample_free_spin(rng) for _ in range(10))
        round_samples.append(min(CONFIG.max_round_win_milli, payout))

    free_ten_summary = _sample_summary(
        free_ten_samples, feature_ev, feature_variance, free_ten_hit,
        "10 fixed Free Spins conditional on every spin having 0-2 Scatter; no retrigger", 10,
    )
    round_summary = _sample_summary(
        round_samples, round_mean, round_variance, round_hit,
        "conditional BASE round: BASE Scatter 0-2 pays BASE only; exact-3 awards 10 fixed FS; each FS spin conditioned on 0-2 Scatter", 1,
    )
    base_valid_probability = Fraction(base_valid_mass, total_spin_mass)
    fs_valid_probability = Fraction(free_valid_mass, total_spin_mass)
    base_four_plus_mass = total_spin_mass - base_valid_mass
    free_three_plus_probability = Fraction(free_blocked_mass, total_spin_mass)

    exact_three_base_max = max(base_joint[3])
    free_valid_max = max(free_valid)
    max_feature = 10 * free_valid_max
    theoretical_round_max = min(CONFIG.max_round_win_milli, exact_three_base_max + max_feature)
    max_base_three_mass = base_joint[3][exact_three_base_max]
    max_free_spin_mass = free_valid[free_valid_max]
    max_round_path_probability = (
        Fraction(max_base_three_mass, base_exact_three_mass)
        * Fraction(max_free_spin_mass, free_valid_mass) ** 10
    )
    max_round_reachable = (base_joint[3].get(exact_three_base_max, 0) > 0
                           and free_valid.get(free_valid_max, 0) > 0
                           and theoretical_round_max <= CONFIG.max_round_win_milli)

    return {
        "schema": "ganesha-draft-conditional-round-projection.v1",
        "status": "PASS_EXACT_CONDITIONAL_DRAFT_MODEL_ONLY",
        "canonical_math": False,
        "provider_approved": False,
        "rtp_claim_permitted": False,
        "stake_upload_permitted": False,
        "draft_config_version": base["draft_config_version"],
        "calculation": {
            "method": "exhaustive 13^5 weighted stop-vector enumeration per spin mode; integer stop weights; exact Fraction EV/variance/hit-frequency and exact IID streak calculations; deterministic-seed Monte Carlo sampled from exact weighted single-spin distributions for 10-Free-Spin/round quantiles, CVaR and bucket frequencies",
            "stop_vectors_per_mode": base["total_stop_vectors_enumerated"],
            "single_spin_probability_mass": total_spin_mass,
            "free_spin_draws_per_feature": 10,
            "monte_carlo_used_for_distribution_estimates": True,
            "monte_carlo_used_for_exact_moments": False,
            "monte_carlo_sample_count_per_scope": sample_count,
            "monte_carlo_seed": simulation_seed,
            "quantile_and_cvar_status": "ESTIMATED_FROM_1M_SAMPLES",
            "canonical_or_provider_authority": False,
        },
        "conditional_model_rules": {
            "BASE_scatter_0_to_2": "BASE payout only",
            "BASE_exactly_3_scatter": "BASE payout plus exactly 10 Free Spins",
            "BASE_scatter_4_plus": "excluded; rules unspecified",
            "FREE_SPINS_scatter_0_to_2": "payout only; no retrigger",
            "FREE_SPINS_scatter_3_plus": "excluded; retrigger/feature behavior unspecified",
            "wild_expansion": "Draft config only: each reel containing Wild expands; multiplier 2^reels capped at 64",
            "payout_cap": {"single_spin_milli": CONFIG.max_win_milli, "round_milli": CONFIG.max_round_win_milli},
        },
        "excluded_probability_mass": {
            "BASE_4_plus_scatter": _fraction(Fraction(base_four_plus_mass, total_spin_mass)),
            "FREE_SPINS_3_plus_scatter_per_spin": _fraction(free_three_plus_probability),
            "at_least_one_blocked_retrigger_outcome_in_10_spins": _fraction(1 - fs_valid_probability ** 10),
        },
        "conditional_domain_probability": {
            "BASE_0_to_3_scatter": _fraction(base_valid_probability),
            "FREE_SPINS_0_to_2_scatter_per_spin": _fraction(fs_valid_probability),
            "all_10_Free_Spins_avoid_3_plus_Scatter": _fraction(fs_valid_probability ** 10),
        },
        "base_exact_three_trigger_probability_conditional_on_base_0_to_3": _fraction(trigger_probability),
        "base_exact_three_trigger_probability_unconditional_single_spin": _fraction(Fraction(base_exact_three_mass, total_spin_mass)),
        "base_expected_payout_milli_conditional_on_base_0_to_3": _fraction(base_mean),
        "free_spins_ev_per_spin_milli_conditional_on_0_to_2_scatter": _fraction(free_mean),
        "free_spins_10_ev_milli_conditional_on_no_retrigger": _fraction(feature_ev),
        "free_spins_10_variance_milli_squared_conditional_on_no_retrigger": _fraction(feature_variance),
        "feature_value_per_base_wager_milli_conditional_model": _fraction(trigger_probability * feature_ev),
        "feature_value_contribution_per_base_wager_milli_using_unconditional_exact_three_probability": _fraction(Fraction(base_exact_three_mass, total_spin_mass) * feature_ev),
        "base_single_spin_payout_only_all_scatter_counts": base,
        "free_spin_single_spin_payout_only_all_scatter_counts_not_feature_validity": free,
        "conditional_base_round_exact_moments": {
            "mean_payout_milli": _fraction(round_mean),
            "variance_milli_squared": _fraction(round_variance),
            "hit_frequency": _fraction(round_hit),
            "loss_frequency": _fraction(1 - round_hit),
        },
        "base_spin": base_summary,
        "free_spin_one_spin": free_single_summary,
        "free_spins_10_cumulative": free_ten_summary,
        "conditional_base_round": round_summary,
        "free_spins_10_streaks": _max_streak_masses(
            sum(m for p, m in free_valid.items() if p > 0),
            free_valid_mass - sum(m for p, m in free_valid.items() if p > 0),
            free_valid_mass,
        ),
        "conditional_round_streaks": {
            "model": "IID rounds under the same conditional BASE/10FS scenario; not provider-certified player history",
            "loss_run_at_least_n": [
                {"n": n, "probability": _fraction((1 - round_hit) ** n)} for n in range(1, 11)
            ],
            "win_run_at_least_n": [
                {"n": n, "probability": _fraction(round_hit ** n)} for n in range(1, 11)
            ],
        },
        "maximum_payout_reachability": {
            "draft_single_spin_cap_x": CONFIG.max_win_milli / 1000,
            "max_BASE_payout_on_exact_3_scatter_x": exact_three_base_max / 1000,
            "max_FREE_SPINS_payout_on_0_to_2_scatter_x": free_valid_max / 1000,
            "max_10_Free_Spins_cumulative_x": max_feature / 1000,
            "max_round_payout_mathematically_in_conditional_model_x": theoretical_round_max / 1000,
            "max_round_payout_observed_in_simulation_x": max(round_samples) / 1000,
            "max_round_path_has_nonzero_weight_mass": max_round_reachable,
            "maximum_round_path_probability_conditional_model": _fraction(max_round_path_probability),
            "max_exact_3_BASE_vector_weight_mass": max_base_three_mass,
            "max_valid_FREE_SPINS_vector_weight_mass": max_free_spin_mass,
            "draft_round_cap_x": CONFIG.max_round_win_milli / 1000,
            "draft_11_000x_upper_bound_is_tight": theoretical_round_max == 11_000_000,
            "50_000x_reachable_under_current_draft_spin_and_feature_limits": False,
            "50_000x_math_ceiling_vs_generation": "round cap is 50,000x, but current path is one BASE spin plus exactly ten Free Spins, each capped at 1,000x; actual path maximum is derived above and remains <=11,000x",
            "wallet_payment": {
                "local_sqlite_round_cap_x": CONFIG.max_round_win_milli / 1000,
                "maximum_base_bet_minor_supported_by_sqlite_cap": (((1 << 63) - 1) * 1000 - 500) // CONFIG.max_round_win_milli,
                "example_base_bet_minor": 1000,
                "example_max_reachable_payout_minor_half_up": (1000 * theoretical_round_max + 500) // 1000,
                "example_reserved_50000x_cap_minor": (1000 * CONFIG.max_round_win_milli + 500) // 1000,
                "local_ledger_behavior": "reserves 50,000x cap, verifies committed payout does not exceed it, and checks signed 64-bit balance overflow at settlement",
                "provider_wallet_or_distributed_settlement": "BLOCKED_NOT_CONNECTED_OR_PROVEN",
            },
        },
        "spin_distributions": {
            "BASE_all_scatter_counts": base,
            "FREE_SPINS_all_scatter_counts": free,
        },
    }
