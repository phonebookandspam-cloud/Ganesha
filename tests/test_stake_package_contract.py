import json
import tempfile
import unittest
import zipfile
from pathlib import Path

import zstandard

from tools.verify_stake_package import (
    verify_frontend_directory, verify_frontend_zip, verify_math_directory,
    verify_math_zip,
)


class StakePackageContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _math_package(self, payout_csv="1,100,20\n", payout_book=20, event_rows=None):
        root = self.root / "math"
        root.mkdir(exist_ok=True)
        (root / "index.json").write_text(json.dumps({"modes": [{
            "name": "base", "cost": 1.0, "events": "books_base.jsonl.zst", "weights": "lookup_base.csv"
        }]}), encoding="utf-8")
        (root / "lookup_base.csv").write_text(payout_csv, encoding="utf-8")
        record = {"id": 1, "events": event_rows if event_rows is not None else [{"type": "test-event"}],
                  "payoutMultiplier": payout_book}
        compressed = zstandard.ZstdCompressor().compress((json.dumps(record) + "\n").encode("utf-8"))
        (root / "books_base.jsonl.zst").write_bytes(compressed)
        return root

    def test_math_directory_requires_root_index_json(self):
        root = self.root / "missing-index"
        root.mkdir()
        report = verify_math_directory(root)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertIn("ERR_MISSING_FILE", {item["code"] for item in report["issues"]})

    def test_math_directory_checks_books_lut_ids_and_payouts_exactly(self):
        report = verify_math_directory(self._math_package())
        self.assertEqual(report["status"], "PASS", report["issues"])
        self.assertEqual(report["modes"][0]["outcomes"], 1)
        mismatch = verify_math_directory(self._math_package("1,100,30\n", payout_book=20))
        self.assertIn("PAYOUT_MULTIPLIER_MISMATCH", {item["code"] for item in mismatch["issues"]})

    def test_math_lookup_rejects_header_and_non_uint64_rows(self):
        header = verify_math_directory(self._math_package("simulation_number,round_probability,payout_multiplier\n1,100,20\n"))
        self.assertIn("INVALID_LOOKUP_TABLE", {item["code"] for item in header["issues"]})
        overflow = verify_math_directory(self._math_package("1,18446744073709551616,20\n"))
        self.assertIn("INVALID_LOOKUP_TABLE", {item["code"] for item in overflow["issues"]})

    def test_math_directory_rejects_empty_modes_and_path_traversal(self):
        root = self._math_package()
        index = root / "index.json"
        index.write_text('{"modes":[]}', encoding="utf-8")
        self.assertIn("EMPTY_MODES", {item["code"] for item in verify_math_directory(root)["issues"]})
        index.write_text(json.dumps({"modes": [{"name": "base", "cost": 1.0,
            "events": "../books.jsonl.zst", "weights": "lookup_base.csv"}]}), encoding="utf-8")
        self.assertIn("UNSAFE_REFERENCE", {item["code"] for item in verify_math_directory(root)["issues"]})

    def test_math_zip_requires_index_at_extraction_root_and_checks_crc(self):
        root = self._math_package()
        zip_path = self.root / "nested-math.zip"
        with zipfile.ZipFile(zip_path, "w") as archive:
            for path in root.iterdir():
                archive.write(path, "MATH/" + path.name)
        report = verify_math_zip(zip_path)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertIn("ERR_MISSING_FILE", {item["code"] for item in report["issues"]})

    def _frontend_package(self):
        root = self.root / "front"
        assets = root / "assets"
        assets.mkdir(parents=True)
        (root / "index.html").write_text('<html><head><link rel="stylesheet" href="assets/app.css"></head><body><script type="module" src="assets/app.js"></script></body></html>', encoding="utf-8")
        (assets / "app.css").write_text('body{background:url("./tile.svg")}', encoding="utf-8")
        (assets / "tile.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"></svg>', encoding="utf-8")
        (assets / "app.js").write_text("const launch = ['sessionID','rgs_url','lang','device'];", encoding="utf-8")
        (root / "manifest.json").write_text(json.dumps({
            "schema": "ganesha.frontend-engineering-manifest.v1",
            "package_kind": "STAKE_ENGINE_RELEASE_CANDIDATE",
            "entrypoint": "index.html",
            "provider_sdk": {"status": "FULL_RGS_ROUND_LIFECYCLE"},
            "capabilities": {"provider_authenticate": "FULL", "play": True, "end_round": True,
                "event": True, "wagering": True, "bonus_buy": True,
                "outcome_mutation_by_frontend": False}
        }), encoding="utf-8")
        return root

    def test_frontend_directory_requires_static_root_and_all_local_refs(self):
        root = self._frontend_package()
        report = verify_frontend_directory(root)
        self.assertEqual(report["status"], "PASS", report["issues"])
        (root / "assets/app.css").write_text('body{background:url("./missing.svg")}', encoding="utf-8")
        broken = verify_frontend_directory(root)
        self.assertIn("MISSING_ASSET_REFERENCE", {item["code"] for item in broken["issues"]})

    def test_frontend_directory_blocks_missing_rgs_calls_and_external_origins(self):
        root = self._frontend_package()
        (root / "assets/app.js").write_text("fetch('https://hardcoded.example/api');", encoding="utf-8")
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        manifest["package_kind"] = "NON_FINANCIAL_ENGINEERING_PREVIEW"
        manifest["provider_sdk"]["status"] = "BETA_READ_ONLY_AUTHENTICATE_ONLY"
        for capability in ("play", "end_round", "event", "wagering", "bonus_buy"):
            manifest["capabilities"][capability] = False
        (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        report = verify_frontend_directory(root)
        codes = {item["code"] for item in report["issues"]}
        self.assertIn("HARDCODED_EXTERNAL_ORIGIN", codes)
        self.assertIn("RGS_CAPABILITY_NOT_IMPLEMENTED", codes)
        self.assertIn("RGS_ADAPTER_NOT_PRODUCTION_READY", codes)
        self.assertIn("MISSING_LAUNCH_PARAMETER", codes)

    def test_frontend_zip_is_rechecked_after_extraction(self):
        root = self._frontend_package()
        zip_path = self.root / "front.zip"
        with zipfile.ZipFile(zip_path, "w") as archive:
            for path in root.rglob("*"):
                if path.is_file():
                    archive.write(path, path.relative_to(root).as_posix())
        report = verify_frontend_zip(zip_path)
        self.assertEqual(report["status"], "PASS", report["issues"])


if __name__ == "__main__":
    unittest.main()
