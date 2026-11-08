import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from qa_source_completeness import classify_source_completeness


class SourceCompletenessDiagnosticTests(unittest.TestCase):
    def test_separates_disk_present_untracked_from_physically_absent_tracked(self):
        with tempfile.TemporaryDirectory(prefix="source-completeness-") as temporary:
            root = Path(temporary)
            (root / "src").mkdir()
            (root / "docs").mkdir()
            (root / "src" / "tracked.py").write_text("tracked\n", encoding="utf-8")
            (root / "src" / "local_only.py").write_text("untracked\n", encoding="utf-8")
            (root / "artifacts").mkdir()
            (root / "artifacts" / "evidence.json").write_text("{}\n", encoding="utf-8")
            (root / "build").mkdir()
            (root / "build" / "generated.py").write_text("generated\n", encoding="utf-8")

            result = classify_source_completeness(
                root,
                ["src/tracked.py", "docs/removed.md"],
            )

            self.assertEqual(result["tracked_missing"], ["docs/removed.md"])
            self.assertEqual(result["tracked_invalid"], [])
            self.assertEqual(result["untracked_required"], ["src/local_only.py"])
            self.assertFalse(result["pass"])
            self.assertNotIn("artifacts/evidence.json", result["untracked_required"])
            self.assertNotIn("build/generated.py", result["untracked_required"])

    def test_historical_qa_evidence_is_not_misclassified_as_product_source(self):
        with tempfile.TemporaryDirectory(prefix="source-completeness-") as temporary:
            root = Path(temporary)
            evidence = root / "qa/work_20261106_submission_repair_r1"
            evidence.mkdir(parents=True)
            (evidence / "REPAIR_AND_REVALIDATION_REPORT.md").write_text("historical\n", encoding="utf-8")
            (evidence / "SHA256SUMS.txt").write_text("checksum\n", encoding="utf-8")
            result = classify_source_completeness(root, [])
            self.assertEqual(result["untracked_required"], [])

    def test_verified_snapshot_exclusion_does_not_grant_general_registration(self):
        with tempfile.TemporaryDirectory(prefix="source-completeness-") as temporary:
            root = Path(temporary)
            snapshot = root / "frontend" / "artifacts" / "FRONTEND_BUILD_TEST"
            snapshot.mkdir(parents=True)
            bundle = snapshot / "bundle.js"
            bundle.write_text("bundle\n", encoding="utf-8")
            manifest = {
                "schema": "ganesha.generated-frontend-snapshot-integrity.v1",
                "snapshot": "frontend/artifacts/FRONTEND_BUILD_TEST",
                "files": [{
                    "path": "bundle.js",
                    "sha256": hashlib.sha256(bundle.read_bytes()).hexdigest(),
                    "bytes": bundle.stat().st_size,
                }],
            }
            (snapshot / "snapshot.integrity.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            (root / "frontend" / "artifacts" / "ordinary.py").write_text("source\n", encoding="utf-8")

            result = classify_source_completeness(root, [])

            self.assertEqual(result["untracked_required"], ["frontend/artifacts/ordinary.py"])
            self.assertFalse(result["pass"])


if __name__ == "__main__":
    unittest.main()
