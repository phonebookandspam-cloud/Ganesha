"""Read-only diagnostic for the publication gate's source-path policy.

This tool does not stage files, modify registration lists, or authorize exclusions.
Only explicitly named frontend build snapshots with a complete byte-verified
integrity manifest are treated as generated output, matching qa_release_gate.py.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path, PurePosixPath

from tools.source_path_policy import is_excluded_source_path

ROOT = Path(__file__).resolve().parent
def _validated_frontend_snapshots(root, snapshot_root):
    """Return roots only when every named snapshot passes the gate's exact check."""
    if not snapshot_root.exists():
        return set()
    if snapshot_root.is_symlink() or not snapshot_root.is_dir():
        return set()
    namespace_entries = sorted(snapshot_root.iterdir())
    if any(item.is_symlink() for item in namespace_entries):
        return set()
    snapshots = [item for item in namespace_entries
                 if item.is_dir() and item.name.startswith("FRONTEND_BUILD_")]
    roots = set()
    for snapshot in snapshots:
        manifest_path = snapshot / "snapshot.integrity.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return set()
        if (not isinstance(manifest, dict)
                or manifest.get("schema") != "ganesha.generated-frontend-snapshot-integrity.v1"
                or manifest.get("snapshot") != snapshot.relative_to(root).as_posix()
                or not isinstance(manifest.get("files"), list)):
            return set()
        declared = {}
        for entry in manifest["files"]:
            if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
                return set()
            filename = entry["path"]
            relative = PurePosixPath(filename)
            if (not filename or "\\" in filename or relative.is_absolute()
                    or ".." in relative.parts or "." in relative.parts or filename in declared):
                return set()
            path = snapshot.joinpath(*relative.parts)
            cursor = snapshot
            for part in relative.parts:
                cursor = cursor / part
                if cursor.is_symlink():
                    return set()
            if not path.is_file() or snapshot.resolve() not in path.resolve().parents:
                return set()
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if entry.get("sha256") != digest or entry.get("bytes") != path.stat().st_size:
                return set()
            declared[filename] = (digest, path.stat().st_size)
        actual = {}
        for path in snapshot.rglob("*"):
            if path.is_symlink():
                return set()
            if path.is_file() and path.name not in (".DS_Store", "snapshot.integrity.json"):
                rel = path.relative_to(snapshot).as_posix()
                actual[rel] = (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_size)
        if actual != declared:
            return set()
        roots.add(snapshot.relative_to(root).as_posix())
    return roots


def _is_excluded(rel, path):
    return is_excluded_source_path(rel)


def classify_source_completeness(root, tracked_paths):
    """Classify required paths without mutating the worktree or Git index.

    `tracked_missing` are Git-index paths absent from disk. `tracked_invalid`
    are tracked paths present as symlinks or non-regular filesystem objects.
    `untracked_required` are policy-included files or symlink entries present on
    disk but absent from `git ls-files`. Excluded generated/evidence paths are omitted.
    """
    root = Path(root).resolve()
    tracked = {PurePosixPath(str(item)).as_posix() for item in tracked_paths if str(item)}
    tracked_missing = []
    tracked_invalid = []
    for rel in sorted(tracked):
        path = root.joinpath(*PurePosixPath(rel).parts)
        if not path.exists() and not path.is_symlink():
            tracked_missing.append(rel)
        elif path.is_symlink() or not path.is_file():
            tracked_invalid.append(rel)

    validated = _validated_frontend_snapshots(root, root / "frontend/artifacts")
    untracked_required = []
    for path in root.rglob("*"):
        rel = path.relative_to(root).as_posix()
        if _is_excluded(rel, path) or rel in tracked:
            continue
        # pathlib does not recurse into directory symlinks, and is_file() is
        # false for them. Record the link itself instead of silently omitting it.
        if path.is_symlink():
            untracked_required.append(rel)
            continue
        if not path.is_file():
            continue
        if any(rel.startswith(snapshot + "/") for snapshot in validated):
            continue
        untracked_required.append(rel)

    return {
        "pass": not (tracked_missing or tracked_invalid or untracked_required),
        "tracked_missing": tracked_missing,
        "tracked_invalid": tracked_invalid,
        "untracked_required": sorted(untracked_required),
    }


def main():
    try:
        tracked = subprocess.check_output(
            ["git", "ls-files"], cwd=str(ROOT), stderr=subprocess.DEVNULL, text=True
        ).splitlines()
    except (OSError, subprocess.CalledProcessError):
        print(json.dumps({"error": "git ls-files unavailable", "pass": False}, indent=2))
        return 2
    report = classify_source_completeness(ROOT, tracked)
    report["policy"] = "qa_release_gate.py source-path exclusions; verified frontend build snapshots only"
    report["counts"] = {key: len(report[key]) for key in (
        "tracked_missing", "tracked_invalid", "untracked_required"
    )}
    print(json.dumps(report, indent=2))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
