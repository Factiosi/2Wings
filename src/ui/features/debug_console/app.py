"""Standalone debug console window."""

from __future__ import annotations

import ctypes
import sys

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import PlainTextEdit, PushButton, isDarkTheme

from src.core.branding import app_window_icon_path
from src.core.debug_log import clear, get_persistent_text
from src.core.paths import APP_NAME, APP_USER_MODEL_ID
from src.core.settings import get_settings
from src.ui.components import apply_theme, use_vsync_rendering

POLL_MS = 1000
_DWMWA_USE_IMMERSIVE_DARK_MODE = 20


class DebugConsole(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} — консоль отладки")
        icon_path = app_window_icon_path()
        if icon_path is not None:
            self.setWindowIcon(QIcon(str(icon_path)))
        self.resize(900, 500)
        self.setMinimumSize(480, 240)
        dark = isDarkTheme()
        self.setStyleSheet(f"DebugConsole {{ background: {'#202020' if dark else '#f3f3f3'}; }}")
        self._log = PlainTextEdit(self)
        self._log.setReadOnly(True)
        self._log.setStyleSheet("font-family: 'Cascadia Mono', Consolas, monospace; font-size: 13px;")
        clear_button = PushButton("Очистить", self)
        clear_button.clicked.connect(self._clear)
        strip = QHBoxLayout()
        strip.addStretch(1)
        strip.addWidget(clear_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addLayout(strip)
        layout.addWidget(self._log, 1)
        self._text = ""
        self._refresh(force_bottom=True)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(POLL_MS)
        if sys.platform == "win32":
            flag = ctypes.c_int(1 if dark else 0)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                int(self.winId()), _DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.byref(flag), ctypes.sizeof(flag)
            )

    def _refresh(self, *, force_bottom: bool = False) -> None:
        text = get_persistent_text() or ""
        if text == self._text and not force_bottom:
            return
        bar = self._log.verticalScrollBar()
        pinned = force_bottom or bar.value() >= bar.maximum() - 4
        position = bar.value()
        self._text = text
        self._log.setPlainText(text)
        bar.setValue(bar.maximum() if pinned else position)

    def _clear(self) -> None:
        clear()
        self._refresh(force_bottom=True)


def main() -> int:
    if sys.platform == "win32":
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    use_vsync_rendering()
    app = QApplication(sys.argv)
    apply_theme(get_settings().theme_mode)
    window = DebugConsole()
    window.show()
    return app.exec()
