#!/usr/bin/env python3
"""Independent, hash-bound audit of the current unapproved Draft Math evidence.

This audit does not create or certify Canonical Math. It independently rebuilds
the stop-to-board mapping, checks the existing Draft engine against the separate
reference evaluator on resolved domains, preserves unresolved probability mass,
and reports maximum-path probability under explicitly named conditioning scopes.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import argparse
from collections import defaultdict
from fractions import Fraction
from math import prod
from pathlib import Path

from ganesha.math.config import (
    CONFIG, REEL_STRIPS, SCATTER, STOP_WEIGHTS,
)
from ganesha.math.engine import board_from_stops

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "artifacts/DRAFT_MATH_EVIDENCE_AUDIT_20261104_R4_draft_only.json"
REPORT_HASH = REPORT.with_suffix(REPORT.suffix + ".sha256")
R3_REPORT = ROOT / "artifacts/DRAFT_CONDITIONAL_ROUND_EXACT_20261104_R3_draft_only.json"
CROSSCHECK_REPORT = ROOT / "artifacts/DRAFT_MATH_INDEPENDENT_CROSSCHECK_20261104_R2_draft_only.json"
SOURCE_PATHS = (
    "src/ganesha/math/config.py",
    "src/ganesha/math/engine.py",
    "src/ganesha/math/reference.py",
    "src/ganesha/math/rng.py",
    "src/ganesha/math/draft_distribution.py",
    "src/ganesha/math/draft_round_projection.py",
    "src/ganesha/game/engine.py",
    "src/ganesha/game/math_port.py",
    "src/ganesha/rgs/service.py",
    "src/ganesha/wallet/ledger.py",
    "tools/math_reference_crosscheck.py",
    "tools/audit_draft_conditional_round.py",
    "tools/audit_independent_draft_math.py",
    "docs/authority-boundary.md",
    "docs/canonical-math-recovery-checklist.md",
    "docs/math-spec-v1-draft.md",
    "tests/test_math_engine.py",
    "tests/test_math_reference.py",
    "tests/test_draft_distribution.py",
    "tests/test_draft_round_projection.py",
    "tests/test_game_engine.py",
    "tests/test_wallet_rgs.py",
    "artifacts/DRAFT_CONDITIONAL_ROUND_EXACT_20261104_R3_draft_only.json",
    "artifacts/DRAFT_MATH_INDEPENDENT_CROSSCHECK_20261104_R2_draft_only.json",
    "tools/audit_draft_math_evidence_r4.py",
    "tests/test_draft_math_evidence_r4.py",
)


def _fraction(value: Fraction) -> dict[str, int]:
    return {"numerator": value.numerator, "denominator": value.denominator}


def independent_board_from_stops(stops, reel_strips=REEL_STRIPS):
    """Reconstruct the visible board without calling the production board mapper."""
    if not isinstance(stops, (tuple, list)) or len(stops) != 5:
        raise ValueError("exactly five stop indices are required")
    if not isinstance(reel_strips, (tuple, list)) or len(reel_strips) != 5:
        raise ValueError("exactly five reel strips are required")
    board = []
    for index, stop in enumerate(stops):
        strip = reel_strips[index]
        if not strip or type(stop) is not int or not 0 <= stop < len(strip):
            raise ValueError("stop index is outside its reel strip")
        board.append(tuple(strip[(stop + row) % len(strip)] for row in range(3)))
    return tuple(board)


def maximum_path_probability_scopes(*, total_mass: int, base_valid_mass: int,
                                    exact_three_mass: int, max_base_exact_three_mass: int,
                                    free_valid_mass: int, max_free_valid_mass: int,
                                    free_spins: int = 10) -> dict:
    """Return three distinct probabilities; never conflate trigger-conditional and wager-level mass."""
    values = (total_mass, base_valid_mass, exact_three_mass,
              max_base_exact_three_mass, free_valid_mass,
              max_free_valid_mass, free_spins)
    if any(type(value) is not int or value <= 0 for value in values):
        raise ValueError("all masses and free_spins must be positive integers")
    if (base_valid_mass > total_mass or exact_three_mass > base_valid_mass
            or max_base_exact_three_mass > exact_three_mass
            or free_valid_mass > total_mass or max_free_valid_mass > free_valid_mass):
        raise ValueError("probability masses are not nested consistently")

    max_free_given_valid = Fraction(max_free_valid_mass, free_valid_mass)
    conditional_on_trigger = (
        Fraction(max_base_exact_three_mass, exact_three_mass)
        * max_free_given_valid ** free_spins
    )
    conditional_base_domain = (
        Fraction(max_base_exact_three_mass, base_valid_mass)
        * max_free_given_valid ** free_spins
    )
    unconditional_stop_model = (
        Fraction(max_base_exact_three_mass, total_mass)
        * Fraction(max_free_valid_mass, total_mass) ** free_spins
    )
    return {
        "conditional_on_exact_three_trigger_and_each_free_spin_in_0_to_2": _fraction(conditional_on_trigger),
        "conditional_on_base_scatter_0_to_3_and_each_free_spin_in_0_to_2": _fraction(conditional_base_domain),
        "unconditional_stop_vector_mass_for_this_known_path": _fraction(unconditional_stop_model),
        "assumptions": [
            "BASE and each Free Spin use the same explicitly configured independent reel-stop weight model.",
            "The ten Free Spins are independent draws from that same model.",
            "The BASE maximum path requires exactly three Scatter; Free Spin maximum paths require zero to two Scatter.",
            "These are Draft model probabilities only, not Canonical Math or Provider Golden Vector probabilities.",
        ],
    }


def audit() -> dict:
    if len(REEL_STRIPS) != 5 or len(STOP_WEIGHTS) != 5:
        raise ValueError("Draft model must contain five reel strips and five weight arrays")
    for index, (strip, weights) in enumerate(zip(REEL_STRIPS, STOP_WEIGHTS)):
        if len(strip) != len(weights) or not strip or any(type(w) is not int or w <= 0 for w in weights):
            raise ValueError("invalid Draft strip/weight pairing on reel %d" % index)

    if not R3_REPORT.is_file() or not CROSSCHECK_REPORT.is_file():
        raise FileNotFoundError("hash-bound R3 conditional projection and R2 independent crosscheck are required")
    r3_bytes = R3_REPORT.read_bytes()
    crosscheck_bytes = CROSSCHECK_REPORT.read_bytes()
    r3 = json.loads(r3_bytes)
    crosscheck = json.loads(crosscheck_bytes)
    if (r3.get("status") != "PASS_EXACT_CONDITIONAL_DRAFT_MODEL_ONLY"
            or r3.get("canonical_math") is not False
            or r3.get("provider_approved") is not False
            or crosscheck.get("status") != "PASS_DRAFT_ONLY"
            or crosscheck.get("canonical_math") is not False
            or crosscheck.get("provider_approved") is not False):
        raise ValueError("input Draft evidence has an unexpected status or authority classification")

    r3_math_paths = (
        "src/ganesha/math/config.py", "src/ganesha/math/engine.py",
        "src/ganesha/math/reference.py", "src/ganesha/math/draft_distribution.py",
        "src/ganesha/math/draft_round_projection.py", "src/ganesha/game/engine.py",
        "src/ganesha/game/math_port.py", "tools/audit_draft_conditional_round.py",
    )
    r3_math_hash_matches = {
        path: r3.get("source_hashes", {}).get(path) == hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
        for path in r3_math_paths
    }
    r3_non_math_hash_drift = {
        path: {
            "recorded": expected,
            "current": hashlib.sha256((ROOT / path).read_bytes()).hexdigest(),
        }
        for path, expected in r3.get("source_hashes", {}).items()
        if path not in r3_math_paths
        and (ROOT / path).is_file()
        and expected != hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
    }
    crosscheck_hash_matches = {
        path: expected == hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
        for path, expected in crosscheck.get("source_hashes", {}).items()
        if (ROOT / path).is_file()
    }
    if not all(r3_math_hash_matches.values()) or not all(crosscheck_hash_matches.values()):
        raise ValueError("R3/R2 math source hashes do not match current source bytes")
    if crosscheck.get("mismatches"):
        raise ValueError("hash-matched R2 independent evaluator crosscheck contains mismatches")

    base_data = r3["spin_distributions"]["BASE_all_scatter_counts"]
    free_data = r3["spin_distributions"]["FREE_SPINS_all_scatter_counts"]
    total_mass = base_data["total_probability_mass"]
    total_vectors = base_data["total_stop_vectors_enumerated"]
    if total_mass != prod(sum(weights) for weights in STOP_WEIGHTS):
        raise ValueError("R3 probability mass differs from the current configured reel-weight product")
    if total_vectors != prod(len(strip) for strip in REEL_STRIPS):
        raise ValueError("R3 stop-vector count differs from the current configured reel-strip product")
    if (free_data["total_probability_mass"] != total_mass
            or free_data["total_stop_vectors_enumerated"] != total_vectors):
        raise ValueError("R3 BASE and FREE_SPINS distributions do not share the same stop domain")

    payout_by_scatter = {
        "BASE": {
            item["scatter_count"]: {row["payout_milli"]: row["weight_mass"] for row in item["payout_distribution"]}
            for item in base_data["scatter_count_payout_weight_mass"]
        },
        "FREE_SPINS": {
            item["scatter_count"]: {row["payout_milli"]: row["weight_mass"] for row in item["payout_distribution"]}
            for item in free_data["scatter_count_payout_weight_mass"]
        },
    }
    r3_scatter_masses = {
        "BASE": {item["scatter_count"]: item["weight_mass"] for item in base_data["scatter_count_weight_mass"]},
        "FREE_SPINS": {item["scatter_count"]: item["weight_mass"] for item in free_data["scatter_count_weight_mass"]},
    }
    independent_scatter_masses: dict[int, int] = defaultdict(int)
    mapping_mismatches = []
    mapped_vectors = 0
    for stops in itertools.product(*(range(len(strip)) for strip in REEL_STRIPS)):
        board = independent_board_from_stops(stops)
        mapped_vectors += 1
        if board != board_from_stops(stops) and len(mapping_mismatches) < 5:
            mapping_mismatches.append({"stops": list(stops), "independent": board, "production": board_from_stops(stops)})
        weight = prod(STOP_WEIGHTS[index][stop] for index, stop in enumerate(stops))
        scatter_count = sum(symbol == SCATTER for reel in board for symbol in reel)
        independent_scatter_masses[scatter_count] += weight
    if mapped_vectors != total_vectors:
        raise AssertionError("independent stop mapping vector count differs from R3")
    scatter_mass_matches = {
        mode: independent_scatter_masses == r3_scatter_masses[mode]
        for mode in ("BASE", "FREE_SPINS")
    }
    if not all(scatter_mass_matches.values()):
        raise AssertionError("independently reconstructed Scatter probability masses differ from R3")
    payout_mass_matches = {
        mode: {
            scatter_count: sum(payouts.values()) == independent_scatter_masses.get(scatter_count, 0)
            for scatter_count, payouts in payout_by_scatter[mode].items()
        }
        for mode in ("BASE", "FREE_SPINS")
    }
    if not all(all(results.values()) for results in payout_mass_matches.values()):
        raise AssertionError("R3 payout-by-Scatter masses do not conserve independently mapped Scatter masses")

    def mass_for(scatter_counts) -> int:
        return sum(independent_scatter_masses.get(count, 0) for count in scatter_counts)

    def payout_mass(mode: str, scatter_counts) -> dict[int, int]:
        result: dict[int, int] = defaultdict(int)
        for count in scatter_counts:
            for payout, mass in payout_by_scatter[mode].get(count, {}).items():
                result[payout] += mass
        return dict(result)

    base_valid_mass = mass_for(range(4))
    base_exact_three_mass = mass_for((3,))
    free_valid_mass = mass_for(range(3))
    base_no_feature = payout_mass("BASE", range(3))
    base_exact_three = payout_mass("BASE", (3,))
    free_valid = payout_mass("FREE_SPINS", range(3))
    if not base_valid_mass or not base_exact_three_mass or not free_valid_mass:
        raise AssertionError("required known Draft domain has zero probability mass")
    max_base_payout, max_free_payout = max(base_exact_three), max(free_valid)
    max_base_mass = base_exact_three[max_base_payout]
    max_free_mass = free_valid[max_free_payout]
    max_round_raw = max_base_payout + 10 * max_free_payout
    max_base_no_feature_payout = max(base_no_feature)
    max_round_raw_overall = max(max_base_no_feature_payout, max_round_raw)
    max_round_payout = min(CONFIG.max_round_win_milli, max_round_raw_overall)
    path_scopes = maximum_path_probability_scopes(
        total_mass=total_mass,
        base_valid_mass=base_valid_mass,
        exact_three_mass=base_exact_three_mass,
        max_base_exact_three_mass=max_base_mass,
        free_valid_mass=free_valid_mass,
        max_free_valid_mass=max_free_mass,
    )
    cap_saturated = max_round_raw_overall >= CONFIG.max_round_win_milli
    if cap_saturated or max_round_raw <= max_base_no_feature_payout:
        max_frequency_scope = "MAX_PAYOUT_FREQUENCY_NOT_ENUMERATED; REPORTED PATH IS A LOWER-BOUND WITNESS"
    else:
        max_frequency_scope = "EXACT_MAXIMUM_PAYOUT_FREQUENCY_FOR_THE_CONDITIONAL_MODEL"

    source_hashes = {
        path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
        for path in SOURCE_PATHS
    }
    status = "PASS_DRAFT_ONLY_WITH_UNRESOLVED_FEATURE_DOMAINS" if (
        not mapping_mismatches and all(scatter_mass_matches.values())
        and all(all(results.values()) for results in payout_mass_matches.values())
        and base_valid_mass + (total_mass - base_valid_mass) == total_mass
        and free_valid_mass + (total_mass - free_valid_mass) == total_mass
    ) else "FAIL"

    return {
        "schema": "ganesha-draft-math-evidence-audit.v4",
        "status": status,
        "authority": {
            "canonical_math": False,
            "provider_approved": False,
            "stake_upload_permitted": False,
            "rtp_claim_permitted": False,
            "release_evidence": False,
            "design_targets_unverified": {"rtp_percent": "96.50", "maximum_payout_x": 50000},
        },
        "draft_model": {
            "config_version": CONFIG.version,
            "symbols_count": len({symbol for reel in REEL_STRIPS for symbol in reel}),
            "reels": len(REEL_STRIPS),
            "stops_per_reel": [len(strip) for strip in REEL_STRIPS],
            "stop_vectors_per_mode": total_vectors,
            "stop_weight_sums": [sum(weights) for weights in STOP_WEIGHTS],
            "total_stop_vector_weight_mass": total_mass,
            "single_spin_cap_milli": CONFIG.max_win_milli,
            "round_cap_milli": CONFIG.max_round_win_milli,
            "initial_exact_three_free_spins": 10,
        },
        "independent_mapping_and_evaluator": {
            "mapping_method": "independent direct strip indexing; does not call board_from_stops",
            "mapping_mismatches": mapping_mismatches,
            "mapping_vectors_checked": mapped_vectors,
            "scatter_mass_reconstruction_matches_r3": scatter_mass_matches,
            "r3_payout_mass_conservation_by_scatter_class": payout_mass_matches,
            "r3_math_source_hash_matches_current": r3_math_hash_matches,
            "r3_non_math_source_hash_drift": r3_non_math_hash_drift,
            "r2_independent_evaluator_crosscheck": {
                "artifact_sha256": hashlib.sha256(crosscheck_bytes).hexdigest(),
                "status": crosscheck.get("status"),
                "source_hash_matches_current": crosscheck_hash_matches,
                "modes": crosscheck.get("modes"),
                "mismatches": crosscheck.get("mismatches"),
                "scope": "previous hash-matched exhaustive current-Draft engine/reference comparison; not canonical correctness",
            },
            "r3_projection_artifact_sha256": hashlib.sha256(r3_bytes).hexdigest(),
            "evaluator_scope": "R4 independently verifies stop-to-board mapping and Scatter masses against hash-bound R3 exact payout distributions; evaluator parity is carried from the hash-matched R2 independent crosscheck, not recomputed here",
        },
        "known_and_blocked_domains": {
            "BASE_scatter_0_to_2": "DRAFT_PAYOUT_ONLY; NO_FEATURE_AWARD",
            "BASE_scatter_exactly_3": "DRAFT_PAYOUT_ONLY_PLUS_EXACTLY_10_FREE_SPINS",
            "BASE_scatter_4_plus": "UNRESOLVED; EXCLUDED_FROM_FULL_ROUND_METRICS",
            "FREE_SPINS_scatter_0_to_2": "DRAFT_PAYOUT_ONLY; NO_RETRIGGER",
            "FREE_SPINS_scatter_3_plus": "UNRESOLVED_RETRIGGER; EXCLUDED_FROM_FULL_ROUND_METRICS",
            "MAGIC_BUY": "UNSUPPORTED_NO_APPROVED_PRICE_OR_PROBABILITY_MODEL",
            "EPIC_BUY": "UNSUPPORTED_NO_APPROVED_PRICE_OR_PROBABILITY_MODEL",
            "wild_expansion": "DRAFT_ONLY_NOT_CANONICAL_OR_APPROVED",
            "multiplier": "DRAFT_ONLY_NOT_CANONICAL_OR_APPROVED",
        },
        "probability_mass": {
            "BASE_4_plus_scatter_excluded": _fraction(Fraction(total_mass - base_valid_mass, total_mass)),
            "BASE_exact_three_trigger_unconditional": _fraction(Fraction(base_exact_three_mass, total_mass)),
            "BASE_exact_three_trigger_conditional_on_base_0_to_3": _fraction(Fraction(base_exact_three_mass, base_valid_mass)),
            "FREE_SPINS_3_plus_scatter_excluded_per_spin": _fraction(Fraction(total_mass - free_valid_mass, total_mass)),
            "at_least_one_blocked_free_spin_in_ten_independent_spins": _fraction(1 - Fraction(free_valid_mass, total_mass) ** 10),
        },
        "maximum_payout_path": {
            "max_base_payout_on_exact_three_scatter_milli": max_base_payout,
            "max_base_payout_on_zero_to_two_scatter_milli": max_base_no_feature_payout,
            "max_free_spin_payout_on_zero_to_two_scatter_milli": max_free_payout,
            "max_round_raw_sum_milli": max_round_raw,
            "maximum_raw_payout_across_known_round_paths_milli": max_round_raw_overall,
            "max_round_payout_after_cap_milli": max_round_payout,
            "max_round_payout_x_of_base_wager": max_round_payout / 1000,
            "round_cap_saturated": cap_saturated,
            "path_has_nonzero_weight_mass": max_base_mass > 0 and max_free_mass > 0,
            "path_probability_scopes": path_scopes,
            "maximum_payout_frequency_interpretation": max_frequency_scope,
            "provider_payment_capability": "UNVERIFIED",
            "50_000x_reachable_under_current_draft_spin_limits": max_round_payout >= 50_000_000,
        },
        "probability_assumptions_and_limits": [
            "Per-round exact probability calculations assume independent weighted reel stops; each stop-vector mass is the product of five configured reel weights.",
            "The ten Free Spins are modeled as independent draws from the configured Draft stop distribution, conditioned to 0-2 Scatter only for conditional metrics.",
            "HMAC-SHA256 rejection sampling is a deterministic Draft RNG implementation; production entropy, key custody, canonical RNG version and Provider seed contract are not certified by this audit.",
            "Blocked Scatter/retrigger domains retain explicit excluded probability mass; no payout or feature rule is assigned to those domains.",
            "No Canonical RTP, volatility, Buy-mode RTP, 50,000x reachability or Provider payment claim is made.",
        ],
        "source_hashes_sha256": source_hashes,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=REPORT,
                        help="new report path; existing report and SHA files are never overwritten")
    args = parser.parse_args()
    target = args.output if args.output.is_absolute() else ROOT / args.output
    target_hash = target.with_suffix(target.suffix + ".sha256")
    if target.exists() or target_hash.exists():
        raise SystemExit("refusing to overwrite existing evidence: %s or %s" % (target, target_hash))
    result = audit()
    payload = (json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    with target.open("xb") as handle:
        handle.write(payload)
    with target_hash.open("x", encoding="ascii") as handle:
        handle.write("%s  %s\n" % (digest, target.name))
    print(json.dumps({
        "status": result["status"],
        "report": str(target),
        "report_sha256": digest,
        "stop_vectors_per_mode": result["draft_model"]["stop_vectors_per_mode"],
        "mapping_mismatches": len(result["independent_mapping_and_evaluator"]["mapping_mismatches"]),
        "r2_independent_evaluator_crosscheck": result["independent_mapping_and_evaluator"]["r2_independent_evaluator_crosscheck"],
        "maximum_payout_x": result["maximum_payout_path"]["max_round_payout_x_of_base_wager"],
        "maximum_path_probability_scopes": result["maximum_payout_path"]["path_probability_scopes"],
    }, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["status"] == "PASS_DRAFT_ONLY_WITH_UNRESOLVED_FEATURE_DOMAINS" else 2)


if __name__ == "__main__":
    main()
