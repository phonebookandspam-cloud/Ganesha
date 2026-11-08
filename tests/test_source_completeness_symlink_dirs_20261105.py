import tempfile
import unittest
from pathlib import Path

from qa_source_completeness import classify_source_completeness


class SourceCompletenessSymlinkDirectoryTests(unittest.TestCase):
    def test_untracked_directory_symlink_is_not_silently_omitted(self):
        with tempfile.TemporaryDirectory(prefix="source-completeness-symlink-") as temporary:
            parent = Path(temporary)
            root = parent / "workspace"
            source = root / "src"
            source.mkdir(parents=True)
            external = parent / "external-source"
            external.mkdir()
            (external / "unregistered.py").write_text("source\n", encoding="utf-8")
            (source / "linked-source").symlink_to(external, target_is_directory=True)

            result = classify_source_completeness(root, [])

            self.assertFalse(result["pass"])
            self.assertEqual(result["untracked_required"], ["src/linked-source"])

    def test_tracked_directory_symlink_is_classified_as_invalid(self):
        with tempfile.TemporaryDirectory(prefix="source-completeness-symlink-") as temporary:
            root = Path(temporary)
            external = root / "external-source"
            external.mkdir()
            (root / "linked-source").symlink_to(external, target_is_directory=True)

            result = classify_source_completeness(root, ["linked-source"])

            self.assertFalse(result["pass"])
            self.assertEqual(result["tracked_invalid"], ["linked-source"])


if __name__ == "__main__":
    unittest.main()
