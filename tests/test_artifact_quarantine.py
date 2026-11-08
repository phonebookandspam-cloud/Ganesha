import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from ganesha.math.artifact_quarantine import RELEASE_STATUS
from ganesha.math.artifact_writers import (
    write_crosscheck_report,
    write_exact_report,
    write_monte_carlo_report,
)

ROOT = Path(__file__).resolve().parents[1]


class ArtifactQuarantineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.artifacts = Path(self.temp.name) / "artifacts"
        self.artifacts.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def assert_quarantined(self, path, expected_scope_fragment):
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["release_status"], RELEASE_STATUS)
        self.assertIs(data["public_claims_permitted"], False)
        self.assertIn(expected_scope_fragment, data["scope"])
        return data

    def test_each_writer_path_stamps_sentinel_and_preserves_numeric_payload(self):
        cases = (
            (write_exact_report, "math_audit_v1_draft_only.json", "Fail-closed full-round", "rtp_percent"),
            (write_monte_carlo_report, "monte_carlo_v1_draft_only.json", "No simulation is run", "observed_rtp_percent"),
            (write_crosscheck_report, "math_crosscheck_v1_draft_only.json", "comparison", "diagnostic_value"),
        )
        for writer, filename, scope, numeric_key in cases:
            with self.subTest(writer=writer.__name__):
                original = {numeric_key: 96.501234, "nested": {"value": 123},
                            "release_status": "APPROVED", "public_claims_permitted": True}
                path = writer(original, self.artifacts / filename)
                result = self.assert_quarantined(path, scope)
                self.assertEqual(result[numeric_key], 96.501234)
                self.assertEqual(result["nested"], {"value": 123})
                self.assertEqual(original["release_status"], "APPROVED")  # caller data is not mutated

    def test_every_writer_refuses_protected_release_artifact_names_without_overwrite(self):
        protected = (
            "math_audit_v1.json",
            "monte_carlo_v1.json",
            "math_crosscheck_v1.json",
        )
        writers = (write_exact_report, write_monte_carlo_report, write_crosscheck_report)
        for writer in writers:
            for filename in protected:
                with self.subTest(writer=writer.__name__, filename=filename):
                    target = self.artifacts / filename
                    original = b'{"release_status":"SUPERSEDED_NOT_RELEASE_EVIDENCE","keep":7}\n'
                    target.write_bytes(original)
                    with self.assertRaises(ValueError):
                        writer({"rtp_percent": 99.0}, target)
                    self.assertEqual(target.read_bytes(), original)

    def test_writer_refuses_to_overwrite_existing_draft_artifact(self):
        target = self.artifacts / "preserved_draft_only.json"
        original = b'{"preserve":true}\n'
        target.write_bytes(original)
        with self.assertRaises(ValueError):
            write_monte_carlo_report({"sample_run_performed": False}, target)
        self.assertEqual(target.read_bytes(), original)

    def test_writer_rejects_non_draft_names_wrong_directory_and_symlink(self):
        with self.assertRaises(ValueError):
            write_monte_carlo_report({}, self.artifacts / "monte_carlo_v1.json")
        with self.assertRaises(ValueError):
            write_monte_carlo_report({}, Path(self.temp.name) / "monte_carlo_v1_draft_only.json")
        real = self.artifacts / "real_draft_only.json"
        real.write_text("{}", encoding="utf-8")
        link = self.artifacts / "linked_draft_only.json"
        link.symlink_to(real)
        with self.assertRaises(ValueError):
            write_monte_carlo_report({}, link)

    def test_make_math_audit_is_fail_closed_and_draft_target_is_separate(self):
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        self.assertIn("math-audit:", makefile)
        self.assertIn("exit 2", makefile)
        self.assertIn("math-audit-draft:", makefile)
        self.assertIn("math_audit_v1_draft_only.json", (ROOT / "src/ganesha/math/artifact_writers.py").read_text(encoding="utf-8"))
        result = subprocess.run(["make", "math-audit"], cwd=str(ROOT), text=True, capture_output=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("BLOCKED", result.stdout)

    def test_monte_carlo_cli_no_longer_accepts_unapproved_buy_round_counts(self):
        source = (ROOT / "qa_run_math.py").read_text(encoding="utf-8")
        self.assertNotIn("--magic-rounds", source)
        self.assertNotIn("--epic-rounds", source)
        self.assertIn("report = run_monte_carlo()", source)

    def test_cli_output_override_cannot_target_primary_artifact(self):
        source = (ROOT / "qa_run_math.py").read_text(encoding="utf-8")
        self.assertIn("write_monte_carlo_report(report, args.output)", source)
        # Exercise the exact writer used by --output, not merely source text.
        target = self.artifacts / "monte_carlo_v1.json"
        target.write_text('{"keep":true}\n', encoding="utf-8")
        before = target.read_bytes()
        with self.assertRaises(ValueError):
            write_monte_carlo_report({"rounds": 1}, target)
        self.assertEqual(target.read_bytes(), before)

    def test_legacy_superseded_artifacts_have_uniform_sentinel(self):
        for name in ("math_audit_v1_draft003_SUPERSEDED.json", "monte_carlo_v1_pre_jackpot_SUPERSEDED.json"):
            data = json.loads((ROOT / "artifacts" / name).read_text(encoding="utf-8"))
            self.assertEqual(data["release_status"], RELEASE_STATUS)
            self.assertIs(data["public_claims_permitted"], False)

    def test_primary_artifacts_remain_quarantined(self):
        for name in ("math_audit_v1.json", "math_crosscheck_v1.json", "monte_carlo_v1.json"):
            data = json.loads((ROOT / "artifacts" / name).read_text(encoding="utf-8"))
            self.assertEqual(data["release_status"], RELEASE_STATUS)
            self.assertIn("release_blockers", data)


if __name__ == "__main__":
    unittest.main()
