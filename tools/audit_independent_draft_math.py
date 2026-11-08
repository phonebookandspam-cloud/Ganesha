#!/usr/bin/env python3
"""Exhaustive audit of the isolated independent Draft Math engine.

This deliberately reports unresolved regions and hard upper bounds only. It does
not manufacture RTP, hit frequency, volatility, Buy terms or jackpot probability.
"""
from __future__ import annotations
import hashlib, itertools, json
from collections import Counter
from pathlib import Path

from ganesha.math.config import (CONFIG, PAYLINES, PAYOUT_SCALE_DENOMINATOR,
                                 PAYOUT_SCALE_NUMERATOR, PAYTABLE_MILLI,
                                 REEL_STRIPS, SCATTER, STOP_WEIGHTS, SYMBOLS, WILD,
                                 validate_config)
from ganesha.math.engine import (UnspecifiedMathRule, board_from_stops,
                                 evaluate_board, free_spins_awarded)
from ganesha.math.reference import UnspecifiedReferenceRule, evaluate_board as reference_board
from ganesha.math.rng import HmacStopGenerator, implementation_version
from ganesha.game.engine import GameEngine
from ganesha.game.math_port import DraftMathPort

ROOT = Path(__file__).resolve().parents[1]


def _reference(board, mode):
    expanded = [i for i, reel in enumerate(board) if WILD in reel] if mode == "FREE_SPINS" else []
    multiplier = 1
    if expanded:
        multiplier = min(CONFIG.feature_rules.free_spin_wild_reel_multiplier ** len(expanded)
                         * (2 if len(expanded) == 5 else 1),
                         CONFIG.feature_rules.max_wild_reel_multiplier)
    return reference_board(board, paylines=PAYLINES, paytable_milli=PAYTABLE_MILLI,
                           wild_symbol=WILD, scatter_symbol=SCATTER, mode=mode,
                           wild_expansion_reels=expanded, wild_multiplier=multiplier,
                           scale_numerator=PAYOUT_SCALE_NUMERATOR,
                           scale_denominator=PAYOUT_SCALE_DENOMINATOR,
                           payout_cap_milli=CONFIG.max_win_milli)


def audit():
    validate_config()
    total_vectors = 1
    for strip in REEL_STRIPS:
        total_vectors *= len(strip)
    result = {
        "schema": "ganesha-independent-draft-math-audit.v1",
        "status": "PASS_DRAFT_STRUCTURE_WITH_MATH_RELEASE_BLOCKERS",
        "canonical_math": False,
        "provider_approved": False,
        "stake_upload_permitted": False,
        "rtp_claim_permitted": False,
        "config_version": CONFIG.version,
        "source_hashes": {},
        "input_structure": {
            "symbols": list(SYMBOLS), "symbol_count": len(SYMBOLS),
            "reels": len(REEL_STRIPS), "stops_per_reel": [len(x) for x in REEL_STRIPS],
            "stop_vectors": total_vectors, "stop_weight_sums": [sum(x) for x in STOP_WEIGHTS],
            "paylines": len(PAYLINES), "paytable_symbols": len(PAYTABLE_MILLI),
            "paytable_match_lengths": [3, 4, 5],
            "payout_scale": {"numerator": PAYOUT_SCALE_NUMERATOR, "denominator": PAYOUT_SCALE_DENOMINATOR},
        },
        "rng": {}, "feature_rules": {}, "enumeration": {},
        "full_game_metrics": {key: "BLOCKED_NOT_COMPUTED" for key in (
            "base_rtp", "free_spins_rtp", "magic_buy_rtp", "epic_buy_rtp",
            "hit_frequency", "variance", "volatility", "payout_distribution",
            "losing_streak_distribution", "winning_streak_distribution", "max_payout_frequency")},
        "buy_modes": {"MAGIC_BUY": "BLOCKED_NO_APPROVED_PRICE_SPIN_COUNT_OR_PROBABILITY_MODEL",
                      "EPIC_BUY": "BLOCKED_NO_APPROVED_PRICE_SPIN_COUNT_OR_PROBABILITY_MODEL"},
        "design_targets": {"rtp_percent": "96.50_UNVERIFIED", "max_win_x": "50000_UNVERIFIED"},
        "issues": [],
    }

    # Determinism under a test-only key; this is not entropy or key-management certification.
    test_key = bytes(range(32))
    rng_a = HmacStopGenerator(test_key)
    rng_b = HmacStopGenerator(test_key)
    sample_a = rng_a.stop_vectors("DRAFT-AUDIT-TEST-ROUND", 16)
    sample_b = rng_b.stop_vectors("DRAFT-AUDIT-TEST-ROUND", 16)
    valid_bounds = all(len(v) == 5 and all(0 <= stop < 13 for stop in v) for v in sample_a)
    result["rng"] = {"algorithm": "HMAC-SHA256 with rejection sampling",
                      "implementation_version": implementation_version(),
                      "same_test_key_round_spin_reproducible": sample_a == sample_b,
                      "stop_vector_bounds_valid": valid_bounds,
                      "test_key_is_ephemeral_not_a_production_secret": True,
                      "cryptographic_entropy_and_secret_storage": "NOT_CERTIFIED"}

    result["feature_rules"] = {
        "base_exact_three_scatter_award": 10,
        "base_scatter_0_to_2_award": 0,
        "base_scatter_4_plus": "BLOCKED_UNSPECIFIED",
        "free_spins_scatter_retrigger": "BLOCKED_UNSPECIFIED",
        "wild_expansion": {"mode": "FREE_SPINS_DRAFT_ONLY", "per_reel_multiplier": CONFIG.feature_rules.free_spin_wild_reel_multiplier,
                           "max_wild_multiplier": CONFIG.feature_rules.max_wild_reel_multiplier},
        "bonus_buy": "BLOCKED_NO_EXPLICIT_MATH_PORT_TERMS",
    }

    counts = {"BASE": {"checked": 0, "blocked": 0, "mismatches": 0,
                       "scatter_stop_vectors": Counter(), "max_payout_milli": 0, "max_vector_count": 0},
              "FREE_SPINS": {"checked": 0, "blocked": 0, "mismatches": 0,
                             "scatter_stop_vectors": Counter(), "max_payout_milli": 0, "max_vector_count": 0}}
    first_mismatches = []
    for stops in itertools.product(*(range(len(strip)) for strip in REEL_STRIPS)):
        board = board_from_stops(stops)
        scatter_count = sum(symbol == SCATTER for reel in board for symbol in reel)
        for mode in ("BASE", "FREE_SPINS"):
            bucket = counts[mode]
            bucket["scatter_stop_vectors"][str(scatter_count)] += 1
            try:
                engine_result = evaluate_board(board, mode)
            except UnspecifiedMathRule:
                try:
                    _reference(board, mode)
                except UnspecifiedReferenceRule:
                    bucket["blocked"] += 1
                    continue
                bucket["mismatches"] += 1
                if len(first_mismatches) < 10:
                    first_mismatches.append({"stops": stops, "mode": mode, "reason": "engine blocked; reference resolved"})
                continue
            try:
                reference_result = _reference(board, mode)
            except Exception as exc:
                bucket["mismatches"] += 1
                if len(first_mismatches) < 10:
                    first_mismatches.append({"stops": stops, "mode": mode, "reason": "reference raised " + type(exc).__name__})
                continue
            bucket["checked"] += 1
            if engine_result != reference_result:
                bucket["mismatches"] += 1
                if len(first_mismatches) < 10:
                    first_mismatches.append({"stops": stops, "mode": mode, "reason": "result mismatch"})
            payout = engine_result["payout_milli"]
            if payout > bucket["max_payout_milli"]:
                bucket["max_payout_milli"] = payout
                bucket["max_vector_count"] = 1
            elif payout == bucket["max_payout_milli"]:
                bucket["max_vector_count"] += 1

    for mode, bucket in counts.items():
        result["enumeration"][mode] = {
            "total_stop_vectors": total_vectors,
            "fully_resolved_vectors": bucket["checked"],
            "blocked_vectors": bucket["blocked"],
            "independent_reference_mismatches": bucket["mismatches"],
            "scatter_count_stop_vector_counts": dict(bucket["scatter_stop_vectors"]),
            "max_resolved_single_spin_payout_milli": bucket["max_payout_milli"],
            "vectors_at_resolved_single_spin_max": bucket["max_vector_count"],
        }
    result["independent_reference_crosscheck"] = {
        "status": "PASS_DRAFT_ONLY" if not first_mismatches and all(x["mismatches"] == 0 for x in counts.values()) else "FAIL",
        "mismatches": first_mismatches,
        "scope": "Two independently implemented evaluators over the same unapproved draft inputs; not canonical correctness.",
    }

    # The currently executable draft has one BASE spin plus exactly ten Free Spins;
    # each spin is capped at 1,000x and retrigger is blocked.
    max_spin_x = CONFIG.max_win_milli / 1000
    max_round_x = max_spin_x * (1 + 10)
    result["maximum_payout_bound"] = {
        "per_spin_cap_x": max_spin_x,
        "base_spins": 1,
        "authorized_initial_free_spins": 10,
        "retrigger": "BLOCKED",
        "current_draft_round_upper_bound_x": max_round_x,
        "design_target_x": 50000,
        "design_target_reachable_under_current_draft_rules": False,
        "reason": "At most 11 capped spins (one BASE + ten Free Spins) exist in this draft; 11 × 1,000x = 11,000x. The 50,000x round cap is only a ceiling and no jackpot path is enabled.",
        "canonical_max_win_reachability": "UNVERIFIED",
        "provider_payment_capability": "UNVERIFIED",
        "max_win_frequency": "NOT_COMPUTED",
    }
    result["bonus_buy_port"] = {"draft_math_port_has_buy_resolver": hasattr(DraftMathPort(), "resolve_bonus_buy_terms"),
                                "game_engine_buy_terms": "REQUIRES_EXPLICIT_AUTHORIZED_MATH_PORT_TERMS",
                                "current_mode_prices": "NOT_DEFINED"}

    paths = ("src/ganesha/math/config.py", "src/ganesha/math/engine.py", "src/ganesha/math/reference.py",
             "src/ganesha/math/rng.py", "src/ganesha/math/round_ev.py", "src/ganesha/math/feature_ev.py",
             "src/ganesha/math/simulation.py", "src/ganesha/game/engine.py", "src/ganesha/game/math_port.py")
    result["source_hashes"] = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in paths}
    if not result["rng"]["same_test_key_round_spin_reproducible"] or not valid_bounds:
        result["issues"].append("RNG deterministic test failed")
    if result["independent_reference_crosscheck"]["status"] != "PASS_DRAFT_ONLY":
        result["issues"].append("Independent draft evaluator/reference mismatch")
    if any(v["mismatches"] for v in counts.values()):
        result["issues"].append("Independent reference mismatch")
    if result["issues"]:
        result["status"] = "FAIL"
    return result


def main():
    report = audit()
    target = ROOT / "artifacts/INDEPENDENT_DRAFT_MATH_AUDIT_20261104.json"
    if target.exists():
        raise SystemExit("refusing to overwrite existing audit artifact: " + str(target))
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("REPORT_PATH=" + str(target))
    raise SystemExit(0 if report["status"] == "PASS_DRAFT_STRUCTURE_WITH_MATH_RELEASE_BLOCKERS" else 2)


if __name__ == "__main__":
    main()
