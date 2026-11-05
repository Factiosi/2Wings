from __future__ import annotations

import subprocess
import unittest
from unittest.mock import MagicMock, patch

from src.daemon import ui_launcher


class LaunchGuiTests(unittest.TestCase):
    def setUp(self) -> None:
        ui_launcher._gui_pids.clear()
        ui_launcher._gui_processes.clear()
        ui_launcher._last_gui_spawn = 0.0
        self.addCleanup(ui_launcher._gui_processes.clear)
        self.addCleanup(ui_launcher._gui_pids.clear)

    def _popen(self):
        proc = MagicMock(pid=4242)
        proc.poll.return_value = None
        return patch.object(ui_launcher.subprocess, "Popen", return_value=proc)

    def test_window_process_is_not_told_to_hide_its_window(self) -> None:
        with self._popen() as popen:
            ok, _message = ui_launcher.launch_gui()
        self.assertTrue(ok)
        self.assertNotIn("startupinfo", popen.call_args.kwargs)

    def test_background_process_stays_hidden(self) -> None:
        _cmd, kwargs = ui_launcher._spawn_args("--daemon")
        self.assertEqual(kwargs["startupinfo"].wShowWindow, subprocess.SW_HIDE)

    def test_repeated_clicks_start_one_window(self) -> None:
        with self._popen() as popen, patch("src.core.win32_window.raise_window_of_processes", return_value=False):
            ui_launcher.launch_gui()
            ui_launcher.launch_gui()
        popen.assert_called_once()

    def test_open_window_is_raised_instead_of_a_new_one(self) -> None:
        ui_launcher._gui_pids.add(77)
        with self._popen() as popen, patch("src.core.win32_window.raise_window_of_processes", return_value=True) as raised:
            ok, _message = ui_launcher.launch_gui()
        self.assertTrue(ok)
        raised.assert_called_once_with({77})
        popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
