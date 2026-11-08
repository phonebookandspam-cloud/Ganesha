import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.verify_sbom_completeness_20261104 import (
    REQUIRED_WAVS,
    SBOMCompletenessError,
    verify_sbom,
)


class SBOMCompletenessVerifierTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "frontend/assets/sfx").mkdir(parents=True)
        (self.root / "requirements-build.txt").write_text("build==1.4.4\nsetuptools==82.0.1\n", encoding="utf-8")
        (self.root / "requirements-test.txt").write_text("zstandard==0.25.0\n", encoding="utf-8")
        lock = {
            "lockfileVersion": 3,
            "packages": {
                "": {"name": "fixture"},
                "node_modules/stake-engine": {"version": "0.1.32"},
                "node_modules/@scope/tool": {"version": "2.3.4"},
            },
        }
        (self.root / "package-lock.json").write_text(json.dumps(lock), encoding="utf-8")
        self.assets = []
        for name in sorted(REQUIRED_WAVS | {"icon.svg"}):
            data = ("asset:" + name).encode()
            path = self.root / "frontend/assets" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            self.assets.append({"file": name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
        (self.root / "frontend/assets/ASSET_PROVENANCE.json").write_text(
            json.dumps({"schema": "fixture", "assets": self.assets}), encoding="utf-8"
        )
        components = [
            {"type": "library", "bom-ref": "pkg:npm/stake-engine@0.1.32", "purl": "pkg:npm/stake-engine@0.1.32", "name": "stake-engine", "version": "0.1.32"},
            {"type": "library", "bom-ref": "pkg:npm/%40scope/tool@2.3.4", "purl": "pkg:npm/%40scope/tool@2.3.4", "name": "@scope/tool", "version": "2.3.4"},
            {"type": "library", "bom-ref": "pkg:pypi/build@1.4.4", "purl": "pkg:pypi/build@1.4.4", "name": "build", "version": "1.4.4"},
            {"type": "library", "bom-ref": "pkg:pypi/setuptools@82.0.1", "purl": "pkg:pypi/setuptools@82.0.1", "name": "setuptools", "version": "82.0.1"},
            {"type": "library", "bom-ref": "pkg:pypi/zstandard@0.25.0", "purl": "pkg:pypi/zstandard@0.25.0", "name": "zstandard", "version": "0.25.0"},
        ]
        for asset in self.assets:
            ref = "urn:sha256:" + asset["sha256"]
            components.append({"type": "file", "bom-ref": ref, "name": asset["file"],
                               "hashes": [{"alg": "SHA-256", "content": asset["sha256"]}]})
        self.sbom = {"bomFormat": "CycloneDX", "specVersion": "1.5", "components": components}
        self.sbom_path = self.root / "fixture.sbom.json"
        self.write_sbom()

    def tearDown(self):
        self.temp.cleanup()

    def write_sbom(self):
        self.sbom_path.write_text(json.dumps(self.sbom), encoding="utf-8")

    def test_complete_fixture_covers_npm_python_all_assets_and_four_wavs(self):
        result = verify_sbom(self.sbom_path, self.root)
        self.assertEqual(result, {"npm_components": 2, "python_build_components": 2,
                                  "python_test_components": 1, "shipped_assets": 5, "required_wavs": 4})

    def test_missing_locked_npm_component_fails_closed(self):
        self.sbom["components"] = [c for c in self.sbom["components"] if c.get("purl") != "pkg:npm/stake-engine@0.1.32"]
        self.write_sbom()
        with self.assertRaisesRegex(SBOMCompletenessError, "locked npm"):
            verify_sbom(self.sbom_path, self.root)

    def test_missing_pinned_python_component_fails_closed(self):
        self.sbom["components"] = [c for c in self.sbom["components"] if c.get("purl") != "pkg:pypi/build@1.4.4"]
        self.write_sbom()
        with self.assertRaisesRegex(SBOMCompletenessError, "pinned Python"):
            verify_sbom(self.sbom_path, self.root)

    def test_missing_pinned_python_test_component_fails_closed(self):
        self.sbom["components"] = [c for c in self.sbom["components"]
                                   if c.get("purl") != "pkg:pypi/zstandard@0.25.0"]
        self.write_sbom()
        with self.assertRaisesRegex(SBOMCompletenessError, "pinned Python test"):
            verify_sbom(self.sbom_path, self.root)

    def test_missing_one_of_four_wavs_fails_closed(self):
        missing = "sfx/win.wav"
        self.sbom["components"] = [c for c in self.sbom["components"] if c.get("name") != missing]
        self.write_sbom()
        with self.assertRaisesRegex(SBOMCompletenessError, "omits shipped asset"):
            verify_sbom(self.sbom_path, self.root)

    def test_unlisted_shipped_file_fails_closed(self):
        (self.root / "frontend/assets/new-shipped.svg").write_text("<svg/>", encoding="utf-8")
        with self.assertRaisesRegex(SBOMCompletenessError, "exact shipped asset inventory"):
            verify_sbom(self.sbom_path, self.root)

    def test_asset_hash_mismatch_fails_closed(self):
        (self.root / "frontend/assets/sfx/win.wav").write_bytes(b"changed")
        with self.assertRaisesRegex(SBOMCompletenessError, "provenance hash/size mismatch"):
            verify_sbom(self.sbom_path, self.root)

    def test_duplicate_component_reference_fails_closed(self):
        self.sbom["components"].append(copy.deepcopy(self.sbom["components"][0]))
        self.write_sbom()
        with self.assertRaisesRegex(SBOMCompletenessError, "duplicate SBOM bom-ref"):
            verify_sbom(self.sbom_path, self.root)

    def test_cli_requires_explicit_sbom_and_emits_no_report_file(self):
        report = self.root / "must-not-exist.json"
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parents[1] / "tools/verify_sbom_completeness_20261104.py"),
             "--sbom", str(self.sbom_path), "--root", str(self.root)],
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("SBOM_COMPLETENESS=PASS", proc.stdout)
        self.assertFalse(report.exists())


if __name__ == "__main__":
    unittest.main()
