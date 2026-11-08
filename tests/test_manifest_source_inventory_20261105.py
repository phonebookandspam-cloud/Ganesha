import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.verify_manifest_source_inventory import verify_manifest_source_inventory


class ManifestSourceInventoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="manifest-source-tree-")
        self.root = Path(self.temporary.name)
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=self.root, check=True)
        (self.root / "src").mkdir()
        (self.root / "src" / "one.py").write_bytes(b"one\n")
        (self.root / "src" / "two.py").write_bytes(b"two\n")
        subprocess.run(["git", "add", "src"], cwd=self.root, check=True)
        subprocess.run(["git", "commit", "-qm", "fixture"], cwd=self.root, check=True)
        self.commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=self.root, text=True
        ).strip()
        self.inventory = {
            "src/one.py": hashlib.sha256(b"one\n").hexdigest(),
            "src/two.py": hashlib.sha256(b"two\n").hexdigest(),
        }

    def tearDown(self):
        self.temporary.cleanup()

    def test_exact_committed_inventory_passes_even_if_worktree_differs(self):
        (self.root / "src" / "one.py").write_bytes(b"worktree mutation\n")
        self.assertEqual(
            verify_manifest_source_inventory(self.root, self.commit, self.inventory),
            (True, "manifest source paths and SHA-256 values match exact commit blobs"),
        )

    def test_missing_extra_and_stale_source_entries_fail_closed(self):
        missing = {"src/one.py": self.inventory["src/one.py"]}
        extra = dict(self.inventory, **{"src/extra.py": self.inventory["src/one.py"]})
        stale = dict(self.inventory, **{"src/one.py": "0" * 64})
        self.assertFalse(verify_manifest_source_inventory(self.root, self.commit, missing)[0])
        self.assertFalse(verify_manifest_source_inventory(self.root, self.commit, extra)[0])
        self.assertFalse(verify_manifest_source_inventory(self.root, self.commit, stale)[0])


if __name__ == "__main__":
    unittest.main()
