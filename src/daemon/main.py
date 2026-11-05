"""2Wings background daemon entry."""

from __future__ import annotations

from dataclasses import asdict, fields
import signal
import sys
import threading
import time

from src.core.debug_log import info, warn
from src.core.automation import automation_enabled
from src.core.paths import APP_NAME, debug_log_path, ensure_layout, is_packaged_app
from src.core.settings import AppSettings, get_settings, reload_settings, save_settings
from src.kernel import runtime_state
from src.daemon.ipc import IpcServer, build_status_response
from src.daemon.protocol import CommandName
from src.daemon.tray import TrayController
from src.daemon.ui_launcher import close_all_gui, launch_gui, register_gui_pid
from src.kernel.process_monitor import start_monitor, stop_monitor
from src.kernel.public import get_runtime_status, initialize_runtime, start_custom_strategy, start_strategy, stop_strategy
from src.modules.lifecycle.public import launch_last_strategy_if_configured
from src.modules.tls_exclude.watcher import start_watcher as start_tls_exclude_watcher
from src.modules.strategies.repository import bootstrap_user_lists, list_strategies
from src.modules.updates.service import ensure_runtime_installed, run_startup_updates
from src.modules.strategy_testing import results as test_results
from src.modules.strategy_testing.results import load_cache
from src.modules.strategy_testing.runner import StrategyTestJob, StrategyTestRunner


class TwoWingsDaemon:
    def __init__(self) -> None:
        self._shutdown = threading.Event()
        self._tray: TrayController | None = None
        self._ipc = IpcServer(self._handle_command)
        self._bootstrap_done = threading.Event()
        self._operation_lock = threading.RLock()
        self._test_runner = StrategyTestRunner()
        self._test_message = ""
        self._test_ok = True

    def run(self) -> None:
        info("daemon", f"starting {APP_NAME} daemon")
        get_settings()
        start_tls_exclude_watcher()
        self._ipc.start()
        from src.core.process_label import set_process_description

        if set_process_description("2Wings daemon"):
            info("daemon", "process description: 2Wings daemon")
        else:
            warn("daemon", "failed to set process description")
        info("daemon", "IPC ready")
        threading.Thread(
            target=self._start_tg_proxy,
            daemon=True,
            name="twowings-tg-ws-proxy-boot",
        ).start()

        self._tray = TrayController(
            on_start=self._tray_start,
            on_stop=self._tray_stop,
            on_shutdown=self._request_shutdown_from_tray,
            status_provider=self._tray_status,
        )
        tray_thread = threading.Thread(target=self._tray.start, daemon=True, name="twowings-tray")
        tray_thread.start()

        threading.Thread(target=self._bootstrap_runtime, daemon=True, name="twowings-daemon-bootstrap").start()

        def handle_signal(_signum, _frame) -> None:
            self._request_shutdown(stop_icon=True)

        signal.signal(signal.SIGINT, handle_signal)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, handle_signal)

        while not self._shutdown.is_set():
            time.sleep(0.5)
        stop_monitor()
        self._ipc.stop()
        info("daemon", "daemon stopped")

    def _start_tg_proxy(self) -> None:
        try:
            from src.modules.tg_ws_proxy.service import ensure_running

            ensure_running()
        except Exception as exc:  # noqa: BLE001
            warn("tg-ws-proxy", f"не запустился: {exc}")

    def _stop_tg_proxy(self) -> None:
        try:
            from src.modules.tg_ws_proxy.service import stop

            stop()
        except Exception as exc:  # noqa: BLE001
            warn("tg-ws-proxy", f"не остановился: {exc}")

    def _bootstrap_runtime(self) -> None:
        try:
            ensure_layout()
            bootstrap_user_lists()
            load_cache()
            initialize_runtime()
            start_monitor()
            run_startup_updates(
                on_message=lambda msg, error=False: warn("updates", msg) if error else info("updates", msg)
            )
            threading.Thread(target=self._clean_retired_dns, daemon=True, name="twowings-dns-cleanup").start()
            if get_settings().auto_check_updates_on_startup:
                threading.Thread(
                    target=self._refresh_hosts_catalog, daemon=True, name="twowings-hosts-catalog"
                ).start()
            runtime_result = ensure_runtime_installed(allow_update=get_settings().auto_promote_updates)
            if runtime_result.ok:
                launch_last_strategy_if_configured(from_daemon=True)
            else:
                warn("updates", runtime_result.message)
            info("daemon", "runtime bootstrap complete")
        except Exception as exc:  # noqa: BLE001
            warn("daemon", f"runtime bootstrap failed: {exc}")
            runtime_state.mark_failed(f"Инициализация daemon завершилась ошибкой: {exc}")
        finally:
            self._bootstrap_done.set()

    @staticmethod
    def _clean_retired_dns() -> None:
        from src.modules.dns.cleanup import clean_retired_dns
        from src.core.paths import remove_legacy_updater
        from src.modules.lifecycle.public import sync_autostart_task

        try:
            remove_legacy_updater()
            sync_autostart_task()
            clean_retired_dns()
        except Exception as exc:  # noqa: BLE001 - must not take the daemon's startup with it
            warn("dns", f"не удалось убрать прежний DNS: {exc}")

    @staticmethod
    def _refresh_hosts_catalog() -> None:
        from src.modules.hosts.service import refresh_catalog_and_services

        ok, message = refresh_catalog_and_services()
        if message:
            (info if ok else warn)("hosts", message)

    def _tray_status(self) -> tuple[bool, bool]:
        from src.kernel.process_probe import is_canonical_winws_running

        status = get_runtime_status()
        busy = status.tests_running or status.phase.value in {"starting", "stopping"}
        probed, _pid = is_canonical_winws_running()
        running = status.running or probed
        return running, busy

    def _tray_start(self, request: dict | None = None) -> tuple[bool, str]:
        if not self._bootstrap_done.is_set():
            warn("daemon", "runtime still initializing")
            return False, "2Wings ещё инициализируется. Повторите через несколько секунд."
        with self._operation_lock:
            if self._test_runner.running:
                return False, "Сначала остановите тестирование стратегий."
            reload_settings()
            payload = request or {}
            explicit_id = payload.get("strategy_id")
            if isinstance(explicit_id, str) and explicit_id.strip():
                for strategy in list_strategies():
                    if strategy.id == explicit_id.strip():
                        return start_strategy(strategy)
                return False, "Выбранная стратегия не найдена."
            settings = get_settings()
            if settings.strategy_source == "custom":
                if settings.custom_strategy_args.strip():
                    return start_custom_strategy(settings.custom_strategy_args)
                return False, "Параметры собственной стратегии не заданы."
            if settings.selected_strategy:
                for strategy in list_strategies():
                    if strategy.id == settings.selected_strategy:
                        return start_strategy(strategy)
                return False, "Выбранная стратегия не найдена."
            return False, "Стратегия не выбрана."

    def _tray_stop(self) -> tuple[bool, str]:
        with self._operation_lock:
            if self._test_runner.running:
                return False, "Сначала остановите тестирование стратегий."
            return stop_strategy()

    def _test_done(self, ok: bool, message: str) -> None:
        self._test_ok = ok
        self._test_message = message

    def _start_tests(self, request: dict) -> tuple[bool, str]:
        if not self._bootstrap_done.is_set():
            return False, "2Wings ещё инициализируется. Повторите через несколько секунд."
        version = str(request.get("version") or "").strip()
        test_type = str(request.get("test_type") or "standard").strip()
        raw_ids = request.get("strategy_ids")
        if not isinstance(raw_ids, list) or len(raw_ids) > 500:
            return False, "Некорректный список стратегий."
        strategy_ids = [str(value) for value in raw_ids if isinstance(value, str) and value]
        with self._operation_lock:
            if self._test_runner.running:
                return False, "Тесты уже выполняются."
            stop_strategy(cleanup_windivert=False)
            self._test_ok = True
            self._test_message = "Тесты запущены."
            return self._test_runner.start(
                StrategyTestJob(version, test_type, strategy_ids),
                on_done=self._test_done,
            )

    def _stop_tests(self) -> tuple[bool, str]:
        with self._operation_lock:
            if not self._test_runner.running:
                return True, "Тесты уже остановлены."
            self._test_runner.stop()
            self._test_message = "Остановка тестов…"
            return True, self._test_message

    @staticmethod
    def _automation_denied() -> dict:
        return {
            "ok": False,
            "error": (
                "Automation API отключён. Для compiled daemon задайте "
                "TWOWINGS_AUTOMATION=1 до запуска."
            ),
        }

    def _automation_get_settings(self) -> dict:
        if not automation_enabled():
            return self._automation_denied()
        return {"ok": True, "settings": asdict(get_settings())}

    def _automation_update_settings(self, request: dict) -> dict:
        if not automation_enabled():
            return self._automation_denied()
        values = request.get("values")
        if not isinstance(values, dict):
            return {"ok": False, "error": "Поле values должно быть JSON-объектом."}
        known = {item.name for item in fields(AppSettings)}
        forbidden = {"storage_root"}
        choices = {
            "game_filter": {"off", "all", "tcp", "udp"},
            "ipset_filter": {"loaded", "none", "any"},
            "version_retention": {"all", "latest_only", "keep_previous"},
            "theme_mode": {"auto", "dark", "light"},
            "strategy_source": {"flowseal", "custom"},
            "close_action": {"exit", "minimize_tray"},
        }
        settings = get_settings()
        for key, value in values.items():
            if key not in known or key in forbidden:
                return {"ok": False, "error": f"Настройка недоступна для automation: {key}"}
            current = getattr(settings, key)
            if isinstance(current, bool) and not isinstance(value, bool):
                return {"ok": False, "error": f"{key}: ожидается boolean."}
            if isinstance(current, int) and not isinstance(current, bool):
                if not isinstance(value, int) or isinstance(value, bool):
                    return {"ok": False, "error": f"{key}: ожидается integer."}
            elif current is not None and not isinstance(current, (bool, int)):
                if not isinstance(value, type(current)):
                    return {"ok": False, "error": f"{key}: неверный тип значения."}
            elif current is None and value is not None and not isinstance(value, str):
                return {"ok": False, "error": f"{key}: ожидается string или null."}
            if key in choices and value not in choices[key]:
                return {"ok": False, "error": f"{key}: недопустимое значение {value!r}."}
            if key == "keep_version_count" and not 1 <= int(value) <= 20:
                return {"ok": False, "error": "keep_version_count должен быть от 1 до 20."}
            setattr(settings, key, value)
        save_settings(settings)
        return {"ok": True, "settings": asdict(settings)}

    def _automation_read_log(self, request: dict) -> dict:
        if not automation_enabled():
            return self._automation_denied()
        raw_limit = request.get("limit", 100)
        limit = max(1, min(int(raw_limit) if isinstance(raw_limit, int) else 100, 500))
        path = debug_log_path()
        if not path.exists():
            return {"ok": True, "lines": []}
        try:
            with path.open("rb") as handle:
                handle.seek(0, 2)
                size = handle.tell()
                handle.seek(max(0, size - 512 * 1024))
                text = handle.read().decode("utf-8", errors="replace")
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "lines": text.splitlines()[-limit:]}

    def _automation_list_strategies(self) -> dict:
        if not automation_enabled():
            return self._automation_denied()
        settings = get_settings()
        return {
            "ok": True,
            "active_version": settings.active_version,
            "selected_strategy": settings.selected_strategy,
            "strategies": [
                {
                    "id": strategy.id,
                    "name": strategy.name,
                    "display_name": strategy.display_name,
                }
                for strategy in list_strategies(settings)
            ],
        }

    def _automation_update_strategies(self) -> dict:
        if not automation_enabled():
            return self._automation_denied()
        with self._operation_lock:
            if self._test_runner.running:
                return {"ok": False, "error": "Сначала остановите тестирование стратегий."}
            was_running = get_runtime_status().running
            if was_running:
                stop_strategy(cleanup_windivert=False)
            from src.modules.updates.service import check_and_apply

            result = check_and_apply(restart_running=False)
            restart_ok, restart_message = True, ""
            if was_running:
                restart_ok, restart_message = self._tray_start()
            ok = result.ok and restart_ok
            payload = {
                "ok": ok,
                "message": result.message,
                "version_changed": result.version_changed,
                "applied_tag": result.applied_tag,
            }
            if not restart_ok:
                payload["error"] = f"Обновление завершено, но restart не удался: {restart_message}"
            elif not result.ok:
                payload["error"] = result.message
            return payload

    def _request_shutdown_from_tray(self, icon) -> None:
        self._request_shutdown(stop_icon=False)
        icon.stop()

    def _request_shutdown(self, *, stop_icon: bool) -> None:
        if self._shutdown.is_set():
            return
        if self._test_runner.running:
            self._test_runner.stop()
        with self._operation_lock:
            stop_strategy()
        self._stop_tg_proxy()
        close_all_gui()
        self._shutdown.set()
        if stop_icon and self._tray:
            self._tray.stop()

    def _handle_command(self, cmd: CommandName, request: dict) -> dict:
        if cmd == "ping":
            return {"ok": True, "message": "pong"}
        if cmd == "register_gui":
            pid = request.get("pid")
            if isinstance(pid, int):
                register_gui_pid(pid)
            else:
                register_gui_pid()
            return {"ok": True}
        if cmd == "status":
            return build_status_response()
        if cmd == "start":
            ok, message = self._tray_start(request)
            return {"ok": ok, "message": message} if ok else {"ok": False, "error": message}
        if cmd == "stop":
            ok, message = self._tray_stop()
            return {"ok": ok, "message": message}
        if cmd == "test_start":
            ok, message = self._start_tests(request)
            return {"ok": ok, "message": message} if ok else {"ok": False, "error": message}
        if cmd == "test_stop":
            ok, message = self._stop_tests()
            return {"ok": ok, "message": message}
        if cmd == "test_status":
            active_strategy_id = self._test_runner.active_strategy_id
            version = self._test_runner.version
            return {
                "ok": True,
                "running": self._test_runner.running,
                "phase": self._test_runner.phase,
                "current_strategy_id": active_strategy_id,
                "completed_strategy_ids": self._test_runner.completed_strategy_ids,
                "planned_strategy_ids": self._test_runner.planned_strategy_ids,
                "version": version,
                "probe": (
                    {
                        "strategy_id": active_strategy_id,
                        "rows": test_results.probe_snapshot(
                            active_strategy_id,
                            version=version,
                        ),
                    }
                    if active_strategy_id
                    else None
                ),
                "message": self._test_message,
                "success": self._test_ok,
            }
        if cmd == "automation_info":
            return {
                "ok": True,
                "enabled": automation_enabled(),
                "packaged": is_packaged_app(),
            }
        if cmd == "automation_get_settings":
            return self._automation_get_settings()
        if cmd == "automation_update_settings":
            return self._automation_update_settings(request)
        if cmd == "automation_list_strategies":
            return self._automation_list_strategies()
        if cmd == "automation_read_log":
            return self._automation_read_log(request)
        if cmd == "automation_update_strategies":
            return self._automation_update_strategies()
        if cmd == "open_ui":
            ok, message = launch_gui()
            return {"ok": ok, "message": message}
        if cmd == "tg_proxy_status":
            from src.modules.tg_ws_proxy.service import status

            return status()
        if cmd == "tg_proxy_apply":
            from src.modules.tg_ws_proxy.service import apply_settings

            return apply_settings()
        return {"ok": False, "error": f"unknown command: {cmd}"}


def run_daemon() -> None:
    TwoWingsDaemon().run()


if __name__ == "__main__":
    run_daemon()
    sys.exit(0)
