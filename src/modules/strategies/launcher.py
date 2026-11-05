"""Build winws launch command from a strategy."""

from __future__ import annotations

import re
from pathlib import Path

from src.core.debug_log import debug, warn
from src.core.paths import (
    bin_dir,
    engine_exe,
    flowseal_fake_bin_dir,
    flowseal_user_lists_dir,
    flowseal_version_lists_dir,
    lua_dir,
    missing_engine_files,
    program_root,
    tls_watch_script,
    winws2_writable_dir,
)
from src.core.settings import get_settings
from src.kernel.launch_spec import WinwsLaunchSpec, tokenize_winws_args
from src.kernel.process_probe import find_foreign_winws_processes
from src.modules.filters.game_filter import ensure_game_filter_synced, get_game_filter_ports
from src.modules.filters.tcp import enable_tcp_timestamps
from src.modules.strategies.models import Strategy
from src.modules.strategies.parser import resolve_strategy_args
from src.modules.strategies.winws2 import ConversionError, inject_tls_watch, to_winws2_argv


def _validate_assets(args: str) -> str | None:
    for match in re.finditer(r'"([^"]+)"', args):
        candidate = Path(match.group(1))
        if candidate.suffix.lower() in {".bin", ".txt"} and not candidate.exists():
            return f"Файл не найден: {candidate}"
    return None


def _engine_preflight() -> str | None:
    missing = missing_engine_files()
    if missing:
        names = ", ".join(path.name for path in missing)
        return f"Движок winws2 установлен не полностью (нет {names}). Перезапустите 2Wings, чтобы скачать zapret2."
    foreign = find_foreign_winws_processes()
    if foreign:
        pid, path = foreign[0]
        return (
            f"Обнаружен другой winws (PID {pid}): {path}. "
            "Остановите другую программу обхода и повторите запуск."
        )
    if not enable_tcp_timestamps():
        return "Не удалось включить TCP timestamps."
    return None


def _winws2_argv(args: str, *, label: str, tls_watch: bool = True) -> tuple[list[str] | None, str | None]:
    try:
        result = to_winws2_argv(tokenize_winws_args(args), lua_dir=lua_dir())
    except ConversionError as exc:
        return None, f"Стратегию «{label}» не удалось перевести на winws2: {exc}"
    for message in result.warnings:
        warn("strategies", f"{label}: {message}")
    argv = result.argv
    script = tls_watch_script()
    if tls_watch and get_settings().tls_auto_exclude and script.exists():
        writable = winws2_writable_dir()
        # winws2 creates only the last level of --writable.
        writable.parent.mkdir(parents=True, exist_ok=True)
        argv = inject_tls_watch(argv, script=script, writable_dir=writable)
    return argv, None


def ensure_runtime_preflight(*, version: str) -> tuple[bool, str]:
    error = _engine_preflight()
    if error:
        return False, error
    ensure_game_filter_synced(version)
    debug("strategies", f"preflight ok for version {version}")
    return True, ""


def build_winws_launch(
    strategy: Strategy, *, version: str | None = None, tls_watch: bool = True
) -> tuple[WinwsLaunchSpec | None, str | None]:
    """``tls_watch=False`` for strategy tests: a strategy under test must not edit the exclude lists."""
    settings = get_settings()
    ver = version or settings.active_version
    if not ver:
        return None, "Не выбрана активная версия flowseal."

    ok, message = ensure_runtime_preflight(version=ver)
    if not ok:
        debug("strategies", message, level="error")
        return None, message

    game_tcp, game_udp = get_game_filter_ports(settings.game_filter)
    args = resolve_strategy_args(
        strategy.args_template,
        bin_dir=flowseal_fake_bin_dir(),
        lists_dir=flowseal_version_lists_dir(ver),
        user_lists_dir=flowseal_user_lists_dir(),
        root_dir=program_root(),
        game_filter_tcp=game_tcp,
        game_filter_udp=game_udp,
    )
    missing = _validate_assets(args)
    if missing:
        debug("strategies", missing, level="error")
        return None, missing
    argv, error = _winws2_argv(args, label=strategy.display_name, tls_watch=tls_watch)
    if argv is None:
        debug("strategies", error or "", level="error")
        return None, error

    spec = WinwsLaunchSpec(
        exe=engine_exe(),
        argv=argv,
        cwd=bin_dir(),
        strategy_name=strategy.display_name,
        strategy_id=strategy.id,
    )
    debug("strategies", f"built launch spec for {strategy.name}: argv={spec.argv}")
    return spec, None


def resolve_custom_args(args: str) -> str:
    """Same placeholders as Flowseal strategies: ``"%LISTS%list-general-user.txt"``.

    %LISTS% points at the user lists for list-*-user.txt / ipset-exclude-user.txt
    and at the active Flowseal version's lists otherwise; absolute paths stay as written.
    """
    settings = get_settings()
    version = settings.active_version
    game_tcp, game_udp = get_game_filter_ports(settings.game_filter)
    return resolve_strategy_args(
        args,
        bin_dir=flowseal_fake_bin_dir(),
        lists_dir=flowseal_version_lists_dir(version) if version else flowseal_user_lists_dir(),
        user_lists_dir=flowseal_user_lists_dir(),
        root_dir=program_root(),
        game_filter_tcp=game_tcp,
        game_filter_udp=game_udp,
    )


def build_custom_launch(args_text: str) -> tuple[WinwsLaunchSpec | None, str | None]:
    settings = get_settings()
    args = (args_text or settings.custom_strategy_args or "").strip()
    if not args:
        return None, "Укажите аргументы своей стратегии."

    error = _engine_preflight()
    if error:
        return None, error
    args = resolve_custom_args(args)
    missing = _validate_assets(args)
    if missing:
        return None, missing
    # winws1 arguments are converted, winws2 ones pass through.
    argv, error = _winws2_argv(args, label="Своя стратегия")
    if argv is None:
        return None, error

    spec = WinwsLaunchSpec(
        exe=engine_exe(),
        argv=argv,
        cwd=bin_dir(),
        strategy_name="custom",
        strategy_id="custom",
    )
    debug("strategies", f"built custom launch spec: argv={spec.argv}")
    return spec, None
