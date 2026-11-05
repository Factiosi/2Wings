"""Fluent InfoBar notifications at the top of the main window."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget
from qfluentwidgets import InfoBar, InfoBarIcon, InfoBarPosition, PushButton

from src.ui.dispatch import run_bg

TOAST_SHOW_MS = 4000
TOAST_CLICKABLE_MS = 12000

_host: QWidget | None = None
_active: InfoBar | None = None

_ICONS = {
    "info": InfoBarIcon.INFORMATION,
    "success": InfoBarIcon.SUCCESS,
    "warning": InfoBarIcon.WARNING,
    "error": InfoBarIcon.ERROR,
}


def set_toast_host(window: QWidget | None) -> None:
    global _host
    _host = window


def _forget(bar: InfoBar) -> None:
    global _active
    if _active is bar:
        _active = None


def show_toast(
    message: str,
    *,
    kind: str = "info",
    duration: float | None = None,
    action: tuple[str, Callable[[], None]] | None = None,
) -> None:
    """One notification at a time; ``duration`` in seconds, ``action`` adds a button."""
    global _active
    text = message.strip()
    if not text or _host is None:
        return
    if _active is not None:
        _active.close()
    default_ms = TOAST_CLICKABLE_MS if action else TOAST_SHOW_MS
    bar = InfoBar.new(
        _ICONS.get(kind, InfoBarIcon.INFORMATION),
        "",
        text,
        orient=Qt.Orientation.Vertical if len(text) > 80 else Qt.Orientation.Horizontal,
        isClosable=True,
        duration=round(duration * 1000) if duration is not None else default_ms,
        position=InfoBarPosition.TOP,
        parent=_host,
    )
    if action:
        label, callback = action

        def on_action() -> None:
            callback()
            bar.close()

        button = PushButton(label)
        button.clicked.connect(on_action)
        bar.addWidget(button)
    bar.closedSignal.connect(lambda: _forget(bar))
    _active = bar


def _start_app_update_install() -> None:
    from src.modules.updates.app import check_and_install_app

    def done(result) -> None:
        ok, message, kind = result
        if ok and kind == "success":
            return
        show_toast(message, kind=kind if ok else "error")

    run_bg(
        check_and_install_app,
        done,
        name="twowings-app-update-install",
        on_error=lambda exc: (False, str(exc), "error"),
    )


def present_app_update_result(ok: bool, message: str, kind: str) -> None:
    from src.modules.updates.app import MSG_APP_UP_TO_DATE, MSG_APP_UPDATE_CLICKABLE

    if ok and message == MSG_APP_UP_TO_DATE:
        show_toast(message, kind="success")
    elif ok and kind == "warning":
        show_toast(MSG_APP_UPDATE_CLICKABLE, kind="warning", action=("Обновить", _start_app_update_install))
    else:
        show_toast(message, kind=kind if ok else "error")
