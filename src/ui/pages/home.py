"""Home page — main zapret control screen."""

from __future__ import annotations

import asyncio
import threading

import flet as ft

from src.core.debug_log import debug, error as log_error, info as log_info
from src.core.paths import APP_NAME
from src.core.settings import get_settings, save_settings
from src.daemon.ipc import daemon_start, daemon_stop, is_daemon_running
from src.kernel import runtime_state
from src.kernel.public import (
    get_effective_runtime_status,
    restart_if_running,
)
from src.kernel.runtime_state import RuntimePhase
from src.modules.filters.game_filter import apply_game_filter
from src.modules.filters.ipset_filter import apply_ipset_mode
from src.modules.strategies.models import Strategy
from src.modules.strategies.repository import (
    NO_FLOWSEAL_STRATEGIES_LABEL,
    bootstrap_user_lists,
    has_flowseal_strategies,
    list_strategies,
)
from src.ui.theme import T
from src.ui.components import (
    block_section,
    make_select,
    pill_button,
    scroll_page,
    status_pill,
    ui_text,
)
from src.ui.filter_labels import (
    GAME_FILTER_OPTIONS,
    IPSET_FILTER_OPTIONS,
    game_filter_label,
    ipset_filter_label,
)
from src.ui.notifications import show_toast
from src.ui.strategy_status import strategy_status_pill

CUSTOM_HINT = (
    "Здесь можно указать свою стратегию в формате winws1 или winws2. Пример: "
    '--filter-tcp=2053,2083,2087,2096,8443 --hostlist-domains=discord.media. '
    'Листы — полным путём: --hostlist="C:\\Users\\User\\Documents\\zapret\\list-general.txt", '
    'или пользовательские листы Tigo: --hostlist="%LISTS%list-general-user.txt" '
    "(также list-exclude-user.txt, ipset-exclude-user.txt). "
    'Фейки Flowseal — "%BIN%имя.bin", порты игрового фильтра — %GameFilterTCP% и %GameFilterUDP%.'
)


class HomePage:
    def __init__(
        self,
        page: ft.Page,
        *,
        on_strategies_available=None,
    ) -> None:
        self.page = page
        self._on_strategies_available = on_strategies_available
        self._busy = False
        self._status_row = ft.Row(spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER)
        self._selected_strategy_id = get_settings().selected_strategy or ""
        self._custom_args = get_settings().custom_strategy_args or ""
        self._polling = False
        self._last_running: bool | None = None
        self._last_phase: RuntimePhase | None = None
        self._start_btn: ft.Control | None = None
        self._stop_btn: ft.Control | None = None

    def _sync_selected_strategy(self) -> None:
        settings = get_settings()
        strategies = list_strategies()
        known = {strategy.id for strategy in strategies}
        if self._selected_strategy_id in known:
            selected = self._selected_strategy_id
        elif settings.selected_strategy in known:
            selected = settings.selected_strategy or ""
        else:
            selected = strategies[0].id if strategies else ""
        self._selected_strategy_id = selected
        if settings.selected_strategy != selected:
            settings.selected_strategy = selected or None
            save_settings(settings)

    def build(self) -> ft.Control:
        bootstrap_user_lists()
        settings = get_settings()
        is_custom = settings.strategy_source == "custom"
        self._sync_selected_strategy()

        self._start_btn = pill_button("Запуск", primary=True, on_click=self._start)
        self._stop_btn = pill_button("Остановка", on_click=self._stop)

        launch_section = block_section(
            "Запуск zapret",
            ft.Row(
                [
                    ui_text("Статус", color=T.TEXT_MUTED),
                    self._status_row,
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                wrap=True,
            ),
            ft.Row([self._start_btn, self._stop_btn], wrap=True, spacing=8),
        )

        sections: list[ft.Control] = [launch_section]

        if is_custom:
            custom_field = ft.TextField(
                value=self._custom_args,
                multiline=True,
                min_lines=10,
                max_lines=16,
                on_change=self._on_custom_args_change,
                border_radius=T.RADIUS_L,
                filled=True,
                bgcolor=T.SURFACE,
                border_color=T.BORDER,
                focused_border_color=T.FOCUS,
                focused_border_width=2,
                cursor_color=T.BUTTON,
                text_style=ft.TextStyle(font_family=T.FONT_MONO, size=T.FONT_CAPTION),
            )
            sections.append(
                block_section(
                    "Своя стратегия",
                    ui_text(CUSTOM_HINT, size=T.FONT_CAPTION, color=T.TEXT_MUTED),
                    custom_field,
                )
            )
        else:
            strategies = list_strategies()
            has_strategies = bool(strategies)
            if not self._selected_strategy_id and strategies:
                self._sync_selected_strategy()

            strategy_options = (
                [(s.id, s.display_name) for s in strategies]
                if has_strategies
                else [("", NO_FLOWSEAL_STRATEGIES_LABEL)]
            )
            strategy_select = make_select(
                self.page,
                "Стратегия",
                strategy_options,
                self._selected_strategy_id if has_strategies else "",
                on_change=self._on_strategy_change if has_strategies else None,
                disabled=not has_strategies,
                option_trailing=lambda strategy_id: strategy_status_pill(strategy_id)
                if strategy_id
                else None,
            )
            game_select = make_select(
                self.page,
                "Game filter",
                GAME_FILTER_OPTIONS,
                settings.game_filter,
                on_change=self._on_game_filter_change,
            )
            ipset_select = make_select(
                self.page,
                "IPset filter",
                IPSET_FILTER_OPTIONS,
                settings.ipset_filter,
                on_change=self._on_ipset_change,
            )
            sections.extend(
                [
                    block_section("Стратегии", strategy_select),
                    block_section("Настройки фильтров", game_select, ipset_select),
                ]
            )

        content = scroll_page(*sections, page=self.page)
        self._refresh_status()
        self._start_status_polling()
        return content

    def _update_action_buttons(self) -> None:
        if not self._start_btn or not self._stop_btn:
            return
        if self._busy:
            self._start_btn.disabled = True
            self._stop_btn.disabled = True
            return
        status = self._resolve_status()
        starting = status.phase == RuntimePhase.STARTING
        stopping = status.phase == RuntimePhase.STOPPING
        running = self._status_running(status)
        settings = get_settings()
        no_flowseal = settings.strategy_source == "flowseal" and not has_flowseal_strategies()
        self._start_btn.disabled = self._busy or starting or stopping or running or no_flowseal
        self._stop_btn.disabled = self._busy or stopping or (not running and not stopping)

    def on_mounted(self) -> None:
        runtime_state.subscribe(self._on_runtime_event)
        log_info("bootstrap", f"{APP_NAME} готов к работе")
        self._start_strategies_poll()

    def _start_strategies_poll(self) -> None:
        settings = get_settings()
        if settings.strategy_source != "flowseal" or has_flowseal_strategies():
            return

        async def poll() -> None:
            while self._polling and not has_flowseal_strategies():
                await asyncio.sleep(2.0)
            if self._polling and has_flowseal_strategies() and self._on_strategies_available:
                try:
                    self.page.run_thread(self._on_strategies_available)
                except AttributeError:
                    self._on_strategies_available()

        self.page.run_task(poll)

    def stop(self) -> None:
        self._polling = False
        runtime_state.unsubscribe(self._on_runtime_event)

    def _start_status_polling(self) -> None:
        self._polling = True

        async def poll() -> None:
            while self._polling:
                self._refresh_status(only_if_changed=True)
                await asyncio.sleep(2.0)

        self.page.run_task(poll)

    def _on_runtime_event(self) -> None:
        self._refresh_status(only_if_changed=True)
        try:
            self.page.update()
        except RuntimeError:
            pass

    def _resolve_status(self):
        return get_effective_runtime_status()

    def _invalidate_status_cache(self) -> None:
        self._last_running = None
        self._last_phase = None

    def _schedule_status_resync(self, *, attempts: int = 6, interval: float = 0.5) -> None:
        async def resync() -> None:
            for _ in range(attempts):
                self._refresh_status()
                await asyncio.sleep(interval)

        self.page.run_task(resync)

    def _status_running(self, status) -> bool:
        return status.running or status.phase == RuntimePhase.RUNNING

    def _refresh_status(self, *, only_if_changed: bool = False) -> None:
        if self._busy and only_if_changed:
            return
        status = self._resolve_status()
        running = self._status_running(status)
        if (
            only_if_changed
            and self._last_running == running
            and self._last_phase == status.phase
        ):
            self._update_action_buttons()
            return
        self._last_running = running
        self._last_phase = status.phase
        if running:
            label = f"zapret запущен · {status.strategy_name}" if status.strategy_name else "zapret запущен"
            pill_key = "active"
        elif status.phase == RuntimePhase.STARTING:
            label = "запуск zapret…"
            pill_key = "connecting"
        elif status.phase == RuntimePhase.STOPPING:
            label = "остановка zapret…"
            pill_key = "connecting"
        elif status.phase == RuntimePhase.FAILED:
            label = status.error or "ошибка запуска zapret"
            pill_key = "error"
        else:
            label = "zapret не запущен"
            pill_key = "offline"
        self._status_row.controls = [status_pill(pill_key, label)]
        self._update_action_buttons()
        self.page.update()

    def _show_message(self, message: str, *, error: bool = False) -> None:
        if error:
            log_error("ui", message)
        else:
            log_info("ui", message)
        show_toast(self.page, message, kind="error" if error else "info")

    def _show_transition_status(self, label: str) -> None:
        self._invalidate_status_cache()
        self._status_row.controls = [status_pill("connecting", label)]
        self._update_action_buttons()
        self.page.update()

    def _run_bg(self, work, on_done) -> None:
        if self._busy:
            return
        self._busy = True
        self._update_action_buttons()
        self.page.update()

        def runner() -> None:
            try:
                result = work()
            except Exception as exc:  # noqa: BLE001
                result = (False, str(exc))

            def finish() -> None:
                self._busy = False
                on_done(result)
                self._update_action_buttons()

            try:
                self.page.run_thread(finish)
            except AttributeError:
                finish()

        threading.Thread(target=runner, daemon=True).start()

    def _find_strategy(self) -> Strategy | None:
        self._sync_selected_strategy()
        for strategy in list_strategies():
            if strategy.id == self._selected_strategy_id:
                return strategy
        strategies = list_strategies()
        return strategies[0] if strategies else None

    def _start(self, _: ft.ControlEvent) -> None:
        if self._busy:
            return
        self._sync_selected_strategy()
        if not is_daemon_running():
            self._show_message("Фоновый процесс Tigo не запущен", error=True)
            return
        status = get_effective_runtime_status()
        if status.running or status.phase == RuntimePhase.STARTING:
            self._show_message("Zapret уже запущен или запускается")
            return

        settings = get_settings()
        if settings.strategy_source == "custom":

            def work():
                return daemon_start()

            def done(result):
                ok, msg = result
                self._show_message(msg, error=not ok)
                self._invalidate_status_cache()
                self._refresh_status()
                self._schedule_status_resync()

            debug("ui", "start custom strategy")
            self._run_bg(work, done)
            return

        strategy = self._find_strategy()
        if not strategy:
            self._show_message(
                "Стратегии отсутствуют. Проверьте обновления в настройках.",
                error=True,
            )
            return

        settings = get_settings()
        if settings.selected_strategy != strategy.id:
            settings.selected_strategy = strategy.id
            save_settings(settings)

        debug("ui", f"start zapret strategy={strategy.name}")

        def work():
            return daemon_start(strategy.id)

        def done(result):
            ok, msg = result
            self._show_message(msg, error=not ok)
            self._invalidate_status_cache()
            self._refresh_status()
            self._schedule_status_resync()

        self._run_bg(work, done)

    def _stop(self, _: ft.ControlEvent) -> None:
        if self._busy:
            return
        if not is_daemon_running():
            self._show_message("Фоновый процесс Tigo не запущен", error=True)
            return
        status = get_effective_runtime_status()
        if not status.running:
            self._show_message("Zapret не запущен")
            return

        debug("ui", "stop zapret")

        def work():
            return daemon_stop()

        def done(result):
            ok, msg = result
            self._show_message(msg, error=not ok)
            self._invalidate_status_cache()
            self._refresh_status()
            self._schedule_status_resync()

        self._run_bg(work, done)

    def _on_custom_args_change(self, e: ft.ControlEvent) -> None:
        self._custom_args = e.control.value or ""
        settings = get_settings()
        settings.custom_strategy_args = self._custom_args
        save_settings(settings)

    def _on_strategy_change(self, strategy_id: str) -> None:
        self._selected_strategy_id = strategy_id
        settings = get_settings()
        settings.selected_strategy = strategy_id
        save_settings(settings)
        name = next((s.display_name for s in list_strategies() if s.id == strategy_id), strategy_id)
        debug("ui", f"selected strategy: {name}")
        status = get_effective_runtime_status()
        if status.running or status.phase in {RuntimePhase.STARTING, RuntimePhase.STOPPING}:
            self._show_transition_status("перезапуск zapret…")

            def work():
                return restart_if_running(strategy_id=strategy_id)

            def done(result):
                ok, msg = result
                self._show_message(msg or f"Перезапущено: {name}", error=not ok)
                self._invalidate_status_cache()
                self._refresh_status()
                self._schedule_status_resync()

            self._run_bg(work, done)

    def _on_game_filter_change(self, mode: str) -> None:
        settings = get_settings()
        if not settings.active_version:
            self._show_message("Сначала установите версию flowseal", error=True)
            return
        apply_game_filter(settings.active_version, mode)  # type: ignore[arg-type]
        label = game_filter_label(mode)
        if get_effective_runtime_status().running:
            self._show_transition_status("перезапуск zapret…")

            def work():
                return restart_if_running()

            def done(result):
                ok, msg = result
                self._show_message(msg or f"Game filter: {label}. Перезапущено.", error=not ok)
                self._invalidate_status_cache()
                self._refresh_status()
                self._schedule_status_resync()

            self._run_bg(work, done)
        else:
            self._show_message(f"Game filter: {label}.")

    def _on_ipset_change(self, mode: str) -> None:
        settings = get_settings()
        if not settings.active_version:
            self._show_message("Сначала установите версию flowseal", error=True)
            return
        try:
            apply_ipset_mode(settings.active_version, mode)  # type: ignore[arg-type]
        except FileNotFoundError as exc:
            self._show_message(str(exc), error=True)
            return
        label = ipset_filter_label(mode)
        if get_effective_runtime_status().running:
            self._show_transition_status("перезапуск zapret…")

            def work():
                return restart_if_running()

            def done(result):
                ok, msg = result
                self._show_message(msg or f"IPset filter: {label}. Перезапущено.", error=not ok)
                self._invalidate_status_cache()
                self._refresh_status()
                self._schedule_status_resync()

            self._run_bg(work, done)
        else:
            self._show_message(f"IPset filter: {label}.")
