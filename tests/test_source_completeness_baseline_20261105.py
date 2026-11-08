import tempfile
import unittest
from pathlib import Path

from qa_source_completeness import classify_source_completeness


class SourceCompletenessBaselineTests(unittest.TestCase):
    def test_manifest_required_artifact_baseline_is_untracked_required_not_excluded(self):
        with tempfile.TemporaryDirectory(prefix="source-completeness-baseline-") as temporary:
            root = Path(temporary)
            artifacts = root / "artifacts"
            artifacts.mkdir()
            (artifacts / "BASELINE.md").write_text("required source\n", encoding="utf-8")
            (artifacts / "CI_EVIDENCE.json").write_text("{}\n", encoding="utf-8")

            result = classify_source_completeness(root, [])

            self.assertFalse(result["pass"])
            self.assertEqual(result["untracked_required"], ["artifacts/BASELINE.md"])
            self.assertEqual(result["tracked_missing"], [])
            self.assertEqual(result["tracked_invalid"], [])


if __name__ == "__main__":
    unittest.main()
