#!/usr/bin/env python3
"""Read-only completeness verification for the Ganesha CycloneDX SBOM.

This verifier deliberately does not import or call the SBOM generator. It checks
an explicit SBOM against the npm lockfile, pinned Python build requirements,
asset provenance inventory, and bytes currently shipped under frontend/assets.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_WAVS = {
    "sfx/free-spins.wav",
    "sfx/reel-stop.wav",
    "sfx/wild-expansion.wav",
    "sfx/win.wav",
}


class SBOMCompletenessError(ValueError):
    """The SBOM or its source inventory is incomplete or inconsistent."""


def _read_json(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SBOMCompletenessError(f"cannot read {label}: {path}: {exc}") from exc


def _pypi_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _expected_npm(lock: dict[str, Any]) -> dict[str, tuple[str, str]]:
    if lock.get("lockfileVersion") != 3 or not isinstance(lock.get("packages"), dict):
        raise SBOMCompletenessError("package-lock.json must use lockfileVersion 3 and contain packages")
    expected: dict[str, tuple[str, str]] = {}
    for package_path, package in lock["packages"].items():
        if package_path == "":
            continue
        if not isinstance(package_path, str) or not isinstance(package, dict):
            raise SBOMCompletenessError(f"invalid npm lock entry: {package_path!r}")
        parts = PurePosixPath(package_path).parts
        markers = [i for i, part in enumerate(parts) if part == "node_modules"]
        if not markers:
            raise SBOMCompletenessError(f"npm lock package path is not under node_modules: {package_path}")
        name = "/".join(parts[markers[-1] + 1:])
        version = package.get("version")
        if not name or not isinstance(version, str) or not version:
            raise SBOMCompletenessError(f"invalid npm lock package name/version: {package_path}")
        encoded_name = name.replace("@", "%40", 1) if name.startswith("@") else name
        purl = f"pkg:npm/{encoded_name}@{version}"
        prior = expected.get(purl)
        identity = (name, version)
        if prior is not None and prior != identity:
            raise SBOMCompletenessError(f"conflicting npm lock identities for {purl}")
        expected[purl] = identity
    if not expected:
        raise SBOMCompletenessError("npm lockfile contains no non-root packages")
    return expected


def _expected_python(requirements_path: Path) -> dict[str, tuple[str, str]]:
    expected: dict[str, tuple[str, str]] = {}
    try:
        lines = requirements_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise SBOMCompletenessError(f"cannot read pinned Python build requirements: {exc}") from exc
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+-]+)", line)
        if not match:
            raise SBOMCompletenessError(f"Python build dependency must be exactly pinned: {line}")
        name, version = match.groups()
        purl = f"pkg:pypi/{_pypi_name(name)}@{version}"
        expected[purl] = (name, version)
    if not expected:
        raise SBOMCompletenessError("no pinned Python build dependencies found")
    return expected


def _hash_entry(component: dict[str, Any], algorithm: str, digest: str, label: str) -> None:
    hashes = component.get("hashes")
    if not isinstance(hashes, list) or not any(
        isinstance(item, dict)
        and isinstance(item.get("alg"), str)
        and item["alg"].upper().replace("-", "") == algorithm.upper().replace("-", "")
        and isinstance(item.get("content"), str)
        and item["content"].lower() == digest.lower()
        for item in hashes
    ):
        raise SBOMCompletenessError(f"{label} is missing its matching {algorithm} content hash")


def _component_index(sbom: dict[str, Any]) -> dict[str, dict[str, Any]]:
    components = sbom.get("components")
    if not isinstance(components, list):
        raise SBOMCompletenessError("SBOM components must be an array")
    by_ref: dict[str, dict[str, Any]] = {}
    for component in components:
        if not isinstance(component, dict):
            raise SBOMCompletenessError("SBOM component entry must be an object")
        ref = component.get("bom-ref")
        if not isinstance(ref, str) or not ref:
            raise SBOMCompletenessError("SBOM component is missing bom-ref")
        if ref in by_ref:
            raise SBOMCompletenessError(f"duplicate SBOM bom-ref: {ref}")
        by_ref[ref] = component
    return by_ref


def verify_sbom(sbom_path: Path | str, root: Path | str = ROOT) -> dict[str, int]:
    """Verify an SBOM file against source inventories; never writes files."""
    root = Path(root).resolve()
    requested_sbom_path = Path(sbom_path)
    if requested_sbom_path.is_symlink():
        raise SBOMCompletenessError(f"SBOM path must not be a symlink: {requested_sbom_path}")
    sbom_path = requested_sbom_path.resolve()
    if not sbom_path.is_file():
        raise SBOMCompletenessError(f"SBOM path must be an existing regular file: {sbom_path}")
    sbom = _read_json(sbom_path, "SBOM")
    if not isinstance(sbom, dict) or sbom.get("bomFormat") != "CycloneDX":
        raise SBOMCompletenessError("SBOM root must be a CycloneDX object")
    if sbom.get("specVersion") != "1.5":
        raise SBOMCompletenessError("SBOM specVersion must be 1.5")
    by_ref = _component_index(sbom)

    lock = _read_json(root / "package-lock.json", "npm lockfile")
    if not isinstance(lock, dict):
        raise SBOMCompletenessError("npm lockfile root must be an object")
    expected_npm = _expected_npm(lock)
    expected_python_build = _expected_python(root / "requirements-build.txt")
    expected_python_test = _expected_python(root / "requirements-test.txt")

    missing_npm = sorted(set(expected_npm) - set(by_ref))
    if missing_npm:
        raise SBOMCompletenessError(
            f"SBOM omits {len(missing_npm)} locked npm components: " + ", ".join(missing_npm[:8])
        )
    for purl, (name, version) in expected_npm.items():
        component = by_ref[purl]
        if component.get("purl") != purl or component.get("name") != name or component.get("version") != version:
            raise SBOMCompletenessError(f"npm component identity mismatch for {purl}")

    missing_python_build = sorted(set(expected_python_build) - set(by_ref))
    if missing_python_build:
        raise SBOMCompletenessError(
            f"SBOM omits {len(missing_python_build)} pinned Python build components: " + ", ".join(missing_python_build)
        )
    for purl, (name, version) in expected_python_build.items():
        component = by_ref[purl]
        if component.get("purl") != purl or component.get("name") != name or component.get("version") != version:
            raise SBOMCompletenessError(f"Python build component identity mismatch for {purl}")

    missing_python_test = sorted(set(expected_python_test) - set(by_ref))
    if missing_python_test:
        raise SBOMCompletenessError(
            f"SBOM omits {len(missing_python_test)} pinned Python test components: " + ", ".join(missing_python_test)
        )
    for purl, (name, version) in expected_python_test.items():
        component = by_ref[purl]
        if component.get("purl") != purl or component.get("name") != name or component.get("version") != version:
            raise SBOMCompletenessError(f"Python test component identity mismatch for {purl}")

    assets_dir = root / "frontend" / "assets"
    manifest_path = assets_dir / "ASSET_PROVENANCE.json"
    manifest = _read_json(manifest_path, "asset provenance manifest")
    assets = manifest.get("assets") if isinstance(manifest, dict) else None
    if not isinstance(assets, list):
        raise SBOMCompletenessError("asset provenance manifest must contain an assets array")

    manifest_files: set[str] = set()
    expected_assets: dict[str, tuple[str, int]] = {}
    for asset in assets:
        if not isinstance(asset, dict) or not isinstance(asset.get("file"), str):
            raise SBOMCompletenessError("asset provenance entry must contain a file path")
        filename = asset["file"]
        rel = PurePosixPath(filename)
        if rel.is_absolute() or ".." in rel.parts or filename in manifest_files:
            raise SBOMCompletenessError(f"unsafe or duplicate asset provenance path: {filename}")
        manifest_files.add(filename)
        path = assets_dir.joinpath(*rel.parts)
        cursor = assets_dir
        has_symlink_parent = False
        for part in rel.parts:
            cursor = cursor / part
            has_symlink_parent = has_symlink_parent or cursor.is_symlink()
        if (not path.is_file() or has_symlink_parent
                or assets_dir.resolve() not in path.resolve().parents):
            raise SBOMCompletenessError(f"shipped asset is missing, symlinked or escapes assets root: {filename}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        size = path.stat().st_size
        if asset.get("sha256") != digest or asset.get("bytes") != size:
            raise SBOMCompletenessError(f"asset provenance hash/size mismatch: {filename}")
        expected_assets[filename] = (digest, size)

    disk_files = {
        path.relative_to(assets_dir).as_posix()
        for path in assets_dir.rglob("*")
        if path.is_file() and path.name != "ASSET_PROVENANCE.json"
    }
    if disk_files != manifest_files:
        unlisted = sorted(disk_files - manifest_files)
        absent = sorted(manifest_files - disk_files)
        raise SBOMCompletenessError(
            f"asset provenance does not enumerate exact shipped asset inventory; unlisted={unlisted}, absent={absent}"
        )
    missing_wavs = sorted(REQUIRED_WAVS - manifest_files)
    if missing_wavs:
        raise SBOMCompletenessError("asset provenance omits required WAV assets: " + ", ".join(missing_wavs))

    for filename, (digest, _size) in expected_assets.items():
        ref = "urn:sha256:" + digest
        component = by_ref.get(ref)
        if component is None:
            raise SBOMCompletenessError(f"SBOM omits shipped asset: {filename}")
        if component.get("type") != "file" or component.get("name") != filename:
            raise SBOMCompletenessError(f"SBOM asset identity mismatch: {filename}")
        _hash_entry(component, "SHA-256", digest, f"asset {filename}")

    return {
        "npm_components": len(expected_npm),
        "python_build_components": len(expected_python_build),
        "python_test_components": len(expected_python_test),
        "shipped_assets": len(expected_assets),
        "required_wavs": len(REQUIRED_WAVS),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sbom", required=True, help="explicit path to the CycloneDX SBOM JSON file")
    parser.add_argument("--root", default=str(ROOT), help="workspace root containing package-lock.json and frontend/assets")
    args = parser.parse_args(argv)
    try:
        counts = verify_sbom(args.sbom, args.root)
    except SBOMCompletenessError as exc:
        print(f"SBOM_COMPLETENESS=FAIL: {exc}", file=sys.stderr)
        return 2
    print("SBOM_COMPLETENESS=PASS")
    for key, value in counts.items():
        print(f"{key.upper()}={value}")
    print(f"SBOM={Path(args.sbom).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
