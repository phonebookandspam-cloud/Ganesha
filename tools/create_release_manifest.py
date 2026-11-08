#!/usr/bin/env python3
"""Create an unsigned source/artifact manifest. Signing is a separate owner-controlled step."""
import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.generate_sbom import validate_sbom_document


def git(*args):
    return subprocess.check_output(["git", *args], cwd=str(ROOT), text=True).strip()


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--artifact", action="append", default=[])
    args = parser.parse_args()
    if git("status", "--porcelain"):
        raise SystemExit("Refusing to manifest a dirty or untracked source checkout")
    commit = git("rev-parse", "HEAD")
    tracked = git("ls-files").splitlines()
    sources = {}
    for rel in tracked:
        source_path = (ROOT / rel).resolve()
        if ROOT not in source_path.parents or not source_path.is_file() or (ROOT / rel).is_symlink():
            raise SystemExit("Tracked source path is missing, symlinked or escapes repository root: %s" % rel)
        sources[rel] = sha256(source_path)
    artifacts = {}
    for value in args.artifact:
        path = (ROOT / value).resolve()
        if ROOT not in path.parents or not path.is_file() or path.is_symlink():
            raise SystemExit("Artifact must be an existing file inside the repository: %s" % value)
        rel = path.relative_to(ROOT).as_posix()
        artifacts[rel] = {"sha256": sha256(path), "size_bytes": path.stat().st_size}
    wheel_names = [name for name in artifacts if name.endswith(".whl")]
    sdist_names = [name for name in artifacts if name.endswith(".tar.gz")]
    if len(wheel_names) != 1 or len(sdist_names) != 1:
        raise SystemExit("Manifest requires exactly one wheel and one source distribution artifact")
    sbom_names = [name for name in artifacts if "sbom" in name.lower()]
    if len(sbom_names) != 1:
        raise SystemExit("Manifest requires a generated SBOM artifact")
    sbom = json.loads((ROOT / sbom_names[0]).read_text(encoding="utf-8"))
    try:
        validate_sbom_document(sbom)
    except ValueError as exc:
        raise SystemExit("SBOM is incomplete or does not match the exact source inventory: %s" % exc)
    source_properties = {item.get("name"): item.get("value") for item in sbom.get("metadata", {}).get("properties", [])}
    if source_properties.get("ganesha.source.commit") != commit:
        raise SystemExit("SBOM must be bound to the exact source commit")
    evidence_path = ROOT / "artifacts/BUILD_REPRODUCIBILITY_20261103.json"
    if not evidence_path.is_file():
        raise SystemExit("Source-bound two-clean-clone build evidence is required")
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence_sources = dict(sources)
    evidence_sources.pop("artifacts/BUILD_REPRODUCIBILITY_20261103.json", None)
    tested_commit = evidence.get("tested_commit", "")
    if (evidence.get("schema") != "ganesha-build-reproducibility.v1"
            or not re.fullmatch(r"[0-9a-f]{40}", str(tested_commit))
            or any(evidence.get(field) != tested_commit for field in ("clean_clone_test_commit", "source_manifest_commit"))
            or evidence.get("source_manifest") != evidence_sources
            or evidence.get("source_manifest_entries") != len(evidence_sources)
            or evidence.get("clean_clone_test_status") != "PASS"
            or evidence.get("clean_clone_count") != 2
            or evidence.get("two_clean_clone_builds_byte_identical") is not True
            or not subprocess.run(["git", "merge-base", "--is-ancestor", tested_commit, commit],
                                  cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0):
        raise SystemExit("Build evidence does not match the current tracked source snapshot")
    if sha256(ROOT / wheel_names[0]) != evidence.get("wheel_sha256"):
        raise SystemExit("Built wheel bytes do not match the two-clean-clone reproducibility evidence")
    if sha256(ROOT / sdist_names[0]) != evidence.get("sdist_sha256"):
        raise SystemExit("Built sdist bytes do not match the two-clean-clone reproducibility evidence")
    manifest = {
        "schema": "ganesha-release-manifest.v1",
        "source_commit": commit,
        "source_tree": git("rev-parse", "HEAD^{tree}"),
        "source_date_epoch": int(git("log", "-1", "--format=%ct")),
        "source_files": sources,
        "artifacts": artifacts,
        "build_reproducibility_evidence_sha256": sha256(evidence_path),
    }
    output = (ROOT / args.output).resolve()
    if ROOT not in output.parents:
        raise SystemExit("Output must remain inside the repository")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("MANIFEST=%s" % output)
    print("SOURCE_COMMIT=%s" % commit)
    print("SOURCE_FILES=%d" % len(sources))
    print("ARTIFACTS=%d" % len(artifacts))
    print("STATUS=UNSIGNED_REQUIRES_OWNER_KEY_AND_TRUST_ANCHOR")


if __name__ == "__main__":
    main()
