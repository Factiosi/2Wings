from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from src.kernel import process, windivert_cleanup, winws_runner


class KillTests(unittest.TestCase):
    def test_leftover_winws2_is_killed_and_awaited(self) -> None:
        # The engine left by the previous version must be gone before the service is deleted.
        pids = [[25236], [25236], []]
        with (
            patch.object(process, "find_canonical_winws_pids", side_effect=pids),
            patch.object(process, "_taskkill", return_value=True) as taskkill,
            patch.object(process.time, "sleep"),
        ):
            self.assertTrue(process.kill_winws())
        taskkill.assert_any_call("/PID", "25236")


class CleanupTests(unittest.TestCase):
    def test_waits_until_the_service_is_really_gone(self) -> None:
        calls: list[list[str]] = []
        queries = {"WinDivert": [0, 0, 0, 1060], "WinDivert14": [1060]}

        def run(args, **_kwargs):
            calls.append(args)
            code = queries[args[2]].pop(0) if args[:2] == ["sc", "query"] else 0
            return MagicMock(returncode=code)

        with patch.object(windivert_cleanup.subprocess, "run", side_effect=run), patch.object(windivert_cleanup.time, "sleep"):
            windivert_cleanup.cleanup_windivert_services()
        self.assertEqual(queries["WinDivert"], [])
        self.assertIn(["sc", "delete", "WinDivert"], calls)
        self.assertNotIn(["sc", "delete", "WinDivert14"], calls)


class RetryTests(unittest.TestCase):
    def _start(self, results):
        runner = winws_runner.WinwsRunner()
        spec = MagicMock()
        with (
            patch.object(runner, "_start_once", side_effect=results) as once,
            patch.object(winws_runner.time, "sleep"),
        ):
            outcome = runner.start(spec)
        return outcome, once.call_count

    def test_busy_driver_gets_another_try(self) -> None:
        busy = (False, "winws завершился (код 34). windivert: error opening filter: The service cannot be started")
        outcome, attempts = self._start([busy, (True, "Запущено")])
        self.assertEqual(outcome, (True, "Запущено"))
        self.assertEqual(attempts, 2)

    def test_other_errors_are_reported_at_once(self) -> None:
        outcome, attempts = self._start([(False, "desync function does not exist")])
        self.assertFalse(outcome[0])
        self.assertEqual(attempts, 1)

    def test_gives_up_after_the_last_try(self) -> None:
        busy = (False, "windivert: error opening filter: x")
        outcome, attempts = self._start([busy] * (winws_runner.DRIVER_RETRIES + 1))
        self.assertFalse(outcome[0])
        self.assertEqual(attempts, winws_runner.DRIVER_RETRIES + 1)


if __name__ == "__main__":
    unittest.main()
