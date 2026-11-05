from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.core.settings import AppSettings, get_settings, reload_settings, save_settings


class SettingsMergeSaveTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.path = Path(self._tmpdir.name) / "settings.json"
        self._path_patch = patch(
            "src.core.settings.bootstrap_settings_path",
            return_value=self.path,
        )
        self._path_patch.start()
        reload_settings()

    def tearDown(self) -> None:
        self._path_patch.stop()
        self._tmpdir.cleanup()

    def test_daemon_save_does_not_overwrite_unrelated_gui_field(self) -> None:
        gui = get_settings()
        gui.auto_install_app_updates = True
        save_settings(gui)

        reload_settings()
        daemon = get_settings()
        self.assertTrue(daemon.auto_install_app_updates)
        daemon.selected_strategy = "other-strategy"
        save_settings(daemon)

        disk = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertTrue(disk["auto_install_app_updates"])
        self.assertEqual(disk["selected_strategy"], "other-strategy")

    def test_only_changed_fields_are_written(self) -> None:
        base = AppSettings()
        base.auto_check_app_updates_on_startup = False
        base.save(self.path)
        reload_settings()

        stale = get_settings()
        stale.auto_install_app_updates = True
        save_settings(stale)

        disk = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertTrue(disk["auto_install_app_updates"])
        self.assertFalse(disk["auto_check_app_updates_on_startup"])


class LegacyDataTests(unittest.TestCase):
    def _run(self, *, log_first: bool):
        import os
        import tempfile
        from unittest.mock import patch

        from src.core import paths

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        roaming = Path(tmp.name)
        old = roaming / "Tigo"
        (old / "strategies").mkdir(parents=True)
        (old / "settings.json").write_text('{"advanced_mode": true}', encoding="utf-8")
        (old / "strategies" / "a.txt").write_text("a", encoding="utf-8")
        new = roaming / "2Wings"
        if log_first:
            new.mkdir()
            (new / "debug.log").write_text("early log", encoding="utf-8")
        with patch.dict(os.environ, {"APPDATA": str(roaming)}), patch.object(paths, "default_app_data_root", return_value=new):
            paths.migrate_legacy_app_data()
        return new

    def test_data_of_the_previous_name_moves_over(self) -> None:
        new = self._run(log_first=False)
        self.assertTrue((new / "settings.json").exists())
        self.assertTrue((new / "strategies" / "a.txt").exists())

    def test_an_early_log_does_not_block_the_copy(self) -> None:
        new = self._run(log_first=True)
        self.assertTrue((new / "settings.json").exists())
        self.assertEqual((new / "debug.log").read_text(encoding="utf-8"), "early log")
