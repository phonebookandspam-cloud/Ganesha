import ast
import unittest
from pathlib import Path

from tools.source_path_policy import is_excluded_artifact_path


ROOT = Path(__file__).resolve().parents[1]


class RequiredSourceBaselineTests(unittest.TestCase):
    def test_manifest_declared_baseline_is_not_silently_excluded(self):
        manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8").splitlines()
        self.assertIn("include artifacts/BASELINE.md", manifest)
        self.assertTrue((ROOT / "artifacts/BASELINE.md").is_file())
        self.assertFalse(is_excluded_artifact_path("artifacts/BASELINE.md"))
        self.assertTrue(is_excluded_artifact_path("artifacts/CI_EVIDENCE.json"))

    def test_release_gate_uses_the_corrected_artifact_exclusion_policy(self):
        source = (ROOT / "qa_release_gate.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports_policy = any(
            isinstance(node, ast.ImportFrom)
            and node.module == "tools.source_path_policy"
            and any(alias.name == "is_excluded_artifact_path" for alias in node.names)
            for node in ast.walk(tree)
        )
        invokes_policy = any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "is_excluded_artifact_path"
            for node in ast.walk(tree)
        )
        self.assertTrue(imports_policy and invokes_policy)

    def test_source_completeness_runs_in_clean_clone_ci_and_is_in_sdist(self):
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")

        self.assertIn("source-completeness:", makefile)
        self.assertIn("PYTHON ?= python3", makefile)
        self.assertIn("$(PYTHON) qa_source_completeness.py", makefile)
        self.assertIn("run: make source-completeness", workflow)
        self.assertIn("include qa_source_completeness.py", manifest)


if __name__ == "__main__":
    unittest.main()
