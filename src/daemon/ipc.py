"""Localhost JSON IPC between 2Wings GUI and daemon."""

from __future__ import annotations

import json
import socket
import threading
from typing import Any, Callable

from src.core.debug_log import debug
from src.daemon.protocol import CommandName, DaemonStatus, status_from_dict, status_to_dict

HOST = "127.0.0.1"
PORT = 51731
_TIMEOUT = 2.0
_SLOW_TIMEOUT = 15.0
_UPDATE_TIMEOUT = 300.0
_MAX_REQUEST_BYTES = 64 * 1024
_MAX_RESPONSE_BYTES = 1024 * 1024
_SERVER_CLIENT_TIMEOUT = 20.0


def _send_recv(payload: dict[str, Any], *, timeout: float = _TIMEOUT) -> dict[str, Any]:
    data = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
    with socket.create_connection((HOST, PORT), timeout=timeout) as sock:
        sock.sendall(data)
        sock.shutdown(socket.SHUT_WR)
        chunks: list[bytes] = []
        while True:
            part = sock.recv(4096)
            if not part:
                break
            chunks.append(part)
            if sum(map(len, chunks)) > _MAX_RESPONSE_BYTES:
                raise OSError("Ответ daemon превышает допустимый размер.")
    raw = b"".join(chunks).decode("utf-8").strip()
    if not raw:
        return {"ok": False, "error": "Пустой ответ daemon."}
    try:
        response = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise OSError("Daemon вернул некорректный JSON.") from exc
    if not isinstance(response, dict):
        raise OSError("Daemon вернул ответ неизвестного формата.")
    return response


def is_daemon_running() -> bool:
    try:
        response = _send_recv({"cmd": "ping"})
        return bool(response.get("ok"))
    except OSError:
        return False


def daemon_status() -> DaemonStatus | None:
    try:
        response = _send_recv({"cmd": "status"})
        if not response.get("ok"):
            return None
        return status_from_dict(response.get("status") or {})
    except OSError:
        return None


def daemon_start(strategy_id: str | None = None) -> tuple[bool, str]:
    payload: dict[str, str] = {"cmd": "start"}
    if strategy_id:
        payload["strategy_id"] = strategy_id
    try:
        response = _send_recv(payload, timeout=_SLOW_TIMEOUT)
        return bool(response.get("ok")), str(response.get("message") or response.get("error") or "")
    except TimeoutError:
        return False, "Превышено время ожидания ответа daemon при запуске zapret."
    except OSError as exc:
        if "timed out" in str(exc).lower():
            return False, "Превышено время ожидания ответа daemon при запуске zapret."
        return False, str(exc)


def daemon_stop() -> tuple[bool, str]:
    try:
        response = _send_recv({"cmd": "stop"}, timeout=_SLOW_TIMEOUT)
        return bool(response.get("ok")), str(response.get("message") or response.get("error") or "")
    except TimeoutError:
        return False, "Превышено время ожидания ответа daemon при остановке zapret."
    except OSError as exc:
        if "timed out" in str(exc).lower():
            return False, "Превышено время ожидания ответа daemon при остановке zapret."
        return False, str(exc)


def daemon_open_ui() -> tuple[bool, str]:
    try:
        response = _send_recv({"cmd": "open_ui"})
        return bool(response.get("ok")), str(response.get("message") or response.get("error") or "")
    except OSError as exc:
        return False, str(exc)


def daemon_test_start(version: str, test_type: str, strategy_ids: list[str]) -> tuple[bool, str]:
    try:
        response = _send_recv(
            {
                "cmd": "test_start",
                "version": version,
                "test_type": test_type,
                "strategy_ids": strategy_ids,
            },
            timeout=_SLOW_TIMEOUT,
        )
        return bool(response.get("ok")), str(response.get("message") or response.get("error") or "")
    except OSError as exc:
        return False, str(exc)


def daemon_test_stop() -> tuple[bool, str]:
    try:
        response = _send_recv({"cmd": "test_stop"}, timeout=_SLOW_TIMEOUT)
        return bool(response.get("ok")), str(response.get("message") or response.get("error") or "")
    except OSError as exc:
        return False, str(exc)


def daemon_test_status() -> dict[str, Any]:
    try:
        response = _send_recv({"cmd": "test_status"})
    except OSError as exc:
        return {"ok": False, "running": False, "error": str(exc)}
    return response


def daemon_automation_info() -> dict[str, Any]:
    try:
        return _send_recv({"cmd": "automation_info"})
    except OSError as exc:
        return {"ok": False, "error": str(exc)}


def daemon_get_settings() -> dict[str, Any]:
    try:
        return _send_recv({"cmd": "automation_get_settings"})
    except OSError as exc:
        return {"ok": False, "error": str(exc)}


def daemon_update_settings(values: dict[str, Any]) -> dict[str, Any]:
    try:
        return _send_recv({"cmd": "automation_update_settings", "values": values})
    except OSError as exc:
        return {"ok": False, "error": str(exc)}


def daemon_list_strategies() -> dict[str, Any]:
    try:
        return _send_recv({"cmd": "automation_list_strategies"})
    except OSError as exc:
        return {"ok": False, "error": str(exc)}


def daemon_read_log(limit: int = 100) -> dict[str, Any]:
    try:
        return _send_recv({"cmd": "automation_read_log", "limit": limit})
    except OSError as exc:
        return {"ok": False, "error": str(exc)}


def daemon_tg_proxy_status() -> dict[str, Any]:
    try:
        return _send_recv({"cmd": "tg_proxy_status"})
    except OSError as exc:
        return {"ok": False, "running": False, "error": str(exc)}


def daemon_tg_proxy_apply() -> dict[str, Any]:
    try:
        return _send_recv({"cmd": "tg_proxy_apply"}, timeout=_SLOW_TIMEOUT)
    except OSError as exc:
        return {"ok": False, "running": False, "error": str(exc)}


def daemon_update_strategies() -> dict[str, Any]:
    try:
        return _send_recv(
            {"cmd": "automation_update_strategies"},
            timeout=_UPDATE_TIMEOUT,
        )
    except OSError as exc:
        return {"ok": False, "error": str(exc)}


def register_gui_with_daemon(pid: int | None = None) -> None:
    payload: dict[str, Any] = {"cmd": "register_gui"}
    if pid is not None:
        payload["pid"] = pid
    try:
        _send_recv(payload)
    except OSError:
        pass


class IpcServer:
    def __init__(self, handler: Callable[[CommandName, dict[str, Any]], dict[str, Any]]) -> None:
        self._handler = handler
        self._thread: threading.Thread | None = None
        self._running = False
        self._sock: socket.socket | None = None
        self._ready = threading.Event()
        self._start_error: OSError | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._running = True
        self._ready.clear()
        self._start_error = None
        self._thread = threading.Thread(target=self._serve, daemon=True, name="twowings-ipc")
        self._thread.start()
        if not self._ready.wait(3.0):
            self._running = False
            raise TimeoutError("IPC daemon не успел запуститься.")
        if self._start_error is not None:
            self._running = False
            raise self._start_error

    def stop(self) -> None:
        self._running = False
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass

    def _serve(self) -> None:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            server.bind((HOST, PORT))
            server.listen(5)
        except OSError as exc:
            self._start_error = exc
            self._ready.set()
            server.close()
            return
        server.settimeout(1.0)
        self._sock = server
        self._ready.set()
        debug("daemon", f"IPC listening on {HOST}:{PORT}")
        while self._running:
            try:
                conn, _addr = server.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            threading.Thread(target=self._handle_client, args=(conn,), daemon=True).start()

    def _handle_client(self, conn: socket.socket) -> None:
        try:
            conn.settimeout(_SERVER_CLIENT_TIMEOUT)
            chunks: list[bytes] = []
            size = 0
            while True:
                part = conn.recv(4096)
                if not part:
                    break
                size += len(part)
                if size > _MAX_REQUEST_BYTES:
                    conn.sendall(b'{"ok": false, "error": "request too large"}\n')
                    return
                chunks.append(part)
            raw = b"".join(chunks).decode("utf-8").strip()
            if not raw:
                conn.sendall(b'{"ok": false, "error": "empty request"}\n')
                return
            request = json.loads(raw)
            if not isinstance(request, dict):
                conn.sendall(b'{"ok": false, "error": "invalid request"}\n')
                return
            cmd = str(request.get("cmd") or "ping")
            response = self._handler(cmd, request)  # type: ignore[arg-type]
            conn.sendall((json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            try:
                conn.sendall(
                    (json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False) + "\n").encode("utf-8")
                )
            except OSError:
                pass
        finally:
            conn.close()


def build_status_response() -> dict[str, Any]:
    from src.kernel.public import get_runtime_status

    status = get_runtime_status()
    payload = status_to_dict(
        DaemonStatus(
            running=status.running,
            phase=status.phase.value,
            strategy_name=status.strategy_name or "",
            error=status.error or "",
            pid=status.pid,
            tests_running=status.tests_running,
        )
    )
    return {"ok": True, "status": payload}
