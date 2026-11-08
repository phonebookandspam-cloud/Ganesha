"""Shared root-relative source-path exclusions for publication diagnostics."""

from pathlib import PurePosixPath


GENERATED_DIRECTORIES = frozenset({
    ".git", "__pycache__", ".pytest_cache", "build", "dist",
    "frontend-build", "node_modules",
})
GENERATED_NAMES = frozenset({"frontend/config.js"})
IGNORED_SUFFIXES = (
    ".pyc", ".sqlite", ".sqlite-wal", ".sqlite-shm", ".db", "_draft_only.json",
)


def is_excluded_source_path(relative_path):
    """Return whether a repository-relative POSIX path is generated or evidence.

    All checks are deliberately relative to the repository root. In particular,
    callers must not pass ``Path.parts`` from an absolute filesystem path.
    ``artifacts/BASELINE.md`` is a declared source-distribution input and is
    therefore required, unlike other paths beneath ``artifacts/``.
    """
    relative = PurePosixPath(str(relative_path))
    if relative.is_absolute() or ".." in relative.parts or "\\" in str(relative_path):
        return False
    return (
        any(part in GENERATED_DIRECTORIES for part in relative.parts)
        or relative.as_posix().startswith("qa/work_20261106_submission_repair_r1/")
        or any(part.endswith(".egg-info") for part in relative.parts)
        or (relative.as_posix().startswith("artifacts/")
            and relative.as_posix() != "artifacts/BASELINE.md")
        or relative.as_posix() in GENERATED_NAMES
        or relative.name == ".DS_Store"
        or relative.as_posix().endswith(IGNORED_SUFFIXES)
    )


def is_excluded_artifact_path(relative_path):
    """Backward-compatible artifact-only predicate; prefer the full policy."""
    relative = PurePosixPath(str(relative_path)).as_posix()
    return (
        relative.startswith("artifacts/")
        and is_excluded_source_path(relative)
    )
