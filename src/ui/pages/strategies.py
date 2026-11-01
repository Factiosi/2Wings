"""Strategy testing and selection page."""

from __future__ import annotations

import asyncio
import math
import threading
from typing import Callable

import flet as ft

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
from src.ui.theme import T
from src.ui.components import (
    CHEVRON_ANIM,
    EXPAND_ANIM,
    bind_select_dismiss,
    quiet_checkbox,
    block_section,
    pill_button,
    scroll_page,
    set_pill_disabled,
    ui_text,
)
from src.ui.notifications import show_toast
from src.ui.probe_table import ProbeTableView, factiosi_spinner
from src.ui.strategy_status import strategy_actions_disabled, strategy_status_pill


def _probe_body_padding(*, expanded: bool) -> ft.Padding:
    if not expanded:
        return ft.Padding.all(0)
    return ft.Padding.only(left=12, right=12, bottom=12, top=4)


def _should_build_probe_table(strategy_id: str) -> bool:
    return True


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


class StrategiesPage:
    def __init__(self, page: ft.Page) -> None:
        self.page = page
        self._test_type = "standard"
        self._tests_running = False
        self._polling = False
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
        self._checkboxes: dict[str, ft.Checkbox] = {}
        self._master_checkbox: ft.Checkbox | None = None
        self._start_btn: ft.Control | None = None
        self._stop_btn: ft.Control | None = None
        self._status_text: ft.Text | None = None
        self._strategy_header: ft.Row | None = None
        self._strategy_actions: ft.Row | None = None
        self._strategy_list_panel: ft.Column | None = None
        self._strategy_list = ft.Column(spacing=4, tight=True)
        self._results_unsubscribe: Callable[[], None] | None = None
        self._strategies: list[Strategy] = []
        self._strategies_by_id: dict[str, Strategy] = {}
        self._row_index: dict[str, int] = {}
        self._probe_body_by_id: dict[str, ft.Container] = {}
        self._probe_table_by_id: dict[str, ProbeTableView] = {}
        self._chevron_by_id: dict[str, ft.Icon] = {}
        self._probe_dirty: set[str] = set()
        self._probe_flush_timer: threading.Timer | None = None
        self._probe_timer_lock = threading.Lock()
        self._last_current_id: str | None = None

    def stop(self) -> None:
        self._polling = False
        with self._probe_timer_lock:
            if self._probe_flush_timer:
                self._probe_flush_timer.cancel()
                self._probe_flush_timer = None
            self._probe_dirty.clear()
        if self._results_unsubscribe:
            self._results_unsubscribe()
            self._results_unsubscribe = None

    def _strategy_sort_key(self, strategy: Strategy) -> tuple[int, str]:
        sid = strategy.id
        if self._focused_strategy_id == sid or tr.current_strategy_id() == sid:
            return (0, strategy.display_name.lower())

        item = tr.get_result(sid)
        if item is None:
            return (3, strategy.display_name.lower())

        rank_by_state = {
            "full": 1,
            "partial": 2,
            "failed": 4,
            "unknown": 4,
        }
        return (rank_by_state.get(item.state, 3), strategy.display_name.lower())

    def _sorted_strategies(self) -> list[Strategy]:
        return sorted(self._strategies, key=self._strategy_sort_key)

    def _ui(self, fn) -> None:
        """Run UI mutation on the Flet main thread."""
        try:
            self.page.run_thread(fn)
        except AttributeError:
            fn()

    def _populate_list(self) -> None:
        rows: list[ft.Control] = []
        self._row_index.clear()
        self._probe_body_by_id.clear()
        self._probe_table_by_id.clear()
        self._chevron_by_id.clear()

        if not self._strategies:
            rows.append(ui_text("Нет доступных стратегий", color=T.TEXT_MUTED))
        else:
            self._checkboxes.clear()
            for index, strategy in enumerate(self._sorted_strategies()):
                rows.append(self._build_strategy_row(strategy))
                self._row_index[strategy.id] = index

        self._strategy_list.controls = rows
        self._update_buttons()

    def _probe_table_for(self, strategy_id: str) -> ProbeTableView:
        view = self._probe_table_by_id.get(strategy_id)
        if view is None:
            view = ProbeTableView(strategy_id)
            self._probe_table_by_id[strategy_id] = view
        return view

    def _probe_actions_for(self, strategy_id: str) -> ft.Row:
        disabled = strategy_actions_disabled(
            strategy_id,
            selected_strategy=get_settings().selected_strategy,
            tests_running=self._tests_running,
        )
        return ft.Row(
            [
                pill_button(
                    "Выбрать стратегию",
                    on_click=lambda _e, sid=strategy_id: self._choose_strategy(sid),
                    disabled=disabled,
                ),
                pill_button(
                    "Выбрать стратегию и запустить",
                    primary=True,
                    on_click=lambda _e, sid=strategy_id: self._choose_and_start(sid),
                    disabled=disabled,
                ),
            ],
            spacing=8,
            wrap=True,
        )

    def _refresh_strategy_action_buttons(self) -> None:
        for strategy_id in self._expanded:
            body = self._probe_body_by_id.get(strategy_id)
            if not body:
                continue
            content = self._probe_content_for(strategy_id)
            if content is None:
                continue
            body.content = content
            if body.page:
                try:
                    body.update()
                except RuntimeError:
                    pass

    def _probe_content_for(self, strategy_id: str) -> ft.Control | None:
        if not _should_build_probe_table(strategy_id):
            return None
        return ft.Column(
            [self._probe_table_for(strategy_id).control, self._probe_actions_for(strategy_id)],
            spacing=8,
            tight=True,
        )

    def _update_probe_only(self, strategy_id: str) -> None:
        body = self._probe_body_by_id.get(strategy_id)
        if not body or strategy_id not in self._expanded:
            return
        if not _should_build_probe_table(strategy_id):
            return
        view = self._probe_table_by_id.get(strategy_id)
        if view is None:
            body.content = self._probe_content_for(strategy_id)
        else:
            view.sync(strategy_id)
        if body.page:
            try:
                body.update()
            except RuntimeError:
                pass

    def _expanded_body_height(self, strategy_id: str) -> int:
        view = self._probe_table_by_id.get(strategy_id)
        count = len(view._row_order) if view is not None else 0
        if count == 0:
            count = len(tr.get_probe_table(strategy_id) or tr.default_probe_table())
        return count * 34 + 130

    def _animate_expand(self, strategy_id: str, opening: bool) -> None:
        chevron = self._chevron_by_id.get(strategy_id)
        if chevron is not None:
            chevron.animate_rotation = CHEVRON_ANIM
            chevron.rotate = ft.Rotate(
                math.pi if opening else 0,
                alignment=ft.Alignment.CENTER,
            )
            if chevron.page:
                try:
                    chevron.update()
                except RuntimeError:
                    pass
        body = self._probe_body_by_id.get(strategy_id)
        if body is None:
            return
        body.animate = EXPAND_ANIM
        body.animate_opacity = EXPAND_ANIM
        if opening:
            body.content = self._probe_content_for(strategy_id)
            body.padding = _probe_body_padding(expanded=True)
            body.height = self._expanded_body_height(strategy_id)
            body.opacity = 1
        else:
            body.height = 0
            body.opacity = 0
            body.padding = _probe_body_padding(expanded=False)
        if body.page:
            try:
                body.update()
            except RuntimeError:
                pass

    def _update_row(self, strategy_id: str) -> None:
        strategy = self._strategies_by_id.get(strategy_id)
        index = self._row_index.get(strategy_id)
        if strategy is None or index is None:
            return
        self._strategy_list.controls[index] = self._build_strategy_row(strategy)
        self._row_index[strategy_id] = index
        if self._strategy_list.page:
            try:
                self._strategy_list.update()
            except RuntimeError:
                pass

    def _apply_probe_updates(self, strategy_ids: set[str]) -> None:
        for strategy_id in strategy_ids:
            self._update_probe_only(strategy_id)

    def _schedule_probe_updates(self, strategy_id: str) -> None:
        with self._probe_timer_lock:
            self._probe_dirty.add(strategy_id)
            if self._probe_flush_timer is not None:
                return
            self._probe_flush_timer = threading.Timer(0.12, self._flush_probe_updates)
            self._probe_flush_timer.daemon = True
            self._probe_flush_timer.start()

    def _flush_probe_updates(self) -> None:
        with self._probe_timer_lock:
            pending = set(self._probe_dirty)
            self._probe_dirty.clear()
            self._probe_flush_timer = None
        if pending:
            self._ui(lambda: self._apply_probe_updates(pending))

    def _handle_status_change(self, strategy_id: str | None) -> None:
        desired = [s.id for s in self._sorted_strategies()]
        current_ids = sorted(self._row_index.keys(), key=lambda sid: self._row_index[sid])
        if desired != current_ids and len(desired) == len(current_ids):
            row_by_id = {
                sid: self._strategy_list.controls[idx] for sid, idx in self._row_index.items()
            }
            self._strategy_list.controls = [row_by_id[sid] for sid in desired]
            self._row_index = {sid: index for index, sid in enumerate(desired)}

        current = tr.current_strategy_id()
        touch = {sid for sid in (self._last_current_id, current, strategy_id) if sid}
        for sid in touch:
            if sid in self._row_index:
                self._update_row(sid)
        self._last_current_id = current

        if self._strategy_list.page:
            try:
                self._strategy_list.update()
            except RuntimeError:
                pass

    def _on_results_change(self, change: ResultChange) -> None:
        if change.event == "probe" and change.strategy_id:
            self._schedule_probe_updates(change.strategy_id)
            return
        if change.event == "status":
            self._ui(lambda: self._handle_status_change(change.strategy_id))
            return
        self._ui(self._refresh_list)

    def _refresh_list(self) -> None:
        self._populate_list()
        if not self._strategy_list.page:
            return
        try:
            self._strategy_list.update()
            if self._start_btn and self._start_btn.page:
                self._start_btn.update()
            if self._stop_btn and self._stop_btn.page:
                self._stop_btn.update()
            if self._status_text and self._status_text.page:
                self._status_text.update()
            if self._strategy_header and self._strategy_header.page:
                self._strategy_header.update()
            if self._strategy_actions and self._strategy_actions.page:
                self._strategy_actions.update()
        except RuntimeError:
            pass

    def _rebuild_list(self) -> None:
        self._refresh_list()

    def _build_strategy_row(self, strategy: Strategy) -> ft.Control:
        sid = strategy.id
        expanded = sid in self._expanded
        is_running = self._test_phase == "testing" and self._focused_strategy_id == sid

        checkbox = quiet_checkbox(
            value=sid in self._selected,
            label="",
            active_color=T.BUTTON,
            check_color=T.ON_BUTTON,
            hover_color="#00000000",
            splash_radius=0,
            on_change=lambda e, strategy_id=sid: self._on_strategy_toggle(strategy_id, bool(e.control.value)),
        )
        self._checkboxes[sid] = checkbox

        def toggle_select(_: ft.ControlEvent) -> None:
            checked = sid not in self._selected
            checkbox.value = checked
            self._on_strategy_toggle(sid, checked)

        def toggle_expand(_: ft.ControlEvent) -> None:
            if self._tests_running:
                return
            opening = sid not in self._expanded
            if opening:
                self._expanded.add(sid)
            else:
                self._expanded.discard(sid)
            self._animate_expand(sid, opening)

        chevron = ft.Icon(
            ft.Icons.EXPAND_MORE,
            color=T.TEXT_MUTED,
            size=18,
            animate_rotation=CHEVRON_ANIM,
            rotate=ft.Rotate(math.pi if expanded else 0, alignment=ft.Alignment.CENTER),
        )
        self._chevron_by_id[sid] = chevron

        right_controls: list[ft.Control] = []
        if is_running:
            right_controls.append(factiosi_spinner(size=14))
        right_controls.extend(
            [
                strategy_status_pill(sid),
                ft.Container(content=chevron, padding=4, border_radius=T.RADIUS),
            ]
        )

        select_zone = ft.Container(
            content=ft.Row(
                [
                    checkbox,
                    ui_text(strategy.display_name, expand=True),
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            expand=4,
            padding=ft.Padding.only(left=8, top=10, bottom=10, right=0),
            on_click=bind_select_dismiss(toggle_select),
        )
        expand_zone = ft.Container(
            content=ft.Row(
                right_controls,
                spacing=8,
                alignment=ft.MainAxisAlignment.END,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            expand=6,
            padding=ft.Padding.only(left=0, top=10, bottom=10, right=8),
            on_click=bind_select_dismiss(toggle_expand),
        )

        header = ft.Container(
            content=ft.Row(
                [
                    select_zone,
                    ft.Container(width=1, height=28, bgcolor=T.BORDER),
                    expand_zone,
                ],
                spacing=0,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            border_radius=T.RADIUS,
        )

        body = ft.Container(
            content=self._probe_content_for(sid) if expanded else None,
            height=None if expanded else 0,
            opacity=1 if expanded else 0,
            padding=_probe_body_padding(expanded=expanded),
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
            animate=EXPAND_ANIM,
            animate_opacity=EXPAND_ANIM,
        )
        self._probe_body_by_id[sid] = body

        return ft.Container(
            content=ft.Column(
                [header, body],
                spacing=0,
                tight=True,
            ),
            bgcolor=T.SURFACE,
            border=ft.Border.all(1, T.BORDER),
            border_radius=T.RADIUS,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
        )

    def build(self) -> ft.Control:
        settings = get_settings()
        version = settings.active_version
        self._strategies = list_strategies(settings)
        self._strategies_by_id = {s.id: s for s in self._strategies}
        self._selected.clear()

        tr.subscribe(self._on_results_change)
        self._results_unsubscribe = lambda: tr.unsubscribe(self._on_results_change)

        test_type_group = ft.RadioGroup(
            value=self._test_type,
            content=ft.Column(
                [
                    ft.Radio(
                        label="Стандартный тест (HTTP / Ping)",
                        value="standard",
                        label_style=ft.TextStyle(font_family=T.FONT_FAMILY, color=T.TEXT),
                    ),
                    ft.Radio(
                        label="Проверка DPI (TCP 16–20 freeze)",
                        value="dpi",
                        label_style=ft.TextStyle(font_family=T.FONT_FAMILY, color=T.TEXT),
                    ),
                ],
                spacing=4,
                tight=True,
            ),
            on_change=self._on_test_type_change,
        )

        self._master_checkbox = quiet_checkbox(
            label="Все стратегии",
            value=False,
            active_color=T.BUTTON,
            check_color=T.ON_BUTTON,
            hover_color="#00000000",
            splash_radius=0,
            label_style=ft.TextStyle(font_family=T.FONT_FAMILY, color=T.TEXT),
            on_change=self._on_master_toggle,
        )

        self._start_btn = pill_button(
            "Запуск тестов",
            primary=True,
            on_click=self._start_tests,
            disabled=not self._strategies or not version,
        )
        self._stop_btn = pill_button(
            "Остановка тестов",
            on_click=self._stop_tests,
            disabled=True,
        )
        self._status_text = ui_text("", size=T.FONT_CAPTION, color=T.TEXT_MUTED)

        self._strategy_actions = ft.Row(
            [self._start_btn, self._stop_btn],
            spacing=8,
            wrap=True,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        self._strategy_header = ft.Row(
            [self._master_checkbox],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        self._strategy_list_panel = ft.Column(
            [self._strategy_header, self._strategy_list],
            spacing=4,
            tight=True,
        )

        if not version:
            self._strategy_list.controls = [
                ui_text("Сначала установите версию flowseal", color=T.TEXT_MUTED),
            ]
        else:
            self._populate_list()

        self._polling = True
        self.page.run_task(self._poll_test_state)
        return scroll_page(
            block_section("Тип тестирования", test_type_group),
            block_section(
                "Стратегии к тестированию",
                self._strategy_actions,
                self._status_text,
                ft.Divider(height=1, color=T.BORDER),
                self._strategy_list_panel,
            ),
            page=self.page,
        )

    def _on_test_type_change(self, e: ft.ControlEvent) -> None:
        if e.control.value:
            self._test_type = str(e.control.value)

    def _on_master_toggle(self, e: ft.ControlEvent) -> None:
        if e.control.value:
            self._selected = {s.id for s in self._strategies}
        else:
            self._selected.clear()
        for sid, checkbox in self._checkboxes.items():
            checkbox.value = sid in self._selected
        self._update_buttons()
        self.page.update()

    def _on_strategy_toggle(self, strategy_id: str, checked: bool) -> None:
        if checked:
            self._selected.add(strategy_id)
        else:
            self._selected.discard(strategy_id)
        if self._master_checkbox:
            self._master_checkbox.value = bool(self._strategies) and len(self._selected) == len(self._strategies)
        self._update_buttons()
        self.page.update()

    def _update_buttons(self) -> None:
        running = self._tests_running
        if self._start_btn:
            set_pill_disabled(self._start_btn, running or not self._selected)
        if self._stop_btn:
            set_pill_disabled(self._stop_btn, not running)

    def _snack(self, message: str, *, error: bool = False) -> None:
        if self._status_text:
            self._status_text.value = message
            self._status_text.color = T.STATUS_ERROR if error else T.TEXT_MUTED
        show_toast(self.page, message, kind="error" if error else "info")

    def _choose_strategy(self, strategy_id: str) -> None:
        if self._tests_running or not tr.is_tested(strategy_id):
            return
        settings = get_settings()
        if settings.selected_strategy == strategy_id:
            self._snack("Стратегия уже выбрана")
            return
        settings.selected_strategy = strategy_id
        save_settings(settings)
        self._refresh_strategy_action_buttons()
        self._snack("Стратегия применена, но не запущена")

    def _choose_and_start(self, strategy_id: str) -> None:
        if self._tests_running or not tr.is_tested(strategy_id):
            return
        settings = get_settings()
        if settings.selected_strategy != strategy_id:
            settings.selected_strategy = strategy_id
            save_settings(settings)
            self._refresh_strategy_action_buttons()

        def work() -> tuple[bool, str]:
            status = get_effective_runtime_status()
            if status.running:
                stopped, message = daemon_stop()
                if not stopped:
                    return False, message
                return daemon_start(strategy_id)
            return daemon_start(strategy_id)

        def runner() -> None:
            try:
                result = work()
            except Exception as exc:  # noqa: BLE001
                result = (False, str(exc))

            def finish() -> None:
                ok, msg = result
                if ok:
                    self._snack("Стратегия применена, winws запущен")
                else:
                    self._snack(msg or "Не удалось запустить winws", error=True)

            self._ui(finish)

        threading.Thread(
            target=runner,
            daemon=True,
            name="tigo-select-and-start",
        ).start()

    def _start_tests(self, _: ft.ControlEvent) -> None:
        settings = get_settings()
        if not settings.active_version or not self._selected:
            return
        self._seen_daemon_completed.clear()
        self._session_completed.clear()
        self._session_planned = set(self._selected)
        self._session_active = True
        self._last_daemon_current = None
        self._update_buttons()

        def work() -> None:
            ok, msg = daemon_test_start(
                settings.active_version or "",
                self._test_type,
                sorted(self._selected),
            )

            def finish() -> None:
                self._tests_running = ok
                if not ok:
                    self._session_active = False
                    self._session_planned.clear()
                self._update_buttons()
                if self._status_text:
                    self._status_text.value = msg if ok else f"Ошибка: {msg}"
                    self._status_text.color = T.TEXT_MUTED if ok else T.STATUS_ERROR
                if not ok:
                    self._snack(msg, error=True)
                else:
                    self.page.update()

            self._ui(finish)

        threading.Thread(target=work, daemon=True, name="tigo-test-start").start()

    def _stop_tests(self, _: ft.ControlEvent) -> None:
        def work() -> None:
            ok, msg = daemon_test_stop()

            def finish() -> None:
                if self._status_text:
                    self._status_text.value = msg
                    self._status_text.color = T.TEXT_MUTED if ok else T.STATUS_ERROR
                if not ok:
                    self._snack(msg, error=True)
                else:
                    self.page.update()

            self._ui(finish)

        threading.Thread(target=work, daemon=True, name="tigo-test-stop").start()

    async def _poll_test_state(self) -> None:
        while self._polling:
            state = await asyncio.to_thread(daemon_test_status)
            if state.get("ok"):
                running = bool(state.get("running"))
                phase = str(state.get("phase") or ("testing" if running else "idle"))
                if phase not in {"idle", "testing", "pause"}:
                    phase = "testing" if running else "idle"
                current_raw = state.get("current_strategy_id")
                current = str(current_raw) if current_raw else None
                running_changed = self._tests_running != running
                layout_changed = (
                    current != self._focused_strategy_id
                    or phase != self._test_phase
                    or running_changed
                )
                self._tests_running = running
                if running:
                    self._session_active = True
                planned_raw = state.get("planned_strategy_ids")
                if isinstance(planned_raw, list):
                    daemon_planned = {
                        str(value) for value in planned_raw if isinstance(value, str) and value
                    }
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
                        tr.apply_remote_probe_snapshot(
                            probe_sid,
                            probe_rows,
                            version=version,
                        )

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
                message_changed = (
                    message != self._last_daemon_message or success != self._last_daemon_success
                )
                if running_changed:
                    self._update_buttons()
                if self._status_text:
                    if message and message_changed:
                        self._status_text.value = message
                        self._status_text.color = (
                            T.TEXT_MUTED if success else T.STATUS_ERROR
                        )
                self._last_daemon_message = message
                self._last_daemon_success = success
                if layout_changed:
                    self._refresh_list()
                elif (running_changed or message_changed) and self._start_btn and self._start_btn.page:
                    try:
                        self.page.update()
                    except RuntimeError:
                        pass
            await asyncio.sleep(0.5)
