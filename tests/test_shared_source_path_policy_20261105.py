import ast
import tempfile
import unittest
from pathlib import Path

from qa_source_completeness import _is_excluded
from tools.source_path_policy import is_excluded_source_path


ROOT = Path(__file__).resolve().parents[1]


class SharedSourcePathPolicyTests(unittest.TestCase):
    def test_common_exclusions_have_identical_decisions_in_both_consumers(self):
        paths = (
            ".git/config",
            "pkg/__pycache__/module.pyc",
            "build/generated.py",
            "vendor/example.egg-info/PKG-INFO",
            "artifacts/CI_EVIDENCE.json",
            "frontend/config.js",
            "docs/.DS_Store",
            "state/cache.sqlite-wal",
            "artifacts/BASELINE.md",
            "src/ordinary.py",
        )
        for relative in paths:
            with self.subTest(relative=relative):
                self.assertEqual(
                    is_excluded_source_path(relative),
                    _is_excluded(relative, Path(relative)),
                )

    def test_egg_info_ancestor_outside_repository_cannot_exclude_repo_paths(self):
        with tempfile.TemporaryDirectory(prefix="checkout.egg-info-") as temporary:
            repository = Path(temporary) / "project"
            source = repository / "src" / "module.py"
            self.assertFalse(is_excluded_source_path("src/module.py"))
            self.assertFalse(_is_excluded("src/module.py", source))

    def test_baseline_remains_required_while_other_artifacts_are_excluded(self):
        self.assertFalse(is_excluded_source_path("artifacts/BASELINE.md"))
        self.assertTrue(is_excluded_source_path("artifacts/CI_EVIDENCE.json"))

    def test_release_gate_and_diagnostic_call_the_same_shared_policy(self):
        gate = ast.parse((ROOT / "qa_release_gate.py").read_text(encoding="utf-8"))
        diagnostic = ast.parse((ROOT / "qa_source_completeness.py").read_text(encoding="utf-8"))

        def imports_shared_policy(tree):
            return any(
                isinstance(node, ast.ImportFrom)
                and node.module == "tools.source_path_policy"
                and any(alias.name == "is_excluded_source_path" for alias in node.names)
                for node in ast.walk(tree)
            )

        def calls_shared_policy(tree):
            return any(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "is_excluded_source_path"
                for node in ast.walk(tree)
            )

        self.assertTrue(imports_shared_policy(gate))
        self.assertTrue(imports_shared_policy(diagnostic))
        self.assertTrue(calls_shared_policy(gate))
        self.assertTrue(calls_shared_policy(diagnostic))


if __name__ == "__main__":
    unittest.main()
