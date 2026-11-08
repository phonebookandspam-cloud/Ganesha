import gzip
import hashlib
import io
import tarfile
import tempfile
import unittest
from pathlib import Path

from tools.normalize_sdist import normalize_sdist


class BuildReproducibilityTests(unittest.TestCase):
    def _make_archive(self, path, mtime):
        with tarfile.open(str(path), "w:gz") as archive:
            directory = tarfile.TarInfo("package/")
            directory.type = tarfile.DIRTYPE
            directory.mtime = mtime
            archive.addfile(directory)
            data = b"source content\n"
            file_info = tarfile.TarInfo("package/source.txt")
            file_info.size = len(data)
            file_info.mtime = mtime
            archive.addfile(file_info, io.BytesIO(data))

    def test_normalized_source_archives_are_byte_identical(self):
        with tempfile.TemporaryDirectory() as temporary:
            first = Path(temporary) / "first.tar.gz"
            second = Path(temporary) / "second.tar.gz"
            self._make_archive(first, 1700000000)
            self._make_archive(second, 1800000000)
            normalize_sdist(first, 1700000000)
            normalize_sdist(second, 1700000000)
            digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(digest(first), digest(second))

    def test_normalizer_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive_path = Path(temporary) / "unsafe.tar.gz"
            with tarfile.open(str(archive_path), "w:gz") as archive:
                data = b"bad"
                info = tarfile.TarInfo("../escape.txt")
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
            with self.assertRaises(ValueError):
                normalize_sdist(archive_path, 1700000000)


if __name__ == "__main__":
    unittest.main()
