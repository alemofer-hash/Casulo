from __future__ import annotations

import hashlib
import importlib.util
import io
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "normalize_sdist",
    ROOT / "tools" / "normalize_sdist.py",
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ReproducibleReleaseTests(unittest.TestCase):
    def test_normalizer_removes_build_time_from_sdist(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "first.tar.gz"
            second = root / "second.tar.gz"
            self._write_sdist(first, mtime=100)
            self._write_sdist(second, mtime=200)
            MODULE.normalize_sdist(first, epoch=42)
            MODULE.normalize_sdist(second, epoch=42)
            first_hash = hashlib.sha256(first.read_bytes()).hexdigest()
            second_hash = hashlib.sha256(second.read_bytes()).hexdigest()
        self.assertEqual(first_hash, second_hash)

    @staticmethod
    def _write_sdist(path: Path, mtime: int) -> None:
        content = b"Casulo\n"
        info = tarfile.TarInfo("casulo/example.txt")
        info.size = len(content)
        info.mtime = mtime
        with tarfile.open(path, "w:gz") as archive:
            archive.addfile(info, io.BytesIO(content))


if __name__ == "__main__":
    unittest.main()
