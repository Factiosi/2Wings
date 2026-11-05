from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.core.settings import reload_settings


class EveryPageBuildsTests(unittest.TestCase):
    """A page that fails to build leaves an empty area with no message, so build them all."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = patch.dict(os.environ, {"APPDATA": tmp.name, "LOCALAPPDATA": tmp.name})
        env.start()
        self.addCleanup(reload_settings)
        self.addCleanup(env.stop)
        reload_settings()

    def _build(self, factory) -> None:
        page = factory()
        self.addCleanup(page.deleteLater)
        self.addCleanup(page.stop)
        self.assertGreater(page.body.count(), 1, "the page shows nothing but its title")

    def test_home(self) -> None:
        from src.ui.pages.home import HomePage

        self._build(HomePage)

    def test_strategies(self) -> None:
        from src.ui.pages.strategies import StrategiesPage

        self._build(StrategiesPage)

    def test_lists(self) -> None:
        from src.ui.pages.lists import ListsPage

        self._build(ListsPage)

    def test_dns(self) -> None:
        from src.ui.pages.dns import DnsPage

        self._build(DnsPage)

    def test_hosts(self) -> None:
        from src.ui.pages.hosts import HostsPage

        self._build(HostsPage)

    def test_tg_ws_proxy(self) -> None:
        from src.ui.pages.tg_ws_proxy import TgWsProxyPage

        with patch("src.ui.pages.tg_ws_proxy.daemon_tg_proxy_status", return_value={"running": False}):
            self._build(TgWsProxyPage)

    def test_settings(self) -> None:
        from src.ui.pages.settings import SettingsPage

        self._build(lambda: SettingsPage(on_settings_change=lambda: None))


if __name__ == "__main__":
    unittest.main()
