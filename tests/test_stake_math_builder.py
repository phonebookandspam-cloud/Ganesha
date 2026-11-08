import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import zstandard

from tools.build_stake_math_package import REQUIRED_FIELDS, inspect_manifest, build_package


def _set_path(obj, dotted, value):
    parts = dotted.split(".")
    for part in parts[:-1]:
        obj = obj.setdefault(part, {})
    obj[parts[-1]] = value


def _hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class StakeMathBuilderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _complete_manifest(self):
        manifest = {"status": "CANONICAL_SOURCE_VERIFIED"}
        source_files = {}
        file_fields = [f for f in REQUIRED_FIELDS if f.endswith(".path") or f in
                       ("generator.source_entrypoint", "sdk.dependency_lock_path")]
        for i, field in enumerate(file_fields):
            path = self.root / f"source-{i}.dat"
            path.write_bytes(f"authority-bound-source-{i}".encode())
            source_files[field] = path
            _set_path(manifest, field, path.name)
            hash_field = field[:-5] + ".sha256" if field.endswith(".path") else (
                "generator.source_sha256" if field == "generator.source_entrypoint" else "sdk.dependency_lock_sha256")
            _set_path(manifest, hash_field, _hash(path))
        for field in REQUIRED_FIELDS:
            if field.endswith(".approval_reference"):
                _set_path(manifest, field, "test-fixture-approval-reference")
            elif field.endswith(".multiplier"):
                _set_path(manifest, field, 1.0 if field == "purchase_costs.BASE.multiplier" else 100.0)
            elif field.endswith(".sha256") and _get(manifest, field) is None:
                _set_path(manifest, field, "a" * 64)
            elif _get(manifest, field) is None:
                _set_path(manifest, field, "test-fixture-explicit-value")
        artifacts = {}
        for mode in ("BASE", "MAGICBUY_V36", "EPICBUY_V37"):
            book = self.root / f"books_{mode}.jsonl.zst"
            lut = self.root / f"weights_{mode}.csv"
            record = {"id": 1, "events": [{"type": "fixture"}], "payoutMultiplier": 20}
            book.write_bytes(zstandard.ZstdCompressor().compress((json.dumps(record) + "\n").encode()))
            lut.write_text("1,100,20\n", encoding="utf-8")
            artifacts[mode] = {"events_path": book.name, "events_sha256": _hash(book),
                               "weights_path": lut.name, "weights_sha256": _hash(lut)}
        manifest["publish_artifacts"] = artifacts
        path = self.root / "generator_input_manifest.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        return path

    def test_contract_has_exactly_58_unique_fields(self):
        self.assertEqual(len(REQUIRED_FIELDS), 58)
        self.assertEqual(len(set(REQUIRED_FIELDS)), 58)

    def test_missing_canonical_manifest_reports_all_58_fields(self):
        report = inspect_manifest(self.root / "missing-canonical-manifest.json")
        self.assertEqual(report["status"], "BLOCKED")
        self.assertEqual(len(report["missing_fields"]), 58)
        self.assertIn("CANONICAL_MANIFEST_MISSING", {x["code"] for x in report["issues"]})

    def test_partial_manifest_blocks_and_lists_all_missing_fields(self):
        path = self.root / "partial.json"
        path.write_text(json.dumps({"status": "PARTIAL_EVIDENCE_ONLY_NOT_CANONICAL_OR_APPROVED"}))
        report = inspect_manifest(path)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertEqual(len(report["missing_fields"]), 58)
        codes = {item["code"] for item in report["issues"]}
        self.assertIn("CANONICAL_SOURCE_STATUS_NOT_VERIFIED", codes)
        self.assertIn("CANONICAL_FIELDS_MISSING", codes)

    def test_valid_manifest_builds_separate_source_and_zip_with_final_recheck(self):
        manifest = self._complete_manifest()
        report = inspect_manifest(manifest)
        self.assertEqual(report["status"], "PASS", report["issues"])
        out_dir, out_zip = self.root / "out-MATH", self.root / "out-MATH.zip"
        built = build_package(manifest, out_dir, out_zip)
        self.assertEqual(built["status"], "PASS", built["issues"])
        self.assertEqual(built["source_math_verification"]["status"], "PASS")
        self.assertEqual(built["zip_verification"]["status"], "PASS")
        self.assertEqual(built["final_directory_verification"]["status"], "PASS")
        self.assertEqual(built["final_zip_verification"]["status"], "PASS")
        self.assertEqual(json.loads((out_dir / "index.json").read_text())["modes"], [
            {"name": "BASE", "cost": 1.0, "events": "books_BASE.jsonl.zst", "weights": "weights_BASE.csv"},
            {"name": "MAGICBUY_V36", "cost": 100.0, "events": "books_MAGICBUY_V36.jsonl.zst", "weights": "weights_MAGICBUY_V36.csv"},
            {"name": "EPICBUY_V37", "cost": 100.0, "events": "books_EPICBUY_V37.jsonl.zst", "weights": "weights_EPICBUY_V37.csv"},
        ])
        no_overwrite = build_package(manifest, out_dir, self.root / "second.zip")
        self.assertEqual(no_overwrite["status"], "BLOCKED")
        self.assertIn("OUTPUT_ALREADY_EXISTS_NO_OVERWRITE", {x["code"] for x in no_overwrite["issues"]})
        second = build_package(manifest, self.root / "out-MATH-2", self.root / "out-MATH-2.zip")
        self.assertEqual(second["status"], "PASS", second["issues"])
        self.assertEqual(built["zip_sha256"], second["zip_sha256"])

    def test_bad_source_hash_blocks_before_any_output(self):
        manifest = self._complete_manifest()
        data = json.loads(manifest.read_text())
        data["generator"]["source_sha256"] = "0" * 64
        manifest.write_text(json.dumps(data))
        out_dir, out_zip = self.root / "blocked-MATH", self.root / "blocked-MATH.zip"
        report = build_package(manifest, out_dir, out_zip)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertFalse(out_dir.exists())
        self.assertFalse(out_zip.exists())
        self.assertIn("SOURCE_HASH_MISMATCH", {x["code"] for x in report["preflight"]["issues"]})

    def test_unsafe_publish_artifact_path_is_rejected(self):
        manifest = self._complete_manifest()
        data = json.loads(manifest.read_text())
        data["publish_artifacts"]["BASE"]["events_path"] = "../outside.jsonl.zst"
        manifest.write_text(json.dumps(data))
        report = inspect_manifest(manifest)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertIn("UNSAFE_SOURCE_PATH", {x["code"] for x in report["issues"]})


def _get(obj, dotted):
    value = obj
    for part in dotted.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


if __name__ == "__main__":
    unittest.main()
