"""Strategy testing and selection page."""

from __future__ import annotations

import threading
from typing import Callable

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CheckBox,
    HorizontalSeparator,
    PrimaryPushButton,
    PushButton,
    RadioButton,
    SimpleCardWidget,
    VerticalSeparator,
)

from src.core.settings import get_settings, save_settings
from src.daemon.ipc import (
    daemon_start,
    daemon_stop,
    daemon_test_start,
    daemon_test_status,
    daemon_test_stop,
)
from src.kernel.public import get_effective_runtime_status
from src.modules.strategies.models import Strategy
from src.modules.strategies.repository import list_strategies
from src.modules.strategy_testing import results as tr
from src.modules.strategy_testing.results import ResultChange
from src.ui.components import (
    COLOR_ERROR,
    COLOR_MUTED,
    EXPAND_MS,
    ExpandChevron,
    Group,
    Lucide,
    Page,
    Panel,
    caption,
    clear_layout,
    row,
    play_at_display_rate,
    spinner,
)
from src.ui.dispatch import run_bg, ui_call
from src.ui.notifications import show_toast
from src.ui.probe_table import ProbeTableView
from src.ui.strategy_status import strategy_actions_disabled, strategy_badge

POLL_MS = 500
_NO_LIMIT = 16777215  # QWIDGETSIZE_MAX
PROBE_FLUSH_SECONDS = 0.12


def compute_expanded_state(
    *,
    running: bool,
    current_strategy_id: str | None,
    session_active: bool,
    planned_strategy_ids: set[str],
    completed_strategy_ids: set[str],
    current_expanded: set[str],
) -> set[str]:
    """Pure expansion policy used by the daemon polling state machine."""
    session_completed = completed_strategy_ids & planned_strategy_ids
    if running and current_strategy_id:
        return {current_strategy_id}
    if not running and session_active:
        return session_completed
    return set(current_expanded)


class _ClickZone(QWidget):
    """Part of a row that answers to a click anywhere in it, so nobody has to aim."""

    def __init__(self, on_click, parent: QWidget) -> None:
        super().__init__(parent)
        self._on_click = on_click
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self._on_click()


class _StrategyRow(SimpleCardWidget):
    """Left part ticks the strategy, right part opens the probe table below."""

    def __init__(self, page: "StrategiesPage", strategy: Strategy, *, expanded: bool, running: bool) -> None:
        super().__init__()
        self._page = page
        self.strategy_id = strategy.id
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 8, 8, 8)
        outer.setSpacing(8)
        head = QHBoxLayout()
        head.setSpacing(0)
        left = _ClickZone(lambda: self.checkbox.toggle(), self)
        left_line = QHBoxLayout(left)
        left_line.setContentsMargins(0, 4, 8, 4)
        self.checkbox = CheckBox(strategy.display_name, left)
        self.checkbox.setChecked(strategy.id in page._selected)
        self.checkbox.toggled.connect(lambda checked: page._on_strategy_toggle(strategy.id, checked))
        left_line.addWidget(self.checkbox)
        left_line.addStretch(1)
        right = _ClickZone(lambda: page._toggle_expand(strategy.id), self)
        right_line = QHBoxLayout(right)
        right_line.setContentsMargins(8, 4, 0, 4)
        right_line.setSpacing(12)
        right_line.addStretch(1)
        if running:
            right_line.addWidget(spinner(16, right))
        right_line.addWidget(strategy_badge(strategy.id, right))
        self.chevron = ExpandChevron(expanded, right)
        # The whole right part is the button.
        self.chevron.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        right_line.addWidget(self.chevron)
        head.addWidget(left, 4)
        head.addWidget(VerticalSeparator(self))
        head.addWidget(right, 6)
        outer.addLayout(head)
        self.body = QWidget(self)
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 4, 8, 8)
        self.body_layout.setSpacing(12)
        outer.addWidget(self.body)
        self.table: ProbeTableView | None = None
        self._opening = expanded
        self._slide = QPropertyAnimation(self.body, b"maximumHeight", self)
        self._slide.setDuration(EXPAND_MS)
        self._slide.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._slide.finished.connect(self._on_slide_done)
        self.set_expanded(expanded)

    def _ensure_body(self) -> None:
        if self.table is not None:
            return
        self.table = ProbeTableView(self.strategy_id, self.body)
        self.body_layout.addWidget(self.table)
        self._actions = QWidget(self.body)
        self.body_layout.addWidget(self._actions)
        layout = QHBoxLayout(self._actions)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self._choose = PushButton("Выбрать стратегию", self._actions)
        self._choose.clicked.connect(lambda: self._page._choose_strategy(self.strategy_id))
        self._start = PrimaryPushButton("Выбрать стратегию и запустить", self._actions)
        self._start.clicked.connect(lambda: self._page._choose_and_start(self.strategy_id))
        layout.addWidget(self._choose)
        layout.addWidget(self._start)
        layout.addStretch(1)

    def set_expanded(self, expanded: bool, *, animate: bool = False) -> None:
        if expanded:
            self._ensure_body()
            self.sync_actions()
        if not animate:
            self.body.setMaximumHeight(_NO_LIMIT)
            self.body.setVisible(expanded)
            return
        self.chevron.set_expanded(expanded)
        self._slide.stop()
        start = self.body.height() if self.body.isVisible() else 0
        self.body.setMaximumHeight(start)
        self.body.setVisible(True)
        self._slide.setStartValue(start)
        self._slide.setEndValue(self.body.sizeHint().height() if expanded else 0)
        self._opening = expanded
        play_at_display_rate(self._slide)

    def _on_slide_done(self) -> None:
        if self._opening:
            # The table may grow after opening: the limit was only for the animation.
            self.body.setMaximumHeight(_NO_LIMIT)
        else:
            self.body.setVisible(False)

    def sync_actions(self) -> None:
        if self.table is None:
            return
        disabled = strategy_actions_disabled(
            self.strategy_id,
            selected_strategy=get_settings().selected_strategy,
            tests_running=self._page._tests_running,
        )
        self._choose.setEnabled(not disabled)
        self._start.setEnabled(not disabled)


class StrategiesPage(Page):
    title = "Тестирование стратегий"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._test_type = "standard"
        self._tests_running = False
        self._last_daemon_current: str | None = None
        self._seen_daemon_completed: set[str] = set()
        self._last_daemon_message = ""
        self._last_daemon_success = True
        self._test_phase = "idle"
        self._focused_strategy_id: str | None = None
        self._session_completed: set[str] = set()
        self._session_planned: set[str] = set()
        self._session_active = False
        self._selected: set[str] = set()
        self._expanded: set[str] = set()
        self._rows: dict[str, _StrategyRow] = {}
        self._results_unsubscribe: Callable[[], None] | None = None
        self._strategies: list[Strategy] = []
        self._probe_dirty: set[str] = set()
        self._probe_flush_timer: threading.Timer | None = None
        self._probe_timer_lock = threading.Lock()
        self._alive = True
        self._polling_now = False
        self._master_guard = False
        self._build()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(POLL_MS)

    def stop(self) -> None:
        self._alive = False
        self._timer.stop()
        with self._probe_timer_lock:
            if self._probe_flush_timer:
                self._probe_flush_timer.cancel()
                self._probe_flush_timer = None
            self._probe_dirty.clear()
        if self._results_unsubscribe:
            self._results_unsubscribe()
            self._results_unsubscribe = None

    def _build(self) -> None:
        settings = get_settings()
        version = settings.active_version
        self._strategies = list_strategies(settings)
        tr.subscribe(self._on_results_change)
        self._results_unsubscribe = lambda: tr.unsubscribe(self._on_results_change)

        standard = RadioButton("Стандартный тест (HTTP / Ping)")
        standard.setChecked(True)
        standard.toggled.connect(lambda on: self._set_test_type("standard") if on else None)
        dpi = RadioButton("Проверка DPI (TCP 16–20 freeze)")
        dpi.toggled.connect(lambda on: self._set_test_type("dpi") if on else None)

        self._start_btn = PrimaryPushButton(Lucide("play"), "Запуск тестов")
        self._start_btn.clicked.connect(self._start_tests)
        self._stop_btn = PushButton(Lucide("square"), "Остановка тестов")
        self._stop_btn.clicked.connect(self._stop_tests)
        self._status_text = caption("")
        self._master = CheckBox("Все стратегии")
        self._master.toggled.connect(self._on_master_toggle)
        self._list_holder = QWidget()
        self._list = QVBoxLayout(self._list_holder)
        self._list.setContentsMargins(0, 0, 0, 0)
        self._list.setSpacing(4)
        # Extra height during an animation must not spread the rows apart.
        self._list.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.add(
            Group("Тип тестирования", Panel(standard, dpi, spacing=8)),
            Group(
                "Стратегии к тестированию",
                Panel(
                    row(self._start_btn, self._stop_btn),
                    self._status_text,
                    HorizontalSeparator(),
                    self._master,
                ),
                self._list_holder,
            ),
        )
        if version:
            self._populate_list()
        else:
            self._list.addWidget(BodyLabel("Сначала установите версию flowseal"))
            self._master.setEnabled(False)
        self._update_buttons()

    def _set_test_type(self, value: str) -> None:
        self._test_type = value

    # list ----------------------------------------------------------------------
    def _strategy_sort_key(self, strategy: Strategy) -> tuple[int, str]:
        sid = strategy.id
        if self._focused_strategy_id == sid or tr.current_strategy_id() == sid:
            return (0, strategy.display_name.lower())
        item = tr.get_result(sid)
        if item is None:
            return (3, strategy.display_name.lower())
        rank_by_state = {"full": 1, "partial": 2, "failed": 4, "unknown": 4}
        return (rank_by_state.get(item.state, 3), strategy.display_name.lower())

    def _populate_list(self) -> None:
        scroll = self.verticalScrollBar().value()
        clear_layout(self._list)
        self._rows.clear()
        if not self._strategies:
            self._list.addWidget(BodyLabel("Нет доступных стратегий"))
        for strategy in sorted(self._strategies, key=self._strategy_sort_key):
            self._rows[strategy.id] = self._new_row(strategy)
            self._list.addWidget(self._rows[strategy.id])
        self._update_buttons()
        self.verticalScrollBar().setValue(scroll)

    def _new_row(self, strategy: Strategy) -> _StrategyRow:
        return _StrategyRow(
            self,
            strategy,
            expanded=strategy.id in self._expanded,
            running=self._test_phase == "testing" and self._focused_strategy_id == strategy.id,
        )

    def _toggle_expand(self, strategy_id: str) -> None:
        if self._tests_running:
            return
        opening = strategy_id not in self._expanded
        if opening:
            self._expanded.add(strategy_id)
        else:
            self._expanded.discard(strategy_id)
        row_widget = self._rows.get(strategy_id)
        if row_widget is not None:
            row_widget.set_expanded(opening, animate=True)

    def _refresh_row(self, strategy_id: str) -> None:
        old = self._rows.get(strategy_id)
        strategy = next((s for s in self._strategies if s.id == strategy_id), None)
        if old is None or strategy is None:
            return
        index = self._list.indexOf(old)
        fresh = self._new_row(strategy)
        self._list.insertWidget(index, fresh)
        self._list.removeWidget(old)
        old.setParent(None)
        old.deleteLater()
        self._rows[strategy_id] = fresh

    def _refresh_actions(self) -> None:
        for row_widget in self._rows.values():
            row_widget.sync_actions()

    # results -------------------------------------------------------------------
    def _schedule_probe_updates(self, strategy_id: str) -> None:
        with self._probe_timer_lock:
            self._probe_dirty.add(strategy_id)
            if self._probe_flush_timer is not None:
                return
            self._probe_flush_timer = threading.Timer(PROBE_FLUSH_SECONDS, self._flush_probe_updates)
            self._probe_flush_timer.daemon = True
            self._probe_flush_timer.start()

    def _flush_probe_updates(self) -> None:
        with self._probe_timer_lock:
            pending = set(self._probe_dirty)
            self._probe_dirty.clear()
            self._probe_flush_timer = None
        if pending:
            ui_call(lambda: self._apply_probe_updates(pending))

    def _apply_probe_updates(self, strategy_ids: set[str]) -> None:
        if not self._alive:
            return
        for strategy_id in strategy_ids:
            row_widget = self._rows.get(strategy_id)
            if row_widget is not None and row_widget.table is not None:
                row_widget.table.sync(strategy_id)

    def _on_results_change(self, change: ResultChange) -> None:
        if change.event == "probe" and change.strategy_id:
            self._schedule_probe_updates(change.strategy_id)
            return
        ui_call(self._refresh_list)

    def _refresh_list(self) -> None:
        if self._alive and get_settings().active_version:
            self._populate_list()

    # selection -----------------------------------------------------------------
    def _on_master_toggle(self, checked: bool) -> None:
        if self._master_guard:
            return
        self._selected = {s.id for s in self._strategies} if checked else set()
        for strategy_id, row_widget in self._rows.items():
            row_widget.checkbox.blockSignals(True)
            row_widget.checkbox.setChecked(strategy_id in self._selected)
            row_widget.checkbox.blockSignals(False)
        self._update_buttons()

    def _on_strategy_toggle(self, strategy_id: str, checked: bool) -> None:
        if checked:
            self._selected.add(strategy_id)
        else:
            self._selected.discard(strategy_id)
        self._master_guard = True
        self._master.setChecked(bool(self._strategies) and len(self._selected) == len(self._strategies))
        self._master_guard = False
        self._update_buttons()

    def _update_buttons(self) -> None:
        running = self._tests_running
        self._start_btn.setEnabled(not running and bool(self._selected))
        self._stop_btn.setEnabled(running)

    def _set_status(self, message: str, *, error: bool = False) -> None:
        self._status_text.setText(message)
        self._status_text.setTextColor(*(COLOR_ERROR if error else COLOR_MUTED))

    def _snack(self, message: str, *, error: bool = False) -> None:
        self._set_status(message, error=error)
        show_toast(message, kind="error" if error else "info")

    def _choose_strategy(self, strategy_id: str) -> None:
        if self._tests_running or not tr.is_tested(strategy_id):
            return
        settings = get_settings()
        if settings.selected_strategy == strategy_id:
            self._snack("Стратегия уже выбрана")
            return
        settings.selected_strategy = strategy_id
        save_settings(settings)
        self._refresh_actions()
        self._snack("Стратегия применена, но не запущена")

    def _choose_and_start(self, strategy_id: str) -> None:
        if self._tests_running or not tr.is_tested(strategy_id):
            return
        settings = get_settings()
        if settings.selected_strategy != strategy_id:
            settings.selected_strategy = strategy_id
            save_settings(settings)
            self._refresh_actions()

        def work() -> tuple[bool, str]:
            if get_effective_runtime_status().running:
                stopped, message = daemon_stop()
                if not stopped:
                    return False, message
            return daemon_start(strategy_id)

        def done(result) -> None:
            ok, msg = result
            if not self._alive:
                return
            if ok:
                self._snack("Стратегия применена, winws запущен")
            else:
                self._snack(msg or "Не удалось запустить winws", error=True)

        run_bg(work, done, name="twowings-select-and-start")

    # tests ---------------------------------------------------------------------
    def _start_tests(self) -> None:
        settings = get_settings()
        if not settings.active_version or not self._selected:
            return
        self._seen_daemon_completed.clear()
        self._session_completed.clear()
        self._session_planned = set(self._selected)
        self._session_active = True
        self._last_daemon_current = None
        self._update_buttons()
        version = settings.active_version or ""
        chosen = sorted(self._selected)

        def done(result) -> None:
            ok, msg = result
            if not self._alive:
                return
            self._tests_running = ok
            if not ok:
                self._session_active = False
                self._session_planned.clear()
            self._update_buttons()
            self._set_status(msg if ok else f"Ошибка: {msg}", error=not ok)
            if not ok:
                self._snack(msg, error=True)

        run_bg(lambda: daemon_test_start(version, self._test_type, chosen), done, name="twowings-test-start")

    def _stop_tests(self) -> None:
        def done(result) -> None:
            ok, msg = result
            if not self._alive:
                return
            self._set_status(msg, error=not ok)
            if not ok:
                self._snack(msg, error=True)

        run_bg(daemon_test_stop, done, name="twowings-test-stop")

    def _poll(self) -> None:
        """Ask the daemon off the UI thread: its socket may stall for seconds."""
        if self._polling_now:
            return
        self._polling_now = True

        def done(state) -> None:
            self._polling_now = False
            if self._alive and state and state.get("ok"):
                self._apply_state(state)

        run_bg(daemon_test_status, done, name="twowings-test-status", on_error=lambda _exc: None)

    def _apply_state(self, state: dict) -> None:
        running = bool(state.get("running"))
        phase = str(state.get("phase") or ("testing" if running else "idle"))
        if phase not in {"idle", "testing", "pause"}:
            phase = "testing" if running else "idle"
        current_raw = state.get("current_strategy_id")
        current = str(current_raw) if current_raw else None
        running_changed = self._tests_running != running
        layout_changed = current != self._focused_strategy_id or phase != self._test_phase or running_changed
        self._tests_running = running
        if running:
            self._session_active = True
        planned_raw = state.get("planned_strategy_ids")
        if isinstance(planned_raw, list):
            daemon_planned = {str(value) for value in planned_raw if isinstance(value, str) and value}
            if daemon_planned:
                self._session_planned = daemon_planned
        completed_raw = state.get("completed_strategy_ids")
        completed = (
            {str(value) for value in completed_raw if isinstance(value, str)}
            if isinstance(completed_raw, list)
            else set()
        )
        newly_completed = completed - self._seen_daemon_completed
        for strategy_id in newly_completed:
            tr.reload_strategy(strategy_id)
        self._seen_daemon_completed.update(completed)
        session_completed = completed & self._session_planned
        if session_completed != self._session_completed:
            self._session_completed = session_completed
            layout_changed = True
        elif newly_completed:
            layout_changed = True

        version_raw = state.get("version")
        version = str(version_raw) if version_raw else None
        probe = state.get("probe")
        if isinstance(probe, dict):
            probe_sid = probe.get("strategy_id")
            probe_rows = probe.get("rows")
            if isinstance(probe_sid, str) and isinstance(probe_rows, list):
                tr.apply_remote_probe_snapshot(probe_sid, probe_rows, version=version)

        remote_current = current if phase == "testing" else None
        if remote_current != self._last_daemon_current:
            tr.set_remote_current(remote_current, version=version)
            self._last_daemon_current = remote_current

        self._focused_strategy_id = current
        self._test_phase = phase
        desired_expanded = compute_expanded_state(
            running=running,
            current_strategy_id=current,
            session_active=self._session_active,
            planned_strategy_ids=self._session_planned,
            completed_strategy_ids=self._session_completed,
            current_expanded=self._expanded,
        )
        if not running and self._session_active:
            self._session_active = False
            self._session_planned.clear()
        if desired_expanded != self._expanded:
            self._expanded = desired_expanded
            layout_changed = True

        message = str(state.get("message") or "")
        success = bool(state.get("success", True))
        if running_changed:
            self._update_buttons()
        if message and (message != self._last_daemon_message or success != self._last_daemon_success):
            self._set_status(message, error=not success)
        self._last_daemon_message = message
        self._last_daemon_success = success
        if layout_changed:
            self._refresh_list()
