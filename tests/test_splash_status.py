from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.modules.updates.splash_status import read_update_status, write_update_status


class SplashStatusTests(unittest.TestCase):
    def test_write_and_read_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch("src.modules.updates.splash_status.temp_dir", return_value=root):
                write_update_status("downloading", "Скачивание...", target_version="1.2.3")
                payload = read_update_status()
            self.assertEqual(payload["phase"], "downloading")
            self.assertEqual(payload["message"], "Скачивание...")
            self.assertEqual(payload["target_version"], "1.2.3")


if __name__ == "__main__":
    unittest.main()
