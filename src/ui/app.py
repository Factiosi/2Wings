"""Main window: Fluent navigation over the pages."""

from __future__ import annotations

import ctypes
import sys
from collections.abc import Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget
from qfluentwidgets import FluentWindow, NavigationItemPosition

from src.core.branding import app_window_icon_path
from src.core.events import subscribe, unsubscribe
from src.core.paths import APP_NAME, APP_USER_MODEL_ID, is_packaged_app
from src.core.settings import get_settings
from src.daemon.ipc import is_daemon_running
from src.modules.lifecycle.public import handle_window_close, should_start_hidden
from src.modules.strategies.repository import has_flowseal_strategies
from src.modules.updates.app import MSG_APP_UP_TO_DATE, check_and_install_app, check_app_only
from src.ui.components import Lucide, Page, apply_theme, use_vsync_rendering
from src.ui.dispatch import install_dispatcher, run_bg, ui_call
from src.ui.notifications import present_app_update_result, set_toast_host
from src.ui.pages.dns import DnsPage
from src.ui.pages.home import HomePage
from src.ui.pages.hosts import HostsPage
from src.ui.pages.lists import ListsPage
from src.ui.pages.settings import SettingsPage
from src.ui.pages.strategies import StrategiesPage
from src.ui.pages.tg_ws_proxy import TgWsProxyPage

WATCHDOG_MS = 2000
WINDOW_SIZE = (1040, 760)
MIN_WINDOW_SIZE = (860, 600)
NAV_WIDTH = 280


def visible_routes() -> set[str]:
    """Routes the current settings allow; the rest stay out of navigation."""
    settings = get_settings()
    routes = {"home", "tg_ws_proxy", "settings"}
    if settings.strategy_source == "flowseal":
        routes.add("lists")
        if has_flowseal_strategies(settings):
            routes.add("strategies")
    if settings.advanced_mode:
        routes.update({"dns", "hosts"})
    return routes


class _Host(QWidget):
    """Navigation target. The page inside is built on entry and destroyed on leaving,
    so every visit shows fresh data and no timers run for a page nobody sees."""

    def __init__(self, route: str, factory: Callable[[], Page], parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName(route)
        self._factory = factory
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self.page: Page | None = None

    def enter(self) -> None:
        if self.page is None:
            self.page = self._factory()
            self._layout.addWidget(self.page)

    def leave(self) -> None:
        if self.page is not None:
            self.page.stop()
            self._layout.removeWidget(self.page)
            self.page.setParent(None)
            self.page.deleteLater()
            self.page = None


class MainWindow(FluentWindow):
    def __init__(self) -> None:
        super().__init__()
        self._recreate_with_alpha()
        self.setWindowTitle(APP_NAME)
        icon_path = app_window_icon_path()
        if icon_path is not None:
            self.setWindowIcon(QIcon(str(icon_path)))
        self.resize(*WINDOW_SIZE)
        self.setMinimumSize(*MIN_WINDOW_SIZE)
        self.navigationInterface.setExpandWidth(NAV_WIDTH)
        self.navigationInterface.setMinimumExpandWidth(MIN_WINDOW_SIZE[0])
        self._hosts: dict[str, _Host] = {}
        self._current: _Host | None = None
        self._add_route("home", "Главный экран", Lucide("house"), lambda: HomePage(on_strategies_available=self.reload_shell))
        self._add_route("strategies", "Тестирование стратегий", Lucide("flask-conical"), StrategiesPage)
        self._add_route("lists", "Редактирование листов", Lucide("file-cog"), ListsPage)
        self._add_route("dns", "Изменение DNS", Lucide("columns-3-cog"), DnsPage)
        self._add_route("hosts", "Редактирование hosts", Lucide("server-cog"), HostsPage)
        self._add_route("tg_ws_proxy", "TG WS Proxy", Lucide("send"), TgWsProxyPage)
        self._add_route(
            "settings",
            "Настройки",
            Lucide("settings"),
            lambda: SettingsPage(on_settings_change=self.reload_shell),
            position=NavigationItemPosition.BOTTOM,
        )
        self.stackedWidget.currentChanged.connect(self._on_page_changed)
        self.navigationInterface.expand(useAni=False)
        self._sync_navigation()
        self._on_page_changed()
        set_toast_host(self)
        subscribe("strategies_changed", self._on_strategies_changed)
        self._watchdog = QTimer(self)
        self._watchdog.timeout.connect(self._check_daemon)
        self._watchdog.start(WATCHDOG_MS)
        self._watching = False

    def _recreate_with_alpha(self) -> None:
        """Mica over Direct3D needs a surface with alpha, but the library creates the native
        window in its constructor without one: make it again and repeat the library's setup."""
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.destroy(True, False)
        self.create()
        self.updateFrameless()
        self.windowHandle().screenChanged.connect(self._WindowsFramelessWindowBase__onScreenChanged)
        self.setMicaEffectEnabled(False)
        self.setMicaEffectEnabled(True)

    def _add_route(self, route, label, icon, factory, position=NavigationItemPosition.TOP) -> None:
        host = _Host(route, factory, self)
        self._hosts[route] = host
        self.addSubInterface(host, icon, label, position=position)

    def _sync_navigation(self) -> None:
        allowed = visible_routes()
        for route in self._hosts:
            self.navigationInterface.widget(route).setVisible(route in allowed)

    def _on_page_changed(self, _index: int = 0) -> None:
        widget = self.stackedWidget.currentWidget()
        if widget is self._current:
            return
        if self._current is not None:
            self._current.leave()
        self._current = widget if isinstance(widget, _Host) else None
        if self._current is not None:
            self._current.enter()

    def _on_strategies_changed(self) -> None:
        ui_call(self.reload_shell)

    def reload_shell(self) -> None:
        """Settings changed what is available: rebuild the open page, leave it if now hidden."""
        self._sync_navigation()
        current = self._current
        if current is None:
            return
        if current.objectName() not in visible_routes():
            self.switchTo(self._hosts["home"])
            return
        current.leave()
        current.enter()

    def start_update_check(self) -> None:
        settings = get_settings()
        if not is_packaged_app() or not settings.auto_check_app_updates_on_startup:
            return
        auto_install = settings.auto_install_app_updates

        def done(result) -> None:
            ok, message, kind = result
            if ok and message == MSG_APP_UP_TO_DATE:
                return
            if auto_install and ok and kind == "success":
                return
            present_app_update_result(ok, message, kind)

        run_bg(
            check_and_install_app if auto_install else check_app_only,
            done,
            name="twowings-app-update-check",
            on_error=lambda exc: (False, str(exc), "error"),
        )

    def _check_daemon(self) -> None:
        """The GUI has no purpose without the daemon: close when it is gone."""
        if self._watching:
            return
        self._watching = True

        def done(alive) -> None:
            self._watching = False
            if not alive:
                self.close()

        run_bg(is_daemon_running, done, name="twowings-daemon-watch", on_error=lambda _exc: True)

    def closeEvent(self, event) -> None:
        self._watchdog.stop()
        unsubscribe("strategies_changed", self._on_strategies_changed)
        if self._current is not None:
            self._current.leave()
        handle_window_close(get_settings().close_action)
        set_toast_host(None)
        super().closeEvent(event)
        QApplication.quit()


def main() -> int:
    if sys.platform == "win32":
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    use_vsync_rendering()
    app = QApplication(sys.argv)
    install_dispatcher()
    mode = get_settings().theme_mode
    apply_theme(mode)
    app.styleHints().colorSchemeChanged.connect(lambda _scheme: apply_theme(get_settings().theme_mode))
    window = MainWindow()
    if not should_start_hidden():
        window.show()
    window.start_update_check()
    return app.exec()


__all__ = ["MainWindow", "main", "visible_routes"]
