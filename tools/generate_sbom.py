#!/usr/bin/env python3
"""Generate a deterministic CycloneDX 1.5 SBOM for Python/npm dependencies and shipped assets."""
import argparse
import base64
import datetime
import hashlib
import json
import os
import re
import subprocess
import uuid
from pathlib import PurePosixPath
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# SPDX expressions copied from the exact wheel METADATA for the pinned Python
# build/test dependencies. New dependencies fail closed until reviewed here.
PYTHON_DEPENDENCY_LICENSES = {
    "build": "MIT",
    "importlib-metadata": "Apache-2.0",
    "packaging": "Apache-2.0 OR BSD-2-Clause",
    "pip": "MIT",
    "pyproject-hooks": "MIT",
    "setuptools": "MIT",
    "tomli": "MIT",
    "wheel": "MIT",
    "zipp": "MIT",
    "zstandard": "BSD-3-Clause",
}


def git(*args):
    return subprocess.check_output(["git", *args], cwd=str(ROOT), text=True).strip()


def generate():
    components = []
    dependencies = []
    root_ref = "ganesha-full-scratch-v1@" + git("rev-parse", "HEAD")
    for requirements_file, dependency_scope in (("requirements-build.txt", "build"),
                                                ("requirements-test.txt", "test")):
        for line in (ROOT / requirements_file).read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+-]+)", line)
            if not match:
                raise ValueError("%s dependency must be exactly pinned: %s" % (dependency_scope, line))
            name, version = match.groups()
            normalized_name = name.lower().replace("_", "-")
            license_expression = PYTHON_DEPENDENCY_LICENSES.get(normalized_name)
            if not license_expression:
                raise ValueError("Python dependency license expression is not reviewed: %s" % name)
            ref = "pkg:pypi/%s@%s" % (name.lower().replace("_", "-"), version)
            components.append({"type": "library", "bom-ref": ref, "name": name, "version": version,
                               "purl": ref, "scope": "required" if dependency_scope == "build" else "excluded",
                               "licenses": [{"expression": license_expression}],
                               "properties": [{"name": "ganesha.python.dependency.scope", "value": dependency_scope},
                                              {"name": "ganesha.python.license.evidence", "value": "exact pinned wheel METADATA License-Expression"},
                                              {"name": "ganesha.python.requirements.file", "value": requirements_file}]})
            dependencies.append(ref)

    # Include the complete npm lock graph plus Python build and test requirements.
    # A bundled SDK is still a shipped dependency even when it is split into a
    # lazy-loaded browser chunk; listing only the Python toolchain is incomplete.
    lock = json.loads((ROOT / "package-lock.json").read_text(encoding="utf-8"))
    if lock.get("lockfileVersion") != 3 or not isinstance(lock.get("packages"), dict):
        raise ValueError("package-lock.json must be a valid npm lockfileVersion 3")
    npm_packages = lock["packages"]
    npm_refs = {}
    for package_path, package in sorted(npm_packages.items()):
        if not package_path:
            continue
        parts = PurePosixPath(package_path).parts
        try:
            marker = max(index for index, part in enumerate(parts) if part == "node_modules")
        except ValueError:
            raise ValueError("npm lock package path is not rooted under node_modules: %s" % package_path)
        name = "/".join(parts[marker + 1:])
        version = package.get("version")
        if not name or not isinstance(version, str) or not version:
            raise ValueError("npm lock package name/version is invalid: %s" % package_path)
        purl = "pkg:npm/%s@%s" % (name.replace("@", "%40", 1) if name.startswith("@") else name, version)
        ref = purl
        npm_refs[package_path] = ref
        component = {"type": "library", "bom-ref": ref, "name": name, "version": version,
                     "purl": purl, "scope": "excluded" if package.get("dev") else "required",
                     "properties": [{"name": "npm.package.path", "value": package_path},
                                    {"name": "npm.dev_dependency", "value": str(bool(package.get("dev"))).lower()}]}
        license_value = package.get("license")
        if isinstance(license_value, str) and license_value:
            component["licenses"] = [{"license": {"id": license_value}}]
        integrity = package.get("integrity", "")
        if isinstance(integrity, str) and integrity.startswith("sha512-"):
            try:
                digest = base64.b64decode(integrity[7:], validate=True).hex()
            except Exception as exc:
                raise ValueError("invalid npm SHA-512 integrity for %s" % package_path) from exc
            component["hashes"] = [{"alg": "SHA-512", "content": digest}]
        components.append(component)

    def resolve_npm_dependency(package_path, dependency_name):
        prefix = list(PurePosixPath(package_path).parts)
        dep_parts = dependency_name.split("/")
        while prefix:
            candidate = "/".join(prefix + ["node_modules"] + dep_parts)
            if candidate in npm_refs:
                return npm_refs[candidate]
            prefix.pop()
        candidate = "/".join(["node_modules"] + dep_parts)
        return npm_refs.get(candidate)

    npm_relationships = []
    root_package = npm_packages.get("", {})
    root_npm_dependencies = []
    for field in ("dependencies", "devDependencies"):
        for dependency_name in sorted(root_package.get(field, {})):
            resolved = resolve_npm_dependency("", dependency_name)
            if not resolved:
                raise ValueError("root npm dependency is absent from the lockfile: %s" % dependency_name)
            root_npm_dependencies.append(resolved)
    npm_relationships.append({"ref": root_ref,
                              "dependsOn": sorted(set(root_npm_dependencies))})
    for package_path, package in sorted(npm_packages.items()):
        if not package_path:
            continue
        refs = set()
        for field in ("dependencies", "optionalDependencies", "peerDependencies"):
            for dependency_name in package.get(field, {}):
                resolved = resolve_npm_dependency(package_path, dependency_name)
                if not resolved and field != "peerDependencies":
                    raise ValueError("locked npm package %s has unresolved %s dependency %s" %
                                     (package_path, field, dependency_name))
                if resolved:
                    refs.add(resolved)
        npm_relationships.append({"ref": npm_refs[package_path], "dependsOn": sorted(refs)})
    asset_root = ROOT / "frontend/assets"
    provenance_path = asset_root / "ASSET_PROVENANCE.json"
    if asset_root.is_symlink() or not asset_root.is_dir() or provenance_path.is_symlink():
        raise ValueError("asset root and provenance manifest must be regular repository paths")
    asset_manifest = json.loads(provenance_path.read_text(encoding="utf-8"))
    asset_records = asset_manifest.get("assets") if isinstance(asset_manifest, dict) else None
    if not isinstance(asset_records, list) or len(asset_records) != 22:
        raise ValueError("asset provenance must contain exactly 22 shipped asset records")
    filenames = [asset.get("file") if isinstance(asset, dict) else None for asset in asset_records]
    if any(not isinstance(name, str) or not name or "\\" in name or PurePosixPath(name).is_absolute()
           or PurePosixPath(name).as_posix() != name or ".." in PurePosixPath(name).parts
           for name in filenames):
        raise ValueError("asset provenance contains an invalid relative asset path")
    if len(set(filenames)) != len(filenames):
        raise ValueError("asset provenance contains duplicate asset paths")
    digests = [asset.get("sha256") for asset in asset_records]
    if any(not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
           for digest in digests) or len(set(digests)) != len(digests):
        raise ValueError("asset provenance contains an invalid or duplicate content identity")
    actual_assets = set()
    for candidate in asset_root.rglob("*"):
        if candidate.is_symlink():
            raise ValueError("shipped asset inventory contains a symlink: %s" % candidate.relative_to(asset_root))
        if candidate.is_file() and candidate.name != "ASSET_PROVENANCE.json":
            actual_assets.add(candidate.relative_to(asset_root).as_posix())
    if actual_assets != set(filenames):
        raise ValueError("asset provenance does not match the exact shipped asset inventory")
    for asset in asset_records:
        filename = asset["file"]
        path = asset_root / filename
        if not path.is_file() or path.is_symlink() or asset_root.resolve() not in path.resolve().parents:
            raise ValueError("SBOM asset is missing, symlinked or escapes the asset root: %s" % filename)
        if type(asset.get("bytes")) is not int or asset["bytes"] < 0:
            raise ValueError("SBOM asset provenance byte count is invalid: %s" % filename)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != asset.get("sha256") or path.stat().st_size != asset.get("bytes"):
            raise ValueError("SBOM asset provenance hash/size mismatch: %s" % filename)
        ref = "urn:sha256:" + digest
        components.append({
            "type": "file", "bom-ref": ref, "name": filename, "scope": "required",
            "hashes": [{"alg": "SHA-256", "content": digest}],
            "properties": [
                {"name": "ganesha.asset.creator", "value": str(asset.get("creator", "not established"))},
                {"name": "ganesha.asset.rights_holder", "value": str(asset.get("rights_holder", "not established"))},
                {"name": "ganesha.asset.license", "value": str(asset.get("license", "not established"))},
                {"name": "ganesha.asset.redistribution_rights", "value": str(asset.get("redistribution_rights", "not established"))},
                {"name": "ganesha.asset.modification_permission", "value": str(asset.get("modification_permission", "not established"))},
                {"name": "ganesha.asset.redistribution_permission", "value": str(asset.get("redistribution_permission", "not established"))},
                {"name": "ganesha.asset.rights_evidence_ref", "value": str(asset.get("rights_evidence_ref", "not established"))},
            ],
        })
        dependencies.append(ref)
    source_epoch = int(os.environ.get("SOURCE_DATE_EPOCH", git("log", "-1", "--format=%ct")))
    timestamp = datetime.datetime.fromtimestamp(source_epoch, datetime.timezone.utc).isoformat().replace("+00:00", "Z")
    identity_refs = dependencies + list(npm_refs.values())
    identity = hashlib.sha256((root_ref + "\n" + "\n".join(sorted(identity_refs))).encode("utf-8")).hexdigest()
    serial = str(uuid.uuid5(uuid.NAMESPACE_URL, "urn:ganesha:sbom:" + identity))
    return {
        "bomFormat": "CycloneDX", "specVersion": "1.5", "serialNumber": "urn:uuid:" + serial,
        "version": 1,
        "metadata": {"timestamp": timestamp, "component": {"type": "application", "bom-ref": root_ref,
                      "name": "ganesha-full-scratch-v1", "version": "0.1.0"},
                      "properties": [{"name": "ganesha.source.commit", "value": git("rev-parse", "HEAD")},
                                     {"name": "ganesha.source.attestation_scope", "value": "HEAD is the base commit; dependency and asset components are enumerated from the current working-tree lockfile, build requirements and asset provenance. This SBOM does not attest uncommitted source files or constitute a release manifest."},
                                     {"name": "ganesha.runtime.dependencies", "value": "Python standard library only"},
                                     {"name": "ganesha.python.build.dependencies", "value": "requirements-build.txt"},
                                     {"name": "ganesha.python.test.dependencies", "value": "requirements-test.txt"},
                                     {"name": "ganesha.npm.lockfile.sha256", "value": hashlib.sha256((ROOT / "package-lock.json").read_bytes()).hexdigest()},
                                     {"name": "ganesha.npm.locked.package.count", "value": str(len(npm_refs))},
                      {"name": "ganesha.sbom.scope", "value": "pinned Python build and test dependencies, all package-lock.json npm packages and shipped frontend assets; source-file hashes are separately bound by the release manifest"}]},
        "components": sorted(components, key=lambda item: item["name"].lower()),
        "dependencies": [{"ref": root_ref, "dependsOn": sorted(dependencies + root_npm_dependencies)}] +
                        [{"ref": ref, "dependsOn": []} for ref in sorted(dependencies)] +
                        [item for item in npm_relationships if item["ref"] != root_ref],
    }


def validate_sbom_document(sbom):
    """Require the SBOM to match the complete lockfile, build/test tools and asset inventory."""
    if not isinstance(sbom, dict):
        raise ValueError("SBOM root must be an object")
    expected = generate()
    expected_metadata = expected["metadata"]
    metadata = sbom.get("metadata")
    if not isinstance(metadata, dict):
        raise ValueError("SBOM metadata is missing")
    for field in ("bomFormat", "specVersion", "serialNumber", "version"):
        if sbom.get(field) != expected.get(field):
            raise ValueError("SBOM %s does not match the current source inventory" % field)
    for field in ("component", "properties"):
        if metadata.get(field) != expected_metadata.get(field):
            raise ValueError("SBOM metadata %s does not match the current source inventory" % field)
    if sbom.get("components") != expected.get("components"):
        raise ValueError("SBOM components do not cover the complete locked npm, Python build/test and shipped asset inventory")
    if sbom.get("dependencies") != expected.get("dependencies"):
        raise ValueError("SBOM dependency relationships do not match the complete npm lock graph")
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(generate(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("SBOM=%s" % output)
    print("SHA256=%s" % hashlib.sha256(output.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
