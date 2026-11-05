"""Hosts editor page."""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import CheckBox, PrimaryPushButton, PushButton, SearchLineEdit, StrongBodyLabel

from src.core.paths import APP_NAME
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
from src.ui.components import Lucide, Group, OptionCard, Page, Panel, caption, clear_layout, row, select_card, status_badge
from src.ui.dispatch import run_bg
from src.ui.notifications import show_toast

_CATEGORY_ORDER = ("ai", "other", "direct")
SERVICES_HINT = (
    "Отмеченные сервисы получают в hosts адреса прокси выбранного DNS. Comss и XBOX "
    f"{APP_NAME} спрашивает вживую при «Применить», остальные берёт из каталога; неотвечающие адреса "
    "не записываются. Домены, которые DNS не проксирует, остаются обычному DNS. "
    "«Прямые записи» — готовые адреса."
)


class HostsPage(Page):
    title = "Редактирование hosts"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._busy = False
        settings = get_settings()
        self._selected: set[str] = set(settings.hosts_services)
        self._profile = settings.hosts_profile
        self._query = ""
        self._catalog: Catalog | None = None
        self._catalog_error = ""
        self._unavailable: set[str] = set()
        self._service_rows: dict[str, QWidget] = {}
        self._checkboxes: dict[str, CheckBox] = {}
        self._group_headers: dict[str, QWidget] = {}
        self._content = QWidget()
        self._stack = QVBoxLayout(self._content)
        self._stack.setContentsMargins(0, 0, 0, 0)
        self._stack.setSpacing(24)
        self.add(self._content)
        self._load_catalog()
        self._render(load_state())

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
        scroll = self.verticalScrollBar().value()
        clear_layout(self._stack)
        presets = Group("Готовые наборы", *(self._preset_card(preset, count) for preset, count in state.presets))
        own_entries = sum(state.summary.blocks.values())
        info = caption(f"{hosts_path()} · записей: {state.summary.entries}, из них {APP_NAME}: {own_entries}")
        open_btn = PushButton(Lucide("square-pen"), "Открыть в редакторе")
        open_btn.clicked.connect(self._open)
        reload_btn = PushButton(Lucide("refresh-cw"), "Обновить")
        reload_btn.clicked.connect(self._reload)
        backup_btn = PushButton(f"Вернуть копию до {APP_NAME}")
        backup_btn.setEnabled(state.has_backup)
        backup_btn.clicked.connect(lambda: self._run(restore_backup))
        default_btn = PushButton("Стандартный hosts Windows")
        default_btn.clicked.connect(lambda: self._run(restore_default))
        self._stack.addWidget(presets)
        self._stack.addWidget(self._services_section(state))
        self._stack.addWidget(Group("Файл hosts", Panel(info, row(open_btn, reload_btn), row(backup_btn, default_btn))))
        self.verticalScrollBar().setValue(scroll)

    def _services_section(self, state: HostsState) -> QWidget:
        if self._catalog is None:
            download = PushButton("Скачать каталог")
            download.clicked.connect(self._update_catalog)
            return Group("Сервисы", Panel(caption(f"Каталог сервисов недоступен: {self._catalog_error}"), row(download)))
        written = {
            service.id
            for service in self._catalog.services
            if state.summary.blocks.get(service_block_id(service.id), 0) > 0
        }
        profile_card = select_card(
            "Через какой DNS открывать сервисы",
            list(self._catalog.profiles),
            self._profile,
            self._on_profile_change,
            icon=Lucide("globe"),
        )
        search = SearchLineEdit()
        search.setPlaceholderText("Поиск")
        search.setText(self._query)
        search.textChanged.connect(self._on_search)
        self._service_rows = {}
        self._checkboxes = {}
        self._group_headers = {}
        services_panel = Panel(search, spacing=4)
        for category in _CATEGORY_ORDER:
            services = [service for service in self._catalog.services if service.category == category]
            if not services:
                continue
            header = StrongBodyLabel(CATEGORY_TITLES.get(category, category))
            header.setContentsMargins(0, 12, 0, 4)
            self._group_headers[category] = header
            services_panel.add(header)
            for service in services:
                widget = self._service_row(service, written=service.id in written)
                self._service_rows[service.id] = widget
                services_panel.add(widget)
        self._apply_filter()
        apply_btn = PrimaryPushButton("Применить")
        apply_btn.clicked.connect(self._apply_services)
        all_btn = PushButton("Выделить всё")
        all_btn.clicked.connect(lambda: self._check_visible(True))
        none_btn = PushButton("Снять всё")
        none_btn.clicked.connect(lambda: self._check_visible(False))
        update_btn = PushButton("Обновить каталог")
        update_btn.clicked.connect(self._update_catalog)
        return Group(
            "Сервисы",
            caption(SERVICES_HINT),
            profile_card,
            services_panel,
            Panel(row(apply_btn, all_btn, none_btn, update_btn, caption(f"Каталог {self._catalog.version}"))),
        )

    def _service_row(self, service, *, written: bool) -> QWidget:
        unavailable = service.id in self._unavailable
        label = f"{service.name} · {service.domains} {'записей' if service.kind != 'dns' else 'доменов'}"
        if unavailable:
            label += " · нужен IPv6"
        checkbox = CheckBox(label)
        checkbox.setChecked(service.id in self._selected)
        checkbox.setEnabled(not unavailable)
        checkbox.toggled.connect(lambda checked, sid=service.id: self._on_toggle(sid, checked))
        self._checkboxes[service.id] = checkbox
        holder = QWidget()
        line = QHBoxLayout(holder)
        line.setContentsMargins(0, 6, 0, 6)
        line.addWidget(checkbox, 1)
        if written:
            line.addWidget(status_badge("active", "В hosts"))
        return holder

    def _preset_card(self, preset, count: int) -> OptionCard:
        enabled = count > 0
        badge = status_badge("active", f"Включено · {count}") if enabled else status_badge("offline", "Выключено")
        button = (PushButton if enabled else PrimaryPushButton)("Выключить" if enabled else "Включить")
        button.clicked.connect(lambda: self._run(lambda: set_preset(preset.id, not enabled)))
        return OptionCard(preset.title, preset.description, badge, button)

    def _apply_filter(self) -> None:
        query = self._query.strip().lower()
        visible_by_category: dict[str, bool] = {}
        for service in self._catalog.services if self._catalog else ():
            widget = self._service_rows.get(service.id)
            if widget is None:
                continue
            shown = not query or query in service.name.lower()
            widget.setVisible(shown)
            visible_by_category[service.category] = visible_by_category.get(service.category, False) or shown
        for category, header in self._group_headers.items():
            header.setVisible(visible_by_category.get(category, False))

    def _reload(self) -> None:
        self._render(load_state())

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

    def _on_search(self, text: str) -> None:
        self._query = text
        self._apply_filter()

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

    def _apply_services(self) -> None:
        selection = self._selection()
        if selection and not self._busy:
            show_toast("Спрашиваю адреса у DNS и проверяю прокси…")
        self._run(lambda: apply_services(selection))

    def _check_visible(self, checked: bool) -> None:
        """Tick or untick every service the search shows; hosts changes on «Применить»."""
        for service_id, checkbox in self._checkboxes.items():
            if checkbox.isEnabled() and not self._service_rows[service_id].isHidden():
                checkbox.setChecked(checked)

    def _update_catalog(self) -> None:
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

        def done(result) -> None:
            ok, message = result
            self._busy = False
            if ok:
                self._selected = set(get_settings().hosts_services)
            self._reload()
            show_toast(message, kind="success" if ok else "error")

        run_bg(work, done, name="twowings-hosts")

    def _open(self) -> None:
        ok, message = open_in_editor()
        show_toast(message, kind="success" if ok else "error")
