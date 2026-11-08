"""Exhaustively cross-check the quarantined draft evaluator against the independent reference.

The result is engineering evidence for the supplied draft inputs only. It is not
canonical Math, RTP approval, Provider Golden Vector evidence or Stake submission data.
"""
import hashlib
import itertools
import json
from pathlib import Path

from ganesha.math.config import (CONFIG, PAYLINES, PAYOUT_SCALE_DENOMINATOR,
                                 PAYOUT_SCALE_NUMERATOR, PAYTABLE_MILLI,
                                 REEL_STRIPS, SCATTER, WILD)
from ganesha.math.engine import UnspecifiedMathRule, board_from_stops, evaluate_board
from ganesha.math.reference import UnspecifiedReferenceRule, evaluate_board as reference_board
from ganesha.math.artifact_writers import write_crosscheck_report

ROOT = Path(__file__).resolve().parents[1]


def reference(board, mode):
    expanded = [i for i, reel in enumerate(board) if WILD in reel] if mode == "FREE_SPINS" else []
    multiplier = 1
    if expanded:
        multiplier = min(CONFIG.feature_rules.free_spin_wild_reel_multiplier ** len(expanded)
                         * (2 if len(expanded) == 5 else 1),
                         CONFIG.feature_rules.max_wild_reel_multiplier)
    return reference_board(
        board, paylines=PAYLINES, paytable_milli=PAYTABLE_MILLI,
        wild_symbol=WILD, scatter_symbol=SCATTER, mode=mode,
        wild_expansion_reels=expanded, wild_multiplier=multiplier,
        scale_numerator=PAYOUT_SCALE_NUMERATOR,
        scale_denominator=PAYOUT_SCALE_DENOMINATOR,
        payout_cap_milli=CONFIG.max_win_milli,
    )


def main():
    modes = {"BASE": {"checked": 0, "unspecified": 0},
             "FREE_SPINS": {"checked": 0, "unspecified": 0}}
    mismatches = []
    for stops in itertools.product(*(range(len(strip)) for strip in REEL_STRIPS)):
        board = board_from_stops(stops)
        for mode in modes:
            try:
                expected = evaluate_board(board, mode)
            except UnspecifiedMathRule:
                try:
                    reference(board, mode)
                except UnspecifiedReferenceRule:
                    modes[mode]["unspecified"] += 1
                    continue
                mismatches.append({"stops": stops, "mode": mode,
                                   "error": "engine blocked but reference did not"})
                continue
            try:
                actual = reference(board, mode)
            except Exception as exc:
                mismatches.append({"stops": stops, "mode": mode,
                                   "error": "reference raised " + type(exc).__name__})
                continue
            modes[mode]["checked"] += 1
            if expected != actual:
                mismatches.append({"stops": stops, "mode": mode,
                                   "engine": expected, "reference": actual})
                if len(mismatches) >= 10:
                    break
        if len(mismatches) >= 10:
            break

    config_paths = ("src/ganesha/math/config.py", "src/ganesha/math/engine.py",
                    "src/ganesha/math/reference.py", "tools/math_reference_crosscheck.py")
    source_hashes = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                     for name in config_paths}
    result = {
        "schema": "ganesha-draft-math-independent-crosscheck.v1",
        "status": "PASS_DRAFT_ONLY" if not mismatches else "FAIL",
        "canonical_math": False,
        "provider_approved": False,
        "rtp_claim_permitted": False,
        "stake_upload_permitted": False,
        "source_hashes": source_hashes,
        "stop_vectors_total": 1,
        "modes": modes,
        "mismatches": mismatches,
        "scope": "Exhaustive deterministic equivalence of the current quarantined draft evaluator to a separately implemented reference using the same explicitly supplied draft inputs. It does not establish canonical correctness, approved probabilities, RTP, maximum-win reachability or Provider acceptance.",
    }
    result["stop_vectors_total"] = 1
    for strip in REEL_STRIPS:
        result["stop_vectors_total"] *= len(strip)
    output = write_crosscheck_report(
        result, ROOT / "artifacts/DRAFT_MATH_INDEPENDENT_CROSSCHECK_20261104_R2_draft_only.json")
    print(json.dumps(json.loads(output.read_text(encoding="utf-8")), indent=2, sort_keys=True))
    if mismatches:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
