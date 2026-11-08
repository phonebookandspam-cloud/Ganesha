#!/usr/bin/env python3
"""Fail-closed structural verifier for Stake Engine Math and static Frontend packages.

This verifies published file contracts only. It does not certify game mathematics,
Provider approval, legal compliance, or production RGS behavior.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import re
import stat
import tempfile
import zipfile
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

UINT64_MAX = (1 << 64) - 1
_ALLOWED_FRONTEND_SUFFIXES = {
    ".html", ".css", ".js", ".mjs", ".json", ".webmanifest", ".svg", ".png",
    ".jpg", ".jpeg", ".webp", ".gif", ".ico", ".wav", ".mp3", ".ogg",
    ".woff", ".woff2", ".ttf", ".otf", ".wasm",
}
_REQUIRED_RGS_PATHS = ("/wallet/authenticate", "/wallet/play", "/wallet/end-round", "/bet/event")
_REQUIRED_LAUNCH_PARAMS = ("sessionID", "rgs_url", "lang", "device")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key: %s" % key)
        result[key] = value
    return result


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError("invalid JSON constant: " + value)))


def _issue(report, code, detail):
    report["issues"].append({"code": code, "detail": detail})


def _safe_package_file(root: Path, filename: str, suffixes: tuple[str, ...], report, label: str):
    if not isinstance(filename, str) or not filename or "\\" in filename:
        _issue(report, "INVALID_REFERENCE", "%s must be a non-empty relative filename" % label)
        return None
    rel = PurePosixPath(filename)
    if rel.is_absolute() or len(rel.parts) != 1 or rel.parts[0] in (".", ".."):
        _issue(report, "UNSAFE_REFERENCE", "%s is not a root-level package filename: %r" % (label, filename))
        return None
    if not filename.endswith(suffixes):
        _issue(report, "INVALID_EXTENSION", "%s has unsupported extension: %s" % (label, filename))
        return None
    target = root / filename
    if target.is_symlink() or not target.is_file():
        _issue(report, "MISSING_REFERENCE", "%s does not resolve to a regular file: %s" % (label, filename))
        return None
    return target


def verify_math_directory(package_dir) -> dict:
    """Validate a Math source directory against Stake's index/CSV/Zstandard Books contract."""
    root = Path(package_dir).resolve()
    report = {"kind": "stake-math-directory", "path": str(root), "status": "BLOCKED", "modes": [], "issues": []}
    if not root.is_dir():
        _issue(report, "NOT_A_DIRECTORY", "Math package source path is not a directory")
        return report
    index_path = root / "index.json"
    if index_path.is_symlink() or not index_path.is_file():
        _issue(report, "ERR_MISSING_FILE", "Stake Math upload requires index.json at the package root")
        return report
    try:
        index = _read_json(index_path)
    except Exception as exc:
        _issue(report, "INVALID_INDEX_JSON", str(exc))
        return report
    if not isinstance(index, dict) or set(index) != {"modes"}:
        _issue(report, "INVALID_INDEX_SCHEMA", "index.json must contain exactly one top-level key: modes")
        return report
    modes = index.get("modes")
    if not isinstance(modes, list) or not modes:
        _issue(report, "EMPTY_MODES", "index.json modes must be a non-empty array; empty/dummy modes are not accepted")
        return report

    names = set()
    costs = []
    for position, mode in enumerate(modes):
        label = "modes[%d]" % position
        if not isinstance(mode, dict) or set(mode) != {"name", "cost", "events", "weights"}:
            _issue(report, "INVALID_MODE_SCHEMA", "%s must contain exactly name, cost, events, weights" % label)
            continue
        name, cost = mode["name"], mode["cost"]
        if not isinstance(name, str) or not name or name.strip() != name or name in names:
            _issue(report, "INVALID_MODE_NAME", "%s.name must be a unique non-empty string" % label)
            continue
        names.add(name)
        if isinstance(cost, bool) or not isinstance(cost, (int, float)) or not math.isfinite(cost) or cost <= 0:
            _issue(report, "INVALID_MODE_COST", "%s.cost must be a finite positive number" % label)
            continue
        costs.append(float(cost))
        book_path = _safe_package_file(root, mode["events"], (".jsonl.zst", ".jsonl.zstd"), report, label + ".events")
        lut_path = _safe_package_file(root, mode["weights"], (".csv",), report, label + ".weights")
        if book_path is None or lut_path is None:
            continue

        csv_ids, csv_payouts, total_weight = [], [], 0
        try:
            with lut_path.open("r", encoding="utf-8", newline="") as stream:
                for line_number, row in enumerate(csv.reader(stream), start=1):
                    if not row or (len(row) == 1 and not row[0].strip()):
                        continue
                    if len(row) != 3:
                        raise ValueError("line %d must contain exactly three comma-separated uint64 values (no header row)" % line_number)
                    values = []
                    for column, raw in enumerate(row, start=1):
                        value = raw.strip()
                        if not re.fullmatch(r"[0-9]+", value):
                            raise ValueError("line %d column %d is not an unsigned integer" % (line_number, column))
                        number = int(value)
                        if number > UINT64_MAX:
                            raise ValueError("line %d column %d exceeds uint64" % (line_number, column))
                        values.append(number)
                    simulation_id, weight, payout = values
                    if simulation_id in csv_ids:
                        raise ValueError("duplicate simulation_number %d" % simulation_id)
                    if payout and (payout < 10 or payout % 10):
                        raise ValueError("line %d payout_multiplier must be zero or a multiple of 10 >= 10" % line_number)
                    csv_ids.append(simulation_id)
                    csv_payouts.append(payout)
                    total_weight += weight
                    if total_weight > UINT64_MAX:
                        raise ValueError("sum of round_probability exceeds uint64")
            if not csv_ids or total_weight <= 0:
                raise ValueError("lookup table must contain outcomes and a positive total round_probability")
        except Exception as exc:
            _issue(report, "INVALID_LOOKUP_TABLE", "%s: %s" % (lut_path.name, exc))
            continue

        book_ids, book_payouts, event_count = [], [], 0
        try:
            import zstandard
            with book_path.open("rb") as raw:
                with zstandard.ZstdDecompressor().stream_reader(raw) as reader:
                    text_stream = io.TextIOWrapper(reader, encoding="utf-8")
                    for line_number, line in enumerate(text_stream, start=1):
                        if not line.strip():
                            continue
                        blob = json.loads(line, object_pairs_hook=_unique_object)
                        if not isinstance(blob, dict) or not {"id", "events", "payoutMultiplier"}.issubset(blob):
                            raise ValueError("line %d must contain id, events and payoutMultiplier" % line_number)
                        simulation_id, events, payout = blob["id"], blob["events"], blob["payoutMultiplier"]
                        if type(simulation_id) is not int or not 0 <= simulation_id <= UINT64_MAX:
                            raise ValueError("line %d id must be a uint64 integer" % line_number)
                        if simulation_id in book_ids:
                            raise ValueError("duplicate book simulation id %d" % simulation_id)
                        if not isinstance(events, list) or not all(isinstance(event, dict) for event in events):
                            raise ValueError("line %d events must be an array of objects" % line_number)
                        if type(payout) is not int or not 0 <= payout <= UINT64_MAX:
                            raise ValueError("line %d payoutMultiplier must be a uint64 integer" % line_number)
                        book_ids.append(simulation_id)
                        book_payouts.append(payout)
                        event_count += len(events)
            if not book_ids:
                raise ValueError("compressed Books contains no simulation records")
        except Exception as exc:
            _issue(report, "INVALID_COMPRESSED_BOOKS", "%s: %s" % (book_path.name, exc))
            continue

        if csv_ids != book_ids:
            _issue(report, "SIMULATION_ID_MISMATCH", "%s: CSV simulation_number order/IDs differ from Books id order" % name)
        if csv_payouts != book_payouts:
            _issue(report, "PAYOUT_MULTIPLIER_MISMATCH", "%s: CSV payout_multiplier values do not exactly match Books payoutMultiplier values in order" % name)
        report["modes"].append({"name": name, "cost": cost, "outcomes": len(book_ids),
                                "event_count": event_count, "total_weight": total_weight,
                                "max_payout_multiplier": max(book_payouts)})

    if costs and 1.0 not in costs:
        _issue(report, "BASE_MODE_COST_MISSING", "Stake Math SDK submission verifier requires at least one 1.0x base-cost mode")
    report["status"] = "PASS" if not report["issues"] and len(report["modes"]) == len(modes) else "BLOCKED"
    return report


class _HtmlReferenceParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.references = []
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        for key in ("src", "href", "poster"):
            if attrs.get(key):
                self.references.append((attrs[key], Path("."), "HTML %s.%s" % (tag, key)))


def _resolve_local_reference(root: Path, base: Path, reference: str, report, label: str):
    value = reference.strip()
    if not value or value.startswith(("#", "data:", "blob:", "mailto:", "tel:")):
        return
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc:
        _issue(report, "EXTERNAL_ASSET_REFERENCE", "%s references external URL %s; final build must be static/self-contained" % (label, value))
        return
    path_text = parsed.path
    if not path_text:
        return
    rel = PurePosixPath(path_text.lstrip("/")) if path_text.startswith("/") else PurePosixPath(path_text)
    if rel.is_absolute() or ".." in rel.parts:
        _issue(report, "UNSAFE_ASSET_REFERENCE", "%s contains unsafe local path %s" % (label, value))
        return
    target = root.joinpath(*rel.parts) if path_text.startswith("/") else (root / base).joinpath(*rel.parts)
    # Resolve case-sensitively even on case-insensitive development filesystems.
    cursor = root
    for part in target.relative_to(root).parts:
        try:
            actual = next((entry.name for entry in cursor.iterdir() if entry.name == part), None)
        except OSError:
            actual = None
        if actual is None:
            _issue(report, "MISSING_ASSET_REFERENCE", "%s references missing/case-mismatched file %s" % (label, value))
            return
        cursor = cursor / actual
    if cursor.is_symlink() or not cursor.is_file():
        _issue(report, "INVALID_ASSET_TARGET", "%s does not resolve to a regular file: %s" % (label, value))


def verify_frontend_directory(package_dir) -> dict:
    """Validate a fully static Frontend directory and the public RGS launch/API contract."""
    root = Path(package_dir).resolve()
    report = {"kind": "stake-frontend-directory", "path": str(root), "status": "BLOCKED", "files": 0,
              "sdk_path_literals_found": [], "launch_params_found": [], "declared_capabilities": {}, "issues": []}
    if not root.is_dir():
        _issue(report, "NOT_A_DIRECTORY", "Frontend package path is not a directory")
        return report
    index = root / "index.html"
    if index.is_symlink() or not index.is_file():
        _issue(report, "ERR_MISSING_FILE", "Stake Frontend build must contain index.html at package root")
        return report
    files = [path for path in root.rglob("*") if path.is_file()]
    report["files"] = len(files)
    if not files:
        _issue(report, "EMPTY_FRONTEND", "Frontend package contains no static files")
        return report
    for path in files:
        if path.is_symlink():
            _issue(report, "SYMLINK_IN_PACKAGE", "Static package must not contain symlinks: %s" % path.relative_to(root))
        if path.suffix.lower() not in _ALLOWED_FRONTEND_SUFFIXES:
            _issue(report, "NON_STATIC_OR_UNKNOWN_FILE", "Unsupported/non-static file in frontend package: %s" % path.relative_to(root))

    parser = _HtmlReferenceParser()
    try:
        parser.feed(index.read_text(encoding="utf-8"))
    except Exception as exc:
        _issue(report, "INVALID_HTML", str(exc))
    for reference, base, label in parser.references:
        _resolve_local_reference(root, base, reference, report, label)

    js_text = []
    for path in files:
        suffix = path.suffix.lower()
        try:
            content = path.read_text(encoding="utf-8") if suffix in (".js", ".mjs", ".css", ".html", ".json", ".webmanifest") else ""
        except UnicodeDecodeError:
            _issue(report, "INVALID_TEXT_ASSET", "Expected UTF-8 text asset: %s" % path.relative_to(root))
            continue
        rel = path.relative_to(root)
        if suffix in (".js", ".mjs"):
            js_text.append(content)
            for match in re.finditer(r"new URL\(\s*['\"]([^'\"]+)['\"]\s*,\s*import\.meta\.url\s*\)", content):
                _resolve_local_reference(root, rel.parent, match.group(1), report, str(rel))
            for match in re.finditer(r"\bimport\(\s*['\"]([^'\"]+)['\"]\s*\)", content):
                _resolve_local_reference(root, rel.parent, match.group(1), report, str(rel))
            for match in re.finditer(r"['\"](\./assets/[^'\"]+)['\"]", content):
                _resolve_local_reference(root, Path("."), match.group(1), report, str(rel))
            if re.search(r"https?://", content, re.IGNORECASE):
                _issue(report, "HARDCODED_EXTERNAL_ORIGIN", "%s contains an absolute HTTP(S) origin; RGS must be selected from launch rgs_url" % rel)
        elif suffix == ".css":
            for match in re.finditer(r"url\(\s*['\"]?([^)'\"]+)['\"]?\s*\)", content, re.IGNORECASE):
                _resolve_local_reference(root, rel.parent, match.group(1), report, str(rel))
            for match in re.finditer(r"@import\s+(?:url\()?['\"]([^'\"]+)['\"]", content, re.IGNORECASE):
                _resolve_local_reference(root, rel.parent, match.group(1), report, str(rel))
            if re.search(r"https?://", content, re.IGNORECASE):
                _issue(report, "EXTERNAL_CSS_ORIGIN", "%s contains an absolute HTTP(S) origin" % rel)

    combined_js = "\n".join(js_text)
    # SDK bundles may contain Play/EndRound/Event methods even when the game never
    # invokes them. Presence of a string is therefore not proof of integration.
    report["sdk_path_literals_found"] = [path for path in _REQUIRED_RGS_PATHS if path in combined_js]
    report["launch_params_found"] = [param for param in _REQUIRED_LAUNCH_PARAMS if param in combined_js]
    for param in _REQUIRED_LAUNCH_PARAMS:
        if param not in combined_js:
            _issue(report, "MISSING_LAUNCH_PARAMETER", "Frontend bundle does not consume documented launch parameter %s" % param)

    manifest_path = root / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        _issue(report, "MISSING_ENGINEERING_MANIFEST", "Project engineering manifest is required to distinguish implemented RGS operations from SDK symbols")
    else:
        try:
            manifest = _read_json(manifest_path)
            if (not isinstance(manifest, dict)
                    or manifest.get("schema") != "ganesha.frontend-engineering-manifest.v1"
                    or manifest.get("entrypoint") != "index.html"
                    or not isinstance(manifest.get("capabilities"), dict)):
                raise ValueError("manifest schema, entrypoint or capabilities are invalid")
            capabilities = manifest["capabilities"]
            report["declared_capabilities"] = capabilities
            for capability in ("provider_authenticate", "play", "end_round", "event", "wagering", "bonus_buy"):
                if capability not in capabilities:
                    _issue(report, "UNDECLARED_RGS_CAPABILITY", "Engineering manifest does not declare capability %s" % capability)
            for capability in ("play", "end_round", "event", "wagering", "bonus_buy"):
                if capabilities.get(capability) is not True:
                    _issue(report, "RGS_CAPABILITY_NOT_IMPLEMENTED", "Engineering manifest explicitly declares %s unavailable" % capability)
            if capabilities.get("outcome_mutation_by_frontend") is not False:
                _issue(report, "UNSAFE_OUTCOME_AUTHORITY", "Frontend must never declare authority to mutate committed outcomes")
            sdk_status = manifest.get("provider_sdk", {}).get("status") if isinstance(manifest.get("provider_sdk"), dict) else None
            if sdk_status != "FULL_RGS_ROUND_LIFECYCLE":
                _issue(report, "RGS_ADAPTER_NOT_PRODUCTION_READY", "Provider adapter is not declared as a full authenticated Play/Event/EndRound lifecycle")
            if manifest.get("package_kind") != "STAKE_ENGINE_RELEASE_CANDIDATE":
                _issue(report, "NON_RELEASE_FRONTEND_PACKAGE", "Engineering manifest identifies this as a non-release package")
        except Exception as exc:
            _issue(report, "INVALID_ENGINEERING_MANIFEST", str(exc))
    report["status"] = "PASS" if not report["issues"] else "BLOCKED"
    return report


def _verify_zip(zip_path: Path, verifier):
    report = {"kind": "stake-package-zip", "path": str(zip_path), "status": "BLOCKED", "issues": []}
    if not zip_path.is_file():
        _issue(report, "ZIP_NOT_FOUND", "Package ZIP does not exist")
        return report
    try:
        with zipfile.ZipFile(zip_path) as archive:
            names = set()
            for info in archive.infolist():
                name = info.filename
                rel = PurePosixPath(name)
                if rel.is_absolute() or ".." in rel.parts or "\\" in name:
                    _issue(report, "UNSAFE_ZIP_PATH", "Unsafe ZIP entry path: %s" % name)
                if name in names:
                    _issue(report, "DUPLICATE_ZIP_ENTRY", "Duplicate ZIP entry: %s" % name)
                names.add(name)
                mode = info.external_attr >> 16
                if stat.S_ISLNK(mode):
                    _issue(report, "ZIP_SYMLINK", "ZIP contains a symlink: %s" % name)
            bad = archive.testzip()
            if bad:
                _issue(report, "ZIP_CRC_FAILURE", "ZIP CRC failed for %s" % bad)
            if report["issues"]:
                return report
            with tempfile.TemporaryDirectory(prefix="stake-package-check-") as temp:
                archive.extractall(temp)
                inner = verifier(temp)
                report["inner"] = inner
                report["status"] = "PASS" if inner["status"] == "PASS" else "BLOCKED"
                report["issues"].extend(inner["issues"])
    except Exception as exc:
        _issue(report, "INVALID_ZIP", str(exc))
    return report


def verify_math_zip(zip_path) -> dict:
    report = _verify_zip(Path(zip_path).resolve(), verify_math_directory)
    report["kind"] = "stake-math-zip"
    return report


def verify_frontend_zip(zip_path) -> dict:
    report = _verify_zip(Path(zip_path).resolve(), verify_frontend_directory)
    report["kind"] = "stake-frontend-zip"
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("math-dir", "math-zip", "frontend-dir", "frontend-zip"))
    parser.add_argument("path")
    args = parser.parse_args()
    verifier = {"math-dir": verify_math_directory, "math-zip": verify_math_zip,
                "frontend-dir": verify_frontend_directory, "frontend-zip": verify_frontend_zip}[args.kind]
    report = verifier(args.path)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["status"] == "PASS" else 2)


if __name__ == "__main__":
    main()
