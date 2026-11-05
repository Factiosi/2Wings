"""System tray icon and menu for 2Wings daemon."""

from __future__ import annotations

import sys
import threading

import pystray

from src.core.branding import load_tray_icon
from src.core.debug_log import debug
from src.core.paths import APP_NAME
from src.daemon.ui_launcher import launch_gui, notify_spawn_error

if sys.platform == "win32":
    from src.daemon.tray_win32 import TwoWingsTrayIcon, menu_item
else:
    TwoWingsTrayIcon = pystray.Icon  # type: ignore[misc, assignment]

    def menu_item(text, action, *, icon=None, **kwargs):  # type: ignore[misc]
        return pystray.MenuItem(text, action, **kwargs)


class TrayController:
    def __init__(
        self,
        *,
        on_start,
        on_stop,
        on_shutdown,
        status_provider: Callable[[], tuple[bool, bool]],
    ) -> None:
        self._on_start = on_start
        self._on_stop = on_stop
        self._on_shutdown = on_shutdown
        self._status_provider = status_provider
        self._icon: pystray.Icon | None = None
        self._thread: threading.Thread | None = None
        self._poll_thread: threading.Thread | None = None
        self._poll_stop = threading.Event()
        self._last_running: bool | None = None
        self._last_busy: bool | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, daemon=False, name="twowings-tray")
        self._thread.start()

    def stop(self) -> None:
        self._poll_stop.set()
        icon = self._icon
        if icon is not None:
            try:
                icon.stop()
            except Exception as exc:  # noqa: BLE001
                debug("daemon", f"tray stop: {exc}", level="error")

    def _run(self) -> None:
        running, _busy = self._status_provider()
        self._last_running = running
        menu = pystray.Menu(
            menu_item("Открыть окно", self._menu_open, icon="app-window", default=True),
            pystray.Menu.SEPARATOR,
            menu_item("Запустить", self._menu_start, icon="play", enabled=self._can_start),
            menu_item("Остановить", self._menu_stop, icon="square", enabled=self._can_stop),
            pystray.Menu.SEPARATOR,
            menu_item("Завершить работу", self._menu_shutdown, icon="power"),
        )
        self._icon = TwoWingsTrayIcon(
            APP_NAME,
            load_tray_icon(running=running),
            APP_NAME,
            menu,
            on_double_click=self._menu_open,
        )
        self._poll_stop.clear()
        self._poll_thread = threading.Thread(
            target=self._poll_tray_icon,
            daemon=True,
            name="twowings-tray-icon",
        )
        self._poll_thread.start()
        self._icon.run()

    def _poll_tray_icon(self) -> None:
        while not self._poll_stop.wait(1.0):
            icon = self._icon
            if icon is None:
                continue
            running, busy = self._status_provider()
            if running == self._last_running and busy == self._last_busy:
                continue
            self._last_running = running
            self._last_busy = busy
            try:
                icon.icon = load_tray_icon(running=running)
            except Exception as exc:  # noqa: BLE001
                debug("daemon", f"tray icon update: {exc}", level="error")
            self._refresh_menu()

    def _refresh_menu(self) -> None:
        if self._icon:
            self._icon.update_menu()

    def _sync_tray_icon(self) -> None:
        icon = self._icon
        if icon is None:
            return
        running, _busy = self._status_provider()
        self._last_running = running
        try:
            icon.icon = load_tray_icon(running=running)
        except Exception as exc:  # noqa: BLE001
            debug("daemon", f"tray icon sync: {exc}", level="error")

    def _can_start(self, _item) -> bool:
        running, busy = self._status_provider()
        return not running and not busy

    def _can_stop(self, _item) -> bool:
        running, busy = self._status_provider()
        return running and not busy

    def _menu_start(self, _icon, _item) -> None:
        self._on_start()
        self._sync_tray_icon()
        self._refresh_menu()

    def _menu_stop(self, _icon, _item) -> None:
        self._on_stop()
        self._sync_tray_icon()
        self._refresh_menu()

    def _menu_open(self, _icon, _item) -> None:
        ok, msg = launch_gui()
        if not ok:
            debug("daemon", f"open ui failed: {msg}", level="error")
            notify_spawn_error(msg)

    def _menu_shutdown(self, icon, _item) -> None:
        self._on_shutdown(icon)
