"""DNS settings page."""

from __future__ import annotations

from PySide6.QtCore import QTimer

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
from src.ui.components import Lucide, Group, Page, Panel, caption, row, select_card, text_field
from src.ui.dispatch import run_bg
from src.ui.notifications import show_toast

AUTO_DNS_KEY = "__auto__"
CUSTOM_DNS_KEY = "__custom__"
FLUSH_LABEL_MS = 5000


class DnsPage(Page):
    title = "Изменение DNS"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._busy = False
        self._adapter = ALL_ADAPTERS_KEY
        self._dns_choice = AUTO_DNS_KEY
        self._applied_snapshot: str | None = None
        self._providers_map: dict[str, tuple[list[str], list[str]]] = {}
        self._status = caption("")
        self._status.setTextInteractionFlags(self._status.textInteractionFlags())
        self._build()

    def _build(self) -> None:
        state = load_state(self._adapter or None)
        self._adapter = state.selected_adapter
        adapter_options = [(ALL_ADAPTERS_KEY, "Все адаптеры")]
        adapter_options.extend((name, name) for name in state.adapters if name != ALL_ADAPTERS_KEY)

        provider_options = [(AUTO_DNS_KEY, "Авто (DHCP)")]
        for group, name, desc, ipv4, ipv6 in flatten_providers():
            key = f"{group}::{name}"
            provider_options.append((key, f"{name} ({desc})"))
            self._providers_map[key] = (ipv4, ipv6)
        provider_options.append((CUSTOM_DNS_KEY, "Свои настройки DNS"))

        self._dns_card = select_card("DNS", provider_options, self._dns_choice, self._on_dns_choice_change, icon=Lucide("globe"))
        self._dns_card.select.setMinimumWidth(340)
        self._primary = text_field(placeholder="Основной DNS")
        self._secondary = text_field(placeholder="Дополнительный DNS")
        self._primary.textChanged.connect(lambda _text: self._update_apply_button())
        self._secondary.textChanged.connect(lambda _text: self._update_apply_button())
        self._custom = Panel(self._primary, self._secondary)
        self._custom.setVisible(False)

        self._apply_btn = PrimaryPushButton("Применить")
        self._apply_btn.clicked.connect(self._apply)
        self._reset_btn = PushButton("Сбросить настройки DNS")
        self._reset_btn.clicked.connect(self._reset_dns)
        self._flush_btn = PushButton("Сбросить DNS-кэш")
        self._flush_btn.clicked.connect(self._flush)

        self._refresh_status(state)
        self.add(
            self._status,
            Group(
                "Настройки",
                select_card("Адаптер", adapter_options, self._adapter, self._on_adapter_change, icon=Lucide("network")),
                self._dns_card,
                self._custom,
                Panel(row(self._apply_btn, self._reset_btn, self._flush_btn)),
            ),
        )

    def _snapshot(self) -> str:
        return "|".join([self._adapter, self._dns_choice, self._primary.text().strip(), self._secondary.text().strip()])

    def _update_apply_button(self) -> None:
        applied = self._applied_snapshot is not None and self._snapshot() == self._applied_snapshot
        self._apply_btn.setText("Применено" if applied else "Применить")
        self._apply_btn.setEnabled(not applied and not self._busy)

    def _refresh_status(self, state) -> None:
        self._status.setText("\n".join(format_status_lines(state)))

    def _on_adapter_change(self, value: str) -> None:
        self._adapter = value or ALL_ADAPTERS_KEY
        self._applied_snapshot = None
        self._refresh_status(load_state(self._adapter))
        self._update_apply_button()

    def _on_dns_choice_change(self, value: str) -> None:
        self._dns_choice = value or AUTO_DNS_KEY
        self._custom.setVisible(self._dns_choice == CUSTOM_DNS_KEY)
        self._update_apply_button()

    def _run_bg(self, work, *, on_success=None) -> None:
        if self._busy:
            return
        self._busy = True
        self._update_apply_button()

        def done(result) -> None:
            ok, msg = result
            self._busy = False
            if ok and on_success:
                on_success()
            self._update_apply_button()
            show_toast(msg, kind="success" if ok else "error")

        run_bg(work, done, name="twowings-dns")

    def _apply(self) -> None:
        state = load_state(self._adapter or None)
        adapters = resolve_apply_adapters(self._adapter, state.adapters)
        choice = self._dns_choice
        primary = self._primary.text().strip()
        secondary = self._secondary.text().strip() or None

        def work():
            if choice == AUTO_DNS_KEY:
                return apply_auto(adapters)
            if choice == CUSTOM_DNS_KEY:
                if not primary:
                    return False, "Укажите основной DNS"
                return apply_custom(adapters, primary, secondary)
            ipv4, ipv6 = self._providers_map.get(choice, ([], []))
            return apply_provider(adapters, ipv4, ipv6, ipv6_available=state.ipv6_available)

        def on_success() -> None:
            self._applied_snapshot = self._snapshot()
            self._refresh_status(load_state(self._adapter or None))

        self._run_bg(work, on_success=on_success)

    def _reset_dns(self) -> None:
        state = load_state(self._adapter or None)
        adapters = resolve_apply_adapters(self._adapter, state.adapters)

        def on_success() -> None:
            self._dns_choice = AUTO_DNS_KEY
            self._primary.clear()
            self._secondary.clear()
            self._dns_card.select.set_value(AUTO_DNS_KEY)
            self._custom.setVisible(False)
            self._applied_snapshot = self._snapshot()
            self._refresh_status(load_state(self._adapter or None))

        self._run_bg(lambda: reset_dns_settings(adapters), on_success=on_success)

    def _flush(self) -> None:
        def on_success() -> None:
            self._flush_btn.setText("DNS-кэш сброшен")
            self._flush_btn.setEnabled(False)
            QTimer.singleShot(FLUSH_LABEL_MS, self, self._reset_flush_button)

        self._run_bg(flush_cache, on_success=on_success)

    def _reset_flush_button(self) -> None:
        self._flush_btn.setText("Сбросить DNS-кэш")
        self._flush_btn.setEnabled(True)
