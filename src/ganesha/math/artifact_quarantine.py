"""Fail-closed writer for hypothetical Math research artifacts.

Release-facing artifact names are reserved. Draft calculations may only be
written beneath an artifacts/ directory to explicitly named *_draft_only.json
files, and every payload is stamped before the atomic replace.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping, Union

RELEASE_STATUS = "SUPERSEDED_NOT_RELEASE_EVIDENCE"
PROTECTED_RELEASE_NAMES = frozenset({
    "math_audit_v1.json",
    "math_crosscheck_v1.json",
    "monte_carlo_v1.json",
})


def write_quarantined_json(path: Union[str, Path], payload: Mapping[str, Any], *, scope: str) -> Path:
    """Atomically write a permanently quarantined draft artifact.

    Refuses paths that could be mistaken for release evidence. The target must
    be a regular, non-symlink JSON file named *_draft_only.json directly inside
    an artifacts directory. The input mapping is copied; caller data is not
    mutated.
    """
    target = Path(path)
    if target.name in PROTECTED_RELEASE_NAMES:
        raise ValueError(f"refusing to overwrite protected release artifact: {target.name}")
    if target.suffix != ".json" or not target.name.endswith("_draft_only.json"):
        raise ValueError("draft Math output must be named *_draft_only.json")
    if target.parent.name != "artifacts":
        raise ValueError("draft Math output must be written directly inside an artifacts/ directory")
    if target.is_symlink():
        raise ValueError("refusing to write through a symlink")
    if target.exists():
        raise ValueError(f"refusing to overwrite existing draft artifact: {target}")
    if not isinstance(payload, Mapping):
        raise TypeError("quarantined artifact payload must be a mapping")
    if not isinstance(scope, str) or not scope.strip():
        raise ValueError("a non-empty draft scope is required")

    stamped = dict(payload)
    stamped.update({
        "release_status": RELEASE_STATUS,
        "public_claims_permitted": False,
        "scope": scope.strip(),
    })
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(stamped, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        # Hard-link publication is atomic and fails if the destination appeared
        # after the preflight; unlike os.replace it cannot overwrite an artifact.
        os.link(temporary_name, target)
        os.unlink(temporary_name)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise
    return target
