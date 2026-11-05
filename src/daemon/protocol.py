"""IPC message types for 2Wings daemon."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

CommandName = Literal[
    "ping",
    "status",
    "start",
    "stop",
    "open_ui",
    "register_gui",
    "test_start",
    "test_stop",
    "test_status",
    "automation_info",
    "automation_get_settings",
    "automation_update_settings",
    "automation_list_strategies",
    "automation_read_log",
    "automation_update_strategies",
    "tg_proxy_status",
    "tg_proxy_apply",
]


@dataclass
class DaemonStatus:
    running: bool
    phase: str
    strategy_name: str
    error: str
    pid: int | None
    tests_running: bool = False


def status_to_dict(status: DaemonStatus) -> dict[str, Any]:
    return {
        "running": status.running,
        "phase": status.phase,
        "strategy_name": status.strategy_name,
        "error": status.error,
        "pid": status.pid,
        "tests_running": status.tests_running,
    }


def status_from_dict(data: dict[str, Any]) -> DaemonStatus:
    return DaemonStatus(
        running=bool(data.get("running")),
        phase=str(data.get("phase") or "idle"),
        strategy_name=str(data.get("strategy_name") or ""),
        error=str(data.get("error") or ""),
        pid=data.get("pid") if isinstance(data.get("pid"), int) else None,
        tests_running=bool(data.get("tests_running")),
    )
