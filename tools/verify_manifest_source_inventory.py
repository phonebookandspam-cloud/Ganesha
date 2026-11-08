"""Verify a release manifest's source inventory against an exact Git tree."""
import hashlib
import re
import subprocess
from pathlib import Path


def verify_manifest_source_inventory(root, commit, source_files):
    """Return (ok, reason), hashing committed blobs rather than worktree files."""
    root = Path(root).resolve()
    if not isinstance(source_files, dict):
        return False, "manifest source_files is not an object"
    try:
        tree = subprocess.check_output(
            ["git", "ls-tree", "-r", "-z", "--full-tree", commit],
            cwd=str(root), stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return False, "exact source commit tree is unavailable"

    entries = {}
    try:
        for record in tree.split(b"\0"):
            if not record:
                continue
            header, raw_path = record.split(b"\t", 1)
            mode, object_type, object_id = header.decode("ascii").split(" ")
            path = raw_path.decode("utf-8")
            if mode not in ("100644", "100755") or object_type != "blob":
                return False, "exact source commit contains a non-regular source entry"
            entries[path] = object_id
    except (UnicodeDecodeError, ValueError):
        return False, "exact source commit tree contains an unsupported path entry"

    if set(source_files) != set(entries):
        return False, "manifest source path set does not equal the exact source commit tree"
    if any(re.fullmatch(r"[0-9a-f]{64}", str(digest)) is None for digest in source_files.values()):
        return False, "manifest source inventory contains an invalid SHA-256"

    request = b"".join(object_id.encode("ascii") + b"\n" for object_id in entries.values())
    try:
        response = subprocess.check_output(
            ["git", "cat-file", "--batch"], cwd=str(root), input=request,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return False, "exact source commit blobs are unavailable"

    offset = 0
    for path, object_id in entries.items():
        header_end = response.find(b"\n", offset)
        if header_end < 0:
            return False, "Git returned a truncated source blob batch"
        header = response[offset:header_end].split()
        if len(header) != 3 or header[0].decode("ascii", "replace") != object_id or header[1] != b"blob":
            return False, "Git returned an unexpected source blob object"
        try:
            size = int(header[2])
        except ValueError:
            return False, "Git returned an invalid source blob size"
        offset = header_end + 1
        blob = response[offset:offset + size]
        if len(blob) != size or response[offset + size:offset + size + 1] != b"\n":
            return False, "Git returned a truncated source blob"
        if hashlib.sha256(blob).hexdigest() != source_files[path]:
            return False, "manifest source hash does not match exact commit blob: %s" % path
        offset += size + 1
    return True, "manifest source paths and SHA-256 values match exact commit blobs"
