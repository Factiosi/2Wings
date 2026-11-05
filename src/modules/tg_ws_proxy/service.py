"""Запуск TG WS Proxy в процессе демона. Остальные параметры — как в оригинале."""

from __future__ import annotations

import asyncio
import os
import socket
import threading
import time
from typing import Any

from src.core.debug_log import error, info, warn
from src.core.settings import AppSettings, get_settings, reload_settings, save_settings
from src.modules.tg_ws_proxy.options import (
    HOST,
    DEFAULT_PORT,
    dc_lines,
    telegram_link,
    validate_dc_ip,
    validate_port,
)
from src.modules.tg_ws_proxy.proxy.config import parse_dc_ip_list, proxy_config
from src.modules.tg_ws_proxy.proxy.tg_ws_proxy import _run

_lock = threading.RLock()
_thread: threading.Thread | None = None
_async_stop: tuple[asyncio.AbstractEventLoop, asyncio.Event] | None = None
_last_error = ""


def _ensure_secret(settings: AppSettings) -> str:
    secret = (settings.tg_ws_proxy_secret or "").strip()
    if len(secret) == 32:
        try:
            bytes.fromhex(secret)
            return secret
        except ValueError:
            pass
    secret = os.urandom(16).hex()
    settings.tg_ws_proxy_secret = secret
    save_settings(settings)
    return secret


def _apply_upstream(settings: AppSettings, secret: str) -> str | None:
    lines = dc_lines(settings.tg_ws_proxy_dc_ip)
    problem = validate_port(settings.tg_ws_proxy_port) or validate_dc_ip(lines)
    if problem:
        return problem
    proxy_config.port = int(settings.tg_ws_proxy_port)
    proxy_config.host = HOST
    proxy_config.secret = secret
    proxy_config.dc_redirects = parse_dc_ip_list(lines)
    proxy_config.buffer_size = 256 * 1024
    proxy_config.pool_size = 4
    proxy_config.fallback_cfproxy = True
    proxy_config.cfproxy_user_domains = []
    proxy_config.cfproxy_worker_domains = []
    proxy_config.cfproxy_h2_media = True
    proxy_config.disable_secure = False
    proxy_config.fake_tls_domain = ""
    proxy_config.proxy_protocol = False
    proxy_config.force_test_dc = False
    return None


def _listen_error(exc: BaseException) -> str:
    winerror = getattr(exc, "winerror", None)
    if winerror == 10048 or getattr(exc, "errno", None) in {98, 48}:
        return "Этот порт уже занят."
    return "Не удалось запустить TG WS Proxy."


def _run_thread() -> None:
    global _async_stop, _last_error
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    stop_event = asyncio.Event()
    _async_stop = (loop, stop_event)
    try:
        loop.run_until_complete(_run(stop_event=stop_event))
    except Exception as exc:  # noqa: BLE001
        _last_error = _listen_error(exc)
        error("tg-ws-proxy", f"{_last_error} ({exc})")
    finally:
        pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()
        _async_stop = None


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection((HOST, port), timeout=0.2):
            return True
    except OSError:
        return False


def running() -> bool:
    return _thread is not None and _thread.is_alive() and _port_open(proxy_config.port)


def stop() -> None:
    global _thread
    with _lock:
        pair = _async_stop
        thread = _thread
        if pair is not None and thread is not None:
            loop, stop_event = pair
            loop.call_soon_threadsafe(stop_event.set)
            thread.join(timeout=5)
        _thread = None


def _start_locked() -> str | None:
    global _thread, _last_error
    if running():
        return None
    _last_error = ""
    _thread = threading.Thread(target=_run_thread, daemon=True, name="twowings-tg-ws-proxy")
    _thread.start()
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if _last_error:
            return _last_error
        if _port_open(proxy_config.port):
            info("tg-ws-proxy", f"слушает {HOST}:{proxy_config.port}")
            return None
        if _thread is not None and not _thread.is_alive():
            return _last_error or "Не удалось запустить TG WS Proxy."
        time.sleep(0.05)
    return _last_error or "TG WS Proxy не открыл порт."


def status() -> dict[str, Any]:
    settings = get_settings()
    port = int(settings.tg_ws_proxy_port or DEFAULT_PORT)
    secret = (settings.tg_ws_proxy_secret or "").strip()
    link = telegram_link(port, secret) if len(secret) == 32 else ""
    alive = running()
    return {
        "ok": True,
        "enabled": bool(settings.tg_ws_proxy_enabled),
        "running": alive,
        "port": port,
        "dc_ip": dc_lines(settings.tg_ws_proxy_dc_ip),
        "link": link,
        "error": "" if alive else _last_error,
    }


def apply_settings() -> dict[str, Any]:
    global _last_error
    with _lock:
        settings = reload_settings()
        if not settings.tg_ws_proxy_enabled:
            stop()
            _last_error = ""
            info("tg-ws-proxy", "выключен")
            return status()
        secret = _ensure_secret(settings)
        problem = _apply_upstream(settings, secret)
        if problem:
            _last_error = problem
            return {**status(), "ok": False, "error": problem}
        stop()
        time.sleep(0.3)
        problem = _start_locked()
        payload = status()
        if problem:
            payload["ok"] = False
            payload["error"] = problem
            warn("tg-ws-proxy", problem)
        return payload


def ensure_running() -> None:
    settings = get_settings()
    if settings.tg_ws_proxy_enabled:
        apply_settings()
