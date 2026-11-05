"""Background strategy test runner — start→verify→stop loop."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Literal

from src.core.debug_log import debug
from src.core.settings import (
    GameFilterMode,
    IpsetFilterMode,
    StrategySource,
    get_settings,
)
from src.kernel import runtime_state
from src.kernel.public import (
    get_runtime_status,
    start_custom_strategy,
    start_strategy,
    stop_strategy,
)
from src.kernel.winws_runner import get_runner
from src.modules.filters.game_filter import apply_game_filter, get_game_filter_ports, read_game_filter_mode
from src.modules.filters.ipset_filter import apply_ipset_mode
from src.modules.strategies.launcher import build_winws_launch, ensure_runtime_preflight
from src.modules.strategies.repository import list_strategies
from src.modules.strategy_testing import journal as tls
from src.modules.strategy_testing import results as tr
from src.modules.strategy_testing.dpi_probe import format_dpi_lines, probe_dpi_with_callback
from src.modules.strategy_testing.probe import format_probe_lines, probe_all_targets_with_callback, score_results


_STATUS_LABELS = {
    "unknown": "Неизвестная работоспособность",
    "failed": "Не работает",
    "partial": "Частично работает",
    "full": "Полностью работает",
}
INTER_STRATEGY_PAUSE_SECONDS = 2.0
TestPhase = Literal["idle", "testing", "pause"]


@dataclass
class _FilterSnapshot:
    version: str
    game_filter: GameFilterMode
    ipset_filter: IpsetFilterMode
    was_running: bool
    selected_strategy: str | None
    strategy_source: StrategySource
    custom_strategy_args: str


def _score_to_status(passed: int, total: int) -> str:
    if total <= 0:
        return "unknown"
    ratio = passed / total
    if ratio >= 1.0:
        return "full"
    if ratio >= 0.5:
        return "partial"
    return "failed"


def _capture_filter_snapshot(version: str) -> _FilterSnapshot:
    settings = get_settings()
    return _FilterSnapshot(
        version=version,
        game_filter=settings.game_filter,
        ipset_filter=settings.ipset_filter,
        was_running=get_runtime_status().running,
        selected_strategy=settings.selected_strategy,
        strategy_source=settings.strategy_source,
        custom_strategy_args=settings.custom_strategy_args,
    )


def _restore_filter_snapshot(snapshot: _FilterSnapshot) -> None:
    apply_game_filter(snapshot.version, snapshot.game_filter)
    apply_ipset_mode(snapshot.version, snapshot.ipset_filter)
    if not snapshot.was_running:
        return
    if snapshot.strategy_source == "custom":
        if snapshot.custom_strategy_args.strip():
            start_custom_strategy(snapshot.custom_strategy_args)
        return
    if not snapshot.selected_strategy:
        return
    for strategy in list_strategies():
        if strategy.id == snapshot.selected_strategy:
            start_strategy(strategy)
            break


class StrategyTestJob:
    def __init__(self, version: str, test_type: str, strategy_ids: list[str]) -> None:
        self.version = version
        self.test_type = test_type
        self.strategy_ids = strategy_ids


class StrategyTestRunner:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop_requested = False
        self._completed_lock = threading.Lock()
        self._completed_strategy_ids: list[str] = []
        self._planned_strategy_ids: list[str] = []
        self._phase: TestPhase = "idle"
        self._active_strategy_id: str | None = None
        self._version: str | None = None
        self._filter_snapshot: _FilterSnapshot | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def stop(self) -> None:
        self._stop_requested = True
        get_runner().stop()
        tls.append("Остановка тестов…", level=tls.TestLogLevel.WARN)
        debug("strategy_testing", "stop requested")

    @property
    def completed_strategy_ids(self) -> list[str]:
        with self._completed_lock:
            return list(self._completed_strategy_ids)

    @property
    def planned_strategy_ids(self) -> list[str]:
        with self._completed_lock:
            return list(self._planned_strategy_ids)

    @property
    def phase(self) -> TestPhase:
        return self._phase

    @property
    def active_strategy_id(self) -> str | None:
        return self._active_strategy_id

    @property
    def version(self) -> str | None:
        return self._version

    def _mark_completed(self, strategy_id: str) -> None:
        with self._completed_lock:
            if strategy_id not in self._completed_strategy_ids:
                self._completed_strategy_ids.append(strategy_id)

    def start(self, job: StrategyTestJob, on_done=None) -> tuple[bool, str]:
        if self.running:
            return False, "Тесты уже выполняются."
        if not job.strategy_ids:
            return False, "Не выбрано ни одной стратегии."
        if job.test_type not in {"standard", "dpi"}:
            return False, f"Неизвестный тип теста: {job.test_type}."

        from src.modules.strategy_testing.curl import curl_available

        ok, message = curl_available()
        if not ok:
            return False, message

        self._stop_requested = False
        self._phase = "idle"
        self._active_strategy_id = None
        self._version = job.version
        self._filter_snapshot = None
        with self._completed_lock:
            self._completed_strategy_ids.clear()
            self._planned_strategy_ids = list(job.strategy_ids)
        debug("strategy_testing", f"starting tests: {job.strategy_ids}")

        def runner() -> None:
            try:
                ok, message = self._run_job(job)
                if on_done:
                    on_done(ok, message)
            except Exception as exc:  # noqa: BLE001
                tls.append(str(exc), level=tls.TestLogLevel.ERROR)
                debug("strategy_testing", str(exc), level="error")
                if on_done:
                    on_done(False, str(exc))
            finally:
                snapshot = self._filter_snapshot
                self._filter_snapshot = None
                if snapshot is not None:
                    try:
                        _restore_filter_snapshot(snapshot)
                    except Exception as exc:  # noqa: BLE001
                        debug("strategy_testing", f"filter restore failed: {exc}", level="error")
                runtime_state.set_tests_running(False)
                stop_strategy(cleanup_windivert=False)
                self._phase = "idle"
                self._active_strategy_id = None
                self._thread = None

        self._thread = threading.Thread(target=runner, daemon=True)
        self._thread.start()
        return True, "Тесты запущены."

    def _probe_strategy(
        self,
        *,
        strategy,
        job: StrategyTestJob,
        runner,
        index: int,
        total: int,
    ) -> None:
        tls.append("> Проверка целей…", level=tls.TestLogLevel.INFO)
        tr.set_probe_loading(strategy.id, version=job.version, test_type=job.test_type)

        def on_target(result) -> None:
            tr.apply_probe_result(strategy.id, result, version=job.version)

        if job.test_type == "dpi":
            results = probe_dpi_with_callback(on_target)
            format_lines = format_dpi_lines
        else:
            results = probe_all_targets_with_callback(on_target)
            format_lines = format_probe_lines

        for line in format_lines(results):
            tls.append_from_console(line)

        passed, score_total = score_results(results)
        status = _score_to_status(passed, score_total) if score_total else "unknown"
        detail = ""
        if status == "unknown":
            detail = "Нет данных для оценки (0 целей)."
        tr.set_result(
            strategy.id,
            version=job.version,
            state=status,  # type: ignore[arg-type]
            rows=results,
            score=(passed, score_total),
            detail=detail,
        )
        self._mark_completed(strategy.id)
        tls.append(
            f"{strategy.display_name}: {_STATUS_LABELS[status]} ({passed}/{score_total})",
            level=tls.TestLogLevel.OK if status == "full" else tls.TestLogLevel.INFO,
        )
        debug("strategy_testing", f"{strategy.display_name}: {status} ({passed}/{score_total})")
        runner.stop()
        self._phase = "pause"
        time.sleep(INTER_STRATEGY_PAUSE_SECONDS)

    def _run_job(self, job: StrategyTestJob) -> tuple[bool, str]:
        strategies = {s.id: s for s in list_strategies()}
        selected = [strategies[sid] for sid in job.strategy_ids if sid in strategies]
        if not selected:
            tls.append("Выбранные стратегии не найдены.", level=tls.TestLogLevel.ERROR)
            return False, "Выбранные стратегии не найдены."

        ok, message = ensure_runtime_preflight(version=job.version)
        if not ok:
            tls.append(message, level=tls.TestLogLevel.ERROR)
            return False, message

        self._filter_snapshot = _capture_filter_snapshot(job.version)
        runtime_state.set_tests_running(True)
        stop_strategy(cleanup_windivert=False)
        tr.begin_test_run(version=job.version)
        tls.clear()
        label = "DPI" if job.test_type == "dpi" else "стандартный"
        tls.append(f"Запуск тестов ({label})…", level=tls.TestLogLevel.INFO)
        gf_mode = read_game_filter_mode(job.version)
        gf_tcp, gf_udp = get_game_filter_ports(gf_mode)
        gf_label = {
            "off": "выключен",
            "all": "включён (TCP+UDP)",
            "tcp": "включён (TCP)",
            "udp": "включён (UDP)",
        }.get(gf_mode, gf_mode)
        tls.append(
            f"Game filter: {gf_label} (wf: {gf_tcp}/{gf_udp})",
            level=tls.TestLogLevel.INFO,
        )
        tls.append(
            f"Стратегии: {', '.join(s.display_name for s in selected)} · версия {job.version}",
            level=tls.TestLogLevel.INFO,
        )

        runner = get_runner()

        for index, strategy in enumerate(selected, start=1):
            if self._stop_requested:
                break

            debug("strategy_testing", f"testing [{index}/{len(selected)}] {strategy.display_name}")
            self._phase = "testing"
            self._active_strategy_id = strategy.id
            tr.set_running(strategy.id, version=job.version, test_type=job.test_type)
            tls.append(
                f"--- [{index}/{len(selected)}] {strategy.display_name} ---",
                level=tls.TestLogLevel.INFO,
            )
            tls.append("> Запуск стратегии…", level=tls.TestLogLevel.INFO)

            spec, error = build_winws_launch(strategy, version=job.version, tls_watch=False)
            if error or spec is None:
                msg = error or "Ошибка сборки команды."
                tls.append(msg, level=tls.TestLogLevel.ERROR)
                tr.set_result(
                    strategy.id,
                    version=job.version,
                    state="failed",
                    rows=[],
                    score=None,
                    detail=msg,
                )
                self._mark_completed(strategy.id)
                self._phase = "pause"
                time.sleep(INTER_STRATEGY_PAUSE_SECONDS)
                continue

            started, start_msg = runner.start(spec, wait_seconds=5.0)
            if not started:
                tls.append(start_msg, level=tls.TestLogLevel.ERROR)
                tr.set_result(
                    strategy.id,
                    version=job.version,
                    state="failed",
                    rows=[],
                    score=None,
                    detail=start_msg,
                )
                self._mark_completed(strategy.id)
                self._phase = "pause"
                time.sleep(INTER_STRATEGY_PAUSE_SECONDS)
                continue

            self._probe_strategy(
                strategy=strategy,
                job=job,
                runner=runner,
                index=index,
                total=len(selected),
            )

        if not self._stop_requested:
            tls.append("Все тесты завершены.", level=tls.TestLogLevel.OK)
            return True, "Тестирование завершено."
        return True, "Тестирование остановлено."
