#!/usr/bin/env python3
"""Fail-closed builder for an authority-bound Stake Math package.

The builder never infers source Math from Books/LUT/index. It requires the
58-field RC10 canonical-input manifest, hash-linked source files, explicit
approval references, and generator-produced publish artifact declarations.
It writes nothing unless every precondition and the final SDK package verifier
passes. Output paths must not already exist.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

try:
    from tools.verify_stake_package import verify_math_directory, verify_math_zip
except ModuleNotFoundError:  # direct script execution from tools/
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools.verify_stake_package import verify_math_directory, verify_math_zip

REQUIRED_FIELDS = (
    "generator.name", "generator.version", "generator.source_entrypoint",
    "generator.source_sha256", "sdk.repository", "sdk.commit",
    "sdk.dependency_lock_path", "sdk.dependency_lock_sha256",
    "game_config.path", "game_config.sha256", "game_config.approval_reference",
    "modes.BASE.reel_strips.path", "modes.BASE.reel_strips.sha256", "modes.BASE.reel_strips.approval_reference",
    "modes.MAGICBUY_V36.reel_strips.path", "modes.MAGICBUY_V36.reel_strips.sha256", "modes.MAGICBUY_V36.reel_strips.approval_reference",
    "modes.EPICBUY_V37.reel_strips.path", "modes.EPICBUY_V37.reel_strips.sha256", "modes.EPICBUY_V37.reel_strips.approval_reference",
    "paytable.path", "paytable.sha256", "paytable.approval_reference",
    "paylines.path", "paylines.sha256", "paylines.approval_reference",
    "symbols.path", "symbols.sha256", "symbols.approval_reference",
    "feature_rules.path", "feature_rules.sha256", "feature_rules.approval_reference",
    "feature_rules.scatter_policy", "feature_rules.six_plus_scatter_policy", "feature_rules.retrigger_policy",
    "modes.BASE.probability_model.path", "modes.BASE.probability_model.sha256", "modes.BASE.probability_model.approval_reference",
    "modes.MAGICBUY_V36.probability_model.path", "modes.MAGICBUY_V36.probability_model.sha256", "modes.MAGICBUY_V36.probability_model.approval_reference",
    "modes.EPICBUY_V37.probability_model.path", "modes.EPICBUY_V37.probability_model.sha256", "modes.EPICBUY_V37.probability_model.approval_reference",
    "rng.algorithm", "rng.version", "rng.seed_derivation",
    "purchase_costs.BASE.multiplier", "purchase_costs.BASE.approval_reference",
    "purchase_costs.MAGICBUY_V36.multiplier", "purchase_costs.MAGICBUY_V36.approval_reference",
    "purchase_costs.EPICBUY_V37.multiplier", "purchase_costs.EPICBUY_V37.approval_reference",
    "golden_vectors.path", "golden_vectors.sha256", "golden_vectors.approval_reference",
    "front_contract.path", "front_contract.sha256",
)
REQUIRED_MODES = ("BASE", "MAGICBUY_V36", "EPICBUY_V37")


def _get(obj, dotted):
    value = obj
    for part in dotted.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _confined_file(root: Path, raw: object, label: str, issues: list) -> Path | None:
    if not isinstance(raw, str) or not raw or "\\" in raw:
        issues.append({"code": "INVALID_SOURCE_PATH", "field": label, "value": raw})
        return None
    rel = PurePosixPath(raw)
    if rel.is_absolute() or ".." in rel.parts or not rel.parts:
        issues.append({"code": "UNSAFE_SOURCE_PATH", "field": label, "value": raw})
        return None
    candidate = root.joinpath(*rel.parts)
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root.resolve(strict=True))
    except (OSError, ValueError):
        issues.append({"code": "SOURCE_FILE_MISSING_OR_OUTSIDE_ROOT", "field": label, "value": raw})
        return None
    if candidate.is_symlink() or not resolved.is_file():
        issues.append({"code": "SOURCE_FILE_NOT_REGULAR", "field": label, "value": raw})
        return None
    return resolved


def inspect_manifest(manifest_path: str | Path) -> dict:
    path = Path(manifest_path).resolve()
    report = {"schema": "ganesha-stake-math-source-preflight.v1", "status": "BLOCKED",
              "manifest_path": str(path), "required_field_count": len(REQUIRED_FIELDS),
              "missing_fields": [], "file_checks": [], "issues": []}
    if not path.is_file():
        report["missing_fields"] = list(REQUIRED_FIELDS)
        report["issues"].append({"code": "CANONICAL_MANIFEST_MISSING", "missing_field_count": len(REQUIRED_FIELDS),
                                 "missing_fields": list(REQUIRED_FIELDS)})
        return report
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_pairs,
                              parse_constant=lambda v: (_ for _ in ()).throw(ValueError("invalid JSON constant " + v)))
    except Exception as exc:
        report["issues"].append({"code": "MANIFEST_JSON_INVALID", "detail": str(exc)})
        return report
    if not isinstance(manifest, dict):
        report["issues"].append({"code": "MANIFEST_ROOT_NOT_OBJECT"})
        return report
    missing = [field for field in REQUIRED_FIELDS if _get(manifest, field) is None or _get(manifest, field) == ""]
    report["missing_fields"] = missing
    root = path.parent
    for field in REQUIRED_FIELDS:
        value = _get(manifest, field)
        if value is None or value == "":
            continue
        if field.endswith(".path") or field in ("generator.source_entrypoint", "sdk.dependency_lock_path"):
            file_path = _confined_file(root, value, field, report["issues"])
            hash_field = field[:-5] + ".sha256" if field.endswith(".path") else (
                "generator.source_sha256" if field == "generator.source_entrypoint" else "sdk.dependency_lock_sha256")
            expected = _get(manifest, hash_field)
            if file_path:
                actual = _sha(file_path)
                match = isinstance(expected, str) and actual == expected.lower()
                report["file_checks"].append({"field": field, "path": value, "sha256": actual,
                                               "expected_sha256": expected, "matches": match})
                if not match:
                    report["issues"].append({"code": "SOURCE_HASH_MISMATCH", "field": field,
                                             "expected": expected, "actual": actual})
        elif field.endswith(".sha256"):
            if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdefABCDEF" for c in value):
                report["issues"].append({"code": "INVALID_SHA256", "field": field})
        elif field.endswith(".approval_reference"):
            if not isinstance(value, str) or not value.strip():
                report["issues"].append({"code": "APPROVAL_REFERENCE_MISSING", "field": field})
        elif field.endswith(".multiplier"):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                report["issues"].append({"code": "PURCHASE_COST_INVALID", "field": field, "value": value})
        elif not isinstance(value, str) or not value.strip():
            report["issues"].append({"code": "REQUIRED_VALUE_INVALID", "field": field})

    # A canonical package requires explicit generated output files, not inferred names.
    artifacts = manifest.get("publish_artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != set(REQUIRED_MODES):
        report["issues"].append({"code": "PUBLISH_ARTIFACT_MODE_SET_INVALID",
                                 "expected_modes": list(REQUIRED_MODES)})
    else:
        for mode in REQUIRED_MODES:
            entry = artifacts[mode]
            if not isinstance(entry, dict) or set(entry) != {"events_path", "events_sha256", "weights_path", "weights_sha256"}:
                report["issues"].append({"code": "PUBLISH_ARTIFACT_DECLARATION_INVALID", "mode": mode})
                continue
            for key in ("events_path", "weights_path"):
                field = f"publish_artifacts.{mode}.{key}"
                file_path = _confined_file(root, entry.get(key), field, report["issues"])
                hash_value = entry.get(key.replace("_path", "_sha256"))
                if file_path:
                    actual = _sha(file_path)
                    match = isinstance(hash_value, str) and actual == hash_value.lower()
                    report["file_checks"].append({"field": field, "path": entry[key], "sha256": actual,
                                                   "expected_sha256": hash_value, "matches": match})
                    if not match:
                        report["issues"].append({"code": "PUBLISH_ARTIFACT_HASH_MISMATCH", "field": field})

    # Fail closed on an explicitly partial or unapproved source manifest.
    if manifest.get("status") != "CANONICAL_SOURCE_VERIFIED":
        report["issues"].append({"code": "CANONICAL_SOURCE_STATUS_NOT_VERIFIED",
                                 "observed": manifest.get("status")})
    if missing:
        report["issues"].append({"code": "CANONICAL_FIELDS_MISSING", "count": len(missing), "fields": missing})
    report["manifest_sha256"] = _sha(path)
    report["status"] = "PASS" if not report["issues"] else "BLOCKED"
    return report


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key: " + key)
        result[key] = value
    return result


def build_package(manifest_path: str | Path, output_dir: str | Path, output_zip: str | Path) -> dict:
    preflight = inspect_manifest(manifest_path)
    report = {"schema": "ganesha-stake-math-package-build.v1", "status": "BLOCKED",
              "preflight": preflight, "output_dir": str(Path(output_dir).absolute()),
              "output_zip": str(Path(output_zip).absolute()), "issues": []}
    if preflight["status"] != "PASS":
        report["issues"].append({"code": "SOURCE_PREFLIGHT_BLOCKED"})
        return report
    out_dir, out_zip = Path(output_dir).absolute(), Path(output_zip).absolute()
    if out_dir.exists() or out_zip.exists():
        report["issues"].append({"code": "OUTPUT_ALREADY_EXISTS_NO_OVERWRITE"})
        return report
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"), object_pairs_hook=_unique_pairs)
    root = Path(manifest_path).resolve().parent
    with tempfile.TemporaryDirectory(prefix="ganesha-math-build-") as temp:
        stage = Path(temp) / "MATH"
        stage.mkdir()
        index_modes = []
        for mode in REQUIRED_MODES:
            spec = manifest["publish_artifacts"][mode]
            events_src = _confined_file(root, spec["events_path"], mode + ".events", report["issues"])
            weights_src = _confined_file(root, spec["weights_path"], mode + ".weights", report["issues"])
            if not events_src or not weights_src:
                return report
            events_name, weights_name = Path(spec["events_path"]).name, Path(spec["weights_path"]).name
            if events_name == weights_name or (stage / events_name).exists() or (stage / weights_name).exists():
                report["issues"].append({"code": "PUBLISH_BASENAME_COLLISION", "mode": mode})
                return report
            shutil.copyfile(events_src, stage / events_name)
            shutil.copyfile(weights_src, stage / weights_name)
            index_modes.append({"name": mode, "cost": manifest["purchase_costs"][mode]["multiplier"],
                                "events": events_name, "weights": weights_name})
        (stage / "index.json").write_text(json.dumps({"modes": index_modes}, ensure_ascii=False,
                                                       indent=2) + "\n", encoding="utf-8")
        math_report = verify_math_directory(stage)
        report["source_math_verification"] = math_report
        if math_report["status"] != "PASS":
            report["issues"].append({"code": "STAKE_MATH_DIRECTORY_VERIFICATION_BLOCKED"})
            return report
        # Build in a temporary file, then atomically publish only to previously absent paths.
        temp_zip = Path(temp) / "MATH.zip"
        with zipfile.ZipFile(temp_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for item in sorted(stage.iterdir(), key=lambda p: p.name):
                info = zipfile.ZipInfo(item.name, date_time=(2020, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, item.read_bytes())
        zip_report = verify_math_zip(temp_zip)
        report["zip_verification"] = zip_report
        if zip_report["status"] != "PASS":
            report["issues"].append({"code": "STAKE_MATH_ZIP_VERIFICATION_BLOCKED"})
            return report
        # Destination parents must exist; never replace an existing destination.
        if not out_dir.parent.is_dir() or not out_zip.parent.is_dir():
            report["issues"].append({"code": "OUTPUT_PARENT_MISSING"})
            return report
        os.mkdir(out_dir)
        try:
            for item in stage.iterdir():
                shutil.copyfile(item, out_dir / item.name)
            with out_zip.open("xb") as stream:
                stream.write(temp_zip.read_bytes())
        except Exception:
            # Do not silently delete partial output; report exact paths for manual review.
            report["issues"].append({"code": "OUTPUT_WRITE_INCOMPLETE_REQUIRES_MANUAL_REVIEW"})
            return report
    # Recheck the actual published destination, not only the staging directory.
    report["final_directory_verification"] = verify_math_directory(out_dir)
    report["final_zip_verification"] = verify_math_zip(out_zip)
    if (report["final_directory_verification"]["status"] != "PASS"
            or report["final_zip_verification"]["status"] != "PASS"):
        report["issues"].append({"code": "FINAL_DESTINATION_RECHECK_FAILED"})
        return report
    report["status"] = "PASS"
    report["output_files"] = sorted(p.name for p in out_dir.iterdir())
    report["zip_sha256"] = _sha(out_zip)
    report["zip_size_bytes"] = out_zip.stat().st_size
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    pre = sub.add_parser("preflight")
    pre.add_argument("manifest")
    build = sub.add_parser("build")
    build.add_argument("manifest")
    build.add_argument("output_dir")
    build.add_argument("output_zip")
    args = parser.parse_args()
    result = inspect_manifest(args.manifest) if args.command == "preflight" else build_package(
        args.manifest, args.output_dir, args.output_zip)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["status"] == "PASS" else 2)


if __name__ == "__main__":
    main()
