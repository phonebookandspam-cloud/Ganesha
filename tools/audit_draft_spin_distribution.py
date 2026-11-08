#!/usr/bin/env python3
"""Exhaustive exact weighted single-spin audit for isolated Draft Math only."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ganesha.math.config import CONFIG, REEL_STRIPS, STOP_WEIGHTS
from ganesha.math.draft_distribution import exact_weighted_spin_distribution

ROOT = Path(__file__).resolve().parents[1]


def audit() -> dict:
    modes = {mode: exact_weighted_spin_distribution(mode) for mode in ("BASE", "FREE_SPINS")}
    max_spin_x = CONFIG.max_win_milli / 1000
    result = {
        "schema": "ganesha-draft-exact-single-spin-distribution.v1",
        "status": "PASS_DRAFT_SINGLE_SPIN_ONLY",
        "release_status": "SUPERSEDED_NOT_RELEASE_EVIDENCE",
        "canonical_math": False,
        "provider_approved": False,
        "rtp_claim_permitted": False,
        "stake_upload_permitted": False,
        "draft_config_version": CONFIG.version,
        "input_shape": {
            "reels": len(REEL_STRIPS),
            "stops_per_reel": [len(reel) for reel in REEL_STRIPS],
            "stop_weight_sums": [sum(weights) for weights in STOP_WEIGHTS],
            "stop_vectors_per_mode": 13 ** 5,
        },
        "modes": modes,
        "full_game_metrics": {
            "BASE_RTP_including_feature_value": "BLOCKED_4_PLUS_SCATTER_AND_CANONICAL_AUTHORITY",
            "FREE_SPINS_RTP_including_feature_value": "BLOCKED_RETRIGGER_TERMINATION_AND_CANONICAL_AUTHORITY",
            "MAGIC_BUY_RTP": "BLOCKED_NO_APPROVED_PRICE_SPIN_COUNT_OR_PROBABILITY_MODEL",
            "EPIC_BUY_RTP": "BLOCKED_NO_APPROVED_PRICE_SPIN_COUNT_OR_PROBABILITY_MODEL",
            "full_round_variance_volatility_and_payout_distribution": "BLOCKED_UNSPECIFIED_TRANSITIONS",
            "full_round_streak_distribution": "BLOCKED_MODE_TRANSITIONS_AND_FEATURE_LENGTH",
            "50_000x_round_max_frequency": "BLOCKED_NO_REACHABLE_APPROVED_PATH_OR_PROVIDER_PAYMENT_EVIDENCE",
        },
        "maximum_payout_reachability": {
            "draft_single_spin_cap_x": max_spin_x,
            "draft_authorized_initial_free_spins": 10,
            "retrigger": "BLOCKED_UNSPECIFIED",
            "current_draft_round_upper_bound_x": max_spin_x * 11,
            "50_000x_reachable_under_current_draft_rules": False,
            "all_single_spin_stop_vectors_enumerated": all(
                mode["total_stop_vectors_enumerated"] == 13 ** 5 for mode in modes.values()
            ),
        },
        "interpretation": (
            "Exact weighted distribution of one spin under the unapproved Draft-005 reel strips, "
            "weights, paytable, payline, Wild and payout-cap assumptions. It excludes feature value, "
            "retrigger, Buy modes and complete game-round behavior. Streaks are IID single-spin "
            "Bernoulli projections, not actual round-level streak claims."
        ),
        "source_hashes": {},
    }
    for relative in (
        "src/ganesha/math/config.py", "src/ganesha/math/engine.py",
        "src/ganesha/math/reference.py", "src/ganesha/math/rng.py",
        "src/ganesha/math/draft_distribution.py", "tools/audit_draft_spin_distribution.py",
    ):
        result["source_hashes"][relative] = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
    return result


def main() -> None:
    report = audit()
    target = ROOT / "artifacts/DRAFT_EXACT_SINGLE_SPIN_DISTRIBUTION_20261104_R2_draft_only.json"
    if target.exists():
        raise SystemExit("refusing to overwrite existing artifact: " + str(target))
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("REPORT_PATH=" + str(target))


if __name__ == "__main__":
    main()
