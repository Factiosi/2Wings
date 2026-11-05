from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.modules.updates import splash_launcher
from src.update_splash.worker import _expected_sum, _install_fraction


class UpdaterCopyTests(unittest.TestCase):
    def test_copies_bundled_updater_once_and_drops_old_revisions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundled = root / "Program Files" / "2Wings" / "updater"
            bundled.mkdir(parents=True)
            (bundled / "TwoWingsUpdate.exe").write_bytes(b"new")
            local = root / "Local" / "2Wings" / "updater"
            (local / "1").mkdir(parents=True)
            with (
                patch.object(splash_launcher, "bundled_updater_dir", return_value=bundled),
                patch.object(splash_launcher, "updater_root", return_value=local),
            ):
                exe = splash_launcher.ensure_updater()
                self.assertEqual(exe, local / str(splash_launcher.UPDATER_REVISION) / "TwoWingsUpdate.exe")
                self.assertEqual(exe.read_bytes(), b"new")
                self.assertFalse((local / "1").exists())
                # Повторный запуск не трогает копию, даже если в Program Files лежит другая.
                (bundled / "TwoWingsUpdate.exe").write_bytes(b"newer")
                self.assertEqual(splash_launcher.ensure_updater().read_bytes(), b"new")

    def test_missing_bundled_updater(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (
                patch.object(splash_launcher, "bundled_updater_dir", return_value=root / "none"),
                patch.object(splash_launcher, "updater_root", return_value=root / "local"),
            ):
                self.assertIsNone(splash_launcher.ensure_updater())


class UpdaterWorkerTests(unittest.TestCase):
    def test_install_progress_from_inno(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "install-progress.txt"
            self.assertIsNone(_install_fraction(path))
            path.write_text("250 1000", encoding="ascii")
            self.assertEqual(_install_fraction(path), 0.25)
            path.write_text("garbage", encoding="ascii")
            self.assertIsNone(_install_fraction(path))

    def test_checksum_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.sha256"
            path.write_text("AB" * 32 + "  2Wings-Setup-1.5.2.exe\n", encoding="utf-8")
            self.assertEqual(_expected_sum(path), "ab" * 32)
            path.write_text("nope", encoding="utf-8")
            with self.assertRaises(ValueError):
                _expected_sum(path)


if __name__ == "__main__":
    unittest.main()
