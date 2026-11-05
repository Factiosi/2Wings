"""Home page — main zapret control screen."""

from __future__ import annotations

from PySide6.QtCore import QTimer
from qfluentwidgets import PlainTextEdit, PrimaryPushButton, PushButton

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
from src.ui.components import Lucide, Group, Page, Panel, StatusMark, caption, row, select_card
from src.ui.dispatch import run_bg, ui_call
from src.ui.filter_labels import (
    GAME_FILTER_OPTIONS,
    IPSET_FILTER_OPTIONS,
    game_filter_label,
    ipset_filter_label,
)
from src.ui.notifications import show_toast
from src.ui.strategy_status import strategy_status

POLL_MS = 2000
RESYNC_MS = 500
RESYNC_ATTEMPTS = 6
CUSTOM_HINT = (
    "Здесь можно указать свою стратегию в формате winws1 или winws2. Пример: "
    "--filter-tcp=2053,2083,2087,2096,8443 --hostlist-domains=discord.media. "
    'Листы — полным путём: --hostlist="C:\\Users\\User\\Documents\\zapret\\list-general.txt", '
    f'или пользовательские листы {APP_NAME}: --hostlist="%LISTS%list-general-user.txt" '
    "(также list-exclude-user.txt, ipset-exclude-user.txt). "
    'Фейки Flowseal — "%BIN%имя.bin", порты игрового фильтра — %GameFilterTCP% и %GameFilterUDP%.'
)


class HomePage(Page):
    title = "Главный экран"

    def __init__(self, *, on_strategies_available=None, parent=None) -> None:
        super().__init__(parent)
        self._on_strategies_available = on_strategies_available
        self._busy = False
        self._selected_strategy_id = get_settings().selected_strategy or ""
        self._last_running: bool | None = None
        self._last_phase: RuntimePhase | None = None
        self._fetching = False
        self._alive = True
        self._last_status = None
        self._status = StatusMark()
        self._start_btn = PrimaryPushButton(Lucide("play"), "Запуск")
        self._stop_btn = PushButton(Lucide("square"), "Остановка")
        self._start_btn.clicked.connect(self._start)
        self._stop_btn.clicked.connect(self._stop)
        self._build()
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll)
        self._poll_timer.start(POLL_MS)
        self._strategies_timer = QTimer(self)
        self._strategies_timer.timeout.connect(self._check_strategies)
        self._resync_left = 0
        self._resync_timer = QTimer(self)
        self._resync_timer.setInterval(RESYNC_MS)
        self._resync_timer.timeout.connect(self._resync_tick)
        runtime_state.subscribe(self._on_runtime_event)
        log_info("bootstrap", f"{APP_NAME} готов к работе")
        settings = get_settings()
        if settings.strategy_source == "flowseal" and not has_flowseal_strategies():
            self._strategies_timer.start(POLL_MS)
        self._poll()

    def stop(self) -> None:
        self._alive = False
        self._poll_timer.stop()
        self._strategies_timer.stop()
        self._resync_timer.stop()
        runtime_state.unsubscribe(self._on_runtime_event)

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

    def _build(self) -> None:
        bootstrap_user_lists()
        settings = get_settings()
        self._sync_selected_strategy()
        launch = Panel(self._status, row(self._start_btn, self._stop_btn))
        self.add(Group("Запуск zapret", launch))

        if settings.strategy_source == "custom":
            field = PlainTextEdit()
            field.setPlainText(settings.custom_strategy_args or "")
            field.setMinimumHeight(220)
            field.setStyleSheet("font-family: 'Cascadia Mono', Consolas, monospace;")
            field.textChanged.connect(lambda: self._on_custom_args_change(field.toPlainText()))
            self.add(Group("Своя стратегия", Panel(caption(CUSTOM_HINT), field)))
            return

        strategies = list_strategies()
        options = (
            [(s.id, s.display_name) for s in strategies]
            if strategies
            else [("", NO_FLOWSEAL_STRATEGIES_LABEL)]
        )
        strategy_card = select_card(
            "Стратегия",
            options,
            self._selected_strategy_id if strategies else "",
            self._on_strategy_change if strategies else None,
            icon=Lucide("waypoints"),
        )
        strategy_card.select.setMinimumWidth(240)
        strategy_card.select.badges = {s.id: strategy_status(s.id) for s in strategies}
        self.add(
            Group("Стратегии", strategy_card),
            Group(
                "Настройки фильтров",
                select_card(
                    "Game filter",
                    GAME_FILTER_OPTIONS,
                    settings.game_filter,
                    self._on_game_filter_change,
                    icon=Lucide("gamepad-2"),
                ),
                select_card(
                    "IPset filter",
                    IPSET_FILTER_OPTIONS,
                    settings.ipset_filter,
                    self._on_ipset_change,
                    icon=Lucide("filter"),
                ),
            ),
        )

    # status --------------------------------------------------------------------
    def _status_running(self, status) -> bool:
        return status.running or status.phase == RuntimePhase.RUNNING

    def _update_action_buttons(self, status=None) -> None:
        status = status or self._last_status
        if self._busy or status is None:
            self._start_btn.setEnabled(False)
            self._stop_btn.setEnabled(False)
            return
        starting = status.phase == RuntimePhase.STARTING
        stopping = status.phase == RuntimePhase.STOPPING
        running = self._status_running(status)
        no_flowseal = get_settings().strategy_source == "flowseal" and not has_flowseal_strategies()
        self._start_btn.setEnabled(not (starting or stopping or running or no_flowseal))
        self._stop_btn.setEnabled(running and not stopping)

    def _poll(self, *, force: bool = False) -> None:
        """Ask for the status off the UI thread: the daemon socket may stall for seconds."""
        if self._fetching or (self._busy and not force):
            return
        self._fetching = True

        def done(status) -> None:
            self._fetching = False
            if self._alive and status is not None:
                self._paint_status(status, only_if_changed=not force)

        run_bg(get_effective_runtime_status, done, name="twowings-home-status", on_error=lambda _exc: None)

    def _on_runtime_event(self) -> None:
        ui_call(lambda: self._poll() if self._alive else None)

    def _invalidate_status_cache(self) -> None:
        self._last_running = None
        self._last_phase = None

    def _schedule_status_resync(self) -> None:
        self._resync_left = RESYNC_ATTEMPTS
        self._resync_timer.start()

    def _resync_tick(self) -> None:
        self._resync_left -= 1
        if self._resync_left <= 0:
            self._resync_timer.stop()
        self._poll(force=True)

    def _paint_status(self, status, *, only_if_changed: bool) -> None:
        self._last_status = status
        running = self._status_running(status)
        if only_if_changed and self._last_running == running and self._last_phase == status.phase:
            self._update_action_buttons(status)
            return
        self._last_running = running
        self._last_phase = status.phase
        if running:
            label = f"zapret запущен · {status.strategy_name}" if status.strategy_name else "zapret запущен"
            kind = "active"
        elif status.phase == RuntimePhase.STARTING:
            label, kind = "запуск zapret…", "connecting"
        elif status.phase == RuntimePhase.STOPPING:
            label, kind = "остановка zapret…", "connecting"
        elif status.phase == RuntimePhase.FAILED:
            label, kind = status.error or "ошибка запуска zapret", "error"
        else:
            label, kind = "zapret не запущен", "offline"
        self._status.set_status(kind, label)
        self._update_action_buttons(status)

    def _show_transition_status(self, label: str) -> None:
        self._invalidate_status_cache()
        self._status.set_status("connecting", label)
        self._update_action_buttons()

    def _show_message(self, message: str, *, error: bool = False) -> None:
        if error:
            log_error("ui", message)
        else:
            log_info("ui", message)
        show_toast(message, kind="error" if error else "info")

    def _check_strategies(self) -> None:
        if has_flowseal_strategies():
            self._strategies_timer.stop()
            if self._on_strategies_available:
                self._on_strategies_available()

    # actions -------------------------------------------------------------------
    def _run_bg(self, work, on_done) -> None:
        if self._busy:
            return
        self._busy = True
        self._update_action_buttons()

        def finish(result) -> None:
            self._busy = False
            if self._alive:
                on_done(result)
                self._update_action_buttons()

        run_bg(work, finish, name="twowings-home-action")

    def _report(self, result, fallback: str = "") -> None:
        ok, msg = result
        self._show_message(msg or fallback, error=not ok)
        self._invalidate_status_cache()
        self._poll(force=True)
        self._schedule_status_resync()

    def _find_strategy(self) -> Strategy | None:
        self._sync_selected_strategy()
        strategies = list_strategies()
        for strategy in strategies:
            if strategy.id == self._selected_strategy_id:
                return strategy
        return strategies[0] if strategies else None

    def _start(self) -> None:
        if self._busy:
            return
        self._sync_selected_strategy()
        if not is_daemon_running():
            self._show_message(f"Фоновый процесс {APP_NAME} не запущен", error=True)
            return
        status = get_effective_runtime_status()
        if status.running or status.phase == RuntimePhase.STARTING:
            self._show_message("Zapret уже запущен или запускается")
            return

        settings = get_settings()
        if settings.strategy_source == "custom":
            debug("ui", "start custom strategy")
            self._run_bg(daemon_start, self._report)
            return

        strategy = self._find_strategy()
        if not strategy:
            self._show_message("Стратегии отсутствуют. Проверьте обновления в настройках.", error=True)
            return
        if settings.selected_strategy != strategy.id:
            settings.selected_strategy = strategy.id
            save_settings(settings)
        debug("ui", f"start zapret strategy={strategy.name}")
        self._run_bg(lambda: daemon_start(strategy.id), self._report)

    def _stop(self) -> None:
        if self._busy:
            return
        if not is_daemon_running():
            self._show_message(f"Фоновый процесс {APP_NAME} не запущен", error=True)
            return
        if not get_effective_runtime_status().running:
            self._show_message("Zapret не запущен")
            return
        debug("ui", "stop zapret")
        self._run_bg(daemon_stop, self._report)

    def _on_custom_args_change(self, text: str) -> None:
        settings = get_settings()
        settings.custom_strategy_args = text
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
            self._run_bg(
                lambda: restart_if_running(strategy_id=strategy_id),
                lambda result: self._report(result, f"Перезапущено: {name}"),
            )

    def _restart_after_filter(self, title: str, label: str) -> None:
        if get_effective_runtime_status().running:
            self._show_transition_status("перезапуск zapret…")
            self._run_bg(restart_if_running, lambda result: self._report(result, f"{title}: {label}. Перезапущено."))
        else:
            self._show_message(f"{title}: {label}.")

    def _on_game_filter_change(self, mode: str) -> None:
        settings = get_settings()
        if not settings.active_version:
            self._show_message("Сначала установите версию flowseal", error=True)
            return
        apply_game_filter(settings.active_version, mode)  # type: ignore[arg-type]
        self._restart_after_filter("Game filter", game_filter_label(mode))

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
        self._restart_after_filter("IPset filter", ipset_filter_label(mode))
