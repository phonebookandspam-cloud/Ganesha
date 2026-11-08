"""Quarantined output adapters for the three historical Math report types."""
from pathlib import Path
from typing import Any, Mapping, Union

from .artifact_quarantine import write_quarantined_json

EXACT_SCOPE = (
    "Fail-closed full-round Math report. Unspecified 4+ Scatter, Free Spins retrigger, "
    "Buy terms and jackpot policy block RTP/EV/variance output; no metrics are computed."
)
MONTE_CARLO_SCOPE = (
    "Fail-closed Monte Carlo report. No simulation is run while canonical inputs and "
    "complete approved feature/Buy rules are unavailable."
)
CROSSCHECK_SCOPE = (
    "Independent evaluator/reference comparison over resolved unapproved Draft inputs only; "
    "blocked outcomes, canonical correctness, RTP and rare-tail risk remain unverified."
)


def write_exact_report(payload: Mapping[str, Any], path: Union[str, Path] = "artifacts/math_audit_v1_draft_only.json") -> Path:
    return write_quarantined_json(path, payload, scope=EXACT_SCOPE)


def write_monte_carlo_report(payload: Mapping[str, Any], path: Union[str, Path] = "artifacts/monte_carlo_v1_draft_only.json") -> Path:
    return write_quarantined_json(path, payload, scope=MONTE_CARLO_SCOPE)


def write_crosscheck_report(payload: Mapping[str, Any], path: Union[str, Path] = "artifacts/math_crosscheck_v1_draft_only.json") -> Path:
    return write_quarantined_json(path, payload, scope=CROSSCHECK_SCOPE)
