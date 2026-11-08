#!/usr/bin/env python3
"""Build exact conditional Draft BASE/10-Free-Spins distribution evidence."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ganesha.math.draft_round_projection import build_conditional_draft_round_projection

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "artifacts/DRAFT_CONDITIONAL_ROUND_EXACT_20261104_R3_draft_only.json"


def main() -> None:
    if TARGET.exists():
        raise SystemExit("refusing to overwrite existing artifact: " + str(TARGET))
    report = build_conditional_draft_round_projection()
    source_paths = (
        "src/ganesha/math/config.py", "src/ganesha/math/engine.py",
        "src/ganesha/math/reference.py", "src/ganesha/math/draft_distribution.py",
        "src/ganesha/math/draft_round_projection.py", "src/ganesha/game/engine.py",
        "src/ganesha/game/math_port.py", "src/ganesha/rgs/service.py",
        "src/ganesha/wallet/ledger.py", "tools/audit_draft_conditional_round.py",
    )
    report["source_hashes"] = {
        path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
        for path in source_paths
    }
    report["artifact_status"] = "DRAFT_ONLY_NOT_CANONICAL_NOT_PROVIDER_APPROVED"
    report["supersedes"] = {
        "artifacts": [
            "DRAFT_CONDITIONAL_ROUND_EXACT_20261104_R1_draft_only.json",
            "DRAFT_CONDITIONAL_ROUND_EXACT_20261104_R2_draft_only.json",
        ],
        "reason": "R1 CLI summary formatting failed after JSON write; R2 reported exact-convolution metadata after distribution quantiles had been switched to Monte Carlo. R3 corrects provenance and labels exact moments separately from sampled quantiles/CVaR.",
    }
    TARGET.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "base": report["base_spin"]["return_percent_of_one_base_wager"],
        "fs_one": report["free_spin_one_spin"]["mean_payout_x_of_base_wager"],
        "fs_ten": report["free_spins_10_cumulative"]["exact_mean_payout_x_of_base_wager"],
        "conditional_round_return_percent_not_canonical_rtp": report["conditional_base_round"]["exact_return_percent_of_one_base_wager"],
        "excluded_base_4plus": report["excluded_probability_mass"]["BASE_4_plus_scatter"],
        "blocked_fs_3plus_per_spin": report["excluded_probability_mass"]["FREE_SPINS_3_plus_scatter_per_spin"],
        "max_round_x": report["maximum_payout_reachability"]["max_round_payout_mathematically_in_conditional_model_x"],
        "max_path_nonzero": report["maximum_payout_reachability"]["max_round_path_has_nonzero_weight_mass"],
        "path": str(TARGET),
    }, indent=2))


if __name__ == "__main__":
    main()
