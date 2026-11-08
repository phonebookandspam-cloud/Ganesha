#!/usr/bin/env python3
"""Verify Ed25519 signature, trusted-key fingerprint, source commit and artifact hashes."""
import argparse
import hashlib
import json
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


def require_openssl3():
    version = subprocess.check_output(["openssl", "version"], text=True).strip()
    if not version.startswith("OpenSSL 3."):
        raise SystemExit("OpenSSL 3.x is required for Ed25519 verification; detected: %s" % version)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--signature", required=True)
    parser.add_argument("--public-key", required=True)
    parser.add_argument("--trusted-key-sha256", required=True)
    args = parser.parse_args()
    require_openssl3()
    manifest_path, signature, public_key = map(Path, (args.manifest, args.signature, args.public_key))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != "ganesha-release-manifest.v1":
        raise SystemExit("Unsupported release manifest schema")
    fingerprint = hashlib.sha256(subprocess.check_output(
        ["openssl", "pkey", "-pubin", "-in", str(public_key), "-outform", "DER"])).hexdigest()
    if fingerprint != args.trusted_key_sha256:
        raise SystemExit("Public key fingerprint is not the approved trust anchor")
    subprocess.check_call(["openssl", "pkeyutl", "-verify", "-rawin", "-pubin", "-inkey", str(public_key),
                           "-sigfile", str(signature), "-in", str(manifest_path)])
    if manifest.get("source_commit") != git("rev-parse", "HEAD"):
        raise SystemExit("Manifest source commit does not equal current checkout HEAD")
    if manifest.get("source_tree") != git("rev-parse", "HEAD^{tree}"):
        raise SystemExit("Manifest source tree does not equal current checkout tree")
    if git("status", "--porcelain"):
        raise SystemExit("Refusing to verify release bundle against a dirty checkout")
    tracked = set(git("ls-files").splitlines())
    manifested_sources = set(manifest.get("source_files", {}))
    if tracked != manifested_sources:
        raise SystemExit("Manifest source-file set does not equal the tracked repository source set")
    for rel, expected in manifest.get("source_files", {}).items():
        path = (ROOT / rel).resolve()
        if ROOT not in path.parents or not path.is_file() or (ROOT / rel).is_symlink() or sha256(path) != expected:
            raise SystemExit("Source file hash mismatch: %s" % rel)
    for rel, expected in manifest.get("artifacts", {}).items():
        path = ROOT / rel
        if ROOT not in path.resolve().parents or path.is_symlink():
            raise SystemExit("Artifact path escapes repository root: %s" % rel)
        if not path.is_file() or sha256(path) != expected.get("sha256") or path.stat().st_size != expected.get("size_bytes"):
            raise SystemExit("Artifact hash/size mismatch: %s" % rel)
    sbom_names = [rel for rel in manifest.get("artifacts", {}) if "sbom" in rel.lower()]
    if len(sbom_names) != 1:
        raise SystemExit("Manifest must contain exactly one SBOM")
    sbom = json.loads((ROOT / sbom_names[0]).read_text(encoding="utf-8"))
    try:
        validate_sbom_document(sbom)
    except ValueError as exc:
        raise SystemExit("SBOM is incomplete or does not match the current source inventory: %s" % exc)
    source_properties = {item.get("name"): item.get("value") for item in sbom.get("metadata", {}).get("properties", [])}
    if source_properties.get("ganesha.source.commit") != manifest["source_commit"]:
        raise SystemExit("SBOM source commit does not match the release manifest")
    print("SIGNATURE=PASS")
    print("TRUSTED_KEY_SHA256=%s" % fingerprint)
    print("SOURCE_COMMIT=%s" % manifest["source_commit"])
    print("SOURCE_FILES=%d" % len(manifest.get("source_files", {})))
    print("ARTIFACTS=%d" % len(manifest.get("artifacts", {})))


if __name__ == "__main__":
    main()
