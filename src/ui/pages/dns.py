"""DNS settings page."""

from __future__ import annotations

import asyncio
import threading

import flet as ft

from src.modules.dns.service import (
    ALL_ADAPTERS_KEY,
    apply_auto,
    apply_custom,
    apply_provider,
    flatten_providers,
    flush_cache,
    format_status_lines,
    load_state,
    reset_dns_settings,
    resolve_apply_adapters,
)
from src.ui.theme import T
from src.ui.components import block_section, make_select, pill_button, scroll_page, set_pill_disabled, ui_text
from src.ui.notifications import show_toast

AUTO_DNS_KEY = "__auto__"
CUSTOM_DNS_KEY = "__custom__"


class DnsPage:
    def __init__(self, page: ft.Page) -> None:
        self.page = page
        self._busy = False
        self._adapter = ALL_ADAPTERS_KEY
        self._dns_choice = AUTO_DNS_KEY
        self._primary = ""
        self._secondary = ""
        self._applied_snapshot: str | None = None
        self._flush_timer_running = False

        self._status_text = ui_text("", color=T.TEXT_MUTED, size=T.FONT_CAPTION, selectable=True)
        self._provider_options: list[tuple[str, str]] = []
        self._providers_map: dict[str, tuple[list[str], list[str]]] = {}

        self._apply_btn: ft.FilledButton | None = None
        self._reset_btn: ft.OutlinedButton | None = None
        self._flush_btn: ft.OutlinedButton | None = None
        self._dns_dropdown: ft.Dropdown | None = None
        self._custom_fields: ft.Column | None = None
        self._primary_field: ft.TextField | None = None
        self._secondary_field: ft.TextField | None = None

    def build(self) -> ft.Control:
        state = load_state(self._adapter or None)
        self._adapter = state.selected_adapter
        self._build_dns_options()
        if not self._dns_choice or self._dns_choice not in dict(self._provider_options):
            self._dns_choice = AUTO_DNS_KEY

        adapter_options = [(ALL_ADAPTERS_KEY, "Все адаптеры")]
        adapter_options.extend((name, name) for name in state.adapters if name != ALL_ADAPTERS_KEY)

        adapter_select = make_select(
            self.page,
            "Адаптер",
            adapter_options or [("", "Нет адаптеров")],
            self._adapter,
            on_change=self._on_adapter_change,
        )
        dns_select = make_select(
            self.page,
            "DNS",
            self._provider_options,
            self._dns_choice,
            on_change=self._on_dns_choice_change,
            menu_height=320,
        )
        anchor = dns_select.controls[1]
        if isinstance(anchor, ft.Container) and isinstance(anchor.content, ft.Dropdown):
            self._dns_dropdown = anchor.content

        self._primary_field = ft.TextField(
            label="Основной DNS",
            value=self._primary,
            on_change=self._on_custom_field_change,
            border_radius=T.RADIUS_L,
            filled=True,
            bgcolor=T.SURFACE,
            border_color=T.BORDER,
            focused_border_color=T.FOCUS,
            focused_border_width=2,
            cursor_color=T.BUTTON,
        )
        self._secondary_field = ft.TextField(
            label="Дополнительный DNS",
            value=self._secondary,
            on_change=self._on_custom_field_change,
            border_radius=T.RADIUS_L,
            filled=True,
            bgcolor=T.SURFACE,
            border_color=T.BORDER,
            focused_border_color=T.FOCUS,
            focused_border_width=2,
            cursor_color=T.BUTTON,
        )
        self._custom_fields = ft.Column(
            [self._primary_field, self._secondary_field],
            spacing=12,
            visible=self._dns_choice == CUSTOM_DNS_KEY,
        )

        self._apply_btn = pill_button("Применить", primary=True, on_click=self._apply)
        self._reset_btn = pill_button("Сбросить настройки DNS", on_click=self._reset_dns)
        self._flush_btn = pill_button("Сбросить DNS-кэш", on_click=self._flush)

        self._refresh_status(state)
        self._update_apply_button()

        return scroll_page(
            self._status_text,
            block_section(
                "Настройки",
                adapter_select,
                dns_select,
                self._custom_fields,
                ft.Row(
                    [self._apply_btn, self._reset_btn, self._flush_btn],
                    spacing=8,
                    wrap=True,
                ),
            ),
            page=self.page,
        )

    def _build_dns_options(self) -> None:
        self._provider_options = [(AUTO_DNS_KEY, "Авто (DHCP)")]
        self._providers_map = {}
        for group, name, desc, ipv4, ipv6 in flatten_providers():
            key = f"{group}::{name}"
            self._provider_options.append((key, f"{name} ({desc})"))
            self._providers_map[key] = (ipv4, ipv6)
        self._provider_options.append((CUSTOM_DNS_KEY, "Свои настройки DNS"))

    def _snapshot(self) -> str:
        return "|".join(
            [
                self._adapter,
                self._dns_choice,
                self._primary.strip(),
                self._secondary.strip(),
            ]
        )

    def _mark_dirty(self) -> None:
        self._update_apply_button()

    def _update_apply_button(self) -> None:
        if not self._apply_btn:
            return
        applied = self._applied_snapshot is not None and self._snapshot() == self._applied_snapshot
        if applied:
            self._apply_btn.text = "Применено"
            set_pill_disabled(self._apply_btn, True)
        else:
            self._apply_btn.text = "Применить"
            set_pill_disabled(self._apply_btn, self._busy)
        try:
            self.page.update()
        except RuntimeError:
            pass

    def _update_custom_fields_visibility(self) -> None:
        if self._custom_fields:
            self._custom_fields.visible = self._dns_choice == CUSTOM_DNS_KEY

    def _refresh_status(self, state) -> None:
        self._status_text.value = "\n".join(format_status_lines(state))

    def _on_adapter_change(self, value: str) -> None:
        self._adapter = value or ALL_ADAPTERS_KEY
        self._applied_snapshot = None
        state = load_state(self._adapter)
        self._refresh_status(state)
        self._mark_dirty()
        try:
            self.page.update()
        except RuntimeError:
            pass

    def _on_dns_choice_change(self, value: str) -> None:
        self._dns_choice = value or AUTO_DNS_KEY
        self._update_custom_fields_visibility()
        self._mark_dirty()

    def _on_custom_field_change(self, e: ft.ControlEvent) -> None:
        field = e.control
        if field is self._primary_field:
            self._primary = field.value or ""
        elif field is self._secondary_field:
            self._secondary = field.value or ""
        self._mark_dirty()

    def _run_bg(self, work, *, on_success=None) -> None:
        if self._busy:
            return
        self._busy = True
        self._update_apply_button()

        def runner() -> None:
            try:
                ok, msg = work()
            except Exception as exc:  # noqa: BLE001
                ok, msg = False, str(exc)

            def finish() -> None:
                self._busy = False
                if ok and on_success:
                    on_success()
                self._update_apply_button()
                show_toast(self.page, msg, kind="error" if not ok else "success")

            try:
                self.page.run_thread(finish)
            except AttributeError:
                finish()

        threading.Thread(target=runner, daemon=True).start()

    def _apply(self, _: ft.ControlEvent) -> None:
        state = load_state(self._adapter or None)
        adapters = resolve_apply_adapters(self._adapter, state.adapters)
        choice = self._dns_choice

        def work():
            if choice == AUTO_DNS_KEY:
                return apply_auto(adapters)
            if choice == CUSTOM_DNS_KEY:
                primary = self._primary.strip()
                if not primary:
                    return False, "Укажите основной DNS"
                secondary = self._secondary.strip() or None
                return apply_custom(adapters, primary, secondary)
            ipv4, ipv6 = self._providers_map.get(choice, ([], []))
            return apply_provider(adapters, ipv4, ipv6, ipv6_available=state.ipv6_available)

        def on_success() -> None:
            self._applied_snapshot = self._snapshot()
            state_after = load_state(self._adapter or None)
            self._refresh_status(state_after)

        self._run_bg(work, on_success=on_success)

    def _reset_dns(self, _: ft.ControlEvent) -> None:
        state = load_state(self._adapter or None)
        adapters = resolve_apply_adapters(self._adapter, state.adapters)

        def work():
            return reset_dns_settings(adapters)

        def on_success() -> None:
            self._dns_choice = AUTO_DNS_KEY
            self._primary = ""
            self._secondary = ""
            if self._primary_field:
                self._primary_field.value = ""
            if self._secondary_field:
                self._secondary_field.value = ""
            if self._dns_dropdown:
                self._dns_dropdown.value = AUTO_DNS_KEY
            self._applied_snapshot = self._snapshot()
            state_after = load_state(self._adapter or None)
            self._refresh_status(state_after)
            self._update_custom_fields_visibility()
            self._update_apply_button()

        self._run_bg(work, on_success=on_success)

    def _flush(self, _: ft.ControlEvent) -> None:
        if self._flush_timer_running or not self._flush_btn:
            return

        def work():
            return flush_cache()

        def on_success() -> None:
            self._flush_timer_running = True
            self._flush_btn.text = "DNS-кэш сброшен"
            set_pill_disabled(self._flush_btn, True)
            self.page.update()
            self.page.run_task(self._reset_flush_button_after_delay)

        self._run_bg(work, on_success=on_success)

    async def _reset_flush_button_after_delay(self) -> None:
        await asyncio.sleep(5)
        self._flush_timer_running = False
        if self._flush_btn:
            self._flush_btn.text = "Сбросить DNS-кэш"
            set_pill_disabled(self._flush_btn, False)
        try:
            self.page.update()
        except RuntimeError:
            pass
