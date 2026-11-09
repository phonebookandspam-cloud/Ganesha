"""Fail-closed Monte Carlo entrypoint with retained pure statistics utilities.

The helper functions below only summarize caller-supplied samples. The active
run_monte_carlo entrypoint intentionally performs no sampling until canonical
inputs and complete approved feature/Buy rules exist.
"""
import math
from collections import Counter


def _streak_metrics(samples):
    """Pure streak summary over caller-supplied observations."""
    zero_hist = Counter()
    win_hist = Counter()
    zero_run = 0
    win_run = 0
    max_zero = 0
    max_win = 0
    for value in samples:
        if value == 0:
            if win_run:
                win_hist[min(win_run, 10)] += 1
                win_run = 0
            zero_run += 1
            max_zero = max(max_zero, zero_run)
        else:
            if zero_run:
                zero_hist[min(zero_run, 10)] += 1
                zero_run = 0
            win_run += 1
            max_win = max(max_win, win_run)
    if zero_run:
        zero_hist[min(zero_run, 10)] += 1
    if win_run:
        win_hist[min(win_run, 10)] += 1
    return {
        "max_consecutive_zero_rounds": max_zero,
        "max_consecutive_winning_rounds": max_win,
        "zero_streak_length_histogram_capped_at_10": dict(sorted(zero_hist.items())),
        "win_streak_length_histogram_capped_at_10": dict(sorted(win_hist.items())),
    }


def _metrics(samples, cost_x):
    """Pure sample-statistics utility; not invoked by the blocked game simulator."""
    try:
        values = list(samples)
    except TypeError as exc:
        raise ValueError("samples must be an iterable of non-negative exact integer payouts") from exc
    n = len(values)
    if n == 0 or any(type(value) is not int or value < 0 for value in values):
        raise ValueError("samples must be non-empty non-negative exact integer payouts")
    if (type(cost_x) not in (int, float) or not math.isfinite(cost_x)
            or cost_x <= 0):
        raise ValueError("cost_x must be a positive finite exact int or float")
    values.sort()
    mean = sum(values) / n
    variance = sum((x - mean) ** 2 for x in values) / n
    sd = math.sqrt(variance)
    top_n = max(1, int(math.ceil(n * 0.001)))
    top = values[-top_n:]

    def quantile(q):
        return values[min(n - 1, int(math.ceil(q * n)) - 1)] / 1000.0 / cost_x

    buckets = {
        "zero": sum(x == 0 for x in values),
        "0_to_1x": sum(0 < x <= 1000 for x in values),
        "1_to_5x": sum(1000 < x <= 5000 for x in values),
        "5_to_20x": sum(5000 < x <= 20000 for x in values),
        "20_to_100x": sum(20000 < x <= 100000 for x in values),
        "100x_plus": sum(x > 100000 for x in values),
    }
    return {
        "rounds": n,
        "purchase_cost_x": cost_x,
        "observed_rtp_percent": mean / 1000.0 / cost_x * 100,
        "standard_deviation_x_of_base_wager": sd / 1000.0,
        "standard_deviation_x_of_purchase_cost": sd / 1000.0 / cost_x,
        "rtp_95pct_normal_ci_percent": [
            (mean - 1.96 * sd / math.sqrt(n)) / 1000.0 / cost_x * 100,
            (mean + 1.96 * sd / math.sqrt(n)) / 1000.0 / cost_x * 100,
        ],
        "hit_frequency": sum(x > 0 for x in values) / n,
        "max_win_observed_count": sum(x >= 50_000_000 for x in values),
        "max_win_observed_frequency": sum(x >= 50_000_000 for x in values) / n,
        "quantiles_x_of_purchase_cost": {"p50": quantile(.50), "p90": quantile(.90), "p95": quantile(.95), "p99": quantile(.99), "p99_9": quantile(.999), "p99_99": quantile(.9999)},
        "upper_0_1pct_cvar_x_of_purchase_cost": sum(top) / top_n / 1000.0 / cost_x,
        "payout_bucket_counts": buckets,
        "streaks": _streak_metrics(samples),
        "max_payout_x_of_base_wager": max(values) / 1000.0,
        "max_payout_x_of_purchase_cost": max(values) / 1000.0 / cost_x,
    }


def run_monte_carlo():
    return {
        "schema": "ganesha-full-scratch-monte-carlo.v2",
        "status": "BLOCKED_UNSPECIFIED_RULES",
        "release_status": "SUPERSEDED_NOT_RELEASE_EVIDENCE",
        "canonical_math": False,
        "provider_approved": False,
        "public_claims_permitted": False,
        "sample_run_performed": False,
        "modes": {
            "BASE": "BLOCKED_CANONICAL_INPUTS_AND_5_SCATTER_EMBEDDED_EPIC_PAYLOAD",
            "FREE_SPINS": "BLOCKED_RETRIGGER_AND_TERMINATION_RULES",
            "MAGIC_BUY": "BLOCKED_NO_CANONICAL_PROBABILITY_MODEL_OR_PROVIDER_APPROVAL; USER_PRICE_X100",
            "EPIC_BUY": "BLOCKED_NO_CANONICAL_PROBABILITY_MODEL_OR_PROVIDER_APPROVAL; USER_PRICE_X500",
        },
        "metrics": {"rtp": "NOT_COMPUTED", "hit_frequency": "NOT_COMPUTED",
                    "variance": "NOT_COMPUTED", "volatility": "NOT_COMPUTED",
                    "payout_distribution": "NOT_COMPUTED", "streak_distribution": "NOT_COMPUTED",
                    "max_payout_frequency": "NOT_COMPUTED"},
        "blockers": [
            "A Monte Carlo run cannot resolve missing game rules or canonical source authority.",
            "Current BASE awards are 3 Scatter = 10 Free Spins and 4 Scatter = 12 Free Spins; 5 Scatter selects the embedded EPICBUY_V37 feature but remains blocked without its Provider payload and BASE-unit conversion; 6+ fails closed.",
            "Free Spins retrigger remains fail closed until its canonical rule is approved.",
            "No Buy price, spin count or probability model may be inferred.",
            "The 96.50% RTP and 50,000x maximum payout remain design targets only.",
        ],
    }
