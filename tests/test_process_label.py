from __future__ import annotations

import unittest
from unittest.mock import patch

from src.core.process_label import set_process_description_for_pid


class ProcessLabelTests(unittest.TestCase):
    def test_set_process_description_for_pid_rejects_invalid_pid(self) -> None:
        with patch("src.core.process_label.sys.platform", "win32"):
            self.assertFalse(set_process_description_for_pid(0, "2Wings GUI"))


if __name__ == "__main__":
    unittest.main()
