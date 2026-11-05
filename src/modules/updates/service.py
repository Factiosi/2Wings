"""Flowseal update orchestration — shared by settings, startup and daemon."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from typing import Callable

from src.core.events import emit
from src.core.debug_log import debug, info as log_info
from src.core.paths import runtime_installed, staging_dir
from src.core.settings import get_settings
from src.kernel.process_probe import is_canonical_winws_running
from src.kernel.public import get_effective_runtime_status
from src.modules.filters.game_filter import ensure_game_filter_synced
from src.modules.filters.ipset_filter import keep_ipset_mode
from src.modules.strategies.repository import (
    apply_version_retention,
    has_flowseal_strategies,
    set_active_version,
    write_version_meta,
)
from src.modules.updates.github import (
    check_for_update,
    download_release_to_staging,
    fetch_latest_release_asset_url,
)
from src.modules.updates.engine import engine_update_available, install_engine
from src.modules.updates.transformer import promote_staging

MessageCallback = Callable[[str, bool], None]

MSG_UP_TO_DATE = "У вас последняя актуальная версия стратегий"
MSG_UPDATE_AVAILABLE = "Доступна новая версия стратегий"
MSG_DOWNLOADING = "Новая версия стратегий доступна и скачивается"
MSG_STALE_REMOVED = "Неактуальные версии стратегий удалены"


@dataclass
class ApplyResult:
    ok: bool
    message: str
    toast_kind: str = "info"
    version_changed: bool = False
    applied_tag: str | None = None


def format_check_message(info) -> tuple[bool, str, str]:
    if info.error and not info.update_available:
        return False, info.error, "error"
    if info.update_available:
        return True, MSG_UPDATE_AVAILABLE, "warning"
    return True, MSG_UP_TO_DATE, "success"


def check_only() -> tuple[bool, str, str]:
    settings = get_settings()
    info = check_for_update(settings.active_version)
    return format_check_message(info)


def ensure_runtime_installed(*, allow_update: bool = False) -> ApplyResult:
    """Install the mandatory winws2 engine independently from strategy settings.

    With ``allow_update`` a newer zapret2 release replaces the installed one,
    but only while 2Wings's winws2 is not running (its files are locked then).
    """
    release = None
    if runtime_installed():
        if not allow_update or is_canonical_winws_running()[0]:
            return ApplyResult(True, "Движок winws2 уже установлен.", toast_kind="success")
        release = engine_update_available()
        if release is None:
            return ApplyResult(True, "Движок winws2 актуален.", toast_kind="success")

    try:
        tag = install_engine(release)
    except Exception as exc:  # noqa: BLE001
        debug("updates", f"engine install failed: {exc}", level="error")
        if runtime_installed():
            return ApplyResult(True, f"Не удалось обновить winws2: {exc}", toast_kind="warning")
        return ApplyResult(False, f"Не удалось установить winws2: {exc}", toast_kind="error")
    if not runtime_installed():
        return ApplyResult(False, "Архив zapret2 установлен не полностью.", toast_kind="error")
    log_info("updates", f"installed winws2 engine from zapret2 {tag}")
    return ApplyResult(True, f"Движок winws2 (zapret2 {tag}) установлен.", toast_kind="success", applied_tag=tag)


def check_and_apply(*, restart_running: bool = True) -> ApplyResult:
    settings = get_settings()
    missing_local = not has_flowseal_strategies()
    info = check_for_update(None if missing_local else settings.active_version)
    if info.error and not info.update_available:
        return ApplyResult(False, info.error, toast_kind="error")
    if not info.update_available:
        return ApplyResult(True, MSG_UP_TO_DATE, toast_kind="success")

    tag, url = fetch_latest_release_asset_url()
    if not url or not tag:
        return ApplyResult(False, "Не удалось найти архив релиза на GitHub.", toast_kind="error")

    was_running = restart_running and get_effective_runtime_status().running
    if was_running:
        from src.daemon.ipc import daemon_stop

        stopped, stop_message = daemon_stop()
        if not stopped:
            return ApplyResult(
                False,
                f"Не удалось остановить zapret перед обновлением: {stop_message}",
                toast_kind="error",
            )

    staging = staging_dir()
    try:
        source = download_release_to_staging(url, tag)
        promote_staging(source, tag, skip_list_updates=settings.skip_list_updates)
        write_version_meta(tag)
        previous = settings.active_version
        set_active_version(tag)
        apply_version_retention()
        ensure_game_filter_synced(tag)
        keep_ipset_mode(tag)
        version_changed = previous != tag
        if was_running:
            from src.daemon.ipc import daemon_start

            ok, msg = daemon_start()
            if not ok:
                return ApplyResult(
                    False,
                    f"Версия {tag} установлена, но перезапуск не удался: {msg}",
                    toast_kind="error",
                    version_changed=True,
                    applied_tag=tag,
                )
        log_info("updates", f"applied flowseal version {tag}")
        emit("strategies_changed")
        return ApplyResult(
            True,
            MSG_UP_TO_DATE,
            toast_kind="success",
            version_changed=version_changed,
            applied_tag=tag,
        )
    except Exception as exc:  # noqa: BLE001
        debug("updates", f"apply failed: {exc}", level="error")
        if was_running:
            from src.daemon.ipc import daemon_start

            daemon_start()
        return ApplyResult(False, str(exc), toast_kind="error")
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def run_startup_updates(on_message: MessageCallback | None = None) -> None:
    settings = get_settings()
    if settings.strategy_source != "flowseal":
        return
    if not settings.auto_check_updates_on_startup and not settings.auto_promote_updates:
        return

    info_obj = check_for_update(settings.active_version)
    if settings.auto_check_updates_on_startup and on_message:
        ok, msg, kind = format_check_message(info_obj)
        on_message(msg, error=not ok or kind == "error")

    if settings.auto_promote_updates and (
        info_obj.update_available or not has_flowseal_strategies()
    ):
        result = check_and_apply()
        if on_message:
            on_message(result.message, error=not result.ok)
