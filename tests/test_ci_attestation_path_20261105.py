"""Regression tests for exact release-manifest attestation path wiring."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class CiAttestationPathTests(unittest.TestCase):
    def test_attestation_action_uses_resolved_step_output_not_shell_substitution(self):
        workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertIn("id: release_manifest_path", workflow)
        self.assertIn('path=dist/$(git rev-parse --short HEAD)/RELEASE_MANIFEST.json', workflow)
        self.assertIn(
            "subject-path: ${{ steps.release_manifest_path.outputs.path }}", workflow
        )
        self.assertNotIn(
            "subject-path: dist/$(git rev-parse --short HEAD)/RELEASE_MANIFEST.json",
            workflow,
        )

    def test_source_distribution_includes_required_node_qa_tools(self):
        manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")
        self.assertIn("recursive-include tools *.mjs", manifest)


if __name__ == "__main__":
    unittest.main()
