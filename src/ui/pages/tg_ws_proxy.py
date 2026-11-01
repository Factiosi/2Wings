"""Страница TG WS Proxy: включение, ссылка в Telegram, порт и адреса DC."""

from __future__ import annotations

import threading
import webbrowser

import flet as ft

from src.core.settings import get_settings, reload_settings, save_settings
from src.daemon.ipc import daemon_tg_proxy_apply, daemon_tg_proxy_status
from src.modules.tg_ws_proxy.options import (
    DEFAULT_DC_IP,
    dc_lines,
    validate_dc_ip,
    validate_port,
)
from src.ui.components import (
    block_section,
    make_text_field,
    LeoSwitch,
    pill_button,
    scroll_page,
    status_pill,
    ui_text,
)
from src.ui.notifications import show_toast
from src.ui.theme import T


class TgWsProxyPage:
    def __init__(self, page: ft.Page) -> None:
        self.page = page
        self._applying = False
        self._rows: list[tuple[ft.TextField, ft.TextField]] = []
        self._dc_column = ft.Column(spacing=12, tight=True)
        self._status_row = ft.Row(spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER)
        self._switch: LeoSwitch | None = None
        self._port: ft.TextField | None = None
        self._queued = False

    def build(self) -> ft.Control:
        settings = get_settings()
        self._switch = LeoSwitch(
            label="Включить TG WS Proxy",
            value=settings.tg_ws_proxy_enabled,
            on_change=self._on_toggle,
        )
        port_block = make_text_field("Порт", str(settings.tg_ws_proxy_port))
        self._port = port_block.controls[1]
        self._port.on_blur = self._on_port_blur
        self._fill_rows(dc_lines(settings.tg_ws_proxy_dc_ip))
        self._paint_status(daemon_tg_proxy_status())
        return scroll_page(
            block_section(
                None,
                ft.Container(content=self._switch.control, padding=ft.Padding.only(bottom=12)),
                ft.Row(
                    [
                        ui_text("Статус", color=T.TEXT_MUTED),
                        self._status_row,
                    ],
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    wrap=True,
                ),
                ft.Row(
                    [pill_button("Добавить в Telegram", primary=True, on_click=self._on_open_telegram)],
                    spacing=8,
                ),
                port_block,
            ),
            block_section(
                "Дата-центры Telegram (DC → IP)",
                self._dc_column,
                ft.Row(
                    [pill_button("Добавить адрес", on_click=self._on_add_row)],
                    spacing=8,
                ),
            ),
            page=self.page,
        )

    def _fill_rows(self, lines: list[str]) -> None:
        self._rows.clear()
        self._dc_column.controls.clear()
        source = lines or list(DEFAULT_DC_IP)
        for line in source:
            dc, _, ip = line.partition(":")
            self._append_row(dc, ip)

    def _append_row(self, dc: str, ip: str) -> None:
        dc_block = make_text_field("DC", dc, expand=False)
        ip_block = make_text_field("IP", ip)
        dc_field = dc_block.controls[1]
        ip_field = ip_block.controls[1]
        dc_field.width = 88
        dc_field.on_blur = self._on_dc_blur
        ip_field.on_blur = self._on_dc_blur
        self._rows.append((dc_field, ip_field))
        remove = ft.TextButton(
            "Убрать",
            style=ft.ButtonStyle(color=T.TEXT_MUTED),
            on_click=lambda _e, pair=(dc_field, ip_field): self._on_remove_row(pair),
        )
        self._dc_column.controls.append(
            ft.Row(
                [
                    ft.Container(dc_block, width=120),
                    ft.Container(ip_block, expand=True),
                    remove,
                ],
                spacing=12,
                vertical_alignment=ft.CrossAxisAlignment.END,
            )
        )

    def _on_add_row(self, _e: ft.ControlEvent) -> None:
        self._append_row("", "")
        self.page.update()

    def _on_remove_row(self, pair: tuple[ft.TextField, ft.TextField]) -> None:
        if len(self._rows) <= 1:
            show_toast(self.page, "Нужен хотя бы один дата-центр", kind="error")
            return
        index = self._rows.index(pair)
        self._rows.pop(index)
        self._dc_column.controls.pop(index)
        self.page.update()
        self._commit()

    def _on_toggle(self, enabled: bool) -> None:
        self._commit(enabled=enabled)

    def _on_port_blur(self, _e: ft.ControlEvent) -> None:
        self._commit()

    def _on_dc_blur(self, _e: ft.ControlEvent) -> None:
        self._commit()

    def _form(self) -> tuple[int, list[str]] | str:
        port_text = self._port.value if self._port is not None else ""
        port_error = validate_port(port_text)
        if port_error:
            return port_error
        lines: list[str] = []
        for dc_field, ip_field in self._rows:
            dc = (dc_field.value or "").strip()
            ip = (ip_field.value or "").strip()
            if not dc and not ip:
                continue
            lines.append(f"{dc}:{ip}")
        dc_error = validate_dc_ip(lines)
        if dc_error:
            return dc_error
        return int(str(port_text).strip()), lines

    def _commit(self, enabled: bool | None = None) -> None:
        if self._switch is None:
            return
        if self._applying:
            self._queued = True
            return
        parsed = self._form()
        if isinstance(parsed, str):
            if enabled is not None:
                self._switch.set_value(not enabled)
            show_toast(self.page, parsed, kind="error")
            self.page.update()
            return
        port, lines = parsed
        settings = get_settings()
        new_enabled = self._switch.value if enabled is None else enabled
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
        self._status_row.controls = [
            status_pill("connecting", "запуск прокси" if new_enabled else "остановка прокси")
        ]
        if self._status_row.page:
            self._status_row.update()

        def work() -> None:
            try:
                result = daemon_tg_proxy_apply()
            except (OSError, TimeoutError) as exc:
                result = {"ok": False, "running": False, "error": str(exc)}

            def finish() -> None:
                self._applying = False
                if self._queued:
                    self._queued = False
                    self._commit()
                    return
                reload_settings()
                failed = (
                    bool(result.get("error"))
                    and not result.get("running")
                    and new_enabled
                )
                if failed and self._switch is not None:
                    message = str(result.get("error") or "Не удалось запустить TG WS Proxy")
                    self._switch.set_value(False)
                    current = get_settings()
                    current.tg_ws_proxy_enabled = False
                    save_settings(current)
                    show_toast(self.page, message, kind="error")
                    threading.Thread(
                        target=daemon_tg_proxy_apply,
                        daemon=True,
                        name="tigo-tg-proxy-stop",
                    ).start()
                self._paint_status(result if not failed else {**result, "running": False})
                self.page.update()

            try:
                self.page.run_thread(finish)
            except RuntimeError:
                finish()

        threading.Thread(target=work, daemon=True, name="tigo-tg-proxy-apply").start()

    def _paint_status(self, result: dict) -> None:
        if result.get("running"):
            port = result.get("port") or ""
            pill = status_pill("active", f"прокси запущен · {port}")
        elif result.get("error") and get_settings().tg_ws_proxy_enabled:
            pill = status_pill("error", result.get("error") or "ошибка запуска прокси")
        else:
            pill = status_pill("offline", "прокси не запущен")
        self._status_row.controls = [pill]

    def _on_open_telegram(self, _e: ft.ControlEvent) -> None:
        result = daemon_tg_proxy_status()
        link = str(result.get("link") or "")
        if not result.get("running") or not link:
            show_toast(self.page, "Сначала включите TG WS Proxy", kind="error")
            return
        if not webbrowser.open(link):
            show_toast(self.page, "Не удалось открыть Telegram", kind="error")
