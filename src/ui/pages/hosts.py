"""Hosts editor page."""

from __future__ import annotations

import threading

import flet as ft

from src.core.settings import get_settings, save_settings
from src.modules.hosts.catalog import (
    CATEGORY_TITLES,
    DIRECT_PROFILE,
    Catalog,
    CatalogError,
    has_ipv6_route,
    load_catalog,
    service_rows,
)
from src.modules.hosts.hosts_file import hosts_path
from src.modules.hosts.service import (
    HostsState,
    apply_services,
    load_state,
    open_in_editor,
    refresh_catalog_and_services,
    restore_backup,
    restore_default,
    service_block_id,
    set_preset,
)
from src.ui.components import (
    block_section,
    make_select,
    make_text_field,
    pill_button,
    quiet_checkbox,
    scroll_page,
    status_pill,
    ui_text,
)
from src.ui.notifications import show_toast
from src.ui.theme import T

_CATEGORY_ORDER = ("ai", "other", "direct")


class HostsPage:
    def __init__(self, page: ft.Page) -> None:
        self.page = page
        self._busy = False
        self._root = ft.Container()
        settings = get_settings()
        self._selected: set[str] = set(settings.hosts_services)
        self._profile = settings.hosts_profile
        self._query = ""
        self._catalog: Catalog | None = None
        self._catalog_error = ""
        self._unavailable: set[str] = set()
        self._service_rows: dict[str, ft.Control] = {}
        self._checkboxes: dict[str, ft.Checkbox] = {}
        self._group_headers: dict[str, ft.Control] = {}

    def build(self) -> ft.Control:
        self._load_catalog()
        self._render(load_state())
        return self._root

    def _load_catalog(self) -> None:
        try:
            self._catalog = load_catalog()
            self._catalog_error = ""
        except CatalogError as exc:
            self._catalog, self._catalog_error = None, str(exc)
            return
        profiles = [pid for pid, _ in self._catalog.profiles]
        if self._profile not in profiles and profiles:
            self._profile = profiles[0]
        # Direct entries are fixed addresses; some exist only for IPv6.
        ipv6 = has_ipv6_route()
        self._unavailable = {
            service.id
            for service in self._catalog.services
            if service.kind != "dns" and not service_rows(self._catalog, service.id, DIRECT_PROFILE, ipv6=ipv6)
        }

    # rendering -----------------------------------------------------------------
    def _render(self, state: HostsState) -> None:
        preset_rows = [self._preset_row(preset, count) for preset, count in state.presets]
        tigo_entries = sum(state.summary.blocks.values())
        file_info = ui_text(
            f"{hosts_path()} · записей: {state.summary.entries}, из них Tigo: {tigo_entries}",
            color=T.TEXT_MUTED,
            size=T.FONT_CAPTION,
            selectable=True,
        )
        self._root.content = scroll_page(
            block_section("Готовые наборы", *preset_rows),
            self._services_section(state),
            block_section(
                "Файл hosts",
                file_info,
                ft.Row(
                    [
                        pill_button("Открыть в редакторе", on_click=self._open),
                        pill_button("Обновить", on_click=lambda _: self._reload()),
                        pill_button(
                            "Вернуть копию до Tigo",
                            on_click=self._restore_backup,
                            disabled=not state.has_backup,
                        ),
                        pill_button("Стандартный hosts Windows", destructive=True, on_click=self._restore_default),
                    ],
                    spacing=8,
                    wrap=True,
                ),
            ),
            page=self.page,
        )

    def _services_section(self, state: HostsState) -> ft.Control:
        if self._catalog is None:
            return block_section(
                "Сервисы",
                ui_text(f"Каталог сервисов недоступен: {self._catalog_error}", color=T.TEXT_MUTED, size=T.FONT_CAPTION),
                pill_button("Скачать каталог", on_click=self._update_catalog),
            )
        written = {
            service.id
            for service in self._catalog.services
            if state.summary.blocks.get(service_block_id(service.id), 0) > 0
        }
        profile_select = make_select(
            self.page,
            "Через какой DNS открывать сервисы",
            list(self._catalog.profiles),
            self._profile,
            on_change=self._on_profile_change,
        )
        search = make_text_field("Поиск", self._query, on_change=self._on_search)
        self._service_rows = {}
        self._checkboxes = {}
        self._group_headers = {}
        groups: list[ft.Control] = []
        for category in _CATEGORY_ORDER:
            services = [service for service in self._catalog.services if service.category == category]
            if not services:
                continue
            header = ui_text(
                CATEGORY_TITLES.get(category, category),
                size=T.FONT_LABEL,
                color=T.TEXT_MUTED,
                weight=ft.FontWeight.W_500,
            )
            self._group_headers[category] = header
            groups.append(header)
            for service in services:
                row = self._service_row(service, written=service.id in written)
                self._service_rows[service.id] = row
                groups.append(row)
        self._apply_filter()
        hint = (
            "Отмеченные сервисы получают в hosts адреса прокси выбранного DNS. Zapret DNS, Comss и XBOX "
            "Tigo спрашивает вживую при «Применить», остальные берёт из каталога; неотвечающие адреса "
            "не записываются. Домены, которые DNS не проксирует, остаются обычному DNS. "
            "«Прямые записи» — готовые адреса."
        )
        return block_section(
            "Сервисы",
            ui_text(hint, color=T.TEXT_MUTED, size=T.FONT_CAPTION),
            ft.Row([ft.Container(profile_select, expand=True), ft.Container(search, expand=True)], spacing=12),
            ft.Column(groups, spacing=2, tight=True),
            ft.Row(
                [
                    pill_button("Применить", primary=True, on_click=self._apply_services),
                    pill_button("Выделить всё", on_click=lambda _: self._check_visible(True)),
                    pill_button("Снять всё", on_click=lambda _: self._check_visible(False)),
                    pill_button("Обновить каталог", on_click=self._update_catalog),
                    ui_text(f"Каталог {self._catalog.version}", color=T.TEXT_MUTED, size=T.FONT_CAPTION),
                ],
                spacing=8,
                wrap=True,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )

    def _service_row(self, service, *, written: bool) -> ft.Control:
        unavailable = service.id in self._unavailable
        label = f"{service.name} · {service.domains} {'записей' if service.kind != 'dns' else 'доменов'}"
        if unavailable:
            label += " · нужен IPv6"
        checkbox = quiet_checkbox(
            value=service.id in self._selected,
            disabled=unavailable,
            on_change=lambda e, sid=service.id: self._on_toggle(sid, bool(e.control.value)),
        )
        self._checkboxes[service.id] = checkbox
        trailing: list[ft.Control] = [status_pill("active", "В hosts", dense=True)] if written else []
        return ft.Row(
            [checkbox, ui_text(label, expand=True, color=T.TEXT_MUTED if unavailable else T.TEXT), *trailing],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def _preset_row(self, preset, count: int) -> ft.Control:
        enabled = count > 0
        badge = status_pill("active", f"Включено · {count}") if enabled else status_pill("offline", "Выключено")
        return ft.Row(
            [
                ft.Column(
                    [
                        ui_text(preset.title, weight=ft.FontWeight.W_500),
                        ui_text(preset.description, color=T.TEXT_MUTED, size=T.FONT_CAPTION),
                    ],
                    spacing=2,
                    tight=True,
                    expand=True,
                ),
                badge,
                pill_button(
                    "Выключить" if enabled else "Включить",
                    primary=not enabled,
                    on_click=lambda _, pid=preset.id, on=not enabled: self._run(lambda: set_preset(pid, on)),
                ),
            ],
            spacing=12,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def _apply_filter(self) -> None:
        query = self._query.strip().lower()
        visible_by_category: dict[str, bool] = {}
        for service in self._catalog.services if self._catalog else ():
            row = self._service_rows.get(service.id)
            if row is None:
                continue
            row.visible = not query or query in service.name.lower()
            visible_by_category[service.category] = visible_by_category.get(service.category, False) or row.visible
        for category, header in self._group_headers.items():
            header.visible = visible_by_category.get(category, False)

    def _reload(self) -> None:
        self._render(load_state())
        self.page.update()

    # events --------------------------------------------------------------------
    def _on_toggle(self, service_id: str, checked: bool) -> None:
        if checked:
            self._selected.add(service_id)
        else:
            self._selected.discard(service_id)

    def _on_profile_change(self, value: str) -> None:
        self._profile = value or self._profile
        settings = get_settings()
        settings.hosts_profile = self._profile
        save_settings(settings)

    def _on_search(self, e: ft.ControlEvent) -> None:
        self._query = str(e.control.value or "")
        self._apply_filter()
        self.page.update()

    def _selection(self) -> dict[str, str]:
        catalog = self._catalog
        if catalog is None:
            return {}
        result: dict[str, str] = {}
        for service_id in sorted(self._selected):
            service = catalog.service(service_id)
            if service is None:
                continue
            result[service_id] = self._profile if service.kind == "dns" else DIRECT_PROFILE
        return result

    def _apply_services(self, _: ft.ControlEvent) -> None:
        selection = self._selection()
        if selection and not self._busy:
            show_toast(self.page, "Спрашиваю адреса у DNS и проверяю прокси…", kind="info")
        self._run(lambda: apply_services(selection))

    def _check_visible(self, checked: bool) -> None:
        """Tick or untick every service the search shows; hosts changes on «Применить»."""
        for service_id, checkbox in self._checkboxes.items():
            if checkbox.disabled or not self._service_rows[service_id].visible:
                continue
            checkbox.value = checked
            self._on_toggle(service_id, checked)
        self.page.update()

    def _update_catalog(self, _: ft.ControlEvent) -> None:
        def work():
            ok, message = refresh_catalog_and_services(force=True)
            self._load_catalog()
            return ok, message

        self._run(work)

    # actions -------------------------------------------------------------------
    def _run(self, work) -> None:
        if self._busy:
            return
        self._busy = True

        def runner() -> None:
            try:
                ok, message = work()
            except Exception as exc:  # noqa: BLE001
                ok, message = False, str(exc)

            def finish() -> None:
                self._busy = False
                self._selected = set(get_settings().hosts_services) if ok else self._selected
                self._reload()
                show_toast(self.page, message, kind="success" if ok else "error")

            try:
                self.page.run_thread(finish)
            except AttributeError:
                finish()

        threading.Thread(target=runner, daemon=True).start()

    def _open(self, _: ft.ControlEvent) -> None:
        ok, message = open_in_editor()
        show_toast(self.page, message, kind="success" if ok else "error")

    def _restore_backup(self, _: ft.ControlEvent) -> None:
        self._run(restore_backup)

    def _restore_default(self, _: ft.ControlEvent) -> None:
        self._run(restore_default)
