"""Run code on the Qt main thread from background threads."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot


class _Dispatcher(QObject):
    called = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.called.connect(self._run)

    @Slot(object)
    def _run(self, fn: Callable[[], None]) -> None:
        fn()


_dispatcher: _Dispatcher | None = None


def install_dispatcher() -> None:
    """Call once on the main thread, after QApplication exists."""
    global _dispatcher
    _dispatcher = _Dispatcher()


def ui_call(fn: Callable[[], None]) -> None:
    if _dispatcher is None:
        fn()
    else:
        _dispatcher.called.emit(fn)


def run_bg(
    work: Callable[[], Any],
    on_done: Callable[[Any], None],
    *,
    name: str = "twowings-ui-worker",
    on_error: Callable[[Exception], Any] = lambda exc: (False, str(exc)),
) -> None:
    """Run ``work`` off the UI thread and hand its result to ``on_done`` on the UI thread."""

    def runner() -> None:
        try:
            result = work()
        except Exception as exc:  # noqa: BLE001 - a failed action is reported, not fatal
            result = on_error(exc)
        ui_call(lambda: on_done(result))

    threading.Thread(target=runner, daemon=True, name=name).start()
