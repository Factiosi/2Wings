"""Страница TG WS Proxy: включение, ссылка в Telegram, порт и адреса DC."""

from __future__ import annotations

import threading
import webbrowser

from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QVBoxLayout, QWidget
from qfluentwidgets import PrimaryPushButton, PushButton, TransparentPushButton

from src.core.settings import get_settings, reload_settings, save_settings
from src.daemon.ipc import daemon_tg_proxy_apply, daemon_tg_proxy_status
from src.modules.tg_ws_proxy.options import (
    DEFAULT_DC_IP,
    dc_lines,
    validate_dc_ip,
    validate_port,
)
from src.ui.components import Lucide, Group, OptionCard, Page, Panel, StatusMark, row, switch, text_field
from src.ui.dispatch import run_bg
from src.ui.notifications import show_toast


class TgWsProxyPage(Page):
    title = "TG WS Proxy"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._applying = False
        self._queued = False
        self._rows: list[tuple[QWidget, QLineEdit, QLineEdit]] = []
        settings = get_settings()
        self._status = StatusMark()
        self._switch = switch(settings.tg_ws_proxy_enabled, self._on_toggle)
        self._port = text_field(str(settings.tg_ws_proxy_port), width=120)
        self._port.editingFinished.connect(self._commit)
        self._dc_holder = QWidget()
        self._dc_layout = QVBoxLayout(self._dc_holder)
        self._dc_layout.setContentsMargins(0, 0, 0, 0)
        self._dc_layout.setSpacing(8)
        for line in dc_lines(settings.tg_ws_proxy_dc_ip) or list(DEFAULT_DC_IP):
            dc, _, ip = line.partition(":")
            self._append_row(dc, ip)
        open_btn = PrimaryPushButton(Lucide("send"), "Добавить в Telegram")
        open_btn.clicked.connect(self._on_open_telegram)
        add_btn = PushButton(Lucide("plus"), "Добавить адрес")
        add_btn.clicked.connect(lambda: self._append_row("", ""))
        self.add(
            Group(
                None,
                OptionCard("Включить TG WS Proxy", "", self._switch, icon=Lucide("send")),
                OptionCard("Порт", "", self._port, icon=Lucide("plug")),
                Panel(self._status, row(open_btn)),
            ),
            Group("Дата-центры Telegram (DC → IP)", Panel(self._dc_holder, row(add_btn))),
        )
        self._paint_status(daemon_tg_proxy_status())

    def _append_row(self, dc: str, ip: str) -> None:
        holder = QWidget()
        line = QHBoxLayout(holder)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(8)
        dc_field = text_field(dc, placeholder="DC", width=88)
        ip_field = text_field(ip, placeholder="IP")
        dc_field.editingFinished.connect(self._commit)
        ip_field.editingFinished.connect(self._commit)
        remove = TransparentPushButton("Убрать")
        entry = (holder, dc_field, ip_field)
        remove.clicked.connect(lambda: self._on_remove_row(entry))
        line.addWidget(dc_field)
        line.addWidget(ip_field, 1)
        line.addWidget(remove)
        self._rows.append(entry)
        self._dc_layout.addWidget(holder)

    def _on_remove_row(self, entry) -> None:
        if len(self._rows) <= 1:
            show_toast("Нужен хотя бы один дата-центр", kind="error")
            return
        self._rows.remove(entry)
        self._dc_layout.removeWidget(entry[0])
        entry[0].setParent(None)
        entry[0].deleteLater()
        self._commit()

    def _on_toggle(self, enabled: bool) -> None:
        self._commit(enabled=enabled)

    def _form(self) -> tuple[int, list[str]] | str:
        port_text = self._port.text()
        port_error = validate_port(port_text)
        if port_error:
            return port_error
        lines: list[str] = []
        for _holder, dc_field, ip_field in self._rows:
            dc = dc_field.text().strip()
            ip = ip_field.text().strip()
            if not dc and not ip:
                continue
            lines.append(f"{dc}:{ip}")
        dc_error = validate_dc_ip(lines)
        if dc_error:
            return dc_error
        return int(port_text.strip()), lines

    def _set_switch(self, value: bool) -> None:
        self._switch.blockSignals(True)
        self._switch.setChecked(value)
        self._switch.blockSignals(False)

    def _commit(self, enabled: bool | None = None) -> None:
        if self._applying:
            self._queued = True
            return
        parsed = self._form()
        if isinstance(parsed, str):
            if enabled is not None:
                self._set_switch(not enabled)
            show_toast(parsed, kind="error")
            return
        port, lines = parsed
        settings = get_settings()
        new_enabled = self._switch.isChecked() if enabled is None else enabled
        if (
            settings.tg_ws_proxy_enabled == new_enabled
            and int(settings.tg_ws_proxy_port) == port
            and dc_lines(settings.tg_ws_proxy_dc_ip) == lines
        ):
            return
        settings.tg_ws_proxy_enabled = new_enabled
        settings.tg_ws_proxy_port = port
        settings.tg_ws_proxy_dc_ip = lines
        save_settings(settings)
        self._applying = True
        self._status.set_status("connecting", "запуск прокси" if new_enabled else "остановка прокси")

        def done(result: dict) -> None:
            self._applying = False
            if self._queued:
                self._queued = False
                self._commit()
                return
            reload_settings()
            failed = bool(result.get("error")) and not result.get("running") and new_enabled
            if failed:
                self._set_switch(False)
                current = get_settings()
                current.tg_ws_proxy_enabled = False
                save_settings(current)
                show_toast(str(result.get("error") or "Не удалось запустить TG WS Proxy"), kind="error")
                threading.Thread(target=daemon_tg_proxy_apply, daemon=True, name="twowings-tg-proxy-stop").start()
            self._paint_status(result if not failed else {**result, "running": False})

        run_bg(
            daemon_tg_proxy_apply,
            done,
            name="twowings-tg-proxy-apply",
            on_error=lambda exc: {"ok": False, "running": False, "error": str(exc)},
        )

    def _paint_status(self, result: dict) -> None:
        if result.get("running"):
            self._status.set_status("active", f"прокси запущен · {result.get('port') or ''}")
        elif result.get("error") and get_settings().tg_ws_proxy_enabled:
            self._status.set_status("error", result.get("error") or "ошибка запуска прокси")
        else:
            self._status.set_status("offline", "прокси не запущен")

    def _on_open_telegram(self) -> None:
        result = daemon_tg_proxy_status()
        link = str(result.get("link") or "")
        if not result.get("running") or not link:
            show_toast("Сначала включите TG WS Proxy", kind="error")
            return
        if not webbrowser.open(link):
            show_toast("Не удалось открыть Telegram", kind="error")
